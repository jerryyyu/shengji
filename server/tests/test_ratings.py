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


def _user(store, sub, name=None, rating=1000.0):
    """A signed-in account at ``rating``: the worked examples here are set at
    the bot anchor (1000), not at a new account's start (``START_RATING``)."""
    user = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com", name=name or sub.title()))
    if rating is not None:
        _set(store, user["id"], rating)
    return user["id"], {"cookie": f"sj_session={store.create_session(user['id'])}"}


def _events(store, sql="SELECT * FROM rating_events ORDER BY id", *args):
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql, args)]


# an Advanced bot seat's anchor (``ratings.ADVANCED_BOT_RATING``)
ADV = 1059.0


def _e(us, them):
    """The expected score of a team of strength ``us`` against ``them``."""
    return 1 / (1 + 10 ** ((them - us) / 400))


def _set(store, user_id, rating, rounds=0):
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("UPDATE users SET rating = ?, rated_rounds = ? WHERE id = ?",
                   (rating, rounds, user_id))
        db.commit()


class Table:
    """A room whose four seats the test assigns (an int is a signed-in human,
    None a guest, "bot" a bot), played in-process. It is a queue-matched room
    unless ``ranked=False``: only a ranked room is rated."""

    def __init__(self, srv, seats, code="RATE", ranked=True):
        from shengji.engine.game import Game

        self.srv = srv
        self.room = srv.Room(code=code, matched=ranked)
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
    assert r.k_factor(0) == 40 and r.k_factor(19) == 40 and r.k_factor(20) == 40


def test_team_strength_is_the_seat_mean_plus_the_banker_side():
    from shengji.api import ratings as r

    assert r.team_strengths([1100, 1000, 1000, 1000], banker_team=0) == (1090.0, 1000.0)
    assert r.team_strengths([1100, 1000, 1000, 1000], banker_team=1) == (1050.0, 1040.0)


def test_new_accounts_and_guests_count_800_and_an_advanced_bot_1059():
    from shengji.api import accounts, ratings as r

    assert r.START_RATING == accounts.START_RATING == r.GUEST_RATING == 800.0
    assert r.BOT_RATING == accounts.RATING_SCALE == 1000.0
    assert r.ADVANCED_BOT_RATING == ADV
    assert r.BOT_ANCHORS == {"advanced": ADV, "standard": 1000.0, "beginner": 1000.0}


