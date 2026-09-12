#!/usr/bin/env python3
"""
CLI Utility to send standard Syslog messages (RFC 5424 / RFC 3164) over TCP or UDP
to the Vector ingress pipeline at port 5140.
"""

import socket
import argparse
from datetime import datetime, timezone

VECTOR_HOST = "192.168.194.187"
VECTOR_PORT = 5140

PRESETS = {
    "bgp_down": {
        "pri": 11,  # facility user (1), severity error (3) -> 1*8 + 3 = 11 (MAJOR)
        "host": "core-router-01.lon",
        "app": "bgp",
        "procid": "4491",
        "msgid": "BGP-5-ADJCHANGE",
        "msg": "neighbor 10.254.20.1 Down - BGP notification received: hold timer expired"
    },
    "ospf_down": {
        "pri": 11,  # MAJOR
        "host": "dist-switch-03.fra",
        "app": "ospf",
        "procid": "2104",
        "msgid": "OSPF-5-ADJCHANGE",
        "msg": "neighbor 172.16.88.2 on Vlan100 from FULL to DOWN: Inactivity timer expired"
    },
    "disk_critical": {
        "pri": 10,  # CRITICAL (facility 1, sev 2 -> 1*8+2=10)
        "host": "storage-filer-02.ams",
        "app": "systemd",
        "procid": "1",
        "msgid": "DISK_ALERT",
        "msg": "Root volume /data is at 98% capacity. Immediate cleanup required."
    },
    "service_restart": {
        "pri": 12,  # WARNING
        "host": "api-gateway-node-09",
        "app": "envoy",
        "procid": "8902",
        "msgid": "CIRCUIT_BREAKER",
        "msg": "Upstream cluster payment-backend reached max pending requests limit (500). Trip engaged."
    }
}

def send_syslog(preset_name, proto="tcp", host=VECTOR_HOST, port=VECTOR_PORT):
    if preset_name not in PRESETS:
        print(f"Unknown preset: {preset_name}. Choose from: {list(PRESETS.keys())}")
        return

    p = PRESETS[preset_name]
    now = datetime.now(timezone.utc).isoformat()
    # RFC 5424 formatted string
    rfc5424_msg = f"<{p['pri']}>1 {now} {p['host']} {p['app']} {p['procid']} {p['msgid']} - {p['msg']}\n"

    print(f"🚀 Sending Syslog ({proto.upper()}) to Vector at {host}:{port}...")
    print(f"   Payload: {rfc5424_msg.strip()}")

    if proto.lower() == "tcp":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.sendall(rfc5424_msg.encode("utf-8"))
        s.close()
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(rfc5424_msg.encode("utf-8"), (host, port))
        s.close()

    print(f"✅ Syslog message dispatched successfully!")
    print(f"   Open Web UI: http://192.168.194.197:8080 to view in the alerts table!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send RFC 5424 Syslog messages to Vector")
    parser.add_argument("type", choices=["bgp_down", "ospf_down", "disk_critical", "service_restart"], nargs="?", default="bgp_down")
    parser.add_argument("--proto", choices=["tcp", "udp"], default="tcp", help="Protocol (tcp or udp)")
    parser.add_argument("--host", default=VECTOR_HOST, help="Vector IP")
    parser.add_argument("--port", type=int, default=VECTOR_PORT, help="Port (default 5140)")
    args = parser.parse_args()

    send_syslog(args.type, args.proto, args.host, args.port)
