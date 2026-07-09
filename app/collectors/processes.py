from __future__ import annotations

import psutil

from app.config import (
    PROCESS_MAX_DEPTH,
    PROCESS_MAX_NODES,
    PROCESS_MAX_ROOTS,
    SYSTEM_NAME_PREFIXES,
    SYSTEM_PROCESS_NAMES,
)


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


def _process_label(proc: psutil.Process) -> str:
    try:
        cmdline = proc.cmdline()
        if cmdline:
            return " ".join(cmdline)[:96]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return _process_name(proc)


def _process_user(proc: psutil.Process) -> str:
    try:
        return proc.username()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "?"


def is_system_process(name: str) -> bool:
    if name in SYSTEM_PROCESS_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SYSTEM_NAME_PREFIXES)


def _sort_nodes(nodes: list[dict], sort_by: str) -> None:
    sort_key = {
        "cpu": lambda n: n["cpu"],
        "mem": lambda n: n["mem_pct"],
        "pid": lambda n: n["pid"],
    }.get(sort_by, lambda n: n["cpu"])
    reverse = sort_by != "pid"
    nodes.sort(key=sort_key, reverse=reverse)
    for node in nodes:
        if node["children"]:
            _sort_nodes(node["children"], sort_by)


def _matches_search(node: dict, needle: str) -> bool:
    hay = f"{node['pid']} {node['name']} {node['label']} {node['user']}".lower()
    return needle in hay


def _filter_tree(nodes: list[dict], needle: str) -> list[dict]:
    if not needle:
        return nodes
    filtered: list[dict] = []
    for node in nodes:
        children = _filter_tree(node["children"], needle)
        if _matches_search(node, needle) or children:
            copy = {**node, "children": children}
            filtered.append(copy)
    return filtered


def _prune_system(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        promoted = _prune_system(node["children"])
        if node["is_system"]:
            result.extend(promoted)
        else:
            result.append({**node, "children": promoted})
    return result


def _reparent_visible(nodes: dict[int, dict], visible: set[int]) -> list[dict]:
    for pid in visible:
        nodes[pid]["children"] = []

    roots: list[dict] = []
    for pid in visible:
        node = nodes[pid]
        ancestor = node["ppid"]
        while ancestor in nodes and ancestor not in visible and ancestor != pid:
            ancestor = nodes[ancestor]["ppid"]
        if ancestor in visible and ancestor != pid:
            nodes[ancestor]["children"].append(node)
        else:
            roots.append(node)
    return roots


def _trim_tree(nodes: list[dict], max_nodes: int, max_depth: int, depth: int = 0) -> tuple[list[dict], int]:
    trimmed: list[dict] = []
    count = 0
    for node in nodes:
        if count >= max_nodes:
            break
        count += 1
        children: list[dict] = []
        if depth < max_depth and node["children"]:
            children, added = _trim_tree(node["children"], max_nodes - count, max_depth, depth + 1)
            count += added
        trimmed.append({**node, "children": children})
    return trimmed, count


def collect_process_tree(
    search: str = "",
    sort_by: str = "cpu",
) -> tuple[list[dict], int]:
    raw_nodes: dict[int, dict] = {}
    procs = list(psutil.process_iter(["pid", "ppid", "username", "name", "memory_percent"]))

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
            ppid = info.get("ppid")
            if ppid is None:
                try:
                    ppid = proc.ppid()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ppid = 0

            raw_nodes[proc.pid] = {
                "pid": proc.pid,
                "ppid": ppid,
                "user": user,
                "cpu": round(float(cpu or 0.0), 1),
                "mem_pct": round(float(mem_pct or 0.0), 1),
                "name": name,
                "label": _process_label(proc),
                "is_system": is_system_process(name),
                "children": [],
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    total_count = len(raw_nodes)
    for pid, node in raw_nodes.items():
        node["children"] = []
    roots: list[dict] = []
    for pid, node in raw_nodes.items():
        ppid = node["ppid"]
        if ppid in raw_nodes and ppid != pid:
            raw_nodes[ppid]["children"].append(node)
        else:
            roots.append(node)

    needle = search.strip().lower()
    if needle:
        roots = _filter_tree(roots, needle)

    _sort_nodes(roots, sort_by)
    roots = roots[:PROCESS_MAX_ROOTS]
    roots, _ = _trim_tree(roots, PROCESS_MAX_NODES, PROCESS_MAX_DEPTH)
    return roots, total_count


def collect_processes(
    search: str = "",
    sort_by: str = "cpu",
    limit: int = 200,
) -> list[dict]:
    """Flat process list kept for backward compatibility."""
    tree, _ = collect_process_tree(search=search, sort_by=sort_by)
    flat: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            flat.append(
                {
                    "pid": node["pid"],
                    "user": node["user"],
                    "cpu": node["cpu"],
                    "mem_pct": node["mem_pct"],
                    "name": node["name"],
                }
            )
            walk(node["children"])

    walk(tree)
    return flat[:limit]
