#!/usr/bin/env python3
"""
Transactional Outbox Forwarder Daemon (Instance 1)
Wakes up via PostgreSQL LISTEN/NOTIFY with 5-second unnotified fallback polling.
Uses FOR UPDATE SKIP LOCKED for multi-worker safe concurrency.
Implements Dead-Letter Queue (DLQ) to prevent Head-of-Line blocking on poison pills.
Guarantees sequential, in-order HTTP delivery across the Network Security Gateway.
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timezone
import requests
import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FORWARDER] %(levelname)s: %(message)s")

DB_URI = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres-instance1:5432/postgres")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://instance2-gateway:8082/api/v1/replicate")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
TIMEOUT_SEC = 4.0

SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=50)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

BACKPRESSURE_FAILURES = 0
LAST_MAINTENANCE = 0.0

def compact_outbox(conn) -> int:
    """
    Issue 7: Outbox Compaction during backpressure or gateway outages.
    Collapses intermediate pending updates for the same alert_id, retaining only the latest ID.
    Because Instance 2 performs version-checked atomic upsert, older pending versions are redundant.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM alerts_outbox a
                WHERE a.status = 'PENDING'
                  AND EXISTS (
                      SELECT 1 FROM alerts_outbox b
                      WHERE b.alert_id = a.alert_id
                        AND b.status = 'PENDING'
                        AND b.id > a.id
                  );
            """)
            deleted = cur.rowcount
            if deleted > 0:
                conn.commit()
                logging.info(f"🧹 [OUTBOX COMPACTION] Purged {deleted} obsolete pending updates from outbox during backpressure.")
            return deleted
    except Exception as e:
        conn.rollback()
        logging.warning(f"Failed to compact outbox: {e}")
        return 0

def prune_dlq(conn) -> int:
    """
    Issue 7: Prunes dead-letter queue entries older than 7 days to prevent unbounded growth.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts_dlq WHERE failed_at < NOW() - INTERVAL '7 days';")
            deleted = cur.rowcount
            if deleted > 0:
                conn.commit()
                logging.info(f"🧹 [DLQ RETENTION] Pruned {deleted} expired DLQ records.")
            return deleted
    except Exception as e:
        conn.rollback()
        logging.warning(f"Failed to prune DLQ: {e}")
        return 0

