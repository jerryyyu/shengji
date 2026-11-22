"""Online soak, tier (a): the real game server on loopback, guest clients over
real WebSockets, each behind its own fault proxy.

    server/.venv/bin/python server/scripts/online_soak/soak.py --minutes 20

One process: uvicorn serves ``shengji.api.server:app`` on 127.0.0.1 with a
temp data and log dir, the server's timers divided by ``--scale``, and the
clients and proxies run on the same event loop. The server source is not
changed; the run wraps four of its functions to observe it (the action
handler, the move-clock strike, the room log and nothing else), and a
client picks its cards from its own seat's legal plays in the server's
round. Every address goes through ``localonly.require_local``.

The report (JSON, and a summary on stdout) holds the plan's bar:
stuck tables, wrong-decision plays, strikes for time away, recovery
p50/p95/worst in unscaled seconds, double seats, task exits and the
refusal codes seen.
"""
from __future__ import annotations

import argparse
import asyncio
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

from localonly import require_local, require_not_deployed  # noqa: E402

# the timers a scaled run divides (server.py and matchmaking.py module constants)
SERVER_TIMERS = ("BOT_DELAY", "DEAL_DELAY", "DECLARE_GRACE", "DECLARE_EXTEND", "ROOM_TTL",
                 "EMPTY_ROOM_BOT_DELAY", "MOVE_TIMER", "RETURN_MIN", "TAKEOVER_AFTER",
                 "READY_KEEP_SECONDS", "WS_PING_INTERVAL", "WS_PING_TIMEOUT", "MOVE_TIMER_POLL")
MATCH_TIMERS = ("BOT_FILL_SECS", "START_NOW_SECS", "JOIN_COOLDOWN_SECS")
PROGRESS = frozenset({"play", "bury", "trick", "round_start", "round_end", "declare", "trump"})
EXPECTED_REFUSALS = frozenset({"stale_connection", "not_your_turn", "illegal_play", "no_room",
                               "room_not_found", "rate_limited", "wrong_phase", "none",
                               "resumed_after_leave"})
