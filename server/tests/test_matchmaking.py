"""Matchmaking queue (``shengji.api.matchmaking``).

The matcher is driven with an injected clock and explicit ``tick``/``pump``
calls, never real sleeps. The first part runs the ``Matchmaker`` with fake
sockets and a recording room factory; the second drives the real
``ws_endpoint`` through TestClient with signed-in cookies, so the room the
queue builds is the server's own and its rating snapshot is the existing
ratings path.
"""
from __future__ import annotations

import asyncio
import re

import pytest

from shengji.api import matchmaking as mm
from shengji.api import ratings

from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_ratings import _set, _user
from tests.test_server_ws import _drain, client  # noqa: F401


# ---------------------------------------------------------------- harness
# Two device keys as a client sends them (``?device=``): 22 base64url chars.
DEVICE_A = "AAAAAAAAAAAAAAAAAAAAAA"
DEVICE_B = "BBBBBBBBBBBBBBBBBBBBBB"


class FakeConn(mm.Conn):
    def __init__(self, uid, name):
        super().__init__(None, uid, name)
        self.sent: list[dict] = []

    def push(self, payload):
        if not self.closed:
            self.sent.append(payload)

    def of(self, kind):
        return [m for m in self.sent if m["type"] == kind]

    def last(self, kind):
        found = self.of(kind)
        return found[-1] if found else None

    def clear(self):
        self.sent.clear()


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Env:
    def __init__(self):
        self.clock = Clock()
        self.ratings: dict[int, float] = {}
        self.started: list[tuple[str | None, list[mm.Slot]]] = []
        self.conns: dict[int, FakeConn] = {}
        self.modes: list[str] = []
        self.chats: list[list[dict]] = []

        async def rating_of(uid):
            return self.ratings.get(uid)

        self.rooms: list[dict] = []

        async def start_room(match_id, slots, conns, mode="ranked", chat=(), **room):
            self.started.append((match_id, slots))
            self.modes.append(mode)
            self.chats.append(list(chat))
            self.rooms.append(room)
            for c in conns.values():
                self.mm.enter_room(c)
            return "ROOM"

        self.mm = mm.Matchmaker(clock=self.clock, rating_of=rating_of,
                                start_room=start_room, user_active=lambda uid: True,
                                autorun=False)

    def player(self, uid, rating=1000.0, name=None):
        conn = FakeConn(uid, name or f"P{uid}")
        self.ratings[uid] = rating
        self.conns[uid] = conn
        self.mm.connect(conn)
        return conn

    async def send(self, uid, kind, conn=None, **fields):
        await self.mm.handle(conn or self.conns[uid], {"type": kind, **fields}, uid)

    async def join(self, uid, rating=1000.0, **fields):
        if uid not in self.conns:
            self.player(uid, rating)
        await self.send(uid, "queue_join", **fields)
        started = any(uid in humans_of(slots) for _, slots in self.started)
        assert started or self.mm._entry(uid) is not None, self.conns[uid].sent

    async def pair(self, leader, partner, r1=1000.0, r2=1000.0):
        self.player(leader, r1)
        self.player(partner, r2)
        await self.send(leader, "party_create")
        code = self.conns[leader].last("party")["code"]
        await self.send(partner, "party_join", code=code)
        return self.mm._party(leader)

def run(coro):
    return asyncio.run(coro)


def humans_of(slots):
    return [s.user_id for s in slots if not s.is_bot]


# ------------------------------------------------------- the constants
def test_window_steps_timers_and_table_rules_are_the_named_constants():
    assert mm.BOT_FILL_SECS == 60.0
    assert mm.WINDOW_STEPS == ((20.0, 100.0), (40.0, 250.0))
    assert mm.window_for(0) == 100 and mm.window_for(19.9) == 100
    assert mm.window_for(20) == 250 and mm.window_for(39.9) == 250
    assert mm.window_for(40) == float("inf")
    assert mm.WINDOW_FROM == 5
    assert mm.AWAY_SECS == 10.0 and mm.TABLE_AWAY_SECS == 60.0 and mm.WAIT_AWAY_SECS == 60.0
    assert mm.TABLE_IDLE_SECS == 120.0 and mm.STILL_HERE_SECS == 30.0
    assert mm.SEAT_ORDER == (0, 2, 1, 3) and mm.PAIR_SEATS == ((0, 2), (1, 3))
    assert mm.OFFER_SECS == 20.0


# ------------------------------------------------------- seating a table
def test_alone_in_the_queue_there_is_no_table():
    async def go():
        env = Env()
        await env.join(1)
        state = env.conns[1].last("queue_state")
        assert state["queued"] and state["table"] is None
        assert env.mm.tables == {}
    run(go())


def test_two_singles_form_one_table_on_the_second_ones_arrival_as_partners():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 2, None]
        for uid, seat in ((1, 0), (2, 2)):
            table = env.conns[uid].last("queue_state")["table"]
            assert table["id"] == t.id and table["you"] == seat
            assert [s and s["name"] for s in table["seats"]] == ["P1", None, "P2", None]
            assert table["seats"][seat]["you"] is True
            assert table["ready"] == 0 and table["of"] == 2
        assert env.started == []
    run(go())


def test_a_third_sits_across_and_a_fourth_takes_the_last_seat_and_starts_the_table_at_once():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, 2, None]
        await env.join(4)
        (table_id, slots), = env.started
        assert table_id == t.id
        assert [s.user_id for s in slots] == [1, 3, 2, 4]
        assert env.mm.tables == {} and env.mm.entries == {}
        for c in env.conns.values():          # no ready check on the way in
            assert c.of("match") == [] and c.of("match_ready") == []
    run(go())


def test_a_pair_sits_as_partners_on_the_free_team():
    async def go():
        env = Env()
        await env.join(1)
        await env.pair(2, 3)
        await env.send(2, "queue_join")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, 3]
        table = env.conns[3].last("queue_state")["table"]
        assert table["you"] == 3 and table["seats"][1]["pair"] and table["seats"][1]["leader"]
        assert not table["seats"][3]["leader"]
    run(go())


def test_a_pair_first_takes_seats_zero_and_two_and_a_single_sits_opposite():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.join(3)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, 2, None]
    run(go())


def test_a_duo_sits_across_from_a_table_of_two_singles_and_starts_it():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        (table_id, slots), = env.started
        assert table_id is not None and [s.user_id for s in slots] == [1, 3, 2, 4]
        assert env.mm.tables == {} and env.mm.entries == {}
    run(go())


def test_a_pair_never_splits_across_teams_to_fit_a_table():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        await env.pair(4, 5)
        await env.send(4, "queue_join")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, 2, None]
        assert env.mm._entry(4).table_id is None
        assert env.conns[5].last("queue_state")["table"] is None
    run(go())


def test_two_pairs_fill_a_table_and_start_it():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, 3, 2, 4]
    run(go())


def test_under_five_queued_anyone_sits_with_anyone():
    async def go():
        env = Env()
        await env.join(1, 1000)
        await env.join(2, 1700)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 2, None]
    run(go())


def test_from_five_queued_the_rating_window_decides_who_shares_a_table():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid, 1000)
        await env.pair(4, 5, 1000, 1000)
        await env.send(4, "queue_join")      # no pair seats left: waits alone
        await env.join(6, 1600)               # five queued: 600 is outside ±100
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, 2, None]
        assert env.mm._entry(6).table_id is None
        await env.join(7, 1050)               # inside the window: the last seat
        (table_id, slots), = env.started
        assert table_id == t.id and [s.user_id for s in slots] == [1, 3, 2, 7]
    run(go())


def test_a_second_table_forms_when_the_first_has_no_pair_seats():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid, 1000)
        await env.pair(4, 5, 1000, 1000)
        await env.send(4, "queue_join")       # alone: no pair seats at the table
        await env.pair(6, 7, 1000, 1000)
        await env.send(6, "queue_join")       # sits with the other pair
        tables = list(env.mm.tables.values())
        assert env.started and [s.user_id for s in env.started[0][1]] == [4, 6, 5, 7]
        assert len(tables) == 1 and tables[0].seats == [1, 3, 2, None]
    run(go())


# ------------------------------------------------------------- starting
def test_every_start_tapped_starts_the_table_with_bots_and_a_newcomer_keeps_the_ticks():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        await env.send(1, "table_start")
        assert env.started == []
        mine = env.conns[1].last("queue_state")["table"]
        assert mine["you_ready"] and mine["ready"] == 1 and mine["waiting_for"] == ["P2"]
        assert mine["seats"][0]["ready"] and not mine["seats"][2]["ready"]
        await env.join(3)                     # a newcomer does not clear the tick
        mine = env.conns[1].last("queue_state")["table"]
        assert mine["ready"] == 1 and mine["of"] == 3 and mine["waiting_for"] == ["P2", "P3"]
        await env.send(2, "table_start")
        await env.send(2, "table_start")      # twice is once
        assert env.started == []
        await env.send(3, "table_start")
        (table_id, slots), = env.started
        assert [s.user_id for s in slots] == [1, 3, 2, None]
    run(go())


def test_the_table_timer_is_the_earliest_switch_off_players_and_switch_on_players_ride_it():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_wait_players")
        env.clock.advance(10)
        await env.join(2)
        bots_at_2 = env.mm._entry(2).bots_at
        env.clock.advance(5)
        await env.join(3)
        timer = env.conns[1].last("queue_state")["table"]["timer"]
        assert timer == {"at": bots_at_2, "name": "P2", "you": False}
        assert env.conns[2].last("queue_state")["table"]["timer"]["you"] is True
        await env.send(2, "queue_leave")      # the owner leaves: the next switch-off one owns it
        timer = env.conns[1].last("queue_state")["table"]["timer"]
        assert timer["name"] == "P3" and timer["at"] == env.mm._entry(3).bots_at
        env.clock.t = env.mm._entry(3).bots_at - 0.1
        await env.mm.tick()
        assert env.started == []
        env.clock.advance(0.1)
        await env.mm.tick()
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, 3, None, None]
    run(go())


def test_with_every_switch_on_there_is_no_timer_and_only_every_start_starts_it():
    async def go():
        env = Env()
        for uid in (1, 2):
            await env.join(uid)
            await env.send(uid, "queue_wait_players")
        assert env.conns[1].last("queue_state")["table"]["timer"] is None
        env.clock.advance(100)
        await env.mm.pump()
        assert env.started == []
        await env.send(1, "table_start")
        await env.send(2, "table_start")
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, None, 2, None]
    run(go())


def test_alone_the_bot_timer_starts_a_bot_game_without_a_ready_check():
    async def go():
        env = Env()
        await env.join(1)
        env.clock.advance(mm.BOT_FILL_SECS - mm.TICK_INTERVAL)
        await env.mm.pump()
        assert env.started == []
        env.clock.advance(mm.TICK_INTERVAL)
        await env.mm.pump()
        (table_id, slots), = env.started
        assert table_id is None and [s.user_id for s in slots] == [1, None, None, None]
        assert env.conns[1].of("match") == []
    run(go())


def test_alone_with_the_switch_on_never_starts_with_bots():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_wait_players")
        env.clock.advance(1000)
        await env.mm.tick()
        assert env.started == [] and env.mm._entry(1) is not None
    run(go())


def test_the_ready_check_is_gone():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "match_accept", match_id="x")
        assert env.conns[1].last("error")["code"] == "no_match"
        await env.send(1, "table_start")
        assert env.conns[1].last("error")["code"] == "not_seated"
    run(go())


def test_an_older_clients_play_bots_at_a_table_is_its_start():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        await env.send(1, "queue_start_bots")
        assert env.started == [] and env.conns[1].last("queue_state")["table"]["you_ready"]
        await env.send(2, "queue_start_bots")
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, None, 2, None]
    run(go())


def test_the_pair_leader_starts_for_the_pair_and_the_partner_cannot():
    async def go():
        env = Env()
        await env.join(1)
        await env.pair(2, 3)
        await env.send(2, "queue_join")
        for kind in ("table_start", "queue_leave", "queue_wait_players"):
            await env.send(3, kind)
            assert env.conns[3].last("error")["code"] == "not_leader"
        await env.send(2, "table_start")
        table = env.conns[1].last("queue_state")["table"]
        assert table["ready"] == 2 and table["of"] == 3 and table["waiting_for"] == []
        await env.send(1, "table_start")
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, 2, None, 3]
    run(go())


# --------------------------------------------------------- leaving a table
def test_leaving_frees_the_seat_and_nobody_moves():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        await env.send(2, "queue_leave")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, None, None]
        assert env.conns[2].last("queue_state")["queued"] is False
        assert env.conns[1].last("queue_state")["table"]["seats"][2] is None
        await env.join(4)
        assert t.seats == [1, 3, 4, None]
    run(go())


def test_the_last_one_left_at_a_table_is_alone_again_with_its_own_timer():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        await env.send(1, "table_start")
        await env.send(2, "queue_leave")
        assert env.mm.tables == {}
        state = env.conns[1].last("queue_state")
        assert state["queued"] and state["table"] is None
        await env.join(3)                     # a fresh table: the old tick is gone
        assert env.conns[1].last("queue_state")["table"]["you_ready"] is False
    run(go())


def test_a_seated_socket_that_closes_holds_its_seat_sixty_seconds_reconnecting():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_wait_players")
        await env.join(2)
        await env.send(2, "table_start")
        env.mm.disconnect(env.conns[2])
        seat = env.conns[1].last("queue_state")["table"]["seats"][2]
        assert seat["reconnecting"] is True and seat["ready"] is True
        env.clock.advance(mm.TABLE_AWAY_SECS - 1)
        await env.mm.pump()
        assert env.mm._entry(2) is not None
        back = FakeConn(2, "P2")
        env.mm.connect(back)                 # the app comes back: resync, readiness kept
        table = back.last("queue_state")["table"]
        assert table["you"] == 2 and table["you_ready"] is True
        assert env.conns[1].last("queue_state")["table"]["seats"][2]["reconnecting"] is False
        env.mm.disconnect(back)
        env.clock.advance(mm.TABLE_AWAY_SECS + 1)
        await env.mm.pump()
        assert env.mm._entry(2) is None and env.mm.tables == {}
        assert env.conns[1].last("queue_state")["table"] is None
    run(go())


def test_four_people_wait_for_a_reconnecting_one_but_the_timer_does_not():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_wait_players")
        for uid in (2, 3):
            await env.join(uid)
        env.mm.disconnect(env.conns[2])
        await env.join(4)
        assert env.started == []              # four, but one is reconnecting
        env.clock.t = env.mm._entry(3).bots_at
        await env.mm.tick()
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, 3, None, 4]
        assert env.mm._entry(2) is None
    run(go())


def test_at_a_table_with_no_timer_two_minutes_idle_asks_still_here_and_half_a_minute_more_removes_you():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
            await env.send(uid, "queue_wait_players")
        await env.send(1, "table_start")      # ready: never idle
        env.clock.advance(100)
        await env.send(3, "queue_allow_bots") # a tap resets the clock
        await env.send(3, "queue_wait_players")
        env.clock.advance(mm.TABLE_IDLE_SECS - 100)
        await env.mm.pump()
        assert env.conns[2].last("queue_removed") is None
        asked = env.conns[2].last("queue_state")
        assert asked["still_here_until"] == env.clock.t + mm.STILL_HERE_SECS
        assert env.conns[3].last("queue_state")["still_here_until"] is None
        env.clock.advance(mm.STILL_HERE_SECS)
        await env.mm.pump()
        removed = env.conns[2].last("queue_removed")
        assert removed["reason"] == "idle" and removed["cooldown_until"] is None
        assert env.mm._entry(1) is not None and env.mm._entry(3) is not None
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 3, None, None]
        await env.join(2)                     # straight back: no cooldown
        assert env.mm._entry(2) is not None
    run(go())


def test_the_room_start_hook_gets_the_table_id_only_for_a_table():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_start_bots")
        await env.join(2)
        await env.join(3)
        await env.send(2, "table_start")
        await env.send(3, "table_start")
        assert [tid is None for tid, _ in env.started] == [True, False]
    run(go())


# ----------------------------------------------------- queue_start_bots
def test_start_bots_solo_seats_one_human_and_three_bots():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_start_bots")
        (match_id, slots), = env.started
        assert match_id is None and humans_of(slots) == [1]
        assert [s.is_bot for s in slots] == [False, True, True, True]
        assert env.mm.entries == {}
    run(go())


def test_start_bots_as_a_pair_puts_the_bots_opposite_and_is_the_leaders_call():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.send(2, "queue_start_bots")
        assert env.conns[2].last("error")["code"] == "not_leader"
        await env.send(1, "queue_start_bots")
        (_, slots), = env.started
        assert [s.user_id for s in slots] == [1, None, 2, None]
    run(go())


def test_start_bots_failure_reaches_both_members_of_a_pair():
    async def go():
        env = Env()

        async def boom(match_id, slots, conns, **kw):
            raise RuntimeError("no room")
        env.mm.start_room = boom
        await env.pair(1, 2)
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "not_queued"
        await env.send(1, "queue_join")
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "start_failed"
        assert env.conns[2].last("error")["code"] == "start_failed"
    run(go())


def test_start_bots_needs_a_queue_entry():
    async def go():
        env = Env()
        env.player(1)
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "not_queued"
    run(go())


# --------------------------------------------------------- away from app
def test_alone_away_over_ten_seconds_drops_without_a_cooldown():
    async def go():
        env = Env()
        await env.join(1)
        env.mm.disconnect(env.conns[1])
        env.clock.advance(mm.AWAY_SECS - 1)
        await env.mm.pump()
        assert env.mm._entry(1) is not None
        env.clock.advance(2)
        await env.mm.pump()
        assert env.mm._entry(1) is None
        again = env.player(1)
        await env.send(1, "queue_join", conn=again)
        assert env.mm._entry(1) is not None
    run(go())


def test_a_disconnected_entry_is_not_seated_while_it_may_come_back():
    async def go():
        env = Env()
        await env.join(1)
        env.mm.disconnect(env.conns[1])
        await env.join(2)
        assert env.mm.tables == {}
    run(go())


def test_a_failed_table_start_puts_everyone_back_at_the_front():
    async def go():
        env = Env()

        async def boom(match_id, slots, conns, **kw):
            raise RuntimeError("no room")
        env.mm.start_room = boom
        for uid in (1, 2, 3, 4):
            await env.join(uid)
        assert env.mm.tables == {}
        for uid in (1, 2, 3, 4):
            e = env.mm._entry(uid)
            assert e is not None and e.front and e.table_id is None
            assert env.conns[uid].last("match_cancelled")["reason"] == "server_error"
    run(go())


# ------------------------------------------------------------------ pairs
def test_a_pair_is_one_entry_at_its_average_rating():
    async def go():
        env = Env()
        await env.pair(1, 2, 1000, 1100)
        await env.send(1, "queue_join")
        e = env.mm._entry(1)
        assert e is env.mm._entry(2) and e.rating == 1050 and e.size == 2
        assert env.mm.count() == 2
        assert env.conns[2].last("queue_state")["leader"] is False
    run(go())


def test_only_the_leader_queues_or_cancels():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(2, "queue_join")
        assert env.conns[2].last("error")["code"] == "not_leader"
        await env.send(1, "queue_join")
        await env.send(2, "queue_leave")
        assert env.conns[2].last("error")["code"] == "not_leader"
        assert env.mm._entry(1) is not None
        await env.send(2, "party_leave")        # either member may leave
        assert env.mm._entry(1) is None and env.mm._party(1) is None
        closed = env.conns[1].last("party_closed")
        assert closed["by"] == "P2" and closed["you"] is False
    run(go())


def test_a_pair_leaving_its_party_frees_both_seats():
    async def go():
        env = Env()
        await env.join(1)
        await env.pair(2, 3)
        await env.send(2, "queue_join")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, 3]
        await env.send(3, "party_leave")
        assert t.seats == [1, None, None, None] and env.mm.tables == {}
        assert env.mm._entry(2) is None and env.mm._entry(3) is None
        assert env.conns[1].last("queue_state")["table"] is None
    run(go())


