from __future__ import annotations

import psutil


def _is_kernel_thread(proc: psutil.Process) -> bool:
    try:
        if proc.pid == 0:
            return True
        name = proc.name()
        if name.startswith("["):
            return True
        status = proc.status()
        if status == psutil.STATUS_IDLE and name in {"kthreadd", "ksoftirqd", "migration"}:
            return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return True
    return False


def _process_name(proc: psutil.Process) -> str:
    try:
        return proc.name() or proc.exe() or "unknown"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "unknown"


def _process_user(proc: psutil.Process) -> str:
    try:
        return proc.username()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "?"


def collect_processes(
    search: str = "",
    sort_by: str = "cpu",
    limit: int = 200,
) -> list[dict]:
    results: list[dict] = []
    procs = list(psutil.process_iter(["pid", "username", "name", "memory_percent"]))

    for proc in procs:
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for proc in procs:
        try:
            if _is_kernel_thread(proc):
                continue
            info = proc.info
            name = info.get("name") or _process_name(proc)
            user = info.get("username") or _process_user(proc)
            cpu = info.get("cpu_percent")
            if cpu is None:
                cpu = proc.cpu_percent(interval=0.0)
            mem_pct = info.get("memory_percent")
            if mem_pct is None:
                mem_pct = proc.memory_percent()

            entry = {
                "pid": proc.pid,
                "user": user,
                "cpu": round(float(cpu or 0.0), 1),
                "mem_pct": round(float(mem_pct or 0.0), 1),
                "name": name,
            }
            results.append(entry)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    needle = search.strip().lower()
    if needle:
        results = [
            p
            for p in results
            if needle in p["name"].lower() or needle in p["user"].lower() or needle in str(p["pid"])
        ]

    sort_key = {
        "cpu": lambda p: p["cpu"],
        "mem": lambda p: p["mem_pct"],
        "pid": lambda p: p["pid"],
    }.get(sort_by, lambda p: p["cpu"])

    reverse = sort_by != "pid"
    results.sort(key=sort_key, reverse=reverse)
    return results[:limit]
