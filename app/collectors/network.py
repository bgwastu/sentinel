from __future__ import annotations

import os
import re
import socket
import struct
import time
import urllib.request
from pathlib import Path

import psutil

from app.utils import format_bytes, host_path

TCP_STATES = {
    "01": "ESTABLISHED",
    "0A": "LISTEN",
}

PUBLIC_IP_CACHE_TTL = 3600
_public_ip_cache: tuple[str | None, float] = (None, 0.0)


def _hex_ip(hex_addr: str) -> str:
    if len(hex_addr) != 8:
        return hex_addr
    try:
        packed = struct.pack("<I", int(hex_addr, 16))
        return socket.inet_ntoa(packed)
    except (struct.error, ValueError, OSError):
        return hex_addr


def _hex_ip6(hex_addr: str) -> str:
    if len(hex_addr) != 32:
        return hex_addr
    try:
        packed = bytes.fromhex(hex_addr)
        return socket.inet_ntop(socket.AF_INET6, packed)
    except (OSError, ValueError):
        return hex_addr


def _build_socket_inode_map() -> dict[str, tuple[int, str]]:
    """Map socket inode string -> (pid, process name)."""
    inode_map: dict[str, tuple[int, str]] = {}
    proc_root = host_path("proc")
    if not proc_root.exists():
        proc_root = Path("/proc")

    for pid_dir in proc_root.iterdir():
        if not pid_dir.name.isdigit():
            continue
        pid = int(pid_dir.name)
        try:
            proc_name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            proc_name = "unknown"

        fd_dir = pid_dir / "fd"
        if not fd_dir.is_dir():
            continue
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                match = re.match(r"socket:\[(\d+)\]", target)
                if match:
                    inode_map[match.group(1)] = (pid, proc_name)
        except (OSError, PermissionError):
            continue

    return inode_map


def _parse_proc_listen(path: Path, proto: str, inode_map: dict[str, tuple[int, str]], ipv6: bool = False) -> list[dict]:
    sockets: list[dict] = []
    if not path.exists():
        return sockets

    try:
        for line in path.read_text(errors="ignore").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            if parts[3] != "0A":
                continue
            local = parts[1]
            if ":" not in local:
                continue
            ip_hex, port_hex = local.rsplit(":", 1)
            port = int(port_hex, 16)
            bind = _hex_ip6(ip_hex) if ipv6 else _hex_ip(ip_hex)
            inode = parts[9]
            pid, proc_name = inode_map.get(inode, (None, "unknown"))
            if pid and proc_name == "unknown":
                try:
                    proc_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            sockets.append(
                {
                    "port": port,
                    "bind": bind,
                    "proto": proto,
                    "process": proc_name,
                    "status": "LISTEN",
                }
            )
    except OSError:
        pass

    return sockets


def _normalize_bind(bind: str) -> str:
    if bind in {"0.0.0.0", "::", "*"}:
        return "*"
    if bind in {"127.0.0.1", "::1"}:
        return "127.0.0.1"
    return bind


def _dedupe_dual_stack_sockets(sockets: list[dict]) -> list[dict]:
    """Collapse IPv4/IPv6 dual-stack duplicates (0.0.0.0 + ::, 127.0.0.1 + ::1)."""
    grouped: dict[tuple[int, str], dict] = {}
    for sock in sockets:
        key = (sock["port"], sock["proto"])
        bind = _normalize_bind(sock["bind"])
        existing = grouped.get(key)
        if not existing:
            grouped[key] = {**sock, "bind": bind}
            continue
        if existing["process"] == "unknown" and sock["process"] != "unknown":
            existing["process"] = sock["process"]
    return list(grouped.values())


def collect_listening_sockets() -> list[dict]:
    inode_map = _build_socket_inode_map()
    tcp4 = _parse_proc_listen(host_path("proc/net/tcp"), "TCP", inode_map, ipv6=False)
    tcp6 = _parse_proc_listen(host_path("proc/net/tcp6"), "TCP", inode_map, ipv6=True)
    udp4 = _parse_proc_listen(host_path("proc/net/udp"), "UDP", inode_map, ipv6=False)
    udp6 = _parse_proc_listen(host_path("proc/net/udp6"), "UDP", inode_map, ipv6=True)

    merged = _dedupe_dual_stack_sockets(tcp4 + tcp6 + udp4 + udp6)

    if not merged:
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                    continue
                proc_name = "unknown"
                if conn.pid:
                    try:
                        proc_name = psutil.Process(conn.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                merged.append(
                    {
                        "port": conn.laddr.port,
                        "bind": conn.laddr.ip,
                        "proto": "TCP" if conn.type == socket.SOCK_STREAM else "UDP",
                        "process": proc_name,
                        "status": "LISTEN",
                    }
                )
        except (psutil.AccessDenied, PermissionError):
            pass

    merged = _dedupe_dual_stack_sockets(merged)
    return sorted(merged, key=lambda s: (s["port"], s["bind"]))


def get_public_ip() -> str | None:
    global _public_ip_cache
    env_ip = os.environ.get("PUBLIC_IP", "").strip()
    if env_ip:
        return env_ip

    cached_ip, cached_at = _public_ip_cache
    if cached_ip and (time.time() - cached_at) < PUBLIC_IP_CACHE_TTL:
        return cached_ip

    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=4) as resp:
            import json

            data = json.loads(resp.read().decode())
            ip = data.get("ip")
            if ip:
                _public_ip_cache = (ip, time.time())
                return ip
    except Exception:
        pass

    for nic, addrs in psutil.net_if_addrs().items():
        if nic.startswith(("lo", "docker", "br-", "veth")):
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            ip = addr.address
            if ip.startswith(("10.", "172.", "192.168.", "127.")):
                continue
            _public_ip_cache = (ip, time.time())
            return ip

    return cached_ip


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
