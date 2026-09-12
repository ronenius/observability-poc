#!/usr/bin/env python3
"""
Net-SNMP snmptrapd Handler Script
Invoked by Net-SNMP daemon whenever a trap is received on UDP port 162/1162.
Reads standard Net-SNMP stdin, parses MIB varbinds, normalizes the alert,
and forwards it to the NOC Alert Platform Ingestion API.
"""

import os
import sys
import re
import json
import logging
import requests

INGEST_URL = os.getenv("INGEST_URL", "http://instance1-api:8081/api/v1/ingest")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SNMPTRAPD-HANDLER] %(levelname)s: %(message)s"
)

def main():
    lines = [line.strip() for line in sys.stdin.readlines() if line.strip()]
    if len(lines) < 2:
        return

    raw_host = lines[0]
    transport = lines[1]
    varbind_lines = lines[2:]

    # Extract sender IP from transport line, e.g. UDP: [192.168.1.50]:54321->...
    sender_ip = raw_host
    match = re.search(r"\[([0-9a-fA-F\.\:]+)\]", transport)
    if match:
        sender_ip = match.group(1)

    # Parse OID -> Value mappings
    varbinds = {}
    trap_oid = "unknown"
    for line in varbind_lines:
        parts = line.split(None, 1)
        if len(parts) == 2:
            oid, val = parts[0], parts[1]
            varbinds[oid] = val
            if "snmpTrapOID" in oid or oid.endswith(".1.3.6.1.6.3.1.1.4.1.0"):
                trap_oid = val
        elif len(parts) == 1:
            varbinds[parts[0]] = ""

    # Determine node name
    node = sender_ip
    for k, v in varbinds.items():
        if "sysName" in k:
            node = v
            break

    # Determine interface if present
    if_name = None
    for k, v in varbinds.items():
        if "ifDescr" in k or "ifName" in k:
            if_name = v
            break
        elif "ifIndex" in k:
            if_name = f"ifIndex-{v}"

    # Map Trap types to NOC Severity and Summaries
    trap_lower = trap_oid.lower()
    if "linkdown" in trap_lower or trap_oid.endswith("1.3.6.1.6.3.1.1.5.3"):
        target_if = if_name or "interface-0"
        alert_key = f"linkDown:{target_if}"
        severity = "CRITICAL"
        summary = f"SNMP linkDown: Interface {target_if} on {node} is DOWN"
    elif "linkup" in trap_lower or trap_oid.endswith("1.3.6.1.6.3.1.1.5.4"):
        target_if = if_name or "interface-0"
        alert_key = f"linkDown:{target_if}"
        severity = "CLEAR"
        summary = f"SNMP linkUp: Interface {target_if} on {node} is restored UP"
    elif "coldstart" in trap_lower or trap_oid.endswith("1.3.6.1.6.3.1.1.5.1"):
        alert_key = "coldStart"
        severity = "WARNING"
        summary = f"SNMP coldStart: System rebooted (Cold boot) on {node}"
    elif "warmstart" in trap_lower or trap_oid.endswith("1.3.6.1.6.3.1.1.5.2"):
        alert_key = "warmStart"
        severity = "INFO"
        summary = f"SNMP warmStart: System re-initialized (Warm boot) on {node}"
    elif "auth" in trap_lower or "authenticationfailure" in trap_lower or trap_oid.endswith("1.3.6.1.6.3.1.1.5.5"):
        alert_key = "snmp_auth_failure"
        severity = "WARNING"
        summary = f"SNMP authenticationFailure: Unauthorized SNMP access attempt on {node}"
    else:
        alert_key = f"snmp:{trap_oid.split('::')[-1]}"
        severity = "MAJOR"
        summary = f"SNMP Trap [{trap_oid}] received from {node}"

    payload = {
        "node": node,
        "alert_key": alert_key,
        "severity": severity,
        "summary": summary,
        "custom_fields": {
            "source": "snmptrapd",
            "sender_ip": sender_ip,
            "transport": transport,
            "trap_oid": trap_oid,
            "varbinds": varbinds
        }
    }

    try:
        r = requests.post(INGEST_URL, json=payload, timeout=3.0)
        logging.info(f"Forwarded trap to {INGEST_URL}: {r.status_code} ({alert_key})")
    except Exception as e:
        logging.error(f"Failed to post trap to {INGEST_URL}: {e}")

if __name__ == "__main__":
    main()
