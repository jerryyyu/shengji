"""Continue a saved game: ``create_room`` with ``resume_from``.

The saved game is played in-process (``tests.test_saved_games_api.Table``)
so its log holds real records; the continuing table is then created over the
socket by the account that played it, and its first round must start at that
game's last levels with its next banker, the account back in its seat and
bots in the other three.
"""
from __future__ import annotations

import pytest

from tests.test_accounts import _claims, _session_cookie, accounts_on, keypair  # noqa: F401
from tests.test_saved_games_api import Table
from tests.test_server_ws import _drain, client  # noqa: F401


@pytest.fixture()
def env(accounts_on, client, keypair):
    from shengji.api import saved_games, server as srv

    saved_games.READ_LIMITER.reset()
    saved_games._segments.clear()
    saved_games._names.clear()
    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    [uid] = [u["id"] for u in [accounts_on.STORE.session_user(cookie.split("=", 1)[1])]]
    return srv, accounts_on.STORE, client, cookie, uid, private_pem


def _saved(srv, uid, seat=2, rounds=2, code="SAVE"):
    """A finished-rounds game with ``uid`` at ``seat``; returns (table, last result)."""
    from shengji.api import saved_games

    users = [None, None, None, None]
    users[seat] = uid
    t = Table(srv, code=code, users=tuple(users))
    for n in range(rounds):
        t.start_round(first=n == 0)
        t.act()
        # bot_step settles the round and logs its round_end
        assert t.room.round.phase == "round_end" and t.room.game.result is not None
    saved_games.flush()
    return t, t.room.game.result


def _continue(client, cookie, game_id):
    ws = client.websocket_connect("/ws", headers={"cookie": cookie})
    ws.__enter__()
    ws.send_json({"type": "create_room", "name": "", "resume_from": game_id})
    return ws


def test_resume_point_is_the_last_levels_banker_and_seat(env):
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    t, last = _saved(srv, uid, seat=2, rounds=3)
    point = saved_games.resume_point(uid, t.game_id)
    assert point == {"seat": 2, "levels": list(last.new_levels), "banker": last.next_banker}


def test_continue_starts_a_table_at_those_levels_banker_and_seat(env):
    srv, store, client, cookie, uid, _pem = env
    t, last = _saved(srv, uid, seat=2, rounds=2)
    ws = _continue(client, cookie, t.game_id)
    try:
        room_msg = _drain(ws, "room")
        assert room_msg["you"] == 2 and room_msg["host"] == 2
        assert [p["is_bot"] for p in room_msg["players"]] == [True, True, False, True]
        assert room_msg["players"][2]["name"] == "Jerry"
        room = srv.rooms[room_msg["room"]]
        assert room.seats[2].user_id == uid
        ws.send_json({"type": "start_game"})
        state = _drain(ws, "state", tries=60)
        assert state["you"] == 2
        assert state["levels"] == list(last.new_levels)
        assert room.game.levels == tuple(last.new_levels)
        assert room.round.banker == last.next_banker
        assert room.round.trump_rank == last.new_levels[last.next_banker % 2]
        # a new saved game, linked to the same account at the same seat
        assert room.saved_game is not None and room.saved_game.id != t.game_id
        assert room.saved_game.open == {2: uid}
    finally:
        ws.__exit__(None, None, None)


def test_a_continued_game_is_rated_for_the_signed_in_player(env):
    srv, store, client, cookie, uid, _pem = env
    t, _last = _saved(srv, uid, seat=1, rounds=1)
    ws = _continue(client, cookie, t.game_id)
    try:
        code = _drain(ws, "room")["room"]
        ws.send_json({"type": "start_game"})
        _drain(ws, "state", tries=60)
        room = srv.rooms[code]
        assert room.ratings is not None and room.ratings.present == {1: uid}
    finally:
        ws.__exit__(None, None, None)


