"""Ratings for signed-in players (``shengji.api.ratings``).

The maths is checked with worked numbers; rounds are played in-process with
the heuristic bot on every seat through the server's own round functions,
so the hooks see exactly what a live room gives them, and the rating write
runs inline (no event loop), as a queued write would.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing

import pytest

from tests.test_accounts import _claims, _session_cookie, accounts_on, keypair  # noqa: F401
from tests.test_server_ws import _drain, client  # noqa: F401


def _user(store, sub, name=None):
    user = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com", name=name or sub.title()))
    return user["id"], {"cookie": f"sj_session={store.create_session(user['id'])}"}


def _events(store, sql="SELECT * FROM rating_events ORDER BY id", *args):
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql, args)]


def _set(store, user_id, rating, rounds=0):
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("UPDATE users SET rating = ?, rated_rounds = ? WHERE id = ?",
                   (rating, rounds, user_id))
        db.commit()


class Table:
    """A room whose four seats the test assigns (an int is a signed-in human,
    None a guest, "bot" a bot), played in-process."""

    def __init__(self, srv, seats, code="RATE"):
        from shengji.engine.game import Game

        self.srv = srv
        self.room = srv.Room(code=code)
        self.room.seats = [
            srv.Seat(name=f"Bot {i}", is_bot=True) if s == "bot"
            else srv.Seat(name=f"P{i}", user_id=s, connected=True)
            for i, s in enumerate(seats)]
        self.room.game = Game(start_level="2", games_to_win=None)

    def start_round(self, banker=None):
        from shengji.api import ratings

        room = self.room
        first = room.game.round_no == 0
        if banker is not None:
            room.game.banker = banker
        room.game.start_round()
        room.index_round()
        if first:
            room.saved_game = None
            ratings.start(room)
        else:
            ratings.round_started(room)
        rnd = room.round
        while rnd.phase == "deal":
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code
        rnd.finalize_declare()
        if rnd.banker is None:
            rnd.banker = banker or 0

    def finish(self):
        """Play the round out with the bot on every seat."""
        srv, room = self.srv, self.room
        while room.round.phase in ("bury", "play"):
            seat = room.round.banker if room.round.phase == "bury" else room.round.turn
            assert srv.bot_step(room, seat)
        return room.game.result

    def play_round(self, banker=None):
        self.start_round(banker)
        return self.finish()


def _force_outcome(monkeypatch, attacker_points):
    """Pin the round's final attacker points so the outcome is known."""
    from shengji.engine.game import Game

    real = Game.finish_round

    def finish_round(self):
        self.round.attacker_points = attacker_points
        return real(self)

    monkeypatch.setattr(Game, "finish_round", finish_round)


@pytest.fixture()
def env(accounts_on, client):
    from shengji.api import ratings, server as srv

    ratings.LIMITER.reset()
    return srv, accounts_on.STORE, client


# ------------------------------------------------------------------- maths
def test_expected_score_and_round_score_worked_numbers():
    from shengji.api import ratings as r

    assert r.expected_score(1000, 1000) == pytest.approx(0.5)
    # 40 points of banker advantage between otherwise equal teams
    assert r.expected_score(1040, 1000) == pytest.approx(0.557312, abs=1e-6)
    assert r.expected_score(1000, 1400) == pytest.approx(1 / 11, abs=1e-9)
    assert r.round_score(True, 1) == pytest.approx(2 / 3)
    assert r.round_score(True, 2) == pytest.approx(5 / 6)
    assert r.round_score(True, 3) == pytest.approx(1.0)
    assert r.round_score(True, 5) == pytest.approx(1.0)
    assert r.round_score(False, 1) == pytest.approx(1 / 3)
    assert r.round_score(False, 3) == pytest.approx(0.0)
    # attackers taking the deal at 80..115 points gain no level
    assert r.round_score(True, 0) == pytest.approx(0.6)
    assert r.round_score(False, 0) == pytest.approx(0.4)
    assert r.k_factor(0) == 40 and r.k_factor(19) == 40 and r.k_factor(20) == 20


def test_team_strength_is_the_seat_mean_plus_the_banker_side():
    from shengji.api import ratings as r

    assert r.team_strengths([1100, 1000, 1000, 1000], banker_team=0) == (1090.0, 1000.0)
    assert r.team_strengths([1100, 1000, 1000, 1000], banker_team=1) == (1050.0, 1040.0)


def test_new_accounts_bots_and_guests_all_start_at_1000():
    from shengji.api import accounts, ratings as r

    assert r.START_RATING == r.BOT_RATING == r.GUEST_RATING == accounts.START_RATING == 1000.0


def test_engine_level_change_is_zero_for_an_attacker_takeover(monkeypatch):
    """The 0.6 case exists: attackers with 80..115 points win, gaining 0 levels."""
    from shengji.engine.game import Game
    from shengji.engine.round import Round

    game = Game(start_level="2", games_to_win=None)
    game.banker = 0
    game.round = Round("2", 0, game.rng)
    game.round.phase = "round_end"
    game.round.attacker_points = 100
    result = game.finish_round()
    assert result.winner_team == 1 and result.level_change == 0


