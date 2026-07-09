from __future__ import annotations

import json
import os
import platform
import socket
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import psutil

from app.config import HISTORY_PATH, HISTORY_SIZE, HOST_PREFIX, SPARKLINE_INTERVAL
from app.utils import format_bytes_per_sec, format_uptime, gb, host_path


_cpu_primed = False
_persist_counter = 0


def _timestamp_epoch(offset_seconds: float = 0.0) -> float:
    return round(time.time() - offset_seconds, 3)


@dataclass
class MetricHistory:
    cpu: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    memory: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    disk: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    network: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    lock: Lock = field(default_factory=Lock)
    _last_net: dict[str, tuple[int, int, float]] = field(default_factory=dict)
    _initialized: bool = False

    def load(self) -> None:
        if not HISTORY_PATH.exists():
            return
        try:
            data = json.loads(HISTORY_PATH.read_text())
            with self.lock:
                for key in ("cpu", "memory", "disk", "network"):
                    values = data.get(key, [])
                    getattr(self, key).extend(values[-HISTORY_SIZE:])
                raw_ts = data.get("timestamps", [])[-HISTORY_SIZE:]
                for value in raw_ts:
                    if isinstance(value, (int, float)):
                        self.timestamps.append(float(value))
                if len(self.cpu) >= HISTORY_SIZE:
                    self._initialized = True
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    def _persist(self) -> None:
        global _persist_counter
        _persist_counter += 1
        if _persist_counter % 5 != 0:
            return
        try:
            HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cpu": list(self.cpu),
                "memory": list(self.memory),
                "disk": list(self.disk),
                "network": list(self.network),
                "timestamps": list(self.timestamps),
            }
            tmp = HISTORY_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(HISTORY_PATH)
        except OSError:
            pass

    def seed(self, cpu: float, mem_pct: float, disk_pct: float, net_rate: float) -> None:
        with self.lock:
            if self._initialized:
                return
            for i in range(HISTORY_SIZE):
                offset = (HISTORY_SIZE - 1 - i) * SPARKLINE_INTERVAL
                self.cpu.append(cpu)
                self.memory.append(mem_pct)
                self.disk.append(disk_pct)
                self.network.append(net_rate)
                self.timestamps.append(_timestamp_epoch(offset))
            self._initialized = True
            self._persist()

    def append(self, cpu: float, mem_pct: float, disk_pct: float, net_rate: float) -> None:
        with self.lock:
            self.cpu.append(cpu)
            self.memory.append(mem_pct)
            self.disk.append(disk_pct)
            self.network.append(net_rate)
            self.timestamps.append(_timestamp_epoch())
            self._persist()

    def snapshot(self) -> dict[str, list]:
        with self.lock:
            cpu = list(self.cpu)
            memory = list(self.memory)
            disk = list(self.disk)
            network = list(self.network)
            timestamps = list(self.timestamps)

        while len(cpu) < HISTORY_SIZE:
            cpu.insert(0, cpu[0] if cpu else 0.0)
        while len(memory) < HISTORY_SIZE:
            memory.insert(0, memory[0] if memory else 0.0)
        while len(disk) < HISTORY_SIZE:
            disk.insert(0, disk[0] if disk else 0.0)
        while len(network) < HISTORY_SIZE:
            network.insert(0, network[0] if network else 0.0)
        while len(timestamps) < HISTORY_SIZE:
            timestamps.insert(0, timestamps[0] if timestamps else _timestamp_epoch())

        return {
            "cpu": cpu[-HISTORY_SIZE:],
            "memory": memory[-HISTORY_SIZE:],
            "disk": disk[-HISTORY_SIZE:],
            "network": network[-HISTORY_SIZE:],
            "timestamps": timestamps[-HISTORY_SIZE:],
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
    global _cpu_primed
    try:
        if not _cpu_primed:
            psutil.cpu_percent(interval=0.1)
            _cpu_primed = True
        return round(psutil.cpu_percent(interval=None), 1)
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
