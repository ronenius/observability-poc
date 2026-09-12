#!/usr/bin/env python3
"""
Netcool/OMNIbus Alternative - 1,000 DISTINCT Alerts/Sec Stress Test (2 Minutes)
================================================================================
Target:
  • Rate: 1,000 alerts/second (100% DISTINCT alerts, zero deduplication)
  • Duration: 2 minutes (120 seconds) = 120,000 total distinct events
  • Database Target:
      - DB1 alerts table count must reach exactly 120,000 rows
      - DB2 alerts table count must reach exactly 120,000 rows (100% replication parity)
      - Every alert has tally=1, version=1
  • Telemetry:
      - Continuous monitoring of container CPU & RAM across all 6 microservices
      - Outbox backlog queue depth
      - End-to-end drain time to zero backlog
"""

import os
import sys
import time
import json
import random
import threading
import subprocess
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests
import psycopg
from psycopg.rows import dict_row

VECTOR_URL = os.getenv("VECTOR_URL", "http://192.168.194.187:9000")
DB1_URI = os.getenv("DATABASE_URL_1", "postgresql://postgres:postgres@192.168.194.162:5432/postgres")
DB2_URI = os.getenv("DATABASE_URL_2", "postgresql://postgres:postgres@192.168.194.154:5432/postgres")

DURATION_SECONDS = 120       # 2 minutes
TARGET_EPS = 1000            # 1,000 alerts per second
BATCH_SIZE = 10              # 10 alerts per HTTP POST
DISPATCHES_PER_SEC = TARGET_EPS // BATCH_SIZE  # 100 HTTP POSTs per second
INTERVAL = 1.0 / DISPATCHES_PER_SEC            # 0.01s (10ms) per dispatch

# Terminal Styling
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
C_MAGENTA = "\033[35m"

stop_event = threading.Event()
metrics_lock = threading.Lock()
telemetry_data = []

stats = {
    "alerts_sent": 0,
    "http_success": 0,
    "http_error": 0,
    "latencies_ms": [],
    "start_time": 0.0,
    "end_send_time": 0.0,
    "drain_finish_time": 0.0,
    "peak_outbox_backlog": 0,
    "peak_cpu": {},
    "peak_mem": {},
}

SEVERITIES = ["CRITICAL", "MAJOR", "WARNING", "MINOR"]
CHECKS = ["BGP_Neighbor_Down", "OOM_Killed", "Disk_Full", "Core_Dump", "Interface_Flap", "CPU_Throttling"]

def generate_distinct_batch(batch_size: int, seq_offset: int) -> list:
    """Generate 100% distinct alerts. Every alert has a globally unique node and identifier."""
    batch = []
    for i in range(batch_size):
        seq = seq_offset + i
        node = f"dist-node-{seq:07d}"
        check = CHECKS[seq % len(CHECKS)]
        sev = SEVERITIES[seq % len(SEVERITIES)]
        batch.append({
            "node": node,
            "alert_key": check,
            "severity": sev,
            "summary": f"Distinct unique event on {node} (seq={seq})",
            "environment": "production",
            "datacenter": f"dc-{seq % 10}",
            "cluster": f"k8s-cluster-{seq % 20}",
            "custom_fields": {
                "source": "distinct-stress-test",
                "seq_id": seq,
                "created_ts": time.time()
            }
        })
    return batch

def get_container_stats():
    """Poll docker stats for all 6 active NOC microservice containers."""
    try:
        out = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"],
            text=True,
            timeout=4
        )
        containers = {}
        for line in out.strip().split('\n')[1:]:
            parts = re.split(r'\s{2,}', line.strip())
            if len(parts) >= 4:
                name, cpu_str, mem_str, mem_perc_str = parts[0], parts[1], parts[2], parts[3]
                if 'k8s_POD_' in name:
                    continue
                key = None
                if 'vector' in name: key = 'vector'
                elif 'instance1-api' in name: key = 'api1'
                elif 'postgres-instance1' in name: key = 'postgres1'
                elif 'outbox-forwarder' in name: key = 'forwarder'
                elif 'instance2-gateway' in name: key = 'gateway2'
                elif 'postgres-instance2' in name: key = 'postgres2'
                
                if key:
                    cpu_val = float(cpu_str.replace('%', ''))
                    mem_usage_val = mem_str.split('/')[0].strip()
                    mem_perc_val = float(mem_perc_str.replace('%', ''))
                    containers[key] = {
                        "cpu": cpu_val,
                        "mem": mem_usage_val,
                        "mem_perc": mem_perc_val
                    }
        return containers
    except Exception:
        return {}