# ------------------------------------------------------------- rated rounds
def test_a_signed_in_player_vs_bots_gets_the_worked_delta(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "solo")
    _force_outcome(monkeypatch, 30)            # bankers hold, attackers 30: +2 levels
    table = Table(srv, [uid, "bot", "bot", "bot"])
    result = table.play_round(banker=0)
    assert result.winner_team == 0 and result.level_change == 2
    [event] = _events(store)
    assert event["user_id"] == uid and event["team"] == 0 and event["banker_team"] == 1
    assert event["expected"] == pytest.approx(0.557312, abs=1e-6)
    assert event["actual"] == pytest.approx(5 / 6)
    assert event["k"] == 40
    assert event["delta"] == pytest.approx(40 * (5 / 6 - 0.557312), abs=1e-4)   # +11.04
    assert event["delta"] == pytest.approx(11.04, abs=0.005)
    assert event["rating_before"] == 1000
    assert event["rating_after"] == pytest.approx(1000 + event["delta"])
    assert store.user(uid)["rating"] == pytest.approx(event["rating_after"])
    assert store.user(uid)["rated_rounds"] == 1
    assert event["levels"] == 2 and event["won"] == 1 and event["partner_bot"] == 1
    assert event["opponents_bots"] == 2


def test_banker_adjustment_goes_to_the_banker_side(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "attacker")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.play_round(banker=1)                 # the bots defend
    [event] = _events(store)
    assert event["banker_team"] == 0 and event["won"] == 0
    assert event["expected"] == pytest.approx(1 - 0.557312, abs=1e-6)
    assert event["actual"] == pytest.approx(1 / 6)
    assert event["levels"] == -2


def test_partners_move_in_lockstep_and_bots_and_guests_are_never_rated(env, monkeypatch):
    srv, store, _ = env
    a, _ = _user(store, "alice")
    b, _ = _user(store, "bob")
    _set(store, a, 1100, rounds=30)
    _set(store, b, 1000, rounds=30)
    _force_outcome(monkeypatch, 130)           # attackers 130: they win 1 level
    table = Table(srv, [a, None, b, "bot"])
    result = table.play_round(banker=1)
    assert result.winner_team == 0 and result.level_change == 1
    events = _events(store)
    assert sorted(e["user_id"] for e in events) == [a, b]
    da, db = (e["delta"] for e in sorted(events, key=lambda e: e["user_id"]))
    assert da == pytest.approx(db)
    # team 0 = (1100 + 1000) / 2 = 1050; team 1 = guest 1000 + bot 1000, banker +40
    exp = 1 / (1 + 10 ** ((1040 - 1050) / 400))
    assert events[0]["expected"] == pytest.approx(exp)
    assert da == pytest.approx(20 * (2 / 3 - exp))
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_a_guest_seat_counts_1000_whatever_the_guest_is_called(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "host")
    _force_outcome(monkeypatch, 30)
    Table(srv, [uid, None, None, None]).play_round(banker=0)
    [event] = _events(store)
    assert event["expected"] == pytest.approx(0.557312, abs=1e-6)
    assert event["partner_bot"] == 0 and event["partner"] == "P2" and event["opponents_bots"] == 0


def test_a_provisional_player_moves_faster_than_an_established_partner(env, monkeypatch):
    srv, store, _ = env
    new, _ = _user(store, "newbie")
    old, _ = _user(store, "veteran")
    _set(store, old, 1000, rounds=40)
    _force_outcome(monkeypatch, 30)
    Table(srv, [new, "bot", old, "bot"]).play_round(banker=0)
    by = {e["user_id"]: e for e in _events(store)}
    # the veteran's K halves because the partner is provisional
    assert by[new]["k"] == 40 and by[old]["k"] == 10
    assert by[new]["delta"] == pytest.approx(4 * by[old]["delta"])


@pytest.mark.parametrize("seats", [
    ["me", "bot", "bot", "bot"],          # alone with bots
    ["me", "bot", "vet", "bot"],          # an established partner
    ["me", "vet", "bot", "vet2"],         # established opponents
    ["me", None, "bot", "bot"],           # a guest in a casual room
])
def test_k_is_unchanged_when_no_other_rated_player_is_provisional(env, monkeypatch, seats):
    srv, store, _ = env
    ids = {}
    for name in ("me", "vet", "vet2"):
        ids[name], _ = _user(store, name)
        _set(store, ids[name], 1000, rounds=40)
    _force_outcome(monkeypatch, 30)
    Table(srv, [ids.get(s, s) if isinstance(s, str) else s for s in seats]).play_round(banker=0)
    assert {e["k"] for e in _events(store)} == {20}