def test_parties_expire_after_five_minutes_unless_queued():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        await env.send(3, "queue_wait_players")
        env.clock.advance(mm.PARTY_TTL + 1)
        env.mm._last_tick = env.clock()          # keep the matcher out of it
        await env.mm.pump()
        assert env.mm._party(1) is None
        assert env.conns[2].last("party_closed")["reason"] == "expired"
        assert env.mm._party(3) is not None
    run(go())


def test_party_join_rules():
    async def go():
        env = Env()
        await env.pair(1, 2)
        code = env.mm._party(1).code
        env.player(3)
        await env.send(3, "party_join", code=code)
        assert env.conns[3].last("error")["code"] == "party_full"
        await env.send(3, "party_join", code="0000")
        assert env.conns[3].last("error")["code"] == "party_not_found"
        await env.send(3, "party_invite")             # the code is the invite
        assert env.conns[3].last("party")["code"] != code
        env.player(5)
        await env.send(5, "queue_join", party_id=env.mm._party(3).id)
        assert env.conns[5].last("error")["code"] == "bad_party"
    run(go())


def test_a_cooldown_is_pushed_to_the_lobby_and_counted_down_by_queue_state():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        other_tab = FakeConn(1, "P1")
        env.mm.connect(other_tab)
        await env.send(1, "open_table_join", room="OPEN", seat=2)
        env.mm.join_seated(1)
        env.mm.left_open_table(1, "OPEN")
        until = env.clock.t + mm.JOIN_COOLDOWN_SECS
        # a lobby tab hears at once; the leaving socket as it gets back
        assert other_tab.last("queue_state") == {"type": "queue_state", "queued": False,
                                                 "count": 0, "cooldown_until": until}
        env.conns[1].clear()
        env.mm.return_to_lobby(env.conns[1])
        assert env.conns[1].last("queue_state")["cooldown_until"] == until
        fresh = FakeConn(1, "P1")
        env.mm.connect(fresh)
        assert fresh.last("queue_state")["cooldown_until"] == until
        env.clock.advance(48)
        await env.send(1, "queue_status")
        assert env.conns[1].last("queue_state")["cooldown_until"] == until
        await env.send(1, "queue_join")
        err = env.conns[1].last("error")
        assert err["code"] == "cooldown" and err["message"].endswith("Play again in 0:12.")
        env.clock.advance(mm.JOIN_COOLDOWN_SECS)
        await env.send(1, "queue_status")
        assert "cooldown_until" not in env.conns[1].last("queue_state")
    run(go())


def test_leave_queue_on_another_device_tells_the_holder_it_was_stopped_there():
    async def go():
        env = Env()
        phone = FakeConn(1, "P1")
        phone.device = DEVICE_A
        env.conns[1] = phone
        env.mm.connect(phone)
        await env.send(1, "queue_join")
        desk = FakeConn(1, "P1")
        desk.device = DEVICE_B
        env.mm.connect(desk)
        await env.mm.handle(desk, {"type": "queue_leave"}, 1)
        told = [m for m in phone.of("queue_state") if m.get("replaced")]
        assert told and told[-1]["by"] == "device" and told[-1]["stopped"] is True
        assert env.mm._entry(1) is None
        # a Play from another window of the same device moves the search
        win = FakeConn(1, "P1")
        win.device = DEVICE_B
        env.mm.connect(win)
        await env.mm.handle(desk, {"type": "queue_join"}, 1)
        await env.mm.handle(win, {"type": "queue_join"}, 1)
        told = [m for m in desk.of("queue_state") if m.get("replaced")]
        assert told[-1]["by"] == "window" and "stopped" not in told[-1]
    run(go())


def test_a_guest_who_enters_its_own_duo_code_is_told_a_duo_needs_two_devices():
    async def go():
        env = Env()
        env.player(-7, name="G")
        await env.send(-7, "party_create")
        code = env.conns[-7].last("party")["code"]
        other_tab = FakeConn(-7, "G")
        env.mm.connect(other_tab)
        await env.send(-7, "party_join", conn=other_tab, code=code)
        err = other_tab.last("error")
        assert err["code"] == "same_device" and err["message"] == "A Duo needs two devices."
        assert len(env.mm._party(-7).members) == 1
    run(go())


def test_duo_messages_say_duo_never_party_or_pair():
    async def go():
        env = Env()
        await env.pair(1, 2)
        code = env.mm._party(1).code
        env.player(3)
        await env.send(3, "party_join", code=code)
        assert env.conns[3].last("error")["message"] == "That Duo is full."
        await env.send(3, "party_join", code="ZZZZ")
        assert env.conns[3].last("error")["message"] == "No Duo has that code."
        await env.send(3, "party_leave")
        assert env.conns[3].last("error")["message"] == "You are not in a Duo."
        await env.send(2, "queue_join")
        assert "Duo" in env.conns[2].last("error")["message"]
        src = open(mm.__file__).read()
        said = re.findall(r'QueueError\([^,]+,\s*f?"([^"]*)"', src)
        assert said and not [m for m in said if re.search(r"\b(party|pair)\b", m, re.I)]
    run(go())


# --------------------------------------------------------------- the rest
def test_guests_are_refused():
    async def go():
        env = Env()
        guest = FakeConn(None, "")
        env.mm.connect(guest)
        for kind in ("queue_join", "party_create", "queue_start_bots", "queue_wait_players",
                     "table_start"):
            await env.mm.handle(guest, {"type": kind}, None)
        assert [m["code"] for m in guest.of("error")] == ["signed_in_only"] * 5
        assert env.mm.entries == {}
    run(go())


def test_one_entry_per_account_and_a_second_socket_takes_it_over():
    async def go():
        env = Env()
        await env.join(1)
        second = FakeConn(1, "P1")
        env.mm.connect(second)
        await env.mm.handle(second, {"type": "queue_join"}, 1)
        assert len(env.mm.entries) == 1 and env.mm.count() == 1
        states = env.conns[1].of("queue_state")
        assert any(m.get("replaced") is True and m["queued"] is False for m in states)
        # the first socket then shows the search as held elsewhere
        assert states[-1]["queued"] is True and states[-1]["elsewhere"] is True
        assert env.mm.conns[1] is second and second.last("queue_state")["queued"]
        assert "elsewhere" not in second.last("queue_state")
    run(go())


def test_queue_count_is_debounced_to_one_broadcast_per_second():
    async def go():
        env = Env()
        watcher = FakeConn(None, "")
        env.mm.connect(watcher)
        for uid in (1, 2, 3):
            await env.join(uid)
        assert [m["count"] for m in watcher.of("queue_count")] == [1]
        env.clock.advance(0.5)
        await env.mm.pump()
        assert len(watcher.of("queue_count")) == 1
        env.clock.advance(0.5)
        await env.mm.pump()
        assert [m["count"] for m in watcher.of("queue_count")] == [1, 3]
        late = FakeConn(None, "")
        env.mm.connect(late)
        assert late.last("queue_count")["count"] == 3
    run(go())


def test_queue_join_and_party_messages_are_rate_limited():
    async def go():
        env = Env()
        env.player(1)
        for _ in range(mm.JOIN_LIMIT[0]):
            await env.send(1, "queue_join")
            await env.send(1, "queue_leave")
        await env.send(1, "queue_join")
        assert env.conns[1].last("error")["code"] == "rate_limited"
        for _ in range(mm.PARTY_LIMIT[0]):
            await env.send(1, "party_create")
        await env.send(1, "party_leave")
        assert env.conns[1].last("error")["code"] == "rate_limited"
    run(go())


def test_a_socket_in_a_room_cannot_queue():
    async def go():
        env = Env()
        conn = env.player(1)
        env.mm.enter_room(conn)
        await env.send(1, "queue_join")
        assert conn.last("error")["code"] == "in_room"
    run(go())


def test_concurrent_starts_ticks_and_leaves_seat_everyone_once():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        for uid in (4, 5):
            await env.join(uid)              # 4 fills the first table; 5 waits
        await env.join(6)
        assert len(env.started) == 1

        async def later(coro):
            await asyncio.sleep(0)
            await coro

        await asyncio.gather(*[later(env.send(u, k)) for u in (5, 6)
                               for k in ("table_start", "queue_start_bots", "table_start")],
                             later(env.mm.tick()), later(env.mm.pump()))
        seated = [u for _, slots in env.started for u in humans_of(slots)]
        assert sorted(seated) == list(range(1, 7))
        assert len(env.started) == 2 and env.mm.entries == {} and env.mm.tables == {}
    run(go())


# ------------------------------------------------ a room that fails to start
class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)


async def _four(env):
    """Four players with sockets join; the fourth fills the table and starts it."""
    for uid in (1, 2, 3, 4):
        env.player(uid).ws = _FakeWS()
    for uid in (1, 2, 3, 4):
        await env.join(uid)
        env.clock.advance(1)


@pytest.mark.parametrize("fail_at", ["first_attach", "second_attach", "first_broadcast",
                                     "start_game", "last_broadcast"])
def test_a_failed_room_start_unwinds_the_room_before_requeueing(monkeypatch, fail_at):
    from shengji.api import server as srv

    async def go():
        env = Env()
        built = []
        real_room = srv.Room

        def room(**kw):
            r = real_room(bot=object(), **kw)
            built.append(r)
            return r

        calls = {"attach": 0, "broadcast": 0}
        real_attach, real_broadcast, real_action = srv._attach, srv.broadcast, srv.handle_action

        def attach(room_, seat, ws):
            calls["attach"] += 1
            if (fail_at, calls["attach"]) in (("first_attach", 1), ("second_attach", 2)):
                raise RuntimeError("injected attach failure")
            return real_attach(room_, seat, ws)

        async def broadcast(room_):
            calls["broadcast"] += 1
            if (fail_at, calls["broadcast"]) in (("first_broadcast", 1), ("last_broadcast", 2)):
                raise RuntimeError("injected broadcast failure")
            await real_broadcast(room_)

        async def action(room_, seat, msg):
            if fail_at == "start_game":
                raise RuntimeError("injected start failure")
            await real_action(room_, seat, msg)

        monkeypatch.setattr(srv, "Room", room)
        monkeypatch.setattr(srv, "rooms", {})
        monkeypatch.setattr(srv, "MATCHMAKER", env.mm)
        monkeypatch.setattr(srv, "_attach", attach)
        monkeypatch.setattr(srv, "broadcast", broadcast)
        monkeypatch.setattr(srv, "handle_action", action)
        env.mm.start_room = srv.start_matched_room
        await _four(env)
        await asyncio.sleep(0)
        (r,) = built
        assert srv.rooms == {} and r.aborted
        for task in (r.bot_task, r.deal_task, r.watchdog_task, r.cleanup_task):
            assert task is None or task.cancelled() or task.done()
        for seat in r.seats:
            assert seat.ws is None and not seat.connected and seat.writer is None
        for uid, c in env.conns.items():
            assert c.adopted is None and not c.in_room and c in env.mm.lobby
            e = env.mm._entry(uid)
            assert e is not None and e.front and e.table_id is None
            assert c.last("match_cancelled")["reason"] == "server_error"
        assert env.mm.tables == {}
        env.mm.seat_waiting()
        (again,) = env.mm.tables.values()
        assert again.seats == [1, 3, 2, 4]
    run(go())


def test_a_failed_final_broadcast_leaves_no_saved_game_and_no_started_count(
        accounts_on, tmp_path, monkeypatch):  # noqa: F811
    from shengji.api import saved_games
    from shengji.api import server as srv

    store = accounts_on.STORE
    for uid in range(1, 5):
        assert store.upsert_user({"sub": f"user-{uid}", "name": f"P{uid}"})["id"] == uid
    env = Env()
    real_room, real_broadcast = srv.Room, srv.broadcast
    built, calls = [], [0]

    def room(**kw):
        r = real_room(bot=object(), **kw)
        built.append(r)
        return r

    async def broadcast(room_):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("injected last broadcast failure")
        await real_broadcast(room_)

    monkeypatch.setattr(srv, "Room", room)
    monkeypatch.setattr(srv, "rooms", {})
    monkeypatch.setattr(srv, "MATCHMAKER", env.mm)
    monkeypatch.setattr(srv, "broadcast", broadcast)
    monkeypatch.setattr(srv, "LOG_DIR", tmp_path / "logs")
    env.mm.start_room = srv.start_matched_room
    before = srv.ACTIVITY.games_started

    async def go():
        await _four(env)
        await asyncio.sleep(0)
    run(go())
    saved_games.flush()
    (r,) = built
    assert r.aborted and srv.rooms == {}
    assert r.game is not None, "the failure came after start_game, as intended"
    assert srv.ACTIVITY.games_started == before
    for uid in range(1, 5):
        assert saved_games._list(uid, None, 50)["games"] == []




# ----------------------------------------------------- over the websocket
@pytest.fixture()
def wsenv(accounts_on, client):  # noqa: F811
    from shengji.api import server as srv

    clock = Clock()
    mmk = srv.MATCHMAKER
    mmk.reset()
    srv.GUEST_IDS.clear()
    saved = (mmk.clock, mmk.autorun)
    mmk.clock, mmk.autorun = clock, False
    try:
        yield srv, accounts_on.STORE, client, clock
    finally:
        mmk.reset()
        mmk.clock, mmk.autorun = saved


def _drain_all(ws, wants, tries=40):
    """The first message of each wanted type, in whatever order the room's
    writer and the queue's writer deliver them."""
    got = {}
    for _ in range(tries):
        if set(got) >= wants:
            return got
        m = ws.receive_json()
        if m.get("type") in wants:
            got.setdefault(m["type"], m)
    raise AssertionError(f"missing {wants - set(got)}")


def _pump(client, srv):
    client.portal.call(srv.MATCHMAKER.pump)


def _until(ws, kind, tries=80):
    """Messages up to and including the first of ``kind``."""
    seen = []
    for _ in range(tries):
        m = ws.receive_json()
        seen.append(m)
        if m.get("type") == kind:
            return seen
    raise AssertionError(f"no {kind} in {[m.get('type') for m in seen]}")


@pytest.mark.parametrize("heartbeat", [False, True])
def test_ws_four_players_fill_a_waiting_table_and_land_in_a_started_rated_room(wsenv, heartbeat):
    srv, store, client, clock = wsenv
    users = [_user(store, f"s{i}", f"Player{i}") for i in range(4)]
    for (uid, _), r in zip(users, (1400, 1200, 1200, 1000)):
        _set(store, uid, r)
    with client.websocket_connect("/ws?heartbeat=1" if heartbeat else "/ws", headers=users[0][1]) as a, \
            client.websocket_connect("/ws", headers=users[1][1]) as b, \
            client.websocket_connect("/ws", headers=users[2][1]) as c, \
            client.websocket_connect("/ws", headers=users[3][1]) as d:
        if heartbeat:
            assert _drain(a, "heartbeat_ready")["type"] == "heartbeat_ready"
            a.send_json({"type": "ping", "nonce": 1})
            assert _drain(a, "pong")["nonce"] == 1
        socks = [a, b, c, d]
        a.send_json({"type": "queue_join"})
        assert _drain(a, "queue_state")["table"] is None
        b.send_json({"type": "queue_join"})
        table = _drain(b, "queue_state")["table"]
        assert table["you"] == 2 and [s["name"] for s in table["seats"][::2]] == ["Player0", "Player1"]
        c.send_json({"type": "queue_join"})
        assert _drain(c, "queue_state")["table"]["you"] == 1
        d.send_json({"type": "queue_join"})
        for ws in socks:
            seen = _until(ws, "match_started")
            assert not {"match", "match_ready"} & {m["type"] for m in seen}
            started = seen[-1]
        code = started["room"]
        state = _drain(d, "state", tries=80)
        assert state["matched"] is True and state["room"] == code
        room = srv.rooms[code]
        by_seat = [s.user_id for s in room.seats]
        uid = [u for u, _ in users]
        assert by_seat == [uid[0], uid[2], uid[1], uid[3]]   # the second arrival is the first's partner
        assert room.waiting_table == started["match_id"] and room.table_humans == 4
        assert room.game is not None and room.matched
        assert room.ratings is not None
        assert room.ratings.present == {0: uid[0], 1: uid[2], 2: uid[1], 3: uid[3]}
        # The adopted socket plays on as a seated socket: chat reaches the room.
        if heartbeat:
            a.send_json({"type": "ping", "nonce": 2})
            assert _drain(a, "pong", tries=400)["nonce"] == 2
            assert [s.user_id for s in room.seats] == by_seat
        a.send_json({"type": "chat", "text": "gl"})
        assert _drain(b, "chat", tries=400)["text"] == "gl"
        assert srv.MATCHMAKER.entries == {} and srv.MATCHMAKER.tables == {}


def test_ws_a_guest_with_no_device_key_cannot_queue(wsenv):
    srv, store, client, clock = wsenv
    with client.websocket_connect("/ws") as g:
        g.send_json({"type": "queue_join"})
        assert _drain(g, "error")["code"] == "signed_in_only"


def test_ws_start_bots_solo_starts_a_rated_game(wsenv):
    srv, store, client, clock = wsenv
    uid, headers = _user(store, "solo", "Solo")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        started = _drain(a, "match_started", tries=40)
        assert started["match_id"] is None and started["rated"] is True
        state = _drain(a, "state", tries=80)
        room = srv.rooms[started["room"]]
        assert state["you"] == 0 and [s.is_bot for s in room.seats] == [False, True, True, True]
        assert room.ratings.present == {0: uid}


