# Sentinel

Simple server monitoring dashboard in a Docker container.

![Sentinel dashboard](screenshot.png)

## Features

- **System overview** — CPU, memory, disk, and network sparklines with 15-point history
- **Process tree** — hierarchical view with expand/collapse, friendly cmdline labels, hide idle toggle
- **Persistent sparklines** — metric history saved server-side (`HISTORY_PATH`) and cached in browser session
- **Docker tab** — container status, image, CPU, and memory usage via Docker socket
- **Crontabs** — reads system cron files with human-readable schedule summaries
- **Network** — NIC interfaces, RX/TX stats, and listening socket matrix (inbound LISTEN ports only; outbound polling clients like Telegram bots are not shown)
- **Disk analyzer** — partition mounts and largest directory sizes (cached hourly scan)

## Run

```bash
docker compose up -d --build
```

Open **http://localhost:8080**

### Manual Docker run

```bash
docker run -d --name sentinel \
  --net=host --pid=host \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /:/host:ro \
  -e HOST_PREFIX=/host \
  -e HISTORY_PATH=/host/var/lib/sentinel/history.json \
  sentinel
```

Set `HISTORY_PATH` to a path on the host volume to keep sparkline history across container restarts.

## Deploy from GitHub Container Registry

Images are built and published automatically on every push to `main`:

```bash
docker login ghcr.io
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Image: `ghcr.io/bgwastu/sentinel:latest`

On first use, make the package public under **GitHub → Packages → sentinel → Package settings**, or authenticate with a PAT that has `read:packages`.

## API

- `GET /api/telemetry` — dashboard data (`?search=` and `?sort=cpu|mem|pid` for processes)
- `GET /api/health` — health check