def test_a_1059_player_with_an_advanced_partner_meets_two_advanced_bots_at_even(env, monkeypatch):
    """Before the banker head start the two teams are equal: expected 0.5."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "even", rating=ADV)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    assert table.room.ratings.anchors[1:] == [ADV, ADV, ADV]
    table.finish()
    [event] = _events(store)
    head_start = ratings.BANKER_ADVANTAGE_PRESET
    assert event["expected"] == pytest.approx(_e(ADV + head_start, ADV))
    assert ratings.expected_score(ADV, ADV) == 0.5


def test_a_new_account_starts_at_start_rating(env):
    from shengji.api import ratings as r

    _, store, _ = env
    uid, _ = _user(store, "brandnew", rating=None)
    assert store.user(uid)["rating"] == r.START_RATING == 800.0


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
    # team 0 = (1000 + Advanced partner 1059) / 2 + banker 40 = 1069.5; team 1 = 1059
    assert event["expected"] == pytest.approx(_e(1069.5, ADV))
    assert event["actual"] == pytest.approx(5 / 6)
    assert event["k"] == 40
    assert event["delta"] == pytest.approx(40 * (5 / 6 - _e(1069.5, ADV)))   # +12.73
    assert event["delta"] == pytest.approx(12.73, abs=0.005)
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
    # team 0 = (1000 + 1059) / 2 = 1029.5; team 1 = 1059 + banker 40
    assert event["expected"] == pytest.approx(_e(1029.5, ADV + 40))
    assert event["actual"] == pytest.approx(1 / 6)
    assert event["levels"] == -2


def test_a_declared_banker_is_worth_80_and_a_preset_one_40():
    from shengji.api import ratings as r

    assert r.BANKER_ADVANTAGE_DECLARED == 80.0 and r.BANKER_ADVANTAGE_PRESET == 40.0
    assert r.team_strengths([1100, 1000, 1000, 1000], 0, banker_declared=True) == (1130.0, 1000.0)
    assert r.team_strengths([1100, 1000, 1000, 1000], 1, banker_declared=True) == (1050.0, 1080.0)
    assert r.expected_score(1080, 1000) == pytest.approx(0.613137, abs=1e-6)


def test_a_new_games_first_round_rates_the_banker_as_declared(env, monkeypatch):
    """A new game's first round starts with no banker: the deal goes to the
    declarer (seat 0 when nobody declares), and the banker side gets 80."""
    srv, store, _ = env
    uid, _ = _user(store, "declarer")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round()
    assert table.room.ratings.banker_declared is True
    assert table.room.round.banker == 0
    table.finish()
    [event] = _events(store)
    assert event["banker_team"] == 1
    # team 0 = (1000 + 1059) / 2 + declared banker 80; team 1 = 1059
    assert event["expected"] == pytest.approx(_e(1029.5 + 80, ADV))
    assert event["delta"] == pytest.approx(40 * (5 / 6 - _e(1029.5 + 80, ADV)))   # +10.47


def test_the_round_after_a_declared_one_is_preset(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "carried")
    _force_outcome(monkeypatch, 30)            # bankers hold: seat 2 banks next
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.play_round()
    table.start_round()
    assert table.room.round.banker == 2
    assert table.room.ratings.banker_declared is False
    table.finish()
    first, second = _events(store)
    assert first["expected"] == pytest.approx(_e(1029.5 + 80, ADV))
    team = (first["rating_after"] + ADV) / 2 + 40
    assert second["round_no"] == 2
    assert second["expected"] == pytest.approx(_e(team, ADV))


def test_a_resumed_games_first_round_has_a_preset_banker(env, monkeypatch):
    """The saved state's banker is set on the game before its first round
    starts, so that round is rated with the preset advantage."""
    import types

    from shengji.engine.game import Game

    srv, store, _ = env
    uid, _ = _user(store, "resumer")
    room = srv.Room(code="RSUM", matched=True)
    room.seats = [srv.Seat(name="P0", user_id=uid, connected=True)]
    room.resume = {"levels": ["5", "7"], "banker": 2}
    room.watchdog_task = types.SimpleNamespace(done=lambda: False)
    monkeypatch.setattr(srv, "_spawn_room_task", lambda room, attr, coro: coro.close())
    srv._start_game(room)
    assert isinstance(room.game, Game) and room.game.round_no == 1
    assert room.round.banker == 2 and room.round.first_round is False
    assert room.ratings.banker_declared is False

    fresh = srv.Room(code="FRSH", matched=True)
    fresh.seats = [srv.Seat(name="P0", user_id=uid, connected=True)]
    fresh.watchdog_task = types.SimpleNamespace(done=lambda: False)
    srv._start_game(fresh)
    assert fresh.round.banker is None and fresh.ratings.banker_declared is True


def test_a_new_game_at_the_same_table_keeps_the_carried_banker(env, monkeypatch):
    """Holding A scores the game and restarts the levels, but the engine
    passes the deal on as after any round, so the next game's first round is
    preset."""
    from shengji.engine.game import A_INDEX

    srv, store, _ = env
    uid, _ = _user(store, "ace")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.game.level_idx = [A_INDEX, A_INDEX]
    result = table.play_round(banker=0)
    assert result.point_scored and table.room.game.level_idx == [table.room.game.start_idx] * 2
    table.start_round()
    assert table.room.round.banker == 2
    assert table.room.ratings.banker_declared is False
    table.finish()
    first, second = _events(store)
    assert first["expected"] == pytest.approx(_e(1069.5, ADV))
    team = (first["rating_after"] + ADV) / 2 + 40
    assert second["expected"] == pytest.approx(_e(team, ADV))


@pytest.mark.parametrize("others", [["bot", "bot", "bot"], [None, None, None],
                                    [None, "bot", None]])
def test_guest_and_bot_seats_do_not_change_the_banker_flag(env, others):
    srv, store, _ = env
    uid, _ = _user(store, "seats")
    declared = Table(srv, [uid, *others])
    declared.start_round()
    preset = Table(srv, [uid, *others], code="RAT2")
    preset.start_round(banker=1)
    assert declared.room.ratings.banker_declared is True
    assert preset.room.ratings.banker_declared is False


def test_partners_move_in_lockstep_and_bots_and_guests_are_never_rated(env, monkeypatch):
    from shengji.api import ratings

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
    # team 0 = (1100 + 1000) / 2 = 1050; team 1 = (guest 800 + bot 1059) / 2, banker +40
    exp = _e(1050, 969.5)
    assert events[0]["expected"] == pytest.approx(exp)
    # the raw move is under MIN_MOVE, so the win moves by MIN_MOVE
    assert da == pytest.approx(ratings.bounded_delta(40 * (2 / 3 - exp), True, False))
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_a_guest_seat_counts_800_whatever_the_guest_is_called(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "host")
    _force_outcome(monkeypatch, 30)
    Table(srv, [uid, None, None, None]).play_round(banker=0)
    [event] = _events(store)
    # team 0 = (1000 + guest 800) / 2 + banker 40 = 940; team 1 = two guests, 800
    assert event["expected"] == pytest.approx(_e(940, 800))
    assert event["partner_bot"] == 0 and event["partner"] == "P2" and event["opponents_bots"] == 0


def test_a_new_player_and_an_established_partner_move_together(env, monkeypatch):
    srv, store, _ = env
    new, _ = _user(store, "newbie")
    old, _ = _user(store, "veteran")
    _set(store, old, 1000, rounds=40)
    _force_outcome(monkeypatch, 30)
    Table(srv, [new, "bot", old, "bot"]).play_round(banker=0)
    by = {e["user_id"]: e for e in _events(store)}
    # one K for everyone: a new partner no longer shrinks the veteran's move
    assert by[new]["k"] == by[old]["k"] == 40
    assert by[new]["delta"] == pytest.approx(by[old]["delta"])


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
    assert {e["k"] for e in _events(store)} == {40}


@pytest.mark.parametrize("other_seat", [1, 2])     # an opponent, the partner
def test_a_new_player_at_the_table_changes_no_one_s_k(env, monkeypatch, other_seat):
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
    assert by[vet]["k"] == by[newer]["k"] == ratings.K
    if other_seat == 2:                                    # partners move together
        assert by[vet]["delta"] == pytest.approx(by[newer]["delta"])


def test_two_new_players_get_the_one_k(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    a, _ = _user(store, "anna")
    b, _ = _user(store, "bert")
    _force_outcome(monkeypatch, 30)
    Table(srv, [a, "bot", b, "bot"]).play_round(banker=0)
    assert {e["k"] for e in _events(store)} == {ratings.K}


def test_k_factor_is_one_k_for_everyone():
    from shengji.api import ratings as r

    for rounds in (0, r.PROVISIONAL_ROUNDS - 1, r.PROVISIONAL_ROUNDS, 500):
        for prov in (False, True):
            assert r.k_factor(rounds, provisional_opponent=prov) == r.K == 40


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


# ------------------------------------------------------------ ranked switch
def test_an_unranked_created_room_rates_nobody(env, monkeypatch):
    srv, store, _ = env
    a, _ = _user(store, "alice")
    b, _ = _user(store, "bob")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, "bot", b, "bot"], ranked=False)
    table.play_round(banker=0)
    table.play_round()
    assert table.room.ratings is None and _events(store) == []
    assert store.user(a)["rated_rounds"] == 0 and store.user(a)["rating"] == 1000
    assert "rating" not in srv.state_for(table.room, 0)["round_result"]


def test_a_queue_room_rates_beside_guests_at_the_guest_rating(env, monkeypatch):
    """A guest's seat counts ``GUEST_RATING`` (800) and the round is kept."""
    srv, store, _ = env
    a, _ = _user(store, "alice")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, None, "bot", None])
    assert table.room.matched is True
    table.play_round(banker=0)
    [event] = _events(store)
    assert event["user_id"] == a
    # team 0 = (1000 + bot 1059) / 2 + banker 40; team 1 = two guests, 800
    assert event["expected"] == pytest.approx(_e(1069.5, 800))


def test_a_guest_partner_counts_800_in_the_rated_players_expected_score(env, monkeypatch):
    srv, store, _ = env
    a, _ = _user(store, "alice")
    _set(store, a, 1000, rounds=30)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, "bot", None, "bot"])
    table.room.matched = True
    table.play_round(banker=0)
    [event] = _events(store)
    assert event["user_id"] == a
    # team 0 = (1000 + guest partner 800) / 2 + banker 40 = 940; team 1 = two bots, 1059
    assert event["expected"] == pytest.approx(_e(940, ADV))


