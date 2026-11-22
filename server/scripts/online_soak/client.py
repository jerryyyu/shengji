"""A guest player over a real WebSocket, modelled on the page.

The connection rules are ``web/src/ws.ts``'s (ping cadence and deadlines at
a table, the probe after an unanswered action, the connect timeout, the
retry delay), the resume is ``App.tsx``'s (a saved room and token go back as
one ``table_join``), and the resend is ``Table.tsx``'s (a play or bury still
unanswered across a reconnect goes once more when the first state on the
new socket shows the same hand, turn and phase). ``test_online_soak.py``
pins the constants below to ``ws.ts``.

Each play or bury carries a ``_soak`` tag (decision id, socket generation,
send sequence) that the server ignores; the run reads it where the play
applies to name the send it came from. A resend keeps the decision id and
the decision key of the first send.

Every duration is divided by the run's time scale, as the server's are.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import websockets

from audit import frame_key
from localonly import require_local, ws_url

# web/src/ws.ts, in milliseconds
TABLE_PING_MS = 8000
TABLE_PONG_MS = 6000
ANSWER_MS = 1500
ACTION_PONG_MS = 3000
PROBE_MS = 2000
CONNECT_MS = 5000
LONG_LIVED_MS = 10_000
TABLE_RETRY_MAX_MS = 3000
ANSWERED = frozenset({"play", "bury", "declare", "pass_declare", "next_round", "im_back",
                      "table_chat", "table_allow_joiners"})


@dataclass
class Sent:
    """One play or bury on the wire. ``key`` is the decision as it stood at
    the decision's first send, on every resend too."""
    kind: str
    card_ids: list[int]
    codes: list[str]
    key: tuple
    at: float
    did: int = 0
    gen: int = 0
    seq: int = 0
    resend: bool = False


@dataclass
class Pending:
    kind: str
    card_ids: list[int]
    codes: list[str]
    hand_key: tuple
    turn: int | None
    gen: int
    did: int = 0
    key: tuple = ()
    resent: bool = False


@dataclass
class ClientRecord:
    """What one client saw and did, for the checks."""
    sockets: int = 0
    drops: int = 0
    faults: list[dict] = field(default_factory=list)
    sent: list[Sent] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)
    rounds_seen: int = 0
    tables: int = 0
    down: list[list[float]] = field(default_factory=list)   # [start, end] with the socket not open
    task_errors: list[str] = field(default_factory=list)
    sent_types: dict[str, int] = field(default_factory=dict)
    # (room, seat) of each table_leave that went out, in order
    leaves: list[tuple[str | None, int | None]] = field(default_factory=list)
    # (the latest message type sent before it, the error code) for each refusal
    refused_after: dict[str, int] = field(default_factory=dict)


