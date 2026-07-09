from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psutil

from app.config import HOST_PREFIX, IGNORED_FS_TYPES, SCAN_DIRECTORIES, STORAGE_SCAN_INTERVAL, VIRTUAL_MOUNT_PREFIXES
from app.utils import format_bytes, gb, host_path

_cache_lock = threading.Lock()
_storage_cache: list[dict] = []
_last_scan: float = 0.0
_scan_running = False


def _should_skip_mount(mountpoint: str, fstype: str) -> bool:
    if fstype in IGNORED_FS_TYPES:
        return True
    for prefix in VIRTUAL_MOUNT_PREFIXES:
        if mountpoint == prefix or mountpoint.startswith(prefix + "/"):
            return True
    return False


def _dir_size(path: Path, max_depth: int = 3) -> int:
    total = 0
    if not path.exists() or not path.is_dir():
        return 0
    try:
        for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
            depth = root.replace(str(path), "").count(os.sep)
            if depth >= max_depth:
                dirs[:] = []
            for fname in files:
                fpath = Path(root) / fname
                try:
                    if fpath.is_symlink():
                        continue
                    total += fpath.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _scan_directories() -> list[dict]:
    results: list[tuple[str, int]] = []
    for directory in SCAN_DIRECTORIES:
        path = host_path(directory.lstrip("/"))
        size = _dir_size(path)
        if size > 0:
            results.append((directory, size))

    results.sort(key=lambda item: item[1], reverse=True)
    return [{"directory": d, "size": format_bytes(s)} for d, s in results]


def _scan_worker() -> None:
    global _storage_cache, _last_scan, _scan_running
    try:
        data = _scan_directories()
        with _cache_lock:
            _storage_cache = data
            _last_scan = time.time()
    finally:
        with _cache_lock:
            _scan_running = False


def ensure_storage_scan(force: bool = False) -> None:
    global _scan_running
    with _cache_lock:
        due = (time.time() - _last_scan) >= STORAGE_SCAN_INTERVAL
        if not force and not due:
            return
        if _scan_running:
            return
        _scan_running = True
    threading.Thread(target=_scan_worker, daemon=True).start()


def get_storage_directories() -> list[dict]:
    ensure_storage_scan()
    with _cache_lock:
        return list(_storage_cache)


def collect_partitions() -> list[dict]:
    mounts: list[dict] = []
    try:
        for part in psutil.disk_partitions(all=False):
            if _should_skip_mount(part.mountpoint, part.fstype):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError:
                continue
            use_pct = round((usage.used / usage.total) * 100) if usage.total else 0
            mounts.append(
                {
                    "mount": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total": gb(usage.total),
                    "used": gb(usage.used),
                    "free": gb(usage.free),
                    "use_pct": use_pct,
                }
            )
    except Exception:
        pass
    return mounts
