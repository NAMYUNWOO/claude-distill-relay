#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="claude-distill-relay.service"
UNIT_SRC="$REPO_DIR/claude-distill-relay.service"
UNIT_DST="/etc/systemd/system/$SERVICE_NAME"

echo "[1/6] Updating source..."
cd "$REPO_DIR"
git pull --ff-only || true

echo "[2/6] Ensuring environment file..."
if [[ ! -f "$REPO_DIR/.env.relay" ]]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env.relay"
  echo "[INFO] Created $REPO_DIR/.env.relay from .env.example"
fi

echo "[3/6] Installing systemd unit..."
sudo cp "$UNIT_SRC" "$UNIT_DST"


echo "[4/6] Reloading systemd..."
sudo systemctl daemon-reload

echo "[5/6] Enabling and restarting service..."
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "[6/6] Verifying service..."
sudo systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,25p'

echo
echo "[DONE] Deploy complete"
echo "Logs: sudo journalctl -u $SERVICE_NAME -f"
