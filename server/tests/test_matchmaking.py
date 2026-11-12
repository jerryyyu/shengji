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
        assert self.mm._entry(uid) is not None, self.conns[uid].sent

    async def pair(self, leader, partner, r1=1000.0, r2=1000.0):
        self.player(leader, r1)
        self.player(partner, r2)
        await self.send(leader, "party_create")
        code = self.conns[leader].last("party")["code"]
        await self.send(partner, "party_join", code=code)
        return self.mm._party(leader)

    def match_of(self, uid):
        e = self.mm._entry(uid)
        return self.mm.matches.get(e.match_id) if e and e.match_id else None


def run(coro):
    return asyncio.run(coro)


def humans_of(slots):
    return [s.user_id for s in slots if not s.is_bot]


# ------------------------------------------------------------ the window
def test_window_steps_and_bot_fill_are_the_named_constants():
    assert mm.BOT_FILL_SECS == 60.0
    assert mm.WINDOW_STEPS == ((20.0, 100.0), (40.0, 250.0))
    assert mm.window_for(0) == 100 and mm.window_for(19.9) == 100
    assert mm.window_for(20) == 250 and mm.window_for(39.9) == 250
    assert mm.window_for(40) == float("inf")


def test_the_anchor_takes_the_closest_ratings_inside_its_window():
    async def go():
        env = Env()
        await env.join(1, 1000)              # the anchor: longest wait
        env.clock.advance(1)
        for uid, r in ((2, 1050), (3, 1090), (4, 1150), (5, 1020)):
            await env.join(uid, r)
        formed = env.mm.tick()
        assert len(formed) == 1
        assert set(formed[0].humans) == {1, 2, 3, 5}   # 1150 is outside +-100
        assert env.mm._entry(4).match_id is None
    run(go())


def test_the_window_widens_with_the_anchors_wait():
    async def go():
        env = Env()
        await env.join(1, 1000)
        for uid in (2, 3, 4):
            await env.join(uid, 1200)
        assert env.mm.tick() == []           # anchor first: the 1200s wait for it
        env.clock.advance(19.9)
        assert env.mm.tick() == []
        env.clock.advance(0.1)               # 20 s: +-250
        assert len(env.mm.tick()) == 1

        env = Env()
        await env.join(1, 1000)
        for uid in (2, 3, 4):
            await env.join(uid, 1400)
        env.clock.advance(39)
        assert env.mm.tick() == []
        env.clock.advance(1)                 # 40 s: any rating
        assert len(env.mm.tick()) == 1
    run(go())


def test_front_of_line_entries_anchor_before_older_ones():
    async def go():
        env = Env()
        await env.join(1, 1000)
        env.clock.advance(5)
        await env.join(2, 1500)
        env.mm._entry(2).front = True
        for uid in (3, 4, 5):
            await env.join(uid, 1500)
        formed = env.mm.tick()
        assert set(formed[0].humans) == {2, 3, 4, 5}
    run(go())


# ------------------------------------------------------------- the teams
def test_teams_take_the_pairing_with_the_smallest_average_gap():
    slots = [mm.Slot(1, "a", 1400), mm.Slot(2, "b", 1200),
             mm.Slot(3, "c", 1200), mm.Slot(4, "d", 1000)]
    seats = mm.choose_teams(slots)
    team0 = {seats[0].user_id, seats[2].user_id}
    assert team0 == {1, 4} and seats[0].user_id == 1     # 1200 vs 1200: gap 0


def test_a_pair_is_never_split_even_when_splitting_is_fairer():
    slots = [mm.Slot(1, "a", 1400, "p"), mm.Slot(2, "b", 1400, "p"),
             mm.Slot(3, "c", 1000), mm.Slot(4, "d", 1000)]
    seats = mm.choose_teams(slots)
    assert {seats[0].user_id, seats[2].user_id} == {1, 2}


def test_with_bots_the_humans_are_spread_across_both_teams():
    bot = mm.Slot(None, "", ratings.BOT_RATING)
    # Two humans at 1000 and 1000 with bots: grouping the humans would be a
    # zero gap too, but the spread pairing is preferred.
    seats = mm.choose_teams([mm.Slot(1, "a", 1000), mm.Slot(2, "b", 1000), bot, bot])
    assert seats[0].user_id == 1 and seats[1].user_id == 2
    assert seats[2].is_bot and seats[3].is_bot


