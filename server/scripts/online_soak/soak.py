"""Online soak, tier (a): the real game server on loopback, guest clients over
real WebSockets, each behind its own fault proxy.

    server/.venv/bin/python server/scripts/online_soak/soak.py --minutes 20

One process: uvicorn serves ``shengji.api.server:app`` on loopback (127.0.0.1
or ::1, the same family for the server, the proxies and the clients) with a
temp data and log dir, the server's timers divided by ``--scale``, and the
clients and proxies run on the same event loop. The server source is not
changed; the run wraps four of its functions to observe it (the action
handler, the move-clock strike, the room log and nothing else), and a
client picks its cards from its own seat's legal plays in the server's
round. Every address goes through ``localonly.require_local``.

Each client gives the server its own address in ``Fly-Client-IP``, which
``accounts.client_ip`` reads before the socket peer: behind one loopback
peer, 22 clients would share one per-address budget (``limits.QUEUE_STARTS``,
60 queue starts per 10 min), which no set of real players shares.

The report (JSON, and a summary on stdout) holds the plan's bar and a
verdict (``audit.verdict``): FAIL when a bar fails, INCONCLUSIVE when the
run is under a coverage floor, else PASS; exit 0, 1 or 2. Every injected
fault ends recovered, failed or censored in the fault ledger.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SERVER))

import audit  # noqa: E402
from localonly import loopback_family, require_local, require_not_deployed  # noqa: E402

# the timers a scaled run divides (server.py and matchmaking.py module constants)
SERVER_TIMERS = ("BOT_DELAY", "DEAL_DELAY", "DECLARE_GRACE", "DECLARE_EXTEND", "ROOM_TTL",
                 "EMPTY_ROOM_BOT_DELAY", "MOVE_TIMER", "RETURN_MIN", "TAKEOVER_AFTER",
                 "READY_KEEP_SECONDS", "WS_PING_INTERVAL", "WS_PING_TIMEOUT", "MOVE_TIMER_POLL")
MATCH_TIMERS = ("BOT_FILL_SECS", "START_NOW_SECS", "JOIN_COOLDOWN_SECS")
PROGRESS = frozenset({"play", "bury", "trick", "round_start", "round_end", "declare", "trump"})
EXPECTED_REFUSALS = frozenset({"stale_connection", "not_your_turn", "illegal_play", "no_room",
                               "room_not_found", "wrong_phase", "none", "resumed_after_leave"})
# the messages the server counts against limits.QUEUE_STARTS
QUEUE_STARTS = ("queue_join", "queue_start_bots", "open_table_join")
FAULTS = ("drop", "stall", "oneway_down", "oneway_up", "delay", "storm", "relaunch", "dup")
# unscaled seconds a stall or one-way fault lasts: a blip, a lost pong, past
# the server's 20 s, past the 60 s hold
STALL_SECS = (1.0, 4.0, 12.0, 25.0, 65.0)
# real seconds between a lobby client's queue or code retries: the server's
# join and lookup rate limits run on real time, not the scaled timers
RETRY_SECS = 3.0
# unscaled seconds after a fault's end by which the seat must be back, else
# the fault failed
RECOVERY_DEADLINE_SECS = 60.0
# the share of limits.QUEUE_START_LIMIT one client may use in its window
QUEUE_START_BUDGET = 0.8


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


class Soak:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.scale = args.scale
        self.rng = random.Random(args.seed)
        self.tmp = Path(tempfile.mkdtemp(prefix="shengji-online-soak-"))
        os.environ["SHENGJI_DATA_DIR"] = str(self.tmp)
        os.environ["SHENGJI_LOG_DIR"] = str(self.tmp / "logs")
        os.environ.setdefault("SHENGJI_BOT", args.bot)
        from shengji.api import limits, matchmaking, server as srv
        self.srv, self.mm = srv, matchmaking
        self.mm_limits = limits.QUEUE_START_LIMIT
        for name in SERVER_TIMERS:
            setattr(srv, name, getattr(srv, name) / self.scale)
        for name in MATCH_TIMERS:
            setattr(matchmaking, name, getattr(matchmaking, name) / self.scale)
        self.clients: list = []
        self.by_seat: dict[tuple[str, int], object] = {}
        self.progress: dict[str, float] = {}
        self.stuck: list[dict] = []
        self.plays = audit.PlayAudit()
        self.refused: dict[str, int] = {}
        self.strikes: list[dict] = []
        self.double: list[dict] = []
        self.socket_faults: list[dict] = []
        self.writer_errors: list[dict] = []
        self.writer_disconnects: list[dict] = []
        self.task_exits: list[dict] = []
        self.harness_errors: list[dict] = []
        self.ledger = audit.FaultLedger()
        self.rooms_seen: set[str] = set()
        self.presence: dict[tuple[str, int], list[tuple[float, str]]] = {}
        self.decision_at: dict[tuple[str, int], tuple[float, bool]] = {}
        self._hook()

    # observation of the unmodified server
    def _hook(self) -> None:
        srv = self.srv
        real_action = srv.handle_action
        real_strike = srv._count_timeout
        real_log = srv.Room.log_event
        soak = self

        async def handle_action(room, seat, msg):
            kind = msg.get("type")
            if kind not in ("play", "bury") or room.round is None:
                return await real_action(room, seat, msg)
            key = soak._server_key(room, seat)
            try:
                await real_action(room, seat, msg)
            except Exception as e:
                code = getattr(e, "code", None) or type(e).__name__
                soak.refused[code] = soak.refused.get(code, 0) + 1
                raise
            client = soak.by_seat.get((room.code, seat))
            # the play's tag names its send; the decision that send was for
            # is the one its first send saw
            soak.plays.check(client.name if client else f"?{room.code}/{seat}",
                             client.rec.sent if client else [], msg.get("_soak"), key,
                             {"room": room.code, "seat": seat, "kind": kind,
                              "round": room.game.round_no if room.game else None})

        real_sync = srv._sync_move_timer

        def count_timeout(room, seat):
            soak._strike(room, seat)
            return real_strike(room, seat)

        def log_event(room, kind, **data):
            if kind in PROGRESS:
                soak.progress[room.code] = time.monotonic()
            soak._presence(room, kind, data)
            return real_log(room, kind, **data)

        def sync_move_timer(room):
            before = [sd.turn_started if sd is not None else None for sd in room.seats]
            real_sync(room)
            soak._decision_starts(room, before)

        srv.handle_action = handle_action
        srv._count_timeout = count_timeout
        srv.Room.log_event = log_event
        srv._sync_move_timer = sync_move_timer

    # the server's own record of each seat's presence, for the strike check
    def _presence(self, room, kind: str, data: dict) -> None:
        way = {"seat_reconnected": "up", "seat_disconnected": "down", "seat_left": "down"}.get(kind)
        if way is not None and isinstance(data.get("seat"), int):
            self.presence.setdefault((room.code, data["seat"]), []).append((self.srv.now(), way))

    def _decision_starts(self, room, before: list) -> None:
        """A decision starts where the server starts its clock afresh; a
        clock rebased for a returning seat keeps the decision's start."""
        for i, sd in enumerate(room.seats):
            if sd is None:
                continue
            key, after = (room.code, i), sd.turn_started
            if after is None:
                self.decision_at.pop(key, None)
            elif after != before[i] or key not in self.decision_at:
                self.decision_at[key] = (after, bool(sd.connected and not sd.is_bot))

    def _strike(self, room, seat: int) -> None:
        """A move-clock strike, read against the server's presence record:
        time away when the seat was connected for less than MOVE_TIMER of the
        decision, or less than RETURN_MIN since its last return. The client's
        own down time in the window is kept beside it."""
        srv, sd = self.srv, room.seats[seat]
        if sd.is_bot or sd.away:
            return
        at = srv.now()
        start, start_up = self.decision_at.get((room.code, seat), (sd.turn_started, True))
        entry = {"room": room.code, "seat": seat, "matched": room.matched, "decision_secs": None,
                 "time_away": False}
        if start is not None:
            entry.update(audit.strike_presence(
                start=start, start_connected=start_up, events=self.presence.get((room.code, seat), []),
                at=at, move_timer=srv.MOVE_TIMER, return_min=srv.RETURN_MIN, slack=srv.MOVE_TIMER_POLL + 0.05))
            entry["decision_secs"] = at - start
            client = self.by_seat.get((room.code, seat))
            if client is not None:
                # monotonic and the server clock tick together inside one run
                entry["client_down_secs"] = client.down_since(time.monotonic() - (at - start))
        self.strikes.append(entry)

    def _server_key(self, room, seat: int) -> tuple:
        rnd = room.round
        trick = self.srv.trick_json(rnd.trick, rnd.ordering) if rnd.phase == "play" else None
        return audit.frame_key(list(rnd.hands[seat]), trick)

    def _server_view(self, room, seat: int) -> tuple | None:
        """What the seat's next state frame would show, as ``audit.state_view``
        reads a frame."""
        g, rnd = room.game, room.round
        if g is None or rnd is None:
            return None
        phase = "game_over" if g.game_over else rnd.phase
        return (room.code, seat, phase, rnd.turn,
                audit.frame_key(list(rnd.hands[seat]), self.srv.trick_json(rnd.trick, rnd.ordering)))

    # the clients' card choice: a legal play of their own seat
    def brain(self, client, st: dict) -> list[int] | None:
        room = self.srv.rooms.get(st.get("room") or "")
        seat = st.get("you")
        if room is None or room.round is None or seat is None:
            return None
        rnd = room.round
        hand = st.get("hand", [])
        if sorted(c["code"] for c in hand) != sorted(rnd.hands[seat]) or rnd.turn != seat:
            return None        # the frame is not the server's decision any more: wait for the next
        if st.get("phase") == "bury":
            if rnd.phase != "bury":
                return None
            return [c["id"] for c in self.rng.sample(hand, st.get("kitty_count", 8))]
        if rnd.phase != "play":
            return None
        from shengji.rl.actions import enumerate_actions
        plays = enumerate_actions(rnd, seat)
        if not plays:
            return None
        pick = list(self.rng.choice(plays))
        ids, pool = [], list(hand)
        for code in pick:
            c = next(c for c in pool if c["code"] == code)
            pool.remove(c)
            ids.append(c["id"])
        return ids

    # tables
    async def lobby(self, client) -> None:
        """A client back in the lobby queues again after a pause, and again
        while it is neither seated nor queued (a send lost with its socket)."""
        await asyncio.sleep(self.rng.uniform(0.5, 3.0) / self.scale)
        while not client.stop and client.room is None:
            if not client.queued:
                await self._queue_start(client, {"type": "queue_join", "mode": client.mode, "name": client.name})
            await asyncio.sleep(RETRY_SECS)

    async def _queue_start(self, client, msg: dict) -> None:
        """A queue start, held back while this client has used
        ``QUEUE_START_BUDGET`` of the server's per-address queue starts in its
        window (real time), so the run stays under the limit as a player who
        queues by hand does."""
        limit, window = self.mm_limits
        sent = client.queue_starts
        while sent and sent[0] <= time.monotonic() - window:
            sent.popleft()
        if len(sent) >= int(limit * QUEUE_START_BUDGET):
            return
        sent.append(time.monotonic())
        await client._send(msg)

    async def casual_host(self, host, mates: list) -> None:
        """A casual table opened by ``host`` with its mates joining by code, then bots."""
        while not host.stop:
            await asyncio.sleep(0.2)
            if host.room is not None or host.ws is None:
                continue
            code = host.table_code
            if code is None:
                continue
            seated = host.table_humans
            if seated >= 1 + len(mates) or time.monotonic() - host.table_since > 30 / self.scale:
                await host._send({"type": "table_start_bots", **({"panel_seq": host.panel_seq}
                                                                 if host.panel_seq is not None else {})})
                # one Start per table, again only if it is still waiting after a retry gap
                await asyncio.sleep(RETRY_SECS)

    def make_clients(self, port_for) -> None:
        from client import SoakClient
        n = 0

        def mk(mode: str):
            nonlocal n
            n += 1
            ip = None if self.args.shared_client_ip else client_ip(n)
            c = SoakClient(f"Soak-{n}", f"soak{n:019d}", port_for(n), self.scale,
                           random.Random(self.rng.random()), self.brain, self._lobby_for(mode),
                           host=self.args.host, client_ip=ip)
            c.mode = mode
            c.table_code = c.panel_seq = None
            c.table_humans = 0
            c.queued = False
            c.table_since = time.monotonic()
            c.leave_after = self.args.rounds_per_sitting
            c.queue_starts = collections.deque()
            self.clients.append(c)
            return c

        for _ in range(self.args.ranked_tables):
            for _ in range(4):
                mk("ranked")
        self.casual_groups = []
        for i in range(self.args.casual_tables):
            humans = 1 + i % 4
            group = [mk("casual") for _ in range(humans)]
            self.casual_groups.append(group)

    def _lobby_for(self, mode: str):
        async def go(client):
            if mode == "ranked":
                return await self.lobby(client)
            group = next(g for g in self.casual_groups if client in g)
            await asyncio.sleep(self.rng.uniform(0.5, 3.0) / self.scale)
            if client.stop or client.room is not None:
                return
            if client is group[0]:
                client.table_code = None
                client.table_since = time.monotonic()
                while not client.stop and client.room is None:
                    if not client.queued:
                        await self._queue_start(client, {"type": "queue_join", "mode": "casual",
                                                         "name": client.name, "allow_joiners": False})
                    await asyncio.sleep(RETRY_SECS)
            else:
                while not client.stop and client.room is None:
                    code = group[0].table_code
                    if code is not None and group[0].room is None and not client.queued:
                        await client._send({"type": "table_join", "code": code, "name": client.name})
                    await asyncio.sleep(RETRY_SECS)
        return go

    def _wire_queue_frames(self, client) -> None:
        on = client._on

        async def wrapped(msg: dict) -> None:
            t = msg.get("type")
            if t == "queue_state":
                client.queued = bool(msg.get("queued"))
                client.panel_seq = msg.get("panel_seq")
                if msg.get("code"):
                    client.table_code = msg.get("code")
            elif t == "table" and msg.get("phase") == "open":
                client.table_code = msg.get("code")
                client.table_humans = sum(1 for s in (msg.get("seats") or [])
                                          if isinstance(s, dict) and s.get("name") and not s.get("bot"))
            elif t in ("room", "queue_removed"):
                client.queued = False
            if t == "room":
                client.table_code = None
            await on(msg)
            if t in ("room", "state") and client.room is not None and client.seat is not None:
                self.by_seat[(client.room, client.seat)] = client
                self.rooms_seen.add(client.room)
        client._on = wrapped

    # faults
    async def chaos(self, client, proxy, until: float) -> None:
        from proxy import DOWN, UP
        while time.monotonic() < until and not client.stop:
            await asyncio.sleep(self.rng.uniform(*self.args.fault_gap) / self.scale)
            if client.room is None or client.state is None or time.monotonic() >= until:
                continue
            kind = self.rng.choice(FAULTS)
            client.gen_at_fault = client.gen
            rec = self.ledger.open(kind, client.name, time.monotonic())
            origin = rec["origin"] = self._origin(client)
            secs = self.rng.choice(STALL_SECS) / self.scale
            if kind == "drop":
                proxy.cut()
                origin["fresh_after"] = time.monotonic()
            elif kind == "storm":
                for _ in range(4):
                    proxy.cut()
                    origin["fresh_after"] = time.monotonic()
                    await asyncio.sleep(0.3 / self.scale)
            elif kind in ("stall", "oneway_down", "oneway_up"):
                proxy.pause(*{"stall": (UP, DOWN), "oneway_down": (DOWN,), "oneway_up": (UP,)}[kind])
                await asyncio.sleep(secs)
                proxy.resume()
            elif kind == "delay":
                proxy.delay = self.rng.uniform(0.2, 1.2) / self.scale
                await asyncio.sleep(secs)
                proxy.delay = 0.0
            elif kind == "relaunch":
                # the app killed and opened again: only the saved room and token survive
                client.offline_until = time.monotonic() + secs
                proxy.cut()
                origin["fresh_after"] = time.monotonic()
                client.state = None
                client.pending = None
                await asyncio.sleep(secs)
            elif kind == "dup":
                # the fault is the client's next play sent twice; it ends when that goes out
                client.dup_sent_at = None
                client.dup_next = True
                while client.dup_sent_at is None and not client.stop and time.monotonic() < until:
                    if self.srv.rooms.get(origin["room"] or "") is None:
                        break
                    await asyncio.sleep(0.02)
                if client.dup_sent_at is None:
                    client.dup_next = False
                    audit.FaultLedger.close(rec, "censored", reason="shutdown" if time.monotonic() >= until
                                            or client.stop else "table_ended")
                    continue
            end = client.dup_sent_at if kind == "dup" else time.monotonic()
            client.rec.faults.append({"kind": kind, "secs": secs * self.scale})
            rec["trace"] = {}
            outcome, took, reason = await self._recovered(client, end, until, kind in ("drop", "storm", "relaunch"),
                                                          rec["trace"], origin)
            audit.FaultLedger.close(rec, outcome, secs=None if took is None else took * self.scale, reason=reason)

    def _origin(self, client) -> dict:
        """The seat a fault hits, fixed when it is injected: the outcome is
        resolved against this room, seat, owner and socket, wherever the
        client is by the time the fault ends."""
        room = self.srv.rooms.get(client.room or "")
        sd = room.seats[client.seat] if room is not None and client.seat is not None else None
        return {"room": client.room, "seat": client.seat, "gen": client.gen,
                "owner": (audit.seat_owner(sd) if sd is not None else None) or client.device,
                "leaves": len(client.rec.leaves), "fresh_after": time.monotonic()}

    @staticmethod
    def _left_origin(client, origin: dict) -> bool:
        """Whether this client, the origin seat's owner, sent a Leave for that
        room and seat since the fault began."""
        return (origin["room"], origin["seat"]) in client.rec.leaves[origin["leaves"]:]

    async def _recovered(self, client, end: float, until: float, cut: bool,
                         trace: dict | None = None, origin: dict | None = None) -> tuple[str, float | None, str | None]:
        """The fault's outcome: ``recovered`` (with the seconds from its end)
        once ``audit.recovered`` holds: the server holds the seat on a live
        socket, the client's state is the server's decision for that seat, and
        either that state arrived since the fault, or on a socket opened after
        the fault's last cut, or the socket open when the fault began survived
        it with a frame through since; ``failed`` past
        ``RECOVERY_DEADLINE_SECS`` or when the client is off the original seat
        (``origin``) while its room goes on, unless it sent a Leave for that
        room and seat; else
        ``censored``. A state from any other room or seat never recovers the
        original one. ``trace`` gets the unscaled seconds after the end at
        which each condition first held, for reading a slow one."""
        trace = {} if trace is None else trace
        origin = self._origin(client) if origin is None else origin
        gen0 = origin["gen"]
        if not cut and client.gen == client.gen_at_fault and client.ws is not None and client.awaiting is None:
            # ws.ts probes a socket that may have stalled (back online, back in view)
            client.probe()
        room_code, seat = origin["room"], origin["seat"]
        deadline = end + RECOVERY_DEADLINE_SECS / self.scale
        while not client.stop:
            now = time.monotonic()
            if now >= until:
                return "censored", None, "shutdown"
            room = self.srv.rooms.get(room_code or "")
            if room is None:
                return "censored", None, "table_ended"
            if seat is None:
                return "failed", None, "seat_lost"
            sd = room.seats[seat]
            left = self._left_origin(client, origin)
            if client.room != room_code or client.seat != seat or audit.seat_owner(sd) != origin["owner"]:
                if left:
                    return "censored", None, "left_table"      # this client's own Leave
                return "failed", None, "seat_lost"
            cview = audit.state_view(client.state) if client.state_gen == client.gen else None
            sview = self._server_view(room, seat)
            for name, held in (("new_socket", client.gen != gen0), ("ws_open", client.ws is not None),
                               ("rx_since_end", client.last_rx >= end),
                               ("seat_connected", sd.connected and not sd.is_bot),
                               ("state_since_end", client.state_at is not None and client.state_at >= end),
                               ("state_is_server_s", cview is not None and cview == sview)):
                if held and name not in trace:
                    trace[name] = round((now - end) * self.scale, 2)
            via = audit.recovered(fault_end=end, state_at=client.state_at, client_view=cview,
                                  server_view=sview, ws_open=client.ws is not None,
                                  seat_connected=sd.connected, seat_bot=sd.is_bot,
                                  rx_at=client.last_rx, same_socket=client.gen == gen0,
                                  new_socket=(cut and client.state_gen == client.gen and client.gen != gen0
                                              and client.socket_opened.get(client.state_gen, -1.0)
                                              >= origin["fresh_after"]))
            if via is not None:
                trace["via"] = via
                return "recovered", now - end, None
            if now >= deadline:
                return "failed", None, "deadline"
            await asyncio.sleep(0.02)
        return "censored", None, "shutdown"

    async def monitor(self, until: float) -> None:
        srv = self.srv
        limit = (srv.MOVE_TIMER + srv.MOVE_TIMER_POLL) + 15.0 / self.scale
        flagged: set[str] = set()
        seen: dict = {}
        while time.monotonic() < until:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            for code, room in list(srv.rooms.items()):
                for attr, how in room.task_exits.items():
                    if how.startswith("error"):
                        entry = {"room": code, "task": attr, "exit": how[:200]}
                        if entry not in self.task_exits:
                            self.task_exits.append(entry)
                g, rnd = room.game, room.round
                if g is None or rnd is None or g.game_over or rnd.phase in ("round_end", "deal"):
                    continue
                last = self.progress.get(code)
                if last is not None and now - last > limit and code not in flagged:
                    flagged.add(code)
                    self.stuck.append({"room": code, "phase": rnd.phase, "gap_secs": round((now - last) * self.scale, 1),
                                       "humans_connected": sum(1 for s in room.seats if not s.is_bot and s.connected)})
            self._check_seats(seen)

    def _check_seats(self, seen: dict) -> None:
        """One owner per human seat across every room; a connected seat on a
        socket with a running writer. A socket fault counts once it holds on
        two checks running (an attach or detach is not atomic across them)."""
        holders = []
        now_faults = set()
        for code, room in list(self.srv.rooms.items()):
            for i, sd in enumerate(room.seats):
                holders.append((code, i, audit.seat_owner(sd)))
                for what in audit.seat_socket_faults(sd):
                    if what in ("writer_error", "writer_disconnect"):
                        entry = {"room": code, "seat": i, "error": (sd.writer_error or "")[:200]}
                        bucket = self.writer_errors if what == "writer_error" else self.writer_disconnects
                        if entry not in bucket:
                            bucket.append(entry)
                    else:
                        now_faults.add((code, i, what))
        for c in audit.seat_conflicts(holders):
            key = (c["owner"], tuple(c["seats"]))
            if key not in seen.setdefault("double", set()):
                seen["double"].add(key)
                self.double.append(c)
        for f in now_faults & seen.get("socket_prev", set()):
            if f not in seen.setdefault("socket", set()):
                seen["socket"].add(f)
                self.socket_faults.append({"room": f[0], "seat": f[1], "fault": f[2]})
        seen["socket_prev"] = now_faults

    # run
    async def run(self) -> dict:
        import uvicorn
        srv = self.srv
        from proxy import FaultProxy
        host = require_local(self.args.host)
        loopback_family(host)
        cfg = uvicorn.Config(srv.app, host=host, port=0, log_level="warning",
                             ws_ping_interval=srv.WS_PING_INTERVAL, ws_ping_timeout=srv.WS_PING_TIMEOUT)
        server = uvicorn.Server(cfg)
        serving = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        proxies = []

        async def proxy_port(_: int) -> int:
            p = FaultProxy(port, host)
            proxies.append(p)
            return await p.start()

        ports = [await proxy_port(i) for i in range(4 * self.args.ranked_tables
                                                    + sum(1 + i % 4 for i in range(self.args.casual_tables)))]
        self.make_clients(lambda n: ports[n - 1])
        for c in self.clients:
            self._wire_queue_frames(c)
        t0 = time.monotonic()
        until = t0 + self.args.minutes * 60
        named = [(f"client {c.name}", c.run(until)) for c in self.clients]
        named += [(f"chaos {c.name}", self.chaos(c, p, until - 5)) for c, p in zip(self.clients, proxies)]
        named += [(f"casual_host {g[0].name}", self.casual_host(g[0], g[1:])) for g in self.casual_groups]
        named += [("monitor", self.monitor(until)), ("progress", self._progress_line(t0, until))]
        tasks = {asyncio.create_task(coro): name for name, coro in named}
        await asyncio.wait(tasks, timeout=self.args.minutes * 60 + 30)
        for t, name in tasks.items():
            if t.done() and not t.cancelled() and t.exception() is not None:
                e = t.exception()
                self.harness_errors.append({"task": name, "error": f"{type(e).__name__}: {e}"[:300]})
            t.cancel()
        for c in self.clients:
            for e in c.rec.task_errors:
                self.harness_errors.append({"task": f"client {c.name} side task", "error": e})
        self.ledger.censor_open("shutdown")
        for c in self.clients:
            await c.close()
        for p in proxies:
            await p.close()
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(serving, 10)
        out = self.report(time.monotonic() - t0)
        if serving.done() and not serving.cancelled() and serving.exception() is not None:
            e = serving.exception()
            out["harness_errors"] += 1
            out["harness_error_list"].append({"task": "uvicorn", "error": f"{type(e).__name__}: {e}"[:300]})
            out["verdict"] = audit.verdict(out, self.floors())
        return out

    def floors(self) -> audit.Floors:
        a = self.args
        return audit.Floors(rooms=a.min_rooms, rounds=a.min_rounds, recoveries=a.min_recoveries,
                            resolved_share=a.min_resolved_share)

    async def _progress_line(self, t0: float, until: float) -> None:
        while time.monotonic() < until:
            await asyncio.sleep(60)
            r = self.report(time.monotonic() - t0, brief=True)
            print(json.dumps({"t_min": round((time.monotonic() - t0) / 60, 1), **r}), flush=True)

    def report(self, elapsed: float, brief: bool = False) -> dict:
        rec = [c.rec for c in self.clients]
        pairs = self.ledger.recovery_secs()
        recov = [x for _, x in pairs]
        by_kind: dict[str, list[float]] = {}
        for k, x in pairs:
            by_kind.setdefault(k, []).append(x)
        refusals: dict[str, int] = {}
        for x in rec:
            for k, v in x.errors.items():
                refusals[k] = refusals.get(k, 0) + v
        rounds = sum(1 for _ in self._round_ends())
        away = [s for s in self.strikes if s["time_away"]]
        ledger = self.ledger.summary()
        out = {
            "elapsed_min": round(elapsed / 60, 1), "scale": self.scale, "clients": len(self.clients),
            "host": self.args.host, "client_ips": "shared" if self.args.shared_client_ip else "one per client",
            "rooms": len(self.rooms_seen), "rounds_logged": rounds,
            "faults": ledger["total"], "fault_ledger": ledger,
            "plays_applied": self.plays.applied, "stuck_tables": len(self.stuck),
            "wrong_decision_plays": len(self.plays.wrong), "strikes_total": len(self.strikes),
            "strikes_time_away": len(away), "double_seats": len(self.double),
            "seat_socket_faults": len(self.socket_faults), "writer_errors": len(self.writer_errors),
            "writer_disconnects": len(self.writer_disconnects),
            "task_exit_errors": len(self.task_exits), "harness_errors": len(self.harness_errors),
            "recovery_s": {"n": len(recov), "p50": pct(recov, 0.5), "p95": pct(recov, 0.95),
                           "worst": max(recov) if recov else None,
                           "by_kind": {k: {"n": len(v), "p95": pct(v, 0.95), "worst": max(v)}
                                       for k, v in sorted(by_kind.items())}},
            "recovered_via": via_counts(self.ledger.faults),
            "queue_starts_max": max((sum(c.rec.sent_types.get(t, 0) for t in QUEUE_STARTS) for c in self.clients),
                                    default=0),
            "client_refusals": refusals,
            "unexpected_refusals": sorted(k for k in refusals if k not in EXPECTED_REFUSALS),
        }
        firsts = [r["trace"]["state_since_end"] for r in self.ledger.faults
                  if r["outcome"] == "recovered" and "state_since_end" in (r.get("trace") or {})]
        out["first_post_fault_state_s"] = {"n": len(firsts), "p50": pct(firsts, 0.5), "p95": pct(firsts, 0.95),
                                           "worst": max(firsts) if firsts else None}
        if brief:
            out.pop("fault_ledger")
            out["fault_outcomes"] = {k: ledger[k] for k in ("recovered", "failed", "censored", "open")}
            out.pop("recovery_s")
            out["recovery_p95"] = pct(recov, 0.95)
            return out
        failed = [r for r in self.ledger.faults if r["outcome"] == "failed"]
        slow = sorted((r for r in self.ledger.faults if r["outcome"] == "recovered"),
                      key=lambda r: -r["secs"])[:20]
        out.update({"stuck": self.stuck[:50], "wrong": self.plays.wrong[:50], "strikes": self.strikes[:50],
                    "double": self.double[:20], "socket_fault_list": self.socket_faults[:20],
                    "writer_error_list": self.writer_errors[:20], "task_exits": self.task_exits[:20],
                    "harness_error_list": self.harness_errors[:20], "failed_faults": failed[:30],
                    "slowest_recoveries": slow,
                    "per_client": {c.name: {"mode": getattr(c, "mode", None), "sent": c.rec.sent_types,
                                            "refused_after": c.rec.refused_after} for c in self.clients}, "server_refusals": self.refused, "tmp": str(self.tmp)})
        out["verdict"] = audit.verdict(out, self.floors())
        return out

    def _round_ends(self):
        logs = self.tmp / "logs"
        if not logs.is_dir():
            return
        for f in logs.rglob("*.jsonl"):
            with contextlib.suppress(OSError):
                for line in f.open(encoding="utf-8", errors="replace"):
                    if '"round_end"' in line:
                        yield 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--scale", type=float, default=4.0, help="divide every server and client timer by this")
    ap.add_argument("--ranked-tables", type=int, default=3)
    ap.add_argument("--casual-tables", type=int, default=4)
    ap.add_argument("--rounds-per-sitting", type=int, default=3)
    ap.add_argument("--fault-gap", type=float, nargs=2, default=(15.0, 45.0),
                    help="unscaled seconds between one client's faults (uniform range)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bot", default="heuristic", help="SHENGJI_BOT for the run's server")
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback address for the server, the proxies and the clients: 127.0.0.1 or ::1")
    ap.add_argument("--shared-client-ip", action="store_true",
                    help="send no Fly-Client-IP, so every client shares the loopback peer's limits")
    ap.add_argument("--min-rooms", type=int, default=3, help="floor: rooms seen, else INCONCLUSIVE")
    ap.add_argument("--min-rounds", type=int, default=10, help="floor: rounds logged, else INCONCLUSIVE")
    ap.add_argument("--min-recoveries", type=int, default=20, help="floor: recovered faults, else INCONCLUSIVE")
    ap.add_argument("--min-resolved-share", type=float, default=0.8,
                    help="floor: share of faults recovered or failed (not censored), else INCONCLUSIVE")
    ap.add_argument("--out", type=Path, default=None, help="report JSON path")
    args = ap.parse_args(argv)
    require_not_deployed()
    loopback_family(args.host)
    soak = Soak(args)
    report = asyncio.run(soak.run())
    text = json.dumps(report, indent=1, default=str)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return EXIT[report["verdict"]["status"]]


EXIT = {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}


def via_counts(faults: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in faults:
        if r["outcome"] == "recovered":
            via = (r.get("trace") or {}).get("via", "?")
            out[via] = out.get(via, 0) + 1
    return dict(sorted(out.items()))


def client_ip(n: int) -> str:
    """Client ``n``'s address for the server's per-address limits: one of
    198.18.0.0/15, the range set aside for benchmarks, never a real peer."""
    return f"198.18.{n // 256}.{n % 256}"


if __name__ == "__main__":
    sys.exit(main())
