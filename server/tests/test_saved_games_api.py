"""Saved games, read API (``/api/me/games``) and deletion.

Rounds are played in-process through the server's own logging functions
(``_log_round_start``, ``bot_step``, ``_log_round_end``) with the heuristic
bot on every seat, so the log the API slices is the real record format; the
saved-game hooks run inline (no event loop), exactly as queued writes would.
"""
from __future__ import annotations

import json

import pytest

from tests.test_accounts import _claims, accounts_on, keypair  # noqa: F401
from tests.test_server_ws import client  # noqa: F401

FORBIDDEN = ("decision", "model_search", "bot_timing", "declare_decision", "bot_seed",
             "chat", "secret-reasoning", "never-served-text")


def _user(store, sub):
    user = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com"))
    return user["id"], {"cookie": f"sj_session={store.create_session(user['id'])}"}


class Table:
    """A room whose four seats the test assigns to accounts (None = guest)."""

    def __init__(self, srv, code="REPL", users=(None, None, None, None)):
        from shengji.engine.game import Game

        self.srv = srv
        self.room = srv.Room(code=code)
        self.room.seats = [srv.Seat(name=f"P{i}", user_id=u) for i, u in enumerate(users)]
        bot = self.room.bot
        original = bot.decide_play

        def decide_play(rnd, seat):
            cards = original(rnd, seat)
            bot.last_decision_record = {"played": list(cards), "why": "secret-reasoning"}
            return cards

        bot.decide_play = decide_play
        self.room.game = Game(start_level="2", games_to_win=None)

    def start_round(self, first=False):
        from shengji.api import saved_games

        srv, room = self.srv, self.room
        room.game.start_round()
        room.index_round()
        offset = srv._log_round_start(room)
        if first:
            saved_games.start(room, offset, srv.LOG_DIR)
        else:
            saved_games.round_started(room)
        rnd = room.round
        while rnd.phase == "deal":
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code
        rnd.finalize_declare()
        room.log_event("trump", suit=rnd.trump_suit or "NT", rank=rnd.trump_rank,
                       banker=rnd.banker, declared=rnd.declaration is not None)
        room.log_event("declare_decision", seat=0, record={"why": "secret-reasoning"}, bot=True)
        room.log_event("chat", seat=0, text="never-served-text", bot=False)

    def act(self, plays=None):
        """Bot actions until the round ends, or ``plays`` of them."""
        srv, room = self.srv, self.room
        n = 0
        while room.round.phase in ("bury", "play") and (plays is None or n < plays):
            seat = room.round.banker if room.round.phase == "bury" else room.round.turn
            assert srv.bot_step(room, seat)
            room.log_event("model_search", seat=seat, mode="bot", why="secret-reasoning")
            room.log_event("bot_timing", seat=seat, phase="play", compute_seconds=0.1)
            n += 1

    def sign(self, seat, user_id):
        from shengji.api import saved_games

        self.room.seats[seat].user_id = user_id
        saved_games.seat_changed(self.room, seat)

    @property
    def game_id(self):
        return self.room.saved_game.id


@pytest.fixture()
def api(accounts_on, client):
    from shengji.api import saved_games, server as srv

    saved_games.READ_LIMITER.reset()
    saved_games._segments.clear()
    saved_games._names.clear()
    return srv, accounts_on.STORE, client


def _round(client, headers, game_id, n):
    return client.get(f"/api/me/games/{game_id}/rounds/{n}", headers=headers)


def _strings(value):
    return json.dumps(value)


