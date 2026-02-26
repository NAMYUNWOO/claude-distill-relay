# Deployment Guide (General)

This guide explains how to deploy `claude-distill-relay` on any Linux server.

## 1) Prerequisites

- Linux server with public inbound TCP access
- Python 3.10+
- systemd
- sudo privileges
- Open relay port (default: `9784/tcp`)

## 2) Get source

```bash
git clone <your-repo-url> claude-distill-relay
cd claude-distill-relay
```

Or if already cloned:

```bash
git pull
```

## 3) Configure environment

```bash
cp .env.example .env.relay
```

Edit `.env.relay` as needed:

- `RELAY_PORT` (default `9784`)
- `RELAY_MAX_ROOMS` (default `1000`)
- `RELAY_ROOM_TTL` (default `1800` seconds)
- `RELAY_MAX_MSG_SIZE` (default `10485760` bytes)
- `RELAY_RATE_LIMIT_MAX` (default `20`)
- `RELAY_RATE_LIMIT_WINDOW` (default `60` seconds)

## 4) Install systemd service

### Recommended (helper script)

```bash
./scripts/install-systemd.sh
```

### Manual install

```bash
sudo cp claude-distill-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-distill-relay.service
```

## 5) Verify service

```bash
sudo systemctl status claude-distill-relay.service
ss -ltnp | grep 9784
```

Expected: service is `active (running)` and listening on configured port.

## 6) Open firewall / network policy

Allow inbound TCP to the relay port.

Examples:

### UFW

```bash
sudo ufw allow 9784/tcp
sudo ufw status
```

### iptables

```bash
sudo iptables -I INPUT -p tcp --dport 9784 -j ACCEPT
```

Also check cloud security group / VPC firewall / router port forwarding if applicable.

## 7) DNS (optional but recommended)

Point a domain (e.g., `relay.example.com`) to your server public IP.

Validate:

```bash
dig +short relay.example.com
curl -4 ifconfig.me
```

Use endpoint:

- `relay.example.com:9784`

## 8) Smoke test from external network

```bash
nc -vz relay.example.com 9784
```

If successful, clients can connect.

## 9) Operations

View logs:

```bash
sudo journalctl -u claude-distill-relay.service -f
```

Restart:

```bash
sudo systemctl restart claude-distill-relay.service
```

Stop / start:

```bash
sudo systemctl stop claude-distill-relay.service
sudo systemctl start claude-distill-relay.service
```

## 10) Security checklist

- Keep relay on dedicated port; avoid opening unnecessary ports.
- Keep rate limiting enabled.
- Prefer dedicated subdomain (e.g., `relay.example.com`).
- Optionally place behind TLS-capable TCP proxy/tunnel.
- Avoid storing sensitive payloads in logs.

## 11) Common issues

### `Unit ... could not be found`
Service file not installed:

```bash
./scripts/install-systemd.sh
```

### Service running but unreachable
- Firewall not open
- Cloud/network ACL blocking ingress
- DNS points to wrong IP
- Port mismatch between config and client

### Frequent `rate_limited`
Requests per IP exceed limits. Tune in `.env.relay` and restart service.
