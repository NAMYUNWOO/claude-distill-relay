#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"

if ! "$REPO_DIR/scripts/healthcheck.sh"; then
  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") action=restart reason=healthcheck_failed" >> "$LOG_DIR/healthcheck.log"
  systemctl --user restart claude-distill-relay.service || true
fi
