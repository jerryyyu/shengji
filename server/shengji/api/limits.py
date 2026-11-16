"""Bounds on what one client address, and everyone together, may hold.

One small machine serves every table, so sockets, rooms and code lookups are
bounded per client address (``accounts.client_ip``) and in total. The
per-address limits are set for a household or a shared network with several
players at once; they only bite on scripted traffic. Each limit reads its
environment variable once, at import.
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict

from . import accounts


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# Open sockets per client address, and on the whole server.
SOCKETS_PER_IP = _env_int("SHENGJI_SOCKETS_PER_IP", 40)
MAX_SOCKETS = _env_int("SHENGJI_MAX_SOCKETS", 3000)
# Live rooms (``create_room``) per client address, and on the whole server.
ROOMS_PER_IP = _env_int("SHENGJI_ROOMS_PER_IP", 12)
MAX_ROOMS = _env_int("SHENGJI_MAX_ROOMS", 300)
# ``create_room`` per client address per window.
CREATE_LIMIT = (_env_int("SHENGJI_CREATES_PER_IP", 30), 600.0)
# Code lookups (``peek_room``, ``join_room``) per client address per window,
# and lookups of a code that names nothing, which is what a sweep of the
# code space mostly makes.
LOOKUP_LIMIT = (_env_int("SHENGJI_LOOKUPS_PER_IP", 120), 60.0)
MISS_LIMIT = (_env_int("SHENGJI_MISSES_PER_IP", 30), 600.0)
# Queue starts (which can open a table with bots) per client address.
QUEUE_START_LIMIT = (_env_int("SHENGJI_QUEUE_STARTS_PER_IP", 60), 600.0)
# Largest WebSocket message the server reads; every client message is a few
# hundred bytes (telemetry batches stop at 2 KiB).
WS_MAX_BYTES = 64 * 1024
# Guest device keys remembered (each names a guest queue id); the least
# recently seen is forgotten first.
MAX_GUEST_IDS = _env_int("SHENGJI_MAX_GUEST_IDS", 50_000)


def clock() -> float:
    """The limits' one clock, so tests advance time instead of sleeping."""
    return time.monotonic()


class SocketGate:
    """Open sockets per address and in total."""

    def __init__(self) -> None:
        self.open: dict[str, int] = {}
        self.total = 0

    def acquire(self, ip: str) -> bool:
        if self.total >= MAX_SOCKETS or self.open.get(ip, 0) >= SOCKETS_PER_IP:
            return False
        self.open[ip] = self.open.get(ip, 0) + 1
        self.total += 1
        return True

    def release(self, ip: str) -> None:
        n = self.open.get(ip, 0) - 1
        if n > 0:
            self.open[ip] = n
        else:
            self.open.pop(ip, None)
        self.total = max(0, self.total - 1)

    def reset(self) -> None:
        self.open.clear()
        self.total = 0


SOCKETS = SocketGate()
CREATES = accounts.RateLimiter(*CREATE_LIMIT)
LOOKUPS = accounts.RateLimiter(*LOOKUP_LIMIT)
MISSES = accounts.RateLimiter(*MISS_LIMIT)
QUEUE_STARTS = accounts.RateLimiter(*QUEUE_START_LIMIT)


def allow(limiter: accounts.RateLimiter, ip: str) -> bool:
    return limiter.allow(ip, clock())


def misses_left(ip: str) -> bool:
    """Whether ``ip`` may still look up codes: its misses in the window are
    under the limit. Reading it records nothing."""
    q = MISSES._hits.get(ip)
    if not q:
        return True
    t = clock()
    return sum(1 for s in q if s > t - MISSES.window) < MISSES.limit


def record_miss(ip: str) -> None:
    MISSES.allow(ip, clock())


class GuestIds:
    """Device key -> guest queue id (-1, -2, ... in order of first use),
    holding at most ``MAX_GUEST_IDS`` keys: the least recently seen goes
    first, and a forgotten device that comes back gets a new id."""

    def __init__(self) -> None:
        self._ids: OrderedDict[str, int] = OrderedDict()
        self._next = 1

    def get(self, device: str | None, default: int | None = None) -> int | None:
        qid = self._ids.get(device) if device is not None else None
        if qid is None:
            return default
        self._ids.move_to_end(device)
        return qid

    def id_for(self, device: str) -> int:
        qid = self.get(device)
        if qid is None:
            qid = self._ids[device] = -self._next
            self._next += 1
            while len(self._ids) > MAX_GUEST_IDS:
                self._ids.popitem(last=False)
        return qid

    def __contains__(self, device: object) -> bool:
        return device in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def clear(self) -> None:
        self._ids.clear()
        self._next = 1


def reset() -> None:
    """Forget every count (tests)."""
    SOCKETS.reset()
    for limiter in (CREATES, LOOKUPS, MISSES, QUEUE_STARTS):
        limiter.reset()
