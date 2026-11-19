"""Continue a saved game: ``create_room`` with ``resume_from``.

The saved game is played in-process (``tests.test_saved_games_api.Table``)
so its log holds real records; the continuing table is then created over the
socket by the account that played it, and its first round must start at that
game's last levels with its next banker, the account back in its seat and
bots in the other three.

The continuing table carries on the same saved game (one row in the game
list, its rounds numbered on), and a ranked game continues as a ranked table
rated as further rounds of the same rated segment.
"""
from __future__ import annotations

import time

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
    assert point == {"game_id": t.game_id, "first_round": 4, "seat": 2,
                     "levels": list(last.new_levels), "banker": last.next_banker,
                     "games_won": list(last.games_won), "ranked": False}


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
        state = _drain(ws, "state")
        assert state["you"] == 2
        assert state["levels"] == list(last.new_levels)
        assert room.game.levels == tuple(last.new_levels)
        assert room.round.banker == last.next_banker
        assert room.round.trump_rank == last.new_levels[last.next_banker % 2]
        # the same saved game, carried on from round 3 at the same seat
        assert room.saved_game is not None and room.saved_game.id == t.game_id
        assert room.saved_game.round_offset == 2
        assert room.saved_game.open == {2: uid}
    finally:
        ws.__exit__(None, None, None)


def test_a_continued_casual_game_refuses_ranked_and_is_never_rated(env):
    """A casual saved game continues as a casual created room: the old
    Ranked switch is refused and the game stays unrated."""
    from shengji.api import tables

    srv, store, client, cookie, uid, _pem = env
    t, _last = _saved(srv, uid, seat=1, rounds=1)
    ws = _continue(client, cookie, t.game_id)
    try:
        code = _drain(ws, "room")["room"]
        _drain(ws, "state")
        ws.send_json({"type": "set_ranked", "on": True})
        err = _drain(ws, "error")
        assert err["code"] == "retired" and err["message"] == tables.RETIRED_MESSAGE
        room = srv.rooms[code]
        assert room.ratings is None and not room.matched and not room.move_timer
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


def test_continue_with_start_keeps_levels_banker_seat_and_link(env):
    """``create_room`` with ``start: true`` starts the continued table at once:
    the same levels, banker, seat and new linked saved game as Start would."""
    srv, store, client, cookie, uid, _pem = env
    t, last = _saved(srv, uid, seat=2, rounds=2)
    ws = client.websocket_connect("/ws", headers={"cookie": cookie})
    ws.__enter__()
    try:
        ws.send_json({"type": "create_room", "name": "", "resume_from": t.game_id,
                      "start": True})
        room_msg = _drain(ws, "room")
        assert room_msg["you"] == 2 and room_msg["host"] == 2
        assert [p["is_bot"] for p in room_msg["players"]] == [True, True, False, True]
        state = _drain(ws, "state")
        assert state["you"] == 2 and state["levels"] == list(last.new_levels)
        room = srv.rooms[room_msg["room"]]
        assert [sd.name for sd in room.seats] == ["Bot 1", "Bot 2", "Jerry", "Bot 3"]
        assert room.seats[2].user_id == uid
        assert room.game.levels == tuple(last.new_levels)
        assert room.round.banker == last.next_banker
        assert room.round.trump_rank == last.new_levels[last.next_banker % 2]
        assert room.saved_game is not None and room.saved_game.id == t.game_id
        assert room.saved_game.open == {2: uid}
        assert room.ratings is None          # a continued casual game stays casual
    finally:
        ws.__exit__(None, None, None)


def test_a_refused_resume_with_start_creates_nothing(env):
    srv, store, client, cookie, uid, _pem = env
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as ws:
        ws.send_json({"type": "create_room", "name": "", "resume_from": "0" * 32,
                      "start": True})
        assert _drain(ws, "error")["code"] == "resume_unavailable"
        assert not srv.rooms


