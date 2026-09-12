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

def process_outbox(conn) -> bool:
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
                cur.execute("DELETE FROM alerts_outbox WHERE id = ANY(%s);", (all_ids,))
                conn.commit()
                return len(rows) == BATCH_SIZE
            elif resp.status_code == 503:
                logging.warning("⚠️ Gateway unavailable (HTTP 503). Backing off.")
                conn.rollback()
                time.sleep(1.0)
                return False
        except requests.RequestException as e:
            logging.warning(f"🔌 Gateway connectivity error: {e}. Backing off.")
            conn.rollback()
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
    logging.info("🚀 Starting Outbox Forwarder Daemon...")
    logging.info(f"  • DB: {DB_URI}")
    logging.info(f"  • Gateway Target: {GATEWAY_URL}")

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

                    # 2. Ensure connection is out of transaction, then wait on notifies
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
