#!/usr/bin/env python3
"""
Security Gateway & Instance 2 Ingestion API (FastAPI)
Acts as the Network Security Boundary and Secondary Replication Sink.
Enforces Strict JSON Envelope Validation, Tolerant Reader Pattern, and
Optimistic Version-Checked Atomic UPSERT to eliminate Zombie Alerts & State Drift.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INSTANCE2-GW] %(levelname)s: %(message)s")

DB_URI = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres-instance2:5432/postgres")

app = FastAPI(title="Security Gateway & Instance 2 Ingestion API", version="1.0.0")

# Simulation state to test network gateway outages & backpressure
GATEWAY_ENABLED = True

import queue
from contextlib import contextmanager

class SimplePool:
    def __init__(self, uri: str, min_conn: int = 5, max_conn: int = 25):
        self.uri = uri
        self.max_conn = max_conn
        self.pool = queue.Queue(maxsize=max_conn)
        for _ in range(min_conn):
            self.pool.put(self._create_conn())

    def _create_conn(self):
        return psycopg.connect(self.uri, autocommit=True, row_factory=dict_row)

    def get(self):
        try:
            conn = self.pool.get_nowait()
            if conn.closed:
                conn = self._create_conn()
            return conn
        except queue.Empty:
            return self._create_conn()

    def put(self, conn):
        if conn.closed:
            return
        try:
            if not conn.autocommit:
                conn.rollback()
            self.pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

db_pool = SimplePool(DB_URI, min_conn=5, max_conn=25)

@contextmanager
def get_db():
    conn = db_pool.get()
    try:
        yield conn
    finally:
        db_pool.put(conn)

# -------------------------------------------------------------
# Standardized JSON Envelope Schema
# -------------------------------------------------------------

class ReplicatedEnvelope(BaseModel):
    operation: str
    identifier: str
    node: str
    alert_key: str
    severity: str
    status: str
    summary: str
    tally: int
    version: int
    first_occurrence: Optional[str] = None
    last_occurrence: Optional[str] = None
    last_state_change: Optional[str] = None
    is_flapping: Optional[bool] = False
    custom_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)
    deleted_at: Optional[str] = None

# -------------------------------------------------------------
# Gateway Endpoints
# -------------------------------------------------------------

def _replicate_one_item(cur, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Strict Envelope Validation
    required_fields = ["operation", "identifier", "node", "severity", "status", "version", "tally"]
    for rf in required_fields:
        if rf not in payload or payload[rf] is None:
            logging.error(f"❌ [GATEWAY REJECTION] Missing required envelope field: '{rf}' in payload: {payload}")
            raise HTTPException(status_code=422, detail=f"Strict Schema Validation Failed: missing '{rf}'")

    ident = payload["identifier"]
    op = payload["operation"]
    ver = payload["version"]
    sev = payload["severity"]
    stat = payload["status"]
    custom = json.dumps(payload.get("custom_fields", {}))
    now = datetime.now(timezone.utc)

    first_occ = payload.get("first_occurrence") or now
    last_occ = payload.get("last_occurrence") or now
    last_change = payload.get("last_state_change") or now
    deleted_at = payload.get("deleted_at")

    # Atomic UPSERT with Optimistic Concurrency Check:
    # Only update if incoming version is >= existing version!
    # Prevents race conditions, network retries, and out-of-order zombie alerts!
    cur.execute("""
        INSERT INTO alerts (
            identifier, node, alert_key, severity, status, summary,
            tally, version, first_occurrence, last_occurrence, last_state_change,
            is_flapping, custom_fields, deleted_at, replicated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, NOW()
        )
        ON CONFLICT (identifier) DO UPDATE SET
            node = EXCLUDED.node,
            alert_key = EXCLUDED.alert_key,
            severity = EXCLUDED.severity,
            status = EXCLUDED.status,
            summary = EXCLUDED.summary,
            tally = EXCLUDED.tally,
            version = EXCLUDED.version,
            last_occurrence = EXCLUDED.last_occurrence,
            last_state_change = EXCLUDED.last_state_change,
            is_flapping = EXCLUDED.is_flapping,
            custom_fields = EXCLUDED.custom_fields,
            deleted_at = EXCLUDED.deleted_at,
            replicated_at = NOW()
        WHERE EXCLUDED.version >= alerts.version
        RETURNING (xmax = 0) AS was_inserted, version;
    """, (
        ident, payload["node"], payload.get("alert_key", "default"), sev, stat, payload.get("summary", ""),
        payload["tally"], ver, first_occ, last_occ, last_change,
        payload.get("is_flapping", False), custom, deleted_at
    ))
    res = cur.fetchone()

    if res:
        was_inserted, applied_ver = res["was_inserted"], res["version"]
        action = "inserted" if was_inserted else "updated"
        if applied_ver % 500 == 0:
            logging.info(f"📥 [REPLICATED SAMPLE] {ident} | Action: {action} | Version: {applied_ver} | Status: {stat}")
    else:
        # WHERE EXCLUDED.version >= alerts.version evaluated to false (Out-of-order stale update dropped)
        logging.warning(f"🛡️ [OUT-OF-ORDER DROPPED] Discarded stale version {ver} for {ident}. Newer version already exists.")
        return {"status": "dropped_stale_version", "identifier": ident}

    # Record in replication audit log
    cur.execute("""
        INSERT INTO alerts_replication_log (identifier, operation, version, severity, status)
        VALUES (%s, %s, %s, %s, %s);
    """, (ident, op, ver, sev, stat))

    return {"status": "success", "identifier": ident, "version": ver}

@app.post("/api/v1/replicate", status_code=status.HTTP_200_OK)
def replicate_alert(payload: Union[Dict[str, Any], List[Dict[str, Any]]]):
    global GATEWAY_ENABLED
    if not GATEWAY_ENABLED:
        logging.warning("🛑 [GATEWAY OUTAGE] Gateway is currently down for maintenance. Rejecting with HTTP 503.")
        raise HTTPException(status_code=503, detail="Security Gateway Link Severed / Maintenance Mode")

    items = payload if isinstance(payload, list) else [payload]
    results = []
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for item in items:
                    res = _replicate_one_item(cur, item)
                    results.append(res)

    return results if isinstance(payload, list) else results[0]

# -------------------------------------------------------------
# Secondary Query API (Read-Only GUI for Secondary Site)
# -------------------------------------------------------------

@app.get("/api/v1/alerts")
def list_secondary_alerts():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alerts ORDER BY last_occurrence DESC;")
            return cur.fetchall()

@app.get("/api/v1/alerts/{identifier}")
def get_secondary_alert(identifier: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alerts WHERE identifier = %s;", (identifier,))
            alert = cur.fetchone()
            if not alert:
                raise HTTPException(status_code=404, detail="Alert not found in secondary database")
            return alert

@app.get("/api/v1/audit-log")
def get_audit_log(limit: int = 50):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alerts_replication_log ORDER BY id DESC LIMIT %s;", (limit,))
            return cur.fetchall()

# -------------------------------------------------------------
# Simulation Controls
# -------------------------------------------------------------

@app.post("/admin/gateway-toggle")
def toggle_gateway(enabled: bool):
    global GATEWAY_ENABLED
    GATEWAY_ENABLED = enabled
    state_str = "ONLINE (Accepting Traffic)" if enabled else "OFFLINE (Severed / Backlog Simulation)"
    logging.info(f"🔌 [ADMIN TOGGLE] Security Gateway is now: {state_str}")
    return {"gateway_enabled": GATEWAY_ENABLED, "state": state_str}

@app.get("/healthz")
def healthz():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            return {"status": "healthy", "database": "connected", "gateway_enabled": GATEWAY_ENABLED}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
