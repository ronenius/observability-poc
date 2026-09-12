#!/usr/bin/env python3
"""
Netcool/OMNIbus Alternative - End-to-End Replication & Resilience Simulation
Simulates and validates all key challenges from the design document:
 1. Initial Ingestion & Vector In-Flight Remap
 2. In-Flight Dropping of Noisy / Debug Events
 3. Deduplication & Tally Accumulation (HOT Updates)
 4. Auto-Clearing State Transitions
 5. NOC Operator CRUD Actions (API Patch & Annotations)
 6. Cross-Network Gateway Replication via PostgreSQL Outbox Pattern
 7. Security Gateway Outage & Backpressure Handling
 8. Stale Packet Rejection & Zombie Alert Prevention (Optimistic Locking)
 9. Soft-Delete & Tombstone Propagation
"""

import json
import subprocess
import sys
import time
import requests
import psycopg
from psycopg.rows import dict_row

# ANSI Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
C_MAGENTA = "\033[35m"

def log_header(title: str):
    print(f"\n{C_BOLD}{C_CYAN}{'=' * 75}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}>>> {title}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 75}{C_RESET}")

def log_pass(msg: str):
    print(f"  {C_BOLD}{C_GREEN}✔ PASS:{C_RESET} {msg}")

def log_fail(msg: str):
    print(f"  {C_BOLD}{C_RED}✖ FAIL:{C_RESET} {msg}")
    sys.exit(1)

def log_info(msg: str):
    print(f"  {C_YELLOW}ℹ INFO:{C_RESET} {msg}")

# -------------------------------------------------------------
# Dynamic Service Discovery
# -------------------------------------------------------------
def discover_services():
    try:
        out = subprocess.check_output(
            ["kubectl", "get", "svc", "-n", "noc-platform", "-o", "json"],
            text=True
        )
        data = json.loads(out)
        ips = {}
        for item in data.get("items", []):
            name = item["metadata"]["name"]
            cluster_ip = item["spec"]["clusterIP"]
            ips[name] = cluster_ip
        return {
            "vector_http": f"http://{ips['vector-ingress']}:9000",
            "instance1_api": f"http://{ips['instance1-api']}:8081",
            "instance2_gw": f"http://{ips['instance2-gateway']}:8082",
            "db1_uri": f"postgresql://postgres:postgres@{ips['postgres-instance1']}:5432/postgres",
            "db2_uri": f"postgresql://postgres:postgres@{ips['postgres-instance2']}:5432/postgres",
        }
    except Exception as e:
        print(f"Failed to discover services via kubectl: {e}")
        sys.exit(1)

CFG = discover_services()