# -------------------------------------------------------------- bot fill
@pytest.mark.parametrize("humans", [1, 2, 3])
def test_bot_fill_at_sixty_seconds(humans):
    async def go():
        env = Env()
        for uid in range(1, humans + 1):
            await env.join(uid, 1000 + 400 * (uid - 1))
        env.clock.advance(59.9)
        assert env.mm.tick() == []
        env.clock.advance(0.1)
        formed = env.mm.tick()
        assert len(formed) == 1
        m = formed[0]
        assert sorted(m.humans) == list(range(1, humans + 1)) and m.bots == 4 - humans
        assert all(s.rating == ratings.BOT_RATING for s in m.slots if s.is_bot)
        msg = env.conns[1].last("match")
        assert msg["size"] == humans and msg["bots"] == 4 - humans
        if humans >= 2:
            teams = {i % 2 for i, s in enumerate(m.slots) if not s.is_bot}
            assert teams == {0, 1}
    run(go())


def test_bot_fill_keep_waiting_restarts_the_wait_without_a_cooldown():
    async def go():
        env = Env()
        await env.join(1)
        env.clock.advance(60)
        m = env.mm.tick()[0]
        await env.send(1, "match_decline", match_id=m.id, keep_waiting=True)
        e = env.mm._entry(1)
        assert e is not None and e.since == env.clock() and not e.front
        assert 1 not in env.mm.cooldown
    run(go())


# ----------------------------------------------------------- ready check
def test_all_accept_starts_the_room_with_the_chosen_seats():
    async def go():
        env = Env()
        for uid, r in ((1, 1400), (2, 1200), (3, 1200), (4, 1000)):
            await env.join(uid, r)
        env.clock.advance(40)                # any rating from 40 s
        m = env.mm.tick()[0]
        for uid in (1, 2, 3):
            await env.send(uid, "match_accept", match_id=m.id)
        ready = env.conns[1].last("match_ready")
        assert ready["accepted"] == 3 and ready["of"] == 4 and "names" not in ready
        assert env.started == []
        await env.send(4, "match_accept", match_id=m.id)
        assert len(env.started) == 1
        mid, slots = env.started[0]
        assert mid == m.id and [s.user_id for s in slots] == [1, 2, 4, 3]
        final = env.conns[4].last("match_ready")
        assert final["accepted"] == 4 and sorted(final["names"]) == ["P1", "P2", "P3", "P4"]
        assert env.mm.entries == {} and env.mm.matches == {}
    run(go())


def _four(env):
    async def go():
        for uid in (1, 2, 3, 4):
            await env.join(uid)
            env.clock.advance(1)
        return env.mm.tick()[0]
    return go()


def test_a_decline_cools_the_decliner_and_requeues_only_the_accepters_at_the_front():
    async def go():
        env = Env()
        start = env.clock()
        m = await _four(env)
        await env.send(1, "match_accept", match_id=m.id)
        await env.send(2, "match_decline", match_id=m.id)
        removed = env.conns[2].last("queue_removed")
        assert removed["reason"] == "declined"
        assert removed["cooldown_until"] == env.clock() + mm.COOLDOWN_SECS
        assert env.mm._entry(2) is None and m.id not in env.mm.matches
        for uid in (1, 3, 4):
            e = env.mm._entry(uid)
            assert e.match_id is None and e.since == start + (uid - 1)
            assert e.front is (uid == 1)
            assert uid not in env.mm.cooldown
            assert env.conns[uid].last("match_cancelled")["reason"] == "player_missed"
            assert env.conns[uid].last("queue_state")["front"] is (uid == 1)
        env.clock.advance(29)
        await env.send(2, "queue_join")
        err = env.conns[2].last("error")
        assert err["code"] == "cooldown" and env.mm._entry(2) is None
        env.clock.advance(1)
        await env.send(2, "queue_join")
        assert env.mm._entry(2) is not None
    run(go())