# ------------------------------------------------------------ continuations
class Ranked(Table):
    """A table played in-process with its ratings: ranked (queue-matched)
    unless ``ranked=False``, bots in the seats ``users`` leaves None, and,
    with ``resume``, started from that resume point as ``_start_game``
    starts a continued table."""

    def __init__(self, srv, code, users, resume=None, ranked=True):
        super().__init__(srv, code=code, users=users)
        room = self.room
        room.matched = room.move_timer = ranked
        room.resume = resume
        room.seats = [srv.Seat(name=f"Bot {i}", is_bot=True) if u is None
                      else srv.Seat(name=f"P{i}", user_id=u, connected=True)
                      for i, u in enumerate(users)]

    def start_round(self, first=False):
        from shengji.api import ratings
        from shengji.engine.cards import RANKS

        room = self.room
        if first and room.resume is not None:
            room.game.level_idx = [RANKS.index(level) for level in room.resume["levels"]]
            room.game.banker = room.resume["banker"]
            room.game.games_won = list(room.resume["games_won"])
        super().start_round(first=first)
        if first:
            ratings.start(room)
        else:
            ratings.round_started(room)

    def play(self, rounds):
        for n in range(rounds):
            self.start_round(first=self.room.game.round_no == 0)
            self.act()
            assert self.room.round.phase == "round_end"
        _flush()
        return self


def _flush():
    from shengji.api import ratings, saved_games

    saved_games.flush()
    ratings.flush()


def _events(store, game_id):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT * FROM rating_events WHERE substr(game_id, 1, 32) = ? ORDER BY round_no",
            (game_id,))]


def _continued(srv, uid, original, code="CONT", rounds=2, ranked=None):
    """``original`` continued in-process by ``uid`` for ``rounds`` rounds."""
    from shengji.api import saved_games

    point = saved_games.resume_point(uid, original.game_id)
    assert point is not None
    users = [None] * 4
    users[point["seat"]] = uid
    return Ranked(srv, code, tuple(users), resume=point,
                  ranked=point["ranked"] if ranked is None else ranked).play(rounds)


def _no_account_in_log(srv, code, *secrets):
    """No record of ``code``'s log carries an account id key or any of
    ``secrets`` (an email, a token)."""
    import json

    text = (srv.LOG_DIR / f"{code}.jsonl").read_text()
    assert text
    for line in text.splitlines():
        rec = json.loads(line)

        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)

        assert not {"user_id", "user_ids", "account", "account_id", "queue_id"} & set(keys(rec))
    for secret in secrets:
        assert secret not in text


def test_a_ranked_saved_game_resumes_ranked_from_its_rated_segment(env):
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    original = Ranked(srv, "RANK", (uid, None, None, None)).play(2)
    point = saved_games.resume_point(uid, original.game_id)
    deltas = [e["delta"] for e in _events(store, original.game_id)]
    assert len(deltas) == 2
    assert point["ranked"] is True and point["first_round"] == 3 and point["game_no"] == 0
    assert point["game_delta"] == pytest.approx(sum(deltas))
    casual, _last = _saved(srv, uid, seat=0, rounds=1, code="CASU")
    assert saved_games.resume_point(uid, casual.game_id)["ranked"] is False


def test_a_ranked_continuation_rates_its_rounds_as_rounds_of_the_one_saved_game(env):
    """Rated as game rounds 3 and 4 of the same rated segment, with the
    round-end rating line, and listed as one game: every round, the final
    levels and the whole rating change. A leaver cap the account carried
    into Continue caps the continuation's first rated round."""
    from shengji.api import ratings, saved_games

    srv, store, _client, _cookie, uid, _pem = env
    original = Ranked(srv, "RANK", (uid, None, None, None)).play(2)
    ratings.CARRIED_CAPS.clear()
    ratings.carry_leaver_cap(uid)
    try:
        cont = _continued(srv, uid, original, code="CONT", rounds=2)
    finally:
        capped_left = set(ratings.CARRIED_CAPS)
        ratings.CARRIED_CAPS.clear()
    assert capped_left == set()
    room = cont.room
    assert room.saved_game.id == original.game_id and room.ratings.round_offset == 2
    events = _events(store, original.game_id)
    assert [(e["game_id"], e["round_no"]) for e in events] == [
        (f"{original.game_id}/0", n) for n in (1, 2, 3, 4)]
    assert events[2]["actual"] <= ratings.LEAVER_SCORE_CAP and events[2]["abandoned"] == 0
    line = ratings.round_payload(room, 0)["rating"]
    assert line["delta"] == round(events[3]["delta"])
    assert line["rating"] == round(events[3]["rating_after"])

    listed = saved_games._list(uid, None, 50)["games"]
    assert [g["id"] for g in listed] == [original.game_id]
    [game] = listed
    assert game["rounds"] == [1, 2, 3, 4]
    assert game["final_levels"] == list(room.game.result.new_levels)
    assert game["rating_change"] == round(sum(e["delta"] for e in events))
    assert game["rated_rounds"] == 4
    detail = saved_games._detail(uid, original.game_id)
    assert [r["round"] for r in detail["round_results"]] == [1, 2, 3, 4]
    assert [r["rating_delta"] for r in detail["round_results"]] == [
        round(e["delta"]) for e in events]
    assert not detail["incomplete"]
    _no_account_in_log(srv, "CONT", "jerry@example.com")
    _no_account_in_log(srv, "RANK", "jerry@example.com")