def test_ws_pair_start_bots_seats_both_partners(wsenv):
    srv, store, client, clock = wsenv
    u1, h1 = _user(store, "lead", "Lead")
    u2, h2 = _user(store, "mate", "Mate")
    with client.websocket_connect("/ws", headers=h1) as a, \
            client.websocket_connect("/ws", headers=h2) as b:
        a.send_json({"type": "party_create"})
        party = _drain(a, "party")
        b.send_json({"type": "party_join", "code": party["code"]})
        assert len(_drain(b, "party")["members"]) == 2
        a.send_json({"type": "queue_join", "party_id": party["party_id"]})
        _drain(b, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        code = _drain(b, "match_started", tries=40)["room"]
        _drain(b, "state", tries=80)
        room = srv.rooms[code]
        assert [s.user_id for s in room.seats] == [u1, None, u2, None]


def test_ws_two_starts_take_a_waiting_table_to_a_rated_game_with_bots(wsenv):
    srv, store, client, clock = wsenv
    (u1, h1), (u2, h2) = _user(store, "t1", "One"), _user(store, "t2", "Two")
    with client.websocket_connect("/ws", headers=h1) as a, \
            client.websocket_connect("/ws", headers=h2) as b:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        b.send_json({"type": "queue_join"})
        assert _drain(b, "queue_state")["table"]["of"] == 2
        a.send_json({"type": "table_start"})
        table = _drain(b, "queue_state")["table"]
        assert table["ready"] == 1 and table["seats"][0]["ready"] and table["waiting_for"] == []
        b.send_json({"type": "table_start"})
        started = _drain(a, "match_started", tries=80)
        assert started["rated"] is True
        _drain(a, "state", tries=80)
        room = srv.rooms[started["room"]]
        assert [s.user_id for s in room.seats] == [u1, None, u2, None]
        assert room.waiting_table == started["match_id"] and room.table_humans == 2


def test_ws_away_socket_is_dropped_and_a_quick_reconnect_keeps_its_place(wsenv):
    srv, store, client, clock = wsenv
    uid, headers = _user(store, "away")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        since = _drain(a, "queue_state")["since"]
    # The receive loop's cleanup runs on the server's loop; pump until seen.
    for _ in range(50):
        _pump(client, srv)
        if srv.MATCHMAKER.conns[uid].closed:
            break
    clock.advance(5)
    with client.websocket_connect("/ws", headers=headers) as a2:
        state = _drain(a2, "queue_state")
        assert state["queued"] and state["since"] == since
    for _ in range(50):
        _pump(client, srv)
        if srv.MATCHMAKER.conns[uid].closed:
            break
    clock.advance(mm.AWAY_SECS + 1)
    _pump(client, srv)
    assert srv.MATCHMAKER._entry(uid) is None


def test_ws_joining_a_room_leaves_the_queue_and_leaving_it_returns_to_the_lobby(wsenv):
    srv, store, client, clock = wsenv
    uid, headers = _user(store, "roomie")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        a.send_json({"type": "join_room", "room": "NOPE", "name": "x"})
        _drain(a, "error")
        assert srv.MATCHMAKER._entry(uid) is not None      # a failed join keeps the place
        a.send_json({"type": "create_room", "name": "x"})
        got = _drain_all(a, {"room", "queue_removed"})
        assert got["queue_removed"]["reason"] == "in_room"
        assert srv.MATCHMAKER._entry(uid) is None
        a.send_json({"type": "queue_join"})
        assert _drain(a, "error")["code"] == "in_room"
        a.send_json({"type": "leave_room"})
        _drain(a, "left")
        a.send_json({"type": "queue_join"})
        assert _drain(a, "queue_state")["queued"] is True


# ----------------------------------------------------- one code space
class ScriptedCodes:
    """An RNG whose ``choices`` deals the given codes in order."""

    def __init__(self, *codes):
        self.codes = iter(codes)

    def choices(self, population, k):
        code = next(self.codes)
        assert len(code) == k and set(code) <= set(population)
        return list(code)


def test_new_code_draws_again_past_any_taken_code():
    taken = {"ABCD", "EFGH"}
    code = mm.new_code(taken.__contains__, ScriptedCodes("ABCD", "EFGH", "JKLM"))
    assert code == "JKLM"


def test_a_pair_code_never_repeats_a_live_room_code(monkeypatch):
    async def go():
        env = Env()
        env.mm.room_live = {"WXYZ"}.__contains__
        monkeypatch.setattr(mm, "_CODE_RNG", ScriptedCodes("WXYZ", "WXYZ", "PQRS"))
        env.player(1)
        await env.send(1, "party_create")
        assert env.conns[1].last("party")["code"] == "PQRS"
    run(go())


def test_code_lookup_names_rooms_pairs_and_nothing():
    async def go():
        env = Env()
        env.mm.room_live = {"WXYZ"}.__contains__
        p = await env.pair(1, 2)
        guest = FakeConn(None, "")
        env.mm.connect(guest)

        def kind(code, uid=None, conn=guest):
            return env.mm.code_lookup(conn, {"code": code}, uid)

        assert kind(" wxyz ") == {"type": "code_kind", "code": "WXYZ", "kind": "room"}
        assert kind(p.code.lower()) == {"type": "code_kind", "code": p.code, "kind": "party"}
        assert kind(p.code, uid=1, conn=env.conns[1])["kind"] == "party"
        assert kind("ZZZZ")["kind"] == "none"
        for bad in ("WXY", "WXYZQ", "", None, "W-YZ"):
            assert kind(bad)["kind"] == "none", bad
        await env.send(1, "party_leave")             # a closed pair's code is free again
        assert kind(p.code)["kind"] == "none"
    run(go())


def test_code_lookup_is_rate_limited_per_account():
    env = Env()
    conn = env.player(1)
    limit, _ = mm.LOOKUP_LIMIT
    for _ in range(limit):
        assert env.mm.code_lookup(conn, {"code": "ABCD"}, 1)["type"] == "code_kind"
    refused = env.mm.code_lookup(conn, {"code": "ABCD"}, 1)
    assert refused["type"] == "error" and refused["code"] == "rate_limited"
    assert refused["lookup"] == "ABCD"
    env.clock.advance(mm.LOOKUP_LIMIT[1] + 1)
    assert env.mm.code_lookup(conn, {"code": "ABCD"}, 1)["type"] == "code_kind"


def test_ws_room_code_never_repeats_a_live_pair_code(wsenv, monkeypatch):
    import random

    srv, store, client, clock = wsenv
    _, headers = _user(store, "pairer", "Pairer")
    monkeypatch.setattr(mm, "_CODE_RNG", ScriptedCodes("PQRS"))
    rolls = iter(["PQRS", "TUVW"])
    monkeypatch.setattr(random, "choices", lambda population, k: list(next(rolls)))
    with client.websocket_connect("/ws", headers=headers) as a, \
            client.websocket_connect("/ws") as b:
        a.send_json({"type": "party_create"})
        assert _drain(a, "party")["code"] == "PQRS"
        b.send_json({"type": "create_room", "name": "host"})
        assert _drain(b, "room")["room"] == "TUVW"


def test_ws_code_lookup_and_the_old_join_messages(wsenv):
    srv, store, client, clock = wsenv
    _, headers = _user(store, "leader", "Leader")
    with client.websocket_connect("/ws", headers=headers) as a, \
            client.websocket_connect("/ws") as host, \
            client.websocket_connect("/ws") as g:
        a.send_json({"type": "party_create"})
        pair = _drain(a, "party")["code"]
        host.send_json({"type": "create_room", "name": "host"})
        room = _drain(host, "room")["room"]
        assert all(c in mm.CODE_ALPHABET for c in room + pair)

        for code, kind in ((room.lower(), "room"), (pair.lower(), "party"),
                           ("ZZZZ", "none")):
            g.send_json({"type": "code_lookup", "code": code})
            assert _drain(g, "code_kind") == {"type": "code_kind", "code": code.upper(),
                                              "kind": kind}
        # a signed-in socket asks the same way
        a.send_json({"type": "code_lookup", "code": room})
        assert _drain(a, "code_kind")["kind"] == "room"

        # a guest who follows a pair code is told to sign in
        g.send_json({"type": "party_join", "code": pair})
        assert _drain(g, "error")["code"] == "signed_in_only"

        # the messages old clients send still work
        g.send_json({"type": "peek_room", "room": room.lower()})
        assert _drain(g, "room_seats")["room"] == room
        g.send_json({"type": "join_room", "room": room, "name": "guest"})
        assert _drain(g, "room")["room"] == room

        # a closed room's code names nothing
        closed = srv.rooms.pop(room)
        try:
            a.send_json({"type": "code_lookup", "code": room})
            assert _drain(a, "code_kind")["kind"] == "none"
        finally:
            srv.rooms[room] = closed          # the fixture's teardown stops its tasks


# ------------------------------------------------- open tables: the matcher
class Tables:
    """The open tables a fake server reports, and its Join: the first
    confirm of a seat takes it."""

    def __init__(self, env):
        self.env = env
        self.tables: dict[str, dict] = {}
        self.joins: list[tuple[str, int, int]] = []
        env.mm.open_tables = self
        env.mm.join_table = self.join

    def add(self, code, seats, round_end=False, mode="ranked"):
        """``seats``: an int is a person's account, "bot" a bot seat."""
        self.tables[code] = {"code": code, "round_end": round_end, "mode": mode, "seats": [
            {"name": "Bot", "bot": True, "open": True, "queue_id": None, "team": i % 2}
            if s == "bot" else
            {"name": f"P{s}", "bot": False, "open": False, "queue_id": s, "team": i % 2}
            for i, s in enumerate(seats)]}

    def take(self, code, seat, uid):
        self.tables[code]["seats"][seat] = {"name": f"P{uid}", "bot": False, "open": False,
                                            "queue_id": uid, "team": seat % 2}

    def __call__(self):
        return [t for t in self.tables.values() if any(s["open"] for s in t["seats"])]

    async def join(self, code, seat, uid, name, conn):
        t = self.tables.get(code)
        if t is None or not any(s["open"] for s in t["seats"]):
            return "closed"
        if not t["seats"][seat]["open"]:
            return "seat_taken"
        self.take(code, seat, uid)
        self.joins.append((code, seat, uid))
        self.env.mm.enter_room(conn)
        return None


def test_a_newcomer_alone_is_offered_an_open_table_with_the_partner_seat_picked():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        state = env.conns[1].last("queue_state")
        offer = state["offer"]
        assert offer["room"] == "OPEN" and offer["pick"] == 2 and offer["round_end"] is False
        assert offer["expires_at"] == env.clock.t + mm.OFFER_SECS
        assert [(s["name"], s["bot"], s["open"]) for s in offer["seats"]] == [
            ("P50", False, False), ("Bot", True, True), ("Bot", True, True), ("Bot", True, True)]
        # the bot wait stands still while the offer is up
        assert state["bots_paused"] is True and state["bots_at"] is None
        assert state["wait_players"] is False and state["open_tables"] == 0
        env.clock.advance(mm.BOT_FILL_SECS + 5)
        await env.mm.tick()
        assert env.started == []
    run(go())


def test_a_waiting_table_outranks_an_open_table():
    async def go():
        env = Env()
        tables = Tables(env)
        await env.join(1)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.mm.tick()                           # an alone waiter gets the new table
        assert env.conns[1].last("queue_state")["offer"]["room"] == "OPEN"
        env.clock.advance(3)
        await env.join(2)                             # someone queued: they share a table
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 2, None]
        for uid in (1, 2):
            state = env.conns[uid].last("queue_state")
            assert state["offer"] is None and state["table"] is not None
        # the wait stood still under the offer and runs on as the table's timer
        assert env.mm._entry(1).bots_at == env.clock.t + mm.BOT_FILL_SECS
        # a pair queued now sits across from the two singles, before any
        # open table, and the full table starts
        await env.pair(3, 4)
        await env.send(3, "queue_join", party_id=env.mm._party(3).id)
        (table_id, slots), = env.started
        assert table_id == t.id and [s.user_id for s in slots] == [1, 3, 2, 4]
    run(go())


def test_a_seat_another_newcomer_took_first_re_renders_the_offer():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        tables.take("OPEN", 2, 77)                    # another newcomer confirmed seat 2 first
        await env.send(1, "open_table_join", room="OPEN", seat=2)
        assert env.conns[1].last("error")["code"] == "seat_taken"
        offer = env.conns[1].last("queue_state")["offer"]
        assert offer["seats"][2] == {"name": "P77", "bot": False, "open": False}
        assert offer["pick"] == 1 and env.mm._entry(1) is not None
        await env.send(1, "open_table_join", room="OPEN", seat=3)
        assert tables.joins == [("OPEN", 3, 1)]
        assert env.mm._entry(1) is None and env.mm.joining[1][0] == "OPEN"
        assert env.conns[1].in_room
    run(go())


def test_a_tick_re_renders_a_standing_offer_when_its_seat_goes():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", 60, "bot"])
        await env.join(1)
        assert env.conns[1].last("queue_state")["offer"]["pick"] == 1
        tables.take("OPEN", 1, 77)
        await env.mm.tick()
        offer = env.conns[1].last("queue_state")["offer"]
        assert offer["pick"] == 3 and offer["seats"][1]["open"] is False
        tables.take("OPEN", 3, 78)                    # four people: no longer open
        await env.mm.tick()
        assert env.conns[1].last("queue_state")["offer"] is None
    run(go())


def test_wait_keeps_queuing_resumes_the_bot_timer_and_never_re_offers_by_itself():
    async def go():
        env = Env()
        tables = Tables(env)
        await env.join(1)
        env.clock.advance(20)                         # 40 s of bot wait left
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.mm.tick()
        assert env.conns[1].last("queue_state")["bots_paused"] is True   # the offer is up
        env.clock.advance(5)
        await env.send(1, "open_table_wait")
        # after Wait the countdown runs on from where it stopped; the table
        # stays one tap away on the chip
        state = env.conns[1].last("queue_state")
        assert state["queued"] and state["offer"] is None
        assert state["open_tables"] == 1 and state["bots_paused"] is False
        assert state["bots_at"] == env.clock.t + 40
        env.clock.advance(20)
        await env.mm.pump()
        await env.mm.tick()
        assert env.started == [] and env.mm._entry(1).offer is None
        # the chip brings the offer back, with a fresh clock, and holds the timer again
        await env.send(1, "open_table_show")
        state = env.conns[1].last("queue_state")
        offer = state["offer"]
        assert offer["room"] == "OPEN" and offer["expires_at"] == env.clock.t + mm.OFFER_SECS
        assert state["bots_paused"] is True
        await env.send(1, "open_table_wait")
        assert env.conns[1].last("queue_state")["bots_at"] == env.clock.t + 20
        env.clock.advance(20)
        await env.mm.tick()
        assert [humans_of(slots) for _, slots in env.started] == [[1]]
    run(go())


def test_an_unanswered_offer_lapses_into_wait():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        env.clock.advance(mm.OFFER_SECS)
        await env.mm.pump()
        state = env.conns[1].last("queue_state")
        assert state["offer"] is None and state["open_tables"] == 1
        await env.send(1, "open_table_join", room="OPEN", seat=1)
        assert env.conns[1].last("error")["code"] == "no_offer"
    run(go())


def test_a_reclaimed_join_puts_the_newcomer_back_at_the_front():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        await env.send(1, "open_table_join", room="OPEN", seat=2)
        env.mm.return_to_lobby(env.conns[1])
        env.mm.join_ended(1, back_in_line=True)
        e = env.mm._entry(1)
        assert e is not None and e.front and 1 not in env.mm.joining
        assert "OPEN" in env.mm.declined[1] and 1 not in env.mm.cooldowns
        assert env.conns[1].last("queue_state")["queued"] is True
    run(go())


@pytest.mark.parametrize("seated", [False, True])
def test_join_then_leave_costs_a_cooldown_and_the_table_is_never_offered_again(seated):
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        await env.send(1, "open_table_join", room="OPEN", seat=2)
        env.mm.return_to_lobby(env.conns[1])
        if seated:
            env.mm.join_seated(1)
            env.mm.left_open_table(1, "OPEN")
        else:
            env.mm.join_ended(1, back_in_line=False, penalty=True)
        assert env.mm._entry(1) is None
        tables.tables["OPEN"]["seats"][2] = {"name": "Bot", "bot": True, "open": True,
                                             "queue_id": None, "team": 0}
        await env.send(1, "queue_join")
        err = env.conns[1].last("error")
        assert err["code"] == "cooldown"
        assert err["cooldown_until"] == env.clock.t + mm.JOIN_COOLDOWN_SECS
        env.clock.advance(mm.JOIN_COOLDOWN_SECS)
        await env.join(1)
        state = env.conns[1].last("queue_state")
        assert state["offer"] is None and state["open_tables"] == 0
        await env.send(1, "open_table_show")
        assert env.conns[1].last("error")["code"] == "table_closed"
        assert state["bots_paused"] is False
    run(go())


def test_a_guest_never_sees_an_open_table():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        guest = FakeConn(None, "")
        env.mm.connect(guest)
        await env.mm.tick()
        for kind in ("queue_join", "open_table_join", "open_table_show"):
            await env.mm.handle(guest, {"type": kind, "room": "OPEN", "seat": 1}, None)
            assert guest.last("error")["code"] == "signed_in_only"
        assert guest.of("queue_state") == [] and tables.joins == []
    run(go())


