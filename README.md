# Sentinel

Simple server monitoring dashboard in a Docker container.

![Sentinel dashboard](screenshot.png)

## Run

```bash
docker compose up -d --build
```

Open **http://localhost:8080**

## What you get

CPU, memory, disk, network, processes, Docker containers, cron jobs, and disk usage — all in one page.

## API

- `GET /api/telemetry` — dashboard data
- `GET /api/health` — health check
