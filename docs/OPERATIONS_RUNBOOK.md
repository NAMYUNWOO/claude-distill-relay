# Operations Runbook (Production)

This is the canonical runbook for operating `claude-distill-relay` in production.

## 0) Current recommended architecture

For environments without direct public IP exposure:

1. `claude-distill-relay.service` runs WebSocket relay on `127.0.0.1/0.0.0.0:9784`
2. `nginx` proxies `relay.fireamulet.com` (HTTP on localhost:80) -> `127.0.0.1:9784`
3. `cloudflared tunnel` publishes `relay.fireamulet.com` -> `http://localhost:80`
4. Clients connect to `wss://relay.fireamulet.com`

This keeps external traffic on HTTPS/WSS while relay remains private behind local services.

---

## 1) First-time deploy (server)

```bash
cd ~/.openclaw/workspace/claude-distill-relay
./scripts/deploy-oneclick.local.sh fireamulet.com 9784
```

Then configure nginx route:

```bash
./scripts/setup-nginx-relay.sh relay.fireamulet.com 9784
```

---

## 2) Cloudflare dashboard setup

In **Zero Trust -> Networks -> Tunnels -> <your tunnel> -> Published application routes**:

- Subdomain: `relay`
- Domain: `fireamulet.com`
- Path: (empty)
- Service Type: `HTTP`
- URL: `localhost:80`

Save route.

> Do not use private hostname route (`www.example.local`) for this public use case.

---

## 3) Health checks

### Relay service

```bash
sudo systemctl status claude-distill-relay.service
ss -ltnp | grep 9784
```

### Nginx

```bash
sudo nginx -t
sudo systemctl status nginx
```

### Tunnel

```bash
sudo systemctl status cloudflared
```

### End-to-end WSS test

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

Expected: `{"type":"ROOM_CREATED", ...}`

---

## 4) Routine operations

### Restart relay

```bash
sudo systemctl restart claude-distill-relay.service
```

### View relay logs

```bash
sudo journalctl -u claude-distill-relay.service -f
```

### Restart nginx

```bash
sudo systemctl reload nginx
```

### Restart cloudflared

```bash
sudo systemctl restart cloudflared
```

---

## 5) Troubleshooting map

### A) Service active but no external connection
- Confirm Cloudflare published route exists for `relay.fireamulet.com`
- Confirm route points to `http://localhost:80`
- Confirm nginx has relay server block and reload success

### B) `ModuleNotFoundError: websockets`
- Re-run one-click deploy script (it creates `.venv` and installs deps)
- Ensure systemd ExecStart uses `.venv/bin/python`

### C) WebSocket handshake failures
- Check nginx proxy upgrade headers in relay site config
- Check relay service is listening on `:9784`

### D) `rate_limited` responses
- Tune `.env.relay` values:
  - `RELAY_RATE_LIMIT_MAX`
  - `RELAY_RATE_LIMIT_WINDOW`
- Restart relay service

---

## 6) Config files of record

- Relay app: `relay.py`
- Relay env: `.env.relay`
- Relay service unit: `/etc/systemd/system/claude-distill-relay.service`
- Nginx relay site: `/etc/nginx/sites-available/relay.fireamulet.com`
- Tunnel config (if local-managed): `~/.cloudflared/config.yml`

---

## 7) Security checklist

- Keep relay behind WSS endpoint (`relay.fireamulet.com`)
- Keep `RELAY_RATE_LIMIT_*` enabled
- Limit host firewall to required ports only
- Do not commit `.env.relay`
- Rotate tunnel credentials if compromised