# ------------------------------------------------- open tables: the server
@pytest.fixture()
def otenv(accounts_on, tmp_path, monkeypatch):  # noqa: F811
    """The server's open-table functions on a fresh room registry, with the
    queue a test ``Env`` and every bot decision driven by the test."""
    from shengji.api import server as srv

    env = Env()
    monkeypatch.setattr(srv, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(srv, "rooms", {})
    monkeypatch.setattr(srv, "MATCHMAKER", env.mm)
    monkeypatch.setattr(srv, "kick_bots", lambda room: None)

    async def no_deal(room):
        return

    monkeypatch.setattr(srv, "run_deal", no_deal)
    env.mm.open_tables = srv.open_tables
    env.mm.join_table = srv.join_open_table
    ratings.CARRIED_CAPS.clear()
    yield srv, accounts_on.STORE, env
    ratings.CARRIED_CAPS.clear()


class OpenRoom:
    """A ranked room in play whose seats the test assigns (an int is a
    connected signed-in person, "bot" a bot), dealt and played in-process."""

    def __init__(self, srv, seats, code="OPEN"):
        from shengji.engine.game import Game

        self.srv = srv
        self.room = room = srv.Room(code=code, matched=True, move_timer=True)
        room.seats = [srv.Seat(name=f"Bot {i}", is_bot=True) if s == "bot"
                      else srv.Seat(name=f"P{s}", user_id=s, queue_id=s,
                                connected=True)
                      for i, s in enumerate(seats)]
        room.game = Game(start_level="2", games_to_win=None)
        srv.rooms[code] = room

    def first_round(self, banker=0):
        room = self.room
        room.game.banker = banker
        room.game.start_round()
        room.index_round()
        room.saved_game = None
        ratings.start(room)
        self._deal(banker)

    async def next_round(self, banker=None):
        room = self.room
        if banker is not None:
            room.game.result.next_banker = banker
            room.game.banker = banker
        room.ready = {i for i, sd in enumerate(room.seats) if not sd.is_bot and sd.connected}
        assert await self.srv.advance_if_all_ready(room)
        self._deal(room.round.banker if room.round.banker is not None else banker or 0)

    def _deal(self, banker):
        rnd = self.room.round
        while rnd.phase == "deal":
            seat, idx, code = rnd.deal_next()
            self.room.ids[seat][idx] = code
        rnd.finalize_declare()
        if rnd.banker is None:
            rnd.banker = banker

    async def step(self):
        rnd = self.room.round
        actor = rnd.banker if rnd.phase == "bury" else rnd.turn
        assert self.srv.bot_step(self.room, actor)
        await self.srv.broadcast(self.room)

    async def until(self, pred):
        for _ in range(400):
            if pred(self.room.round):
                return
            await self.step()
        raise AssertionError("never reached")

    async def finish(self):
        await self.until(lambda r: r.phase == "round_end")
        ratings.flush()
        return self.room.game.result


def _plays(rnd, seat):
    n = sum(1 for t in rnd.history for p in t.plays if p.seat == seat)
    return n + (sum(1 for p in rnd.trick.plays if p.seat == seat) if rnd.trick else 0)


async def _newcomer_joins(env, uid, seat, name, code="OPEN"):
    conn = env.player(uid, name=name)
    conn.ws = _FakeWS()
    await env.send(uid, "queue_join")
    offer = conn.last("queue_state")["offer"]
    assert offer is not None and offer["room"] == code, conn.sent
    await env.send(uid, "open_table_join", room=code, seat=seat)
    assert conn.last("error") is None, conn.last("error")
    return conn


def test_open_tables_are_ranked_games_in_play_with_bot_seats_and_joiners_allowed(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        assert srv.open_tables() == []                # no game in play yet
        t.first_round()
        (view,) = srv.open_tables()
        assert view["code"] == "OPEN" and view["round_end"] is False
        assert view["mode"] == "ranked"
        assert [s["open"] for s in view["seats"]] == [False, True, True, True]
        assert srv.state_for(t.room, 0)["allow_joiners"] is True
        await srv.handle_action(t.room, 0, {"type": "allow_joiners", "on": False})
        assert srv.open_tables() == [] and srv.state_for(t.room, 0)["allow_joiners"] is False
        with pytest.raises(srv.IllegalPlay):
            await srv.handle_action(t.room, 1, {"type": "allow_joiners", "on": True})
        await srv.handle_action(t.room, 0, {"type": "allow_joiners", "on": True})
        assert len(srv.open_tables()) == 1
        # nobody connected, a test room, four people: none is open
        t.room.seats[0].connected = False
        assert srv.open_tables() == []
        t.room.seats[0].connected = True
        t.room.experimental_policy = "w32"
        assert srv.open_tables() == []
        t.room.experimental_policy = None
        # a casual room is an open table of the casual queue
        t.room.matched = False
        assert [v["mode"] for v in srv.open_tables()] == ["casual"]
        t.room.matched = True
        for i in (1, 2, 3):
            t.room.seats[i] = srv.Seat(name=f"Q{i}", user_id=900 + i, connected=True)
        assert srv.open_tables() == []
    run(go())


def test_the_bot_plays_on_until_the_trick_ends_then_the_newcomer_holds_the_seat(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        await t.until(lambda r: r.phase == "play" and r.trick.plays
                      and all(p.seat != 2 for p in r.trick.plays))
        before = _plays(t.room.round, 2)
        conn = await _newcomer_joins(env, new, 2, "Alice")
        room = t.room
        started = conn.last("match_started")
        assert started["joining"] is True and started["room"] == "OPEN" and started["seat"] == 2
        assert room.seats[2].is_bot and 2 in room.pending_joins
        frame = conn.last("state")
        assert frame["joining_you"] is True and frame["you"] == 2
        assert srv.state_for(room, 0)["joining"] == [{"seat": 2, "name": "Alice", "when": "trick"}]
        # the seat is not open to anyone else meanwhile
        assert [s["open"] for s in srv.open_tables()[0]["seats"]] == [False, True, False, True]
        trick_no = len(room.round.history)
        await t.until(lambda r: len(r.history) > trick_no)
        assert _plays(room.round, 2) == before + 1    # the bot played the seat's card
        seat = room.seats[2]
        assert not seat.is_bot and seat.user_id == new and seat.name == "Alice"
        assert seat.connected and seat.joined_round == room.game.round_no
        assert conn.adopted is not None and conn.adopted[1] is seat
        assert room.pending_joins == {} and new not in env.mm.joining
        assert srv.state_for(room, 0)["joining"] == []
    run(go())


def test_a_joiner_is_unranked_for_the_round_joined_mid_way_and_ranked_from_the_next(
        otenv, monkeypatch):
    from tests.test_ratings import _events, _force_outcome

    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")
    _force_outcome(monkeypatch, 30)

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        await t.until(lambda r: r.phase == "play" and len(r.history) == 2)
        await _newcomer_joins(env, new, 2, "Alice")
        await t.finish()
        assert [e["user_id"] for e in _events(store)] == [host]
        result = srv.state_for(t.room, 2)["round_result"]
        assert result["unranked"] == "joined" and "rating" not in result
        assert "unranked" not in srv.state_for(t.room, 0)["round_result"]
        await t.next_round(banker=0)
        assert t.room.seats[2].joined_round is None
        await t.finish()
        second = sorted(e["user_id"] for e in _events(store) if e["round_no"] == 2)
        assert second == sorted([host, new])
    run(go())


def test_at_a_round_end_the_newcomer_sits_at_once_and_is_ranked_next_round(otenv, monkeypatch):
    from tests.test_ratings import _events, _force_outcome

    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")
    _force_outcome(monkeypatch, 30)

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        await t.finish()
        conn = env.player(new, name="Alice")
        conn.ws = _FakeWS()
        await env.send(new, "queue_join")
        assert conn.last("queue_state")["offer"]["round_end"] is True
        await env.send(new, "open_table_join", room="OPEN", seat=2)
        seat = t.room.seats[2]
        assert seat.user_id == new and seat.joined_round is None
        assert new not in env.mm.joining and env.mm._entry(new) is None
        assert srv.state_for(t.room, 0)["joining"] == [{"seat": 2, "name": "Alice", "when": "round"}]
        assert "unranked" not in srv.state_for(t.room, 2)["round_result"]
        assert srv.pending_ready(t.room) >= {2}       # the newcomer's Next counts too
        await t.next_round(banker=0)
        assert srv.state_for(t.room, 0)["joining"] == []
        await t.finish()
        second = sorted(e["user_id"] for e in _events(store) if e["round_no"] == 2)
        assert second == sorted([host, new])
    run(go())


def test_a_bury_never_changes_hands_and_a_seat_that_owes_nothing_changes_at_once(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")
    other, _ = _user(store, "bob", "Bob")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=2)
        room = t.room
        assert room.round.phase == "bury" and room.round.turn == 2
        await _newcomer_joins(env, new, 2, "Alice")
        assert room.seats[2].is_bot and 2 in room.pending_joins     # mid-bury: waits
        # someone else's bury owes seat 1 nothing: Bob sits at once
        await _newcomer_joins(env, other, 1, "Bob")
        assert room.seats[1].user_id == other
        await t.step()                                # the bot buries
        assert room.round.phase == "play" and room.seats[2].user_id == new
    run(go())


def test_two_confirms_for_one_seat_first_wins(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    a, _ = _user(store, "alice", "Alice")
    b, _ = _user(store, "bob", "Bob")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=2)                       # seat 2 buries: Joins wait
        ca, cb = env.player(a, name="Alice"), env.player(b, name="Bob")
        assert await srv.join_open_table("OPEN", 2, a, "Alice", ca) is None
        assert await srv.join_open_table("OPEN", 2, b, "Bob", cb) == "seat_taken"
        assert t.room.pending_joins[2].uid == a
    run(go())


def test_an_away_seat_is_offered_from_the_round_boundary_and_its_owner_reclaims_it(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    dana, _ = _user(store, "dana", "Dana")
    new, _ = _user(store, "alice", "Alice")
    late, _ = _user(store, "bob", "Bob")

    async def go():
        t = OpenRoom(srv, [host, "bot", dana, "bot"])
        room = t.room
        room.seats[2].name = "Dana"
        t.first_round(banker=0)
        dana_conn = env.player(dana)
        dana_conn.ws = room.seats[2].ws = _FakeWS()
        dana_conn.in_room = True
        # Dana goes away in round 1 (two timeouts): not offered in round 1 or 2
        room.seats[2].timeouts_in_row = 1
        srv._count_timeout(room, 2)
        assert room.seats[2].away and room.seats[2].away_since == 1
        offerable = lambda: [s["open"] for s in srv.open_tables()[0]["seats"]]  # noqa: E731
        assert offerable() == [False, True, False, True]
        await t.finish()
        assert offerable() == [False, True, False, True]
        await t.next_round(banker=0)
        await t.until(lambda r: r.phase == "play" and len(r.history) == 1)
        assert offerable() == [False, True, False, True]
        await t.finish()
        # away for the whole of round 2: offered from its end
        view = srv.open_tables()[0]["seats"]
        assert view[2] == {"name": "Dana", "bot": False, "away": True, "open": True,
                           "team": 0, "queue_id": dana, "device": None}
        await t.next_round(banker=0)
        await t.until(lambda r: r.phase == "play" and r.trick.plays
                      and all(p.seat != 2 for p in r.trick.plays))
        conn = await _newcomer_joins(env, new, 2, "Alice")
        assert 2 in room.pending_joins and room.seats[2].user_id == dana
        # Dana taps I'm back before the trick ends: the seat stays hers
        await srv.handle_action(room, 2, {"type": "im_back"})
        await srv.broadcast(room)
        assert room.pending_joins == {} and room.seats[2].user_id == dana
        left = conn.last("left")
        assert left["reason"] == "reclaimed" and "Dana" in left["message"]
        e = env.mm._entry(new)
        assert e is not None and e.front and not conn.in_room
        await env.send(new, "queue_leave")      # else Bob would sit with her
        # away again for a whole round: Bob takes it at a round end and Dana is sent off
        room.seats[2].away, room.seats[2].away_since = True, room.game.round_no - 1
        await t.finish()
        await _newcomer_joins(env, late, 2, "Bob")
        seat = room.seats[2]
        assert seat.user_id == late and seat.name == "Bob" and not seat.away
        assert dana_conn.last("left")["reason"] == "seat_given"
    run(go())


def _wait_until(pred, timeout=15.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition never held")


def test_ws_join_then_leave_gives_the_seat_back_to_a_bot_with_a_cooldown_and_a_carried_cap(
        wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    ratings.CARRIED_CAPS.clear()
    host, host_headers = _user(store, "host", "Host")
    alice, alice_headers = _user(store, "alice", "Alice")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=alice_headers) as a:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        code = _drain(h, "match_started")["room"]
        room = srv.rooms[code]
        room.seats[0].away = True                    # the bot plays the host's seat too
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        a.send_json({"type": "queue_join"})
        offer = _drain(a, "queue_state")["offer"]
        assert offer["room"] == code and offer["pick"] == 2
        a.send_json({"type": "open_table_join", "room": code, "seat": 2})
        started = _drain(a, "match_started")
        assert started["joining"] is True
        _wait_until(lambda: room.seats[2].user_id == alice)
        assert room.seats[2].joined_round == room.game.round_no
        a.send_json({"type": "leave_room"})
        _drain(a, "left", tries=400)
        seat = room.seats[2]
        assert seat.is_bot and seat.user_id is None and seat.name == "Bot 2"
        assert alice in ratings.CARRIED_CAPS
        a.send_json({"type": "queue_join"})
        err = _drain(a, "error", tries=400)
        assert err["code"] == "cooldown"
        clock.advance(mm.JOIN_COOLDOWN_SECS + 1)
        a.send_json({"type": "queue_join"})
        state = _drain(a, "queue_state", tries=400)
        assert state["queued"] and state["offer"] is None and state["open_tables"] == 0
    ratings.CARRIED_CAPS.clear()


def test_a_newcomer_leaving_at_the_end_of_the_round_it_joined_carries_no_cap(
        wsenv, monkeypatch):
    """The round joined mid-way was played out: Leave on its round-end screen
    is an ordinary between-rounds leave, with no carried cap and no cooldown."""
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    ratings.CARRIED_CAPS.clear()
    host, host_headers = _user(store, "host", "Host")
    alice, alice_headers = _user(store, "alice", "Alice")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=alice_headers) as a:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        code = _drain(h, "match_started")["room"]
        room = srv.rooms[code]
        room.seats[0].away = True                    # the bot plays the host's seat too
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        a.send_json({"type": "queue_join"})
        offer = _drain(a, "queue_state")["offer"]
        assert offer["room"] == code and offer["pick"] == 2
        a.send_json({"type": "open_table_join", "room": code, "seat": 2})
        _drain(a, "match_started")
        _wait_until(lambda: room.seats[2].user_id == alice)
        round_no = room.game.round_no
        assert room.seats[2].joined_round == round_no
        # the bot plays Alice's cards for her; it stands in for her own plays,
        # so that cover is not itself read as abandoning the round
        monkeypatch.setattr(srv, "_joined_round_ended", lambda room: None)
        room.seats[2].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round.phase == "round_end")
        room.seats[2].away = False
        assert room.game.round_no == round_no and alice not in ratings.CARRIED_CAPS
        a.send_json({"type": "leave_room"})
        _drain(a, "left", tries=400)
        assert alice not in ratings.CARRIED_CAPS
        a.send_json({"type": "queue_join"})
        state = _drain(a, "queue_state", tries=400)
        assert state["queued"]
    ratings.CARRIED_CAPS.clear()


@pytest.mark.parametrize("left", [True, False])
def test_leaving_or_dropping_before_the_handover_ends_the_join(otenv, left):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=2)                       # seat 2 buries: the Join waits
        conn = await _newcomer_joins(env, new, 2, "Alice")
        assert 2 in t.room.pending_joins and conn.joining is not None
        if not left:
            conn.close(env.clock.t)
        await srv.end_pending_join(conn, penalty=left)
        assert t.room.pending_joins == {} and t.room.seats[2].is_bot
        assert conn.joining is None and new not in env.mm.joining
        assert ("OPEN" in env.mm.barred.get(new, set())) is left
        assert (new in env.mm.cooldowns) is left
        assert "OPEN" in env.mm.declined.get(new, set()) or left
        assert env.mm._entry(new) is None
        assert len(srv.open_tables()) == 1
    run(go())


# ------------------------------------------- a ranked table's invite link
def _ranked_host(srv, store, client, monkeypatch):
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    host, headers = _user(store, "host", "Host")
    return host, headers


def _start_ranked(srv, h):
    h.send_json({"type": "queue_join"})
    _drain(h, "queue_state")
    h.send_json({"type": "queue_start_bots"})
    code = _drain(h, "match_started")["room"]
    return code, srv.rooms[code]


def test_ws_an_invite_link_seats_a_signed_in_friend_even_with_joiners_off(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _, host_headers = _ranked_host(srv, store, client, monkeypatch)
    friend, friend_headers = _user(store, "friend", "Friend")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=friend_headers) as f:
        code, room = _start_ranked(srv, h)
        room.allow_joiners = False
        room.seats[0].away = True                    # the bot plays on for the host
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        assert srv.open_tables() == []               # not offered to the queue
        f.send_json({"type": "peek_room", "room": code})
        seats = _drain(f, "room_seats")
        assert seats["ranked"] is True and seats["full"] is False
        assert [s["claimable"] for s in seats["seats"]] == [False, True, True, True]
        f.send_json({"type": "join_room", "room": code, "name": "Friend", "seat": 2})
        started = _drain(f, "match_started")
        assert started["joining"] is True and started["seat"] == 2
        _wait_until(lambda: room.seats[2].user_id == friend)
        assert room.seats[2].joined_round == room.game.round_no      # first round unranked
        f.send_json({"type": "leave_room"})
        _drain(f, "left", tries=400)
        assert room.seats[2].is_bot
        assert srv.MATCHMAKER.cooldowns[friend] > clock()
        assert friend in ratings.CARRIED_CAPS
        f.send_json({"type": "join_room", "room": code, "name": "Friend", "seat": 2})
        assert _drain(f, "error", tries=400)["code"] == "cooldown"
    ratings.CARRIED_CAPS.clear()


def test_ws_a_guest_with_a_ranked_invite_joins_as_a_newcomer(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _, host_headers = _ranked_host(srv, store, client, monkeypatch)
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws") as nokey, \
            client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        code, room = _start_ranked(srv, h)
        g.send_json({"type": "peek_room", "room": code})
        assert _drain(g, "room_seats")["ranked"] is True
        # no device key: no queue identity, so no way in
        nokey.send_json({"type": "join_room", "room": code, "name": "Guest", "seat": 2})
        assert _drain(nokey, "error")["code"] == "ranked_queue_only"
        g.send_json({"type": "join_room", "room": code, "name": "Guest", "seat": 2})
        started = _drain(g, "match_started")
        assert started["joining"] is True and started["seat"] == 2
        seat = room.seats[2]
        assert seat.user_id is None and (seat.queue_id or room.pending_joins[2].uid) < 0


def test_ws_a_ranked_invite_with_no_bot_seat_is_table_full(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _, host_headers = _ranked_host(srv, store, client, monkeypatch)
    friend, friend_headers = _user(store, "friend", "Friend")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=friend_headers) as f:
        code, room = _start_ranked(srv, h)

        async def fill():
            async with room.lock:
                for i in (1, 2, 3):
                    seat = room.seats[i]
                    seat.is_bot, seat.name, seat.user_id, seat.connected = False, f"Q{i}", 900 + i, True
        client.portal.call(fill)
        f.send_json({"type": "peek_room", "room": code})
        seats = _drain(f, "room_seats")
        assert seats["full"] is True and not any(s["claimable"] for s in seats["seats"])
        f.send_json({"type": "join_room", "room": code, "name": "Friend"})
        err = _drain(f, "error")
        assert err["code"] == "table_full" and err["message"] == "Table is full."
        assert room.pending_joins == {}


# ------------------------------------------------- open tables: a queued pair
async def _queued_pair(env, leader, partner, names=("Lee", "Pat")):
    for uid, name in zip((leader, partner), names):
        env.player(uid, name=name).ws = _FakeWS()
    await env.send(leader, "party_create")
    code = env.conns[leader].last("party")["code"]
    await env.send(partner, "party_join", code=code)
    await env.send(leader, "queue_join", party_id=env.mm._party(leader).id)
    return env.conns[leader], env.conns[partner]


@pytest.fixture()
def pairenv(otenv):
    srv, store, env = otenv
    env.mm.join_pair = srv.join_pair_open_table
    return otenv


def test_a_pair_is_offered_two_free_partner_seats_together(pairenv):
    srv, store, env = pairenv
    host, _ = _user(store, "host")
    lee, _ = _user(store, "lee", "Lee")
    pat, _ = _user(store, "pat", "Pat")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        cl, cp = await _queued_pair(env, lee, pat)
        lo, po = cl.last("queue_state")["offer"], cp.last("queue_state")["offer"]
        assert lo["room"] == "OPEN" and (lo["pick"], lo["partner"]["seat"]) == (1, 3)
        assert lo["partner"]["name"] == "Pat"
        assert (po["pick"], po["partner"]) == (3, {"seat": 1, "name": "Lee"})
    run(go())


def test_a_pair_is_never_offered_two_bot_seats_that_are_not_partners(pairenv):
    srv, store, env = pairenv
    host, _ = _user(store, "host")
    other, _ = _user(store, "other")
    lee, _ = _user(store, "lee", "Lee")
    pat, _ = _user(store, "pat", "Pat")
    solo, _ = _user(store, "solo", "Solo")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", other])      # bots at 1 and 2: adjacent
        t.first_round(banker=0)
        cl, cp = await _queued_pair(env, lee, pat)
        assert cl.last("queue_state")["offer"] is None and cp.last("queue_state")["offer"] is None
        await env.mm.tick()
        assert env.mm._entry(lee).offer is None
        await env.send(lee, "queue_leave")
        conn = env.player(solo, name="Solo")
        await env.send(solo, "queue_join")
        assert conn.last("queue_state")["offer"]["room"] == "OPEN"   # a single still is
    run(go())


def test_one_partner_waiting_cancels_the_pair_offer_with_no_cost(pairenv):
    srv, store, env = pairenv
    host, _ = _user(store, "host")
    lee, _ = _user(store, "lee", "Lee")
    pat, _ = _user(store, "pat", "Pat")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        cl, cp = await _queued_pair(env, lee, pat)
        await env.send(pat, "open_table_wait")                  # the member, not the leader
        for c in (cl, cp):
            state = c.last("queue_state")
            assert state["queued"] and state["offer"] is None and state["open_tables"] == 1
        assert {"OPEN"} <= env.mm.declined[lee] and {"OPEN"} <= env.mm.declined[pat]
        assert env.mm.cooldowns == {}
        await env.mm.tick()
        assert env.mm._entry(lee).offer is None
    run(go())


@pytest.mark.parametrize("leaver", ["confirmer", "partner"])
def test_a_partner_leaving_before_the_handover_cancels_both_joins(pairenv, leaver):
    srv, store, env = pairenv
    host, _ = _user(store, "host")
    lee, _ = _user(store, "lee", "Lee")
    pat, _ = _user(store, "pat", "Pat")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=1)                 # seat 1 buries: the pair's Join waits
        cl, cp = await _queued_pair(env, lee, pat)
        await env.send(pat, "open_table_join", room="OPEN", seat=3)     # Pat confirms for both
        room = t.room
        assert {s: pj.uid for s, pj in room.pending_joins.items()} == {1: lee, 3: pat}
        assert room.seats[1].is_bot and room.seats[3].is_bot            # 3 owes nothing, yet waits
        gone = cp if leaver == "confirmer" else cl
        stays = cl if gone is cp else cp
        await srv.end_pending_join(gone, penalty=True)
        assert room.pending_joins == {} and room.seats[1].is_bot and room.seats[3].is_bot
        assert stays.last("left")["reason"] == "partner_left"
        assert stays.joining is None and gone.joining is None
        if leaver == "confirmer":
            assert set(env.mm.cooldowns) == {pat} and "OPEN" in env.mm.barred[pat]
        else:
            assert env.mm.cooldowns == {}
    run(go())


def test_a_pair_takes_both_seats_at_the_same_trick_boundary(pairenv):
    srv, store, env = pairenv
    host, _ = _user(store, "host")
    lee, _ = _user(store, "lee", "Lee")
    pat, _ = _user(store, "pat", "Pat")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.first_round(banker=0)
        room = t.room
        # seat 1 has played to this trick (owes nothing), seat 3 has not
        await t.until(lambda r: r.phase == "play" and any(p.seat == 1 for p in r.trick.plays)
                      and all(p.seat != 3 for p in r.trick.plays))
        cl, cp = await _queued_pair(env, lee, pat)
        await env.send(lee, "open_table_join", room="OPEN", seat=1)
        assert set(room.pending_joins) == {1, 3} and room.seats[1].is_bot
        assert srv.state_for(room, 0)["joining"] == [
            {"seat": 1, "name": "Lee", "when": "trick"}, {"seat": 3, "name": "Pat", "when": "trick"}]
        trick_no = len(room.round.history)
        while len(room.round.history) == trick_no:
            assert room.seats[1].is_bot and room.seats[3].is_bot
            await t.step()
        assert room.seats[1].user_id == lee and room.seats[3].user_id == pat
        assert room.seats[1].joined_round == room.seats[3].joined_round == room.game.round_no
        assert cl.adopted[1] is room.seats[1] and cp.adopted[1] is room.seats[3]
        assert lee not in env.mm.joining and pat not in env.mm.joining
    run(go())


# ------------------------------------------------------ the account's name
def test_ws_a_rename_on_an_open_socket_names_the_queued_seat(wsenv):
    srv, store, client, clock = wsenv
    _uid, headers = _user(store, "rename-queue", "Old Name")
    with client.websocket_connect("/ws", headers=headers) as a:
        assert client.patch("/api/me", json={"display_name": "Newname"},
                            headers=headers).status_code == 200
        a.send_json({"type": "queue_join", "name": "Stale"})
        _drain(a, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        started = _drain(a, "match_started", tries=40)
        state = _drain(a, "state", tries=80)
        assert srv.rooms[started["room"]].seats[0].name == "Newname"
        assert state["players"][0]["name"] == "Newname"


def test_ws_a_signed_in_create_room_takes_the_account_name_not_the_sent_one(wsenv):
    srv, store, client, clock = wsenv
    _uid, headers = _user(store, "named", "Alex Smith")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "create_room", "name": "Sarah"})
        room = _drain(a, "room")
        assert room["players"][0]["name"] == "Alex"
    with client.websocket_connect("/ws") as g:
        g.send_json({"type": "create_room", "name": "Sarah"})
        assert _drain(g, "room")["players"][0]["name"] == "Sarah"


def test_ws_a_rename_while_seated_renames_the_seat_in_the_next_frame(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    async def paused_deal(room):
        await asyncio.Future()

    # Isolate rename delivery from the deal's unrelated state broadcasts.
    monkeypatch.setattr(srv, "run_deal", paused_deal)
    _uid, headers = _user(store, "seated", "Old Name")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "create_room"})
        code = _drain(a, "room")["room"]
        assert client.patch("/api/me", json={"display_name": "Lobbyname"},
                            headers=headers).status_code == 200
        assert _drain(a, "room")["players"][0]["name"] == "Lobbyname"
        a.send_json({"type": "start_game"})
        _drain(a, "state", tries=80)
        assert client.patch("/api/me", json={"display_name": "Gamename"},
                            headers=headers).status_code == 200
        assert srv.rooms[code].seats[0].name == "Gamename"
        assert _drain(a, "state", tries=80)["players"][0]["name"] == "Gamename"
        log = (srv.LOG_DIR / f"{code}.jsonl").read_text()
        assert '"e": "seat_renamed"' in log