def test_play_bots_is_unrated_and_the_queue_rates_its_bot_game(queue_env):
    """Play bots is a created room with bots in every other seat: it gets no
    rating state, and its old Ranked switch is refused as retired. The
    ranked queue's game with bots is rated for its signed-in seat."""
    srv, store, client = queue_env
    uid, headers = _user(store, "solo", "Solo")
    with client.websocket_connect("/ws", headers=headers) as a:
        a.send_json({"type": "create_room", "name": "Jerry"})
        code = _drain(a, "room")["room"]
        _drain(a, "state")
        a.send_json({"type": "set_ranked", "on": True})
        assert _drain(a, "error")["code"] == "retired"
        assert srv.rooms[code].ratings is None
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        assert room.ratings is not None and room.ratings.present == {0: uid}


def test_a_queue_room_is_ranked_without_the_switch():
    from shengji.api import ratings, server as srv

    assert ratings.ranked(srv.Room(code="Q", matched=True))
    assert not ratings.ranked(srv.Room(code="C"))


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
    # team 0 = (1000 + 1000) / 2 + banker 40; team 1 = two bots, 1059
    assert by[a]["expected"] == pytest.approx(_e(1040, ADV))
    assert by[b]["expected"] == pytest.approx(_e(1040, ADV))
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
    assert event["expected"] == pytest.approx(_e(1069.5, ADV))   # seat 1 was a bot
    assert event["k"] == 40


def test_a_round_with_a_guest_at_a_queue_table_rates_each_account_in_full(env, monkeypatch):
    """A guest at a queue-matched table counts 800 and is never rated; the
    account beside it is rated on the round with its full K."""
    srv, store, _ = env
    a, _ = _user(store, "alice")
    _set(store, a, 1000, rounds=30)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [a, None, "bot", "bot"])
    table.room.matched = True
    table.room.seats[1].queue_id = -1
    table.play_round(banker=0)
    [event] = _events(store)
    assert event["user_id"] == a
    assert event["k"] == 40
    # team 0 = (1000 + bot 1059) / 2 + banker 40; team 1 = (guest 800 + bot 1059) / 2
    exp = _e(1069.5, 929.5)
    assert event["expected"] == pytest.approx(exp)
    assert event["delta"] == pytest.approx(40 * (5 / 6 - exp), abs=0.005)
    assert store.user(a)["rated_rounds"] == 31


def test_a_ranked_table_of_signed_in_players_is_rated_as_before(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "solo")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.matched = True
    table.play_round(banker=0)
    [event] = _events(store)
    assert event["delta"] == pytest.approx(40 * (5 / 6 - _e(1069.5, ADV)))


# -------------------------------------------------------- ranked join
# A ranked table is filled by the queue: someone holding no seat there is
# refused with ``ranked_queue_only`` (or takes the invite path), an account
# holding a seat comes back to it, and a guest comes back by its token.
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
    a.send_json({"type": "table_start_bots"})
    started = _drain(a, "match_started")
    assert started["rated"] is True
    return started["room"], srv.rooms[started["room"]].seats[0].token


def _seats(room):
    return [(s.name, s.is_bot, s.user_id) for s in room.seats]


def test_a_guest_with_no_device_key_cannot_join_a_ranked_room(queue_env):
    srv, store, client = queue_env
    uid, headers = _user(store, "owner", "Owner")
    with client.websocket_connect("/ws", headers=headers) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        before = _seats(room)
        with client.websocket_connect("/ws") as g:
            g.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Guest"})
            assert _drain(g, "error")["code"] == "ranked_queue_only"
            g.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Guest", "seat": 1})
            assert _drain(g, "error")["code"] == "ranked_queue_only"
        assert _seats(room) == before


def test_another_account_joins_a_ranked_room_by_code_only_as_an_open_table_newcomer(queue_env):
    srv, store, client = queue_env
    owner, h1 = _user(store, "owner", "Owner")
    other, h2 = _user(store, "other", "Other")
    with client.websocket_connect("/ws", headers=h1) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        with client.websocket_connect("/ws", headers=h2) as b:
            # typing the holder's name is not a way into the holder's seat:
            # the code is an invite, taking a bot's seat from the handover
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Owner"})
            started = _drain(b, "match_started")
            assert started["joining"] is True and started["seat"] != 0
            assert room.seats[0].user_id == owner
            seat = started["seat"]
            assert room.seats[seat].user_id == other or room.pending_joins[seat].uid == other


def test_the_seat_holder_comes_back_with_or_without_a_token(queue_env):
    srv, store, client = queue_env
    uid, headers = _user(store, "owner", "Owner")
    with client.websocket_connect("/ws", headers=headers) as a:
        code, token = _ranked_solo(srv, a)
    room = srv.rooms[code]
    with client.websocket_connect("/ws", headers=headers) as again:
        again.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Owner", "token": token})
        state = _drain(again, "state")
        assert state["room"] == code and state["you"] == 0
    with client.websocket_connect("/ws", headers=headers) as other_device:
        other_device.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Phone"})
        state = _drain(other_device, "state")
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
    # a leave never gains rating, even where the capped score beats the expectation
    assert event["delta"] <= 0.0
    assert event["rating_after"] <= event["rating_before"]


def test_an_attacker_who_leaves_a_winning_round_gains_nothing(env, monkeypatch):
    # The attackers expect less than a draw against the banker's advantage, so a
    # win capped at 0.5 would still beat the expectation; the leaver gains nothing.
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "leaver")
    _force_outcome(monkeypatch, 210)
    table = Table(srv, ["bot", uid, "bot", "bot"])
    table.start_round(banker=0)
    ratings.seat_left(table.room, 1)
    table.room.seats[1].connected = False
    table.finish()
    [event] = _events(store)
    assert event["expected"] < ratings.LEAVER_SCORE_CAP
    assert event["actual"] == pytest.approx(ratings.LEAVER_SCORE_CAP)
    assert event["delta"] == 0.0
    assert event["rating_after"] == event["rating_before"]


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


