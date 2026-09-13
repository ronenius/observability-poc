#!/usr/bin/env python3
"""
Verify that Central NOC (Instance 2) strictly ignores any Snooze / Ack
originating from edge instances (Instance 1), ensuring Central NOC is the
sole workflow authority.
"""

import requests
import time
from datetime import datetime, timezone

I1_API = "http://192.168.194.183:8081"
I2_API = "http://192.168.194.159:8082"
I2_UI  = "http://192.168.194.177:8083"

def main():
    print("=" * 70)
    print("TEST: Central NOC Sole Workflow Authority (Edge Snooze/Ack Ignored)")
    print("=" * 70)

    ident = f"edge-test-alert-{int(time.time())}"

    # 1. Ingest alert on Instance 1
    print(f"\n1. Ingesting alert on Instance 1: {ident}...")
    r = requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "edge-switch-01",
        "alert_key": "PORT_DOWN",
        "severity": "MAJOR",
        "summary": "Port GigabitEthernet0/1 Link Down",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    assert r.status_code == 200

    # Verify replication to Instance 2
    time.sleep(1.5)
    r2 = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Instance 2 initial state: status={r2['status']}")
    assert r2["status"] == "OPEN"

    # 2. Snooze on Instance 1 (Edge)
    print("\n2. Snoozing alert directly on Instance 1 (Edge)...")
    r_snooze_i1 = requests.post(f"{I1_API}/api/v1/alerts/{ident}/snooze", json={
        "duration_minutes": 20,
        "reason": "Edge technician working on cable"
    })
    assert r_snooze_i1.status_code == 200
    alert_i1 = requests.get(f"{I1_API}/api/v1/alerts?search={ident}").json()[0]
    print(f"  -> Instance 1 edge status: status={alert_i1['status']}, snooze_until={alert_i1['snooze_until']}")
    assert alert_i1["status"] == "SNOOZED"

    # 3. Wait for replication sync to Instance 2
    print("\n3. Waiting for edge CDC sync to Central NOC (Instance 2)...")
    time.sleep(2.0)
    r2_after_edge_snooze = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Central NOC status after edge snooze: status={r2_after_edge_snooze['status']}, snooze_until={r2_after_edge_snooze['snooze_until']}")
    assert r2_after_edge_snooze["status"] == "OPEN", f"Central NOC should IGNORE edge snooze and remain OPEN, but got {r2_after_edge_snooze['status']}!"
    assert r2_after_edge_snooze["snooze_until"] is None
    print("  ✅ SUCCESS: Central NOC ignored edge snooze and remained OPEN!")

    # 4. Acknowledge on Instance 1 (Edge)
    print("\n4. Acknowledging alert on Instance 1 (Edge)...")
    r_ack_i1 = requests.patch(f"{I1_API}/api/v1/alerts/{ident}", json={
        "status": "ACKNOWLEDGED",
        "custom_fields": {"acknowledged_by": "edge-tech"}
    })
    assert r_ack_i1.status_code == 200
    time.sleep(2.0)
    r2_after_edge_ack = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Central NOC status after edge ack: status={r2_after_edge_ack['status']}")
    assert r2_after_edge_ack["status"] == "OPEN", f"Central NOC should IGNORE edge ACK and remain OPEN, but got {r2_after_edge_ack['status']}!"
    print("  ✅ SUCCESS: Central NOC ignored edge ACK and remained OPEN!")

    # 5. Now Snooze on Central NOC (Instance 2)
    print("\n5. Snoozing alert on Central NOC (port 8083)...")
    r_snooze_i2 = requests.post(f"{I2_UI}/api/v1/alerts/{ident}/snooze", json={
        "duration_minutes": 15,
        "reason": "Central NOC dispatching maintenance team"
    })
    assert r_snooze_i2.status_code == 200
    r2_snooze = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Central NOC status: status={r2_snooze['status']}, snooze_until={r2_snooze['snooze_until']}")
    assert r2_snooze["status"] == "SNOOZED"

    # 6. Send repeated trap from Instance 1
    print("\n6. Sending repeated trap from edge Instance 1 (tally bump)...")
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "edge-switch-01",
        "alert_key": "PORT_DOWN",
        "severity": "MAJOR",
        "summary": "Port GigabitEthernet0/1 Link Down (trap 2)",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(2.0)
    r2_after_trap = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Central NOC after trap: tally={r2_after_trap['tally']}, status={r2_after_trap['status']}")
    assert r2_after_trap["tally"] >= 2
    assert r2_after_trap["status"] == "SNOOZED", "Central NOC snooze lease was lost!"
    print("  ✅ SUCCESS: Central NOC operator lease preserved during edge telemetry sync!")

    # 7. Clear event from Instance 1
    print("\n7. Sending CLEAR event from Instance 1...")
    requests.post(f"{I1_API}/api/v1/ingest", json={
        "identifier": ident,
        "node": "edge-switch-01",
        "alert_key": "PORT_DOWN",
        "severity": "CLEAR",
        "summary": "Port GigabitEthernet0/1 Link Up",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    })
    time.sleep(2.0)
    r2_clear = requests.get(f"{I2_API}/api/v1/alerts/{ident}").json()
    print(f"  -> Central NOC after CLEAR: status={r2_clear['status']}")
    assert r2_clear["status"] == "RESOLVED"
    print("  ✅ SUCCESS: Hardware CLEAR successfully resolved alert on Central NOC!")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED: Central NOC is the exclusive workflow authority!")
    print("=" * 70)

if __name__ == "__main__":
    main()
