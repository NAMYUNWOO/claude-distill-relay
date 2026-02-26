#!/usr/bin/env python3
"""Claude Distill Relay Server (WebSocket).

WebSocket-based dumb relay for pairing sender and receiver clients via room IDs.
Relay does not decrypt payloads; it just forwards frames.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import string
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOM_ID_ALPHABET = string.ascii_lowercase + string.digits


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    host: str = os.getenv("RELAY_HOST", "0.0.0.0")
    port: int = env_int("RELAY_PORT", 9784)
    max_rooms: int = env_int("RELAY_MAX_ROOMS", 1000)
    room_ttl: int = env_int("RELAY_ROOM_TTL", 1800)
    max_msg_size: int = env_int("RELAY_MAX_MSG_SIZE", 10 * 1024 * 1024)
    rate_limit_max: int = env_int("RELAY_RATE_LIMIT_MAX", 20)
    rate_limit_window: int = env_int("RELAY_RATE_LIMIT_WINDOW", 60)


@dataclass
class Connection:
    conn_id: str
    ws: any
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    relay_done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class Room:
    room_id: str
    sender: Connection
    created_at: float
    receiver_queue: asyncio.Queue[Connection] = field(default_factory=asyncio.Queue)
    active_receiver: Optional[Connection] = None
    closed: bool = False


class RelayServer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rooms: dict[str, Room] = {}
        self.rooms_lock = asyncio.Lock()
        self.rate_limit: dict[str, deque[float]] = defaultdict(deque)
        self.rate_limit_lock = asyncio.Lock()

    async def send_json(self, conn: Connection, obj: dict) -> bool:
        try:
            body = json.dumps(obj, ensure_ascii=False)
            if len(body.encode("utf-8")) > self.cfg.max_msg_size:
                return False
            await conn.ws.send(body)
            return True
        except Exception:
            return False

    async def recv_json(self, conn: Connection) -> Optional[dict]:
        try:
            msg = await conn.ws.recv()
            if isinstance(msg, bytes):
                if len(msg) > self.cfg.max_msg_size:
                    return None
                msg = msg.decode("utf-8")
            else:
                if len(msg.encode("utf-8")) > self.cfg.max_msg_size:
                    return None
            return json.loads(msg)
        except Exception:
            return None

    async def close_conn(self, conn: Connection):
        if conn.closed.is_set():
            return
        conn.closed.set()
        try:
            await conn.ws.close()
        except Exception:
            pass

    async def is_rate_limited(self, ip: str) -> bool:
        now = time.time()
        window = self.cfg.rate_limit_window
        limit = self.cfg.rate_limit_max
        async with self.rate_limit_lock:
            q = self.rate_limit[ip]
            cutoff = now - window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return True
            q.append(now)
            return False

    def gen_room_id(self) -> str:
        return "".join(random.choice(ROOM_ID_ALPHABET) for _ in range(6))

    async def create_room(self, sender: Connection) -> Optional[Room]:
        async with self.rooms_lock:
            if len(self.rooms) >= self.cfg.max_rooms:
                return None
            for _ in range(100):
                rid = self.gen_room_id()
                if rid not in self.rooms:
                    room = Room(room_id=rid, sender=sender, created_at=time.time())
                    self.rooms[rid] = room
                    return room
        return None

    async def get_room(self, room_id: str) -> Optional[Room]:
        async with self.rooms_lock:
            room = self.rooms.get(room_id)
            if not room:
                return None
            if room.closed or (time.time() - room.created_at > self.cfg.room_ttl):
                return None
            return room

    async def remove_room(self, room_id: str):
        async with self.rooms_lock:
            self.rooms.pop(room_id, None)

    async def close_room(self, room: Room, notify_waiters: bool = True):
        if room.closed:
            return
        room.closed = True
        await self.remove_room(room.room_id)

        if room.active_receiver:
            await self.close_conn(room.active_receiver)
            room.active_receiver.relay_done.set()

        if notify_waiters:
            while not room.receiver_queue.empty():
                try:
                    queued = room.receiver_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await self.send_json(queued, {"type": "ERROR", "reason": "sender_disconnected"})
                queued.relay_done.set()
                await self.close_conn(queued)

        await self.close_conn(room.sender)

    async def forward(self, src: Connection, dst: Connection):
        while True:
            msg = await src.ws.recv()
            size = len(msg) if isinstance(msg, bytes) else len(msg.encode("utf-8"))
            if size <= 0 or size > self.cfg.max_msg_size:
                raise ConnectionError("invalid_message_size")
            await dst.ws.send(msg)

    async def relay_pair(self, sender: Connection, receiver: Connection):
        try:
            await asyncio.gather(
                self.forward(sender, receiver),
                self.forward(receiver, sender),
            )
        except (ConnectionClosed, ConnectionError, OSError):
            pass

    async def sender_loop(self, room: Room):
        sender = room.sender
        try:
            while not room.closed:
                receiver = await room.receiver_queue.get()
                if room.closed:
                    receiver.relay_done.set()
                    await self.close_conn(receiver)
                    break

                room.active_receiver = receiver
                ok = await self.send_json(sender, {"type": "PEER_JOINED", "peer_id": receiver.conn_id})
                if not ok:
                    await self.close_conn(receiver)
                    receiver.relay_done.set()
                    await self.close_room(room)
                    break

                await self.relay_pair(sender, receiver)

                if not sender.closed.is_set():
                    await self.send_json(sender, {"type": "PEER_DISCONNECTED", "peer_id": receiver.conn_id})

                room.active_receiver = None
                receiver.relay_done.set()
                await self.close_conn(receiver)

                if sender.closed.is_set():
                    await self.close_room(room)
                    break
        finally:
            if not room.closed:
                await self.close_room(room)

    async def monitor_sender_disconnect(self, room: Room):
        await room.sender.closed.wait()
        if not room.closed:
            await self.close_room(room)

    async def handle_create_room(self, conn: Connection):
        room = await self.create_room(conn)
        if not room:
            await self.send_json(conn, {"type": "ERROR", "reason": "too_many_rooms"})
            await self.close_conn(conn)
            return

        await self.send_json(conn, {"type": "ROOM_CREATED", "room_id": room.room_id})

        sender_task = asyncio.create_task(self.sender_loop(room))
        monitor_task = asyncio.create_task(self.monitor_sender_disconnect(room))

        try:
            await sender_task
        finally:
            monitor_task.cancel()
            await self.close_room(room)

    async def handle_join_room(self, conn: Connection, room_id: str):
        if not room_id or len(room_id) != 6 or any(c not in ROOM_ID_ALPHABET for c in room_id):
            await self.send_json(conn, {"type": "ERROR", "reason": "room_not_found"})
            await self.close_conn(conn)
            return

        room = await self.get_room(room_id)
        if not room or room.closed:
            await self.send_json(conn, {"type": "ERROR", "reason": "room_not_found"})
            await self.close_conn(conn)
            return

        ok = await self.send_json(conn, {"type": "ROOM_JOINED", "room_id": room.room_id})
        if not ok:
            await self.close_conn(conn)
            return

        await room.receiver_queue.put(conn)
        await conn.relay_done.wait()
        await self.close_conn(conn)

    async def handle_ws(self, ws):
        conn_id = f"conn_{id(ws):x}"
        conn = Connection(conn_id=conn_id, ws=ws)
        peer = ws.remote_address
        peer_ip = peer[0] if isinstance(peer, tuple) and peer else "unknown"

        try:
            if await self.is_rate_limited(peer_ip):
                await self.send_json(conn, {"type": "ERROR", "reason": "rate_limited"})
                await self.close_conn(conn)
                return

            msg = await self.recv_json(conn)
            if not isinstance(msg, dict):
                await self.send_json(conn, {"type": "ERROR", "reason": "invalid_request"})
                await self.close_conn(conn)
                return

            msg_type = msg.get("type")
            if msg_type == "CREATE_ROOM":
                await self.handle_create_room(conn)
            elif msg_type == "JOIN_ROOM":
                await self.handle_join_room(conn, str(msg.get("room_id", "")))
            else:
                await self.send_json(conn, {"type": "ERROR", "reason": "invalid_request"})
                await self.close_conn(conn)
        finally:
            conn.closed.set()

    async def cleanup_expired_rooms(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired: list[Room] = []
            async with self.rooms_lock:
                for room in list(self.rooms.values()):
                    if now - room.created_at > self.cfg.room_ttl:
                        expired.append(room)
            for room in expired:
                if not room.closed:
                    await self.close_room(room)

    async def serve(self):
        print(f"Relay (WebSocket) listening on ws://{self.cfg.host}:{self.cfg.port}")
        cleanup_task = asyncio.create_task(self.cleanup_expired_rooms())
        try:
            async with serve(self.handle_ws, self.cfg.host, self.cfg.port, max_size=self.cfg.max_msg_size):
                await asyncio.Future()
        finally:
            cleanup_task.cancel()


def parse_args() -> argparse.Namespace:
    cfg = Config()
    parser = argparse.ArgumentParser(description="Claude Distill Relay Server (WebSocket)")
    parser.add_argument("--host", type=str, default=cfg.host, help=f"Listen host (default: {cfg.host})")
    parser.add_argument("--port", type=int, default=cfg.port, help=f"Listen port (default: {cfg.port})")
    parser.add_argument("--max-rooms", type=int, default=cfg.max_rooms)
    parser.add_argument("--room-ttl", type=int, default=cfg.room_ttl)
    parser.add_argument("--max-msg-size", type=int, default=cfg.max_msg_size)
    parser.add_argument("--rate-limit-max", type=int, default=cfg.rate_limit_max)
    parser.add_argument("--rate-limit-window", type=int, default=cfg.rate_limit_window)
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = Config(
        host=args.host,
        port=args.port,
        max_rooms=args.max_rooms,
        room_ttl=args.room_ttl,
        max_msg_size=args.max_msg_size,
        rate_limit_max=args.rate_limit_max,
        rate_limit_window=args.rate_limit_window,
    )
    server = RelayServer(cfg)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