def test_a_partner_disconnected_at_the_start_counts_their_own_rating(env, monkeypatch):
    """A person, not a bot: the partner's seat counts their 1300, not 1000."""
    srv, store, _ = env
    uid, _ = _user(store, "rated", rating=1000.0)
    partner, _ = _user(store, "away", rating=1300.0)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", partner, "bot"])
    table.room.seats[2].connected = False
    table.start_round(banker=0)
    table.finish()
    [event] = _events(store)
    assert event["user_id"] == uid
    assert event["expected"] == pytest.approx(_e((1000 + 1300) / 2 + 40, ADV))


def test_an_unrated_seat_whose_account_is_gone_counts_a_guest(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "rated", rating=1000.0)
    partner, _ = _user(store, "gone", rating=1300.0)
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", partner, "bot"])
    table.room.seats[2].connected = False
    table.start_round(banker=0)
    assert table.room.ratings.anchors[2] == ratings.GUEST_RATING
    assert table.room.ratings.standing.result(timeout=10)[partner] == (1300.0, 0)   # read at the start
    assert store.delete_user(partner)
    table.finish()
    [event] = _events(store)
    assert event["expected"] == pytest.approx(_e((1000 + 800) / 2 + 40, ADV))


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


def test_leaving_a_ranked_room_between_rounds_costs_nothing(env, monkeypatch):
    """leave_room after the round end and before the next round starts: the
    finished round is already rated as played, and the leaver, no longer in
    the seat when the next round starts, is not a participant in it."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "between")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.room.matched = True
    table.play_round(banker=0)
    room = table.room
    assert room.round.phase == "round_end"
    [first] = _events(store)
    assert first["user_id"] == uid and first["abandoned"] == 0 and first["won"] == 1
    # what the server's leave_room handler does to a mid-game seat
    ratings.seat_left(room, 0)
    srv._detach(room.seats[0], room)
    assert room.ratings.left == {}
    assert not room.seats[0].connected
    rated_before = store.user(uid)["rating"]
    table.play_round()                         # the bots play the next round
    assert room.game.round_no == 2
    events = _events(store)
    assert [e["round_no"] for e in events] == [first["round_no"]]
    assert [e["abandoned"] for e in events] == [0]
    assert store.user(uid)["rating"] == rated_before
    assert store.user(uid)["rated_rounds"] == 1


def _start_undealt(table):
    """Start the table's next round as the server does, before any card is dealt."""
    from shengji.api import ratings

    room = table.room
    room.game.start_round()
    room.index_round()
    ratings.round_started(room)
    return room.round


def _deal_out(table, banker=0):
    room, rnd = table.room, table.room.round
    while rnd.phase == "deal":
        seat, idx, code = rnd.deal_next()
        room.ids[seat][idx] = code
    rnd.finalize_declare()
    if rnd.banker is None:
        rnd.banker = banker


def test_leaving_before_the_first_card_of_the_next_round_is_not_an_abandon(env, monkeypatch):
    """Readied, and the Leave lands after the others' Next round started the
    next round but before this seat's first card: nothing of that round was
    seen, so it is not rated, as a leave at the round end would not be."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "readied")
    partner, _ = _user(store, "stayer")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", partner, "bot"])
    table.play_round(banker=0)
    room = table.room
    rnd = _start_undealt(table)
    assert room.ratings.present == {0: uid, 2: partner}
    assert rnd.phase == "deal" and rnd.hands[0] == []
    ratings.seat_left(room, 0)                 # what leave_room does, then detaches
    srv._detach(room.seats[0], room)
    assert room.ratings.left == {} and room.ratings.present == {2: partner}
    _deal_out(table)
    table.finish()
    second = [e for e in _events(store) if e["round_no"] == 2]
    assert [(e["user_id"], e["abandoned"]) for e in second] == [(partner, 0)]
    assert store.user(uid)["rated_rounds"] == 1


def test_leaving_once_a_card_of_the_round_is_dealt_is_still_an_abandon(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "dealt")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.play_round(banker=0)
    room = table.room
    rnd = _start_undealt(table)
    seat, idx, code = rnd.deal_next()
    room.ids[seat][idx] = code
    assert seat == 0 and rnd.hands[0]
    ratings.seat_left(room, 0)
    srv._detach(room.seats[0], room)
    assert room.ratings.left == {uid: 0}
    _deal_out(table)
    table.finish()
    second = [e for e in _events(store) if e["round_no"] == 2]
    assert [(e["user_id"], e["abandoned"]) for e in second] == [(uid, 1)]


def test_away_at_the_round_end_is_an_abandon(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "idler")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.room.seats[0].away = True            # still connected, the bot plays on
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["actual"] == 0.5    # a 2-level win, capped


def test_back_from_away_before_the_round_ends_is_not_an_abandon(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "returner")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.room.seats[0].away = True
    srv._player_moved(table.room, 0)           # "I'm back"
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 0 and event["won"] == 1


def test_one_or_two_timeouts_change_nothing(env, monkeypatch):
    srv, store, _ = env
    uid, _ = _user(store, "slow")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.room.move_timer = True
    seat = table.room.seats[0]
    srv._count_timeout(table.room, 0)
    seat.timeouts_in_row = 0                   # a real move in between
    srv._count_timeout(table.room, 0)
    assert not seat.away
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 0 and event["won"] == 1


def test_a_ranked_room_runs_the_move_timer(queue_env):
    srv, store, client = queue_env
    _, headers = _user(store, "owner", "Owner")
    with client.websocket_connect("/ws", headers=headers) as a:
        code, _ = _ranked_solo(srv, a)
        assert srv.rooms[code].move_timer is True


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


def test_overlapping_rounds_take_k_from_the_round_start(env, monkeypatch):
    """One account in two rooms at once, one round short of established: the
    round that ends second still uses the provisional K it started with."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "twotables")
    _set(store, uid, 1000.0, ratings.PROVISIONAL_ROUNDS - 1)
    _force_outcome(monkeypatch, 30)
    first = Table(srv, [uid, "bot", "bot", "bot"], code="RAT1")
    second = Table(srv, [uid, "bot", "bot", "bot"], code="RAT2")
    first.start_round(banker=0)
    second.start_round(banker=0)
    ratings.flush()                            # both round-start reads are taken
    first.finish()
    ratings.flush()
    second.finish()
    ratings.flush()
    a, b = _events(store)
    assert a["k"] == ratings.K
    assert b["k"] == ratings.K
    assert b["rating_before"] == pytest.approx(a["rating_after"])


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


