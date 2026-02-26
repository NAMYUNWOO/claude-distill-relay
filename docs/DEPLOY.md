# Claude Distill Relay — Single Deployment Guide

This single document covers deployment, operations, verification, and troubleshooting.

---

## 1) Recommended architecture

Recommended end-to-end path:

1. `claude-distill-relay` (WebSocket relay) listens on `127.0.0.1:9784`
2. `nginx` proxies `relay.fireamulet.com` to `127.0.0.1:9784`
3. `cloudflared tunnel` publishes `relay.fireamulet.com` to `http://localhost:80`
4. Clients connect to `wss://relay.fireamulet.com`

In short: external traffic uses WSS (443), internal traffic goes through nginx + relay.

---

## 2) Important clarifications

- This project is a **WebSocket relay**, not a raw TCP relay.
- Even if Cloudflare Tunnel Published Routes show `tcp://`, that does **not** mean generic raw TCP clients can directly connect over the public Internet via `host:port` in the same way.
- If you need generic public raw TCP exposure, you need a separate model (for example, Cloudflare Spectrum).
- The public connection method for this project is **`wss://...`**.

---

## 3) One-time server deployment

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/deploy-oneclick.local.sh fireamulet.com 9784
```

What the script does:
- `git pull`
- creates `.venv` and installs `websockets`
- creates/patches `.env.relay`
- installs/restarts the systemd unit
- checks listening status
- (optional) opens UFW 9784

---

## 4) Configure nginx relay proxy

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/setup-nginx-relay.sh relay.fireamulet.com 9784
```

After this, nginx proxies `relay.fireamulet.com` traffic to the relay service.

---

## 5) Cloudflare Zero Trust dashboard setup

Path:
- Zero Trust → Networks → Tunnels → (your active tunnel) → **Published application routes**

Values:
- Subdomain: `relay`
- Domain: `fireamulet.com`
- Path: (empty)
- Service Type: `HTTP`
- URL: `localhost:80`

Final public endpoint:
- `wss://relay.fireamulet.com`

> Do not use the private hostname route screen (`www.example.local`) for this use case.

---

## 6) Service checks

### relay
```bash
sudo systemctl status claude-distill-relay.service
ss -ltnp | grep 9784
```

### nginx
```bash
sudo nginx -t
sudo systemctl status nginx
```

### cloudflared
```bash
sudo systemctl status cloudflared
```

---

## 7) End-to-end verification

```bash
python3 - <<'PY'
import asyncio, websockets

async def main():
    async with websockets.connect("wss://relay.fireamulet.com") as ws:
        await ws.send('{"type":"CREATE_ROOM"}')
        print(await ws.recv())

asyncio.run(main())
PY
```

Success criteria:
- Response includes `{"type":"ROOM_CREATED", ...}`

---

## 8) Operations commands

```bash
# relay logs
sudo journalctl -u claude-distill-relay.service -f

# restart relay
sudo systemctl restart claude-distill-relay.service

# reload nginx
sudo systemctl reload nginx

# restart cloudflared
sudo systemctl restart cloudflared
```

---

## 9) Quick incident checklist

1. Relay is active (`systemctl status`)
2. Port 9784 is listening (`ss -ltnp | grep 9784`)
3. Nginx config is valid (`nginx -t`)
4. Tunnel is connected (`systemctl status cloudflared`)
5. Published route is `relay.fireamulet.com -> localhost:80`

---

## 10) Source-of-truth files

- App: `relay.py`
- Example env: `.env.example`
- Runtime env: `.env.relay` (gitignored)
- Systemd unit template: `claude-distill-relay.service`
- Deployment scripts:
  - `scripts/deploy-oneclick.local.sh` (one-click)
  - `scripts/setup-nginx-relay.sh` (nginx integration)

---

## 11) Security checklist

- Use WSS endpoint instead of exposing relay directly
- Keep rate limiting enabled (`RELAY_RATE_LIMIT_MAX`, `RELAY_RATE_LIMIT_WINDOW`)
- Keep unnecessary ports closed
- Never commit `.env.relay`
