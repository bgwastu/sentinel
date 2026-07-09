from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

try:
    import docker
except ImportError:
    docker = None  # type: ignore


def _docker_client():
    if docker is None:
        return None
    socket_path = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    try:
        return docker.from_env()
    except Exception:
        try:
            return docker.DockerClient(base_url=socket_path)
        except Exception:
            return None


def _short_id(container_id: str) -> str:
    return container_id[:7] if container_id else "unknown"


def _container_stats(container) -> tuple[float, float]:
    try:
        if container.status != "running":
            return 0.0, 0.0
        stats = container.stats(stream=False)
        cpu_pct = _calc_cpu_percent(stats)
        mem_pct = _calc_mem_percent(stats)
        return round(cpu_pct, 1), round(mem_pct, 1)
    except Exception:
        return 0.0, 0.0


def _calc_cpu_percent(stats: dict[str, Any]) -> float:
    try:
        cpu_stats = stats.get("cpu_stats", {})
        precpu = stats.get("precpu_stats", {})
        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu.get(
            "cpu_usage", {}
        ).get("total_usage", 0)
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len(
            cpu_stats.get("cpu_usage", {}).get("percpu_usage") or [1]
        )
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * online_cpus * 100.0
    except Exception:
        pass
    return 0.0


def _calc_mem_percent(stats: dict[str, Any]) -> float:
    try:
        usage = stats.get("memory_stats", {}).get("usage", 0)
        limit = stats.get("memory_stats", {}).get("limit", 0)
        if limit > 0:
            return (usage / limit) * 100.0
    except Exception:
        pass
    return 0.0


def _human_status(container) -> str:
    try:
        state = container.attrs.get("State", {})
        if container.status == "running":
            started = state.get("StartedAt", "")
            if started:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - started_dt
                days = delta.days
                hours = delta.seconds // 3600
                if days > 0:
                    return f"Up {days} days"
                if hours > 0:
                    return f"Up {hours} hours"
                return "Up"
            return "Up"
        if container.status == "exited":
            code = state.get("ExitCode", 0)
            finished = state.get("FinishedAt", "")
            if finished and finished != "0001-01-01T00:00:00Z":
                finished_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - finished_dt
                if delta.days > 0:
                    return f"Exited ({code}) {delta.days} days ago"
            return f"Exited ({code})"
        return container.status.capitalize()
    except Exception:
        return str(container.status)


def collect_docker() -> list[dict]:
    client = _docker_client()
    if client is None:
        return []

    containers: list[dict] = []
    try:
        for container in client.containers.list(all=True):
            name = container.name.lstrip("/")
            image = (
                container.image.tags[0]
                if container.image.tags
                else (container.image.short_id or "unknown")
            )
            status = _human_status(container)
            cpu_pct, mem_pct = _container_stats(container)
            containers.append(
                {
                    "id": _short_id(container.id),
                    "name": name,
                    "image": image,
                    "status": status,
                    "cpu_pct": cpu_pct,
                    "mem_pct": mem_pct,
                }
            )
    except Exception:
        return []

    return containers
