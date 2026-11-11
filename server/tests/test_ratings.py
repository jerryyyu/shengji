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

    assert r.expected_score(1500, 1500) == pytest.approx(0.5)
    # 40 points of banker advantage between otherwise equal teams
    assert r.expected_score(1540, 1500) == pytest.approx(0.557312, abs=1e-6)
    assert r.expected_score(1500, 1900) == pytest.approx(1 / 11, abs=1e-9)
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

    assert r.team_strengths([1600, 1500, 1500, 1500], banker_team=0) == (1590.0, 1500.0)
    assert r.team_strengths([1600, 1500, 1500, 1500], banker_team=1) == (1550.0, 1540.0)


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
    assert event["rating_after"] == pytest.approx(1500 + event["delta"])
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
    _set(store, a, 1600, rounds=30)
    _set(store, b, 1500, rounds=30)
    _force_outcome(monkeypatch, 130)           # attackers 130: they win 1 level
    table = Table(srv, [a, None, b, "bot"])
    result = table.play_round(banker=1)
    assert result.winner_team == 0 and result.level_change == 1
    events = _events(store)
    assert sorted(e["user_id"] for e in events) == [a, b]
    da, db = (e["delta"] for e in sorted(events, key=lambda e: e["user_id"]))
    assert da == pytest.approx(db)
    # team 0 = (1600 + 1500) / 2 = 1550; team 1 = guest 1500 + bot 1500, banker +40
    exp = 1 / (1 + 10 ** ((1540 - 1550) / 400))
    assert events[0]["expected"] == pytest.approx(exp)
    assert da == pytest.approx(20 * (2 / 3 - exp))
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_a_guest_seat_counts_1500_whatever_the_guest_is_called(env, monkeypatch):
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
    _set(store, old, 1500, rounds=40)
    _force_outcome(monkeypatch, 30)
    Table(srv, [new, "bot", old, "bot"]).play_round(banker=0)
    by = {e["user_id"]: e for e in _events(store)}
    assert by[new]["k"] == 40 and by[old]["k"] == 20
    assert by[new]["delta"] == pytest.approx(2 * by[old]["delta"])


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


# ------------------------------------------------------------------ abandon
def test_leaving_mid_round_is_a_loss_for_that_round_only(env, monkeypatch):
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
    assert by[quitter]["abandoned"] == 1 and by[quitter]["actual"] == 0.0
    assert by[quitter]["won"] == 0 and by[quitter]["delta"] < 0
    assert by[partner]["abandoned"] == 0 and by[partner]["delta"] > 0
    # The next round, with the bot covering the absent seat, rates only the partner.
    seat.bot_announced = True
    table.play_round()
    assert [e["user_id"] for e in _events(store) if e["round_no"] == 2] == [partner]


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
    assert event["abandoned"] == 1 and event["actual"] == 0.0


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
    assert board["anchor"] == {"name": "Sheng Ji bot", "rating": 1500}
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
    assert len(stats["history"]) == 4 and stats["history"][0] == 1500
    assert stats["history"][-1] == stats["rating"] > 1500
    [game] = stats["recent_games"]
    assert game["rounds"] == 3 and game["partner_bot"] is True and game["opponents_bots"] == 2
    assert abs(game["delta"] - (stats["rating"] - 1500)) <= 1

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
        old.upsert_user(_claims(sub="before"))
        assert old.schema_version() == 3
    finally:
        accounts_on.SCHEMA[:] = real
    store = accounts_on.Store(path)
    assert store.schema_version() == len(real) == 4
    row = store.user(1)
    assert row["rating"] == 1500 and row["rated_rounds"] == 0 and row["leaderboard_visible"] == 1
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        accounts_on._migrate_v4(db)            # a re-run changes nothing
        db.commit()
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert {"rating_events", "rating_events_user", "rating_events_created"} <= names
    assert accounts_on.Store(path).schema_version() == 4
