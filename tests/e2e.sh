#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SENTINEL_URL:-http://localhost:8080}"
SCREENSHOT_DIR="$(dirname "$0")/../screenshots"
mkdir -p "$SCREENSHOT_DIR"

echo "==> Health check"
curl -sf "$BASE_URL/api/health" | grep -q '"status":"ok"'

echo "==> Telemetry schema check"
python3 - <<PY
import json, urllib.request
data = json.load(urllib.request.urlopen("$BASE_URL/api/telemetry"))
required = [
    "hostname", "uptime", "cores", "load", "cpu", "memory", "disk", "network",
    "processTree", "processCount", "publicIp", "processes", "docker", "cron",
    "storage", "networkInterfaces", "listeningSockets", "history"
]
missing = [k for k in required if k not in data]
if missing:
    raise SystemExit(f"Missing keys: {missing}")
assert isinstance(data["history"]["cpu"], list) and len(data["history"]["cpu"]) == 15
assert isinstance(data["history"]["timestamps"], list) and len(data["history"]["timestamps"]) == 15
assert isinstance(data["processTree"], list)
print("schema ok")
PY

echo "==> Browser e2e"
npx --yes agent-browser open "$BASE_URL"
npx --yes agent-browser wait --load networkidle
npx --yes agent-browser snapshot -i

echo "==> Verify dashboard header"
npx --yes agent-browser get text "#hostTitle" | grep -qv "loading"

echo "==> Switch to Docker tab"
npx --yes agent-browser click "#tabBtn-docker"
npx --yes agent-browser wait 500
npx --yes agent-browser snapshot -i

echo "==> Switch to Network tab"
npx --yes agent-browser click "#tabBtn-network"
npx --yes agent-browser wait 500

echo "==> Switch to Storage tab"
npx --yes agent-browser click "#tabBtn-storage"
npx --yes agent-browser wait 500

echo "==> Screenshot"
npx --yes agent-browser screenshot "$SCREENSHOT_DIR/e2e-dashboard.png"

echo "==> Close browser"
npx --yes agent-browser close

echo "All e2e checks passed."
