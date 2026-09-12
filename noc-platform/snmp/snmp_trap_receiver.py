#!/usr/bin/env python3
"""
NOC Platform - Pure Python SNMP Trap Receiver Daemon
Listens on UDP ports 162 & 1162 for SNMP v1 and v2c traps.
Parses ASN.1/BER binary payload with zero external C-dependencies,
normalizes MIB-II & Enterprise traps into standard NOC alert envelopes,
and forwards them directly to the NOC Alert Ingestion Pipeline.
"""

import os
import sys
import json
import socket
import logging
import requests
import asyncio
from typing import Dict, Any, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SNMP-TRAPD] %(levelname)s: %(message)s"
)

INGEST_URL = os.getenv("INGEST_URL", "http://instance1-api:8081/api/v1/ingest")
PORT_162 = int(os.getenv("SNMP_PORT_162", "162"))
PORT_1162 = int(os.getenv("SNMP_PORT_1162", "1162"))

# Standard Well-Known SNMP Trap OIDs
STANDARD_TRAPS = {
    "1.3.6.1.6.3.1.1.5.1": ("coldStart", "WARNING", "SNMP coldStart: System rebooted (Cold boot)"),
    "1.3.6.1.6.3.1.1.5.2": ("warmStart", "INFO", "SNMP warmStart: System re-initialized (Warm boot)"),
    "1.3.6.1.6.3.1.1.5.3": ("linkDown", "CRITICAL", "SNMP linkDown: Network interface has gone DOWN"),
    "1.3.6.1.6.3.1.1.5.4": ("linkUp", "CLEAR", "SNMP linkUp: Network interface is restored UP"),
    "1.3.6.1.6.3.1.1.5.5": ("authenticationFailure", "WARNING", "SNMP authenticationFailure: Unauthorized SNMP packet received"),
    "1.3.6.1.6.3.1.1.5.6": ("egpNeighborLoss", "MAJOR", "SNMP egpNeighborLoss: Exterior gateway neighbor lost"),
}

# Standard Varbind OIDs for friendly labeling
KNOWN_VARBINDS = {
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.6.3.1.1.4.1.0": "snmpTrapOID",
    "1.3.6.1.6.3.1.1.4.3.0": "snmpTrapEnterprise",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.2.1.2.2.1.1": "ifIndex",
    "1.3.6.1.2.1.2.2.1.2": "ifDescr",
    "1.3.6.1.2.1.2.2.1.7": "ifAdminStatus",
    "1.3.6.1.2.1.2.2.1.8": "ifOperStatus",
    "1.3.6.1.2.1.31.1.1.1.1": "ifName",
    "1.3.6.1.2.1.31.1.1.1.18": "ifAlias",
}

# -------------------------------------------------------------
# Zero-Dependency ASN.1 / BER Decoder
# -------------------------------------------------------------