@pytest.mark.parametrize("other_seat", [1, 2])     # an opponent, the partner
def test_k_halves_when_another_rated_player_is_provisional(env, monkeypatch, other_seat):
    from shengji.api import ratings

    srv, store, _ = env
    vet, _ = _user(store, "vet")
    newer, _ = _user(store, "newer")
    _set(store, vet, 1000, rounds=40)
    _set(store, newer, 1000, rounds=ratings.PROVISIONAL_ROUNDS - 1)
    _force_outcome(monkeypatch, 30)
    seats = [vet, "bot", "bot", "bot"]
    seats[other_seat] = newer
    Table(srv, seats).play_round(banker=0)
    by = {e["user_id"]: e for e in _events(store)}
    assert by[vet]["k"] == ratings.K_ESTABLISHED / 2
    assert by[newer]["k"] == ratings.K_PROVISIONAL          # the veteran is established
    assert by[vet]["delta"] == pytest.approx(ratings.K_ESTABLISHED / 2
                                             * (by[vet]["actual"] - by[vet]["expected"]))


def test_two_provisional_players_halve_each_other(env, monkeypatch):
    srv, store, _ = env
    a, _ = _user(store, "anna")
    b, _ = _user(store, "bert")
    _force_outcome(monkeypatch, 30)
    Table(srv, [a, "bot", b, "bot"]).play_round(banker=0)
    assert {e["k"] for e in _events(store)} == {20}


def test_a_rated_round_is_never_rated_twice(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "once")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    result = table.play_round(banker=0)
    rec = ratings.build_record(table.room, table.room.ratings, result)
    assert ratings.apply_round(store, rec) == {}
    assert len(_events(store)) == 1 and store.user(uid)["rated_rounds"] == 1


def test_experimental_rooms_are_not_rated(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "tester")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.experimental_policy = "w32"
    table.play_round(banker=0)
    assert table.room.ratings is None and _events(store) == []


# --------------------------------------------------------- frozen at start
def test_seat_ratings_are_read_when_the_round_starts(env, monkeypatch):
    """A partner's rating that moves mid-round (a round finished at another
    table) does not change this round's expected score."""
    from shengji.api import ratings

    srv, store, _ = env
    a, _ = _user(store, "alice")
    b, _ = _user(store, "bob")
    _set(store, a, 1000, rounds=30)
    _set(store, b, 1000, rounds=30)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, "bot", b, "bot"])
    table.start_round(banker=0)
    ratings.flush()                     # the round-start read has run
    _set(store, b, 1400, rounds=31)
    table.finish()
    by = {e["user_id"]: e for e in _events(store)}
    assert by[a]["expected"] == pytest.approx(0.557312, abs=1e-6)
    assert by[b]["expected"] == pytest.approx(0.557312, abs=1e-6)
    # each account's own rating moves from where it stands now
    assert by[b]["rating_before"] == 1400


def test_a_mid_round_claimant_does_not_change_the_round_for_the_others(env, monkeypatch):
    srv, store, _ = env
    host, _ = _user(store, "host")
    strong, _ = _user(store, "strong")
    _set(store, host, 1000, rounds=30)
    _set(store, strong, 1600, rounds=5)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [host, "bot", "bot", "bot"])
    table.start_round(banker=0)
    _claim(table.room.seats[1], strong, "Strong")
    table.finish()
    [event] = _events(store)
    assert event["user_id"] == host
    assert event["expected"] == pytest.approx(0.557312, abs=1e-6)   # seat 1 was a bot
    assert event["k"] == 20             # the provisional claimant was not in the round


def test_a_round_started_with_a_guest_at_a_ranked_table_is_not_rated(env, monkeypatch):
    srv, store, _ = env
    a, _ = _user(store, "alice")
    b, _ = _user(store, "bob")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, None, b, "bot"])
    table.room.matched = True
    table.play_round(banker=0)
    assert _events(store) == []
    assert store.user(a)["rated_rounds"] == 0 and store.user(a)["rating"] == 1000
    # Once the guest's seat is a bot again, the next round is rated.
    table.room.seats[1].is_bot = True
    table.play_round()
    assert sorted(e["user_id"] for e in _events(store)) == sorted([a, b])


def test_a_ranked_table_of_signed_in_players_is_rated_as_before(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "solo")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.matched = True
    table.play_round(banker=0)
    [event] = _events(store)
    assert event["delta"] == pytest.approx(11.04, abs=0.005)


# -------------------------------------------------------- ranked join
# A ranked table is filled by the queue and rated for signed-in players only:
# a guest is refused with ``ranked_sign_in``, another account with
# ``ranked_queue_only``, and the account holding a seat comes back to it.
# Casual rooms keep their open join (``test_server_ws``).
@pytest.fixture()
def queue_env(env):
    """``env`` with the server's queue emptied before and after."""
    srv = env[0]
    srv.MATCHMAKER.reset()
    try:
        yield env
    finally:
        srv.MATCHMAKER.reset()


