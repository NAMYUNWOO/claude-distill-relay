#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="claude-distill-relay.service"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$REPO_DIR/$SERVICE_NAME"
ENV_EXAMPLE="$REPO_DIR/.env.example"
ENV_FILE="$REPO_DIR/.env.relay"

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "[ERROR] service file not found: $UNIT_SRC"
  exit 1
fi

if [[ ! -f "$ENV_FILE" && -f "$ENV_EXAMPLE" ]]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "[INFO] created $ENV_FILE from .env.example"
fi

echo "[INFO] installing $SERVICE_NAME to /etc/systemd/system"
sudo cp "$UNIT_SRC" "/etc/systemd/system/$SERVICE_NAME"

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo
printf '[DONE] Installed and started %s\n' "$SERVICE_NAME"
printf '       Logs: sudo journalctl -u %s -f\n' "$SERVICE_NAME"