# ------------------------------------------------------------ guests
def _guest(env, uid, device, name=None):
    conn = FakeConn(uid, name or f"G{-uid}")
    conn.device = device
    env.conns[uid] = conn
    env.mm.connect(conn)
    return conn


def test_a_guest_queues_at_1000_and_one_device_never_sits_twice_at_a_table():
    async def go():
        env = Env()
        env.player(1, rating=1600).device = DEVICE_A
        _guest(env, -1, DEVICE_A)                # the same device, signed out
        await env.join(1, rating=1600)
        await env.join(-1)
        assert env.mm._entry(-1).member_ratings == {-1: ratings.GUEST_RATING}
        assert env.mm.tables == {}               # the two places are one device's
        env.player(2).device = DEVICE_B
        await env.join(2)
        [t] = env.mm.tables.values()
        assert 2 in t.seats and (1 in t.seats) != (-1 in t.seats)
    run(go())


def test_a_pair_needs_two_devices():
    async def go():
        env = Env()
        env.player(1).device = DEVICE_A
        g = _guest(env, -1, DEVICE_A)
        await env.send(1, "party_create")
        code = env.conns[1].last("party")["code"]
        await env.send(-1, "party_join", code=code)
        assert g.last("error")["code"] == "same_device"
        other = _guest(env, -2, DEVICE_B)
        await env.send(-2, "party_join", code=code)
        assert other.last("party")["members"][1]["name"] == "G2"
        assert env.mm._party(1).members == [1, -2]
    run(go())


def test_an_open_table_holding_the_device_is_not_offered():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [7, "bot", "bot", "bot"])
        tables.tables["OPEN"]["seats"][0]["device"] = DEVICE_A
        _guest(env, -1, DEVICE_A)
        await env.join(-1)
        assert env.conns[-1].last("queue_state")["offer"] is None
        await env.send(-1, "queue_leave")
        _guest(env, -2, DEVICE_B)
        await env.join(-2)
        assert env.conns[-2].last("queue_state")["offer"]["room"] == "OPEN"
    run(go())


def test_ws_a_guest_with_a_device_key_queues(wsenv):
    srv, store, client, clock = wsenv
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "name": "Guesty"})
        state = _drain(g, "queue_state")
        assert state["queued"] is True and state["table"] is None
        assert srv.MATCHMAKER.entry_of.keys() == {-1}
    # a malformed key is no key
    with client.websocket_connect("/ws?device=short") as bad:
        bad.send_json({"type": "queue_join"})
        assert _drain(bad, "error")["code"] == "signed_in_only"


def test_ws_a_guest_and_an_account_share_a_table_and_start(wsenv):
    srv, store, client, clock = wsenv
    uid, headers = _user(store, "acct", "Acct Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a, \
            client.websocket_connect(f"/ws?device={DEVICE_B}") as g:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        g.send_json({"type": "queue_join", "name": "Guesty"})
        table = _drain(g, "queue_state")["table"]
        assert [s and s["name"] for s in table["seats"]] == ["Acct", None, "Guesty", None]
        a.send_json({"type": "table_start"})
        g.send_json({"type": "table_start"})
        seen_a = _until(a, "match_started")
        seen_g = _until(g, "match_started")
        assert "guest" not in seen_a[-1] and seen_g[-1]["guest"] is True
        room = srv.rooms[seen_g[-1]["room"]]
        state = _drain(g, "state", tries=80)
        human = [sd for sd in room.seats if not sd.is_bot]
        assert [(sd.user_id, sd.queue_id) for sd in human] == [(uid, uid), (None, -1)]
        assert state["guest"] is True and "guest" not in _drain(a, "state", tries=80)
        assert room.ratings.present == {0: uid}
        frames = seen_a + seen_g + [state]
        assert DEVICE_A not in str(frames) and DEVICE_B not in str(frames)
        log = (srv.LOG_DIR / f"{room.code}.jsonl").read_text()
        assert DEVICE_A not in log and DEVICE_B not in log and '"user_ids"' not in log


def test_ws_a_guest_comes_back_to_its_matched_seat_by_token_only(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "name": "Guesty"})
        _drain(g, "queue_state")
        g.send_json({"type": "queue_start_bots"})
        seen = _until(g, "match_started")
        code = seen[-1]["room"]
        token = next(m for m in seen if m["type"] == "resume")["token"]
    room = srv.rooms[code]
    with client.websocket_connect(f"/ws?device={DEVICE_B}") as other:
        other.send_json({"type": "join_room", "room": code, "name": "Guesty"})
        assert _drain(other, "error")["code"] in ("ranked_queue_only", "table_full",
                                                  "seat_unavailable")
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as back:
        back.send_json({"type": "join_room", "room": code, "token": token})
        state = _drain(back, "state", tries=80)
        assert state["you"] == 0 and room.seats[0].connected
        assert room.seats[0].queue_id == -1 and room.seats[0].user_id is None


def test_ws_the_same_device_gets_the_same_guest_id_after_a_reconnect(wsenv):
    srv, store, client, clock = wsenv
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join"})
        assert _drain(g, "queue_state")["queued"] is True
    with client.websocket_connect(f"/ws?device={DEVICE_B}") as other:
        other.send_json({"type": "queue_join"})
        _drain(other, "queue_state")
        with client.websocket_connect(f"/ws?device={DEVICE_A}") as again:
            assert _drain(again, "queue_state")["queued"] is True   # its entry, back
            assert srv.MATCHMAKER.conns[-1].ws is not None
            assert srv.guest_queue_id(DEVICE_A) == -1 and srv.guest_queue_id(DEVICE_B) == -2


def test_ws_one_device_is_refused_a_second_seat_at_a_ranked_table(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    host, host_headers = _ranked_host(srv, store, client, monkeypatch)
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=host_headers) as h, \
            client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        code, room = _start_ranked(srv, h)
        # a guest on the device of an account's seat there is that account
        # signed out: it is told to sign in, never seated a second time
        g.send_json({"type": "join_room", "room": code, "name": "Guesty", "seat": 2})
        assert _drain(g, "error")["code"] == "ranked_queue_only"
        assert room.pending_joins == {}

        class Sock:
            device = DEVICE_A
        assert client.portal.call(srv.join_open_table, code, 2, -1, "Guesty", Sock()) \
            == "same_device"
        assert client.portal.call(srv.join_pair_open_table, code, [1, 3], [-1, -2],
                                  ["G1", "G2"], [Sock(), Sock()], -1) == "same_device"
        assert room.pending_joins == {}


def test_ws_a_guest_who_joins_then_leaves_gets_the_cooldown(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    host, host_headers = _ranked_host(srv, store, client, monkeypatch)
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect(f"/ws?device={DEVICE_B}") as g:
        code, room = _start_ranked(srv, h)
        g.send_json({"type": "join_room", "room": code, "name": "Guesty", "seat": 2})
        assert _drain(g, "match_started")["guest"] is True
        g.send_json({"type": "leave_room"})
        _drain(g, "left")
        assert srv.MATCHMAKER.cooldowns[-1] > clock()
        g.send_json({"type": "queue_join"})
        err = _drain(g, "error")
        assert err["code"] == "cooldown" and err["cooldown_until"] > clock()
    # a guest seated mid-round who leaves it: the cooldown, and no carried cap
    caps = set(ratings.CARRIED_CAPS)
    srv._joined_leave_penalty(room, None, -5)
    assert srv.MATCHMAKER.cooldowns[-5] > clock() and ratings.CARRIED_CAPS == caps


# ------------------------------------------------- the move timer and one human
def _owes(srv, room, seat=0):
    async def check():
        async with room.lock:
            return (room.bot_task is None or room.bot_task.done()) and seat in srv._owing_seats(room)
    return check


def test_ws_one_human_at_a_matched_table_has_no_move_clock_until_a_second_sits(
        wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    t = {"v": 5000.0}
    monkeypatch.setattr(srv, "now", lambda: t["v"])
    _, host_headers = _ranked_host(srv, store, client, monkeypatch)
    friend, friend_headers = _user(store, "friend", "Friend")
    with client.websocket_connect("/ws", headers=host_headers) as h:
        code, room = _start_ranked(srv, h)
        assert room.matched and room.move_timer
        _wait_until(lambda: client.portal.call(_owes(srv, room)))

        async def frame():
            async with room.lock:
                await srv.broadcast(room)
                return srv.state_for(room, 0)
        state = client.portal.call(frame)
        assert state["players"][0]["turn_deadline"] is None
        assert room.seats[0].turn_started is None
        t["v"] += 10 * srv.MOVE_TIMER
        assert client.portal.call(srv.move_timer_tick, room) is False
        assert client.portal.call(_owes(srv, room)), "the bot decided for the lone player"
        assert room.seats[0].timeouts_in_row == 0

        with client.websocket_connect("/ws", headers=friend_headers) as f:
            async def due_seat():
                async with room.lock:
                    return next(s for s in (1, 2, 3) if srv._join_due(room, s))
            seat = client.portal.call(due_seat)
            f.send_json({"type": "join_room", "room": code, "seat": seat})
            _drain(f, "match_started")
            _wait_until(lambda: room.seats[seat].user_id == friend)
            state = client.portal.call(frame)
            # the clock starts fresh for the decision still owed
            assert room.seats[0].turn_started == t["v"]
            assert state["players"][0]["turn_deadline"] == srv.MOVE_TIMER
            t["v"] += srv.MOVE_TIMER + 1
            assert client.portal.call(srv.move_timer_tick, room) is True
            assert room.seats[0].timeouts_in_row == 1


# ------------------------------------------------- a guest signs in
def _next(ws, kind, pred, tries=80):
    """The first message of ``kind`` that satisfies ``pred``."""
    for _ in range(tries):
        m = _drain(ws, kind)
        if pred(m):
            return m
    raise AssertionError(f"no matching {kind}")


def _settled(ws):
    """Wait until the server has run this socket's connect."""
    ws.send_json({"type": "ping", "nonce": 1})
    _drain(ws, "pong")


def _guest_match(client, device=DEVICE_A):
    """A guest on ``device`` starts a matched game with bots: (room code, token)."""
    with client.websocket_connect(f"/ws?device={device}") as g:
        g.send_json({"type": "queue_join", "name": "Guesty"})
        _drain(g, "queue_state")
        g.send_json({"type": "queue_start_bots"})
        seen = _until(g, "match_started")
        token = next(m for m in seen if m["type"] == "resume")["token"]
        return seen[-1]["room"], token


def test_ws_a_guest_who_signs_in_takes_its_matched_seat_back_as_the_account(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, token = _guest_match(client)
    room = srv.rooms[code]
    assert room.ratings.kinds[0] == ratings.GUEST and room.ratings.present == {}
    round_no = room.game.round_no
    uid, headers = _user(store, "signer", "Acct Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        a.send_json({"type": "join_room", "room": code, "token": token})
        state = _drain(a, "state", tries=80)
        assert state["you"] == 0 and "guest" not in state
        seat = room.seats[0]
        assert (seat.user_id, seat.queue_id, seat.name) == (uid, uid, "Acct")
        assert seat.connected and srv._holds_seat(room, uid) and not srv._holds_seat(room, -1)
        # the round in play stays as it started: a guest seat, unrated for it
        assert room.game.round_no == round_no
        assert room.ratings.kinds[0] == ratings.GUEST and room.ratings.present == {}
        assert ratings.participants(room, room.ratings) == []


def test_ws_a_guest_seat_moves_only_to_an_account_signed_in_on_that_device(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, token = _guest_match(client)
    room = srv.rooms[code]
    _, headers = _user(store, "elsewhere", "Else Where")
    with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=headers) as a:
        a.send_json({"type": "join_room", "room": code, "token": token})
        assert _drain(a, "error")["code"] in ("table_full", "seat_unavailable")
    assert room.seats[0].user_id is None and room.seats[0].queue_id == -1


def test_ws_a_signed_out_account_cannot_take_its_matched_seat_as_a_guest(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    uid, headers = _user(store, "leaver", "Lea Ver")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        seen = _until(a, "match_started")
        code = seen[-1]["room"]
        token = next(m for m in seen if m["type"] == "resume")["token"]
    room = srv.rooms[code]
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "join_room", "room": code, "token": token, "name": "Lea"})
        assert _drain(g, "error")["code"] == "ranked_queue_only"
    seat = room.seats[0]
    assert (seat.user_id, seat.queue_id) == (uid, uid) and not seat.connected
    assert room.pending_joins == {}


def test_ws_a_guest_who_signs_in_at_a_waiting_table_leaves_it_and_the_table_is_told(wsenv):
    srv, store, client, clock = wsenv
    other, other_headers = _user(store, "other", "Other Person")
    with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=other_headers) as b:
        with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
            g.send_json({"type": "queue_join", "name": "Guesty"})
            _drain(g, "queue_state")
            b.send_json({"type": "queue_join"})
            _next(b, "queue_state", lambda m: m["table"] is not None)
            assert srv.MATCHMAKER.entry_of.keys() == {-1, other}
        uid, headers = _user(store, "signer", "Acct Person")
        with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
            _settled(a)
            # the guest's place is gone; the account holds nothing until Play
            assert srv.MATCHMAKER.entry_of.keys() == {other}
            assert srv.MATCHMAKER.tables == {}
            alone = _next(b, "queue_state", lambda m: m["table"] is None)
            assert alone["queued"] is True
            assert srv.MATCHMAKER.count() == 1
            a.send_json({"type": "queue_join"})
            table = _next(a, "queue_state", lambda m: m["table"] is not None)["table"]
            assert srv.MATCHMAKER.entry_of.keys() == {other, uid}
            assert sorted(s["name"] for s in table["seats"] if s) == ["Acct", "Other"]


def test_ws_a_guest_who_signs_in_while_searching_alone_leaves_the_queue(wsenv):
    srv, store, client, clock = wsenv
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "name": "Guesty"})
        _drain(g, "queue_state")
    uid, headers = _user(store, "signer", "Acct Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        _settled(a)
        assert srv.MATCHMAKER.entry_of == {} and srv.MATCHMAKER.count() == 0
        a.send_json({"type": "queue_join"})
        assert _drain(a, "queue_state")["queued"] is True
        assert srv.MATCHMAKER.entry_of.keys() == {uid}


def test_ws_a_guest_who_signs_in_in_a_pair_ends_the_pair(wsenv):
    srv, store, client, clock = wsenv
    friend, friend_headers = _user(store, "friend", "Friend Person")
    with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=friend_headers) as f:
        with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
            f.send_json({"type": "party_create"})
            code = _drain(f, "party")["code"]
            g.send_json({"type": "party_join", "code": code, "name": "Guesty"})
            _drain(g, "party")
            f.send_json({"type": "queue_join"})
            assert _next(f, "queue_state", lambda m: m["queued"])["queued"] is True
            assert srv.MATCHMAKER.entry_of.keys() == {friend, -1}
        _, headers = _user(store, "signer", "Acct Person")
        with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
            _settled(a)
            assert _next(f, "queue_state", lambda m: not m["queued"])["queued"] is False
            closed = _drain(f, "party_closed")
            assert closed["reason"] == "left" and closed["you"] is False
            assert srv.MATCHMAKER.parties == {} and srv.MATCHMAKER.party_of == {}
            assert srv.MATCHMAKER.entry_of == {} and srv.MATCHMAKER.count() == 0


def test_ws_a_guest_reconnecting_as_a_guest_keeps_its_waiting_table_seat(wsenv):
    srv, store, client, clock = wsenv
    other, other_headers = _user(store, "other", "Other Person")
    with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=other_headers) as b:
        with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
            g.send_json({"type": "queue_join", "name": "Guesty"})
            _drain(g, "queue_state")
            b.send_json({"type": "queue_join"})
            _next(b, "queue_state", lambda m: m["table"] is not None)
        with client.websocket_connect(f"/ws?device={DEVICE_A}") as again:
            assert _next(again, "queue_state", lambda m: m["table"] is not None)["queued"]
            assert srv.MATCHMAKER.entry_of.keys() == {-1, other}
            [t] = srv.MATCHMAKER.tables.values()
            assert -1 in t.seats and other in t.seats