def get_db_metrics():
    """Poll DB1 and DB2 metrics: outbox pending backlog, total alerts, replication counts."""
    metrics = {
        "db1_alerts": 0,
        "db1_outbox_pending": 0,
        "db1_inserts": 0,
        "db2_alerts": 0,
        "db2_replication_logs": 0
    }
    try:
        with psycopg.connect(DB1_URI, autocommit=True, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM alerts_outbox WHERE status = 'PENDING';")
                metrics["db1_outbox_pending"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM alerts;")
                metrics["db1_alerts"] = cur.fetchone()[0]
                cur.execute("SELECT n_tup_ins FROM pg_stat_user_tables WHERE relname = 'alerts';")
                row = cur.fetchone()
                if row:
                    metrics["db1_inserts"] = row[0]
    except Exception as e:
        print(f"[METRICS WARN] DB1 query error: {e}", file=sys.stderr)

    try:
        with psycopg.connect(DB2_URI, autocommit=True, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM alerts;")
                metrics["db2_alerts"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM alerts_replication_log;")
                metrics["db2_replication_logs"] = cur.fetchone()[0]
    except Exception as e:
        print(f"[METRICS WARN] DB2 query error: {e}", file=sys.stderr)

    return metrics

def monitor_thread_fn():
    """Background monitor thread gathering telemetry every 3 seconds."""
    t0 = time.time()
    while not stop_event.is_set():
        elapsed = time.time() - t0
        c_stats = get_container_stats()
        db_metrics = get_db_metrics()

        with metrics_lock:
            sent = stats["alerts_sent"]
            outbox_backlog = db_metrics["db1_outbox_pending"]
            if outbox_backlog > stats["peak_outbox_backlog"]:
                stats["peak_outbox_backlog"] = outbox_backlog

            for k, v in c_stats.items():
                if k not in stats["peak_cpu"] or v["cpu"] > stats["peak_cpu"][k]:
                    stats["peak_cpu"][k] = v["cpu"]
                if k not in stats["peak_mem"] or v["mem_perc"] > stats["peak_mem"][k].get("perc", 0):
                    stats["peak_mem"][k] = {"val": v["mem"], "perc": v["mem_perc"]}

            curr_eps = sent / elapsed if elapsed > 0 else 0

            point = {
                "elapsed_sec": round(elapsed, 1),
                "alerts_sent": sent,
                "instant_eps": round(curr_eps, 1),
                "outbox_backlog": outbox_backlog,
                "db1_alerts": db_metrics["db1_alerts"],
                "db2_alerts": db_metrics["db2_alerts"],
                "db2_replicated": db_metrics["db2_replication_logs"],
                "containers": c_stats
            }
            telemetry_data.append(point)

        cpu_summary = " ".join([f"{k}:{v['cpu']:.0f}%" for k, v in c_stats.items()])
        mem_summary = " ".join([f"{k}:{v['mem']}" for k, v in c_stats.items()])
        print(f"[{C_CYAN}T+{elapsed:5.1f}s{C_RESET}] "
              f"Sent: {C_BOLD}{sent:7,d}{C_RESET} ({curr_eps:6.1f} eps) | "
              f"DB1 Rows: {C_BOLD}{db_metrics['db1_alerts']:7,d}{C_RESET} | "
              f"Outbox Backlog: {C_YELLOW}{outbox_backlog:5,d}{C_RESET} | "
              f"DB2 Rows: {C_GREEN}{db_metrics['db2_alerts']:7,d}{C_RESET} | "
              f"CPU: [{cpu_summary}] | "
              f"Mem: [{mem_summary}]", flush=True)

        time.sleep(3.0)

def reset_environment():
    """Reset both databases to clean initial state before benchmark."""
    print(f"{C_BOLD}{C_YELLOW}>>> Resetting databases for clean distinct alert benchmark...{C_RESET}")
    with psycopg.connect(DB1_URI, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts;")
            cur.execute("DELETE FROM alerts_outbox;")
            cur.execute("DELETE FROM alerts_dlq;")
            cur.execute("SELECT pg_stat_reset();")
    time.sleep(1.0)
    with psycopg.connect(DB1_URI, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts_outbox;")
            cur.execute("DELETE FROM alerts_dlq;")
    with psycopg.connect(DB2_URI, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alerts_replication_log;")
            cur.execute("DELETE FROM alerts;")
            cur.execute("SELECT pg_stat_reset();")
    print(f"{C_BOLD}{C_GREEN}✔ Databases clean and stats reset.{C_RESET}\n")

def main():
    print(f"\n{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}   NETCOOL ALTERNATIVE - 1,000 DISTINCT ALERTS/SEC (2-MINUTE) STRESS TEST{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"  • Target Rate     : {C_BOLD}1,000 alerts/second{C_RESET}")
    print(f"  • Workload Type   : {C_BOLD}100% DISTINCT ALERTS (Zero Deduplication){C_RESET}")
    print(f"  • Duration        : {C_BOLD}120 seconds (2.0 minutes){C_RESET}")
    print(f"  • Expected DB Rows: {C_BOLD}120,000 rows in DB1 AND 120,000 rows in DB2{C_RESET}")
    print(f"  • Vector Ingress  : {C_BOLD}{VECTOR_URL}{C_RESET}")
    print(f"{C_CYAN}{'-' * 80}{C_RESET}\n")

    reset_environment()

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=50,
        pool_maxsize=100,
        max_retries=1
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    monitor_thread = threading.Thread(target=monitor_thread_fn, daemon=True)
    monitor_thread.start()

    executor = ThreadPoolExecutor(max_workers=20)

    def dispatch_batch(batch):
        t_req = time.time()
        try:
            resp = session.post(VECTOR_URL, json=batch, timeout=4.0)
            latency = (time.time() - t_req) * 1000.0
            with metrics_lock:
                stats["alerts_sent"] += len(batch)
                if resp.status_code == 200:
                    stats["http_success"] += len(batch)
                    if random.random() < 0.05:
                        stats["latencies_ms"].append(latency)
                else:
                    stats["http_error"] += len(batch)
        except Exception:
            with metrics_lock:
                stats["alerts_sent"] += len(batch)
                stats["http_error"] += len(batch)

    print(f"{C_BOLD}{C_GREEN}🚀 Starting Generation of 120,000 Distinct Alerts at 1,000 EPS...{C_RESET}\n")
    start_time = time.perf_counter()
    stats["start_time"] = time.time()
    seq_counter = 0

    try:
        for tick in range(DISPATCHES_PER_SEC * DURATION_SECONDS):
            target_time = start_time + (tick * INTERVAL)
            now = time.perf_counter()
            sleep_dur = target_time - now
            if sleep_dur > 0:
                time.sleep(sleep_dur)

            batch = generate_distinct_batch(BATCH_SIZE, seq_counter)
            seq_counter += BATCH_SIZE
            executor.submit(dispatch_batch, batch)

    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}⚠️ Traffic interrupted early by user.{C_RESET}")

    stats["end_send_time"] = time.time()
    send_duration = stats["end_send_time"] - stats["start_time"]
    actual_eps = stats["alerts_sent"] / send_duration if send_duration > 0 else 0
    print(f"\n{C_BOLD}{C_GREEN}✔ Generation Phase Completed in {send_duration:.1f}s!{C_RESET}")
    print(f"  • Total Distinct Alerts Sent: {C_BOLD}{stats['alerts_sent']:,d}{C_RESET}")
    print(f"  • Sustained Ingestion Rate  : {C_BOLD}{actual_eps:.1f} EPS{C_RESET}")
    print(f"  • HTTP Delivery Success     : {C_BOLD}{(stats['http_success']/max(1, stats['alerts_sent'])*100):.2f}%{C_RESET}\n")

    # Queue Drain Phase
    print(f"{C_BOLD}{C_YELLOW}>>> Waiting for Outbox Replication Queue to drain to 0...{C_RESET}")
    drain_start = time.time()

    while True:
        db_m = get_db_metrics()
        pending = db_m["db1_outbox_pending"]
        rep = db_m["db2_replication_logs"]
        db2_alerts = db_m["db2_alerts"]
        drain_elapsed = time.time() - drain_start
        print(f"  ⏳ [Drain +{drain_elapsed:4.1f}s] Outbox Pending: {C_YELLOW}{pending:5,d}{C_RESET} | DB1 Rows: {db_m['db1_alerts']:7,d} | DB2 Rows: {C_GREEN}{db2_alerts:7,d}{C_RESET}", end="\r", flush=True)

        if pending == 0 and (db2_alerts > 0 or drain_elapsed >= 2.0):
            print()
            stats["drain_finish_time"] = time.time()
            total_drain_time = stats["drain_finish_time"] - stats["end_send_time"]
            print(f"  {C_BOLD}{C_GREEN}✔ Outbox Replication Queue Fully Drained in {total_drain_time:.2f}s!{C_RESET}")
            break

        if drain_elapsed > 120:
            print(f"\n  {C_RED}⚠️ Drain timeout exceeded (120s). Backlog remains: {pending}{C_RESET}")
            break
        time.sleep(0.5)

    stop_event.set()
    monitor_thread.join(timeout=4)
    executor.shutdown(wait=True)

    final_db = get_db_metrics()

    lats = sorted(stats["latencies_ms"]) if stats["latencies_ms"] else [0]
    p50 = lats[int(len(lats) * 0.50)]
    p95 = lats[int(len(lats) * 0.95)]
    p99 = lats[int(len(lats) * 0.99)]

    results_summary = {
        "benchmark": "1000_distinct_alerts_per_second_2min",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_sec": round(send_duration, 1),
        "total_alerts_sent": stats["alerts_sent"],
        "http_success": stats["http_success"],
        "http_error": stats["http_error"],
        "sustained_eps": round(actual_eps, 1),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
        "peak_outbox_backlog": stats["peak_outbox_backlog"],
        "queue_drain_time_sec": round(stats.get("drain_finish_time", time.time()) - stats["end_send_time"], 2),
        "final_db1_alerts_rows": final_db["db1_alerts"],
        "final_db2_alerts_rows": final_db["db2_alerts"],
        "final_db2_replicated_records": final_db["db2_replication_logs"],
        "db1_db2_parity_delta": abs(final_db["db1_alerts"] - final_db["db2_alerts"]),
        "peak_cpu": stats["peak_cpu"],
        "peak_mem": stats["peak_mem"],
        "telemetry_points": telemetry_data
    }

    output_path = "noc-platform/simulation/stress_test_distinct_results.json"
    with open(output_path, "w") as f:
        json.dump(results_summary, f, indent=2)
    print(f"\n{C_BOLD}Saved raw telemetry data to {output_path}{C_RESET}")

    print(f"\n{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}          DISTINCT ALERTS (100% INSERT) BENCHMARK RESULTS REPORT{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"  • Total Distinct Alerts Sent  : {C_BOLD}{stats['alerts_sent']:,d}{C_RESET} events")
    print(f"  • Ingestion Duration          : {C_BOLD}{send_duration:.1f} seconds{C_RESET}")
    print(f"  • Sustained Throughput        : {C_BOLD}{actual_eps:.1f} distinct alerts/sec{C_RESET}")
    print(f"  • Primary DB1 'alerts' Rows   : {C_BOLD}{final_db['db1_alerts']:,d}{C_RESET} rows (Target: 120,000)")
    print(f"  • Secondary DB2 'alerts' Rows : {C_BOLD}{final_db['db2_alerts']:,d}{C_RESET} rows (Target: 120,000)")
    print(f"  • Primary-Secondary Parity    : {C_BOLD}{'100% EXACT MATCH (0 delta)' if final_db['db1_alerts'] == final_db['db2_alerts'] else 'PARITY MISMATCH'}{C_RESET}")
    print(f"  • Replication Logs in DB2     : {C_BOLD}{final_db['db2_replication_logs']:,d}{C_RESET} records")
    print(f"  • Vector Latency              : p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms")
    print(f"  • Peak Outbox Queue Depth     : {C_BOLD}{stats['peak_outbox_backlog']:,d} pending items{C_RESET}")
    print(f"  • Outbox Drain Latency        : {C_BOLD}{results_summary['queue_drain_time_sec']:.2f} seconds{C_RESET}")
    print(f"\n{C_BOLD}Peak Resource Consumption per Microservice:{C_RESET}")
    for k in sorted(stats["peak_cpu"].keys()):
        cpu_p = stats["peak_cpu"].get(k, 0)
        mem_info = stats["peak_mem"].get(k, {"val": "N/A", "perc": 0})
        print(f"  • {k:<18}: Peak CPU: {C_BOLD}{cpu_p:5.1f}%{C_RESET} | Peak Memory: {C_BOLD}{mem_info['val']:<10}{C_RESET} ({mem_info['perc']:.1f}%)")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}\n")

if __name__ == "__main__":
    main()