def _ranked_solo(srv, a):
    a.send_json({"type": "queue_join"})
    _drain(a, "queue_state")
    a.send_json({"type": "queue_start_bots"})
    started = _drain(a, "match_started", tries=40)
    assert started["rated"] is True
    return started["room"], srv.rooms[started["room"]].seats[0].token


def _seats(room):
    return [(s.name, s.is_bot, s.user_id) for s in room.seats]


def test_a_guest_cannot_join_a_ranked_room(queue_env):
    srv, store, client = queue_env
    uid, headers = _user(store, "owner", "Owner")
    with client.websocket_connect("/ws", headers=headers) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        before = _seats(room)
        with client.websocket_connect("/ws") as g:
            g.send_json({"type": "join_room", "room": code, "name": "Guest"})
            assert _drain(g, "error")["code"] == "ranked_sign_in"
            g.send_json({"type": "join_room", "room": code, "name": "Guest", "seat": 1})
            assert _drain(g, "error")["code"] == "ranked_sign_in"
        assert _seats(room) == before


def test_another_account_cannot_join_a_ranked_room_by_code(queue_env):
    srv, store, client = queue_env
    _, h1 = _user(store, "owner", "Owner")
    _, h2 = _user(store, "other", "Other")
    with client.websocket_connect("/ws", headers=h1) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        before = _seats(room)
        with client.websocket_connect("/ws", headers=h2) as b:
            b.send_json({"type": "join_room", "room": code, "name": "Other"})
            assert _drain(b, "error")["code"] == "ranked_queue_only"
            # typing the holder's name is not a way in either
            b.send_json({"type": "join_room", "room": code, "name": "Owner"})
            assert _drain(b, "error")["code"] == "ranked_queue_only"
        assert _seats(room) == before


def test_the_seat_holder_comes_back_with_or_without_a_token(queue_env):
    srv, store, client = queue_env
    uid, headers = _user(store, "owner", "Owner")
    with client.websocket_connect("/ws", headers=headers) as a:
        code, token = _ranked_solo(srv, a)
    room = srv.rooms[code]
    with client.websocket_connect("/ws", headers=headers) as again:
        again.send_json({"type": "join_room", "room": code, "name": "Owner", "token": token})
        state = _drain(again, "state", tries=80)
        assert state["room"] == code and state["you"] == 0
    with client.websocket_connect("/ws", headers=headers) as other_device:
        other_device.send_json({"type": "join_room", "room": code, "name": "Phone"})
        state = _drain(other_device, "state", tries=80)
        assert state["room"] == code and state["you"] == 0
    assert room.seats[0].user_id == uid and [s.is_bot for s in room.seats[1:]] == [True] * 3



# ------------------------------------------------------------------ abandon
def test_leaving_mid_round_rates_that_round_only_with_a_winning_result_capped(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    quitter, _ = _user(store, "quitter")
    partner, _ = _user(store, "stayer")
    _force_outcome(monkeypatch, 30)            # their team wins by 2 anyway
    table = Table(srv, [quitter, "bot", partner, "bot"])
    table.start_round(banker=0)
    seat = table.room.seats[0]
    ratings.seat_left(table.room, 0)
    seat.connected = False
    table.finish()
    by = {e["user_id"]: e for e in _events(store)}
    assert by[quitter]["abandoned"] == 1 and by[quitter]["actual"] == ratings.LEAVER_SCORE_CAP
    assert by[quitter]["won"] == 0
    assert by[partner]["abandoned"] == 0 and by[partner]["delta"] > 0
    assert by[quitter]["delta"] < by[partner]["delta"]
    # The next round, with the bot covering the absent seat, rates only the partner.
    seat.bot_announced = True
    table.play_round()
    assert [e["user_id"] for e in _events(store) if e["round_no"] == 2] == [partner]


@pytest.mark.parametrize("leaver_seat, attacker_points, actual", [
    # banker team (seats 0 and 2) defends; the leaver's real result, capped at 0.5
    (0, 0, 0.5),          # defenders +3: a 1.0 win, capped
    (0, 35, 0.5),         # defenders +2: 0.833, capped
    (0, 90, 0.4),         # attackers take over: a loss counts as it happened
    (0, 165, 1 / 6),      # attackers +2
    (1, 60, 1 / 3),       # attacker leaves, defenders +1
    (1, 0, 0.0),          # attacker leaves, defenders +3
    (1, 100, 0.5),        # attackers take over: 0.6, capped
    (1, 210, 0.5),        # attackers +3: 1.0, capped
])
def test_a_leaver_scores_the_real_result_capped_at_a_draw(env, monkeypatch, leaver_seat,
                                                          attacker_points, actual):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "leaver")
    _force_outcome(monkeypatch, attacker_points)
    users = ["bot", "bot", "bot", "bot"]
    users[leaver_seat] = uid
    table = Table(srv, users)
    table.start_round(banker=0)
    ratings.seat_left(table.room, leaver_seat)
    table.room.seats[leaver_seat].connected = False
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["won"] == 0
    assert event["actual"] == pytest.approx(actual)