def parse_ber(data: bytes, idx: int = 0) -> Tuple[Optional[int], Any, int]:
    if idx >= len(data):
        return None, None, idx

    tag = data[idx]
    idx += 1
    if idx >= len(data):
        return None, None, idx

    length = data[idx]
    idx += 1
    if length & 0x80:
        n_bytes = length & 0x7F
        if idx + n_bytes > len(data):
            return None, None, len(data)
        length = int.from_bytes(data[idx:idx + n_bytes], "big")
        idx += n_bytes

    if idx + length > len(data):
        val_bytes = data[idx:]
        end_idx = len(data)
    else:
        val_bytes = data[idx:idx + length]
        end_idx = idx + length

    # Constructed (SEQUENCE 0x30 or Context-specific constructed >= 0xA0)
    if tag == 0x30 or (tag & 0x20):
        items = []
        sub_idx = 0
        while sub_idx < len(val_bytes):
            sub_tag, sub_val, sub_next = parse_ber(val_bytes, sub_idx)
            if sub_tag is None:
                break
            items.append((sub_tag, sub_val))
            sub_idx = sub_next
        return tag, items, end_idx

    elif tag == 0x02:  # INTEGER
        val = int.from_bytes(val_bytes, "big", signed=True) if val_bytes else 0
        return tag, val, end_idx

    elif tag == 0x04:  # OCTET STRING
        try:
            val = val_bytes.decode("utf-8")
        except UnicodeDecodeError:
            val = val_bytes.hex()
        return tag, val, end_idx

    elif tag == 0x06:  # OBJECT IDENTIFIER (OID)
        if not val_bytes:
            return tag, "0.0", end_idx
        oid_parts = [val_bytes[0] // 40, val_bytes[0] % 40]
        val = 0
        for b in val_bytes[1:]:
            val = (val << 7) | (b & 0x7F)
            if not (b & 0x80):
                oid_parts.append(val)
                val = 0
        oid_str = ".".join(str(x) for x in oid_parts)
        return tag, oid_str, end_idx

    elif tag == 0x40:  # IpAddress
        return tag, ".".join(str(b) for b in val_bytes), end_idx

    elif tag in (0x41, 0x42, 0x43):  # Counter32, Gauge32, TimeTicks
        val = int.from_bytes(val_bytes, "big") if val_bytes else 0
        return tag, val, end_idx

    elif tag == 0x05:  # NULL
        return tag, None, end_idx

    else:
        return tag, val_bytes.hex(), end_idx


def decode_snmp_packet(data: bytes, sender_addr: Tuple[str, int]) -> Optional[Dict[str, Any]]:
    try:
        tag, seq, _ = parse_ber(data)
        if tag != 0x30 or not isinstance(seq, list) or len(seq) < 3:
            return None

        # seq[0]: Version (0 = v1, 1 = v2c)
        raw_version = seq[0][1]
        version_str = "v1" if raw_version == 0 else ("v2c" if raw_version == 1 else f"v{raw_version+1}")

        # seq[1]: Community string
        community = seq[1][1]

        # seq[2]: PDU (0xA4 = Trap-PDU for v1, 0xA7 = SNMPv2-Trap-PDU for v2c)
        pdu_tag, pdu_val = seq[2]

        varbinds = {}
        trap_oid = "1.3.6.1.6.3.1.1.5.0"
        enterprise_oid = None
        generic_trap = 0
        specific_trap = 0
        agent_ip = sender_addr[0]

        if pdu_tag == 0xA7:  # SNMPv2-Trap-PDU
            # pdu_val items: [request_id, error_status, error_index, varbind_list]
            if len(pdu_val) >= 4 and isinstance(pdu_val[3][1], list):
                vb_list = pdu_val[3][1]
                for vb in vb_list:
                    if isinstance(vb[1], list) and len(vb[1]) >= 2:
                        vb_oid = vb[1][0][1]
                        vb_val = vb[1][1][1]
                        varbinds[vb_oid] = vb_val
                        if vb_oid == "1.3.6.1.6.3.1.1.4.1.0":  # snmpTrapOID
                            trap_oid = str(vb_val)

        elif pdu_tag == 0xA4:  # SNMPv1 Trap-PDU
            # [enterprise, agent_addr, generic_trap, specific_trap, time_stamp, varbind_list]
            if len(pdu_val) >= 6:
                enterprise_oid = pdu_val[0][1]
                agent_ip = pdu_val[1][1] or sender_addr[0]
                generic_trap = pdu_val[2][1]
                specific_trap = pdu_val[3][1]

                # Map generic trap to standard OID
                if 1 <= generic_trap <= 6:
                    trap_oid = f"1.3.6.1.6.3.1.1.5.{generic_trap}"
                else:
                    trap_oid = f"{enterprise_oid}.0.{specific_trap}"

                if isinstance(pdu_val[5][1], list):
                    for vb in pdu_val[5][1]:
                        if isinstance(vb[1], list) and len(vb[1]) >= 2:
                            varbinds[vb[1][0][1]] = vb[1][1][1]
        else:
            return None

        return {
            "version": version_str,
            "community": community,
            "sender_ip": sender_addr[0],
            "sender_port": sender_addr[1],
            "agent_ip": agent_ip,
            "trap_oid": trap_oid,
            "enterprise": enterprise_oid,
            "generic_trap": generic_trap,
            "specific_trap": specific_trap,
            "varbinds": varbinds
        }
    except Exception as e:
        logging.debug(f"Error parsing BER packet: {e}")
        return None

# -------------------------------------------------------------
# Alert Normalization Engine
# -------------------------------------------------------------

def normalize_snmp_alert(trap_info: Dict[str, Any]) -> Dict[str, Any]:
    trap_oid = trap_info["trap_oid"]
    sender_ip = trap_info["agent_ip"] or trap_info["sender_ip"]
    varbinds = trap_info["varbinds"]

    # Extract friendly device node name if present in varbinds
    node = sender_ip
    for k, v in varbinds.items():
        if k.startswith("1.3.6.1.2.1.1.5"):  # sysName
            node = str(v)
            break

    # Check for interface descriptor
    if_name = None
    for k, v in varbinds.items():
        if k.startswith("1.3.6.1.2.1.2.2.1.2") or k.startswith("1.3.6.1.2.1.31.1.1.1.1"):  # ifDescr / ifName
            if_name = str(v)
            break
        elif k.startswith("1.3.6.1.2.1.2.2.1.1"):  # ifIndex
            if_name = f"ifIndex-{v}"

    if trap_oid in STANDARD_TRAPS:
        name, default_sev, default_summary = STANDARD_TRAPS[trap_oid]
        if name in ("linkDown", "linkUp"):
            target_if = if_name or "interface-0"
            alert_key = f"linkDown:{target_if}"
            if name == "linkDown":
                severity = "CRITICAL"
                summary = f"SNMP linkDown: Interface {target_if} on {node} is DOWN"
            else:
                # linkUp clears the alert
                severity = "CLEAR"
                summary = f"SNMP linkUp: Interface {target_if} on {node} has recovered UP"
        else:
            alert_key = name
            severity = default_sev
            summary = f"{default_summary} on {node}"
    else:
        # Enterprise Trap
        alert_key = f"snmp:{trap_oid}"
        severity = "MAJOR"
        summary = f"Enterprise SNMP Trap [{trap_oid}] received from {node}"

    # Friendly varbind mapping for custom fields
    friendly_varbinds = {}
    for oid, val in varbinds.items():
        # Match prefix
        label = oid
        for prefix, name in KNOWN_VARBINDS.items():
            if oid.startswith(prefix):
                suffix = oid[len(prefix):]
                label = f"{name}{suffix}"
                break
        friendly_varbinds[label] = val

    custom_fields = {
        "source": "snmp-trap",
        "snmp_version": trap_info["version"],
        "community": trap_info["community"],
        "trap_oid": trap_oid,
        "sender_ip": trap_info["sender_ip"],
        "varbinds": friendly_varbinds
    }

    return {
        "node": node,
        "alert_key": alert_key,
        "severity": severity,
        "summary": summary,
        "custom_fields": custom_fields
    }

# -------------------------------------------------------------
# UDP Server Protocol
# -------------------------------------------------------------

class SnmpTrapProtocol(asyncio.DatagramProtocol):
    def __init__(self, port: int):
        self.port = port
        self.session = requests.Session()

    def connection_made(self, transport):
        self.transport = transport
        logging.info(f"🎧 Listening for SNMP Traps on UDP 0.0.0.0:{self.port}...")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        trap_info = decode_snmp_packet(data, addr)
        if not trap_info:
            logging.debug(f"Received non-SNMP datagram ({len(data)} bytes) from {addr}")
            return

        alert = normalize_snmp_alert(trap_info)
        logging.info(
            f"🔔 [SNMP TRAP INGEST] {alert['node']} | Trap: {trap_info['trap_oid']} "
            f"| Key: {alert['alert_key']} | Sev: {alert['severity']}"
        )

        # Forward to NOC Platform Ingestion API
        try:
            r = self.session.post(INGEST_URL, json=alert, timeout=3.0)
            if r.status_code in (200, 201):
                res_data = r.json()
                action = res_data.get("action", "processed")
                logging.info(f"✅ [POSTGRES SINK] Alert {alert['node']}:{alert['alert_key']} -> {action.upper()}")
            else:
                logging.warning(f"⚠️ Ingestion API error {r.status_code}: {r.text}")
        except Exception as e:
            logging.error(f"❌ Failed to forward SNMP alert to {INGEST_URL}: {e}")

# -------------------------------------------------------------
# Main Daemon Entrypoint
# -------------------------------------------------------------

async def main():
    loop = asyncio.get_running_loop()

    # Bind UDP 1162 (standard non-root trap port)
    await loop.create_datagram_endpoint(
        lambda: SnmpTrapProtocol(PORT_1162),
        local_addr=("0.0.0.0", PORT_1162)
    )

    # Attempt to bind UDP 162 (standard privileged SNMP port)
    try:
        await loop.create_datagram_endpoint(
            lambda: SnmpTrapProtocol(PORT_162),
            local_addr=("0.0.0.0", PORT_162)
        )
    except PermissionError:
        logging.warning(f"Port 162 requires root permissions; running on port {PORT_1162} only.")
    except Exception as e:
        logging.warning(f"Could not bind port 162: {e}")

    logging.info("🚀 SNMP Trap Ingestion Gateway is active.")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("SNMP Trap Receiver shutting down.")