def test_leave_room_over_the_socket_marks_the_round_abandoned(queue_env, keypair):
    srv, store, client = queue_env
    private_pem, _ = keypair
    cookie = _session_cookie(srv.accounts, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        code, _ = _ranked_solo(srv, a)
        _drain(a, "state")
        room = srv.rooms[code]
        assert room.ratings is not None and room.ratings.present == {0: 1}
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        assert room.ratings.left == {1: 0}


def test_a_deliberate_leave_keeps_every_rating_and_penalty_rule(queue_env, keypair, monkeypatch):
    """Leave hands the seat to the bot at once, but what a leave costs is
    unchanged: the round is recorded as left, the leaver is rated as an
    abandon whether or not the seat is marked as left, and no queue cooldown
    is added for an ordinary seat."""
    from shengji.api import ratings

    srv, store, client = queue_env
    private_pem, _ = keypair
    cooldowns = []
    monkeypatch.setattr(srv.MATCHMAKER, "left_open_table", lambda *a: cooldowns.append(a))
    cookie = _session_cookie(srv.accounts, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        code, _ = _ranked_solo(srv, a)
        _drain(a, "state")
        room = srv.rooms[code]
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        seat = room.seats[0]
        assert seat.left_by_choice and not seat.is_bot
        assert room.ratings.left == {1: 0}
        marked = ratings.participants(room, room.ratings)
        seat.left_by_choice = False
        unmarked = ratings.participants(room, room.ratings)
        assert marked == unmarked
        assert [(p.user_id, p.abandoned) for p in marked] == [(1, True)]
    assert cooldowns == []


def _wait_until(pred, timeout=60.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition never held"
        time.sleep(0.01)


def test_a_losing_leaver_is_rated_before_the_empty_room_closes(queue_env, keypair, monkeypatch):
    """The last human leaving a rated round of a ranked room: the bots finish
    it without pacing, the leaver is rated on its real result, then the room
    closes."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import ratings

    srv, store, client = queue_env
    private_pem, _ = keypair
    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    _force_outcome(monkeypatch, 165)           # attackers +2: the leaver's banker team loses
    monkeypatch.setattr(srv, "ROOM_TTL", 120.0)  # the round ends well before the backstop
    cookie = _session_cookie(srv.accounts, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        code, _ = _ranked_solo(srv, a)
        _drain(a, "state")
        room = srv.rooms[code]
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        _wait_until(lambda: code not in srv.rooms)
    assert room.game.round_no == 1 and room.round.phase == "round_end"
    ratings.flush()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["won"] == 0
    assert event["actual"] == pytest.approx(1 / 6)
    assert room.seats[0].bot_announced


def test_a_closing_ranked_round_is_finished_without_the_served_search(queue_env, keypair, monkeypatch):
    """Nobody is left to watch the round: the cheap heuristic bot finishes
    it, the served bot is never asked, and the leaver is rated exactly as
    before (abandoned, on the real result)."""
    import json

    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import ratings

    srv, store, client = queue_env
    private_pem, _ = keypair
    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    _force_outcome(monkeypatch, 165)
    monkeypatch.setattr(srv, "ROOM_TTL", 120.0)

    async def no_model_search(*args, **kwargs):
        raise AssertionError("model search ran in a closing room")

    monkeypatch.setattr(srv, "run_model_search", no_model_search)
    asked = []

    class ServedBot(HeuristicBot):
        room = None                      # class-level: a deepcopy does not copy it

        def _check(self, what):
            if type(self).room is not None and type(self).room.closing:
                asked.append(what)
                raise AssertionError(f"served bot asked to {what} in a closing room")

        def decide_declare(self, rnd, seat, final=False):
            self._check("declare")
            return None

        def decide_bury(self, rnd, seat):
            self._check("bury")
            return super().decide_bury(rnd, seat)

        def decide_play(self, rnd, seat):
            self._check("play")
            return super().decide_play(rnd, seat)

    cookie = _session_cookie(srv.accounts, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        ServedBot.room = room
        room.bot = ServedBot()
        _drain(a, "state")
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        _wait_until(lambda: code not in srv.rooms, timeout=20.0)
    assert asked == []
    assert room.game.round_no == 1 and room.round.phase == "round_end"
    ratings.flush()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["won"] == 0
    assert event["actual"] == pytest.approx(1 / 6)
    assert room.seats[0].bot_announced
    records = [json.loads(line) for line in
               (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]
    [start] = [r for r in records if r["e"] == "round_start"]
    assert start["ranked"] is True and "user_ids" not in start
    text = json.dumps(start)
    assert "@" not in text and room.seats[0].token not in text
    assert [r["seat"] for r in records if r["e"] == "seat_left"] == [0]


def test_a_ranked_room_closed_by_its_last_leaver_leaves_nothing_in_the_queue(queue_env, monkeypatch):
    srv, store, client = queue_env
    uid, headers = _user(store, "solo", "Solo")
    monkeypatch.setattr(srv, "ROOM_TTL", 120.0)
    with client.websocket_connect("/ws", headers=headers) as a:
        code, _ = _ranked_solo(srv, a)
        room = srv.rooms[code]
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        _wait_until(lambda: code not in srv.rooms)
        conn = srv.MATCHMAKER.conns[uid]
        assert not conn.in_room and conn.adopted is None
        assert not srv.MATCHMAKER.room_live(code)
        assert srv.MATCHMAKER._entry(uid) is None and not srv.MATCHMAKER.tables
        a.send_json({"type": "queue_join"})
        assert _drain(a, "queue_state")["queued"] is True
    assert all(task is None or task.done()
               for task in (room.bot_task, room.deal_task, room.cleanup_task))


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
    assert board["anchor"] == {"name": "Sheng Ji bot", "rating": 1059}
    assert board["anchors"] == {"advanced": 1059, "standard": 1000, "beginner": 1000}
    week = ratings.leaderboard(store, "week", None, now=now)
    assert "Stale" not in [r["name"] for r in week["players"]] and week["me"] is None
    # every round is this week, so no one had a place a week ago
    assert {r["week_rank_move"] for r in week["players"]} == {None}
    assert "week_delta" not in week["players"][0]
    assert {r["week_rank_move"] for r in board["players"]} == {None}   # All time


def _history(store, sub, rounds, visible=True):
    """An account with rated rounds ``rounds``: (age_seconds, delta) pairs,
    oldest first, from a rating of 1000; ``users.rating`` ends at their sum."""
    rating = 1000.0
    with closing(store._open()) as conn:
        conn.execute(
            """INSERT INTO users(google_sub, email, name, created_at, last_login_at,
                                 rating, rated_rounds, leaderboard_visible)
               VALUES (?, ?, ?, 0, 0, 0, 0, ?)""",
            (sub, f"{sub}@example.com", sub.title(), 1 if visible else 0))
        uid = conn.execute("SELECT id FROM users WHERE google_sub = ?", (sub,)).fetchone()[0]
        now = time.time()
        for i, (age, delta) in enumerate(rounds):
            conn.execute(
                """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                       banker_team, won, levels, expected, actual, k, rating_before,
                       rating_after, delta)
                   VALUES (?, ?, ?, ?, 0, 0, 1, 1, 0.5, 1, 40, ?, ?, ?)""",
                (f"g-{sub}", i + 1, uid, int(now - age), rating, rating + delta, delta))
            rating += delta
        conn.execute("UPDATE users SET rating = ?, rated_rounds = ? WHERE id = ?",
                     (rating, len(rounds), uid))
    return uid


def _moves(board):
    return {r["name"]: r["week_rank_move"] for r in board["players"]}


OLD, NEW = 10 * 86400, 3600       # before the week began, and this week


def test_two_players_who_swap_places_this_week_move_up_one_and_down_one(env):
    from shengji.api import ratings

    srv, store, _ = env
    _history(store, "ann", [(OLD, 50), (NEW, -40)])     # 1050 -> 1010
    _history(store, "bea", [(OLD, 20), (NEW, 10)])      # 1020 -> 1030
    _history(store, "cal", [(OLD, 0), (NEW, 0)])        # 1000 -> 1000, still third
    board = ratings.leaderboard(store, "week", None)
    assert [r["name"] for r in board["players"]] == ["Bea", "Ann", "Cal"]
    assert _moves(board) == {"Bea": 1, "Ann": -1, "Cal": 0}


def test_a_player_new_this_week_has_no_move_and_pushes_the_others_down(env):
    from shengji.api import ratings

    srv, store, _ = env
    ann = _history(store, "ann", [(OLD, 10), (NEW, 5)])
    _history(store, "dee", [(NEW, 80)])                 # first round this week
    _history(store, "old", [(OLD, 90)])                 # not on this week's list
    board = ratings.leaderboard(store, "week", ann)
    assert [r["name"] for r in board["players"]] == ["Dee", "Ann"]
    assert _moves(board) == {"Dee": None, "Ann": -1}
    assert board["me"]["week_rank_move"] == -1


def test_a_tie_a_week_ago_breaks_like_the_ranking_does(env):
    from shengji.api import ratings

    srv, store, _ = env
    # Level at 1020 a week ago; Ann had more rounds then, so she was ahead.
    _history(store, "ann", [(OLD, 10), (OLD, 10), (NEW, 0)])
    _history(store, "bea", [(OLD, 20), (NEW, 1)])
    # Level at 1000 a week ago on rounds too: the lower id (Cal) was ahead.
    _history(store, "cal", [(OLD, 0), (NEW, -1)])
    _history(store, "dan", [(OLD, 0), (NEW, 0)])
    board = ratings.leaderboard(store, "week", None)
    assert [r["name"] for r in board["players"]] == ["Bea", "Ann", "Dan", "Cal"]
    assert _moves(board) == {"Bea": 1, "Ann": -1, "Dan": 1, "Cal": -1}


def test_a_swap_from_a_tie_at_the_week_s_start_counts_through_real_rounds(env):
    """Partners level at the week's start, rated by real rounds; Bea then
    overtakes Ann. Rebuilding Bea's start as rating minus her week's summed
    deltas comes out above Ann's equal stored rating, which would skip the
    id tie-break and show both rows flat."""
    from shengji.api import ratings

    srv, store, _ = env
    ann, _ = _user(store, "ann", "Ann", rating=None)
    bea, _ = _user(store, "bea", "Bea", rating=None)
    now = time.time()

    def rate(game_id, seats, winner_team, level_change, at):
        ratings.apply_round(store, ratings.RoundRecord(
            game_id=game_id, round_no=1, banker_team=0, winner_team=winner_team,
            level_change=level_change, point_scored=False, start_accounts=dict(seats),
            seat_names=[f"P{s}" for s in range(4)], seat_bots=[s not in seats for s in range(4)],
            participants=[ratings.Participant(user_id=u, seat=s) for s, u in seats.items()]),
            now=at)

    for i, (winner, levels) in enumerate([(1, 2), (0, 2), (1, 1)]):
        rate(f"pre{i}", {0: ann, 2: bea}, winner, levels, now - OLD)
    rate("w0", {0: ann}, 0, 1, now - NEW)
    rate("w1", {0: bea}, 1, 1, now - NEW)
    rate("w2", {0: bea}, 0, 2, now - NEW)

    start = {r["user_id"]: r["rating_after"] for r in _events(
        store, "SELECT * FROM rating_events WHERE game_id = 'pre2'")}
    assert start[ann] == start[bea]
    week = {u: sum(r["delta"] for r in _events(
        store, "SELECT * FROM rating_events WHERE user_id = ? AND game_id LIKE 'w%' ORDER BY id", u))
        for u in (ann, bea)}
    rebuilt = {u: ratings.current_rating(store, u) - week[u] for u in (ann, bea)}
    assert rebuilt[bea] != start[bea]           # the drift this guards against

    board = ratings.leaderboard(store, "week", None, now=now)
    assert [r["name"] for r in board["players"]] == ["Bea", "Ann"]
    assert _moves(board) == {"Bea": 1, "Ann": -1}


def test_a_week_move_counts_only_visible_players(env):
    from shengji.api import ratings

    srv, store, _ = env
    _history(store, "hid", [(OLD, 100), (NEW, -100)], visible=False)
    _history(store, "ann", [(OLD, 50), (NEW, 0)])
    bea = _history(store, "bea", [(OLD, 20), (NEW, 0)], visible=False)
    board = ratings.leaderboard(store, "week", bea)
    assert _moves(board) == {"Ann": 0}
    assert board["me"]["rank"] == 2 and board["me"]["week_rank_move"] == 0


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
                        "week_rank_move", "provisional", "you", "look"}

    stats = client.get("/api/me/stats", headers=headers).json()
    assert stats["rounds"] == 3 and stats["rank"] == 1 and stats["won_pct"] == 100.0
    assert stats["defender_won_pct"] == 100.0 and stats["attacker_won_pct"] is None
    assert stats["best_streak"] == 3 and stats["levels_per_round"] == 2.0
    assert stats["games_won"] == 0 and stats["visible"] is True
    assert stats["rounds_won"] == 3 == store.ranked_wins(uid)
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
    assert newcomer["rating"] == accounts_on.START_RATING and newcomer["rated_rounds"] == 0
    board = ratings.leaderboard(again, "all", None)
    assert board["anchor"] == {"name": "Sheng Ji bot", "rating": 1059}
    assert board["anchors"] == {"advanced": 1059, "standard": 1000, "beginner": 1000}


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


def test_a_fresh_database_starts_new_accounts_at_start_rating(accounts_on):
    store = accounts_on.STORE
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert store.upsert_user(_claims(sub="fresh"))["rating"] == accounts_on.START_RATING == 800.0
    # A returning login never resets a moved rating.
    uid = store.upsert_user(_claims(sub="fresh"))["id"]
    _set(store, uid, 1044)
    assert store.upsert_user(_claims(sub="fresh"))["rating"] == 1044


def _events_at(path):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM rating_events ORDER BY id")]


# ------------------------------------------- one account, two sockets
def _displaced_seat(srv, client, cookie, ranked=False):
    """Socket ``a`` starts a game at seat 0; ``b``, the same account in
    another tab, resumes the seat by its token and displaces ``a``."""
    a = client.websocket_connect("/ws", headers={"cookie": cookie}).__enter__()
    if ranked:
        code, token = _ranked_solo(srv, a)
    else:
        a.send_json({"type": "create_room", "name": "Jerry"})
        token = _drain(a, "resume")["token"]
        code = _drain(a, "room")["room"]
    _drain(a, "state")
    room = srv.rooms[code]
    b = client.websocket_connect("/ws", headers={"cookie": cookie}).__enter__()
    b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Jerry", "token": token})
    _drain(b, "state")
    assert room.seats[0].connected
    return a, b, code, room


def test_leaving_from_a_displaced_tab_leaves_the_seat_and_closes_the_room(env, keypair):
    """The account leaves on the socket another of its tabs displaced: the
    seat is left (no stale refusal), the room with no other human closes, and
    the tab that held the seat goes back to the lobby on its next frame."""
    srv, store, client = env
    private_pem, _ = keypair
    cookie = _session_cookie(srv.accounts, client, private_pem)
    a, b, code, room = _displaced_seat(srv, client, cookie)
    try:
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        assert not room.seats[0].connected and not room.seats[0].is_bot
        assert code not in srv.rooms
        b.send_json({"type": "ping", "nonce": 1})
        _drain(b, "left")
        b.send_json({"type": "play", "card_ids": []})
        assert _drain(b, "error")["message"] == "Join a room first."
    finally:
        b.__exit__(None, None, None)
        a.__exit__(None, None, None)


def test_a_displaced_tabs_leave_in_a_ranked_round_finishes_it_bot_covered(queue_env, keypair,
                                                                          monkeypatch):
    srv, store, client = queue_env
    private_pem, _ = keypair
    monkeypatch.setattr(srv, "ROOM_TTL", 120.0)
    cookie = _session_cookie(srv.accounts, client, private_pem)
    a, b, code, room = _displaced_seat(srv, client, cookie, ranked=True)
    try:
        a.send_json({"type": "table_leave"})
        _drain(a, "left")
        assert room.ratings.left == {1: 0}
        _wait_until(lambda: code not in srv.rooms)
        assert room.round.phase == "round_end" and room.seats[0].bot_announced
    finally:
        b.__exit__(None, None, None)
        a.__exit__(None, None, None)
    from shengji.api import ratings
    ratings.flush()
    [event] = _events(store)
    assert event["abandoned"] == 1


def test_a_displaced_tabs_leave_beside_another_human_keeps_the_game(env, keypair):
    srv, store, client = env
    private_pem, _ = keypair
    cookie = _session_cookie(srv.accounts, client, private_pem)
    a, b, code, room = _displaced_seat(srv, client, cookie)
    try:
        with client.websocket_connect("/ws") as guest:
            guest.send_json({"type": "table_join", "expect": "room", "code": code, "name": "amy", "seat": 2})
            _drain(guest, "state")
            a.send_json({"type": "table_leave"})
            _drain(a, "left")
            assert srv.rooms.get(code) is room and not room.closing
            assert not room.seats[0].connected
            assert srv._controller(room, 0) == "bot_cover"
            b.send_json({"type": "ping", "nonce": 1})
            _drain(b, "left")
            assert srv.rooms.get(code) is room
    finally:
        b.__exit__(None, None, None)
        a.__exit__(None, None, None)


def test_a_guest_displaced_socket_still_cannot_leave_for_the_seat(client):
    """Without an account a displaced socket proves nothing about who is
    leaving, so it is refused."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        token = _drain(a, "resume")["token"]
        code = _drain(a, "room")["room"]
        _drain(a, "state")
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "jerry", "token": token})
            _drain(b, "state")
            a.send_json({"type": "table_leave"})
            # the deal's queued state frames reach this socket first
            assert _drain(a, "error")["code"] == "stale_connection"
            assert srv.rooms[code].seats[0].connected