def test_a_bot_takeover_after_a_disconnect_is_an_abandon(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "dropper")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.room.seats[0].connected = False
    table.room.seats[0].bot_announced = True
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["actual"] == 0.5    # a 2-level win, capped


def test_a_blip_inside_the_takeover_window_is_still_a_normal_round(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "blipper")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.room.seats[0].connected = False      # dropped, bot not yet covering
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 0 and event["won"] == 1


def test_leaving_and_returning_before_the_round_ends_is_not_an_abandon(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "returner")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    ratings.seat_left(table.room, 0)
    table.finish()                             # still connected at the end
    [event] = _events(store)
    assert event["abandoned"] == 0


def _claim(seat, uid, name):
    """What the server's mid-game seat claim does to the seat it hands over."""
    seat.bot_announced = False
    seat.is_bot = False
    seat.name = name
    seat.user_id = uid
    seat.connected = True


def test_a_bot_seat_claimed_mid_round_is_rated_from_the_next_round(env, monkeypatch):
    srv, store, _ = env
    host, _ = _user(store, "host")
    late, _ = _user(store, "latecomer")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [host, "bot", "bot", "bot"])
    table.start_round(banker=0)
    _claim(table.room.seats[1], late, "Late")
    table.finish()
    assert [e["user_id"] for e in _events(store)] == [host]
    assert store.user(late)["rated_rounds"] == 0 and store.user(late)["rating"] == 1000
    # Seated when the next round starts, the claimant is rated for it.
    table.play_round()
    second = sorted(e["user_id"] for e in _events(store) if e["round_no"] == 2)
    assert second == sorted([host, late])
    assert store.user(late)["rated_rounds"] == 1


def test_a_dropped_seat_taken_over_mid_round_rates_only_the_original_abandon(env, monkeypatch):
    srv, store, _ = env
    orig, _ = _user(store, "original")
    taker, _ = _user(store, "taker")
    _force_outcome(monkeypatch, 30)            # the seat's team wins by 2
    table = Table(srv, [orig, "bot", "bot", "bot"])
    table.start_round(banker=0)
    seat = table.room.seats[0]
    seat.connected = False
    seat.bot_announced = True
    _claim(seat, taker, "Taker")
    table.finish()
    [event] = _events(store)
    assert event["user_id"] == orig and event["abandoned"] == 1 and event["actual"] == 0.5
    assert store.user(taker)["rated_rounds"] == 0
    table.play_round()
    assert [e["user_id"] for e in _events(store) if e["round_no"] == 2] == [taker]


def test_a_late_claimant_who_leaves_mid_round_is_not_rated(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    host, _ = _user(store, "host")
    late, _ = _user(store, "passer")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [host, "bot", "bot", "bot"])
    table.start_round(banker=0)
    _claim(table.room.seats[1], late, "Passer")
    ratings.seat_left(table.room, 1)
    table.room.seats[1].connected = False
    table.finish()
    assert [e["user_id"] for e in _events(store)] == [host]


def test_recent_games_split_at_each_game_boundary_losses_included(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "tabler")
    _force_outcome(monkeypatch, 30)            # the bankers always hold
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.game.level_idx = [0, 12]        # the bots defend on Ace and win the game
    first = table.play_round(banker=1)
    assert first.point_scored
    table.play_round(banker=0)                 # the next game at the same table
    table.room.game.level_idx[0] = 12
    table.play_round(banker=0)                 # holding Ace: the player wins that game
    table.play_round(banker=0)                 # and a third game begins
    games = ratings.stats(store, uid)["recent_games"]
    assert len(games) == 3
    assert [g["rounds"] for g in games] == [1, 2, 1]
    assert [g["games_won"] for g in games] == [0, 1, 0]


def _three_games(srv, store, uid, monkeypatch, clock):
    """A lost game (1 round), a won game (2 rounds), then one round of a third,
    with each rating write stamped by ``clock``."""
    from types import SimpleNamespace

    from shengji.api import ratings

    stamps = iter(clock)
    monkeypatch.setattr(ratings, "time", SimpleNamespace(time=lambda: next(stamps)))
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.game.level_idx = [0, 12]
    table.play_round(banker=1)                 # lost: the bots hold on Ace
    table.play_round(banker=0)
    table.room.game.level_idx[0] = 12
    table.play_round(banker=0)                 # won: the player holds on Ace
    table.play_round(banker=0)                 # the third game's first round
    return ratings.stats(store, uid, now=10_000)["recent_games"]


