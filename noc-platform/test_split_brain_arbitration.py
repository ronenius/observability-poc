#!/usr/bin/env python3
"""
Verification test for Issue 8: Split-Brain & Accidental Writes on Secondary Site (Central NOC).

Architectural rules verified:
1. One-way network architecture: Instance 2 (Central NOC) has NO outbound access to Instance 1.
2. Inbound telemetry sync from Instance 1 refreshes tally, last_occurrence, etc.
3. Operator workflow states on Instance 2 (SNOOZED, ACKNOWLEDGED) are preserved during sync.
4. Severe escalations (e.g. WARNING -> CRITICAL) break out of snooze into OPEN.
5. Hardware recovery (CLEAR / RESOLVED) resolves the alert on Instance 2.
6. Instance 2 temporal engine autonomously awakens expired snoozes without edge assistance.
"""

import requests
import time
from datetime import datetime, timezone

I1_API = "http://192.168.194.183:8081"
I2_API = "http://192.168.194.159:8082"
I2_UI  = "http://192.168.194.177:8083"

def main():
    print("=" * 70)
    print("TEST: Central NOC State Arbitration & Split-Brain Prevention")
    print("=" * 70)

    ident = f"core-router-bgp-{int(time.time())}"

    # Step 1: Ingest WARNING alert on Instance 1
    print(f"\n[Step 1] Ingesting initial WARNING alert on Instance 1: {ident}...")
    r = requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "core-router-01",
        "alert_key": "BGP_FLAP",
        "severity": "WARNING",
        "summary": "BGP peer 10.0.0.2 is flapping",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    assert r.status_code == 200, f"Failed to ingest on I1: {r.text}"

    # Wait for replication to Instance 2
    time.sleep(1.5)
    r2 = requests.get(f"{I2_API}/api/v1/alerts/{ident}")
    assert r2.status_code == 200, f"Alert not found on I2: {r2.text}"
    i2_alert = r2.json()
    print(f"  -> Replicated to Instance 2: status={i2_alert['status']}, tally={i2_alert['tally']}, severity={i2_alert['severity']}")
    assert i2_alert["status"] == "OPEN"
    assert i2_alert["tally"] == 1

    # Step 2: Operator on Instance 2 (Central NOC) SNOOZES the alert via UI Proxy (port 8083)
    print(f"\n[Step 2] Central NOC Operator snoozes alert for 30 minutes via UI (port 8083)...")
    r_snooze = requests.post(f"{I2_UI}/api/v1/alerts/{ident}/snooze", json={
        "duration_minutes": 30,
        "reason": "Scheduled maintenance maintenance-window-44"
    })
    assert r_snooze.status_code == 200, f"Snooze failed on I2: {r_snooze.text}"
    snoozed = r_snooze.json()
    print(f"  -> Snoozed on Instance 2: status={snoozed['status']}, snooze_until={snoozed['snooze_until']}")
    assert snoozed["status"] == "SNOOZED"
    assert snoozed["snooze_until"] is not None

    # Verify Instance 1 was NOT modified (one-way diode / zero outbound calls from I2)
    r_i1 = requests.get(f"{I1_API}/api/v1/alerts?search={ident}").json()[0]
    print(f"  -> Instance 1 edge status (unaware of NOC snooze): status={r_i1['status']}")
    assert r_i1["status"] == "OPEN", "Instance 1 should remain OPEN as no outbound calls are made from I2"

    # Step 3: Repeated trap arrives at Instance 1 (tally increases on edge)
    print(f"\n[Step 3] Repeated trap arrives at Instance 1 (tally -> 2)...")
    r_repeat = requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "core-router-01",
        "alert_key": "BGP_FLAP",
        "severity": "WARNING",
        "summary": "BGP peer 10.0.0.2 is flapping (tally bump)",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    assert r_repeat.status_code == 200

    # Wait for replication sync
    time.sleep(1.5)
    r2_after_sync = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Instance 2 after edge sync: tally={r2_after_sync['tally']}, status={r2_after_sync['status']}")
    assert r2_after_sync["tally"] == 2, f"Expected tally=2, got {r2_after_sync['tally']}"
    assert r2_after_sync["status"] == "SNOOZED", f"Expected SNOOZED to be preserved, got {r2_after_sync['status']}!"
    assert r2_after_sync["snooze_until"] == snoozed["snooze_until"], "Snooze_until was overwritten!"
    print("  ✅ SUCCESS: Central NOC operator lease preserved! Tally updated to 2 while SNOOZED status was retained.")

    # Step 4: Central NOC Operator acknowledges alert (ACK)
    print(f"\n[Step 4] Operator on Instance 2 changes status to ACKNOWLEDGED...")
    r_ack = requests.patch(f"{I2_UI}/api/v1/alerts/{ident}", json={
        "status": "ACKNOWLEDGED",
        "custom_fields": {"acknowledged_by": "noc-engineer-alex"}
    })
    assert r_ack.status_code == 200
    print(f"  -> Instance 2 status: {r_ack.json()['status']}")
    assert r_ack.json()["status"] == "ACKNOWLEDGED"

    # Repeated trap arrives at Instance 1 again (tally -> 3)
    print(f"\n[Step 5] Another trap arrives at Instance 1 (tally -> 3)...")
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "core-router-01",
        "alert_key": "BGP_FLAP",
        "severity": "WARNING",
        "summary": "BGP peer 10.0.0.2 is flapping (tally 3)",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(1.5)
    r2_ack_sync = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Instance 2 after sync: tally={r2_ack_sync['tally']}, status={r2_ack_sync['status']}")
    assert r2_ack_sync["tally"] == 3
    assert r2_ack_sync["status"] == "ACKNOWLEDGED", f"Expected ACKNOWLEDGED to be preserved, got {r2_ack_sync['status']}!"
    print("  ✅ SUCCESS: ACKNOWLEDGED status preserved during edge sync.")

    # Step 6: Test Severe Escalation Breakout (WARNING -> CRITICAL)
    print(f"\n[Step 6] Re-snoozing alert, then triggering CRITICAL escalation from Instance 1...")
    requests.post(f"{I2_UI}/api/v1/alerts/{ident}/snooze", json={"duration_minutes": 10, "reason": "test"})
    r_check_snooze = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    assert r_check_snooze["status"] == "SNOOZED"

    # Send CRITICAL event from edge
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "core-router-01",
        "alert_key": "BGP_FLAP",
        "severity": "CRITICAL",
        "summary": "BGP Session Completely DOWN to Core",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(1.5)
    r2_crit = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Instance 2 after CRITICAL escalation: severity={r2_crit['severity']}, status={r2_crit['status']}")
    assert r2_crit["severity"] == "CRITICAL"
    assert r2_crit["status"] == "OPEN", f"Expected OPEN after critical escalation, got {r2_crit['status']}"
    assert r2_crit["snooze_until"] is None, "Expected snooze_until to be cleared on critical escalation"
    print("  ✅ SUCCESS: Critical escalation broke through snooze to notify operators!")

    # Step 7: Test Hardware Recovery (CLEAR / RESOLVED)
    print(f"\n[Step 7] Sending CLEAR event from Instance 1...")
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "core-router-01",
        "alert_key": "BGP_FLAP",
        "severity": "CLEAR",
        "summary": "BGP Session restored and stable",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(1.5)
    r2_clear = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Instance 2 after CLEAR: severity={r2_clear['severity']}, status={r2_clear['status']}")
    assert r2_clear["status"] == "RESOLVED"
    print("  ✅ SUCCESS: Hardware recovery resolved alert on Central NOC.")

    # Step 8: Test Autonomous Temporal Engine on Instance 2
    print(f"\n[Step 8] Testing Autonomous Temporal Engine on Instance 2 (5-second snooze)...")
    ident_temp = f"temp-test-{int(time.time())}"
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident_temp,
        "node": "server-rack-01",
        "alert_key": "CPU_HIGH",
        "severity": "MAJOR",
        "summary": "CPU utilization 95%",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(1.5)
    # Snooze for 5 seconds
    res_snooze = requests.post(f"{I2_UI}/api/v1/alerts/{ident_temp}/snooze", json={
        "duration_seconds": 5,
        "reason": "Short temporary snooze"
    })
    assert res_snooze.status_code == 200, f"Snooze failed on I2: {res_snooze.text}"
    r2_temp = requests.get(f"{I2_API}/api/v1/alerts/{ident_temp}").json()
    assert r2_temp["status"] == "SNOOZED"
    print(f"  -> Alert snoozed on I2 until {r2_temp['snooze_until']}. Waiting for temporal engine sweep (up to 12s)...")
    awakened = False
    for _ in range(12):
        time.sleep(1.0)
        r2_check = requests.get(f"{I2_API}/api/v1/alerts/{ident_temp}").json()
        if r2_check["status"] == "OPEN":
            awakened = True
            r2_awakened = r2_check
            break
    assert awakened, f"Expected OPEN after expiration within 12s, alert is still: {r2_check['status']}"
    print(f"  -> Status after expiration: status={r2_awakened['status']}")
    assert r2_awakened["snooze_until"] is None
    print("  ✅ SUCCESS: Instance 2 temporal engine autonomously awakened the expired alert!")

    print("\n" + "=" * 70)
    print("ALL STATE ARBITRATION TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