def test_another_accounts_game_is_refused(env):
    srv, store, client, cookie, uid, private_pem = env
    other = store.upsert_user(_claims(sub="someone-else", email="else@example.com"))["id"]
    t, _last = _saved(srv, other, seat=0, rounds=1)
    rooms_before = set(srv.rooms)
    ws = _continue(client, cookie, t.game_id)
    try:
        err = _drain(ws, "error")
        assert err["code"] == "resume_unavailable"
        assert set(srv.rooms) == rooms_before
    finally:
        ws.__exit__(None, None, None)


@pytest.mark.parametrize("game_id", ["0" * 32, "not-an-id", 7, None])
def test_a_missing_or_malformed_record_is_refused(env, game_id):
    srv, store, client, cookie, uid, _pem = env
    ws = _continue(client, cookie, game_id)
    try:
        assert _drain(ws, "error")["code"] == "resume_unavailable"
        assert not srv.rooms
    finally:
        ws.__exit__(None, None, None)


def test_a_hidden_game_is_refused(env):
    srv, store, client, cookie, uid, _pem = env
    t, _last = _saved(srv, uid, seat=0, rounds=1)
    assert store.hide_game(uid, t.game_id)
    ws = _continue(client, cookie, t.game_id)
    try:
        assert _drain(ws, "error")["code"] == "resume_unavailable"
    finally:
        ws.__exit__(None, None, None)


def test_a_game_with_no_finished_round_is_refused(env):
    srv, store, client, cookie, uid, _pem = env
    t = Table(srv, code="OPEN", users=(uid, None, None, None))
    t.start_round(first=True)
    from shengji.api import saved_games
    saved_games.flush()
    assert saved_games.resume_point(uid, t.game_id) is None
    ws = _continue(client, cookie, t.game_id)
    try:
        assert _drain(ws, "error")["code"] == "resume_unavailable"
    finally:
        ws.__exit__(None, None, None)


def test_a_guest_cannot_resume(env):
    srv, store, client, cookie, uid, _pem = env
    t, _last = _saved(srv, uid, seat=0, rounds=1)
    ws = client.websocket_connect("/ws")
    ws.__enter__()
    try:
        ws.send_json({"type": "create_room", "name": "G", "resume_from": t.game_id})
        assert _drain(ws, "error")["code"] == "resume_unavailable"
    finally:
        ws.__exit__(None, None, None)


def test_a_lost_round_end_makes_continue_unavailable_not_a_rollback(env):
    """The second round's ``round_end`` never reaches the log (the link worker
    still records its levels and marks the game incomplete): Continue must not
    fall back to the first round's levels and banker."""
    from shengji.api import saved_games

    srv, store, client, cookie, uid, _pem = env
    t = Table(srv, code="DROPEND", users=(uid, None, None, None))
    t.start_round(first=True)
    t.act()
    original = t.room.log_event

    def drop_end(kind, **data):
        if kind == "round_end":
            saved_games.log_failed(t.room)
            return None
        return original(kind, **data)

    t.room.log_event = drop_end
    t.start_round()
    t.act()
    saved_games.flush()
    game = store.user_game(uid, t.game_id)
    assert game["incomplete"] and game["final_levels"] == list(t.room.game.result.new_levels)
    assert saved_games.resume_point(uid, t.game_id) is None
    ws = _continue(client, cookie, t.game_id)
    try:
        err = _drain(ws, "error")
        assert err["code"] == "resume_unavailable"
    finally:
        ws.__exit__(None, None, None)


def test_a_summary_that_disagrees_with_the_latest_logged_round_end_is_refused(env):
    """A complete log whose latest ``round_end`` differs from the stored
    summary (the summary write failed or lagged) is not trusted either."""
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    t, last = _saved(srv, uid, seat=0, rounds=2)
    assert saved_games.resume_point(uid, t.game_id) is not None
    other = ["A", "A"] if list(last.new_levels) != ["A", "A"] else ["K", "K"]
    store.record_round_end(t.game_id, 2, other, list(last.games_won))
    assert saved_games.resume_point(uid, t.game_id) is None