@pytest.mark.parametrize("clock", [
    [777, 777, 777, 777],                      # every game ended in the same second
    [100, 200, 200, 200],                      # the later two share a second
    [100, 100, 100, 200],                      # the earlier two share a second
])
def test_recent_games_list_latest_first_even_within_one_second(env, monkeypatch, clock):
    srv, store, _ = env
    uid, _ = _user(store, "ties")
    games = _three_games(srv, store, uid, monkeypatch, clock)
    # latest first: the third game (a won round), the won game, the lost game
    assert [(g["rounds"], g["games_won"]) for g in games] == [(1, 0), (2, 1), (1, 0)]
    assert games[0]["delta"] > 0 and games[2]["delta"] < 0
    assert all("_last_event" not in g for g in games)


def test_leave_room_over_the_socket_marks_the_round_abandoned(env, keypair):
    srv, store, client = env
    private_pem, _ = keypair
    cookie = _session_cookie(srv.accounts, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "create_room", "name": "Jerry"})
        code = _drain(a, "room")["room"]
        for _ in range(3):
            a.send_json({"type": "add_bot"})
        a.send_json({"type": "start_game"})
        _drain(a, "state", tries=60)
        room = srv.rooms[code]
        assert room.ratings is not None and room.ratings.present == {0: 1}
        a.send_json({"type": "leave_room"})
        _drain(a, "left", tries=200)
        assert room.ratings.left == {1: 0}


# ------------------------------------------------------- round-end payload
def test_the_round_result_carries_only_the_seats_own_rating(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "viewer")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, None, "bot", "bot"])
    table.room.seats[1].connected = True
    table.play_round(banker=0)
    mine = srv.state_for(table.room, 0)["round_result"]
    guest = srv.state_for(table.room, 1)["round_result"]
    [event] = _events(store)
    assert mine["rating"] == {"rating": round(event["rating_after"]), "delta": round(event["delta"])}
    assert "rating" not in guest
    assert "example.com" not in str(srv.state_for(table.room, 0))


def test_the_game_total_shows_on_the_round_that_wins_a_game(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "winner")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.play_round(banker=0)
    assert "game_delta" not in srv.state_for(table.room, 0)["round_result"]["rating"]
    table.room.game.level_idx = [12, 0]        # holding Ace: the next defence wins the game
    result = table.play_round(banker=0)
    assert result.point_scored
    line = srv.state_for(table.room, 0)["round_result"]["rating"]
    total = sum(e["delta"] for e in _events(store))
    assert line["game_delta"] == round(total)
    [won] = [e for e in _events(store) if e["round_no"] == 2]
    assert won["game_won"] == 1
    # The next game starts its total afresh.
    table.play_round(banker=0)
    assert table.room.ratings.game_delta[uid] == pytest.approx(_events(store)[-1]["delta"])


def test_a_queued_write_rebroadcasts_the_room(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "async")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    sent = []

    async def fake_broadcast(room):
        sent.append(srv.state_for(room, 0)["round_result"].get("rating"))

    monkeypatch.setattr(srv, "broadcast", fake_broadcast)

    async def go():
        table.finish()                         # round_ended queues the write
        for _ in range(200):
            if sent:
                return
            await asyncio.sleep(0.01)

    asyncio.run(go())
    ratings.flush()
    assert sent and sent[0]["delta"] == round(_events(store)[0]["delta"])


# -------------------------------------------------------- leaderboard / API
def _seed(store, now, specs):
    """specs: (sub, name, rating, rounds, levels, age_seconds, visible)."""
    ids = {}
    with closing(store._open()) as conn:
        for sub, name, rating, rounds, levels, age, visible in specs:
            conn.execute(
                """INSERT INTO users(google_sub, email, name, created_at, last_login_at,
                                     rating, rated_rounds, leaderboard_visible)
                   VALUES (?, ?, ?, 0, 0, ?, ?, ?)""",
                (sub, f"{sub}@example.com", name, rating, rounds, 1 if visible else 0))
            uid = conn.execute("SELECT id FROM users WHERE google_sub = ?", (sub,)).fetchone()[0]
            ids[sub] = uid
            for i in range(rounds):
                conn.execute(
                    """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                           banker_team, won, levels, expected, actual, k, rating_before,
                           rating_after, delta)
                       VALUES (?, ?, ?, ?, 0, ?, ?, ?, 0.5, 1, 20, ?, ?, 2.0)""",
                    (f"g-{sub}", i + 1, uid, int(now - age), i % 2, 1 if levels > 0 else 0,
                     levels, rating - 2, rating))
    return ids