def test_a_timeout_cools_only_the_players_who_did_not_accept():
    async def go():
        env = Env()
        m = await _four(env)
        await env.send(1, "match_accept", match_id=m.id)
        await env.send(3, "match_accept", match_id=m.id)
        env.clock.advance(mm.READY_SECS - 0.1)
        await env.mm.pump()
        assert m.id in env.mm.matches
        env.clock.advance(0.1)
        await env.mm.pump()
        for uid in (2, 4):
            assert env.conns[uid].last("queue_removed")["reason"] == "missed"
            assert uid in env.mm.cooldown
        assert env.mm._entry(1).front and env.mm._entry(3).front
    run(go())


def test_cancelling_during_the_check_is_a_decline():
    async def go():
        env = Env()
        m = await _four(env)
        await env.send(1, "match_accept", match_id=m.id)
        await env.send(3, "queue_leave")
        assert env.conns[3].last("queue_removed")["reason"] == "declined"
        assert 3 in env.mm.cooldown and env.mm._entry(1).front
        assert not env.mm._entry(2).front and 2 not in env.mm.cooldown
    run(go())


def test_the_accepters_rematch_at_the_front_with_a_newcomer():
    async def go():
        env = Env()
        m = await _four(env)
        for uid in (1, 2, 3):
            await env.send(uid, "match_accept", match_id=m.id)
        await env.send(4, "match_decline", match_id=m.id)
        env.clock.advance(5)
        await env.join(9)
        m = env.mm.tick()[0]
        assert set(m.humans) == {1, 2, 3, 9}
    run(go())


# ----------------------------------------------------- queue_start_bots
def test_start_bots_solo_seats_one_human_and_three_bots():
    async def go():
        env = Env()
        await env.join(1)
        await env.send(1, "queue_start_bots")
        mid, slots = env.started[0]
        assert mid is None and humans_of(slots) == [1] and slots[0].user_id == 1
        assert env.mm._entry(1) is None
    run(go())


def test_start_bots_as_a_pair_puts_the_bots_opposite_and_is_the_leaders_call():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.send(2, "queue_start_bots")
        assert env.conns[2].last("error")["code"] == "not_leader" and not env.started
        await env.send(1, "queue_start_bots")
        _, slots = env.started[0]
        assert [s.user_id for s in slots] == [1, None, 2, None]
    run(go())


def test_start_bots_failure_reaches_both_members_of_a_pair():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")

        async def boom(match_id, slots, conns):
            raise RuntimeError("injected start failure")
        env.mm.start_room = boom
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "start_failed"
        assert env.conns[2].last("error")["code"] == "start_failed"
        assert env.mm._entry(1) is None and env.mm._entry(2) is None
    run(go())


def test_start_bots_after_a_match_formed_is_refused_with_match_pending():
    async def go():
        env = Env()
        m = await _four(env)
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "match_pending"
        assert env.started == [] and m.id in env.mm.matches
    run(go())


def test_start_bots_needs_a_queue_entry():
    async def go():
        env = Env()
        env.player(1)
        await env.send(1, "queue_start_bots")
        assert env.conns[1].last("error")["code"] == "not_queued"
    run(go())


# --------------------------------------------------------- away from app
def test_away_over_ten_seconds_drops_without_a_cooldown():
    async def go():
        env = Env()
        await env.join(1)
        env.mm.disconnect(env.conns[1])
        env.clock.advance(mm.AWAY_SECS)
        await env.mm.pump()
        assert env.mm._entry(1) is not None
        env.clock.advance(0.5)
        await env.mm.pump()
        assert env.mm._entry(1) is None and 1 not in env.mm.cooldown
        back = FakeConn(1, "P1")
        env.mm.connect(back)
        await env.mm.handle(back, {"type": "queue_join"}, 1)
        assert env.mm._entry(1) is not None
    run(go())


def test_a_reconnect_within_ten_seconds_keeps_the_place():
    async def go():
        env = Env()
        await env.join(1)
        since = env.mm._entry(1).since
        env.mm.disconnect(env.conns[1])
        env.clock.advance(6)
        back = FakeConn(1, "P1")
        env.mm.connect(back)
        state = back.last("queue_state")
        assert state["queued"] and state["since"] == since
        env.clock.advance(20)
        await env.mm.pump()
        assert env.mm._entry(1).since == since
    run(go())


