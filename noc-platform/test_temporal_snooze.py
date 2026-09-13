#!/usr/bin/env python3
"""
Test script to verify Snooze & Temporal Engine (Issue 16)
1. Send test alert
2. Snooze it for 1 minute
3. Verify status = SNOOZED, snooze_until is populated
4. Verify Instance 2 replication
5. Verify suppressed from ACTIVE filter
6. Wait for Temporal Engine to awaken it back to OPEN
7. Verify outbox replication of wakeup to Instance 2
8. Test manual unsnooze on a second alert
"""

import time
import requests
import json
from datetime import datetime, timezone

I1_API = "http://192.168.194.183:8081"
I2_API = "http://192.168.194.159:8082"

def test_snooze_and_temporal_engine():
    ident = f"test-snooze-temporal-{int(time.time())}"
    print(f"\n--- STEP 1: Ingesting new test alert: {ident} ---")
    payload = {
        "identifier": ident,
        "node": "switch-core-01",
        "alert_key": "BGP_SESSION_DOWN",
        "severity": "CRITICAL",
        "summary": "BGP Peer 10.0.0.1 session down on core-01",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat(),
        "custom_fields": {"peer_ip": "10.0.0.1", "as_number": 65001}
    }
    r = requests.post(f"{I1_API}/api/v1/ingest", json=payload)
    assert r.status_code == 200, f"Ingest failed: {r.text}"
    # Fetch the ingested alert to verify
    time.sleep(0.5)
    r = requests.get(f"{I1_API}/api/v1/alerts?search={ident}")
    alerts = r.json()
    assert len(alerts) > 0, "Alert not found after ingestion"
    alert_v1 = alerts[0]
    print(f"Ingested alert: status={alert_v1['status']}, version={alert_v1['version']}")
    assert alert_v1['status'] == 'OPEN'

    time.sleep(1)

    print(f"\n--- STEP 2: Snoozing alert for 1 minute (duration_minutes=1) ---")
    snooze_req = {
        "duration_minutes": 1,
        "reason": "Scheduled core maintenance window #TEMPORAL-16"
    }
    r = requests.post(f"{I1_API}/api/v1/alerts/{ident}/snooze", json=snooze_req)
    assert r.status_code == 200, f"Snooze failed: {r.text}"
    snoozed_alert = r.json()
    print(f"Snoozed response: status={snoozed_alert['status']}, snooze_until={snoozed_alert['snooze_until']}, version={snoozed_alert['version']}")
    assert snoozed_alert['status'] == 'SNOOZED'
    assert snoozed_alert['snooze_until'] is not None

    print(f"\n--- STEP 3: Verifying suppression from ACTIVE queue on Instance 1 ---")
    r = requests.get(f"{I1_API}/api/v1/alerts?status=ACTIVE")
    active_alerts = r.json()
    found_in_active = any(a['identifier'] == ident for a in active_alerts)
    print(f"Present in ACTIVE list: {found_in_active} (expected: False)")
    assert not found_in_active, "Snoozed alert should NOT appear in ACTIVE queue!"

    print(f"\n--- STEP 4: Verifying presence in SNOOZED queue on Instance 1 ---")
    r = requests.get(f"{I1_API}/api/v1/alerts?status=SNOOZED")
    snoozed_list = r.json()
    found_in_snoozed = any(a['identifier'] == ident for a in snoozed_list)
    print(f"Present in SNOOZED list: {found_in_snoozed} (expected: True)")
    assert found_in_snoozed, "Snoozed alert MUST appear in SNOOZED queue!"

    print(f"\n--- STEP 5: Verifying Outbox CDC Replication to Instance 2 ---")
    time.sleep(2)
    r = requests.get(f"{I2_API}/api/v1/alerts?status=SNOOZED")
    i2_snoozed_list = r.json()
    i2_match = next((a for a in i2_snoozed_list if a['identifier'] == ident), None)
    print(f"Instance 2 alert found: {i2_match is not None}")
    assert i2_match is not None, "Snoozed alert must be replicated to Instance 2!"
    print(f"Instance 2 alert status: {i2_match['status']}, snooze_until: {i2_match['snooze_until']}")
    assert i2_match['status'] == 'SNOOZED'

    print(f"\n--- STEP 6: Waiting for Temporal Engine to awaken alert (sleeping ~62 seconds)... ---")
    # Snooze until was 60s from start. Let's poll every 5s until it awakens
    start_wait = time.time()
    awakened = False
    for attempt in range(20):
        time.sleep(5)
        elapsed = time.time() - start_wait
        r = requests.get(f"{I1_API}/api/v1/alerts?search={ident}")
        items = r.json()
        if items and items[0]['status'] == 'OPEN':
            awakened = True
            print(f"🎉 Alert automatically awakened by Temporal Engine at +{elapsed:.1f}s! Status: {items[0]['status']}, version: {items[0]['version']}, snooze_until: {items[0].get('snooze_until')}")
            break
        else:
            status_now = items[0]['status'] if items else 'NONE'
            print(f"  [+{elapsed:.1f}s] status={status_now}...")

    assert awakened, "Temporal engine failed to awaken expired snoozed alert!"

    print(f"\n--- STEP 7: Verifying awakened alert reappeared in ACTIVE queue on Instance 1 ---")
    r = requests.get(f"{I1_API}/api/v1/alerts?status=ACTIVE")
    active_alerts = r.json()
    found_in_active = any(a['identifier'] == ident for a in active_alerts)
    print(f"Present in ACTIVE list: {found_in_active} (expected: True)")
    assert found_in_active, "Awakened alert MUST appear in ACTIVE queue!"

    print(f"\n--- STEP 8: Verifying awakened alert replicated to Instance 2 ---")
    time.sleep(2)
    r = requests.get(f"{I2_API}/api/v1/alerts?status=ACTIVE")
    i2_active_alerts = r.json()
    found_in_i2_active = any(a['identifier'] == ident for a in i2_active_alerts)
    print(f"Present in Instance 2 ACTIVE list: {found_in_i2_active} (expected: True)")
    assert found_in_i2_active, "Awakened alert must be replicated to Instance 2 as OPEN!"

    print(f"\n--- STEP 9: Testing Manual Un-snooze (Awaken) Action ---")
    ident2 = f"test-unsnooze-manual-{int(time.time())}"
    payload2 = {
        "identifier": ident2,
        "node": "router-border-02",
        "alert_key": "LINK_DEGRADED",
        "severity": "MAJOR",
        "summary": "High CRC error rate on TenGigE0/0/0/1",
        "first_occurrence": datetime.now(timezone.utc).isoformat(),
        "last_occurrence": datetime.now(timezone.utc).isoformat()
    }
    requests.post(f"{I1_API}/api/v1/ingest", json=payload2)
    time.sleep(0.5)
    # Snooze for 60 minutes
    requests.post(f"{I1_API}/api/v1/alerts/{ident2}/snooze", json={"duration_minutes": 60, "reason": "Testing manual wake"})
    r = requests.get(f"{I1_API}/api/v1/alerts?search={ident2}")
    assert r.json()[0]['status'] == 'SNOOZED'
    print(f"Created alert {ident2}, snoozed for 60m.")

    # Now manually unsnooze
    r = requests.post(f"{I1_API}/api/v1/alerts/{ident2}/unsnooze")
    assert r.status_code == 200
    unsnoozed_data = r.json()
    print(f"Manually awakened alert: status={unsnoozed_data['status']}, snooze_until={unsnoozed_data['snooze_until']}")
    assert unsnoozed_data['status'] == 'OPEN'
    assert unsnoozed_data['snooze_until'] is None

    print("\n✅ ALL TESTS PASSED SUCCESSFULLY! Snooze and Temporal Engine are fully operational!")

if __name__ == "__main__":
    test_snooze_and_temporal_engine()
