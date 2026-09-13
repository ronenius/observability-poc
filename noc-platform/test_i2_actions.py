#!/usr/bin/env python3
"""
Test operator actions (Snooze, Unsnooze, Patch) directly through Instance 2
via both Instance 2 API (8082) and Instance 2 Web UI Nginx Proxy (8083).
"""

import requests
import time
from datetime import datetime, timezone

I1_API = "http://192.168.194.183:8081"
I2_API = "http://192.168.194.159:8082"
I2_UI = "http://192.168.194.177:8083"

def test_instance2_operator_actions():
    ident = f"test-i2-snooze-{int(time.time())}"
    print(f"\n1. Ingesting alert {ident} on Instance 1...")
    payload = {
        "identifier": ident,
        "node": "switch-leaf-04",
        "alert_key": "FAN_FAILURE",
        "severity": "MAJOR",
        "summary": "Chassis fan tray #2 failed",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    }
    r = requests.post(f"{I1_API}/api/v1/ingest", json=payload)
    assert r.status_code == 200

    # Wait for replication to Instance 2
    time.sleep(1.5)
    r = requests.get(f"{I2_API}/api/v1/alerts/{ident}")
    assert r.status_code == 200
    print(f"Alert replicated to Instance 2: status={r.json()['status']}")

    # 2. Test SNOOZE via Instance 2 Web UI Nginx Proxy (8083)
    print(f"\n2. Snoozing alert via Instance 2 Web UI Proxy (port 8083)...")
    snooze_payload = {
        "duration_minutes": 10,
        "reason": "Fan replacement ticket #9921"
    }
    r = requests.post(f"{I2_UI}/api/v1/alerts/{ident}/snooze", json=snooze_payload)
    print(f"Response code: {r.status_code}")
    assert r.status_code == 200, f"Snooze failed on Instance 2: {r.text}"
    snoozed = r.json()
    print(f"Instance 2 snooze result: status={snoozed['status']}, snooze_until={snoozed['snooze_until']}")
    assert snoozed['status'] == 'SNOOZED'
    assert snoozed['snooze_until'] is not None

    # Check Instance 1 was also updated
    time.sleep(0.5)
    r1 = requests.get(f"{I1_API}/api/v1/alerts?search={ident}")
    assert r1.status_code == 200
    alert_i1 = r1.json()[0]
    print(f"Instance 1 status: {alert_i1['status']}, snooze_until: {alert_i1.get('snooze_until')}")
    assert alert_i1['status'] == 'SNOOZED'

    # 3. Test UNSNOOZE via Instance 2 Web UI Proxy (8083)
    print(f"\n3. Awaking alert via Instance 2 Web UI Proxy (port 8083)...")
    r = requests.post(f"{I2_UI}/api/v1/alerts/{ident}/unsnooze")
    assert r.status_code == 200
    awakened = r.json()
    print(f"Instance 2 awaken result: status={awakened['status']}, snooze_until={awakened['snooze_until']}")
    assert awakened['status'] == 'OPEN'
    assert awakened['snooze_until'] is None

    # 4. Test ACK via Instance 2 Web UI Proxy (8083)
    print(f"\n4. Acknowledging alert via Instance 2 Web UI Proxy...")
    r = requests.patch(f"{I2_UI}/api/v1/alerts/{ident}", json={"status": "ACKNOWLEDGED"})
    assert r.status_code == 200
    acked = r.json()
    print(f"Instance 2 ACK result: status={acked['status']}")
    assert acked['status'] == 'ACKNOWLEDGED'

    print("\n✅ All operator actions on Instance 2 (Snooze, Awaken, Patch) work perfectly!")

if __name__ == "__main__":
    test_instance2_operator_actions()
