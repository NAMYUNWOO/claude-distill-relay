# Cloudflare Zero Trust Deployment Guide (No Public IP)

This guide is for environments where:
- your server does **not** have a public IP, and
- you use Cloudflare Tunnel / Zero Trust.

In this setup, clients should connect via **WSS over 443**:
- `wss://relay.yourdomain.com`

> Do **not** use `ws://yourdomain:9784` behind Cloudflare proxy mode.

---

## 1) Server: deploy relay locally

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/deploy-oneclick.local.sh yourdomain.com 9784
```

Confirm local listener:

```bash
ss -ltnp | grep 9784
```

---

## 2) Install and login cloudflared (server)

If not installed, follow Cloudflare official install method for your OS.

Login:

```bash
cloudflared tunnel login
```

---

## 3) Create a tunnel and route DNS

```bash
cloudflared tunnel create relay-ws
cloudflared tunnel route dns relay-ws relay.yourdomain.com
```

This creates credentials (JSON) under `~/.cloudflared/`.

---

## 4) Configure tunnel ingress

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: relay-ws
credentials-file: /home/namyunwoo/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: relay.yourdomain.com
    service: http://localhost:9784
    originRequest:
      http2Origin: false
  - service: http_status:404
```

Notes:
- Relay server is WebSocket over HTTP upgrade.
- `service: http://localhost:9784` is correct for WS upgrade.

---

## 5) Run tunnel as service

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

If you manage tunnel manually, use:

```bash
cloudflared tunnel run relay-ws
```

---

## 6) Verify endpoint

DNS check:

```bash
dig +short relay.yourdomain.com
```

Client connection target:

- `wss://relay.yourdomain.com`

Quick WebSocket probe (from another network):

```bash
python3 - <<'PY'
import asyncio, websockets
async def main():
    async with websockets.connect('wss://relay.yourdomain.com') as ws:
        await ws.send('{"type":"CREATE_ROOM"}')
        print(await ws.recv())
asyncio.run(main())
PY
```

---

## 7) Troubleshooting

### `ws://yourdomain:9784` fails
Expected in Zero Trust proxied setup. Use `wss://relay.yourdomain.com` via tunnel.

### Relay service is running but external connect fails
- Check `cloudflared` service status/logs
- Check tunnel DNS route
- Check hostname in `config.yml` matches exactly

### 502 / handshake failure
- Confirm relay listens on `localhost:9784` or `0.0.0.0:9784`
- Confirm ingress service is `http://localhost:9784`
- Restart both services:

```bash
sudo systemctl restart claude-distill-relay.service
sudo systemctl restart cloudflared
```