class SoakClient:
    def __init__(self, name: str, device: str, port: int, scale: float, rng: random.Random,
                 brain: Callable[["SoakClient", dict], list[int] | None],
                 on_lobby: Callable[["SoakClient"], Any], host: str = "127.0.0.1",
                 client_ip: str | None = None) -> None:
        self.name = name
        self.device = device
        # ws.ts socketUrl(): the table heartbeat on, then the device key
        self.url = require_local(ws_url(host, port, f"/ws?heartbeat=1&device={device}"))
        # the address the server's per-address limits key this client by
        # (accounts.client_ip reads Fly-Client-IP before the socket peer)
        self.headers = {"Fly-Client-IP": client_ip} if client_ip else {}
        self.scale = scale
        self.rng = rng
        self.brain = brain
        self.on_lobby = on_lobby
        self.rec = ClientRecord()
        self.ws: Any = None
        self.gen = 0
        self.room: str | None = None
        self.token: str | None = None
        self.seat: int | None = None
        self.state: dict | None = None
        self.pending: Pending | None = None
        self.ready_round: int | None = None
        self.heartbeat = False
        self.awaiting: int | None = None
        self.nonce = 0
        self.last_rx = 0.0
        self.answer_due: float | None = None
        self.ping_due: float | None = None
        self.pong_deadline: float | None = None
        self.backoff = 0.5 / scale
        self.opened_at: float | None = None
        self.state_at: float | None = None      # when the latest state arrived
        self.gen_at_fault: int | None = None
        self.reasked = False
        self.offline_until = 0.0                # an app killed and not yet opened again
        self.stop = False
        self.dup_next = False
        self.dup_sent_at: float | None = None
        self.decisions = 0
        self.last_sent: str | None = None
        self.state_gen: int | None = None        # the socket the latest state came on
        self.socket_opened: dict[int, float] = {}
        self.ready_sent: tuple[int, int] | None = None   # (round seen, socket) of the last Next
        self.seq = 0
        self.rounds_here = 0
        self.leave_after = 3
        self.think_task: asyncio.Task | None = None
        self.lobby_task: asyncio.Task | None = None

    # time, scaled
    def spawn(self, coro: Any) -> asyncio.Future:
        """A side task whose exception lands in the record instead of the log."""
        task = asyncio.ensure_future(coro)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Future) -> None:
        if not task.cancelled() and task.exception() is not None:
            e = task.exception()
            self.rec.task_errors.append(f"{type(e).__name__}: {e}"[:300])

    def s(self, ms: float) -> float:
        return ms / 1000.0 / self.scale

    @property
    def at_table(self) -> bool:
        return self.room is not None

    async def run(self, until: float) -> None:
        # down from now until a socket opens: the interval spans every
        # connect attempt, retry backoff and offline wait in between
        self._mark_down()
        while not self.stop and time.monotonic() < until:
            await self._one_socket(until)
            if self.stop or time.monotonic() >= until:
                break
            lived = (time.monotonic() - self.opened_at) if self.opened_at else 0.0
            delay = 0.0 if lived > self.s(LONG_LIVED_MS) else self.backoff
            self.backoff = min(self.backoff * 2, self.s(TABLE_RETRY_MAX_MS))
            self.opened_at = None
            await asyncio.sleep(delay)
            while time.monotonic() < self.offline_until and not self.stop:
                await asyncio.sleep(0.02)
        await self.close()

    async def close(self) -> None:
        self.stop = True
        for t in (self.think_task, self.lobby_task):
            if t is not None:
                t.cancel()
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()

    def _mark_down(self) -> None:
        now = time.monotonic()
        if not self.rec.down or self.rec.down[-1][1] is not None:
            self.rec.down.append([now, None])

    def _mark_up(self) -> None:
        if self.rec.down and self.rec.down[-1][1] is None:
            self.rec.down[-1][1] = time.monotonic()

    def down_since(self, t0: float) -> float:
        now = time.monotonic()
        total = 0.0
        for a, b in self.rec.down:
            b = now if b is None else b
            if b > t0:
                total += b - max(a, t0)
        return total

    async def _one_socket(self, until: float) -> None:
        try:
            ws = await asyncio.wait_for(websockets.connect(self.url, max_size=None, ping_interval=None,
                                                           open_timeout=None,
                                                           additional_headers=self.headers or None),
                                        self.s(CONNECT_MS))
        except (asyncio.TimeoutError, OSError, websockets.WebSocketException):
            return
        self.ws = ws
        self.gen += 1
        self.rec.sockets += 1
        self.opened_at = time.monotonic()
        self.socket_opened[self.gen] = self.opened_at
        self.backoff = self.s(500)
        self.heartbeat = False
        self.awaiting = None
        self.answer_due = self.ping_due = self.pong_deadline = None
        self.last_rx = time.monotonic()
        self._mark_up()
        if self.room is not None:
            await self._send({"type": "table_join", "code": self.room, "name": self.name, "expect": "room",
                              **({"token": self.token} if self.token else {})})
        else:
            self._to_lobby()
        reader = asyncio.create_task(self._read(ws))
        try:
            while not self.stop and time.monotonic() < until and not reader.done():
                await asyncio.sleep(0.02)
                if self._timers_say_dead():
                    break
        finally:
            # lost or declared dead: down from here until the next socket opens
            self._mark_down()
            reader.cancel()
            with contextlib.suppress(BaseException):
                await reader
            # ws.ts replace() drops the old socket without waiting for its
            # closing handshake, which a half-open link never answers
            with contextlib.suppress(Exception):
                ws.transport.abort()
            self.ws = None
            self.rec.drops += 1

    def _timers_say_dead(self) -> bool:
        now = time.monotonic()
        if self.pong_deadline is not None and now >= self.pong_deadline:
            return True
        if self.answer_due is not None and now >= self.answer_due and self.awaiting is None:
            self.answer_due = None
            self._ping(self.s(ACTION_PONG_MS))
        if self.heartbeat and self.ping_due is not None and now >= self.ping_due and self.awaiting is None:
            self._ping(self.s(TABLE_PONG_MS))
        return False

    def probe(self) -> None:
        """A ping with the short deadline, as ws.ts sends on a wake."""
        self._ping(self.s(PROBE_MS))

    def _ping(self, deadline: float) -> None:
        self.nonce += 1
        self.awaiting = self.nonce
        self.pong_deadline = time.monotonic() + deadline
        self.spawn(self._send({"type": "ping", "nonce": self.nonce}))

    async def _send(self, msg: dict) -> bool:
        ws = self.ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps(msg))
        except Exception:   # noqa: BLE001 - a dead socket is the reader's to notice
            return False
        t = msg.get("type")
        if t == "table_leave":
            self.rec.leaves.append((self.room, self.seat))
        if t != "ping":
            self.rec.sent_types[t] = self.rec.sent_types.get(t, 0) + 1
            self.last_sent = t
        if msg.get("type") in ANSWERED and self.answer_due is None:
            self.answer_due = time.monotonic() + self.s(ANSWER_MS)
        return True

    async def _read(self, ws: Any) -> None:
        async for raw in ws:
            self.last_rx = time.monotonic()
            self.answer_due = None
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            await self._on(msg)

    async def _on(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "heartbeat_ready":
            self.heartbeat = True
            self.ping_due = time.monotonic() + self.s(TABLE_PING_MS)
            return
        if t == "pong":
            if msg.get("nonce") == self.awaiting:
                self.awaiting = None
                self.pong_deadline = None
                self.ping_due = time.monotonic() + self.s(TABLE_PING_MS)
            return
        if t == "resume":
            self.token = msg.get("token")
        elif t == "room":
            self.room = msg.get("room")
            self.seat = msg.get("you")
            self.rec.tables += 1
            self.rounds_here = 0
        elif t == "state":
            self._on_state(msg)
        elif t == "left":
            self._forget_room()
            self._to_lobby()
        elif t == "error":
            code = msg.get("code") or "none"
            self.rec.errors[code] = self.rec.errors.get(code, 0) + 1
            k = f"{self.last_sent}:{code}"
            self.rec.refused_after[k] = self.rec.refused_after.get(k, 0) + 1
            self.pending = None
            # App.tsx: a room that is gone ends the table; a lost seat is asked
            # back once by the resume, then the table ends
            if self.room is not None and (code == "room_not_found" or (code == "no_room" and self.reasked)):
                self._forget_room()
                self._to_lobby()
            elif self.room is not None and code == "no_room":
                self.reasked = True
                await self._send({"type": "table_join", "code": self.room, "name": self.name, "expect": "room",
                                  **({"token": self.token} if self.token else {})})

    def _forget_room(self) -> None:
        self.room = self.token = self.seat = None
        self.state = None
        self.pending = None
        self.ready_round = None

    def _to_lobby(self) -> None:
        if self.lobby_task is None or self.lobby_task.done():
            self.lobby_task = self.spawn(self.on_lobby(self))

    def _on_state(self, st: dict) -> None:
        self.reasked = False
        if self.room is None and st.get("room"):
            self.room = st.get("room")
        self.seat = st.get("you", self.seat)
        prev = self.state
        self.state = st
        self.state_at = time.monotonic()
        self.state_gen = self.gen
        hk = tuple(sorted(c["id"] for c in st.get("hand", [])))
        p = self.pending
        if p is not None:
            if hk != p.hand_key or st.get("turn") != p.turn:
                self.pending = None
            elif self.gen != p.gen:
                ids = {c["id"] for c in st.get("hand", [])}
                again = (not p.resent and st.get("turn") == st.get("you") and not st.get("joining_you")
                         and st.get("phase") == p.kind and all(i in ids for i in p.card_ids))
                if again:
                    self.pending = Pending(p.kind, p.card_ids, p.codes, p.hand_key, p.turn, self.gen,
                                           p.did, p.key, True)
                    self.spawn(self._send(self._play_msg(self.pending, resend=True)))
                else:
                    self.pending = None
        phase = st.get("phase")
        if phase == "round_end" and (prev is None or prev.get("phase") != "round_end"):
            self.rec.rounds_seen += 1
            self.rounds_here += 1
        if phase == "round_end":
            if self.rounds_here >= self.leave_after:
                self.spawn(self._send({"type": "table_leave"}))
                self.rounds_here = -10**6       # one leave per sitting
            elif st.get("you") not in (st.get("ready") or []) and self.ready_sent != (self.rec.rounds_seen, self.gen):
                # a person taps Next again when a resumed round end still shows it untapped
                self.ready_sent = (self.rec.rounds_seen, self.gen)
                self.ready_round = self.rec.rounds_seen
                self.spawn(self._send({"type": "next_round"}))
        elif phase == "game_over":
            if self.rounds_here >= 0:
                self.spawn(self._send({"type": "table_leave"}))
                self.rounds_here = -10**6
        elif -10**6 <= self.rounds_here < -10**6 + 100 and phase not in ("round_end", "game_over"):
            # back in a seat this client already left (its left was lost with
            # the socket): the page would show the table again, so leave again
            self.spawn(self._send({"type": "table_leave"}))
            self.rec.errors["resumed_after_leave"] = self.rec.errors.get("resumed_after_leave", 0) + 1
            self.rounds_here = -2 * 10**6
        elif phase in ("play", "bury") and st.get("turn") == st.get("you") and self.pending is None:
            if self.think_task is None or self.think_task.done():
                self.think_task = self.spawn(self._think(st))

    async def _think(self, st: dict) -> None:
        await asyncio.sleep(self.rng.uniform(0.3, 2.5) / self.scale)
        cur = self.state
        if cur is not st or self.pending is not None or self.ws is None:
            if cur is not None and cur is not st and cur.get("turn") == cur.get("you") \
                    and cur.get("phase") in ("play", "bury") and self.pending is None:
                self.think_task = None
                self._on_state_retry(cur)
            return
        ids = self.brain(self, st)
        if not ids:
            return
        by_id = {c["id"]: c["code"] for c in st.get("hand", [])}
        kind = st["phase"]
        codes = [by_id[i] for i in ids]
        hand = [c["code"] for c in st.get("hand", [])]
        hk = tuple(sorted(by_id))
        self.decisions += 1
        self.pending = Pending(kind, ids, codes, hk, st.get("turn"), self.gen, self.decisions,
                               frame_key(hand, st.get("trick")))
        msg = self._play_msg(self.pending)
        await self._send(msg)
        if self.dup_next:
            self.dup_next = False
            await self._send(msg)
            self.dup_sent_at = time.monotonic()

    def _play_msg(self, p: Pending, resend: bool = False) -> dict:
        """The wire message for ``p`` on this socket, recorded as sent. The
        decision id and key are the first send's."""
        self.seq += 1
        self.rec.sent.append(Sent(p.kind, p.card_ids, p.codes, p.key, time.monotonic(),
                                  p.did, self.gen, self.seq, resend))
        return {"type": p.kind, "card_ids": p.card_ids, "_soak": {"did": p.did, "gen": self.gen, "seq": self.seq}}

    def _on_state_retry(self, st: dict) -> None:
        self.think_task = self.spawn(self._think(st))
