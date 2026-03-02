#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

set -a
source .env.relay
set +a

LOG_DIR="${RELAY_LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/healthcheck.log"

PORT="${RELAY_PORT:-9784}"
HOST="127.0.0.1"

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
STATUS="OK"
DETAILS=()

if ! pgrep -f "claude-distill-relay/relay.py" >/dev/null; then
  STATUS="FAIL"
  DETAILS+=("process_missing")
fi

if ! ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then
  STATUS="FAIL"
  DETAILS+=("port_not_listening:${PORT}")
fi

if ! "$REPO_DIR/.venv/bin/python" - <<PY >/dev/null 2>&1
import asyncio, json, websockets

async def main():
    uri='ws://127.0.0.1:${PORT}'
    async with websockets.connect(uri, open_timeout=3, close_timeout=3) as ws:
        await ws.send(json.dumps({'type':'CREATE_ROOM'}))
        msg = await asyncio.wait_for(ws.recv(), timeout=3)
        data = json.loads(msg)
        assert data.get('type') == 'ROOM_CREATED'

asyncio.run(main())
PY
then
  STATUS="FAIL"
  DETAILS+=("websocket_probe_failed")
fi

if [[ ${#DETAILS[@]} -eq 0 ]]; then
  DETAILS_STR="-"
else
  DETAILS_STR="$(IFS=,; echo "${DETAILS[*]}")"
fi

echo "$TS status=$STATUS details=$DETAILS_STR" >> "$LOG_FILE"

if [[ "$STATUS" != "OK" ]]; then
  exit 1
fi
