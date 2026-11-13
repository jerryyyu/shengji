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

    def add(self, code, seats, round_end=False):
        """``seats``: an int is a person's account, "bot" a bot seat."""
        self.tables[code] = {"code": code, "round_end": round_end, "seats": [
            {"name": "Bot", "bot": True, "open": True, "user_id": None, "team": i % 2}
            if s == "bot" else
            {"name": f"P{s}", "bot": False, "open": False, "user_id": s, "team": i % 2}
            for i, s in enumerate(seats)]}

    def take(self, code, seat, uid):
        self.tables[code]["seats"][seat] = {"name": f"P{uid}", "bot": False, "open": False,
                                            "user_id": uid, "team": seat % 2}

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
        assert t.seats[:2] == [1, 2]
        for uid in (1, 2):
            state = env.conns[uid].last("queue_state")
            assert state["offer"] is None and state["table"] is not None
        # the wait stood still under the offer and runs on as the table's timer
        assert env.mm._entry(1).bots_at == env.clock.t + mm.BOT_FILL_SECS
        # a pair queued while a table waits for people still gets an open
        # table's free partner seats (it cannot sit at a two-seat-short table)
        await env.pair(3, 4)
        await env.send(3, "queue_join", party_id=env.mm._party(3).id)
        assert env.mm._entry(3).table_id is not None or env.mm._entry(3).offer.pair == (1, 3)
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


def test_wait_keeps_queuing_pauses_the_bot_timer_and_never_re_offers_by_itself():
    async def go():
        env = Env()
        tables = Tables(env)
        await env.join(1)
        env.clock.advance(20)                         # 40 s of bot wait left
        tables.add("OPEN", [50, "bot", "bot", "bot"])
        await env.mm.tick()
        await env.send(1, "open_table_wait")
        state = env.conns[1].last("queue_state")
        assert state["queued"] and state["offer"] is None
        assert state["open_tables"] == 1 and state["bots_paused"] is True
        env.clock.advance(600)
        await env.mm.pump()
        await env.mm.tick()
        assert env.started == [] and env.mm._entry(1).offer is None
        # the chip brings the offer back, with a fresh clock
        await env.send(1, "open_table_show")
        offer = env.conns[1].last("queue_state")["offer"]
        assert offer["room"] == "OPEN" and offer["expires_at"] == env.clock.t + mm.OFFER_SECS
        await env.send(1, "open_table_wait")
        # the table closes: the timer runs on from where it stopped
        del tables.tables["OPEN"]
        await env.mm.tick()
        state = env.conns[1].last("queue_state")
        assert state["open_tables"] == 0 and state["bots_paused"] is False
        assert state["bots_at"] == env.clock.t + 40
        env.clock.advance(40)
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
                                             "user_id": None, "team": 0}
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
                      else srv.Seat(name=f"P{s}", user_id=s, connected=True)
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
        assert [s["open"] for s in view["seats"]] == [False, True, True, True]
        assert srv.state_for(t.room, 0)["allow_joiners"] is True
        await srv.handle_action(t.room, 0, {"type": "allow_joiners", "on": False})
        assert srv.open_tables() == [] and srv.state_for(t.room, 0)["allow_joiners"] is False
        with pytest.raises(srv.IllegalPlay):
            await srv.handle_action(t.room, 1, {"type": "allow_joiners", "on": True})
        await srv.handle_action(t.room, 0, {"type": "allow_joiners", "on": True})
        assert len(srv.open_tables()) == 1
        # nobody connected, a casual room, four people: none is open
        t.room.seats[0].connected = False
        assert srv.open_tables() == []
        t.room.seats[0].connected = True
        t.room.matched = False
        assert srv.open_tables() == []
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
                           "team": 0, "user_id": dana}
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


def test_ws_a_guest_with_a_ranked_invite_is_asked_to_sign_in(wsenv, monkeypatch):
    srv, store, client, clock = wsenv
    _, host_headers = _ranked_host(srv, store, client, monkeypatch)
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws") as g:
        code, room = _start_ranked(srv, h)
        g.send_json({"type": "peek_room", "room": code})
        assert _drain(g, "room_seats")["ranked"] is True
        g.send_json({"type": "join_room", "room": code, "name": "Guest", "seat": 2})
        err = _drain(g, "error")
        assert err["code"] == "ranked_sign_in" and err["message"] == "Sign in to join a ranked table."
        assert all(sd.user_id != None or sd.is_bot for sd in room.seats)  # noqa: E711
        assert room.pending_joins == {}


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
