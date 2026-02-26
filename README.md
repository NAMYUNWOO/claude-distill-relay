# Claude Distill Relay Server

A dumb TCP relay server for forwarding distillation sessions across networks.

## Features

- Raw TCP relay with 4-byte big-endian length framing
- Room-based pairing (`CREATE_ROOM`, `JOIN_ROOM`)
- 6-char room IDs (`[a-z0-9]{6}`)
- Transparent bidirectional forwarding after pairing
- Receiver disconnect notification (`PEER_DISCONNECTED`)
- Room TTL cleanup (default 30 minutes)
- Configurable max rooms and max message size
- No external dependencies (Python stdlib only)

## Run

```bash
python3 relay.py --port 9784
```

## Environment variables

- `RELAY_PORT` (default `9784`)
- `RELAY_MAX_ROOMS` (default `1000`)
- `RELAY_ROOM_TTL` (default `1800`)
- `RELAY_MAX_MSG_SIZE` (default `10485760`)

Copy `.env.example` to `.env.relay` if needed.

## systemd

Service file included:

- `claude-distill-relay.service`

Install with helper script:

```bash
./scripts/install-systemd.sh
```

Or install manually:

```bash
sudo cp claude-distill-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-distill-relay.service
sudo systemctl status claude-distill-relay.service
```

## Protocol

### Sender creates room

Request:

```json
{"type":"CREATE_ROOM"}
```

Response:

```json
{"type":"ROOM_CREATED","room_id":"a7f3b2"}
```

### Receiver joins room

Request:

```json
{"type":"JOIN_ROOM","room_id":"a7f3b2"}
```

Response to receiver:

```json
{"type":"ROOM_JOINED","room_id":"a7f3b2"}
```

Event to sender:

```json
{"type":"PEER_JOINED","peer_id":"conn_xxxx"}
```

After this point, all framed messages are forwarded as-is in both directions.
