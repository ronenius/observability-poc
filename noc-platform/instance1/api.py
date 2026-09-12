#!/usr/bin/env python3
"""
Instance 1 Ingestion and Headless CRUD API (FastAPI)
Handles Deduplication, Auto-Clearing, Flap Detection, and NOC Operator Actions.
All state changes trigger PostgreSQL Outbox updates automatically via SQL Triggers.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
from fastapi import FastAPI, HTTPException, Query, Response, Request, status
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
DB_URI = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres-instance1:5432/postgres")

app = FastAPI(title="NOC Alert Engine - Instance 1 API", version="1.0.0")

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# Pydantic Schemas
# -------------------------------------------------------------

class IngestEvent(BaseModel):
    model_config = {"extra": "ignore"}
    identifier: Optional[str] = None
    node: str = "unknown-node"
    alert_key: str = "default-check"
    severity: str = "INFO"  # CRITICAL, WARNING, INFO, CLEAR
    summary: str = "No summary provided"
    custom_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AlertPatch(BaseModel):
    status: Optional[str] = None       # OPEN, ACKNOWLEDGED, RESOLVED, PURGED
    severity: Optional[str] = None
    summary: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

# -------------------------------------------------------------
# Ingestion API (Called by Vector or Direct Webhooks)
# -------------------------------------------------------------

def _process_one_event(cur, event: IngestEvent) -> Dict[str, Any]:
    ident = event.identifier or f"{event.node}:{event.alert_key}"
    sev = event.severity.upper()
    now = datetime.now(timezone.utc)
    custom_dict = event.custom_fields or {}

    # Check existing alert
    cur.execute("SELECT * FROM alerts WHERE identifier = %s", (ident,))
    existing = cur.fetchone()

    if not existing:
        # Initial Insertion
        new_status = "RESOLVED" if sev == "CLEAR" else "OPEN"
        cur.execute("""
            INSERT INTO alerts (
                identifier, node, alert_key, severity, status, summary, 
                tally, version, first_occurrence, last_occurrence, last_state_change,
                custom_fields
            ) VALUES (%s, %s, %s, %s, %s, %s, 1, 1, %s, %s, %s, %s)
            RETURNING *;
        """, (
            ident, event.node, event.alert_key, sev, new_status, event.summary,
            now, now, now, json.dumps(custom_dict)
        ))
        created = cur.fetchone()
        if created["id"] % 500 == 0:
            logging.info(f"✨ [NEW ALERT SAMPLE] {ident} | Severity: {sev} | Status: {new_status}")
        return {"action": "created", "alert": created}

    # Existing Alert: Handle Deduplication, Auto-Clear, and Flap Detection
    current_sev = existing["severity"]
    current_status = existing["status"]
    flap_count = existing["flap_count"]
    is_flapping = existing["is_flapping"]
    last_state_change = existing["last_state_change"]

    # Flap Detection Logic:
    time_since_change = (now - last_state_change).total_seconds()
    if sev != current_sev:
        if time_since_change < 30.0:
            flap_count += 1
            if flap_count >= 4:
                is_flapping = True
                logging.warning(f"⚠️ [FLAP DETECTED] Alert {ident} is flapping! (Transitions: {flap_count})")
        else:
            flap_count = 1
            is_flapping = False

    # Anti-Jitter Dampening:
    if is_flapping and sev == "CLEAR":
        cur.execute("""
            UPDATE alerts SET 
                tally = tally + 1,
                version = version + 1,
                last_occurrence = %s,
                flap_count = %s,
                is_flapping = %s
            WHERE identifier = %s
            RETURNING *;
        """, (now, flap_count, is_flapping, ident))
        updated = cur.fetchone()
        return {"action": "flapping_dampened", "alert": updated}

    # Normal State Transition
    new_status = "RESOLVED" if sev == "CLEAR" else ("OPEN" if current_status == "RESOLVED" else current_status)
    
    # Merge custom fields
    merged_custom = existing["custom_fields"] or {}
    merged_custom.update(custom_dict)

    cur.execute("""
        UPDATE alerts SET
            severity = %s,
            status = %s,
            summary = %s,
            tally = tally + 1,
            version = version + 1,
            last_occurrence = %s,
            last_state_change = CASE WHEN severity != %s THEN %s ELSE last_state_change END,
            flap_count = %s,
            is_flapping = %s,
            custom_fields = %s
        WHERE identifier = %s
        RETURNING *;
    """, (
        sev, new_status, event.summary, now, sev, now,
        flap_count, is_flapping, json.dumps(merged_custom), ident
    ))
    updated = cur.fetchone()
    if updated["version"] % 500 == 0:
        logging.info(f"🔄 [UPDATED ALERT SAMPLE] {ident} | Version: {updated['version']} | Tally: {updated['tally']}")
    return {"action": "updated", "alert": updated}

@app.post("/api/v1/ingest", status_code=status.HTTP_200_OK)
def ingest_alert(payload: Union[Dict[str, Any], List[Dict[str, Any]]]):
    items = payload if isinstance(payload, list) else [payload]
    results = []
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for item in items:
                    ev = IngestEvent.model_validate(item) if isinstance(item, dict) else item
                    results.append(_process_one_event(cur, ev))
    return results if isinstance(payload, list) else results[0]

# -------------------------------------------------------------
# Headless CRUD API (For NOC Operator GUI)
# -------------------------------------------------------------

@app.get("/api/v1/alerts")
def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    node: Optional[str] = None,
    search: Optional[str] = None,
    minutes: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 250,
    offset: int = 0
):
    query = "SELECT * FROM alerts WHERE deleted_at IS NULL"
    params = []
    if status:
        if status.upper() == "ACTIVE":
            query += " AND status != 'RESOLVED'"
        else:
            query += " AND status = %s"
            params.append(status.upper())
    if severity:
        query += " AND severity = %s"
        params.append(severity.upper())
    if node:
        query += " AND node = %s"
        params.append(node)
    if search:
        query += " AND (identifier ILIKE %s OR node ILIKE %s OR alert_key ILIKE %s OR summary ILIKE %s)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern, pattern])
    if minutes is not None and minutes > 0:
        query += " AND last_occurrence >= NOW() - (%s || ' minutes')::interval"
        params.append(str(minutes))
    elif since is not None:
        query += " AND last_occurrence >= %s::timestamptz"
        params.append(since)
    if until is not None:
        query += " AND last_occurrence <= %s::timestamptz"
        params.append(until)

    query += " ORDER BY last_occurrence DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

@app.get("/api/v1/metrics/summary")
def get_metrics_summary(minutes: Optional[int] = None):
    time_filter = ""
    params = []
    if minutes is not None and minutes > 0:
        time_filter = " AND last_occurrence >= NOW() - (%s || ' minutes')::interval"
        params.append(str(minutes))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    count(*) as total_alerts,
                    count(*) FILTER (WHERE status != 'RESOLVED') as active_alerts,
                    count(*) FILTER (WHERE severity = 'CRITICAL' AND status != 'RESOLVED') as critical_alerts,
                    count(*) FILTER (WHERE severity = 'MAJOR' AND status != 'RESOLVED') as major_alerts,
                    count(*) FILTER (WHERE severity = 'WARNING' AND status != 'RESOLVED') as warning_alerts,
                    count(*) FILTER (WHERE is_flapping = TRUE) as flapping_alerts,
                    coalesce(sum(tally), 0) as total_events_tally,
                    count(*) FILTER (WHERE status = 'ACKNOWLEDGED') as acked_alerts,
                    count(*) FILTER (WHERE status = 'RESOLVED') as resolved_alerts
                FROM alerts 
                WHERE deleted_at IS NULL {time_filter};
            """, params)
            return cur.fetchone()