FAULTS = ("drop", "stall", "oneway_down", "oneway_up", "delay", "storm", "relaunch", "dup")
# unscaled seconds a stall or one-way fault lasts: a blip, a lost pong, past
# the server's 20 s, past the 60 s hold
STALL_SECS = (1.0, 4.0, 12.0, 25.0, 65.0)
# real seconds between a lobby client's queue or code retries: the server's
# join and lookup rate limits run on real time, not the scaled timers
RETRY_SECS = 3.0


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
        from shengji.api import matchmaking, server as srv
        self.srv, self.mm = srv, matchmaking
        for name in SERVER_TIMERS:
            setattr(srv, name, getattr(srv, name) / self.scale)
        for name in MATCH_TIMERS:
            setattr(matchmaking, name, getattr(matchmaking, name) / self.scale)
        self.clients: list = []
        self.by_seat: dict[tuple[str, int], object] = {}
        self.progress: dict[str, float] = {}
        self.stuck: list[dict] = []
        self.wrong: list[dict] = []
        self.applied = 0
        self.refused: dict[str, int] = {}
        self.strikes: list[dict] = []
        self.double: list[dict] = []
        self.task_exits: list[dict] = []
        self.faults: dict[str, int] = {}
        self.recovery: list[dict] = []
        self.rooms_seen: set[str] = set()
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
            rnd = room.round
            key = soak._server_key(room, seat)
            try:
                await real_action(room, seat, msg)
            except Exception as e:
                code = getattr(e, "code", None) or type(e).__name__
                soak.refused[code] = soak.refused.get(code, 0) + 1
                raise
            soak.applied += 1
            client = soak.by_seat.get((room.code, seat))
            if client is None:
                return
            ids = list(msg.get("card_ids") or [])
            # the latest send of exactly these cards decides which decision they were for
            mine = [x for x in client.rec.sent if x.kind == kind and x.card_ids == ids]
            if not mine or mine[-1].key != key:
                soak.wrong.append({"room": room.code, "seat": seat, "kind": kind,
                                   "round": room.game.round_no if room.game else None,
                                   "matched_send": bool(mine), "resend": bool(mine and mine[-1].resend)})
            del rnd

        def count_timeout(room, seat):
            sd = room.seats[seat]
            if not sd.is_bot and not sd.away:
                client = soak.by_seat.get((room.code, seat))
                started = sd.turn_started
                away = None
                if client is not None and started is not None:
                    # monotonic and the server clock tick together inside one run
                    window = srv.now() - started
                    away = client.down_since(time.monotonic() - window)
                soak.strikes.append({"room": room.code, "seat": seat, "matched": room.matched,
                                     "down_secs_in_decision": away,
                                     "time_away": bool(away and away > 0.0)})
            return real_strike(room, seat)

        def log_event(room, kind, **data):
            if kind in PROGRESS:
                soak.progress[room.code] = time.monotonic()
            return real_log(room, kind, **data)

        srv.handle_action = handle_action
        srv._count_timeout = count_timeout
        srv.Room.log_event = log_event

    def _server_key(self, room, seat: int) -> tuple:
        from client import frame_key
        rnd = room.round
        trick = self.srv.trick_json(rnd.trick, rnd.ordering) if rnd.phase == "play" else None
        return frame_key(list(rnd.hands[seat]), trick)

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
                await client._send({"type": "queue_join", "mode": client.mode, "name": client.name})
            await asyncio.sleep(RETRY_SECS)

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
                await asyncio.sleep(2.0 / self.scale)

    def make_clients(self, port_for) -> None:
        from client import SoakClient
        n = 0

        def mk(mode: str):
            nonlocal n
            n += 1
            c = SoakClient(f"Soak-{n}", f"soak{n:019d}", port_for(n), self.scale,
                           random.Random(self.rng.random()), self.brain, self._lobby_for(mode))
            c.mode = mode
            c.table_code = c.panel_seq = None
            c.table_humans = 0
            c.queued = False
            c.table_since = time.monotonic()
            c.leave_after = self.args.rounds_per_sitting
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
                        await client._send({"type": "queue_join", "mode": "casual", "name": client.name,
                                            "allow_joiners": False})
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
            self.faults[kind] = self.faults.get(kind, 0) + 1
            secs = self.rng.choice(STALL_SECS) / self.scale
            if kind == "drop":
                proxy.cut()
            elif kind == "storm":
                for _ in range(4):
                    proxy.cut()
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
                client.state = None
                client.pending = None
                await asyncio.sleep(secs)
            elif kind == "dup":
                client.dup_next = True
                continue
            end = time.monotonic()
            client.rec.faults.append({"kind": kind, "secs": secs * self.scale})
            took = await self._recovered(client, end, until, kind in ("drop", "storm", "relaunch"))
            if took is not None:
                self.recovery.append({"kind": kind, "secs": took * self.scale})

    async def _recovered(self, client, end: float, until: float, cut: bool) -> float | None:
        """Seconds from a fault's end until the server holds the seat on a live
        socket and the client holds a state from after the fault (a replaced
        socket's resume state, or a surviving socket's buffered frames)."""
        if not cut and client.gen == client.gen_at_fault and client.ws is not None and client.awaiting is None:
            # ws.ts probes a socket that may have stalled (back online, back in view)
            client.probe()
        while time.monotonic() < until and not client.stop:
            room = self.srv.rooms.get(client.room or "")
            if room is None or client.seat is None:
                return None        # the table ended meanwhile: nothing to recover
            sd = room.seats[client.seat]
            if client.gen != client.gen_at_fault:
                fresh = client.state_at is not None and client.state_at >= end
            else:
                # the socket outlived the fault: something must have come through since
                fresh = cut is False and client.last_rx >= end
            if client.ws is not None and sd.connected and not sd.is_bot and fresh:
                return time.monotonic() - end
            await asyncio.sleep(0.02)
        return None

    async def monitor(self, until: float) -> None:
        srv = self.srv
        limit = (srv.MOVE_TIMER + srv.MOVE_TIMER_POLL) + 15.0 / self.scale
        flagged: set[str] = set()
        while time.monotonic() < until:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            for code, room in list(srv.rooms.items()):
                g, rnd = room.game, room.round
                if g is None or rnd is None or g.game_over or rnd.phase in ("round_end", "deal"):
                    continue
                last = self.progress.get(code)
                if last is not None and now - last > limit and code not in flagged:
                    flagged.add(code)
                    self.stuck.append({"room": code, "phase": rnd.phase, "gap_secs": round((now - last) * self.scale, 1),
                                       "humans_connected": sum(1 for s in room.seats if not s.is_bot and s.connected)})
                for name in {s.name for s in room.seats if not s.is_bot}:
                    held = [i for i, s in enumerate(room.seats) if not s.is_bot and s.name == name]
                    if len(held) > 1:
                        self.double.append({"room": code, "seats": held})
                for attr, how in room.task_exits.items():
                    if how.startswith("error"):
                        entry = {"room": code, "task": attr, "exit": how[:200]}
                        if entry not in self.task_exits:
                            self.task_exits.append(entry)

    # run
    async def run(self) -> dict:
        import uvicorn
        srv = self.srv
        from proxy import FaultProxy
        host = require_local(self.args.host)
        cfg = uvicorn.Config(srv.app, host=host, port=0, log_level="warning",
                             ws_ping_interval=srv.WS_PING_INTERVAL, ws_ping_timeout=srv.WS_PING_TIMEOUT)
        server = uvicorn.Server(cfg)
        serving = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        proxies = []

        async def proxy_port(_: int) -> int:
            p = FaultProxy(port)
            proxies.append(p)
            return await p.start()

        ports = [await proxy_port(i) for i in range(4 * self.args.ranked_tables
                                                    + sum(1 + i % 4 for i in range(self.args.casual_tables)))]
        self.make_clients(lambda n: ports[n - 1])
        for c in self.clients:
            self._wire_queue_frames(c)
        t0 = time.monotonic()
        until = t0 + self.args.minutes * 60
        tasks = [asyncio.create_task(c.run(until)) for c in self.clients]
        tasks += [asyncio.create_task(self.chaos(c, p, until - 5)) for c, p in zip(self.clients, proxies)]
        tasks += [asyncio.create_task(self.casual_host(g[0], g[1:])) for g in self.casual_groups]
        tasks.append(asyncio.create_task(self.monitor(until)))
        tasks.append(asyncio.create_task(self._progress_line(t0, until)))
        await asyncio.wait(tasks, timeout=self.args.minutes * 60 + 30)
        for t in tasks:
            t.cancel()
        for c in self.clients:
            await c.close()
        for p in proxies:
            await p.close()
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(serving, 10)
        return self.report(time.monotonic() - t0)

    async def _progress_line(self, t0: float, until: float) -> None:
        while time.monotonic() < until:
            await asyncio.sleep(60)
            r = self.report(time.monotonic() - t0, brief=True)
            print(json.dumps({"t_min": round((time.monotonic() - t0) / 60, 1), **r}), flush=True)

    def report(self, elapsed: float, brief: bool = False) -> dict:
        rec = [c.rec for c in self.clients]
        recov = [r["secs"] for r in self.recovery]
        by_kind: dict[str, list[float]] = {}
        for r in self.recovery:
            by_kind.setdefault(r["kind"], []).append(r["secs"])
        refusals = {}
        for x in rec:
            for k, v in x.errors.items():
                refusals[k] = refusals.get(k, 0) + v
        rounds = sum(1 for _ in self._round_ends())
        away = [s for s in self.strikes if s["time_away"]]
        out = {
            "elapsed_min": round(elapsed / 60, 1), "scale": self.scale, "clients": len(self.clients),
            "rooms": len(self.rooms_seen), "rounds_logged": rounds,
            "faults": sum(self.faults.values()), "fault_kinds": dict(sorted(self.faults.items())),
            "plays_applied": self.applied, "stuck_tables": len(self.stuck),
            "wrong_decision_plays": len(self.wrong), "strikes_total": len(self.strikes),
            "strikes_time_away": len(away), "double_seats": len(self.double),
            "task_exit_errors": len(self.task_exits),
            "recovery_s": {"n": len(recov), "p50": pct(recov, 0.5), "p95": pct(recov, 0.95),
                           "worst": max(recov) if recov else None,
                           "by_kind": {k: {"n": len(v), "p95": pct(v, 0.95), "worst": max(v)}
                                       for k, v in sorted(by_kind.items())}},
            "client_refusals": refusals,
            "unexpected_refusals": sorted(k for k in refusals if k not in EXPECTED_REFUSALS),
        }
        if not brief:
            out.update({"stuck": self.stuck[:50], "wrong": self.wrong[:50], "strikes": self.strikes[:50],
                        "double": self.double[:20], "task_exits": self.task_exits[:20],
                        "server_refusals": self.refused, "tmp": str(self.tmp)})
            out["bar"] = {
                "stuck_tables_0": out["stuck_tables"] == 0,
                "wrong_decision_0": out["wrong_decision_plays"] == 0,
                "time_away_strikes_0": out["strikes_time_away"] == 0,
                "recovery_p95_le_5s": (out["recovery_s"]["p95"] or 0) <= 5.0,
                "recovery_worst_le_15s": (out["recovery_s"]["worst"] or 0) <= 15.0,
                "double_seats_0": out["double_seats"] == 0,
                "task_exits_0": out["task_exit_errors"] == 0,
            }
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
    ap.add_argument("--host", default="127.0.0.1", help="bind address: loopback only")
    ap.add_argument("--out", type=Path, default=None, help="report JSON path")
    args = ap.parse_args(argv)
    require_not_deployed()
    require_local(args.host)
    soak = Soak(args)
    report = asyncio.run(soak.run())
    text = json.dumps(report, indent=1, default=str)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all(report["bar"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