def heartbeat_emitter_thread():
    """
    Issue 19: Meta-Monitoring Synthetic Heartbeat.
    Emits a synthetic heartbeat every 30 seconds into alerts table on Instance 1,
    which triggers an outbox row and syncs across the gateway to Instance 2.
    """
    logging.info("💓 Starting Synthetic Heartbeat Emitter (interval: 30s)...")
    time.sleep(5.0)
    while True:
        try:
            with psycopg.connect(DB_URI, autocommit=True, row_factory=dict_row) as hb_conn:
                while True:
                    now = datetime.now(timezone.utc)
                    with hb_conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO alerts (
                                identifier, node, alert_key, severity, status, summary,
                                tally, version, first_occurrence, last_occurrence, last_state_change,
                                custom_fields
                            ) VALUES (
                                'system:pipeline_heartbeat', 'system-monitor', 'replication_heartbeat',
                                'INFO', 'OPEN', 'Instance 1 Cross-Domain Pipeline Heartbeat',
                                1, 1, %s, %s, %s,
                                '{"source": "instance1-meta-monitor", "type": "synthetic_heartbeat"}'::jsonb
                            )
                            ON CONFLICT (identifier) DO UPDATE SET
                                tally = alerts.tally + 1,
                                version = alerts.version + 1,
                                last_occurrence = EXCLUDED.last_occurrence,
                                summary = 'Instance 1 Cross-Domain Pipeline Heartbeat'
                            RETURNING version, tally;
                        """, (now, now, now))
                        res = cur.fetchone()
                        if res and res["version"] % 5 == 0:
                            logging.info(f"💓 [HEARTBEAT] Emitted pipeline heartbeat (version: {res['version']}, tally: {res['tally']})")
                    time.sleep(30.0)
        except Exception as e:
            logging.warning(f"Heartbeat emitter error: {e}. Retrying in 10s...")
            time.sleep(10.0)

def process_outbox(conn) -> bool:
    global BACKPRESSURE_FAILURES
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, alert_id, operation, payload, retry_count
            FROM alerts_outbox
            WHERE status = 'PENDING'
            ORDER BY id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED;
        """, (BATCH_SIZE,))
        rows = cur.fetchall()

        if not rows:
            conn.rollback()
            return False

        batch_payload = [row["payload"] for row in rows]
        all_ids = [row["id"] for row in rows]

        try:
            resp = SESSION.post(
                GATEWAY_URL,
                json=batch_payload,
                timeout=TIMEOUT_SEC,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code in (200, 201):
                BACKPRESSURE_FAILURES = 0
                cur.execute("DELETE FROM alerts_outbox WHERE id = ANY(%s);", (all_ids,))
                conn.commit()
                return len(rows) == BATCH_SIZE
            elif resp.status_code == 503:
                BACKPRESSURE_FAILURES += 1
                logging.warning(f"⚠️ Gateway unavailable (HTTP 503, failure count: {BACKPRESSURE_FAILURES}). Backing off.")
                conn.rollback()
                if BACKPRESSURE_FAILURES % 3 == 0:
                    compact_outbox(conn)
                time.sleep(1.0)
                return False
        except requests.RequestException as e:
            BACKPRESSURE_FAILURES += 1
            logging.warning(f"🔌 Gateway connectivity error: {e} (failure count: {BACKPRESSURE_FAILURES}). Backing off.")
            conn.rollback()
            if BACKPRESSURE_FAILURES % 3 == 0:
                compact_outbox(conn)
            time.sleep(1.0)
            return False

        # Fallback to row-by-row if batch had rejection or poison pills (4xx)
        successful_ids = []
        dlq_items = []
        gateway_unavailable = False

        for row in rows:
            row_id = row["id"]
            alert_id = row["alert_id"]
            payload = row["payload"]

            try:
                r = SESSION.post(
                    GATEWAY_URL,
                    json=payload,
                    timeout=TIMEOUT_SEC,
                    headers={"Content-Type": "application/json"}
                )
                if r.status_code in (200, 201):
                    successful_ids.append(row_id)
                elif 400 <= r.status_code < 500:
                    reason = f"Gateway HTTP {r.status_code}: {r.text[:200]}"
                    logging.error(f"☠️ [POISON PILL] Row {row_id} (Alert: {alert_id}) rejected: {reason}. Moving to DLQ.")
                    dlq_items.append((row_id, alert_id, json.dumps(payload), reason))
                else:
                    gateway_unavailable = True
                    break
            except requests.RequestException:
                gateway_unavailable = True
                break

        if successful_ids:
            cur.execute("DELETE FROM alerts_outbox WHERE id = ANY(%s);", (successful_ids,))
            logging.info(f"✅ Dispatched and purged {len(successful_ids)} alerts across gateway.")

        for dlq_id, dlq_alert_id, dlq_payload, dlq_reason in dlq_items:
            cur.execute("""
                INSERT INTO alerts_dlq (outbox_id, alert_id, payload, reason)
                VALUES (%s, %s, %s::jsonb, %s);
            """, (dlq_id, dlq_alert_id, dlq_payload, dlq_reason))
            cur.execute("DELETE FROM alerts_outbox WHERE id = %s;", (dlq_id,))

        conn.commit()

        if gateway_unavailable:
            time.sleep(1.0)
            return False

        return len(rows) == BATCH_SIZE

def run_daemon():
    global LAST_MAINTENANCE
    logging.info("🚀 Starting Outbox Forwarder Daemon...")
    logging.info(f"  • DB: {DB_URI}")
    logging.info(f"  • Gateway Target: {GATEWAY_URL}")

    # Issue 19: Start Synthetic Heartbeat Emitter Thread
    hb_thread = threading.Thread(target=heartbeat_emitter_thread, daemon=True)
    hb_thread.start()

    while True:
        try:
            with psycopg.connect(DB_URI, autocommit=False, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("LISTEN alert_outbox_channel;")
                conn.commit()
                logging.info("🎧 Listening on PostgreSQL channel 'alert_outbox_channel'...")

                while True:
                    # 1. Drain all pending records
                    while process_outbox(conn):
                        pass

                    # 2. Periodic Maintenance (DLQ prune & Compaction check every 60s)
                    now_t = time.time()
                    if now_t - LAST_MAINTENANCE > 60.0:
                        prune_dlq(conn)
                        compact_outbox(conn)
                        LAST_MAINTENANCE = now_t

                    # 3. Ensure connection is out of transaction, then wait on notifies
                    conn.rollback()
                    for notify in conn.notifies(timeout=5.0):
                        break

        except psycopg.OperationalError as e:
            logging.warning(f"Database connection interrupted: {e}. Reconnecting in 3s...")
            time.sleep(3.0)
        except Exception as e:
            logging.error(f"Unexpected forwarder error: {e}", exc_info=True)
            time.sleep(2.0)

if __name__ == "__main__":
    run_daemon()