@app.get("/api/v1/alerts/{identifier}")
def get_alert(identifier: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alerts WHERE identifier = %s AND deleted_at IS NULL", (identifier,))
            alert = cur.fetchone()
            if not alert:
                raise HTTPException(status_code=404, detail="Alert not found")
            return alert

@app.patch("/api/v1/alerts/{identifier}")
def patch_alert(identifier: str, patch: AlertPatch):
    """Allows NOC operator or external systems to acknowledge, reassign, annotate, or change severity."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alerts WHERE identifier = %s AND deleted_at IS NULL", (identifier,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Alert not found")

            new_status = patch.status.upper() if patch.status else existing["status"]
            new_severity = patch.severity.upper() if patch.severity else existing["severity"]
            new_summary = patch.summary if patch.summary is not None else existing["summary"]

            merged_custom = existing["custom_fields"] or {}
            if patch.custom_fields:
                merged_custom.update(patch.custom_fields)

            now = datetime.now(timezone.utc)
            cur.execute("""
                UPDATE alerts SET
                    status = %s,
                    severity = %s,
                    summary = %s,
                    version = version + 1,
                    last_state_change = %s,
                    custom_fields = %s
                WHERE identifier = %s
                RETURNING *;
            """, (new_status, new_severity, new_summary, now, json.dumps(merged_custom), identifier))
            updated = cur.fetchone()
            logging.info(f"✍️ [OPERATOR PATCH] {identifier} | Status: {new_status} | Version: {updated['version']}")
            return updated

@app.delete("/api/v1/alerts/{identifier}")
def delete_alert(identifier: str):
    """Performs soft-delete (marking as PURGED) and triggers tombstone outbox event."""
    with get_db() as conn:
        with conn.cursor() as cur:
            now = datetime.now(timezone.utc)
            cur.execute("""
                UPDATE alerts SET
                    status = 'PURGED',
                    deleted_at = %s,
                    version = version + 1
                WHERE identifier = %s AND deleted_at IS NULL
                RETURNING *;
            """, (now, identifier))
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(status_code=404, detail="Alert not found")
            logging.info(f"🗑️ [SOFT DELETE] {identifier} marked as PURGED (version: {deleted['version']})")
            return {"status": "deleted", "identifier": identifier}

@app.get("/healthz")
def healthz():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            return {"status": "healthy", "database": "connected"}

@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def serve_ui():
    static_file = "/app/static/index.html"
    if os.path.exists(static_file):
        with open(static_file, "r") as f:
            return f.read()
    return "<h2>NOC Alert Platform Engine API is Running.</h2><p>Access the Web UI at port 8080 or mount static assets.</p>"

@app.get("/style.css")
def serve_css():
    css_file = "/app/static/style.css"
    if os.path.exists(css_file):
        return FileResponse(css_file, media_type="text/css")
    return Response(status_code=404)

@app.get("/app.js")
def serve_js():
    js_file = "/app/static/app.js"
    if os.path.exists(js_file):
        return FileResponse(js_file, media_type="application/javascript")
    return Response(status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