def test_a_disconnected_entry_is_not_matched_while_it_may_come_back():
    async def go():
        env = Env()
        m = None
        for uid in (1, 2, 3, 4):
            await env.join(uid)
        env.mm.disconnect(env.conns[4])
        assert env.mm.tick() == []
        env.mm.connect(FakeConn(4, "P4"))
        m = env.mm.tick()
        assert len(m) == 1
    run(go())


def test_an_accepted_player_whose_socket_is_gone_at_start_aborts_without_a_cooldown():
    async def go():
        env = Env()
        m = await _four(env)
        for uid in (1, 2, 3):
            await env.send(uid, "match_accept", match_id=m.id)
        env.mm.disconnect(env.conns[2])
        await env.send(4, "match_accept", match_id=m.id)
        assert env.started == [] and 2 not in env.mm.cooldown
        assert env.mm._entry(2) is None and env.mm._entry(1).front
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


def test_a_pair_prefers_another_pair_over_closer_solos():
    async def go():
        env = Env()
        await env.pair(1, 2, 1000, 1000)
        await env.send(1, "queue_join")
        await env.join(3, 1000)
        await env.join(4, 1000)
        await env.pair(5, 6, 1080, 1080)
        await env.send(5, "queue_join")
        m = env.mm.tick()[0]
        assert set(m.humans) == {1, 2, 5, 6}
        team = {m.slots[0].user_id, m.slots[2].user_id}
        assert team == {1, 2}
    run(go())


def test_a_pair_with_two_solos_is_never_split():
    async def go():
        env = Env()
        await env.pair(1, 2, 1300, 1300)
        await env.send(1, "queue_join")
        await env.join(3, 1250)
        await env.join(4, 1250)
        m = env.mm.tick()[0]
        assert {m.slots[0].user_id, m.slots[2].user_id} == {1, 2}
    run(go())


def test_a_lone_pair_gets_both_bots_on_the_opposing_team_at_sixty_seconds():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        env.clock.advance(59)
        assert env.mm.tick() == []
        env.clock.advance(1)
        m = env.mm.tick()[0]
        assert [s.user_id for s in m.slots] == [1, None, 2, None]
    run(go())


def test_a_pair_and_a_solo_get_one_bot_partnering_the_solo():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.join(3)
        env.clock.advance(60)
        m = env.mm.tick()[0]
        assert {m.slots[0].user_id, m.slots[2].user_id} == {1, 2}
        assert {m.slots[1].user_id, m.slots[3].user_id} == {3, None}
    run(go())


def test_one_partner_missing_cools_both_and_names_who_missed():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        await env.join(3)
        await env.join(4)
        m = env.mm.tick()[0]
        await env.send(1, "match_accept", match_id=m.id)
        await env.send(3, "match_accept", match_id=m.id)
        await env.send(4, "match_accept", match_id=m.id)
        env.clock.advance(mm.READY_SECS)
        await env.mm.pump()
        for uid in (1, 2):
            removed = env.conns[uid].last("queue_removed")
            assert removed["reason"] == "missed" and removed["by"] == "P2"
            assert env.mm.cooldown[uid] == env.clock() + mm.COOLDOWN_SECS
        assert env.mm._party(1) is not None            # the pair stays formed
        assert env.mm._entry(3).front and m.id not in env.mm.matches
        await env.send(1, "queue_join")
        assert env.conns[1].last("error")["code"] == "cooldown"
    run(go())


def test_parties_expire_after_five_minutes_unless_queued():
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.pair(3, 4)
        await env.send(3, "queue_join")
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
        for kind in ("queue_join", "party_create", "queue_start_bots"):
            await env.mm.handle(guest, {"type": kind}, None)
        assert [m["code"] for m in guest.of("error")] == ["signed_in_only"] * 3
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


def test_concurrent_accepts_ticks_and_start_bots_seat_everyone_once():
    async def go():
        env = Env()
        for uid in range(1, 9):
            await env.join(uid)
        formed = env.mm.tick()
        assert len(formed) == 2
        ids = {u: env.match_of(u).id for u in range(1, 9)}

        async def accept(uid):
            await asyncio.sleep(0)
            await env.send(uid, "match_accept", match_id=ids[uid])

        async def bots(uid):
            await asyncio.sleep(0)
            await env.send(uid, "queue_start_bots")

        async def tick():
            await asyncio.sleep(0)
            env.mm.tick()
            await env.mm.pump()

        await asyncio.gather(*[accept(u) for u in range(1, 9)],
                             *[accept(u) for u in range(1, 9)],
                             *[bots(u) for u in range(1, 9)], tick(), tick())
        seated = [u for _, slots in env.started for u in humans_of(slots)]
        assert sorted(seated) == list(range(1, 9))
        assert len(env.started) == 2 and env.mm.entries == {}
    run(go())


