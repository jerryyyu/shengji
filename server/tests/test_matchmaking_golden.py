"""Golden transcripts of the matchmaking queue (``shengji.api.matchmaking``).

Each scenario drives the real ``Matchmaker`` with fake sockets, an injected
clock and a recording room factory, and logs in one ordered list every frame
any socket is sent, every ``start_room`` call (slots with ``group``, mode,
chat, code, Allow joiners, starting level, friend seat), every queue log line
and every ``peek``. The committed fixture holds those logs; a change to the
queue that keeps its behaviour keeps them byte for byte.

Ids and sitting tokens (``secrets.token_hex``) and table codes (random from
``CODE_ALPHABET``) are the only normalized values: each distinct one is named
by its first appearance in the log, so the structure of who shares which id
or code is still held. Times are the injected clock's and stay as they are.

Regenerate only from a tree whose queue behaviour is the reference:
``python -m tests.test_matchmaking_golden --write`` (from ``server/``) records
the tree's ``HEAD`` in the fixture header.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest

from shengji.api import matchmaking as mm

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "matchmaking_golden.json"
FORMAT = 1

_HEX_ID = re.compile(r"^[0-9a-f]{12}$")
_CODE = re.compile(rf"^[{mm.CODE_ALPHABET}]{{{mm.CODE_LEN}}}$")


# ---------------------------------------------------------------- harness
class GoldenConn(mm.Conn):
    def __init__(self, env: "Env", uid: int, name: str, device: str | None, label: str):
        super().__init__(None, uid, name, queue_id=uid, device=device)
        self.env, self.label = env, label
        self.sent: list[dict] = []

    def push(self, payload: dict) -> None:
        if self.closed:
            return
        frame = json.loads(json.dumps(payload))
        self.sent.append(frame)
        self.env.log.append(["frame", self.label, frame])

    def last(self, kind: str) -> dict | None:
        return next((m for m in reversed(self.sent) if m.get("type") == kind), None)


class Clock:
    def __init__(self, t: float = 10_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class _QlogCapture(logging.Handler):
    def __init__(self, env: "Env"):
        super().__init__()
        self.env = env

    def emit(self, record: logging.LogRecord) -> None:
        self.env.log.append(["qlog", json.loads(record.getMessage())])


class OpenTables:
    """The open tables a fake server reports, and its Join of one seat."""

    def __init__(self, env: "Env"):
        self.env = env
        self.tables: dict[str, dict] = {}
        env.mm.open_tables = self
        env.mm.join_table = self.join

    def add(self, code: str, seats: list, mode: str = "ranked") -> None:
        self.tables[code] = {"code": code, "round_end": False, "mode": mode, "seats": [
            {"name": "Bot", "bot": True, "open": True, "queue_id": None, "team": i % 2}
            if s == "bot" else
            {"name": f"P{s}", "bot": False, "open": False, "queue_id": s, "team": i % 2}
            for i, s in enumerate(seats)]}

    def __call__(self) -> list[dict]:
        return [t for t in self.tables.values() if any(s["open"] for s in t["seats"])]

    async def join(self, code: str, seat: int, uid: int, name: str, conn: mm.Conn) -> str | None:
        t = self.tables.get(code)
        if t is None:
            return "closed"
        if not t["seats"][seat]["open"]:
            return "seat_taken"
        t["seats"][seat] = {"name": name, "bot": False, "open": False, "queue_id": uid,
                            "team": seat % 2}
        self.env.log.append(["join_table", code, seat, uid])
        self.env.mm.enter_room(conn)
        return None


class Env:
    def __init__(self) -> None:
        self.clock = Clock()
        self.log: list[list] = []
        self.ratings: dict[int, float] = {}
        self.conns: dict[int, GoldenConn] = {}
        self.all_conns: list[GoldenConn] = []
        self.fail_starts = 0

        async def rating_of(uid: int) -> float | None:
            return self.ratings.get(uid)

        async def start_room(table_id, slots, conns, mode="ranked", chat=(), **room):
            self.log.append(["start_room", {
                "table_id": table_id,
                "slots": [{"user_id": s.user_id, "name": s.name, "rating": s.rating,
                           "group": s.group} for s in slots],
                "conns": sorted(conns), "mode": mode,
                "chat": json.loads(json.dumps(list(chat))),
                "room": json.loads(json.dumps(room, sort_keys=True))}])
            if self.fail_starts:
                self.fail_starts -= 1
                raise RuntimeError("room factory down")
            for c in conns.values():
                self.mm.enter_room(c)
            return "ROOM"

        self.mm = mm.Matchmaker(clock=self.clock, rating_of=rating_of, start_room=start_room,
                                user_active=lambda uid: True, autorun=False)

    # players and messages
    def player(self, uid: int, rating: float = 1000.0, *, device: str | None = None,
               name: str | None = None) -> GoldenConn:
        label = f"{uid}" if uid not in self.conns else f"{uid}#{len(self.log)}"
        conn = GoldenConn(self, uid, name or f"P{uid}", device or f"dev{uid}", label)
        self.ratings[uid] = rating
        self.conns[uid] = conn
        self.all_conns.append(conn)
        self.mm.connect(conn)
        return conn

    async def send(self, uid: int, kind: str, conn: GoldenConn | None = None, **fields: Any) -> None:
        self.log.append(["send", uid, kind, json.loads(json.dumps(fields))])
        await self.mm.handle(conn or self.conns[uid], {"type": kind, **fields}, uid)

    async def join(self, uid: int, rating: float = 1000.0, **fields: Any) -> None:
        if uid not in self.conns:
            self.player(uid, rating)
        await self.send(uid, "queue_join", **fields)

    async def pair(self, leader: int, partner: int, r1: float = 1000.0, r2: float = 1000.0) -> None:
        """A Duo in the lobby and not queued, as one is back from its game
        (``test_matchmaking.lobby_duo``); the leader's ``queue_join``
        queues the two."""
        self.player(leader, r1)
        self.player(partner, r2)
        self.log.append(["duo", leader, partner])
        m = self.mm
        p = mm.Party(id=secrets.token_hex(6), leader=leader, members=[leader, partner],
                     names={u: m._name(u) for u in (leader, partner)}, idle_since=m.clock())
        m.parties[p.id] = p
        for u in p.members:
            m.party_of[u] = p.id
        m._send_party(p)

    def code(self, uid: int) -> str:
        frame = self.conns[uid].last("table")
        assert frame is not None and frame.get("code"), (uid, frame)
        return frame["code"]

    def sit(self, uid: int, seat: int) -> str | None:
        """The sitting token of the person at ``seat`` as ``uid`` sees it."""
        frame = self.conns[uid].last("table")
        return frame["seats"][seat]["sit"] if frame is not None else None

    # time and reads
    async def advance(self, dt: float, *, pump: bool = True) -> None:
        self.clock.t += dt
        self.log.append(["clock", self.clock.t])
        if pump:
            self.mm._last_tick = -float("inf")
            await self.mm.pump()

    async def tick(self) -> None:
        self.log.append(["tick"])
        await self.mm.tick()

    def peek(self, code: str) -> None:
        self.log.append(["peek", code, self.mm.peek(code)])

    def disconnect(self, uid: int) -> None:
        self.log.append(["disconnect", uid])
        self.mm.disconnect(self.conns[uid])


def normalize(log: list) -> list:
    names: dict[str, str] = {}

    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            if _HEX_ID.match(x):
                return names.setdefault(x, f"<id{sum(v.startswith('<id') for v in names.values())}>")
            if _CODE.match(x):
                return names.setdefault(x, f"<code{sum(v.startswith('<code') for v in names.values())}>")
            if x.upper() in names and _CODE.match(x.upper()):
                return names[x.upper()] + ".lower"     # a code typed in lower case
        return x

    return [[event[0], *walk(event[1:])] for event in log]


# --------------------------------------------------------------- scenarios
Scenario = Callable[[Env], Awaitable[None]]
SCENARIOS: dict[str, Scenario] = {}


def scenario(fn: Scenario) -> Scenario:
    SCENARIOS[fn.__name__] = fn
    return fn


@scenario
async def lone_entry_chats_peeks_and_starts_on_its_timer(env: Env) -> None:
    await env.join(1)
    await env.send(1, "table_chat", text="hello alone")
    await env.advance(1.0)
    await env.send(1, "table_chat", text="second line")
    await env.send(1, "queue_status")
    await env.send(1, "table_start")
    await env.send(1, "table_move", seat=1)
    await env.send(1, "table_start_now")
    await env.send(1, "table_here")
    env.peek(env.code(1))
    await env.send(1, "queue_wait_players")
    await env.advance(30.0)
    await env.send(1, "queue_allow_bots")
    await env.advance(mm.BOT_FILL_SECS + 1)


@scenario
async def lone_start_bots_single_and_pair(env: Env) -> None:
    await env.join(1, mode="casual", start_level="6", allow_joiners=False)
    await env.send(1, "table_chat", text="solo")
    await env.send(1, "queue_start_bots")
    await env.pair(2, 3, 1200.0, 1100.0)
    await env.send(2, "queue_join", mode="casual", allow_joiners=False)
    await env.send(3, "table_chat", text="partner says")
    await env.send(2, "table_chat", text="leader says")
    env.peek(env.code(2))
    await env.send(3, "queue_start_bots")
    await env.send(2, "queue_start_bots")


@scenario
async def two_lone_entries_meet_at_the_openers_table(env: Env) -> None:
    await env.join(1, 1100.0, allow_joiners=False)
    await env.send(1, "table_chat", text="one early")
    await env.advance(1.0)
    await env.join(2, 900.0, allow_joiners=False)
    await env.send(2, "table_chat", text="two early")
    await env.advance(1.0)
    await env.send(1, "table_chat", text="one later")
    await env.advance(1.0)
    code1, code2 = env.code(1), env.code(2)
    await env.send(2, "table_allow_joiners", on=True)
    await env.send(1, "table_allow_joiners", on=True)
    env.peek(code1)
    env.peek(code2)
    await env.send(2, "table_chat", text="together")
    await env.send(2, "queue_status")
    await env.advance(40.0)
    await env.send(2, "table_start_now")
    await env.send(1, "table_start_now")


@scenario
async def four_singles_fill_by_seat_order_and_start(env: Env) -> None:
    for uid, r in ((1, 1000.0), (2, 1300.0), (3, 800.0)):
        await env.join(uid, r)
        await env.advance(2.0)
    await env.send(2, "table_start")
    await env.send(2, "table_unready")
    await env.send(3, "table_start")
    await env.join(4, 1000.0)


@scenario
async def a_pair_sits_across_two_singles(env: Env) -> None:
    await env.join(1, 1000.0)
    await env.pair(2, 3, 1500.0, 1400.0)
    await env.send(3, "queue_join")
    await env.send(2, "queue_join")
    await env.send(2, "table_chat", text="pair here")
    await env.join(4, 1000.0)
    await env.join(5, 1000.0)


@scenario
async def pairs_meet_and_a_pair_leaves(env: Env) -> None:
    await env.pair(1, 2)
    await env.send(1, "queue_join")
    await env.send(2, "table_chat", text="from the partner")
    await env.join(7)
    await env.pair(3, 4)
    await env.send(3, "queue_join")
    await env.send(3, "table_chat", text="pair waits alone")
    await env.send(4, "party_leave")
    await env.send(3, "queue_leave")
    await env.send(7, "queue_leave")
    await env.pair(5, 6)
    await env.send(5, "queue_join")
    await env.send(1, "table_start")
    await env.send(2, "table_start")
    await env.send(5, "table_start")
    await env.send(6, "table_start")


@scenario
async def the_rating_window_seats_by_rating(env: Env) -> None:
    for uid, r in ((1, 1000.0), (2, 2000.0), (3, 1050.0), (4, 2080.0), (5, 1500.0), (6, 1010.0)):
        await env.join(uid, r)
        await env.advance(1.0, pump=False)
    await env.tick()
    await env.advance(25.0)
    await env.join(7, 1990.0)
    await env.advance(30.0)
    await env.join(8, 1600.0)
    await env.join(9, 1700.0)


@scenario
async def a_lone_chat_over_the_cap_merges_in_time_order(env: Env) -> None:
    env.mm.chat_limiter = mm.accounts.RateLimiter(10 * mm.CHAT_KEEP, 60.0)
    await env.join(1, mode="casual", allow_joiners=False)
    for i in range(mm.CHAT_KEEP + 3):
        await env.advance(0.25, pump=False)
        await env.send(1, "table_chat", text=f"a{i}")
    await env.join(2, mode="casual", allow_joiners=False)
    for i in range(4):
        await env.advance(0.1, pump=False)
        await env.send(2, "table_chat", text=f"b{i}")
    await env.send(2, "table_allow_joiners", on=True)
    await env.send(1, "table_allow_joiners", on=True)
    await env.join(3, mode="casual", allow_joiners=False)
    await env.send(3, "table_chat", text="third alone")
    await env.send(3, "table_allow_joiners", on=True)
    await env.send(3, "table_chat", text="third at the table")
    await env.send(2, "queue_leave")
    await env.send(1, "queue_leave")
    await env.send(3, "table_chat", text="alone again")
    await env.send(3, "queue_status")
    await env.send(3, "queue_start_bots")


@scenario
async def a_duo_table_holds_its_seat_and_pairs_its_code_joiner(env: Env) -> None:
    await env.join(1, 1200.0, duo=True)
    code = env.code(1)
    env.peek(code)
    await env.send(1, "table_chat", text="waiting for my friend")
    await env.join(3, 1000.0)
    env.peek(code)
    await env.send(1, "table_start")
    await env.join(2, 1100.0, code=code)
    env.peek(code)
    await env.send(2, "table_chat", text="friend arrived")
    await env.send(1, "table_start")
    await env.send(1, "table_unready")
    await env.send(1, "table_start")
    await env.send(2, "table_start")
    await env.send(3, "table_start")
    await env.pair(4, 5)
    await env.send(4, "queue_join")
    await env.join(6, 1000.0)


@scenario
async def a_duo_paired_alone_chats_and_splits(env: Env) -> None:
    await env.join(1, 1200.0, duo=True, mode="casual")
    code = env.code(1)
    await env.join(2, 900.0, code=code)
    await env.send(2, "table_chat", text="partner alone")
    env.peek(code)
    await env.send(2, "table_start")
    await env.send(1, "table_start")
    await env.send(1, "table_unready")
    await env.send(1, "party_leave")
    await env.send(2, "table_chat", text="partner is the opener now")
    await env.send(2, "queue_status")
    env.peek(code)
    await env.join(3, 1000.0, code=code)
    await env.send(3, "table_chat", text="third")
    await env.send(2, "queue_leave")
    await env.send(3, "queue_status")


@scenario
async def a_duo_partner_leaving_holds_the_seat_again(env: Env) -> None:
    await env.join(1, duo=True)
    code = env.code(1)
    await env.join(3)
    await env.join(2, code=code)
    await env.send(1, "table_start")
    await env.send(2, "queue_leave")
    env.peek(code)
    await env.join(5, code=code)
    env.peek(code)
    await env.send(1, "queue_leave")
    env.peek(code)
    await env.send(5, "queue_status")
    await env.join(6, code=code)
    await env.send(3, "table_start")
    await env.send(6, "table_start")
    await env.send(5, "table_start")


@scenario
async def a_duo_starts_with_its_seat_held(env: Env) -> None:
    await env.join(1, duo=True)
    await env.advance(mm.BOT_FILL_SECS + 1)
    await env.join(2, duo=True)
    await env.join(3)
    await env.advance(31.0)
    await env.send(2, "table_start_now")


@scenario
async def code_joins_follow_a_table_for_its_whole_life(env: Env) -> None:
    await env.join(1, allow_joiners=False)
    c1 = env.code(1)
    await env.send(1, "queue_join", code="ZZZZ")
    await env.join(2, code="ZZZZ")
    await env.send(2, "queue_join", code=c1.lower())
    await env.send(2, "queue_status")
    c2 = env.mm._entry(2).code             # its own code still leads to its table
    await env.join(3, allow_joiners=False)
    c3 = env.code(3)
    await env.send(3, "queue_join", code=c3)
    await env.send(3, "queue_leave")
    await env.join(3, code=c2)
    env.peek(c1)
    env.peek(c3)
    await env.send(1, "queue_leave")
    env.peek(c1)
    await env.join(4, code=c1)
    await env.send(4, "table_chat", text="four at the table")
    await env.send(2, "queue_leave")
    env.peek(c2)
    await env.send(3, "queue_leave")
    env.peek(c1)
    await env.send(4, "queue_status")
    await env.send(4, "table_chat", text="alone with the code")
    await env.advance(5.0)
    await env.join(6, code=c1)
    await env.send(6, "table_chat", text="six")
    p = env.player(9, device="dev6")
    await env.send(9, "queue_join", code=c1, conn=p)
    await env.join(7, code=c1)
    await env.pair(10, 11)
    await env.send(10, "queue_join", code=c1)
    await env.send(4, "queue_join", code=c1)
    await env.send(4, "queue_join", code=env.code(4))
    await env.join(8, code=c1)


@scenario
async def settings_carry_and_are_the_openers(env: Env) -> None:
    await env.send(1, "queue_join", conn=env.player(1), mode="ranked", start_level="5")
    await env.send(1, "queue_join", mode="casual", start_level="5", allow_joiners=False)
    await env.join(2, mode="casual", start_level="9")
    c1 = env.code(1)
    await env.send(2, "queue_leave")
    await env.join(2, code=c1, start_level="9", allow_joiners=False)
    await env.send(2, "table_allow_joiners", on=True)
    await env.send(2, "table_start_level", start_level="7")
    await env.send(2, "table_start")
    await env.send(1, "table_start_level", start_level="7")
    await env.send(1, "table_start_level", start_level="nope")
    await env.send(1, "table_allow_joiners", on="yes")
    await env.send(1, "table_allow_joiners", on=True)
    await env.join(3, mode="casual")
    await env.send(3, "table_start")
    await env.send(1, "table_allow_joiners", on=False)
    await env.send(1, "queue_leave")
    await env.send(2, "queue_status")
    await env.send(3, "queue_leave")
    env.peek(c1)
    await env.send(2, "table_start_level", start_level="4")
    await env.send(2, "queue_start_bots")


@scenario
async def still_here_at_a_table_with_no_timer(env: Env) -> None:
    await env.join(1)
    await env.send(1, "queue_wait_players")
    await env.join(2)
    await env.send(2, "queue_wait_players")
    await env.advance(mm.TABLE_IDLE_SECS + 1)
    await env.send(1, "table_here")
    await env.advance(mm.STILL_HERE_SECS + 1)
    await env.advance(mm.TABLE_IDLE_SECS - mm.STILL_HERE_SECS)
    await env.advance(mm.STILL_HERE_SECS + 1)


@scenario
async def idle_at_a_timed_table_leaves(env: Env) -> None:
    await env.join(1)
    await env.join(2)
    await env.send(1, "table_start")
    await env.send(1, "queue_wait_players")
    await env.send(2, "queue_wait_players")
    await env.send(1, "queue_allow_bots")
    await env.advance(mm.TABLE_IDLE_SECS + 1)


@scenario
async def start_now_unlocks_after_the_latest_arrival(env: Env) -> None:
    await env.join(1)
    await env.advance(10.0)
    await env.join(2)
    await env.send(1, "table_start_now")
    await env.advance(20.0)
    await env.join(3)
    await env.advance(29.0)
    await env.send(1, "table_start_now")
    await env.advance(2.0, pump=False)
    await env.send(2, "table_start_now")
    await env.send(1, "table_start_now", panel_seq=1)
    await env.send(1, "table_start_now")


@scenario
async def moves_by_self_and_by_the_opener(env: Env) -> None:
    await env.join(1)
    await env.join(2)
    await env.send(2, "table_move", seat=3)
    await env.send(2, "table_move", seat=0)
    await env.pair(3, 4)
    await env.send(3, "queue_join")
    await env.send(1, "table_move", seat=1, **{"from": 3})
    await env.send(2, "table_start")
    await env.send(2, "table_move", seat=1)
    await env.send(1, "table_move", seat=1, **{"from": 3, "who": env.sit(1, 3)})
    stale = env.sit(1, 1)
    await env.send(1, "table_move", seat=2, **{"from": 1, "who": env.sit(1, 1)})
    await env.send(1, "table_move", seat=3, **{"from": 2, "who": stale})
    await env.join(5)
    await env.send(1, "table_move", seat=3, **{"from": 1, "who": env.sit(1, 1)})
    await env.send(5, "queue_leave")
    await env.tick()


@scenario
async def leave_and_rejoin(env: Env) -> None:
    await env.join(1)
    await env.send(1, "queue_leave")
    await env.send(1, "queue_leave")
    await env.join(1)
    await env.join(2)
    await env.send(2, "queue_leave")
    await env.join(2)
    await env.send(1, "queue_leave")
    await env.join(1, mode="casual")
    await env.send(2, "queue_status")


@scenario
async def away_reconnect_rename_and_a_timer_start_without_the_gone(env: Env) -> None:
    await env.join(1)
    await env.join(2)
    await env.send(2, "table_chat", text="before the drop")
    env.disconnect(2)
    await env.advance(5.0)
    back = env.player(2)
    await env.send(2, "queue_status", conn=back)
    env.conns[1].name = "Renamed"
    env.log.append(["renamed", 1])
    env.mm.renamed(1, "Renamed")
    await env.join(3)
    env.disconnect(3)
    await env.advance(mm.BOT_FILL_SECS)
    await env.join(4)
    env.disconnect(4)
    await env.advance(mm.AWAY_SECS + 1)


@scenario
async def a_failed_start_puts_everyone_back_at_the_front(env: Env) -> None:
    await env.join(1, mode="casual", start_level="8", allow_joiners=False)
    await env.send(1, "table_chat", text="kept alone")
    env.fail_starts = 1
    await env.advance(mm.BOT_FILL_SECS + 1)
    await env.send(1, "queue_wait_players")
    await env.send(1, "queue_status")
    env.peek(env.code(1))
    await env.join(2, mode="casual")
    await env.send(1, "table_allow_joiners", on=True)
    await env.send(2, "table_chat", text="at the table")
    env.fail_starts = 1
    await env.send(1, "table_start")
    await env.send(2, "table_start")
    await env.send(1, "queue_status")
    await env.send(2, "queue_status")
    await env.tick()
    await env.send(2, "table_chat", text="second table")
    await env.send(1, "table_start")
    await env.send(2, "table_start")


@scenario
async def open_table_offers_and_a_join_back_in_line(env: Env) -> None:
    tables = OpenTables(env)
    tables.add("OPEN", [50, "bot", "bot", "bot"])
    tables.add("MORE", [51, "bot", 52, "bot"])
    await env.join(1)
    await env.send(1, "table_chat", text="looking")
    await env.send(1, "open_table_wait")
    await env.send(1, "open_table_show", room="MORE")
    await env.send(1, "open_table_join", room="OPEN", seat=2)
    env.log.append(["return_to_lobby", 1])
    env.mm.return_to_lobby(env.conns[1])
    env.log.append(["join_ended", 1])
    env.mm.join_ended(1, back_in_line=True)
    await env.send(1, "queue_status")
    await env.send(1, "table_chat", text="back in line")
    await env.advance(mm.OFFER_SECS + 1)
    await env.join(2)
    await env.send(2, "table_chat", text="sat")


@scenario
async def a_guest_signs_in_and_one_device_never_sits_twice(env: Env) -> None:
    env.player(-7, device="shared")
    await env.send(-7, "queue_join")
    env.player(8, device="shared")
    await env.send(8, "queue_join", code=env.code(-7))
    await env.send(8, "queue_join")
    await env.join(9, duo=True)
    env.player(-3, device="g3")
    await env.send(-3, "queue_join", code=env.code(9))
    await env.send(-3, "table_chat", text="guest partner")
    env.log.append(["signed_in", -3, 30])
    env.mm.signed_in(-3, 30)
    await env.send(9, "queue_status")
    await env.tick()


# ------------------------------------------------------------------ runner
def run_env(fn: Scenario) -> Env:
    env = Env()
    kept = list(mm.qlog.handlers)
    mm.qlog.handlers = [_QlogCapture(env)]
    try:
        asyncio.run(fn(env))
    finally:
        mm.qlog.handlers = kept
    return env


def run_scenario(fn: Scenario) -> list:
    return normalize(run_env(fn).log)


def transcripts() -> dict[str, list]:
    return {name: run_scenario(fn) for name, fn in SCENARIOS.items()}


def _line(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def dumps(scenarios: dict[str, list]) -> str:
    """One scenario per key, one event per line, so a diff names the event."""
    body = ",\n".join(f" {_line(name)}: [\n" + ",\n".join(f"  {_line(ev)}" for ev in events)
                      + "\n ]" for name, events in sorted(scenarios.items()))
    return "{\n" + body + "\n}\n"


def _committed() -> dict:
    return json.loads(FIXTURE.read_text())


def test_the_fixture_names_its_source_and_every_scenario():
    data = _committed()
    assert data["header"]["format"] == FORMAT
    assert re.fullmatch(r"[0-9a-f]{40}", data["header"]["source_sha"])
    assert sorted(data["scenarios"]) == sorted(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_each_scenario_replays_its_golden_transcript(name):
    want = _committed()["scenarios"][name]
    got = run_scenario(SCENARIOS[name])
    assert dumps({name: got}) == dumps({name: want})


def test_a_scenario_is_deterministic():
    fn = SCENARIOS["two_lone_entries_meet_at_the_openers_table"]
    assert run_scenario(fn) == run_scenario(fn)


def main(argv: list[str]) -> int:
    if argv != ["--write"]:
        print("usage: python -m tests.test_matchmaking_golden --write", file=sys.stderr)
        return 2
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True, cwd=Path(__file__).resolve().parent).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "shengji/api/matchmaking.py"],
                           capture_output=True, text=True, check=True,
                           cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    if dirty:
        print("matchmaking.py differs from HEAD; refusing to record HEAD as the source",
              file=sys.stderr)
        return 1
    header = _line({"format": FORMAT, "source_sha": sha,
                    "normalized": ["token_hex ids", "table codes"]})
    FIXTURE.write_text('{"header": ' + header + ',\n"scenarios": ' + dumps(transcripts()) + "}\n")
    print(f"wrote {FIXTURE} from {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
