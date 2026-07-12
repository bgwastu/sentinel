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
    results: list[dict] = []
    for directory in SCAN_DIRECTORIES:
        path = host_path(directory.lstrip("/"))
        if not path.exists() or not path.is_dir():
            continue
        entry = _scan_tree(path, directory, 0)
        if entry["size_bytes"] > 0:
            results.append(entry)
    results.sort(key=lambda item: item["size_bytes"], reverse=True)
    return results


def _scan_tree(path: Path, display_path: str, depth: int) -> dict:
    size = _dir_size(path, max_depth=max(1, 3 - depth))
    entry = _scan_entry(display_path, size)
    if depth >= 2:
        return entry
    children: list[dict] = []
    try:
        candidates = []
        for child in path.iterdir():
            if child.is_symlink():
                continue
            try:
                child_size = _dir_size(child, max_depth=1) if child.is_dir() else child.stat().st_size
            except OSError:
                continue
            if child_size > 0:
                candidates.append((child, child_size))
        candidates.sort(key=lambda item: item[1], reverse=True)
        for child, child_size in candidates[:24]:
            if child.is_dir():
                children.append(_scan_tree(child, f"{display_path}/{child.name}", depth + 1))
            else:
                children.append(_scan_entry(f"{display_path}/{child.name}", child_size))
    except OSError:
        pass
    if children:
        entry["children"] = children
    return entry


def _scan_entry(directory: str, size: int) -> dict:
    """Return a stable, numeric entry for the client-side squarified treemap."""
    return {
        "directory": directory,
        "path": directory,
        "size_bytes": size,
        "size": format_bytes(size),
    }



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

def get_storage_status() -> dict:
    """Expose scan progress so the UI can distinguish loading from empty."""
    with _cache_lock:
        return {
            "loading": _scan_running,
            "last_scan": _last_scan,
            "has_data": bool(_storage_cache),
        }


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
