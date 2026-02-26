#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup-nginx-relay.sh [relay-domain] [relay-port]
# Example:
#   ./scripts/setup-nginx-relay.sh relay.example.com 9784

RELAY_DOMAIN="${1:-relay.example.com}"
RELAY_PORT="${2:-9784}"
SITE_AVAILABLE="/etc/nginx/sites-available/${RELAY_DOMAIN}"
SITE_ENABLED="/etc/nginx/sites-enabled/${RELAY_DOMAIN}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "[ERROR] missing command: $1"; exit 1; }
}

require_cmd sudo
require_cmd nginx
require_cmd systemctl

echo "[1/5] Writing nginx server block for ${RELAY_DOMAIN} -> 127.0.0.1:${RELAY_PORT}"
sudo tee "$SITE_AVAILABLE" >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${RELAY_DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${RELAY_PORT};
        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;

        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF


echo "[2/5] Enabling site"
if [[ ! -L "$SITE_ENABLED" ]]; then
  sudo ln -s "$SITE_AVAILABLE" "$SITE_ENABLED"
fi

echo "[3/5] Testing nginx config"
sudo nginx -t

echo "[4/5] Reloading nginx"
sudo systemctl reload nginx

echo "[5/5] Done"
echo "Nginx relay proxy enabled: http://${RELAY_DOMAIN} -> 127.0.0.1:${RELAY_PORT}"
echo "Next (Cloudflare Tunnel): set Public Hostname ${RELAY_DOMAIN} -> http://localhost:80"