def test_an_accept_after_the_deadline_before_the_pump_does_not_start_a_room():
    async def go():
        env = Env()
        m = await _four(env)
        for uid in (1, 2, 3):
            await env.send(uid, "match_accept", match_id=m.id)
        env.clock.advance(mm.READY_SECS + 0.1)
        await env.send(4, "match_accept", match_id=m.id)
        assert not env.started and m.id not in env.mm.matches
        assert env.conns[4].last("error")["code"] == "stale_match"
        assert env.conns[4].last("queue_removed")["reason"] == "missed"
        assert 4 in env.mm.cooldown
        for uid in (1, 2, 3):
            assert env.mm._entry(uid).front and uid not in env.mm.cooldown
    run(go())


def test_a_decline_after_the_deadline_is_the_timeout_not_a_decline():
    async def go():
        env = Env()
        m = await _four(env)
        await env.send(1, "match_accept", match_id=m.id)
        env.clock.advance(mm.READY_SECS)
        await env.send(2, "match_decline", match_id=m.id, keep_waiting=True)
        assert env.conns[2].last("error")["code"] == "stale_match"
        for uid in (2, 3, 4):
            assert env.conns[uid].last("queue_removed")["reason"] == "missed"
            assert uid in env.mm.cooldown
        assert env.mm._entry(1).front
    run(go())


@pytest.mark.parametrize("kind", ["match_accept", "match_decline"])
@pytest.mark.parametrize("given", ["missing", "wrong"])
def test_an_answer_must_name_the_current_match(kind, given):
    async def go():
        env = Env()
        m = await _four(env)
        fields = {} if given == "missing" else {"match_id": "0" * 12}
        await env.send(1, kind, **fields)
        assert env.conns[1].last("error")["code"] == "stale_match"
        assert env.mm.matches.get(m.id) is m and m.accepted == set()
        assert env.mm._entry(1).match_id == m.id and 1 not in env.mm.cooldown
    run(go())


def test_a_delayed_answer_to_an_earlier_check_cannot_act_on_its_replacement():
    async def go():
        env = Env()
        old = await _four(env)
        await env.send(2, "match_accept", match_id=old.id)
        await env.send(1, "match_decline", match_id=old.id)
        await env.join(5)
        new = env.mm.tick()[0]
        assert old.id != new.id and 2 in new.humans
        await env.send(2, "match_accept")
        await env.send(2, "match_accept", match_id=old.id)
        await env.send(2, "match_decline", match_id=old.id)
        assert env.mm.matches.get(new.id) is new and 2 not in new.accepted
        assert env.conns[2].last("error")["code"] == "stale_match"
        assert env.mm._entry(2).match_id == new.id
    run(go())


def test_a_decline_gives_front_priority_only_to_players_who_accepted():
    async def go():
        env = Env()
        m = await _four(env)
        await env.send(2, "match_accept", match_id=m.id)
        await env.send(1, "match_decline", match_id=m.id)
        assert env.mm._entry(2).front
        for uid in (3, 4):
            e = env.mm._entry(uid)
            assert not e.front and uid not in env.mm.cooldown
            assert e.since == m.entries[uid - 1].since
    run(go())


