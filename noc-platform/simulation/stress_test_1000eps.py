#!/usr/bin/env python3
"""
Netcool/OMNIbus Alternative - Production 1,000 EPS Stress Test & Resource Monitor
================================================================================
Target:
  • Rate: 1,000 alerts/second sustained
  • Duration: 3 minutes (180 seconds) = 180,000 total events
  • Workload Mix:
      - 70% Recurring duplicate alerts (stresses HOT row updates & fillfactor=70)
      - 20% Distinct new alerts (stresses B-Tree index inserts & WAL)
      - 10% Auto-clearing alerts (stresses state transition engine & partial index)
  • Continuous Telemetry:
      - Container CPU % & Memory Usage (MiB) for all 6 containers
      - DB1 Outbox replication queue backlog depth
      - DB1 HOT update efficiency (pg_stat_user_tables)
      - DB2 Replicated event count & replication lag
      - Post-test queue drain time (time to zero backlog)
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

# Configuration & Endpoints
VECTOR_URL = os.getenv("VECTOR_URL", "http://192.168.194.187:9000")
DB1_URI = os.getenv("DATABASE_URL_1", "postgresql://postgres:postgres@192.168.194.162:5432/postgres")
DB2_URI = os.getenv("DATABASE_URL_2", "postgresql://postgres:postgres@192.168.194.154:5432/postgres")

DURATION_SECONDS = 180       # 3 minutes
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

# Global Shared State
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

# Pre-generate persistent node and check pools for 70% recurring duplicate workload
NODES_POOL = [f"k8s-worker-{i:03d}" for i in range(1, 101)]
CHECKS_POOL = ["BGP_Session_Down", "Interface_Flapping", "High_CPU_Usage", "Disk_Full_95", "Memory_Pressure"]
SEVERITIES = ["CRITICAL", "MAJOR", "WARNING", "MINOR"]

def generate_alert_batch(batch_size: int, seq_offset: int) -> list:
    batch = []
    for i in range(batch_size):
        r = random.random()
        if r < 0.70:
            # 70% Recurring duplicate alerts (HOT row updates)
            node = random.choice(NODES_POOL)
            check = random.choice(CHECKS_POOL)
            sev = random.choice(SEVERITIES)
            summary = f"Persistent telemetry alert on {node} ({check})"
        elif r < 0.90:
            # 20% Distinct new alerts
            new_id = seq_offset + i
            node = f"ephemeral-node-{new_id:06d}"
            check = f"Service_Crash_{new_id % 20}"
            sev = random.choice(SEVERITIES)
            summary = f"Newly discovered event on {node}"
        else:
            # 10% Auto-clearing alerts (CLEAR event for recurring pool)
            node = random.choice(NODES_POOL)
            check = random.choice(CHECKS_POOL)
            sev = "CLEAR"
            summary = f"Auto-cleared event for {node}:{check}"

        batch.append({
            "node": node,
            "alert_key": check,
            "severity": sev,
            "summary": summary,
            "environment": "production",
            "datacenter": "fra-dc2",
            "cluster": "prod-eu-central",
            "custom_fields": {
                "source": "stress-test-engine",
                "sample_seq": seq_offset + i
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
    """Poll DB1 and DB2 metrics: outbox pending backlog, total alerts, replication counts, HOT updates."""
    metrics = {
        "db1_alerts": 0,
        "db1_outbox_pending": 0,
        "db1_hot_updates": 0,
        "db1_total_updates": 0,
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
                cur.execute("SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname = 'alerts';")
                row = cur.fetchone()
                if row:
                    metrics["db1_total_updates"] = row[0]
                    metrics["db1_hot_updates"] = row[1]
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

            # Track peak CPU / Memory
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
                "hot_updates": db_metrics["db1_hot_updates"],
                "total_updates": db_metrics["db1_total_updates"],
                "containers": c_stats
            }
            telemetry_data.append(point)

        # Print live dashboard line
        cpu_summary = " ".join([f"{k}:{v['cpu']:.0f}%" for k, v in c_stats.items()])
        mem_summary = " ".join([f"{k}:{v['mem']}" for k, v in c_stats.items()])
        print(f"[{C_CYAN}T+{elapsed:5.1f}s{C_RESET}] "
              f"Sent: {C_BOLD}{sent:7,d}{C_RESET} ({curr_eps:6.1f} eps) | "
              f"Outbox Backlog: {C_YELLOW}{outbox_backlog:5,d}{C_RESET} | "
              f"DB2 Replicated: {C_GREEN}{db_metrics['db2_replication_logs']:7,d}{C_RESET} | "
              f"CPU: [{cpu_summary}] | "
              f"Mem: [{mem_summary}]", flush=True)

        time.sleep(3.0)

def reset_environment():
    """Reset both databases to clean initial state before test."""
    print(f"{C_BOLD}{C_YELLOW}>>> Resetting databases for clean benchmark...{C_RESET}")
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
    print(f"{C_BOLD}{C_CYAN}    NETCOOL/OMNIBUS ALTERNATIVE - 1,000 EPS (3-MINUTE) STRESS TEST{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"  • Target Rate    : {C_BOLD}1,000 alerts/second{C_RESET}")
    print(f"  • Duration       : {C_BOLD}180 seconds (3.0 minutes){C_RESET}")
    print(f"  • Expected Total : {C_BOLD}180,000 alerts{C_RESET}")
    print(f"  • Vector Ingress : {C_BOLD}{VECTOR_URL}{C_RESET}")
    print(f"  • Workload Profile: 70% Duplicate Recurring, 20% Distinct New, 10% Auto-Clear")
    print(f"{C_CYAN}{'-' * 80}{C_RESET}\n")

    reset_environment()

    # Pre-warm HTTP sessions
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=50,
        pool_maxsize=100,
        max_retries=1
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Start Background Monitor
    monitor_thread = threading.Thread(target=monitor_thread_fn, daemon=True)
    monitor_thread.start()

    # Setup ThreadPool for sending dispatches
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
                    if random.random() < 0.05:  # Sample 5% latencies
                        stats["latencies_ms"].append(latency)
                else:
                    stats["http_error"] += len(batch)
        except Exception:
            with metrics_lock:
                stats["alerts_sent"] += len(batch)
                stats["http_error"] += len(batch)

    print(f"{C_BOLD}{C_GREEN}🚀 Starting Traffic Generation at 1,000 EPS...{C_RESET}\n")
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

            batch = generate_alert_batch(BATCH_SIZE, seq_counter)
            seq_counter += BATCH_SIZE
            executor.submit(dispatch_batch, batch)

    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}⚠️ Traffic interrupted early by user.{C_RESET}")

    stats["end_send_time"] = time.time()
    send_duration = stats["end_send_time"] - stats["start_time"]
    actual_eps = stats["alerts_sent"] / send_duration if send_duration > 0 else 0
    print(f"\n{C_BOLD}{C_GREEN}✔ Generation Phase Completed in {send_duration:.1f}s!{C_RESET}")
    print(f"  • Total Alerts Sent: {C_BOLD}{stats['alerts_sent']:,d}{C_RESET}")
    print(f"  • Sustained Rate   : {C_BOLD}{actual_eps:.1f} EPS{C_RESET}")
    print(f"  • HTTP Success Rate: {C_BOLD}{(stats['http_success']/max(1, stats['alerts_sent'])*100):.2f}%{C_RESET}\n")

    # Queue Drain Phase
    print(f"{C_BOLD}{C_YELLOW}>>> Waiting for Outbox Replication Queue to drain to 0...{C_RESET}")
    drain_start = time.time()
    last_pending = 999999

    while True:
        db_m = get_db_metrics()
        pending = db_m["db1_outbox_pending"]
        rep = db_m["db2_replication_logs"]
        drain_elapsed = time.time() - drain_start
        print(f"  ⏳ [Drain +{drain_elapsed:4.1f}s] Outbox Pending: {C_YELLOW}{pending:5,d}{C_RESET} | Replicated to DB2: {C_GREEN}{rep:7,d}{C_RESET}", end="\r", flush=True)

        if pending == 0 and (rep > 0 or drain_elapsed >= 2.0):
            print()
            stats["drain_finish_time"] = time.time()
            total_drain_time = stats["drain_finish_time"] - stats["end_send_time"]
            print(f"  {C_BOLD}{C_GREEN}✔ Outbox Queue Fully Drained in {total_drain_time:.2f}s!{C_RESET}")
            break

        if drain_elapsed > 120:  # 2 minute drain cutoff
            print(f"\n  {C_RED}⚠️ Drain timeout exceeded (120s). Backlog remains: {pending}{C_RESET}")
            break
        time.sleep(0.5)

    stop_event.set()
    monitor_thread.join(timeout=4)
    executor.shutdown(wait=True)

    # Final Verification & Stats
    final_db = get_db_metrics()
    hot_pct = (final_db["db1_hot_updates"] / max(1, final_db["db1_total_updates"])) * 100.0

    # Latency percentiles
    lats = sorted(stats["latencies_ms"]) if stats["latencies_ms"] else [0]
    p50 = lats[int(len(lats) * 0.50)]
    p95 = lats[int(len(lats) * 0.95)]
    p99 = lats[int(len(lats) * 0.99)]

    results_summary = {
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
        "final_db1_alerts": final_db["db1_alerts"],
        "final_db2_alerts": final_db["db2_alerts"],
        "final_db2_replicated": final_db["db2_replication_logs"],
        "db1_hot_updates": final_db["db1_hot_updates"],
        "db1_total_updates": final_db["db1_total_updates"],
        "hot_update_efficiency_pct": round(hot_pct, 1),
        "peak_cpu": stats["peak_cpu"],
        "peak_mem": stats["peak_mem"],
        "telemetry_points": telemetry_data
    }

    # Save results to JSON
    output_path = "noc-platform/simulation/stress_test_results.json"
    with open(output_path, "w") as f:
        json.dump(results_summary, f, indent=2)
    print(f"\n{C_BOLD}Saved raw telemetry data to {output_path}{C_RESET}")

    # Print Final Summary Table
    print(f"\n{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}                 STRESS TEST BENCHMARK RESULTS REPORT{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}")
    print(f"  • Total Alerts Ingested : {C_BOLD}{stats['alerts_sent']:,d}{C_RESET} events")
    print(f"  • Ingestion Duration    : {C_BOLD}{send_duration:.1f} seconds{C_RESET}")
    print(f"  • Sustained Throughput  : {C_BOLD}{actual_eps:.1f} alerts/sec{C_RESET} (Target: 1,000 eps)")
    print(f"  • HTTP Delivery Success : {C_BOLD}{(stats['http_success']/max(1, stats['alerts_sent'])*100):.2f}%{C_RESET}")
    print(f"  • Vector Latency        : p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms")
    print(f"  • Max Outbox Queue Depth: {C_BOLD}{stats['peak_outbox_backlog']:,d} pending items{C_RESET}")
    print(f"  • Outbox Drain Latency  : {C_BOLD}{results_summary['queue_drain_time_sec']:.2f} seconds{C_RESET}")
    print(f"  • DB1 Active Alerts     : {C_BOLD}{final_db['db1_alerts']:,d}{C_RESET}")
    print(f"  • DB2 Replicated Alerts : {C_BOLD}{final_db['db2_alerts']:,d}{C_RESET}")
    print(f"  • Replication Logs Total: {C_BOLD}{final_db['db2_replication_logs']:,d}{C_RESET}")
    print(f"  • HOT Update Efficiency : {C_BOLD}{hot_pct:.1f}%{C_RESET} ({final_db['db1_hot_updates']:,d} / {final_db['db1_total_updates']:,d} updates)")
    print(f"\n{C_BOLD}Peak Resource Consumption per Microservice:{C_RESET}")
    for k in sorted(stats["peak_cpu"].keys()):
        cpu_p = stats["peak_cpu"].get(k, 0)
        mem_info = stats["peak_mem"].get(k, {"val": "N/A", "perc": 0})
        print(f"  • {k:<18}: Peak CPU: {C_BOLD}{cpu_p:5.1f}%{C_RESET} | Peak Memory: {C_BOLD}{mem_info['val']:<10}{C_RESET} ({mem_info['perc']:.1f}%)")
    print(f"{C_BOLD}{C_CYAN}{'=' * 80}{C_RESET}\n")

if __name__ == "__main__":
    main()
