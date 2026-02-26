# One-Click Deployment Guide

This guide assumes you are deploying on the target Linux server directly.

## 1) Install dependency

```bash
python3 -m pip install websockets
```

## 2) Run one command

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/deploy-oneclick.local.sh fireamulet.com 9784
```

## 3) What it does automatically

- updates source (`git pull`)
- ensures `.env.relay` exists
- installs/updates systemd unit
- reloads systemd and restarts service
- verifies relay is listening on the port
- opens firewall via UFW (if available)
- checks public IP and DNS
- prints final relay endpoint

## 4) Optional

- Skip firewall step:

```bash
OPEN_UFW=0 ./scripts/deploy-oneclick.local.sh fireamulet.com 9784
```

- Use another domain/port:

```bash
./scripts/deploy-oneclick.local.sh relay.example.com 9784
```

## 5) External connectivity test

From another network:

```bash
nc -vz fireamulet.com 9784
```

If success, clients can connect to `ws://fireamulet.com:9784` (or `wss://...` behind TLS proxy).
