from __future__ import annotations

import os
import platform
import socket
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import psutil

from app.config import HISTORY_SIZE, HOST_PREFIX
from app.utils import format_bytes_per_sec, format_uptime, gb, host_path


@dataclass
class MetricHistory:
    cpu: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    memory: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    disk: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    network: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    lock: Lock = field(default_factory=Lock)
    _last_net: dict[str, tuple[int, int, float]] = field(default_factory=dict)
    _initialized: bool = False

    def seed(self, cpu: float, mem_pct: float, disk_pct: float, net_rate: float) -> None:
        with self.lock:
            if self._initialized:
                return
            for _ in range(HISTORY_SIZE):
                self.cpu.append(cpu)
                self.memory.append(mem_pct)
                self.disk.append(disk_pct)
                self.network.append(net_rate)
            self._initialized = True

    def append(self, cpu: float, mem_pct: float, disk_pct: float, net_rate: float) -> None:
        with self.lock:
            self.cpu.append(cpu)
            self.memory.append(mem_pct)
            self.disk.append(disk_pct)
            self.network.append(net_rate)

    def snapshot(self) -> dict[str, list[float]]:
        with self.lock:
            return {
                "cpu": list(self.cpu),
                "memory": list(self.memory),
                "disk": list(self.disk),
                "network": list(self.network),
            }


history = MetricHistory()


def _disk_usage_path() -> str:
    return str(HOST_PREFIX if HOST_PREFIX.exists() else Path("/"))


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def get_uptime() -> str:
    try:
        boot_path = host_path("proc/uptime")
        if boot_path.exists():
            uptime_seconds = float(boot_path.read_text().split()[0])
            return format_uptime(uptime_seconds)
        return format_uptime(time.time() - psutil.boot_time())
    except (OSError, ValueError, IndexError):
        return "unknown"


def get_load_avg() -> str:
    try:
        load_path = host_path("proc/loadavg")
        if load_path.exists():
            parts = load_path.read_text().split()[:3]
            return ", ".join(f"{float(x):.2f}" for x in parts)
        one, five, fifteen = os.getloadavg()
        return f"{one:.2f}, {five:.2f}, {fifteen:.2f}"
    except (OSError, ValueError):
        return "0.00, 0.00, 0.00"


def get_cpu_percent() -> float:
    try:
        return round(psutil.cpu_percent(interval=0.1), 1)
    except Exception:
        return 0.0


def get_memory() -> dict[str, float]:
    try:
        mem = psutil.virtual_memory()
        return {
            "total": gb(mem.total),
            "used": gb(mem.used),
            "free": gb(mem.available),
        }
    except Exception:
        return {"total": 0.0, "used": 0.0, "free": 0.0}


def get_disk() -> dict[str, float]:
    from pathlib import Path

    try:
        usage = psutil.disk_usage(_disk_usage_path())
        return {
            "total": gb(usage.total),
            "used": gb(usage.used),
            "free": gb(usage.free),
        }
    except Exception:
        return {"total": 0.0, "used": 0.0, "free": 0.0}


def _physical_interfaces() -> list[str]:
    names: list[str] = []
    try:
        stats = psutil.net_if_stats()
        for name, stat in stats.items():
            if stat.isup and not name.startswith(("lo", "docker", "br-", "veth")):
                names.append(name)
    except Exception:
        pass
    return names or ["eth0"]


def get_network_rate() -> tuple[str, float, str]:
    """Return (formatted rate, bytes/sec, primary interface name)."""
    now = time.time()
    total_rate = 0.0
    primary = _physical_interfaces()[0] if _physical_interfaces() else "eth0"

    try:
        counters = psutil.net_io_counters(pernic=True)
        for iface in _physical_interfaces():
            if iface not in counters:
                continue
            c = counters[iface]
            prev = history._last_net.get(iface)
            if prev:
                prev_rx, prev_tx, prev_t = prev
                dt = max(now - prev_t, 0.001)
                total_rate += ((c.bytes_recv - prev_rx) + (c.bytes_sent - prev_tx)) / dt
            history._last_net[iface] = (c.bytes_recv, c.bytes_sent, now)
            primary = iface
    except Exception:
        pass

    return format_bytes_per_sec(total_rate), total_rate, primary


def get_kernel_label() -> str:
    try:
        return platform.machine().lower()
    except Exception:
        return "linux"


def collect_host_snapshot() -> dict:
    cpu = get_cpu_percent()
    memory = get_memory()
    disk = get_disk()
    mem_pct = round((memory["used"] / memory["total"]) * 100, 1) if memory["total"] else 0.0
    disk_pct = round((disk["used"] / disk["total"]) * 100, 1) if disk["total"] else 0.0
    net_label, net_rate, net_iface = get_network_rate()

    history.seed(cpu, mem_pct, disk_pct, net_rate)

    return {
        "hostname": get_hostname(),
        "uptime": get_uptime(),
        "cores": psutil.cpu_count(logical=True) or 1,
        "load": get_load_avg(),
        "cpu": cpu,
        "memory": memory,
        "disk": disk,
        "network": {"rate": net_label, "interface": net_iface},
        "kernel": get_kernel_label(),
        "history": history.snapshot(),
    }