def _same_device_lobby(srv, store, client):
    """A created casual room: its host signed in on DEVICE_A, a guest on the
    same device in seat 1 (a joiner sits as the host's partner, so the host
    moves it there)."""
    _, headers = _user(store, "host", "Host Person")
    host = client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers)
    guest = client.websocket_connect(f"/ws?device={DEVICE_A}")
    h, g = host.__enter__(), guest.__enter__()
    h.send_json({"type": "create_room", "name": "Host"})
    code = _drain(h, "room")["room"]
    g.send_json({"type": "join_room", "room": code, "name": "Guesty"})
    _drain(g, "room")
    h.send_json({"type": "swap_seats", "a": 2, "b": 1})
    _next(g, "room", lambda m: m["you"] == 1)
    _next(h, "room", lambda m: [p["seat"] for p in m["players"]] == [0, 1])
    room = srv.rooms[code]
    assert [sd.device for sd in room.seats[:2]] == [DEVICE_A, DEVICE_A]
    return (host, guest), h, g, room


def test_ws_ranked_is_refused_with_two_players_on_one_device(wsenv):
    srv, store, client, clock = wsenv
    ctx, h, g, room = _same_device_lobby(srv, store, client)
    try:
        h.send_json({"type": "set_ranked", "on": True})
        err = _drain(h, "error")
        assert err["code"] == "same_device" and "one device" in err["message"]
        assert room.ranked is False and room.move_timer is False
    finally:
        for c in reversed(ctx):
            c.__exit__(None, None, None)


def test_a_ranked_start_with_two_players_on_one_device_is_refused(wsenv):
    srv, store, client, clock = wsenv
    ctx, h, g, room = _same_device_lobby(srv, store, client)
    try:
        room.seats[1].device = DEVICE_B
        h.send_json({"type": "set_ranked", "on": True})
        _next(h, "room", lambda m: m.get("ranked") is True)
        room.seats[1].device = DEVICE_A       # however the seat came to share it
        h.send_json({"type": "start_game"})
        assert _drain(h, "error")["code"] == "same_device"
        assert room.game is None and room.ratings is None
    finally:
        for c in reversed(ctx):
            c.__exit__(None, None, None)
    # a queue-matched room is held to the same rule at its start
    matched = srv.Room(code="SAMEDV", matched=True, move_timer=True)
    matched.seats = [srv.Seat(name="A", user_id=7, queue_id=7, device=DEVICE_A),
                     srv.Seat(name="Bot 1", is_bot=True),
                     srv.Seat(name="G", queue_id=-3, device=DEVICE_A),
                     srv.Seat(name="Bot 3", is_bot=True)]
    with pytest.raises(srv.SameDevice):
        client.portal.call(srv.handle_action, matched, 0, {"type": "start_game"})
    assert matched.game is None


# ------------------------------------------------- queue truth per socket
def test_every_socket_of_an_account_shows_the_search_the_server_holds():
    async def go():
        env = Env()
        await env.join(1)
        other = FakeConn(1, "P1")                   # the same account in another tab
        env.mm.connect(other)
        held = other.last("queue_state")
        assert held["queued"] is True and held["elsewhere"] is True and held["table"] is None
        await env.join(2)                           # a table forms on the first socket
        assert env.conns[1].last("queue_state")["table"] is not None
        assert other.last("queue_state")["elsewhere"] is True
        await env.send(1, "queue_leave")
        assert env.conns[1].last("queue_state")["queued"] is False
        assert other.last("queue_state")["queued"] is False
    run(go())


def test_a_search_dropped_while_its_socket_is_away_clears_the_accounts_other_tabs():
    async def go():
        env = Env()
        await env.join(1)
        other = FakeConn(1, "P1")
        env.mm.connect(other)
        env.mm.disconnect(env.conns[1])             # the searching tab goes away
        env.clock.advance(mm.AWAY_SECS + 1)
        await env.mm.pump()
        assert env.mm._entry(1) is None
        assert other.last("queue_state")["queued"] is False
    run(go())


def test_a_match_start_clears_the_accounts_other_tabs():
    async def go():
        env = Env()
        await env.join(1)
        other = FakeConn(1, "P1")
        env.mm.connect(other)
        await env.send(1, "queue_start_bots")
        assert env.started and other.last("queue_state")["queued"] is False
    run(go())


def test_queue_status_answers_each_socket_with_what_the_server_holds_for_it():
    async def go():
        env = Env()
        await env.join(1)
        other = FakeConn(1, "P1")
        env.mm.connect(other)
        other.clear()
        await env.mm.handle(env.conns[1], {"type": "queue_status"}, 1)
        mine = env.conns[1].last("queue_state")
        assert mine["queued"] is True and "elsewhere" not in mine
        await env.mm.handle(other, {"type": "queue_status"}, 1)
        assert other.last("queue_state")["elsewhere"] is True
        assert env.mm.conns[1] is env.conns[1]      # asking never takes the entry over
        nobody = FakeConn(None, "")
        env.mm.connect(nobody)
        await env.mm.handle(nobody, {"type": "queue_status"}, None)
        assert nobody.last("queue_state")["queued"] is False and not nobody.of("error")
        lone = env.player(3)
        await env.send(3, "queue_status")
        assert lone.last("queue_state")["queued"] is False
    run(go())


def test_queue_status_for_a_guest_and_from_a_seated_socket():
    async def go():
        env = Env()
        guest = FakeConn(-4, "Guest")
        env.conns[-4] = guest
        env.mm.connect(guest)
        await env.send(-4, "queue_join")
        guest.clear()
        await env.send(-4, "queue_status")
        assert guest.last("queue_state")["queued"] is True
        tab = FakeConn(-4, "Guest")
        env.mm.connect(tab)
        await env.mm.handle(tab, {"type": "queue_status"}, -4)
        assert tab.last("queue_state")["elsewhere"] is True
        await env.send(-4, "queue_start_bots")      # seated in a room now
        assert tab.last("queue_state")["queued"] is False
        await env.send(-4, "queue_status")
        assert guest.last("queue_state")["queued"] is False and not guest.of("error")
    run(go())


def test_a_new_socket_from_the_same_device_takes_the_search_over():
    async def go():
        env = Env()
        first = FakeConn(1, "P1")
        first.device = DEVICE_A
        env.conns[1] = first
        env.mm.connect(first)
        await env.send(1, "queue_join")
        # the page reconnects while the server still thinks the old socket is open
        again = FakeConn(1, "P1")
        again.device = DEVICE_A
        env.mm.connect(again)
        assert env.mm.conns[1] is again
        state = again.last("queue_state")
        assert state["queued"] is True and "elsewhere" not in state
        assert any(m.get("replaced") for m in first.of("queue_state"))
        # another device of the account does not take it
        phone = FakeConn(1, "P1")
        phone.device = DEVICE_B
        env.mm.connect(phone)
        assert env.mm.conns[1] is again and phone.last("queue_state")["elsewhere"] is True
    run(go())


def test_queue_events_are_logged_by_kind_without_identity():
    import logging

    class Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    grab = Grab()
    mm.qlog.addHandler(grab)
    try:
        async def go():
            env = Env()
            await env.join(1234567, name=None)
            guest = FakeConn(-9, "Secret Name")
            env.conns[-9] = guest
            env.mm.connect(guest)
            await env.send(-9, "queue_join")
            await env.send(1234567, "queue_leave")
            await env.send(-9, "queue_start_bots")
        run(go())
    finally:
        mm.qlog.removeHandler(grab)
    import json
    recs = [json.loads(line) for line in grab.lines]
    assert [(r["queue"], r.get("who"), r.get("reason")) for r in recs] == [
        ("join", "account", None), ("join", "guest", None), ("leave", "account", "leave"),
        ("leave", "guest", "bots"), ("start", None, None)]
    assert all("queued" in r for r in recs) and recs[2]["wait"] >= 0
    text = "\n".join(grab.lines)
    assert "1234567" not in text and "Secret" not in text and "-9" not in text


def test_a_queue_writer_that_failed_once_delivers_later_messages():
    class FlakyWs:
        def __init__(self):
            self.sent: list[dict] = []
            self.fail = True

        async def send_json(self, payload):
            if self.fail:
                self.fail = False
                raise RuntimeError("transient")
            self.sent.append(payload)

    async def go():
        ws = FlakyWs()
        c = mm.Conn(ws, 1, "P1")
        c.push({"type": "queue_count", "count": 1})
        for _ in range(5):
            await asyncio.sleep(0)
        c.push({"type": "queue_state", "queued": False, "count": 0})
        for _ in range(5):
            await asyncio.sleep(0)
        assert ws.sent == [{"type": "queue_state", "queued": False, "count": 0}]
    run(go())


def test_ws_two_sockets_of_one_account_both_see_the_true_search(wsenv):
    srv, store, client, clock = wsenv
    _, headers = _user(store, "twotabs", "Two Tabs")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a, \
            client.websocket_connect(f"/ws?device={DEVICE_B}", headers=headers) as b:
        _settled(a)
        _settled(b)
        a.send_json({"type": "queue_join"})
        assert _drain(a, "queue_state")["queued"] is True
        held = _drain(b, "queue_state")
        assert held["queued"] is True and held["elsewhere"] is True
        b.send_json({"type": "queue_status"})
        assert _drain(b, "queue_state")["elsewhere"] is True
        a.send_json({"type": "queue_leave"})
        assert _drain(a, "queue_state")["queued"] is False
        assert _drain(b, "queue_state")["queued"] is False
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_status", "name": "Guesty"})
        assert _drain(g, "queue_state")["queued"] is False


# ------------------------------------------ created rooms: Ranked, Allow joiners
def test_ws_ranked_shows_once_a_signed_in_player_sits_and_goes_off_when_they_leave(wsenv):
    srv, store, client, clock = wsenv
    _, headers = _user(store, "friend", "Friend Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as h:
        h.send_json({"type": "create_room", "name": "Host"})
        first = _drain(h, "room")
        code = first["room"]
        assert "rankable" not in first
        with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=headers) as f:
            f.send_json({"type": "join_room", "room": code, "name": "x"})
            _drain(f, "room")
            assert _next(h, "room", lambda m: len(m["players"]) == 2)["rankable"] is True
            h.send_json({"type": "set_ranked", "on": True})
            assert _next(h, "room", lambda m: m.get("ranked") is True)["allow_joiners"] is True
            f.send_json({"type": "leave_room"})
            st = _next(h, "room", lambda m: len(m["players"]) == 1)
        assert "ranked" not in st and "rankable" not in st
        assert srv.rooms[code].ranked is False


