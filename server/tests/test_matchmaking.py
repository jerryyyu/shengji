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

import pytest

from shengji.api import matchmaking as mm
from shengji.api import ratings

from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_ratings import _set, _user
from tests.test_server_ws import _drain, client  # noqa: F401


# ---------------------------------------------------------------- harness
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

        async def rating_of(uid):
            return self.ratings.get(uid)

        async def start_room(match_id, slots, conns):
            self.started.append((match_id, slots))
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
    assert mm.AWAY_SECS == 10.0 and mm.TABLE_AWAY_SECS == 60.0
    assert mm.TABLE_IDLE_SECS == 120.0
    assert mm.SEAT_ORDER == (0, 1, 2, 3) and mm.PAIR_SEATS == ((0, 2), (1, 3))


# ------------------------------------------------------- seating a table
def test_alone_in_the_queue_there_is_no_table():
    async def go():
        env = Env()
        await env.join(1)
        state = env.conns[1].last("queue_state")
        assert state["queued"] and state["table"] is None
        assert env.mm.tables == {}
    run(go())


def test_two_singles_form_one_table_on_the_second_ones_arrival():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, None]
        for uid, seat in ((1, 0), (2, 1)):
            table = env.conns[uid].last("queue_state")["table"]
            assert table["id"] == t.id and table["you"] == seat
            assert [s and s["name"] for s in table["seats"]] == ["P1", "P2", None, None]
            assert table["seats"][seat]["you"] is True
            assert table["ready"] == 0 and table["of"] == 2
        assert env.started == []
    run(go())


def test_a_third_sits_as_the_first_ones_partner_and_a_fourth_starts_the_table_at_once():
    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, 3, None]
        await env.join(4)
        (table_id, slots), = env.started
        assert table_id == t.id
        assert [s.user_id for s in slots] == [1, 2, 3, 4]
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


def test_a_pair_never_splits_across_teams_to_fit_a_table():
    async def go():
        env = Env()
        await env.join(1)
        await env.join(2)
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, None]
        assert env.mm._entry(3).table_id is None
        assert env.conns[4].last("queue_state")["table"] is None
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
        assert t.seats == [1, 2, None, None]
    run(go())


def test_from_five_queued_the_rating_window_decides_who_shares_a_table():
    async def go():
        env = Env()
        await env.join(1, 1000)
        await env.join(2, 1000)
        await env.pair(3, 4, 1000, 1000)
        await env.send(3, "queue_join")      # no pair seats left: waits alone
        await env.join(5, 1600)               # five queued: 600 is outside ±100
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, None]
        assert env.mm._entry(5).table_id is None
        await env.join(6, 1050)               # inside the window
        assert t.seats == [1, 2, 6, None]
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
        assert len(tables) == 1 and tables[0].seats == [1, 2, 3, None]
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
        assert mine["seats"][0]["ready"] and not mine["seats"][1]["ready"]
        await env.join(3)                     # a newcomer does not clear the tick
        mine = env.conns[1].last("queue_state")["table"]
        assert mine["ready"] == 1 and mine["of"] == 3 and mine["waiting_for"] == ["P2", "P3"]
        await env.send(2, "table_start")
        await env.send(2, "table_start")      # twice is once
        assert env.started == []
        await env.send(3, "table_start")
        (table_id, slots), = env.started
        assert [s.user_id for s in slots] == [1, 2, 3, None]
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
        assert [s.user_id for s in slots] == [1, None, 3, None]
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
        assert [s.user_id for s in slots] == [1, 2, None, None]
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
        assert [s.user_id for s in slots] == [1, 2, None, None]
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
        assert t.seats == [1, None, 3, None]
        assert env.conns[2].last("queue_state")["queued"] is False
        assert env.conns[1].last("queue_state")["table"]["seats"][1] is None
        await env.join(4)
        assert t.seats == [1, 4, 3, None]
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
        seat = env.conns[1].last("queue_state")["table"]["seats"][1]
        assert seat["reconnecting"] is True and seat["ready"] is True
        env.clock.advance(mm.TABLE_AWAY_SECS - 1)
        await env.mm.pump()
        assert env.mm._entry(2) is not None
        back = FakeConn(2, "P2")
        env.mm.connect(back)                 # the app comes back: resync, readiness kept
        table = back.last("queue_state")["table"]
        assert table["you"] == 1 and table["you_ready"] is True
        assert env.conns[1].last("queue_state")["table"]["seats"][1]["reconnecting"] is False
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
        assert [s.user_id for s in slots] == [1, None, 3, 4]
        assert env.mm._entry(2) is None
    run(go())


def test_two_minutes_without_a_tap_at_the_table_removes_you_without_a_cooldown():
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
        removed = env.conns[2].last("queue_removed")
        assert removed["reason"] == "idle" and removed["cooldown_until"] is None
        assert env.mm._entry(1) is not None and env.mm._entry(3) is not None
        (t,) = env.mm.tables.values()
        assert t.seats == [1, None, 3, None]
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

        async def boom(match_id, slots, conns):
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

        async def boom(match_id, slots, conns):
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
        await env.join(2)
        await env.pair(3, 4)
        await env.send(3, "queue_join")
        await env.send(4, "party_leave")
        (t,) = env.mm.tables.values()
        assert t.seats == [1, 2, None, None]
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
        assert env.conns[1].last("queue_state")["replaced"] is True
        assert env.mm.conns[1] is second and second.last("queue_state")["queued"]
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
        assert again.seats == [1, 2, 3, 4]
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
        assert table["you"] == 1 and [s["name"] for s in table["seats"][:2]] == ["Player0", "Player1"]
        c.send_json({"type": "queue_join"})
        assert _drain(c, "queue_state")["table"]["you"] == 2
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
        assert by_seat == uid                 # arrival order, alternating teams
        assert room.waiting_table == started["match_id"] and room.table_humans == 4
        assert room.game is not None and room.matched
        assert room.ratings is not None
        assert room.ratings.present == {0: uid[0], 1: uid[1], 2: uid[2], 3: uid[3]}
        # The adopted socket plays on as a seated socket: chat reaches the room.
        if heartbeat:
            a.send_json({"type": "ping", "nonce": 2})
            assert _drain(a, "pong", tries=400)["nonce"] == 2
            assert [s.user_id for s in room.seats] == by_seat
        a.send_json({"type": "chat", "text": "gl"})
        assert _drain(b, "chat", tries=400)["text"] == "gl"
        assert srv.MATCHMAKER.entries == {} and srv.MATCHMAKER.tables == {}


def test_ws_guest_is_refused(wsenv):
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
        assert [s.user_id for s in room.seats] == [u1, u2, None, None]
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