@pytest.mark.parametrize("attacker_points, won", [(60, True), (130, False)])
def test_a_round_played_out_moves_the_rating_by_at_least_the_minimum(
        env, monkeypatch, attacker_points, won):
    """A strong banker's narrow win would gain under one point (or lose rating)
    by expectation alone; the floor makes it at least ``MIN_MOVE``. A narrow
    loss costs at least as much."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "strong")
    _set(store, uid, 1300.0, rounds=50)
    _force_outcome(monkeypatch, attacker_points)   # seat 0's team banks
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.finish()
    [event] = _events(store)
    assert bool(event["won"]) is won
    raw = event["k"] * (event["actual"] - event["expected"])
    if won:
        assert raw < ratings.MIN_MOVE
        assert event["delta"] == pytest.approx(ratings.MIN_MOVE)
    else:
        assert event["delta"] <= -ratings.MIN_MOVE
    assert event["rating_after"] == pytest.approx(event["rating_before"] + event["delta"])


def test_bounded_delta_caps_a_loss_and_leaves_wins_and_leaves_alone():
    from shengji.api import ratings as r

    assert r.MAX_LOSS == 12.0
    assert r.bounded_delta(-26.1, won=False, leaver=False) == pytest.approx(-12.0)
    assert r.bounded_delta(-12.0, won=False, leaver=False) == pytest.approx(-12.0)
    assert r.bounded_delta(-7.5, won=False, leaver=False) == pytest.approx(-7.5)
    assert r.bounded_delta(-1.0, won=False, leaver=False) == pytest.approx(-3.0)
    assert r.bounded_delta(+0.4, won=False, leaver=False) == pytest.approx(-3.0)
    assert r.bounded_delta(26.1, won=True, leaver=False) == pytest.approx(26.1)
    assert r.bounded_delta(1.0, won=True, leaver=False) == pytest.approx(3.0)
    assert r.MAX_LEAVE_LOSS == 15.0
    assert r.bounded_delta(-26.1, won=False, leaver=True) == pytest.approx(-15.0)
    assert r.bounded_delta(-13.0, won=False, leaver=True) == pytest.approx(-13.0)
    assert r.bounded_delta(-1.0, won=False, leaver=True) == pytest.approx(-1.0)
    assert r.bounded_delta(5.0, won=True, leaver=True) == 0.0


def test_a_heavy_loss_played_out_costs_exactly_the_cap(env, monkeypatch):
    """A 1300 player on the attackers, beaten by three levels (0 points):
    team 1179.5 against the preset banker's 1099, ``E`` 0.614, raw -24.6; the
    loss is held at ``MAX_LOSS``."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "strong")
    _set(store, uid, 1300.0, rounds=50)
    _force_outcome(monkeypatch, 0)
    table = Table(srv, ["bot", uid, "bot", "bot"])
    table.start_round(banker=0)
    table.finish()
    [event] = _events(store)
    assert event["won"] == 0 and event["levels"] == -3
    raw = event["k"] * (event["actual"] - event["expected"])
    assert raw == pytest.approx(-24.6, abs=0.1)
    assert event["delta"] == pytest.approx(-ratings.MAX_LOSS)
    assert event["rating_after"] == pytest.approx(1300.0 - 12.0)