def test_replay_crosses_the_boundary_between_tables(env):
    """Round 2 replays from the first table's log and round 3 from the
    continuation's, each numbered as a round of the saved game."""
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    original, _last = _saved(srv, uid, seat=1, rounds=2, code="FIRST")
    cont = _continued(srv, uid, original, code="SECOND", rounds=1)
    before = saved_games._round(uid, original.game_id, 2)
    after = saved_games._round(uid, original.game_id, 3)
    assert before["finished"] and after["finished"]
    assert {e["room"] for e in before["events"]} == {"FIRST"}
    assert {e["room"] for e in after["events"]} == {"SECOND"}
    assert {e["round"] for e in before["events"]} == {2}
    assert {e["round"] for e in after["events"]} == {3}
    start = next(e for e in after["events"] if e["e"] == "round_start")
    assert start["levels"] == list(original.room.game.result.new_levels)
    assert after["seat"] == 1
    assert saved_games._round(uid, original.game_id, 4) is None
    # a casual continuation is one game too, and unrated
    assert cont.room.ratings is None
    [game] = saved_games._list(uid, None, 50)["games"]
    assert game["rounds"] == [1, 2, 3] and "rating_change" not in game
    # and a continuation continues again, from round 4
    point = saved_games.resume_point(uid, original.game_id)
    assert point["first_round"] == 4
    assert point["levels"] == list(cont.room.game.result.new_levels)


def test_a_partner_left_behind_reads_only_the_rounds_they_played(env):
    """Continuing closes every link still open in the game: the partner who
    is not at the new table cannot read its rounds."""
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    partner = store.upsert_user(_claims(sub="partner", email="p@example.com"))["id"]
    original = Ranked(srv, "PAIR", (uid, None, partner, None)).play(2)
    _continued(srv, uid, original, code="ALONE", rounds=1)
    [mine] = saved_games._list(uid, None, 50)["games"]
    [theirs] = saved_games._list(partner, None, 50)["games"]
    assert mine["rounds"] == [1, 2, 3] and theirs["rounds"] == [1, 2]
    assert saved_games._round(partner, original.game_id, 3) is None
    assert saved_games._round(partner, original.game_id, 2) is not None
    assert [e["round_no"] for e in _events(store, original.game_id) if e["user_id"] == partner] == [1, 2]


def test_a_continuation_rolled_back_leaves_the_saved_game_as_it_was(env):
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    original, _last = _saved(srv, uid, seat=0, rounds=2, code="KEEP")
    cont = _continued(srv, uid, original, code="UNDO", rounds=1)
    saved_games.abort(cont.room)
    saved_games.flush()
    game = store.user_game(uid, original.game_id)
    assert game is not None and game["segments"] == []
    assert saved_games._round(uid, original.game_id, 2) is not None
    assert saved_games._round(uid, original.game_id, 3) is None