def query_db(uri: str, sql: str, params=None):
    with psycopg.connect(uri, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            try:
                return cur.fetchall()
            except psycopg.ProgrammingError:
                return []

def get_alert_db1(identifier: str):
    rows = query_db(CFG["db1_uri"], "SELECT * FROM alerts WHERE identifier = %s", (identifier,))
    return rows[0] if rows else None

def get_alert_db2(identifier: str):
    rows = query_db(CFG["db2_uri"], "SELECT * FROM alerts WHERE identifier = %s", (identifier,))
    return rows[0] if rows else None

def wait_for_db1(identifier: str, condition=lambda a: a is not None, timeout=5.0):
    start = time.time()
    while time.time() - start < timeout:
        a = get_alert_db1(identifier)
        if a and condition(a):
            return a
        time.sleep(0.15)
    return get_alert_db1(identifier)

def wait_for_db2(identifier: str, condition=lambda a: a is not None, timeout=5.0):
    start = time.time()
    while time.time() - start < timeout:
        a = get_alert_db2(identifier)
        if a and condition(a):
            return a
        time.sleep(0.15)
    return get_alert_db2(identifier)

# =============================================================
# SIMULATION TESTS
# =============================================================

def test_1_initial_ingest_and_replication():
    log_header("TEST 1: Ingestion via Vector & Unidirectional Outbox Replication")
    alert_payload = {
        "node": "prod-k8s-worker-01",
        "alert_key": "BGP_Peer_Down",
        "severity": "CRITICAL",
        "summary": "BGP Session to upstream provider is DOWN",
        "datacenter": "fra-dc2",
        "cluster": "prod-eu-central",
        "custom_fields": {
            "asn": 65001,
            "peer_ip": "10.254.0.1"
        }
    }
    
    log_info("POSTing raw alert event to Vector Webhook (port 9000)...")
    res = requests.post(CFG["vector_http"], json=alert_payload, timeout=5)
    if res.status_code != 200:
        log_fail(f"Vector returned status {res.status_code}")
    log_pass("Vector accepted raw alert via HTTP source")

    ident = "prod-k8s-worker-01:BGP_Peer_Down"
    a1 = wait_for_db1(ident, lambda a: a["status"] == "OPEN")
    if not a1:
        log_fail(f"Alert {ident} not found in Instance 1 DB")
    log_pass(f"Alert persisted in DB 1 (ID: {a1['id']}, Status: {a1['status']}, Tally: {a1['tally']}, Version: {a1['version']})")

    a2 = wait_for_db2(ident, lambda a: a["status"] == "OPEN")
    if not a2:
        log_fail(f"Alert {ident} not replicated to Instance 2 DB")
    log_pass(f"Alert replicated to DB 2 (Status: {a2['status']}, Tally: {a2['tally']}, Version: {a2['version']})")

    # Verify Envelope pattern: metadata envelope + custom_fields bag
    assert a2["custom_fields"]["asn"] == 65001, "Custom fields ASN match"
    assert a2["custom_fields"]["datacenter"] == "fra-dc2", "Datacenter normalized"
    log_pass("Dynamic custom_fields bag verified with zero-loss schema integrity")

def test_2_inflight_filtering():
    log_header("TEST 2: In-Flight Dropping of Noisy / Debug Events in Vector")
    debug_payload = {
        "node": "sandbox-host",
        "alert_key": "TestTrace",
        "severity": "DEBUG",
        "summary": "Noisy debug trace event",
        "environment": "dev"
    }

    log_info("POSTing DEBUG level event to Vector...")
    res = requests.post(CFG["vector_http"], json=debug_payload, timeout=5)
    assert res.status_code == 200
    time.sleep(0.5)

    ident = "sandbox-host:TestTrace"
    a1 = get_alert_db1(ident)
    a2 = get_alert_db2(ident)
    if a1 or a2:
        log_fail("DEBUG event leaked through into databases!")
    log_pass("Vector VRL transform successfully aborted event in-flight (0 rows written to DB1 or DB2)")

def test_3_deduplication_and_tally():
    log_header("TEST 3: Deduplication, Tally Accumulation & HOT Row Updates")
    ident = "prod-k8s-worker-01:BGP_Peer_Down"
    a1_before = wait_for_db1(ident)

    repeat_payload = {
        "node": "prod-k8s-worker-01",
        "alert_key": "BGP_Peer_Down",
        "severity": "CRITICAL",
        "summary": "BGP Session to upstream provider is STILL DOWN",
        "datacenter": "fra-dc2"
    }

    log_info("Sending 2 duplicate alert occurrences to Vector...")
    for _ in range(2):
        requests.post(CFG["vector_http"], json=repeat_payload, timeout=5)
        time.sleep(0.15)

    expected_tally = a1_before["tally"] + 2
    a1_after = wait_for_db1(ident, lambda a: a["tally"] >= expected_tally)
    a2_after = wait_for_db2(ident, lambda a: a["tally"] >= expected_tally)

    if not a1_after or a1_after["tally"] != expected_tally:
        log_fail(f"Expected DB1 tally {expected_tally}, got {a1_after['tally'] if a1_after else None}")
    log_pass(f"DB 1 Deduplicated occurrences cleanly: Tally = {a1_after['tally']}, Version = {a1_after['version']}")

    if not a2_after or a2_after["tally"] != expected_tally or a2_after["version"] != a1_after["version"]:
        log_fail(f"DB 2 out of sync: Tally={a2_after['tally'] if a2_after else None}, Version={a2_after['version'] if a2_after else None}")
    log_pass(f"DB 2 Replicated new Tally ({a2_after['tally']}) and Version ({a2_after['version']})")

def test_4_autoclear():
    log_header("TEST 4: State Machine Auto-Clearing (CLEAR -> RESOLVED)")
    ident = "prod-k8s-worker-01:BGP_Peer_Down"
    clear_payload = {
        "node": "prod-k8s-worker-01",
        "alert_key": "BGP_Peer_Down",
        "severity": "CLEAR",
        "summary": "BGP Session has restored normal operation"
    }

    log_info("POSTing CLEAR event to Vector...")
    requests.post(CFG["vector_http"], json=clear_payload, timeout=5)

    a1 = wait_for_db1(ident, lambda a: a["status"] == "RESOLVED")
    a2 = wait_for_db2(ident, lambda a: a["status"] == "RESOLVED")

    if not a1 or a1["status"] != "RESOLVED":
        log_fail(f"Expected DB 1 status RESOLVED, got {a1['status'] if a1 else None}")
    log_pass(f"DB 1 Alert auto-cleared: Status={a1['status']}, Severity={a1['severity']}")

    if not a2 or a2["status"] != "RESOLVED":
        log_fail(f"Expected DB 2 status RESOLVED, got {a2['status'] if a2 else None}")
    log_pass(f"DB 2 Alert auto-cleared in sync: Status={a2['status']}")

def test_5_operator_crud_api():
    log_header("TEST 5: Operator Headless CRUD API (Annotation & Acknowledgment)")
    ident = "prod-k8s-worker-01:BGP_Peer_Down"
    patch_payload = {
        "status": "ACKNOWLEDGED",
        "summary": "BGP Session flapping investigated by NOC Team",
        "custom_fields": {
            "acknowledged_by": "ronen@company.internal",
            "jira_ticket": "NOC-4892",
            "incident_commander": "NOC Tier 2"
        }
    }

    log_info(f"PATCHing /api/v1/alerts/{ident} on Instance 1 API...")
    res = requests.patch(f"{CFG['instance1_api']}/api/v1/alerts/{ident}", json=patch_payload, timeout=5)
    if res.status_code != 200:
        log_fail(f"Operator API returned {res.status_code}: {res.text}")
    log_pass("Operator API updated alert state in Instance 1")

    a1 = wait_for_db1(ident, lambda a: a["status"] == "ACKNOWLEDGED")
    a2 = wait_for_db2(ident, lambda a: a["status"] == "ACKNOWLEDGED")

    assert a1["status"] == "ACKNOWLEDGED"
    assert a1["custom_fields"]["jira_ticket"] == "NOC-4892"
    log_pass(f"DB 1 Operator changes persisted: Version={a1['version']}, Status={a1['status']}")

    assert a2["status"] == "ACKNOWLEDGED"
    assert a2["custom_fields"]["jira_ticket"] == "NOC-4892"
    assert a2["custom_fields"]["acknowledged_by"] == "ronen@company.internal"
    log_pass(f"DB 2 Replicated operator annotations instantly: JIRA={a2['custom_fields']['jira_ticket']}")

def test_6_gateway_outage_and_backpressure():
    log_header("TEST 6: Security Gateway Outage & Transactional Outbox Backpressure")
    log_info("Simulating WAN outage by disabling Instance 2 Security Gateway...")
    res = requests.post(f"{CFG['instance2_gw']}/admin/gateway-toggle?enabled=false", timeout=5)
    assert res.status_code == 200 and res.json()["gateway_enabled"] is False
    log_pass("Security Gateway is now DISABLED (returning HTTP 503 Service Unavailable)")

    # Send new alert during outage
    outage_alert = {
        "node": "edge-router-09",
        "alert_key": "Interface_Flapping",
        "severity": "WARNING",
        "summary": "Interface eth0 is bouncing",
        "custom_fields": {"port": "eth0"}
    }
    requests.post(f"{CFG['instance1_api']}/api/v1/ingest", json=outage_alert, timeout=5)
    time.sleep(1.0)

    # Verify alert is in DB1 but NOT in DB2
    ident = "edge-router-09:Interface_Flapping"
    a1 = get_alert_db1(ident)
    a2 = get_alert_db2(ident)
    assert a1 is not None, "Alert in DB1"
    assert a2 is None, "Alert must NOT be in DB2 while gateway is down"
    log_pass("DB 1 ingested alert during outage; DB 2 has not received it yet")

    # Verify alert is pending in DB1 Outbox
    outbox_pending = query_db(
        CFG["db1_uri"], 
        "SELECT count(*) as count FROM alerts_outbox WHERE status = 'PENDING'"
    )
    count = outbox_pending[0]["count"]
    log_info(f"Pending alerts currently buffered in DB 1 Outbox: {count}")
    assert count >= 1, "Outbox must buffer pending changes"
    log_pass("Outbox successfully buffered pending events without blocking DB1 transaction")

    # Restore Gateway
    log_info("Restoring Security Gateway connectivity...")
    res = requests.post(f"{CFG['instance2_gw']}/admin/gateway-toggle?enabled=true", timeout=5)
    assert res.status_code == 200 and res.json()["gateway_enabled"] is True
    log_pass("Security Gateway re-enabled")

    # Wait for forwarder retry cycle
    log_info("Waiting for Outbox Forwarder backpressure flush (retry poll)...")
    flushed = False
    for attempt in range(12):
        time.sleep(1.5)
        a2 = get_alert_db2(ident)
        if a2:
            flushed = True
            break

    if not flushed:
        log_fail("Outbox Forwarder failed to flush pending alerts after gateway recovery")
    log_pass(f"DB 2 received buffered alert after recovery: {ident} (Version {a2['version']})")

def test_7_zombie_alert_optimistic_lock():
    log_header("TEST 7: Zombie Alert Prevention (Out-of-Order Optimistic Locking)")
    ident = "prod-k8s-worker-01:BGP_Peer_Down"
    a2_current = get_alert_db2(ident)
    current_version = a2_current["version"]
    log_info(f"Current version of {ident} in DB 2 is {current_version}")

    # Fabricate a stale network packet with version = 1
    stale_payload = {
        "operation": "UPDATE",
        "identifier": ident,
        "node": "prod-k8s-worker-01",
        "alert_key": "BGP_Peer_Down",
        "severity": "CRITICAL",
        "status": "OPEN",  # Stale status!
        "summary": "Stale packet from an old retry",
        "tally": 1,
        "version": 1,  # STALE VERSION!
        "first_occurrence": "2026-09-12T00:00:00Z",
        "last_occurrence": "2026-09-12T00:00:00Z",
        "last_state_change": "2026-09-12T00:00:00Z",
        "custom_fields": {"stale": True}
    }

    log_info("Injecting stale out-of-order packet (Version 1) directly into Instance 2 Gateway...")
    res = requests.post(f"{CFG['instance2_gw']}/api/v1/replicate", json=stale_payload, timeout=5)
    assert res.status_code == 200
    res_data = res.json()
    log_info(f"Instance 2 Gateway response: {res_data}")

    # Check that optimistic locking dropped the stale packet
    a2_check = get_alert_db2(ident)
    if a2_check["version"] < current_version:
        log_fail("Stale packet regressed version in DB 2!")
    if a2_check["status"] == "OPEN":
        log_fail("Stale packet resurrected resolved/acknowledged alert (ZOMBIE ALERT)!")

    assert res_data.get("status") == "dropped_stale_version"
    log_pass(f"Instance 2 UPSERT dropped stale update cleanly: Version remains {a2_check['version']}, Status={a2_check['status']}")

def test_8_soft_delete_and_tombstone():
    log_header("TEST 8: Soft Deletion & Tombstone Outbox Synchronization")
    ident = "edge-router-09:Interface_Flapping"
    log_info(f"Calling DELETE /api/v1/alerts/{ident} on Instance 1 API...")
    res = requests.delete(f"{CFG['instance1_api']}/api/v1/alerts/{ident}", timeout=5)
    assert res.status_code == 200
    log_pass("Alert soft-deleted in Instance 1 (marked PURGED)")

    a1 = wait_for_db1(ident, lambda a: a["status"] == "PURGED")
    a2 = wait_for_db2(ident, lambda a: a["status"] == "PURGED")

    assert a1["status"] == "PURGED" and a1["deleted_at"] is not None
    log_pass(f"DB 1 Tombstone active: Status={a1['status']}, Version={a1['version']}")

    assert a2["status"] == "PURGED" and a2["deleted_at"] is not None
    log_pass(f"DB 2 Tombstone replicated: Status={a2['status']}, Version={a2['version']}")

def clean_databases():
    log_info("Resetting databases to clean state...")
    query_db(CFG["db1_uri"], "DELETE FROM alerts; DELETE FROM alerts_outbox; DELETE FROM alerts_dlq;")
    query_db(CFG["db2_uri"], "DELETE FROM alerts; DELETE FROM alerts_replication_log;")
    log_pass("Databases cleaned.")

def main():
    print(f"\n{C_BOLD}{C_MAGENTA}{'#' * 75}{C_RESET}")
    print(f"{C_BOLD}{C_MAGENTA}# Netcool/OMNIbus Alternative - End-to-End Cluster Simulation #{C_RESET}")
    print(f"{C_BOLD}{C_MAGENTA}{'#' * 75}{C_RESET}\n")
    print(f"Target Configuration:")
    for k, v in CFG.items():
        print(f"  • {k:15}: {v}")

    clean_databases()
    t0 = time.time()
    test_1_initial_ingest_and_replication()
    test_2_inflight_filtering()
    test_3_deduplication_and_tally()
    test_4_autoclear()
    test_5_operator_crud_api()
    test_6_gateway_outage_and_backpressure()
    test_7_zombie_alert_optimistic_lock()
    test_8_soft_delete_and_tombstone()
    elapsed = time.time() - t0

    print(f"\n{C_BOLD}{C_GREEN}{'=' * 75}{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}🎉 ALL 8 SIMULATION SCENARIOS PASSED PERFECTLY IN {elapsed:.2f}s!{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}{'=' * 75}{C_RESET}\n")

if __name__ == "__main__":
    main()