@pytest.mark.parametrize("accepted, front", [((1,), False), ((1, 2), True)])
def test_a_pair_goes_to_the_front_only_if_both_partners_accepted(accepted, front):
    async def go():
        env = Env()
        await env.pair(1, 2)
        await env.send(1, "queue_join")
        since = env.mm._entry(1).since
        await env.join(3)
        await env.join(4)
        m = env.mm.tick()[0]
        for uid in accepted:
            await env.send(uid, "match_accept", match_id=m.id)
        await env.send(3, "match_decline", match_id=m.id)
        e = env.mm._entry(1)
        assert e is env.mm._entry(2) and e.match_id is None
        assert e.front is front and e.since == since
        assert 1 not in env.mm.cooldown and 2 not in env.mm.cooldown
        for uid in (1, 2):
            assert env.conns[uid].last("queue_state")["front"] is front
    run(go())


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)


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
        m = await _four(env)
        for c in env.conns.values():
            c.ws = _FakeWS()
        for uid in range(1, 5):
            await env.send(uid, "match_accept", match_id=m.id)
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
            assert e is not None and e.front and e.match_id is None
            assert c.last("match_cancelled")["reason"] == "server_error"
        again = env.mm.tick()
        assert len(again) == 1 and set(again[0].humans) == {1, 2, 3, 4}
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
        m = await _four(env)
        for c in env.conns.values():
            c.ws = _FakeWS()
        for uid in range(1, 5):
            await env.send(uid, "match_accept", match_id=m.id)
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


@pytest.mark.parametrize("heartbeat", [False, True])
def test_ws_four_players_match_accept_and_land_in_a_started_rated_room(wsenv, heartbeat):
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
        for ws in socks:
            ws.send_json({"type": "queue_join"})
            assert _drain(ws, "queue_state")["queued"] is True
        clock.advance(40)
        _pump(client, srv)
        match = [_drain(ws, "match") for ws in socks]
        assert {m["match_id"] for m in match} == {match[0]["match_id"]}
        assert match[0]["size"] == 4 and match[0]["bots"] == 0
        for ws in socks:
            ws.send_json({"type": "match_accept", "match_id": match[0]["match_id"]})
        for ws in socks:
            started = _drain(ws, "match_started", tries=80)
        code = started["room"]
        state = _drain(d, "state", tries=80)
        assert state["matched"] is True and state["room"] == code
        room = srv.rooms[code]
        by_seat = [s.user_id for s in room.seats]
        uid = [u for u, _ in users]
        # 1400 + 1000 vs 1200 + 1200; the anchor (first to join) at seat 0.
        assert by_seat == [uid[0], uid[1], uid[3], uid[2]]
        assert room.game is not None and room.matched
        assert room.ratings is not None
        assert room.ratings.present == {0: uid[0], 1: uid[1], 2: uid[3], 3: uid[2]}
        # The adopted socket plays on as a seated socket: chat reaches the room.
        if heartbeat:
            a.send_json({"type": "ping", "nonce": 2})
            assert _drain(a, "pong", tries=400)["nonce"] == 2
            assert [s.user_id for s in room.seats] == by_seat
        a.send_json({"type": "chat", "text": "gl"})
        assert _drain(b, "chat", tries=400)["text"] == "gl"
        assert srv.MATCHMAKER.entries == {}


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


def test_ws_decline_cools_down_and_refuses_an_early_join(wsenv):
    srv, store, client, clock = wsenv
    users = [_user(store, f"d{i}") for i in range(4)]
    with client.websocket_connect("/ws", headers=users[0][1]) as a, \
            client.websocket_connect("/ws", headers=users[1][1]) as b, \
            client.websocket_connect("/ws", headers=users[2][1]) as c, \
            client.websocket_connect("/ws", headers=users[3][1]) as d:
        socks = [a, b, c, d]
        for ws in socks:
            ws.send_json({"type": "queue_join"})
            _drain(ws, "queue_state")
        _pump(client, srv)
        match_id = [_drain(ws, "match")["match_id"] for ws in socks][0]
        a.send_json({"type": "match_accept", "match_id": match_id})
        _drain(a, "match_ready")
        d.send_json({"type": "match_decline", "match_id": match_id})
        removed = _drain(d, "queue_removed")
        assert removed["reason"] == "declined"
        assert removed["cooldown_until"] == clock() + mm.COOLDOWN_SECS
        d.send_json({"type": "queue_join"})
        assert _drain(d, "error")["code"] == "cooldown"
        back = _drain(a, "queue_state")
        assert back["queued"] and back["front"] is True
        waited = _drain(b, "queue_state")
        assert waited["queued"] and waited["front"] is False


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
    assert srv.MATCHMAKER._entry(uid) is None and uid not in srv.MATCHMAKER.cooldown


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