def test_continue_over_the_socket_is_ranked_and_rates_the_round(env, monkeypatch):
    """The real create path: a ranked table (matched, the move timer, queue
    ids, the leaver rules) on the same saved game; leaving its first round
    rates it as game round 3, abandoned, as at any ranked table."""
    import json

    from shengji.ai.heuristic import HeuristicBot

    srv, store, client, cookie, uid, _pem = env
    monkeypatch.setattr(HeuristicBot, "decide_declare", lambda *a, **kw: None)
    monkeypatch.setattr(srv, "ROOM_TTL", 120.0)
    original = Ranked(srv, "RANK", (None, uid, None, None)).play(2)
    srv.MATCHMAKER.reset()
    try:
        ws = _continue(client, cookie, original.game_id)
        try:
            room_msg = _drain(ws, "room")
            assert room_msg["matched"] is True and room_msg["you"] == 1
            room = srv.rooms[room_msg["room"]]
            _drain(ws, "state")
            assert room.matched and room.move_timer and room.queued
            assert room.seats[1].queue_id == uid and room.seats[1].user_id == uid
            assert [sd.is_bot for sd in room.seats] == [True, False, True, True]
            assert room.saved_game.id == original.game_id
            assert room.ratings is not None and room.ratings.round_offset == 2
            code = room.code
            ws.send_json({"type": "table_leave"})
            _drain(ws, "left")
            deadline = time.monotonic() + 60
            while code in srv.rooms:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        finally:
            ws.__exit__(None, None, None)
    finally:
        srv.MATCHMAKER.reset()
    _flush()
    third = [e for e in _events(store, original.game_id) if e["round_no"] == 3]
    assert [(e["game_id"], e["user_id"], e["abandoned"]) for e in third] == [
        (f"{original.game_id}/0", uid, 1)]
    [start] = [json.loads(line) for line in (srv.LOG_DIR / f"{code}.jsonl").read_text().splitlines()
               if json.loads(line)["e"] == "round_start"]
    assert start["ranked"] is True and start["round"] == 1
    _no_account_in_log(srv, code, "jerry@example.com", room.seats[1].token)
    [game] = saved_games_list(uid)
    assert game["rounds"] == [1, 2, 3]


def saved_games_list(uid):
    from shengji.api import saved_games

    return saved_games._list(uid, None, 50)["games"]


def test_another_account_cannot_continue_a_ranked_game(env):
    srv, store, client, cookie, uid, _pem = env
    other = store.upsert_user(_claims(sub="owner2", email="o2@example.com"))["id"]
    original = Ranked(srv, "THEIRS", (other, None, None, None)).play(1)
    ws = _continue(client, cookie, original.game_id)
    try:
        assert _drain(ws, "error")["code"] == "resume_unavailable"
        assert not srv.rooms
    finally:
        ws.__exit__(None, None, None)


def test_a_game_still_being_played_cannot_be_continued(env):
    """Neither while its own table is still open nor while a continuation of
    it plays: one saved game is played at one table at a time."""
    srv, store, client, cookie, uid, _pem = env
    original = Ranked(srv, "LIVE", (uid, None, None, None)).play(1)
    srv.rooms["LIVE"] = original.room
    try:
        ws = _continue(client, cookie, original.game_id)
        try:
            err = _drain(ws, "error")
            assert err["code"] == "resume_unavailable"
            assert err["message"] == srv.RESUME_UNAVAILABLE_MESSAGE
        finally:
            ws.__exit__(None, None, None)
    finally:
        del srv.rooms["LIVE"]
    srv.MATCHMAKER.reset()
    try:
        first = _continue(client, cookie, original.game_id)
        try:
            code = _drain(first, "room")["room"]
            second = _continue(client, cookie, original.game_id)
            try:
                assert _drain(second, "error")["code"] == "resume_unavailable"
                assert set(srv.rooms) == {code}
            finally:
                second.__exit__(None, None, None)
        finally:
            first.__exit__(None, None, None)
    finally:
        srv.MATCHMAKER.reset()


def test_a_ranked_continuation_keeps_the_queue_rules(env):
    """Not while the account plays another ranked game, nor during its
    queue cooldown; a casual saved game is not held to either."""
    srv, store, client, cookie, uid, _pem = env
    original = Ranked(srv, "RULES", (uid, None, None, None)).play(1)
    casual, _last = _saved(srv, uid, seat=0, rounds=1, code="FREE")
    srv.MATCHMAKER.reset()
    try:
        srv.MATCHMAKER.cooldowns[uid] = srv.MATCHMAKER.clock() + 60
        ws = _continue(client, cookie, original.game_id)
        try:
            err = _drain(ws, "error")
            assert err["code"] == "cooldown" and err["cooldown_until"] > srv.MATCHMAKER.clock()
            assert not srv.rooms
        finally:
            ws.__exit__(None, None, None)
        srv.MATCHMAKER.cooldowns.clear()
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
            a.send_json({"type": "queue_join"})
            _drain(a, "queue_state")
            a.send_json({"type": "table_start_bots"})
            playing = _drain(a, "match_started")["room"]
            ws = _continue(client, cookie, original.game_id)
            try:
                err = _drain(ws, "error")
                assert err["code"] == "resume_unavailable"
                assert err["message"] == srv.ACCOUNT_PLAYING_MESSAGE
                assert set(srv.rooms) == {playing}
            finally:
                ws.__exit__(None, None, None)
            ws = _continue(client, cookie, casual.game_id)
            try:
                code = _drain(ws, "room")["room"]
                assert not srv.rooms[code].matched
            finally:
                ws.__exit__(None, None, None)
    finally:
        srv.MATCHMAKER.reset()


