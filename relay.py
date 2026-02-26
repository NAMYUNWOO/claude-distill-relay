#!/usr/bin/env python3
"""Claude Distill Relay Server.

A dumb TCP relay for pairing a sender and receivers via room IDs.
Protocol framing: [4-byte big-endian length][UTF-8 JSON payload]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import string
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

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
    port: int = env_int("RELAY_PORT", 9784)
    max_rooms: int = env_int("RELAY_MAX_ROOMS", 1000)
    room_ttl: int = env_int("RELAY_ROOM_TTL", 1800)
    max_msg_size: int = env_int("RELAY_MAX_MSG_SIZE", 10 * 1024 * 1024)
    rate_limit_max: int = env_int("RELAY_RATE_LIMIT_MAX", 20)
    rate_limit_window: int = env_int("RELAY_RATE_LIMIT_WINDOW", 60)


@dataclass
class Connection:
    conn_id: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
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

    async def send_msg(self, conn: Connection, obj: dict) -> bool:
        try:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            if len(body) > self.cfg.max_msg_size:
                return False
            conn.writer.write(struct.pack("!I", len(body)) + body)
            await conn.writer.drain()
            return True
        except Exception:
            return False

    async def recv_msg(self, reader: asyncio.StreamReader) -> Optional[dict]:
        try:
            raw_len = await reader.readexactly(4)
            (length,) = struct.unpack("!I", raw_len)
            if length <= 0 or length > self.cfg.max_msg_size:
                return None
            raw_body = await reader.readexactly(length)
            return json.loads(raw_body.decode("utf-8"))
        except Exception:
            return None

    async def close_conn(self, conn: Connection):
        if conn.closed.is_set():
            return
        conn.closed.set()
        try:
            conn.writer.close()
            await conn.writer.wait_closed()
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
                await self.send_msg(queued, {"type": "ERROR", "reason": "sender_disconnected"})
                queued.relay_done.set()
                await self.close_conn(queued)

        await self.close_conn(room.sender)

    async def forward(self, src: Connection, dst: Connection):
        while True:
            raw_len = await src.reader.readexactly(4)
            (length,) = struct.unpack("!I", raw_len)
            if length <= 0 or length > self.cfg.max_msg_size:
                raise ConnectionError("invalid_message_size")
            raw_body = await src.reader.readexactly(length)
            dst.writer.write(raw_len + raw_body)
            await dst.writer.drain()

    async def relay_pair(self, sender: Connection, receiver: Connection):
        try:
            await asyncio.gather(
                self.forward(sender, receiver),
                self.forward(receiver, sender),
            )
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
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
                ok = await self.send_msg(sender, {"type": "PEER_JOINED", "peer_id": receiver.conn_id})
                if not ok:
                    await self.close_conn(receiver)
                    receiver.relay_done.set()
                    await self.close_room(room)
                    break

                await self.relay_pair(sender, receiver)

                if not sender.closed.is_set():
                    await self.send_msg(sender, {"type": "PEER_DISCONNECTED", "peer_id": receiver.conn_id})

                room.active_receiver = None
                receiver.relay_done.set()
                await self.close_conn(receiver)

                if sender.closed.is_set() or sender.writer.is_closing():
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
            await self.send_msg(conn, {"type": "ERROR", "reason": "too_many_rooms"})
            await self.close_conn(conn)
            return

        await self.send_msg(conn, {"type": "ROOM_CREATED", "room_id": room.room_id})

        sender_task = asyncio.create_task(self.sender_loop(room))
        monitor_task = asyncio.create_task(self.monitor_sender_disconnect(room))

        try:
            await sender_task
        finally:
            monitor_task.cancel()
            await self.close_room(room)

    async def handle_join_room(self, conn: Connection, room_id: str):
        if not room_id or len(room_id) != 6 or any(c not in ROOM_ID_ALPHABET for c in room_id):
            await self.send_msg(conn, {"type": "ERROR", "reason": "room_not_found"})
            await self.close_conn(conn)
            return

        room = await self.get_room(room_id)
        if not room:
            await self.send_msg(conn, {"type": "ERROR", "reason": "room_not_found"})
            await self.close_conn(conn)
            return

        if room.closed:
            await self.send_msg(conn, {"type": "ERROR", "reason": "room_not_found"})
            await self.close_conn(conn)
            return

        ok = await self.send_msg(conn, {"type": "ROOM_JOINED", "room_id": room.room_id})
        if not ok:
            await self.close_conn(conn)
            return

        await room.receiver_queue.put(conn)
        await conn.relay_done.wait()
        await self.close_conn(conn)

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        conn_id = f"conn_{id(writer):x}"
        conn = Connection(conn_id=conn_id, reader=reader, writer=writer)
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if isinstance(peer, tuple) and peer else "unknown"

        async def wait_closed_mark():
            try:
                await writer.wait_closed()
            finally:
                conn.closed.set()

        waiter = asyncio.create_task(wait_closed_mark())

        try:
            if await self.is_rate_limited(peer_ip):
                await self.send_msg(conn, {"type": "ERROR", "reason": "rate_limited"})
                await self.close_conn(conn)
                return

            msg = await self.recv_msg(reader)
            if not isinstance(msg, dict):
                await self.close_conn(conn)
                return

            msg_type = msg.get("type")
            if msg_type == "CREATE_ROOM":
                await self.handle_create_room(conn)
            elif msg_type == "JOIN_ROOM":
                await self.handle_join_room(conn, str(msg.get("room_id", "")))
            else:
                await self.send_msg(conn, {"type": "ERROR", "reason": "invalid_request"})
                await self.close_conn(conn)
        finally:
            conn.closed.set()
            waiter.cancel()

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
        server = await asyncio.start_server(self.handle_connection, host="0.0.0.0", port=self.cfg.port)
        addrs = ", ".join(str(sock.getsockname()) for sock in (server.sockets or []))
        print(f"Relay listening on {addrs}")

        cleanup_task = asyncio.create_task(self.cleanup_expired_rooms())
        try:
            async with server:
                await server.serve_forever()
        finally:
            cleanup_task.cancel()


def parse_args() -> argparse.Namespace:
    cfg = Config()
    parser = argparse.ArgumentParser(description="Claude Distill Relay Server")
    parser.add_argument("--port", type=int, default=cfg.port, help=f"Listen port (default: {cfg.port})")
    parser.add_argument(
        "--max-rooms",
        type=int,
        default=cfg.max_rooms,
        help=f"Maximum concurrent rooms (default: {cfg.max_rooms})",
    )
    parser.add_argument(
        "--room-ttl",
        type=int,
        default=cfg.room_ttl,
        help=f"Room TTL seconds (default: {cfg.room_ttl})",
    )
    parser.add_argument(
        "--max-msg-size",
        type=int,
        default=cfg.max_msg_size,
        help=f"Max message size bytes (default: {cfg.max_msg_size})",
    )
    parser.add_argument(
        "--rate-limit-max",
        type=int,
        default=cfg.rate_limit_max,
        help=f"Max CREATE/JOIN attempts per IP in window (default: {cfg.rate_limit_max})",
    )
    parser.add_argument(
        "--rate-limit-window",
        type=int,
        default=cfg.rate_limit_window,
        help=f"Rate-limit window seconds (default: {cfg.rate_limit_window})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = Config(
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