def test_leaderboard_orders_by_rating_with_top_20_and_the_viewers_own_row(env):
    from shengji.api import ratings

    srv, store, _ = env
    now = time.time()
    specs = [(f"p{i:02d}", f"Pl{i:02d} Smith", 2000 - 10 * i, 25, 1, 3600, True) for i in range(24)]
    specs.append(("low", "Lowly", 1100, 5, -1, 3600, True))
    specs.append(("hidden", "Hidden", 2500, 30, 1, 3600, False))
    specs.append(("stale", "Stale", 2400, 30, 1, 30 * 86400, True))
    ids = _seed(store, now, specs)
    board = ratings.leaderboard(store, "all", ids["low"], now=now)
    names = [row["name"] for row in board["players"]]
    assert len(names) == 20 and names[0] == "Stale" and "Hidden" not in names
    assert names[1:3] == ["Pl00", "Pl01"]       # first names only
    assert [r["rank"] for r in board["players"]] == list(range(1, 21))
    ratings_shown = [r["rating"] for r in board["players"]]
    assert ratings_shown == sorted(ratings_shown, reverse=True)
    assert board["me"]["rank"] == 26 and board["me"]["rating"] == 1100
    assert board["me"]["provisional"] is True and board["me"]["levels_per_round"] == -1.0
    assert board["anchor"] == {"name": "Sheng Ji bot", "rating": 1000}
    week = ratings.leaderboard(store, "week", None, now=now)
    assert "Stale" not in [r["name"] for r in week["players"]] and week["me"] is None
    assert week["players"][0]["week_delta"] == 50       # 25 rounds of +2 this week


def test_an_opted_out_viewer_still_sees_their_own_row(env):
    from shengji.api import ratings

    srv, store, _ = env
    now = time.time()
    ids = _seed(store, now, [("a", "Ann", 1700, 3, 1, 60, True),
                             ("b", "Bea", 1800, 3, 1, 60, False)])
    board = ratings.leaderboard(store, "all", ids["b"], now=now)
    assert [r["name"] for r in board["players"]] == ["Ann"]
    assert board["me"]["name"] == "Bea" and board["me"]["rank"] == 1
    assert board["me"]["visible"] is False


def test_api_leaderboard_stats_and_visibility(env, monkeypatch):
    srv, store, client = env
    uid, headers = _user(store, "jerry", name="Jerry Yu")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    for _ in range(3):
        table.play_round(banker=0)

    assert client.get("/api/me/stats").status_code == 401
    assert client.post("/api/me/leaderboard-visibility", json={"visible": False}).status_code == 401
    assert client.get("/api/leaderboard?period=month").status_code == 400

    anon = client.get("/api/leaderboard?period=all").json()
    assert anon["me"] is None and anon["players"][0]["name"] == "Jerry"

    board = client.get("/api/leaderboard?period=week", headers=headers).json()
    [row] = board["players"]
    assert row["you"] is True and row["rounds"] == 3 and row["provisional"] is True
    assert board["me"]["rank"] == 1
    assert set(row) == {"rank", "name", "rating", "rounds", "levels_per_round",
                        "week_delta", "provisional", "you"}

    stats = client.get("/api/me/stats", headers=headers).json()
    assert stats["rounds"] == 3 and stats["rank"] == 1 and stats["won_pct"] == 100.0
    assert stats["defender_won_pct"] == 100.0 and stats["attacker_won_pct"] is None
    assert stats["best_streak"] == 3 and stats["levels_per_round"] == 2.0
    assert stats["games_won"] == 0 and stats["visible"] is True
    assert len(stats["history"]) == 4 and stats["history"][0] == 1000
    assert stats["history"][-1] == stats["rating"] > 1000
    [game] = stats["recent_games"]
    assert game["rounds"] == 3 and game["partner_bot"] is True and game["opponents_bots"] == 2
    assert abs(game["delta"] - (stats["rating"] - 1000)) <= 1

    off = client.post("/api/me/leaderboard-visibility", json={"visible": False}, headers=headers)
    assert off.json() == {"visible": False}
    assert client.get("/api/leaderboard?period=all").json()["players"] == []
    assert client.get("/api/me/stats", headers=headers).json()["visible"] is False

    for body in (anon, board, stats):
        assert "example.com" not in str(body) and "email" not in str(body)
        assert "user_id" not in str(body) and "google_sub" not in str(body)


def test_deleting_an_account_removes_its_rating_events(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "leaver")
    _force_outcome(monkeypatch, 30)
    Table(srv, [uid, "bot", "bot", "bot"]).play_round(banker=0)
    assert len(_events(store)) == 1
    assert store.delete_user(uid)
    assert _events(store) == []


# ---------------------------------------------------------------- migration
def test_a_v3_database_gains_the_rating_tables_idempotently(accounts_on, tmp_path):
    path = tmp_path / "v3" / "accounts.sqlite3"
    path.parent.mkdir(parents=True)
    old = accounts_on.Store(path)
    real = list(accounts_on.SCHEMA)
    accounts_on.SCHEMA[:] = real[:3]
    try:
        assert old.schema_version() == 3
        # A v3 database has no rating column, so its row is written by hand.
        with closing(sqlite3.connect(path)) as db:
            db.execute("""INSERT INTO users(google_sub, email, name, picture, created_at,
                                            last_login_at) VALUES ('before', NULL, 'B', NULL, 1, 1)""")
            db.commit()
    finally:
        accounts_on.SCHEMA[:] = real
    store = accounts_on.Store(path)
    assert store.schema_version() == len(real)
    row = store.user(1)
    assert row["rating"] == 1000 and row["rated_rounds"] == 0 and row["leaderboard_visible"] == 1
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        accounts_on._migrate_v4(db)            # a re-run changes nothing
        db.commit()
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert {"rating_events", "rating_events_user", "rating_events_created"} <= names
    assert accounts_on.Store(path).schema_version() == len(accounts_on.SCHEMA)