def test_ws_allow_joiners_set_in_a_ranked_rooms_lobby_opens_the_table_in_play(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    uid, headers = _user(store, "host", "Host Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as h:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        room = srv.rooms[code]
        h.send_json({"type": "set_ranked", "on": True})
        _next(h, "room", lambda m: m.get("ranked") is True)
        h.send_json({"type": "allow_joiners", "on": True})
        assert _next(h, "room", lambda m: m.get("allow_joiners") is True)["ranked"] is True
        h.send_json({"type": "start_game"})
        assert _drain(h, "state", tries=400)["allow_joiners"] is True
        assert room.seats[0].queue_id == uid
        [view] = [t for t in srv.open_tables() if t["code"] == code]
        assert [s["open"] for s in view["seats"]] == [False, True, True, True]
        assert view["seats"][0]["queue_id"] == uid
        # switched off at the table, as at a queue-matched one
        h.send_json({"type": "allow_joiners", "on": False})
        # the reply queues behind the deal's state frames (about one per card)
        _next(h, "state", lambda m: m.get("allow_joiners") is False, tries=400)
        assert not [t for t in srv.open_tables() if t["code"] == code]


def test_ws_a_ranked_room_left_with_joiners_off_is_not_an_open_table(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _, headers = _user(store, "host", "Host Person")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as h:
        h.send_json({"type": "create_room", "name": "Host"})
        code = _drain(h, "room")["room"]
        h.send_json({"type": "set_ranked", "on": True})
        _next(h, "room", lambda m: m.get("ranked") is True)
        h.send_json({"type": "allow_joiners", "on": False})
        _next(h, "room", lambda m: m.get("allow_joiners") is False)
        h.send_json({"type": "start_game"})
        assert _drain(h, "state", tries=400)["allow_joiners"] is False
        assert not [t for t in srv.open_tables() if t["code"] == code]


# ------------------------------------- signed out while the account plays ranked
def _account_match(srv, store, client, device=DEVICE_A):
    """An account on ``device`` starts a ranked game with bots and its socket
    closes (a sign-out): (room code, resume token)."""
    _, headers = _user(store, "leaver", "Lea Ver")
    with client.websocket_connect(f"/ws?device={device}", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        seen = _until(a, "match_started")
        return seen[-1]["room"], next(m for m in seen if m["type"] == "resume")["token"]


def test_ws_the_signed_out_guest_cannot_queue_while_its_accounts_game_is_in_play(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, _ = _account_match(srv, store, client)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        for kind in ("queue_join", "party_create"):
            g.send_json({"type": kind, "name": "Lea"})
            err = _drain(g, "error")
            assert err == {"type": "error", "code": "account_in_game",
                           "message": "Sign in again to return to your game."}
    assert srv.MATCHMAKER.entry_of == {}
    # another device's guest queues as ever
    with client.websocket_connect(f"/ws?device={DEVICE_B}") as other:
        other.send_json({"type": "queue_join", "name": "Other"})
        assert _drain(other, "queue_state")["queued"]


def test_ws_the_signed_out_guest_asking_for_the_seat_without_a_token_is_told_to_sign_in(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, _ = _account_match(srv, store, client)
    room = srv.rooms[code]
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "join_room", "room": code, "name": "Player"})
        assert _drain(g, "error")["code"] == "ranked_queue_only"
    assert room.pending_joins == {} and [s.is_bot for s in room.seats] == [False, True, True, True]


# ------------------------------------------------ joined seats and guests in frames
def test_a_seat_joined_this_round_says_so_until_the_round_ends(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    t = OpenRoom(srv, [host, "bot", "bot", "bot"])
    t.first_round()
    room = t.room
    assert srv.state_for(room, 0)["joined_round"] is False
    room.seats[2].joined_round = room.game.round_no
    room.seats[2].is_bot = False
    assert srv.state_for(room, 2)["joined_round"] is True
    assert srv.state_for(room, 0)["joined_round"] is False
    room.round.phase = "round_end"
    assert srv.state_for(room, 2)["joined_round"] is False


def test_every_seat_without_an_account_at_a_matched_table_is_a_guest(otenv, monkeypatch):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    t = OpenRoom(srv, [host, "bot", "bot", "bot"])
    t.first_round()
    room = t.room
    room.seats[1] = srv.Seat(name="G", queue_id=-4, connected=True)
    # whether or not the room's rounds are rated
    monkeypatch.setattr(srv.ratings, "ranked", lambda r: False)
    assert srv.state_for(room, 1)["guest"] is True
    assert "guest" not in srv.state_for(room, 0)
    assert "guest" not in srv.state_for(room, 2)
    room.matched = False
    assert "guest" not in srv.state_for(room, 1)


def test_review_signed_out_created_ranked_game_blocks_guest_queue(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    async def paused_deal(room):
        await asyncio.Future()
    monkeypatch.setattr(srv, "run_deal", paused_deal)
    _, headers = _user(store, "review-created", "Host")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as h:
        h.send_json({"type": "create_room"})
        code = _drain(h, "room")["room"]
        h.send_json({"type": "set_ranked", "on": True})
        _next(h, "room", lambda m: m.get("ranked") is True)
        h.send_json({"type": "start_game"})
        _drain(h, "state", tries=400)
    assert srv.rooms[code].ranked and not srv.rooms[code].matched
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "name": "Guest"})
        for _ in range(40):
            msg = g.receive_json()
            if msg["type"] in ("queue_state", "error"):
                assert msg.get("code") == "account_in_game", msg
                break
        else:
            raise AssertionError("no queue response")


def _created_game(srv, store, client, monkeypatch, ranked=True, device=DEVICE_A):
    """An account on ``device`` creates a room (Ranked or not), starts it with
    bots and its socket closes (a sign-out): the room code."""
    async def paused_deal(room):
        await asyncio.Future()
    monkeypatch.setattr(srv, "run_deal", paused_deal)
    _, headers = _user(store, "creator", "Cre Ator")
    with client.websocket_connect(f"/ws?device={device}", headers=headers) as h:
        h.send_json({"type": "create_room"})
        code = _drain(h, "room")["room"]
        if ranked:
            h.send_json({"type": "set_ranked", "on": True})
            _next(h, "room", lambda m: m.get("ranked") is True)
        h.send_json({"type": "start_game"})
        _drain(h, "state", tries=400)
    room = srv.rooms[code]
    assert room.ranked is ranked and not room.matched and room.game is not None
    return code


def test_ws_the_signed_out_guest_cannot_queue_while_its_accounts_created_ranked_game_is_in_play(
        wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _created_game(srv, store, client, monkeypatch)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        for kind in sorted(srv.QUEUE_STARTS):
            g.send_json({"type": kind, "name": "Cre"})
            err = _drain(g, "error")
            assert err == {"type": "error", "code": "account_in_game",
                           "message": "Sign in again to return to your game."}, kind
    assert srv.MATCHMAKER.entry_of == {}
    with client.websocket_connect(f"/ws?device={DEVICE_B}") as other:
        other.send_json({"type": "queue_join", "name": "Other"})
        assert _drain(other, "queue_state")["queued"]


def test_ws_the_signed_out_guest_asking_for_its_created_ranked_seat_without_a_token_is_told_to_sign_in(
        wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    code = _created_game(srv, store, client, monkeypatch)
    room = srv.rooms[code]
    seats = [(s.is_bot, s.user_id) for s in room.seats]
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        for name in ("Player", "Cre Ator"):
            g.send_json({"type": "join_room", "room": code, "name": name})
            assert _drain(g, "error")["code"] == "ranked_queue_only"
    assert room.pending_joins == {} and [(s.is_bot, s.user_id) for s in room.seats] == seats


def test_ws_a_casual_created_game_does_not_hold_the_signed_out_guest(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _created_game(srv, store, client, monkeypatch, ranked=False)
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "name": "Cre"})
        assert _drain(g, "queue_state")["queued"]


def test_live_ranked_room_excludes_a_finished_or_closing_game(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    code = _created_game(srv, store, client, monkeypatch)
    room = srv.rooms[code]
    assert srv._live_ranked_room(room) and srv._account_game_on(DEVICE_A) is room
    for attr in ("aborted", "closing"):
        setattr(room, attr, True)
        assert not srv._live_ranked_room(room) and srv._account_game_on(DEVICE_A) is None
        setattr(room, attr, False)
    room.game.game_over = True
    assert not srv._live_ranked_room(room)
    room.game.game_over = False
    room.ranked = False
    assert not srv._live_ranked_room(room)


def test_ws_a_joined_seat_reconnecting_gets_joined_round_in_its_state_frames(wsenv, monkeypatch):
    """A reload sends no match_started: the reconnected socket's state
    frames alone say the round in play was joined mid-way."""
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    host, host_headers = _user(store, "host", "Host")
    alice, alice_headers = _user(store, "alice", "Alice")
    with client.websocket_connect("/ws", headers=host_headers) as h:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        code = _drain(h, "match_started")["room"]
        room = srv.rooms[code]
        room.seats[0].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        with client.websocket_connect("/ws", headers=alice_headers) as a:
            a.send_json({"type": "queue_join"})
            assert _drain(a, "queue_state")["offer"]["room"] == code
            a.send_json({"type": "open_table_join", "room": code, "seat": 2})
            assert _drain(a, "match_started")["joining"] is True
            _wait_until(lambda: room.seats[2].user_id == alice)
        round_no = room.game.round_no
        assert room.seats[2].joined_round == round_no and room.seats[2].user_id == alice
        with client.websocket_connect("/ws", headers=alice_headers) as a2:
            a2.send_json({"type": "join_room", "room": code, "name": "Alice"})
            seen = []
            for _ in range(80):
                msg = a2.receive_json()
                seen.append(msg["type"])
                if msg["type"] == "state" and msg.get("room") == code:
                    break
            assert "match_started" not in seen
            assert msg["type"] == "state" and msg["you"] == 2
            assert room.game.round_no == round_no and msg["phase"] != "round_end"
            assert msg["joined_round"] is True


def test_ws_an_account_playing_ranked_cannot_press_play_on_a_second_device(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _, headers = _user(store, "twodev", "Two Dev")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        a.send_json({"type": "queue_join"})
        _drain(a, "queue_state")
        a.send_json({"type": "queue_start_bots"})
        _until(a, "match_started")
        _drain(a, "state", tries=80)
        with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=headers) as b:
            b.send_json({"type": "queue_join"})
            assert _drain(b, "error")["code"] == "account_in_game"
            assert srv.MATCHMAKER.entry_of == {}
            # once the account leaves its seat, the other device may queue
            a.send_json({"type": "leave_room"})
            _drain(a, "left", tries=400)
            b.send_json({"type": "queue_join"})
            assert _drain(b, "queue_state")["queued"] is True


# ------------------------------------------------------- the unified table
def test_a_single_at_a_waiting_table_moves_to_an_empty_seat_and_the_table_is_told():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 2, None]
        await env.send(2, "table_move", seat=1)
        assert t.seats == [1, 2, None, None]
        assert env.conns[2].last("queue_state")["table"]["you"] == 1
        assert env.conns[1].last("queue_state")["table"]["seats"][1]["name"] == "P2"
        assert env.conns[1].last("table_moved") == {"type": "table_moved", "name": "P2",
                                                    "seat": 1, "your_team": False}
        assert env.conns[2].last("table_moved") is None
        await env.send(2, "table_move", seat=2)
        assert env.conns[1].last("table_moved")["your_team"] is True
        await env.join(3)                    # an arrival takes the next free seat in order
        assert t.seats == [1, 3, 2, None]
    run(go())


def test_a_table_move_is_refused_with_a_code_for_a_taken_seat_after_start_for_a_duo_and_alone():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "table_move", seat=1)
        assert env.conns[1].last("error")["code"] == "not_seated"
        await env.join(2)
        (t,) = env.mm.tables.values()
        for seat, code in ((0, "seat_taken"), (7, "bad_seat"), (True, "bad_seat"), (None, "bad_seat")):
            await env.send(2, "table_move", seat=seat)
            assert env.conns[2].last("error")["code"] == code
        await env.send(2, "table_start")
        await env.send(2, "table_move", seat=3)
        assert env.conns[2].last("error")["code"] == "already_ready"
        assert t.seats == [1, None, 2, None]

        env = Env()
        await env.join(1)
        await env.pair(2, 3)
        await env.send(2, "queue_join")
        (t,) = env.mm.tables.values()
        await env.send(2, "table_move", seat=2)
        assert env.conns[2].last("error")["code"] == "pair_seats_fixed"
        assert t.seats == [1, 2, None, 3]
    run(go())


def test_keep_looking_is_forgotten_on_the_next_play_but_a_table_left_stays_barred():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        tables.add("LEFT", [60, "bot", "bot", "bot"])
        env.mm.left_open_table(1, "LEFT")
        env.clock.advance(mm.JOIN_COOLDOWN_SECS + 1)
        await env.join(1)
        assert env.conns[1].last("queue_state")["offer"]["room"] == "OPEN"
        await env.send(1, "open_table_wait")
        await env.mm.tick()
        assert env.conns[1].last("queue_state")["offer"] is None
        await env.send(1, "queue_leave")
        await env.join(1)                    # a fresh Play: offered again
        assert env.conns[1].last("queue_state")["offer"]["room"] == "OPEN"
        await env.send(1, "open_table_wait")
        await env.send(1, "queue_leave")
        tables.tables.pop("OPEN")
        await env.join(1)                    # the left table is never offered
        assert env.conns[1].last("queue_state")["offer"] is None
    run(go())


def test_alone_with_wait_for_people_on_a_closed_socket_keeps_its_place_a_minute():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_wait_players")
        env.mm.disconnect(env.conns[1])
        env.clock.advance(mm.AWAY_SECS + 1)
        await env.mm.pump()
        assert env.mm._entry(1) is not None
        env.clock.advance(mm.WAIT_AWAY_SECS - mm.AWAY_SECS)
        await env.mm.pump()
        assert env.mm._entry(1) is None
    run(go())


def test_alone_with_the_switch_off_a_closed_socket_still_leaves_after_ten_seconds():
    async def go():
        env = Env()
        await env.join(1)
        env.mm.disconnect(env.conns[1])
        env.clock.advance(mm.AWAY_SECS + 1)
        await env.mm.pump()
        assert env.mm._entry(1) is None
    run(go())


def test_still_here_is_answered_by_table_here_and_asked_again_after_another_idle_spell():
    async def go():
        env = Env()
        for uid in (1, 2):
            await env.join(uid)
            await env.send(uid, "queue_wait_players")
        await env.send(1, "table_start")
        env.clock.advance(mm.TABLE_IDLE_SECS)
        await env.mm.pump()
        assert env.conns[2].last("queue_state")["still_here_until"] is not None
        await env.send(2, "table_here")
        assert env.conns[2].last("queue_state")["still_here_until"] is None
        env.clock.advance(mm.STILL_HERE_SECS + 1)
        await env.mm.pump()
        assert env.mm._entry(2) is not None and env.conns[2].last("queue_removed") is None
        env.clock.advance(mm.TABLE_IDLE_SECS - mm.STILL_HERE_SECS - 1)
        await env.mm.pump()
        assert env.conns[2].last("queue_state")["still_here_until"] == (
            env.clock.t + mm.STILL_HERE_SECS)
        await env.send(3, "table_here", conn=env.player(3))
        assert env.conns[3].last("error")["code"] == "not_seated"
    run(go())


def test_presence_counts_open_tables_their_people_and_the_queue_debounced_and_without_names():
    async def go():
        env = Env()
        tables = Tables(env)
        watcher = env.player(9)
        assert watcher.of("presence") == []           # all zero: nothing to say
        tables.add("OPEN", [50, "bot", 51, "bot"])
        await env.mm.pump()
        assert watcher.of("presence") == [{"type": "presence", "tables": 1, "playing": 2,
                                           "waiting": 0, "ranked": 1, "casual": 0}]
        await env.join(1)
        await env.mm.pump()                           # inside the debounce: held back
        assert len(watcher.of("presence")) == 1
        env.clock.advance(mm.COUNT_DEBOUNCE)
        await env.mm.pump()
        assert watcher.last("presence") == {"type": "presence", "tables": 1, "playing": 2,
                                            "waiting": 1, "ranked": 1, "casual": 0}
        env.clock.advance(mm.COUNT_DEBOUNCE)
        await env.mm.pump()                           # no change: no message
        assert len(watcher.of("presence")) == 2
        late = env.player(10)                         # a new lobby socket hears it at once
        assert late.last("presence")["waiting"] == 1
        assert "OPEN" not in str(watcher.sent) and "P50" not in str(watcher.of("presence"))
    run(go())


def test_ws_presence_counts_a_solo_ranked_game_and_its_connected_player(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _, headers = _user(store, "solo", "Solo")
    with client.websocket_connect("/ws", headers=headers) as h:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        room = srv.rooms[_drain(h, "match_started")["room"]]
        _wait_until(lambda: room.round is not None)
        assert srv.presence_counts() == (1, 1, 1, 0)
        with client.websocket_connect(f"/ws?device={DEVICE_B}") as w:
            assert _drain(w, "presence") == {"type": "presence", "tables": 1, "playing": 1,
                                             "waiting": 0, "ranked": 1, "casual": 0}
        room.allow_joiners = False                    # not joinable: not counted
        assert srv.presence_counts() == (0, 0, 0, 0)
        room.allow_joiners = True
    _wait_until(lambda: srv.presence_counts() == (0, 0, 0, 0))   # nobody connected


def test_a_start_sent_against_a_panel_that_changed_is_refused():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.join(1)
        shown = env.conns[1].last("queue_state")
        assert shown["offer"]["room"] == "OPEN"
        await env.join(2)                             # 1's panel turns into a waiting table
        now = env.conns[1].last("queue_state")
        assert now["table"] is not None and now["panel_seq"] > shown["panel_seq"]
        await env.send(1, "table_start", panel_seq=shown["panel_seq"])
        assert env.conns[1].last("error")["code"] == "panel_changed"
        (t,) = env.mm.tables.values()
        assert t.ready == set()
        env.clock.advance(1)
        await env.send(2, "table_move", seat=1)       # a re-render keeps the number
        assert env.conns[1].last("queue_state")["panel_seq"] == now["panel_seq"]
        await env.send(1, "table_start", panel_seq=now["panel_seq"])
        assert env.mm._entry(1).id in t.ready
    run(go())


def test_queue_events_reach_the_telemetry_sink_without_identity(tmp_path, monkeypatch):
    import json as _json
    from shengji.api import telemetry

    state_for = telemetry.state_for

    def state_with_numeric_session_id(conn):
        state = state_for(conn)
        state.sid = "dd33d4610318f128"
        return state

    monkeypatch.setattr(telemetry, "state_for", state_with_numeric_session_id)

    out = tmp_path / "telemetry"
    monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(out))

    async def go():
        env = Env()
        await env.join(101)
        await env.send(101, "queue_leave")
        await env.join(102)
        await env.send(102, "queue_start_bots")

        failing = Env()

        async def broken(match_id, slots, conns, **kw):
            raise RuntimeError("injected")
        failing.mm.start_room = broken
        await failing.join(103)
        await failing.join(104)
        await failing.send(103, "table_start")
        await failing.send(104, "table_start")
    run(go())
    rows = [_json.loads(line) for f in sorted(out.glob("ui-*.jsonl"))
            for line in f.read_text().splitlines()]
    assert {r["q"] for r in rows} == {"join", "leave", "start", "start_failed"}
    allowed = {"e", "q", "sid", "build", "ts", "who", "size", "wait", "table", "humans",
               "queued", "reason", "max_wait"}
    for r in rows:
        assert r["e"] == "queue" and set(r) <= allowed
    joins = [r for r in rows if r["q"] == "join"]
    assert all(r["who"] == "account" and "sid" in r for r in joins)
    identity_values = {101, 102, 103, 104, "101", "102", "103", "104",
                       "P101", "P102", "P103", "P104"}
    for row in rows:
        assert not identity_values.intersection(row.values())


def test_ws_the_first_joiner_of_a_game_started_alone_is_announced_once(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _, host_headers = _user(store, "host", "Host")
    _, alice_headers = _user(store, "alice", "Alice")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=alice_headers) as a:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        code = _drain(h, "match_started")["room"]
        room = srv.rooms[code]
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        assert code in [t["code"] for t in srv.open_tables()]     # joinable as ever
        a.send_json({"type": "queue_join"})
        offer = _drain(a, "queue_state")["offer"]
        a.send_json({"type": "open_table_join", "room": code, "seat": offer["pick"]})
        _drain(a, "match_started")
        note = _drain(h, "first_joiner", tries=400)
        assert note == {"type": "first_joiner", "name": "Alice", "seat": offer["pick"],
                        "move_secs": 60, "round_end": False}
        assert room.first_joiner_told
        log = (srv.LOG_DIR / f"{room.code}.jsonl").read_text()
        assert "first_joiner" not in log


# ---------------------------------------- modes, table chat, the relaxed join rule
def test_the_join_cooldown_is_one_minute_and_the_invite_copy_says_so():
    from shengji.api import server as srv
    assert mm.JOIN_COOLDOWN_SECS == 60.0
    assert srv.INVITE_REFUSALS["cooldown"].endswith("join again in 1 minute.")


def test_casual_entries_never_share_a_table_with_ranked_ones():
    async def go():
        env = Env()
        await env.join(1)                              # ranked: no mode is ranked
        await env.join(2, mode="casual")
        assert env.mm.tables == {}                     # alone in each mode
        assert env.conns[2].last("queue_state")["mode"] == "casual"
        assert env.conns[1].last("queue_state")["mode"] == "ranked"
        await env.join(3, mode="casual")
        await env.join(4, mode="ranked")
        by_mode = {t.mode: sorted(u for u in t.seats if u is not None)
                   for t in env.mm.tables.values()}
        assert by_mode == {"casual": [2, 3], "ranked": [1, 4]}
        await env.join(5, mode="casual")
        await env.join(6, mode="casual")               # four casual: that table starts
        assert env.modes == ["casual"]
        assert sorted(humans_of(env.started[0][1])) == [2, 3, 5, 6]
        await env.send(1, "table_start")
        await env.send(4, "table_start")
        assert env.modes == ["casual", "ranked"]
        assert sorted(humans_of(env.started[1][1])) == [1, 4]
    run(go())


def test_a_casual_entry_alone_starts_a_casual_game_with_bots():
    async def go():
        env = Env()
        await env.join(1, mode="casual")
        await env.send(1, "queue_start_bots")
        await env.join(2, mode="casual")
        env.clock.advance(mm.BOT_FILL_SECS + 1)
        await env.mm.tick()                            # its own timer
        assert env.modes == ["casual", "casual"]
        await env.send(3, "queue_join", conn=env.player(3), mode="speed")
        assert env.conns[3].last("error")["code"] == "bad_mode"
        assert env.mm._entry(3) is None
    run(go())


def test_open_table_offers_are_of_the_entrys_own_mode():
    async def go():
        env = Env()
        tables = Tables(env)
        tables.add("RANK", [50, "bot", "bot", "bot"])
        tables.add("CASU", [60, "bot", "bot", "bot"], mode="casual")
        await env.join(1)
        assert env.conns[1].last("queue_state")["offer"]["room"] == "RANK"
        await env.join(2, mode="casual")
        assert env.conns[2].last("queue_state")["offer"]["room"] == "CASU"
        # a casual searcher is never offered a ranked table, even the only one
        del tables.tables["CASU"]
        await env.mm.tick()
        assert env.conns[2].last("queue_state")["offer"] is None
        await env.send(2, "open_table_show", room="RANK")
        assert env.conns[2].last("error")["code"] == "table_closed"
        await env.send(2, "open_table_join", room="RANK", seat=1)
        assert env.conns[2].last("error")["code"] == "no_offer"
        assert tables.joins == []
    run(go())


def test_presence_splits_open_tables_into_ranked_and_casual():
    async def go():
        env = Env()
        tables = Tables(env)
        watcher = env.player(9)
        tables.add("RANK", [50, "bot", 51, "bot"])
        tables.add("CAS1", [60, "bot", "bot", "bot"], mode="casual")
        tables.add("CAS2", [70, "bot", "bot", "bot"], mode="casual")
        await env.mm.pump()
        assert watcher.last("presence") == {"type": "presence", "tables": 3, "playing": 4,
                                            "waiting": 0, "ranked": 1, "casual": 2}
        del tables.tables["CAS1"]
        env.clock.advance(mm.COUNT_DEBOUNCE)
        await env.mm.pump()
        assert watcher.last("presence")["casual"] == 1
    run(go())


def test_table_chat_reaches_everyone_at_the_waiting_table_and_carries_into_the_room(monkeypatch):
    from shengji.api import telemetry

    events = []
    monkeypatch.setattr(telemetry, "queue_event", lambda conn, ev, **f: events.append((ev, f)))
    records = []

    class Grab(__import__("logging").Handler):
        def emit(self, record):
            records.append(record.getMessage())

    grab = Grab()
    mm.qlog.addHandler(grab)
    try:
        async def go():
            env = Env()
            env.player(1)
            await env.send(1, "table_chat", text="anyone?")
            assert env.conns[1].last("error")["code"] == "not_seated"
            await env.join(1)
            await env.join(2)
            await env.send(2, "table_chat", text="  hi there  ")
            for uid in (1, 2):
                line = env.conns[uid].last("table_chat")
                assert {k: line[k] for k in ("id", "seat", "name", "text")} == {
                    "id": 1, "seat": 2, "name": "P2", "text": "hi there"}
            await env.send(1, "table_chat", text="   ")          # empty: nothing
            await env.send(1, "table_chat", text="x" * 500)
            assert env.conns[2].last("table_chat")["text"] == "x" * 300
            await env.join(3)                                    # sits: hears the log so far
            history = env.conns[3].last("table_chat_history")
            assert [m["text"] for m in history["messages"]] == ["hi there", "x" * 300]
            for uid in (1, 2, 3):
                await env.send(uid, "table_start")
            (chat,) = env.chats
            assert [(m["seat"], m["text"]) for m in chat] == [(2, "hi there"), (0, "x" * 300)]
        run(go())
    finally:
        mm.qlog.removeHandler(grab)
    assert records and not any("hi there" in r or "xxx" in r for r in records)
    assert not any("hi there" in str(f) for _, f in events)


def test_table_chat_is_rate_limited():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        for i in range(mm.CHAT_LIMIT[0]):
            await env.send(1, "table_chat", text=f"m{i}")
        assert env.conns[1].last("error") is None
        await env.send(1, "table_chat", text="one too many")
        assert env.conns[1].last("error")["code"] == "rate_limited"
        assert env.conns[2].last("table_chat")["text"] == f"m{mm.CHAT_LIMIT[0] - 1}"
        await env.send(2, "table_chat", text="still mine")   # per person
        assert env.conns[1].last("table_chat")["text"] == "still mine"
    run(go())


def test_a_lone_entry_chats_at_its_own_table_and_hears_it_back():
    async def go():
        env = Env()
        await env.join(1, allow_joiners=False)             # stays alone
        await env.send(1, "table_chat", text="  hello table  ")
        assert env.conns[1].last("error") is None
        line = env.conns[1].last("table_chat")
        assert line["table"] is None
        assert {k: line[k] for k in ("id", "seat", "name", "text")} == {
            "id": 1, "seat": 0, "name": "P1", "text": "hello table"}
        await env.send(1, "table_chat", text="x" * 500)
        assert env.conns[1].last("table_chat")["text"] == "x" * mm.CHAT_MAX_LEN
        assert env.conns[1].last("table_chat")["id"] == 2
        # a Duo alone: both hear it, the partner at seat 2
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        await env.send(4, "table_chat", text="duo line")
        for uid in (3, 4):
            assert env.conns[uid].last("table_chat")["seat"] == 2
        # back from reconnecting: the log so far
        conn = env.player(1)
        await env.send(1, "queue_join", conn=conn)
        history = conn.last("table_chat_history")
        assert history["table"] is None
        assert [m["text"] for m in history["messages"]] == ["hello table", "x" * mm.CHAT_MAX_LEN]
    run(go())


def test_a_lone_entrys_chat_merges_into_the_table_a_stranger_forms():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "table_chat", text="first")
        env.clock.advance(1.0)
        # a third entry waits alone for its code while the others chat
        await env.join(3, allow_joiners=False)
        await env.send(3, "table_chat", text="lone three")
        env.clock.advance(1.0)
        await env.send(1, "table_chat", text="second")
        env.clock.advance(1.0)
        await env.join(2)
        (t,) = env.mm.tables.values()
        assert t.seats.count(None) == 2 and 3 not in t.seats
        assert [(m["id"], m["seat"], m["text"]) for m in t.chat] == [
            (1, 0, "first"), (2, 0, "second")]
        for uid in (1, 2):
            history = env.conns[uid].last("table_chat_history")
            assert history["table"] == t.id
            assert [m["text"] for m in history["messages"]] == ["first", "second"]
        await env.send(2, "table_chat", text="third")
        assert env.conns[1].last("table_chat")["id"] == 3
        # it sits: its lines merge in time order, under ids after the table's
        await env.send(3, "table_allow_joiners", on=True)
        assert env.mm._entry(3).table_id == t.id and env.mm._entry(3).chat == []
        assert [(m["id"], m["text"]) for m in t.chat] == [
            (4, "first"), (5, "lone three"), (6, "second"), (7, "third")]
        assert t.chat[1]["seat"] == t.seats.index(3)
        for uid in (1, 2, 3):
            assert [m["text"] for m in env.conns[uid].last("table_chat_history")["messages"]] == [
                "first", "lone three", "second", "third"]
        for uid in (1, 2, 3):
            await env.send(uid, "table_start")
        (chat,) = env.chats
        assert [m["text"] for m in chat] == ["first", "lone three", "second", "third"]
        assert all(set(m) == {"id", "seat", "name", "text", "t"} for m in chat)
    run(go())


def test_a_merged_lone_chat_keeps_the_table_cap():
    async def go():
        env = Env()
        env.mm.chat_limiter = mm.accounts.RateLimiter(10 * mm.CHAT_KEEP, 60.0)
        await env.join(1, mode="casual", allow_joiners=False)
        for i in range(mm.CHAT_KEEP + 5):
            env.clock.advance(0.01)
            await env.send(1, "table_chat", text=f"a{i}")
        assert len(env.mm._entry(1).chat) == mm.CHAT_KEEP
        await env.join(2, mode="casual", allow_joiners=False)
        for i in range(10):
            env.clock.advance(0.01)
            await env.send(2, "table_chat", text=f"b{i}")
        await env.send(1, "table_allow_joiners", on=True)
        await env.send(2, "table_allow_joiners", on=True)
        (t,) = env.mm.tables.values()
        assert len(t.chat) == mm.CHAT_KEEP
        assert [m["text"] for m in t.chat] == (
            [f"a{i}" for i in range(15, mm.CHAT_KEEP + 5)] + [f"b{i}" for i in range(10)])
    run(go())


def test_a_code_joiner_hears_the_lone_hosts_chat():
    async def go():
        env = Env()
        await env.join(1, mode="casual", allow_joiners=False)
        await env.send(1, "table_chat", text="come sit")
        code = env.conns[1].last("queue_state")["code"]
        env.player(2)
        await env.send(2, "queue_join", code=code)
        (t,) = env.mm.tables.values()
        history = env.conns[2].last("table_chat_history")
        assert history["table"] == t.id
        assert [(m["seat"], m["name"], m["text"]) for m in history["messages"]] == [
            (0, "P1", "come sit")]
        await env.send(1, "table_start")
        await env.send(2, "table_start")
        (chat,) = env.chats
        assert [m["text"] for m in chat] == ["come sit"]
    run(go())


def test_a_lone_entrys_chat_is_the_rooms_scrollback_when_it_starts_alone():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "table_chat", text="just me")
        await env.send(1, "queue_start_bots")
        (table_id, _), = env.started
        assert table_id is None
        (chat,) = env.chats
        assert [(m["seat"], m["name"], m["text"]) for m in chat] == [(0, "P1", "just me")]
        assert all(set(m) == {"id", "seat", "name", "text", "t"} for m in chat)
        # and on the bot timer
        await env.join(2)
        await env.send(2, "table_chat", text="timer me")
        env.clock.advance(mm.BOT_FILL_SECS + 1)
        await env.mm.pump()
        assert [tid for tid, _ in env.started] == [None, None]
        assert [m["text"] for m in env.chats[1]] == ["timer me"]
    run(go())


def test_a_lone_entrys_chat_is_rate_limited():
    async def go():
        env = Env()
        await env.join(1)
        for i in range(mm.CHAT_LIMIT[0]):
            await env.send(1, "table_chat", text=f"m{i}")
        assert env.conns[1].last("error") is None
        await env.send(1, "table_chat", text="one too many")
        assert env.conns[1].last("error")["code"] == "rate_limited"
        assert env.conns[1].last("table_chat")["text"] == f"m{mm.CHAT_LIMIT[0] - 1}"
        assert len(env.mm._entry(1).chat) == mm.CHAT_LIMIT[0]
    run(go())


def test_table_chat_limits_match_room_chat():
    from shengji.api import server as srv
    assert (mm.CHAT_MAX_LEN, mm.CHAT_KEEP) == (srv.CHAT_MAX_LEN, srv.CHAT_KEEP)


def test_ws_table_chat_becomes_the_rooms_scrollback_and_is_never_logged(wsenv):
    srv, store, client, clock = wsenv
    (u1, h1), (u2, h2) = _user(store, "c1", "One"), _user(store, "c2", "Two")
    with client.websocket_connect("/ws", headers=h1) as a, \
            client.websocket_connect("/ws", headers=h2) as b:
        a.send_json({"type": "queue_join", "mode": "casual"})
        _drain(a, "queue_state")
        b.send_json({"type": "queue_join", "mode": "casual"})
        assert _drain(b, "queue_state")["table"]["of"] == 2
        b.send_json({"type": "table_chat", "text": "secret-table-line"})
        assert _drain(a, "table_chat")["text"] == "secret-table-line"
        a.send_json({"type": "table_start"})
        b.send_json({"type": "table_start"})
        seen = _until(a, "state", tries=200)
        started = next(m for m in seen if m["type"] == "match_started")
        assert started["rated"] is False
        history = next(m for m in seen if m["type"] == "chat_history")
        assert [(m["seat"], m["name"], m["text"]) for m in history["messages"]] == [
            (2, "Two", "secret-table-line")]
        room = srv.rooms[started["room"]]
        assert not room.matched and not room.ranked and not room.move_timer
        assert [s.user_id for s in room.seats] == [u1, None, u2, None]
    logs = [p for p in srv.LOG_DIR.rglob("*") if p.is_file()]
    assert logs, "the room wrote its round log"
    assert not any("secret-table-line" in p.read_text(errors="replace") for p in logs)


def test_ws_a_casual_created_room_is_an_open_table_of_the_casual_queue_only(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    _, h1 = _user(store, "own", "Owner")
    _, h2 = _user(store, "cas", "Casual")
    _, h3 = _user(store, "rnk", "Ranked")
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=h1) as o:
        o.send_json({"type": "create_room", "name": "Owner"})
        first = _drain(o, "room")
        code = first["room"]
        assert first["allow_joiners"] is True and "ranked" not in first
        o.send_json({"type": "lobby_ready"})
        _drain(o, "state", tries=400)
        room = srv.rooms[code]
        _wait_until(lambda: room.round is not None)
        [view] = [t for t in srv.open_tables() if t["code"] == code]
        assert view["mode"] == "casual"
        assert [s["open"] for s in view["seats"]] == [False, True, True, True]
        assert srv.presence_counts() == (1, 1, 0, 1)
        with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=h3) as r:
            r.send_json({"type": "queue_join"})
            assert _drain(r, "queue_state")["offer"] is None
        with client.websocket_connect(f"/ws?device={DEVICE_B}", headers=h2) as c:
            c.send_json({"type": "queue_join", "mode": "casual"})
            assert _drain(c, "queue_state")["offer"]["room"] == code


def test_ws_leaving_a_casual_table_one_joined_is_free_but_the_table_stays_barred(
        wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    ratings.CARRIED_CAPS.clear()
    host, host_headers = _user(store, "host", "Host")
    alice, alice_headers = _user(store, "alice", "Alice")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=alice_headers) as a:
        h.send_json({"type": "queue_join", "mode": "casual"})
        _drain(h, "queue_state")
        h.send_json({"type": "queue_start_bots"})
        started = _drain(h, "match_started")
        assert started["rated"] is False
        room = srv.rooms[started["room"]]
        code = room.code
        # the bot plays the host's seat too: away needs the move timer, which
        # a casual room keeps off, so the test turns it on for the host alone
        room.move_timer = True
        room.seats[0].away = True
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        a.send_json({"type": "queue_join", "mode": "casual"})
        offer = _drain(a, "queue_state")["offer"]
        assert offer["room"] == code and offer["pick"] == 2
        a.send_json({"type": "open_table_join", "room": code, "seat": 2})
        assert _drain(a, "match_started")["rated"] is False
        _wait_until(lambda: room.seats[2].user_id == alice)
        assert room.seats[2].joined_round == room.game.round_no
        # the frame's leave warning is a ranked table's only
        assert srv.state_for(room, 2)["joined_round"] is False
        a.send_json({"type": "leave_room"})
        _drain(a, "left", tries=400)
        assert room.seats[2].is_bot and alice not in ratings.CARRIED_CAPS
        assert alice not in srv.MATCHMAKER.cooldowns
        assert code in srv.MATCHMAKER.barred[alice]
        a.send_json({"type": "queue_join", "mode": "casual"})
        state = _drain(a, "queue_state", tries=400)
        assert state["queued"] and state["offer"] is None
    ratings.CARRIED_CAPS.clear()


def test_leaving_a_casual_table_before_the_handover_is_free(otenv):
    srv, store, env = otenv
    host, _ = _user(store, "host")
    new, _ = _user(store, "alice", "Alice")

    async def go():
        t = OpenRoom(srv, [host, "bot", "bot", "bot"])
        t.room.matched = False                        # a casual room
        t.first_round(banker=2)                       # seat 2 buries: the Join waits
        conn = env.player(new, name="Alice")
        conn.ws = _FakeWS()
        await env.send(new, "queue_join", mode="casual")
        await env.send(new, "open_table_join", room="OPEN", seat=2)
        assert 2 in t.room.pending_joins
        await srv.end_pending_join(conn, penalty=True)
        assert "OPEN" in env.mm.barred[new] and new not in env.mm.cooldowns
    run(go())


def test_ws_a_seat_a_queue_join_holds_is_not_claimable_by_code(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    monkeypatch.setattr(srv, "_settle_joins", lambda room: None)   # the Join stays pending
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as o, \
            client.websocket_connect(f"/ws?device={DEVICE_B}") as f:
        o.send_json({"type": "create_room", "name": "Owner"})
        code = _drain(o, "room")["room"]
        o.send_json({"type": "lobby_ready"})
        room = srv.rooms[code]
        _wait_until(lambda: room.round is not None)
        room.pending_joins[2] = srv.PendingJoin(uid=77, name="Queued", conn=mm.Conn(None, 77))
        f.send_json({"type": "peek_room", "room": code})
        assert [s["claimable"] for s in _drain(f, "room_seats")["seats"]] == [
            False, True, False, True]
        f.send_json({"type": "join_room", "room": code, "name": "Friend", "seat": 2})
        assert _drain(f, "error")["code"] == "seat_unavailable"
        f.send_json({"type": "join_room", "room": code, "name": "Friend"})
        _wait_until(lambda: room.seats[1].name == "Friend")
        assert room.seats[2].is_bot


# ------------------------------------------------------- table codes
def test_a_lone_entry_has_its_own_table_code():
    async def go():
        env = Env()
        await env.join(1)
        state = env.conns[1].last("queue_state")
        assert state["table"] is None             # an older client still sees itself alone
        code = state["code"]
        assert len(code) == mm.CODE_LEN and set(code) <= set(mm.CODE_ALPHABET)
        assert state["opener"] is True and state["allow_joiners"] is True
        assert state["start_level"] == "2"
        assert env.mm.has_code(code)
        assert env.mm.code_lookup(env.conns[1], {"code": code.lower()}, 1)["kind"] == "table"
        await env.send(1, "queue_leave")
        assert not env.mm.has_code(code)
        assert env.mm.code_lookup(env.conns[1], {"code": code}, 1)["kind"] == "none"
    run(go())


def test_a_friend_joins_by_code_before_the_game_and_the_code_is_the_room_code():
    async def go():
        env = Env()
        await env.join(1, mode="casual", allow_joiners=False)
        code = env.conns[1].last("queue_state")["code"]
        env.player(2, rating=1900.0)               # far outside any window: a friend sits anyway
        await env.send(2, "queue_join", code=code)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 2, None] and t.mode == "casual"
        for uid in (1, 2):
            state = env.conns[uid].last("queue_state")
            assert state["code"] == code and state["table"]["code"] == code
            assert state["table"]["opener"] == 0 and state["opener"] is (uid == 1)
            assert state["mode"] == "casual" and state["allow_joiners"] is False
        # a joiner's own code still leads to the same table
        mine = env.mm._entry(2).code
        assert mine != code and env.mm.code_lookup(env.conns[2], {"code": mine}, 2)["kind"] == "table"
        await env.send(1, "table_start")
        await env.send(2, "table_start")
        (match_id, slots), = env.started
        assert match_id == t.id and humans_of(slots) == [1, 2]
        assert env.modes == ["casual"]
        assert env.rooms[0] == {"code": code, "allow_joiners": False, "start_level": "2"}
        assert not env.mm.has_code(code) and not env.mm.has_code(mine)
    run(go())


def test_a_game_started_alone_keeps_the_entry_code():
    async def go():
        env = Env()
        await env.join(1)
        code = env.conns[1].last("queue_state")["code"]
        await env.send(1, "queue_start_bots")
        assert env.rooms == [{"code": code, "allow_joiners": True, "start_level": "2"}]
    run(go())


def test_joining_by_code_takes_the_tables_mode_and_keeps_the_queue_guards():
    async def go():
        env = Env()
        await env.join(1)                          # ranked
        code = env.conns[1].last("queue_state")["code"]
        # the code decides the mode, whatever the joiner's tab says
        env.player(-7, name="Guest")
        await env.send(-7, "queue_join", code=code, mode="casual")
        guest = env.mm._entry(-7)
        assert guest.mode == "ranked" and guest.table_id is not None
        assert guest.member_ratings == {-7: ratings.GUEST_RATING}
        # own code, an unknown code, a cooldown, a device already there
        await env.send(1, "queue_join", code=code)
        assert env.conns[1].last("error") is None   # already at that table: a resync
        env.player(3)
        await env.send(3, "queue_join", code="ZZZZ")
        assert env.conns[3].last("error")["code"] == "table_not_found"
        env.mm.cooldowns[3] = env.clock() + 30
        await env.send(3, "queue_join", code=code)
        assert env.conns[3].last("error")["code"] == "cooldown"
        assert env.mm._entry(3) is None
        del env.mm.cooldowns[3]
        env.conns[1].device = DEVICE_A
        env.conns[3].device = DEVICE_A
        await env.send(3, "queue_join", code=code)
        assert env.conns[3].last("error")["code"] == "same_device"
        assert env.mm._entry(3) is None
        # someone searching elsewhere cancels first
        env.conns[3].device = DEVICE_B
        await env.send(3, "queue_join", mode="casual")
        await env.send(3, "queue_join", code=code)
        assert env.conns[3].last("error")["code"] == "in_queue"
        await env.send(3, "queue_leave")
        # a full table refuses
        await env.send(3, "queue_join", code=code)
        env.player(4)
        await env.send(4, "queue_join", code=code)
        assert env.started                          # four people: the table started
        env.player(5)
        await env.send(5, "queue_join", code=code)
        assert env.conns[5].last("error")["code"] == "table_not_found"
    run(go())


def test_a_ranked_table_refuses_a_starting_level_and_a_casual_one_takes_it():
    async def go():
        env = Env()
        env.player(1)
        await env.send(1, "queue_join", start_level="5")
        assert env.conns[1].last("error")["code"] == "ranked_level_fixed"
        await env.send(1, "queue_join")
        await env.send(1, "table_start_level", start_level="5")
        assert env.conns[1].last("error")["code"] == "ranked_level_fixed"
        assert env.conns[1].last("queue_state")["start_level"] == "2"
        await env.send(1, "queue_leave")

        await env.send(1, "queue_join", mode="casual", start_level="5")
        assert env.conns[1].last("queue_state")["start_level"] == "5"
        code = env.conns[1].last("queue_state")["code"]
        env.player(2)
        await env.send(2, "queue_join", code=code)
        await env.send(2, "table_start")
        await env.send(2, "table_start_level", start_level="9")
        assert env.conns[2].last("error")["code"] == "not_opener"
        await env.send(1, "table_start_level", start_level="9")
        state = env.conns[2].last("queue_state")
        assert state["start_level"] == "9" and state["table"]["ready"] == 0   # Start agreed to 5
        await env.send(1, "table_start_level", start_level="1")
        assert env.conns[1].last("error")["code"] == "bad_start_level"
        await env.send(1, "table_start")
        await env.send(2, "table_start")
        assert env.rooms[-1]["start_level"] == "9"
    run(go())


def test_allow_joiners_off_hides_the_table_from_play_but_not_from_its_code():
    async def go():
        env = Env()
        await env.join(1)
        code = env.conns[1].last("queue_state")["code"]
        await env.send(1, "table_allow_joiners", on=False)
        assert env.conns[1].last("queue_state")["allow_joiners"] is False
        await env.join(2)                           # a stranger on Play
        assert env.mm.tables == {} and env.conns[2].last("queue_state")["table"] is None
        env.player(3)
        await env.send(3, "queue_join", code=code)  # the link
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 3, None]
        await env.mm.tick()
        assert env.mm._entry(2).table_id is None    # still not offered the private table
        # on again: Play seats the stranger there
        await env.send(3, "table_allow_joiners", on=True)
        assert t.seats == [1, 2, 3, None]
    run(go())


