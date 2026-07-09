from __future__ import annotations

import re
from pathlib import Path


def host_path(relative: str) -> Path:
    from app.config import HOST_PREFIX

    rel = relative.lstrip("/")
    return HOST_PREFIX / rel


def format_bytes(num: int | float) -> str:
    value = float(num)
    if value < 0:
        value = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} B"
    return f"{value:.1f} {units[idx]}"


def format_bytes_per_sec(num: float) -> str:
    value = max(0.0, float(num))
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB/s"
    if value >= 1024:
        return f"{value / 1024:.1f} KB/s"
    return f"{int(value)} B/s"


def gb(value_bytes: int | float) -> float:
    return round(float(value_bytes) / (1024**3), 1)


def parse_size_to_bytes(size_str: str) -> float:
    match = re.match(r"^([\d.]+)\s*(B|KB|MB|GB|TB)$", size_str.strip(), re.I)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return value * multipliers.get(unit, 1)


def format_uptime(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)
