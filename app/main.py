from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.collectors import cron, docker_collector, host, network, processes, storage
from app.config import SPARKLINE_INTERVAL, STATIC_DIR
from app.collectors.host import history as metric_history
from app.collectors.host import (
    get_cpu_percent,
    get_disk,
    get_memory,
    get_network_rate,
)


async def _sparkline_loop() -> None:
    while True:
        await asyncio.sleep(SPARKLINE_INTERVAL)
        try:
            cpu = get_cpu_percent()
            memory = get_memory()
            disk = get_disk()
            mem_pct = round((memory["used"] / memory["total"]) * 100, 1) if memory["total"] else 0.0
            disk_pct = round((disk["used"] / disk["total"]) * 100, 1) if disk["total"] else 0.0
            _, net_rate, _ = get_network_rate()
            metric_history.append(cpu, mem_pct, disk_pct, net_rate)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.ensure_storage_scan(force=True)
    task = asyncio.create_task(_sparkline_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Sentinel", description="Host monitoring dashboard", lifespan=lifespan)


@app.get("/api/telemetry")
def get_telemetry(
    search: str = Query("", description="Filter processes by name or user"),
    sort: str = Query("cpu", description="Sort processes by cpu, mem, or pid"),
):
    host_data = host.collect_host_snapshot()
    memory = host_data["memory"]
    disk = host_data["disk"]

    payload = {
        "hostname": host_data["hostname"],
        "uptime": host_data["uptime"],
        "cores": host_data["cores"],
        "load": host_data["load"],
        "cpu": host_data["cpu"],
        "memory": memory,
        "disk": disk,
        "network": {"rate": host_data["network"]["rate"]},
        "networkInterface": host_data["network"].get("interface", "eth0"),
        "kernel": host_data.get("kernel", "linux"),
        "history": host_data["history"],
        "processes": processes.collect_processes(search=search, sort_by=sort),
        "docker": docker_collector.collect_docker(),
        "cron": cron.collect_cron(),
        "storage": storage.get_storage_directories(),
        "partitions": storage.collect_partitions(),
        "networkInterfaces": network.collect_network_interfaces(),
        "listeningSockets": network.collect_listening_sockets(),
    }
    return payload


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    return FileResponse(index_path)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
