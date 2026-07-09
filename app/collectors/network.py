from __future__ import annotations

import re
import socket
import struct
from pathlib import Path

import psutil

from app.utils import format_bytes, host_path

TCP_STATES = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}


def _hex_ip(hex_addr: str) -> str:
    if len(hex_addr) != 8:
        return hex_addr
    try:
        packed = struct.pack("<I", int(hex_addr, 16))
        return socket.inet_ntoa(packed)
    except (struct.error, ValueError, OSError):
        return hex_addr


def _parse_proc_net(path: Path, proto: str) -> list[dict]:
    sockets: list[dict] = []
    if not path.exists():
        return sockets

    inode_to_proc: dict[str, str] = {}
    try:
        for conn in psutil.net_connections(kind=proto.lower()):
            if conn.status != psutil.CONN_LISTEN:
                continue
            if conn.laddr and conn.pid:
                proc_name = "unknown"
                try:
                    proc_name = psutil.Process(conn.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                sockets.append(
                    {
                        "port": conn.laddr.port,
                        "bind": conn.laddr.ip,
                        "proto": proto,
                        "process": proc_name,
                        "status": "LISTEN",
                    }
                )
        return sorted(sockets, key=lambda s: s["port"])
    except (psutil.AccessDenied, PermissionError):
        pass

    try:
        for line in path.read_text(errors="ignore").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            local = parts[1]
            state = parts[3]
            if state != "0A":
                continue
            ip_hex, port_hex = local.split(":")
            port = int(port_hex, 16)
            bind = _hex_ip(ip_hex)
            inode = parts[9]
            process = inode_to_proc.get(inode, "unknown")
            sockets.append(
                {
                    "port": port,
                    "bind": bind,
                    "proto": proto,
                    "process": process,
                    "status": TCP_STATES.get(state, "LISTEN"),
                }
            )
    except OSError:
        pass

    return sorted(sockets, key=lambda s: s["port"])


def collect_listening_sockets() -> list[dict]:
    tcp = _parse_proc_net(host_path("proc/net/tcp"), "TCP")
    udp = _parse_proc_net(host_path("proc/net/udp"), "UDP")
    seen: set[tuple] = set()
    merged: list[dict] = []
    for sock in tcp + udp:
        key = (sock["port"], sock["bind"], sock["proto"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(sock)
    return merged


def collect_network_interfaces() -> list[dict]:
    interfaces: list[dict] = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_io_counters(pernic=True)

    for name, addr_list in addrs.items():
        ip = "—"
        mac = "—"
        for addr in addr_list:
            if addr.family == socket.AF_INET:
                ip = addr.address
            elif addr.family == psutil.AF_LINK:
                mac = addr.address

        rx = tx = "0 B"
        if name in stats:
            rx = format_bytes(stats[name].bytes_recv)
            tx = format_bytes(stats[name].bytes_sent)

        interfaces.append(
            {
                "name": name,
                "ip": ip,
                "mac": mac,
                "rx": rx,
                "tx": tx,
            }
        )

    return interfaces