def test_allow_joiners_off_offers_no_open_table():
    async def go():
        env = Env()
        tables = [{"code": "OPEN", "mode": "ranked", "round_end": False, "seats": [
            {"name": "Ann", "bot": False, "open": False, "queue_id": 50, "device": None},
            {"name": "Bot 1", "bot": True, "open": True},
            {"name": "Bot 2", "bot": True, "open": True},
            {"name": "Bot 3", "bot": True, "open": True}]}]
        env.mm.open_tables = lambda: tables
        await env.join(1, allow_joiners=False)
        assert env.conns[1].last("queue_state")["offer"] is None
        await env.send(1, "table_allow_joiners", on=True)
        assert env.conns[1].last("queue_state")["offer"]["room"] == "OPEN"
        await env.send(1, "table_allow_joiners", on=False)
        assert env.conns[1].last("queue_state")["offer"] is None
    run(go())


def test_new_room_and_pair_codes_avoid_queued_table_codes(monkeypatch):
    from shengji.api import server as srv
    srv.MATCHMAKER.reset()
    try:
        srv.MATCHMAKER.entry_codes["TAKN"] = "e1"
        draws = iter(["TAKN", "FREE"])

        class Rng:
            def choices(self, alphabet, k):
                return list(next(draws))
        monkeypatch.setattr(srv, "random", Rng())
        assert srv.new_code() == "FREE"
        assert srv.MATCHMAKER.code_lookup(mm.Conn(None, 1), {"code": "TAKN"}, 1)["kind"] == "table"
    finally:
        srv.MATCHMAKER.reset()


def test_ws_a_friend_joins_a_table_by_its_code_and_the_room_has_that_code(wsenv):
    srv, store, client, clock = wsenv
    host, host_headers = _user(store, "codehost", "Host")
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        h.send_json({"type": "queue_join"})
        code = _drain(h, "queue_state")["code"]
        g.send_json({"type": "code_lookup", "code": code})
        assert _drain(g, "code_kind")["kind"] == "table"
        g.send_json({"type": "queue_join", "code": code, "name": "Guest"})
        table = _drain(g, "queue_state")["table"]
        assert table["code"] == code and table["you"] == 2
        h.send_json({"type": "table_start"})
        g.send_json({"type": "table_start"})
        assert _drain(h, "match_started", tries=80)["room"] == code
        assert _drain(g, "match_started", tries=80)["room"] == code
        room = srv.rooms[code]
        assert room.matched and room.start_level == "2" and room.allow_joiners is True


def test_ws_a_casual_tables_starting_level_reaches_its_room(wsenv):
    srv, store, client, clock = wsenv
    with client.websocket_connect(f"/ws?device={DEVICE_A}") as g:
        g.send_json({"type": "queue_join", "mode": "casual", "start_level": "5", "name": "Guest"})
        state = _drain(g, "queue_state")
        assert state["start_level"] == "5"
        g.send_json({"type": "queue_start_bots"})
        code = _drain(g, "match_started", tries=80)["room"]
        assert code == state["code"]
        room = srv.rooms[code]
        assert room.start_level == "5" and room.game.levels == ("5", "5")