def test_owner_reads_the_game_and_another_account_gets_404(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    _other, other_h = _user(store, "other")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    t.start_round()
    t.act()

    listed = client.get("/api/me/games", headers=owner_h)
    assert listed.status_code == 200
    body = listed.json()
    assert body["next_before"] is None
    [game] = body["games"]
    assert game["id"] == t.game_id and game["room_code"] == "REPL"
    assert game["seat"] == 0 and game["rounds"] == [1, 2]
    assert game["players"] == ["P0", "P1", "P2", "P3"]
    assert game["incomplete"] is False and game["ended_at"] is not None
    assert game["final_levels"] == list(t.room.game.levels)
    assert set(game) == {"id", "room_code", "started_at", "ended_at", "seat", "players",
                         "rounds", "final_levels", "games_won", "incomplete"}

    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert [r["round"] for r in detail["round_results"]] == [1, 2]
    assert set(detail["round_results"][0]["result"]) >= {"attacker_points", "winner_team",
                                                         "new_levels", "kitty"}
    assert all(r["seat"] == 0 for r in detail["round_results"])

    for path in (f"/api/me/games/{t.game_id}", f"/api/me/games/{t.game_id}/rounds/1"):
        assert client.get(path, headers=other_h).status_code == 404
        assert client.get(path).status_code == 401
    assert client.get("/api/me/games").status_code == 401
    assert client.get("/api/me/games", headers=other_h).json() == {"games": [],
                                                                    "next_before": None}

    first = _round(client, owner_h, t.game_id, 1).json()
    assert first["finished"] is True and first["seat"] == 0 and first["round"] == 1
    kinds = [e["e"] for e in first["events"]]
    assert kinds[0] == "round_start" and kinds[-1] == "round_end"
    assert {"trump", "bury", "play", "trick"} <= set(kinds)


def test_events_keep_the_log_keys_minus_the_forbidden_ones(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    served = _round(client, owner_h, t.game_id, 1).json()
    text = _strings(served)
    for word in FORBIDDEN:
        assert word not in text
    raw = [json.loads(line) for line in (srv.LOG_DIR / "REPL.jsonl").read_text().splitlines()]
    assert any("decision" in r for r in raw if r["e"] == "play")      # the log has them
    logged = [r for r in raw if r["e"] in {"round_start", "trump", "bury", "play", "trick",
                                           "round_end"}]
    assert len(logged) == len(served["events"])
    for rec, ev in zip(logged, served["events"]):
        assert ev["e"] == rec["e"]
        assert set(ev) == set(rec) - {"decision", "bot_seed"}
        if rec["e"] != "round_start":
            assert ev == {k: rec[k] for k in ev}       # a finished round shows everything
    assert served["events"][0]["deck"] == logged[0]["deck"]


def test_each_round_result_names_its_level_and_banker(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    t.start_round()
    t.act()
    raw = [json.loads(line) for line in (srv.LOG_DIR / "REPL.jsonl").read_text().splitlines()]
    trump = {r["round"]: r for r in raw if r["e"] == "trump"}
    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert [r["round"] for r in detail["round_results"]] == [1, 2]
    for row in detail["round_results"]:
        assert row["level"] == trump[row["round"]]["rank"]
        assert row["banker"] == trump[row["round"]]["banker"]
        assert row["banker"] in range(4)


def test_hidden_cards_before_round_end(api):
    srv, store, client = api
    users = [store.upsert_user(_claims(sub=f"s{i}"))["id"] for i in range(4)]
    heads = [{"cookie": f"sj_session={store.create_session(u)}"} for u in users]
    t = Table(srv, users=tuple(users))
    t.start_round(first=True)
    t.act(plays=3)                              # the bury plus two plays
    banker = t.room.round.banker
    deck = t.room.round.deck
    for seat in range(4):
        r = _round(client, heads[seat], t.game_id, 1).json()
        assert r["finished"] is False and r["seat"] == seat
        start = r["events"][0]
        assert start["e"] == "round_start" and "bot_seed" not in start
        for i, card in enumerate(start["deck"]):
            if i < 100:
                assert card == (deck[i] if i % 4 == seat else None)
            else:
                assert card == (deck[i] if seat == banker else None)
        [bury] = [e for e in r["events"] if e["e"] == "bury"]
        assert (bury["cards"] is not None) == (seat == banker)
        plays = [e for e in r["events"] if e["e"] == "play"]
        assert len(plays) == 2 and all(p["cards"] for p in plays)
    # Once the round ends every hand and the kitty are shown.
    t.act()
    for seat in range(4):
        r = _round(client, heads[seat], t.game_id, 1).json()
        assert r["finished"] is True
        assert r["events"][0]["deck"] == deck
        [bury] = [e for e in r["events"] if e["e"] == "bury"]
        assert bury["cards"] is not None


def test_mid_game_sign_in_reads_only_from_that_round(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    late, late_h = _user(store, "late")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    t.start_round()
    t.sign(1, late)                              # the guest at seat 1 signs in during round 2
    t.act()
    [game] = client.get("/api/me/games", headers=late_h).json()["games"]
    assert game["rounds"] == [2] and game["seat"] == 1
    assert _round(client, late_h, t.game_id, 1).status_code == 404
    second = _round(client, late_h, t.game_id, 2).json()
    assert second["seat"] == 1
    detail = client.get(f"/api/me/games/{t.game_id}", headers=late_h).json()
    assert [r["round"] for r in detail["round_results"]] == [2]
    # signing in between rounds links from the next round
    t.start_round()
    t.act()
    t.sign(2, late)
    t.start_round()
    t.act()
    [game] = client.get("/api/me/games", headers=late_h).json()["games"]
    assert game["rounds"] == [2, 3, 4]
    assert _round(client, late_h, t.game_id, 3).json()["seat"] == 1


def test_a_seat_change_shows_each_round_from_the_seat_held_then(api):
    srv, store, client = api
    mover, mover_h = _user(store, "mover")
    t = Table(srv, users=(mover, None, None, None))
    t.start_round(first=True)
    t.act()
    t.sign(0, None)                              # leaves seat 0 at round 1's end
    t.sign(2, mover)                             # takes seat 2 for round 2 on
    t.start_round()
    t.act()
    one = _round(client, mover_h, t.game_id, 1).json()
    two = _round(client, mover_h, t.game_id, 2).json()
    assert (one["seat"], two["seat"]) == (0, 2)
    detail = client.get(f"/api/me/games/{t.game_id}", headers=mover_h).json()
    assert [(r["round"], r["seat"]) for r in detail["round_results"]] == [(1, 0), (2, 2)]
    assert detail["seat"] == 2


def test_out_of_range_rounds_and_bad_ids_are_404(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    for n in ("0", "2", "99", "-1", "abc", "1.0", "9999999"):
        assert _round(client, owner_h, t.game_id, n).status_code == 404, n
    for bad in ("x" * 32, "../etc", t.game_id.upper(), t.game_id[:-1]):
        assert client.get(f"/api/me/games/{bad}", headers=owner_h).status_code == 404
        assert _round(client, owner_h, bad, 1).status_code == 404


def test_a_reused_room_code_reads_each_game_from_its_own_offset(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    first = Table(srv, code="SAME", users=(owner, None, None, None))
    first.start_round(first=True)
    first.act()
    first.room.log_event("chat", seat=0, text="lobby of the next room", bot=False)
    first.room.game = None
    second = Table(srv, code="SAME", users=(owner, None, None, None))
    second.room.log_event("chat", seat=0, text="lobby", bot=False)
    second.start_round(first=True)
    second.act()
    games = client.get("/api/me/games", headers=owner_h).json()["games"]
    assert {g["id"] for g in games} == {first.game_id, second.game_id}
    a = _round(client, owner_h, first.game_id, 1).json()
    b = _round(client, owner_h, second.game_id, 1).json()
    assert a["events"][0]["deck"] != b["events"][0]["deck"]
    assert [e["e"] for e in a["events"]].count("round_start") == 1
    assert [e["e"] for e in b["events"]].count("round_start") == 1


def test_list_pages_newest_first(api):
    import sqlite3
    import time as _time
    from contextlib import closing

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    base = int(_time.time()) - 100
    ids = []
    for i in range(3):
        t = Table(srv, code=f"PG{i}A", users=(owner, None, None, None))
        t.start_round(first=True)
        ids.append(t.game_id)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute("UPDATE games SET started_at = ? WHERE id = ?", (base + i, t.game_id))
            db.commit()
    page = client.get("/api/me/games?limit=2", headers=owner_h).json()
    assert [g["id"] for g in page["games"]] == [ids[2], ids[1]]
    assert page["next_before"] == f"{base + 1}:{ids[1]}"
    rest = client.get(f"/api/me/games?limit=2&before={page['next_before']}",
                      headers=owner_h).json()
    assert [g["id"] for g in rest["games"]] == [ids[0]] and rest["next_before"] is None
    assert len(client.get("/api/me/games?limit=999", headers=owner_h).json()["games"]) == 3
    assert len(client.get("/api/me/games?limit=0", headers=owner_h).json()["games"]) == 1


def test_hide_removes_the_game_for_that_account_only(api):
    srv, store, client = api
    a, a_h = _user(store, "a")
    b, b_h = _user(store, "b")
    t = Table(srv, users=(a, b, None, None))
    t.start_round(first=True)
    t.act()
    assert client.delete(f"/api/me/games/{t.game_id}").status_code == 401
    resp = client.delete(f"/api/me/games/{t.game_id}", headers=a_h)
    assert resp.status_code == 204 and resp.content == b""
    assert client.get("/api/me/games", headers=a_h).json()["games"] == []
    assert client.get(f"/api/me/games/{t.game_id}", headers=a_h).status_code == 404
    assert _round(client, a_h, t.game_id, 1).status_code == 404
    assert client.delete(f"/api/me/games/{t.game_id}", headers=a_h).status_code == 404
    assert len(client.get("/api/me/games", headers=b_h).json()["games"]) == 1


def test_account_delete_cascades_and_clears_the_cookie(api):
    import sqlite3
    from contextlib import closing

    srv, store, client = api
    a, a_h = _user(store, "a")
    b, b_h = _user(store, "b")
    t = Table(srv, users=(a, b, None, None))
    t.start_round(first=True)
    t.act()
    assert client.delete("/api/me").status_code == 401
    resp = client.delete("/api/me", headers=a_h)
    assert resp.status_code == 204
    assert 'sj_session=""' in resp.headers["set-cookie"] or "Max-Age=0" in resp.headers["set-cookie"]
    assert client.get("/api/me", headers=a_h).status_code == 401
    assert client.get("/api/me/games", headers=a_h).status_code == 401
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE id = ?", (a,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (a,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM game_players WHERE user_id = ?",
                          (a,)).fetchone()[0] == 0
    # the other player's history and the room log are unchanged
    assert len(client.get("/api/me/games", headers=b_h).json()["games"]) == 1
    assert (srv.LOG_DIR / "REPL.jsonl").exists()
    # a seat still held by the deleted account links nothing more
    t.start_round()
    t.act()
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM game_players WHERE user_id = ?",
                          (a,)).fetchone()[0] == 0


def test_the_read_byte_cap_stops_a_scan(api, monkeypatch):
    from shengji.api import saved_games

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    t.start_round()
    t.act()
    # The cap ends the scan at round 2's first record, so round 2 is never
    # reached whatever length the dealt rounds have.
    blob = (srv.LOG_DIR / "REPL.jsonl").read_bytes()
    round_2 = blob.index(b'"round": 2, "e": "round_start"')
    monkeypatch.setattr(saved_games, "READ_BYTE_CAP", blob.rindex(b"\n", 0, round_2) + 1)
    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert detail["incomplete"] is True
    assert _round(client, owner_h, t.game_id, 2).status_code == 404


# ------------------------------------------------- a round still being dealt
def test_a_live_round_shows_no_deck_card_until_the_deal_completes(api):
    """Through the real start hook and endpoint: before the first card and
    part-way through the deal the viewer sees no deck position at all (the
    log does not say how far the deal had gone); once ``trump`` is logged
    the viewer's own 25 appear, and the kitty only to the banker."""
    from shengji.api import saved_games

    srv, store, client = api
    owner, headers = _user(store, "deal-owner")
    t = Table(srv, users=(owner, None, None, None))
    room = t.room
    room.game.start_round()
    room.index_round()
    saved_games.start(room, srv._log_round_start(room), srv.LOG_DIR)
    rnd = room.round
    assert rnd.phase == "deal" and rnd.hands[0] == []

    def deck_shown():
        r = _round(client, headers, t.game_id, 1)
        assert r.status_code == 200 and r.json()["finished"] is False
        start = r.json()["events"][0]
        assert start["e"] == "round_start" and len(start["deck"]) == len(rnd.deck)
        return [(i, c) for i, c in enumerate(start["deck"]) if c is not None]

    assert deck_shown() == []                               # before the first card
    for _ in range(37):                                     # part-way: 9 or 10 each
        seat, idx, code = rnd.deal_next()
        room.ids[seat][idx] = code
    room.log_event("declare", seat=1, cards=[], bot=True)
    assert rnd.phase == "deal" and 0 < len(rnd.hands[0]) < 25
    assert deck_shown() == []                               # during the deal
    while rnd.phase == "deal":
        seat, idx, code = rnd.deal_next()
        room.ids[seat][idx] = code
    assert deck_shown() == []                               # dealt, declaring open
    rnd.finalize_declare()
    room.log_event("trump", suit=rnd.trump_suit or "NT", rank=rnd.trump_rank,
                   banker=rnd.banker, declared=rnd.declaration is not None)
    own = [(i, rnd.deck[i]) for i in range(100) if i % 4 == 0]
    kitty = [(i, rnd.deck[i]) for i in range(100, 108)]
    assert deck_shown() == own + (kitty if rnd.banker == 0 else [])


# --------------------------------------- deletion while the table stays live
def test_a_deleted_account_is_detached_from_live_seats_and_its_id_not_reused(
        api, monkeypatch):
    """Delete while the room stays live, then an unrelated signup and a new
    game on the same table: the stranger gets a fresh id, the live seat no
    longer carries the old one, and nothing links to either account."""
    import sqlite3
    from contextlib import closing

    from shengji.api import saved_games
    from shengji.engine.game import Game

    srv, store, client = api
    owner, headers = _user(store, "old-owner")
    t = Table(srv, code="LIVE", users=(owner, None, None, None))
    monkeypatch.setitem(srv.rooms, t.room.code, t.room)
    t.start_round(first=True)
    assert t.room.saved_game.open == {0: owner}
    assert client.delete("/api/me", headers=headers).status_code == 204
    assert t.room.seats[0].user_id is None
    assert t.room.saved_game.open == {}
    stranger, stranger_h = _user(store, "unrelated-new-user")
    assert stranger != owner
    # the rest of this game and the next game on the table
    t.act()
    t.start_round()
    t.act(plays=4)
    room = t.room
    room.game = Game(start_level="2", games_to_win=None)
    room.game.start_round()
    room.index_round()
    saved_games.start(room, srv._log_round_start(room), srv.LOG_DIR)
    assert room.saved_game.open == {}
    # a link write naming the deleted id is refused, even straight to the store
    assert store.link_seat(room.saved_game.header(), owner, 0, 1) is False
    assert client.get("/api/me/games", headers=stranger_h).json() == {
        "games": [], "next_before": None}
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM game_players").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def test_a_socket_left_open_across_its_account_delete_is_signed_out(api):
    from tests.test_server_ws import _drain

    srv, store, client = api
    owner, headers = _user(store, "socket-owner")
    with client.websocket_connect("/ws", headers=headers) as ws:
        ws.send_json({"type": "create_room"})
        room = _drain(ws, "room")
        assert room["players"][0]["name"] == "Jerry"
        seat = srv.rooms[room["room"]].seats[0]
        assert seat.user_id == owner
        assert client.delete("/api/me", headers=headers).status_code == 204
        assert seat.user_id is None
        stranger, _h = _user(store, "unrelated-new-user")
        assert stranger != owner
        # The same socket leaves and opens a new table: a guest seat now.
        ws.send_json({"type": "leave_room"})
        ws.send_json({"type": "create_room"})
        again = _drain(ws, "room")
        assert again["room"] != room["room"]
        assert again["players"][0]["name"] == "Player"
        assert srv.rooms[again["room"]].seats[0].user_id is None


def test_list_pages_through_games_that_share_a_start_second(api):
    import sqlite3
    import time as _time
    from contextlib import closing

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    same = int(_time.time()) - 100
    ids = []
    for i in range(5):
        t = Table(srv, code=f"TIE{i}", users=(owner, None, None, None))
        t.start_round(first=True)
        ids.append(t.game_id)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute("UPDATE games SET started_at = ? WHERE id = ?", (same, t.game_id))
            db.commit()
    seen, url = [], "/api/me/games?limit=2"
    while True:
        page = client.get(url, headers=owner_h).json()
        seen += [g["id"] for g in page["games"]]
        if page["next_before"] is None:
            break
        assert isinstance(page["next_before"], str)
        url = f"/api/me/games?limit=2&before={page['next_before']}"
    assert seen == sorted(ids, reverse=True)
    assert client.get("/api/me/games?before=nope", headers=owner_h).status_code == 400
    # a bare integer still reads as "started before that second"
    assert client.get(f"/api/me/games?before={same}", headers=owner_h).json()["games"] == []


def _ranked_table(srv, users, code="RANK"):
    """A Ranked table whose signed-in seats are connected, so its rounds are
    rated through the real ratings hooks."""
    from shengji.api import ratings

    t = Table(srv, code=code, users=users)
    t.room.ranked = True
    for seat in t.room.seats:
        seat.connected = True
    t.start_round(first=True)
    ratings.start(t.room)
    return t


def _my_events(store, user_id):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT * FROM rating_events WHERE user_id = ? ORDER BY id", (user_id,))]


def test_a_ranked_game_shows_the_viewers_own_rating_change(api):
    from shengji.api import ratings

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    other, other_h = _user(store, "other")
    t = _ranked_table(srv, (owner, other, None, None))
    t.act()
    for _ in range(2):
        t.start_round()
        ratings.round_started(t.room)
        t.act()
    ratings.flush()

    mine = _my_events(store, owner)
    theirs = _my_events(store, other)
    assert len(mine) == 3 and len(theirs) == 3
    # a rated round's game id is the saved game's id plus its segment
    assert {e["game_id"] for e in mine} == {f"{t.game_id}/0"}
    assert sum(e["delta"] for e in mine) != sum(e["delta"] for e in theirs)

    [game] = client.get("/api/me/games", headers=owner_h).json()["games"]
    assert game["rating_change"] == round(sum(e["delta"] for e in mine))
    assert game["rating_after"] == round(mine[-1]["rating_after"])
    assert game["rated_rounds"] == 3

    [seen] = client.get("/api/me/games", headers=other_h).json()["games"]
    assert seen["rating_change"] == round(sum(e["delta"] for e in theirs))
    assert seen["rating_after"] == round(theirs[-1]["rating_after"])

    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert detail["rating_change"] == game["rating_change"]
    assert [r["rating_delta"] for r in detail["round_results"]] == [
        round(e["delta"]) for e in mine]
    # another account's per-round figures never appear in this one's game
    other_detail = client.get(f"/api/me/games/{t.game_id}", headers=other_h).json()
    assert [r["rating_delta"] for r in other_detail["round_results"]] == [
        round(e["delta"]) for e in theirs]


def test_an_unranked_game_carries_no_rating_keys(api):
    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()

    [game] = client.get("/api/me/games", headers=owner_h).json()["games"]
    assert not {"rating_change", "rating_after", "rated_rounds"} & set(game)
    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert not {"rating_change", "rating_after", "rated_rounds"} & set(detail)
    assert all("rating_delta" not in r for r in detail["round_results"])


def test_another_accounts_rating_events_never_count(api):
    """An account rated in a game it has no link to (seated as a guest, so
    the saved game is not its own) adds nothing to the linked account's row."""
    import sqlite3
    from contextlib import closing

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    other, _ = _user(store, "other")
    t = Table(srv, users=(owner, None, None, None))
    t.start_round(first=True)
    t.act()
    with closing(sqlite3.connect(store.path)) as db:
        db.execute(
            """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                   banker_team, won, levels, expected, actual, k, rating_before,
                   rating_after, delta)
               VALUES (?, 1, ?, 0, 1, 0, 1, 1, 0.5, 1, 20, 1000, 1030, 30)""",
            (f"{t.game_id}/0", other))
        db.commit()

    [game] = client.get("/api/me/games", headers=owner_h).json()["games"]
    assert "rating_change" not in game
    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert all("rating_delta" not in r for r in detail["round_results"])


def test_every_segment_of_a_saved_game_counts(api):
    """A table plays on past a held Ace as a new segment (``/<n>`` on the
    rated round's game id) of the same saved game: both segments sum."""
    from shengji.api import ratings

    srv, store, client = api
    owner, owner_h = _user(store, "owner")
    t = _ranked_table(srv, (owner, None, None, None), code="SEGS")
    t.act()
    t.room.ratings.game_no += 1          # the boundary a held Ace crosses
    for _ in range(2):
        t.start_round()
        ratings.round_started(t.room)
        t.act()
    ratings.flush()

    mine = _my_events(store, owner)
    assert [e["game_id"] for e in mine] == [f"{t.game_id}/0", f"{t.game_id}/1", f"{t.game_id}/1"]
    [game] = client.get("/api/me/games", headers=owner_h).json()["games"]
    assert game["rating_change"] == round(sum(e["delta"] for e in mine))
    assert game["rating_after"] == round(mine[-1]["rating_after"])
    assert game["rated_rounds"] == 3
    detail = client.get(f"/api/me/games/{t.game_id}", headers=owner_h).json()
    assert [r["rating_delta"] for r in detail["round_results"]] == [
        round(e["delta"]) for e in mine]