def test_a_continuation_replaces_one_interrupted_at_the_same_boundary(env):
    """A continuation that started its first round and never finished it
    (its server restarted) is replaced by the next Continue at the same
    boundary: the replacement's log is the one bound, so its finished round
    replays and the next Continue resumes after it."""
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    original, _ = _saved(srv, uid, seat=0, rounds=2, code="ORIG")
    point = saved_games.resume_point(uid, original.game_id)
    interrupted = Ranked(srv, "STOP", (uid, None, None, None), resume=point, ranked=False)
    interrupted.start_round(first=True)
    _flush()
    replacement = _continued(srv, uid, original, code="NEXT", rounds=1)
    game = store.user_game(uid, original.game_id)
    assert [s["log_file"] for s in game["segments"]] == ["NEXT.jsonl"]
    detail = saved_games._detail(uid, original.game_id)
    assert [r["round"] for r in detail["round_results"]] == [1, 2, 3]
    assert {e["room"] for e in saved_games._round(uid, original.game_id, 3)["events"]} == {"NEXT"}
    again = saved_games.resume_point(uid, original.game_id)
    assert again["first_round"] == 4
    assert again["levels"] == list(replacement.room.game.result.new_levels)


def test_a_replaced_continuation_gives_no_other_table_its_rounds(env):
    """Ranked, with other accounts: a partner who left the first table during
    its unfinished third round and an account seated only at the interrupted
    continuation read none of the replacement's rounds; every finished round
    and its rating events stay as they were."""
    from shengji.api import saved_games

    srv, store, _client, _cookie, uid, _pem = env
    partner = store.upsert_user(_claims(sub="partner", email="p@example.com"))["id"]
    other = store.upsert_user(_claims(sub="other", email="o@example.com"))["id"]
    original = Ranked(srv, "ORIG", (uid, None, partner, None)).play(2)
    gid = original.game_id
    original.start_round()                     # round 3 starts, and the table goes
    _flush()
    store.close_link(gid, partner, 2, 3)       # the partner left during round 3
    before = [(e["game_id"], e["round_no"], e["user_id"], e["delta"]) for e in _events(store, gid)]
    point = saved_games.resume_point(uid, gid)
    assert point["first_round"] == 3 and point["ranked"] is True
    interrupted = Ranked(srv, "STOP", (uid, None, other, None), resume=point)
    interrupted.start_round(first=True)
    _flush()
    assert saved_games._round(other, gid, 3) is not None   # its own round, while bound
    replacement = _continued(srv, uid, original, code="NEXT", rounds=1)
    assert replacement.room.ratings.banker_declared is False   # a resumed banker is preset
    assert [s["log_file"] for s in store.user_game(uid, gid)["segments"]] == ["NEXT.jsonl"]
    assert [r["round"] for r in saved_games._detail(uid, gid)["round_results"]] == [1, 2, 3]
    assert saved_games._round(partner, gid, 3) is None
    assert [g["rounds"] for g in saved_games._list(partner, None, 50)["games"]] == [[1, 2]]
    assert saved_games._round(other, gid, 3) is None
    assert store.user_game(other, gid) is None
    after = [(e["game_id"], e["round_no"], e["user_id"], e["delta"]) for e in _events(store, gid)]
    assert after[:len(before)] == before
    assert [(e["round_no"], e["user_id"]) for e in _events(store, gid)[len(before):]] == [(3, uid)]
    # a rated boundary is the game's: another table cannot take it over
    header = {**replacement.room.saved_game.header(), "room_code": "LATE",
              "log_file": "LATE.jsonl", "log_offset": 0}
    assert store.link_seat(header, uid, 0, 3) is False
    assert [s["log_file"] for s in store.user_game(uid, gid)["segments"]] == ["NEXT.jsonl"]
    # another seat of the same table links without disturbing anyone
    assert store.link_seat(replacement.room.saved_game.header(), other, 2, 3) is True
    assert saved_games._round(uid, gid, 3) is not None
    assert [s["log_file"] for s in store.user_game(uid, gid)["segments"]] == ["NEXT.jsonl"]
