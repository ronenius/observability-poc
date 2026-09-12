#!/usr/bin/env python3
"""
CLI Utility to send real SNMP Traps to the Net-SNMP snmptrapd daemon.
Works using the native macOS / Linux `snmptrap` command or direct UDP.
"""

import sys
import argparse
import subprocess
import shutil

SNMPTRAPD_HOST = "192.168.194.99"
SNMPTRAPD_PORT = "1162"

PRESETS = {
    "linkdown": {
        "oid": "1.3.6.1.6.3.1.1.5.3",
        "name": "IF-MIB::linkDown",
        "varbinds": [
            ("1.3.6.1.2.1.1.5.0", "s", "core-router-01.lon"),
            ("1.3.6.1.2.1.2.2.1.1.8", "i", "8"),
            ("1.3.6.1.2.1.2.2.1.2.8", "s", "HundredGigE0/1/0/8"),
            ("1.3.6.1.2.1.2.2.1.8.8", "i", "2"),  # down
        ]
    },
    "linkup": {
        "oid": "1.3.6.1.6.3.1.1.5.4",
        "name": "IF-MIB::linkUp (Auto-Clears linkDown)",
        "varbinds": [
            ("1.3.6.1.2.1.1.5.0", "s", "core-router-01.lon"),
            ("1.3.6.1.2.1.2.2.1.1.8", "i", "8"),
            ("1.3.6.1.2.1.2.2.1.2.8", "s", "HundredGigE0/1/0/8"),
            ("1.3.6.1.2.1.2.2.1.8.8", "i", "1"),  # up
        ]
    },
    "coldstart": {
        "oid": "1.3.6.1.6.3.1.1.5.1",
        "name": "SNMPv2-MIB::coldStart",
        "varbinds": [
            ("1.3.6.1.2.1.1.5.0", "s", "edge-firewall-01.nyc"),
            ("1.3.6.1.2.1.1.1.0", "s", "Cisco Adaptive Security Appliance Software Version 9.18(3)"),
        ]
    },
    "authfail": {
        "oid": "1.3.6.1.6.3.1.1.5.5",
        "name": "SNMPv2-MIB::authenticationFailure",
        "varbinds": [
            ("1.3.6.1.2.1.1.5.0", "s", "spine-switch-04.pdx"),
        ]
    }
}

def send_trap(preset_name, host=SNMPTRAPD_HOST, port=SNMPTRAPD_PORT, community="public"):
    if preset_name not in PRESETS:
        print(f"Unknown preset: {preset_name}. Choose from: {list(PRESETS.keys())}")
        return False

    preset = PRESETS[preset_name]
    target = f"{host}:{port}"
    print(f"🚀 Sending SNMP Trap [{preset['name']}] to Net-SNMP daemon at {target}...")

    cmd = ["snmptrap", "-v", "2c", "-c", community, target, "", preset["oid"]]
    for vb_oid, vb_type, vb_val in preset["varbinds"]:
        cmd.extend([vb_oid, vb_type, vb_val])

    if shutil.which("snmptrap"):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"✅ SNMP Trap successfully dispatched via Net-SNMP snmptrap utility!")
            print(f"   Command run: {' '.join(cmd)}")
            print(f"   Open Web UI: http://192.168.194.197:8080 to view in the alerts table!")
            return True
        else:
            print(f"snmptrap output: {res.stderr}")
            return False
    else:
        print("snmptrap binary not found on PATH.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send real SNMP traps to snmptrapd")
    parser.add_argument("type", choices=["linkdown", "linkup", "coldstart", "authfail"], nargs="?", default="linkdown", help="Trap preset to send")
    parser.add_argument("--host", default=SNMPTRAPD_HOST, help="snmptrapd IP")
    parser.add_argument("--port", default=SNMPTRAPD_PORT, help="UDP port (default 1162)")
    args = parser.parse_args()

    send_trap(args.type, args.host, args.port)
