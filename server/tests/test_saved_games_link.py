"""Saved games, link side (``shengji.api.saved_games`` hooks in the server).

The websocket tests ride the real protocol: a signed-in seat is linked when
the table starts, a guest seat never is, a reused room code gives two games
with their own exact log offsets, a failing database leaves play alone and
counts the failure, and no log record ever carries the account.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_accounts import _claims, _session_cookie, accounts_on, keypair  # noqa: F401
from tests.test_server_ws import _drain, _room_with_bots, client  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_activity(monkeypatch):
    from shengji.api import server

    activity = server.Activity()
    monkeypatch.setattr(server, "ACTIVITY", activity)
    return activity


def _rows(store, sql, *args):
    from shengji.api import saved_games

    saved_games.flush()
    if not Path(store.path).exists():
        return []
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in db.execute(sql, args)]
        except sqlite3.OperationalError:
            return []


def _record_at(path: Path, offset: int) -> dict:
    with open(path, "rb") as f:
        f.seek(offset)
        return json.loads(f.readline())


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _log_records(srv, code):
    return [json.loads(line) for line in
            (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()]


def _start_signed_in_with_a_guest(client, cookie):
    """Seat 0 signed in, seat 1 a guest, seats 2 and 3 bots; returns sockets."""
    a = client.websocket_connect("/ws", headers={"cookie": cookie})
    a.__enter__()
    a.send_json({"type": "create_room", "name": "Jerry"})
    code = _drain(a, "room")["room"]
    g = client.websocket_connect("/ws")
    g.__enter__()
    g.send_json({"type": "join_room", "room": code, "name": "Guest"})
    _drain(g, "room")
    for _ in range(2):
        a.send_json({"type": "add_bot"})
    a.send_json({"type": "start_game"})
    _drain(a, "state", tries=60)
    return code, a, g


def test_log_event_returns_the_exact_byte_offset(client):
    from shengji.api import server as srv

    room = srv.Room(code="OFFS")
    first = room.log_event("chat", seat=0, text="héllo", bot=False)
    second = room.log_event("chat", seat=0, text="again", bot=False)
    path = srv.LOG_DIR / "OFFS.jsonl"
    assert first == 0 and second == len(path.read_bytes().splitlines(keepends=True)[0])
    assert _record_at(path, second)["text"] == "again"
    # The bytes match a text-mode write: json.dumps escapes to ASCII.
    assert path.read_bytes().decode("ascii").count("\n") == 2


def test_signed_in_seat_is_linked_and_guest_seat_is_not(accounts_on, keypair, client):
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    code, a, g = _start_signed_in_with_a_guest(client, cookie)
    try:
        store = accounts_on.STORE
        [game] = _rows(store, "SELECT * FROM games")
        assert game["room_code"] == code and game["log_file"] == f"{code}.jsonl"
        assert game["last_round"] == 1 and game["incomplete"] == 0
        start = _record_at(srv.LOG_DIR / game["log_file"], game["log_offset"])
        assert start["e"] == "round_start" and start["round"] == 1
        players = _rows(store, "SELECT user_id, seat, from_round, to_round, hidden FROM game_players")
        assert players == [{"user_id": 1, "seat": 0, "from_round": 1, "to_round": None,
                            "hidden": 0}]
        assert srv.rooms[code].saved_game.id == game["id"]
    finally:
        g.__exit__(None, None, None)
        a.__exit__(None, None, None)


def test_a_game_nobody_signed_in_to_never_touches_the_database(accounts_on, client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        _drain(a, "state", tries=60)
        assert srv.rooms[code].saved_game is not None
        assert _rows(accounts_on.STORE, "SELECT * FROM games") == []
    assert not Path(accounts_on.STORE.path).exists()


def test_a_reused_room_code_gives_two_games_with_distinct_offsets(
        accounts_on, keypair, client, monkeypatch):
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    monkeypatch.setattr(srv, "new_code", lambda: "SAME")
    ids = []
    for _ in range(2):
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
            code = _room_with_bots(a)
            assert code == "SAME"
            a.send_json({"type": "start_game"})
            _drain(a, "state", tries=60)
            room = srv.rooms.pop(code)          # the room is gone; the code is free
            ids.append(room.saved_game.id)
            for task in (room.deal_task, room.bot_task, room.cleanup_task):
                if task is not None:
                    task.cancel()
    games = _rows(accounts_on.STORE, "SELECT id, log_file, log_offset FROM games ORDER BY log_offset")
    assert [g["id"] for g in games] == ids and len(set(ids)) == 2
    assert {g["log_file"] for g in games} == {"SAME.jsonl"}
    first, second = (g["log_offset"] for g in games)
    assert first < second
    for offset in (first, second):
        rec = _record_at(srv.LOG_DIR / "SAME.jsonl", offset)
        assert rec["e"] == "round_start" and rec["round"] == 1


def test_a_failing_database_leaves_play_alone_and_is_counted(
        accounts_on, keypair, client, fresh_activity, monkeypatch):
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(accounts_on.STORE, "link_seat", broken)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        st = _drain(a, "state", tries=60)
        assert st["phase"] in ("deal", "declare", "bury", "play")
        st = _drain(a, "state", tries=400)        # the deal keeps going
        assert _wait_for(lambda: fresh_activity.account_link_failures >= 1)
        shown = client.get("/healthz").json()["activity"]
        assert shown["account_link_failures"] >= 1
        assert shown["record_write_failures"] == 0
        assert srv.rooms[code].game is not None


def test_a_hook_that_raises_is_counted_not_raised(fresh_activity, monkeypatch):
    from shengji.api import saved_games

    monkeypatch.setattr(saved_games, "eligible", lambda *a: 1 / 0)
    room = SimpleNamespace(saved_game="x")
    saved_games.start(room, 0, Path("."))
    assert fresh_activity.account_link_failures == 1


def test_no_log_record_carries_the_account(accounts_on, keypair, client):
    """The Seat.user_id invariant: the account reaches the database only."""
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    code, a, g = _start_signed_in_with_a_guest(client, cookie)
    try:
        token = srv.rooms[code].seats[1].token
        g.__exit__(None, None, None)
        # the guest signs in mid-game and resumes their seat
        cookie2 = _session_cookie(accounts_on, client, private_pem, sub="222",
                                  email="other@example.com", name="Other Person")
        with client.websocket_connect("/ws", headers={"cookie": cookie2}) as b:
            b.send_json({"type": "join_room", "room": code, "name": "Guest", "token": token})
            _drain(b, "state", tries=60)
            a.send_json({"type": "chat", "text": "hi"})
            _drain(a, "chat", tries=400)
        game_id = srv.rooms[code].saved_game.id
        links = _rows(accounts_on.STORE,
                      "SELECT user_id, seat, from_round, to_round FROM game_players ORDER BY user_id")
        assert links == [{"user_id": 1, "seat": 0, "from_round": 1, "to_round": None},
                         {"user_id": 2, "seat": 1, "from_round": 1, "to_round": None}]
    finally:
        a.__exit__(None, None, None)
    raw = (srv.LOG_DIR / f"{code}.jsonl").read_text()
    assert game_id not in raw
    for needle in ("jerry@example.com", "other@example.com", "10987654321", '"222"',
                   "Jerry Yu", "Other Person", "user_id", "google_sub", "sj_session"):
        assert needle not in raw

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    allowed = None
    for rec in _log_records(srv, code):
        found = set(keys(rec))
        assert not found & {"user_id", "account", "game_id", "email", "sub"}
        allowed = found if allowed is None else allowed | found
    assert allowed


def _fake_room(round_no, phase, seats):
    return SimpleNamespace(
        code="FAKE", experimental_policy=None, evaluation=None, log_dir=Path("/logs"),
        game=SimpleNamespace(round_no=round_no), round=SimpleNamespace(phase=phase),
        seats=[SimpleNamespace(user_id=u, is_bot=u is None) for u in seats],
        saved_game=None)


def test_mid_game_sign_in_links_from_the_current_round(accounts_on):
    from shengji.api import saved_games

    store = accounts_on.STORE
    a = store.upsert_user(_claims(sub="a"))["id"]
    b = store.upsert_user(_claims(sub="b"))["id"]
    room = _fake_room(1, "play", [a, None, None, None])
    room.seats[1].is_bot = False                 # a guest human at seat 1
    saved_games.start(room, 0, Path("/logs"))
    # Round 3 under way: the guest at seat 1 signs in.
    room.game.round_no, room.round.phase = 3, "play"
    room.seats[1].user_id = b
    saved_games.seat_changed(room, 1)
    # Between rounds 4 and 5 seat 0 changes hands: a leaves, b takes it.
    room.game.round_no, room.round.phase = 4, "round_end"
    room.seats[0].user_id = b
    saved_games.seat_changed(room, 0)
    saved_games.seat_changed(room, 0)            # no change: nothing written
    links = _rows(store, "SELECT user_id, seat, from_round, to_round FROM game_players "
                         "ORDER BY user_id, from_round, seat")
    assert links == [{"user_id": a, "seat": 0, "from_round": 1, "to_round": 4},
                     {"user_id": b, "seat": 1, "from_round": 3, "to_round": None},
                     {"user_id": b, "seat": 0, "from_round": 5, "to_round": None}]
    saved_games.round_ended(room, SimpleNamespace(new_levels=["5", "2"], games_won=[0, 0]))
    room.game.round_no, room.round.phase = 5, "deal"
    saved_games.round_started(room)
    [game] = _rows(store, "SELECT last_round, final_levels, games_won, ended_at FROM games")
    assert game["last_round"] == 5 and json.loads(game["final_levels"]) == ["5", "2"]
    assert game["ended_at"] is not None


def test_a_round_summary_before_the_first_link_reaches_the_row(accounts_on):
    from shengji.api import saved_games

    store = accounts_on.STORE
    a = store.upsert_user(_claims(sub="a"))["id"]
    room = _fake_room(1, "play", [None, None, None, None])
    room.seats[0].is_bot = False
    saved_games.start(room, None, Path("/logs"))   # round 1's record never reached disk
    room.round.phase = "round_end"
    saved_games.round_ended(room, SimpleNamespace(new_levels=["3", "2"], games_won=[0, 0]))
    assert _rows(store, "SELECT * FROM games") == []
    room.seats[0].user_id = a
    saved_games.seat_changed(room, 0)
    [game] = _rows(store, "SELECT * FROM games")
    assert json.loads(game["final_levels"]) == ["3", "2"]
    assert game["incomplete"] == 1 and game["log_offset"] is None
    assert _rows(store, "SELECT from_round FROM game_players") == [{"from_round": 2}]


def test_training_excluded_rooms_are_not_linked(client, tmp_path):
    from shengji.api import saved_games
    from shengji.api import server as srv

    ordinary = srv.Room(code="ORDN")
    assert saved_games.eligible(ordinary, srv.LOG_DIR)
    test_room = srv.Room(code="TEST", experimental_policy="w32", log_dir=tmp_path / "test-root")
    assert not saved_games.eligible(test_room, srv.LOG_DIR)
    elsewhere = srv.Room(code="ELSE", log_dir=tmp_path / "elsewhere")
    assert not saved_games.eligible(elsewhere, srv.LOG_DIR)
    evaluation = SimpleNamespace(experimental_policy=None, evaluation=object(),
                                 log_dir=srv.LOG_DIR)
    assert not saved_games.eligible(evaluation, srv.LOG_DIR)
    test_room.game = SimpleNamespace(round_no=1)
    saved_games.start(test_room, 0, srv.LOG_DIR)
    assert test_room.saved_game is None


def test_a_failed_log_write_marks_a_linked_game_incomplete(accounts_on):
    from shengji.api import saved_games

    store = accounts_on.STORE
    a = store.upsert_user(_claims(sub="a"))["id"]
    room = _fake_room(1, "play", [a, None, None, None])
    saved_games.start(room, 0, Path("/logs"))
    saved_games.log_failed(room)
    saved_games.log_failed(room)
    assert _rows(store, "SELECT incomplete FROM games") == [{"incomplete": 1}]