def test_a_leavers_heavy_loss_is_capped_above_the_played_out_cap(env, monkeypatch):
    """The same round left mid-play: raw -24.6 is held at ``MAX_LEAVE_LOSS``
    (15), more than the 12 a played-out loss costs."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "leaver")
    _set(store, uid, 1300.0, rounds=50)
    _force_outcome(monkeypatch, 0)
    table = Table(srv, ["bot", uid, "bot", "bot"])
    table.start_round(banker=0)
    ratings.seat_left(table.room, 1)
    table.room.seats[1].connected = False
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 1
    raw = event["k"] * (event["actual"] - event["expected"])
    assert raw == pytest.approx(-24.6, abs=0.1)
    assert event["delta"] == pytest.approx(-ratings.MAX_LEAVE_LOSS)
    assert event["delta"] < -ratings.MAX_LOSS


def test_a_big_win_is_not_capped(env, monkeypatch):
    """A 700 player banking with bots wins by three levels: team 919.5
    against 1059, ``E`` 0.309, gain +27.6 in full."""
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "weak")
    _set(store, uid, 700.0, rounds=50)
    _force_outcome(monkeypatch, 0)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.start_round(banker=0)
    table.finish()
    [event] = _events(store)
    assert event["won"] == 1
    raw = event["k"] * (event["actual"] - event["expected"])
    assert event["delta"] == pytest.approx(raw)
    assert event["delta"] > ratings.MAX_LOSS
    assert event["delta"] == pytest.approx(27.6, abs=0.1)


def test_a_leave_is_exempt_from_the_minimum_move(env, monkeypatch):
    from shengji.api import ratings

    srv, store, _ = env
    uid, _ = _user(store, "leaver")
    _force_outcome(monkeypatch, 210)
    table = Table(srv, ["bot", uid, "bot", "bot"])
    table.start_round(banker=0)
    ratings.seat_left(table.room, 1)
    table.room.seats[1].connected = False
    table.finish()
    [event] = _events(store)
    assert event["abandoned"] == 1 and event["delta"] == 0.0


def _rounds_at(store, uid, times, start=1000.0, step=3.0):
    """One rated round per time in ``times``, each gaining ``step``."""
    with closing(store._open()) as conn:
        r = start
        for i, at in enumerate(times):
            conn.execute(
                """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                       banker_team, won, levels, expected, actual, k, rating_before,
                       rating_after, delta)
                   VALUES ('g-hist', ?, ?, ?, 0, 1, 1, 1, 0.5, 1, 20, ?, ?, ?)""",
                (i + 1, uid, at, r, r + step, step))
            r += step


def test_stats_sends_one_time_per_history_point(env):
    from shengji.api import ratings

    _, store, _ = env
    uid, _ = _user(store, "hist")
    _rounds_at(store, uid, [1_700_000_000, 1_700_000_600, 1_700_090_000])
    s = ratings.stats(store, uid, now=1_700_100_000)
    assert s["history"] == [1000, 1003, 1006, 1009]
    # the starting point has no round of its own: it takes the first round's time
    assert s["history_at"] == [1_700_000_000, 1_700_000_000, 1_700_000_600, 1_700_090_000]


def test_stats_history_is_bounded_and_starts_at_the_round_before(env):
    from shengji.api import ratings

    _, store, _ = env
    uid, _ = _user(store, "long")
    n = ratings.HISTORY_POINTS + 25
    times = [1_700_000_000 + 60 * i for i in range(n)]
    _rounds_at(store, uid, times)
    s = ratings.stats(store, uid, now=times[-1] + 1)
    assert len(s["history"]) == len(s["history_at"]) == ratings.HISTORY_POINTS + 1 == 201
    # the first point is the rating before the oldest round shown, timed at
    # the round before that one
    assert s["history_at"][0] == times[-ratings.HISTORY_POINTS - 1]
    assert s["history_at"][1:] == times[-ratings.HISTORY_POINTS:]
    assert s["history"][-1] == 1000 + 3 * n
    assert all(isinstance(t, int) for t in s["history_at"])


def test_stats_with_no_rounds_sends_empty_history(env):
    from shengji.api import ratings

    _, store, _ = env
    uid, _ = _user(store, "fresh")
    s = ratings.stats(store, uid)
    assert s["history"] == [] and s["history_at"] == []