def _v4_database(accounts_on, path, ratings_by_sub):
    """A database at schema v4 (the 1500 scale) holding one user per
    ``ratings_by_sub`` entry and one rated round for each rated user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    real = list(accounts_on.SCHEMA)
    accounts_on.SCHEMA[:] = real[:4]
    try:
        old = accounts_on.Store(path)
        ids = {}
        for sub, rating in ratings_by_sub.items():
            uid = old.upsert_user(_claims(sub=sub))["id"]
            ids[sub] = uid
            with closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE users SET rating = ? WHERE id = ?", (rating, uid))
                if rating != 1500:
                    delta = rating - 1500
                    db.execute(
                        """INSERT INTO rating_events(game_id, round_no, user_id, created_at,
                               team, banker_team, won, levels, expected, actual, k,
                               rating_before, rating_after, delta)
                           VALUES ('g1', 1, ?, 1, 0, 0, ?, 2, 0.557312, 0.8333, 40, 1500, ?, ?)""",
                        (uid, int(delta > 0), rating, delta))
                db.commit()
        assert old.schema_version() == 4
    finally:
        accounts_on.SCHEMA[:] = real
    return ids


def test_a_v4_database_moves_to_the_1000_scale_once(accounts_on, tmp_path):
    from shengji.api import ratings

    path = tmp_path / "v4" / "accounts.sqlite3"
    ids = _v4_database(accounts_on, path, {"even": 1500, "up": 1532, "down": 1471})
    before = {e["user_id"]: e for e in _events_at(path)}
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT rating FROM users WHERE id = ?", (ids["even"],)).fetchone()[0] == 1500

    store = accounts_on.Store(path)
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert [store.user(ids[s])["rating"] for s in ("even", "up", "down")] == [1000, 1032, 971]
    after = {e["user_id"]: e for e in _events_at(path)}
    assert set(after) == {ids["up"], ids["down"]}
    for uid, event in after.items():
        old = before[uid]
        assert event["rating_before"] == old["rating_before"] - 500 == 1000
        assert event["rating_after"] == old["rating_after"] - 500
        for unchanged in ("delta", "expected", "actual", "k"):
            assert event[unchanged] == old[unchanged]
        assert event["rating_after"] - event["rating_before"] == pytest.approx(event["delta"])

    # A second open, a direct re-run of the step and a lost version row each
    # leave the shift applied exactly once.
    assert accounts_on.Store(path).schema_version() == len(accounts_on.SCHEMA)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        accounts_on._migrate_v5(db)
        db.execute("UPDATE schema_version SET version = 4")
        db.commit()
    again = accounts_on.Store(path)
    assert again.schema_version() == len(accounts_on.SCHEMA)
    assert [again.user(ids[s])["rating"] for s in ("even", "up", "down")] == [1000, 1032, 971]
    assert {e["user_id"]: e["rating_after"] for e in _events_at(path)} == {
        uid: e["rating_after"] for uid, e in after.items()}

    newcomer = again.upsert_user(_claims(sub="after-the-move"))
    assert newcomer["rating"] == 1000 and newcomer["rated_rounds"] == 0
    board = ratings.leaderboard(again, "all", None)
    assert board["anchor"] == {"name": "Sheng Ji bot", "rating": 1000}


def test_the_scale_move_keeps_every_delta():
    """Expected scores depend only on rating gaps, so a migrated player meets
    the 1000 bots exactly as they met the 1500 bots."""
    from shengji.api import ratings as r

    for rating in (1532, 1471, 1500, 1900):
        for banker in (0, 1):
            for won, levels in ((True, 2), (False, 1), (True, 0)):
                deltas = []
                for shift, bot in ((0, 1500), (500, r.BOT_RATING)):
                    team, opp = r.team_strengths([rating - shift, bot, bot, bot], banker)
                    deltas.append(r.k_factor(0) * (r.round_score(won, levels)
                                                   - r.expected_score(team, opp)))
                assert deltas[1] == pytest.approx(deltas[0], abs=1e-12)


def test_a_fresh_database_starts_new_accounts_at_1000(accounts_on):
    store = accounts_on.STORE
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert store.upsert_user(_claims(sub="fresh"))["rating"] == 1000
    # A returning login never resets a moved rating.
    uid = store.upsert_user(_claims(sub="fresh"))["id"]
    _set(store, uid, 1044)
    assert store.upsert_user(_claims(sub="fresh"))["rating"] == 1044


def _events_at(path):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM rating_events ORDER BY id")]
