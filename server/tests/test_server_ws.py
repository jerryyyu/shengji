"""Websocket-level tests for the multiplayer room protocol.

These drive the REAL socket via TestClient rather than calling handlers
directly: `peek_room` shipped completely unimplemented on the server while
the client sent it and the suite stayed green, because nothing here spoke
the wire protocol (2026-08-03).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SHENGJI_BOT", "heuristic")  # fast; these tests are protocol-level


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_LOG_DIR", str(tmp_path / "logs"))
    from shengji.api import server as srv

    srv.LOG_DIR = tmp_path / "logs"
    # A real deal is ~22s of DEAL_DELAY; these tests care about the protocol,
    # not the pacing. BOT_DELAY is left alone — one test needs a bot turn to
    # still be PENDING when a human claims that seat.
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.0)
    monkeypatch.setattr(srv, "DECLARE_GRACE", 0.05)
    monkeypatch.setattr(srv, "DECLARE_EXTEND", 0.05)
    srv.rooms.clear()
    with TestClient(srv.app) as c:
        yield c
    # Rooms outlive a test's event loop; their asyncio.Lock binds to whichever
    # loop touches it first, so a leftover room makes the NEXT test fail with
    # "attached to a different loop". Tear down explicitly.
    for room in list(srv.rooms.values()):
        for task in (room.cleanup_task, room.deal_task,
                     getattr(room, "watchdog_task", None)):
            if task is not None:
                task.cancel()
    srv.rooms.clear()


def _drain(ws, want, tries=40):
    """Next message of type `want` (states/chat interleave freely)."""
    for _ in range(tries):
        m = ws.receive_json()
        if m.get("type") == want:
            return m
    raise AssertionError(f"no {want!r} message arrived")


def _room_with_bots(ws, name="jerry"):
    # Lobby broadcasts are "room"; only an in-game room sends "state".
    ws.send_json({"type": "create_room", "name": name})
    code = _drain(ws, "room")["room"]
    for _ in range(3):
        ws.send_json({"type": "add_bot"})
    return code


def test_peek_room_reports_seats_without_joining(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            m = _drain(b, "room_seats")

    assert m["room"] == code
    assert len(m["seats"]) == 4
    assert [s["team"] for s in m["seats"]] == [0, 1, 0, 1]
    assert m["seats"][0]["name"] == "jerry" and not m["seats"][0]["is_bot"]
    assert all(s["is_bot"] for s in m["seats"][1:])
    # Peeking must NOT seat the peeker.
    from shengji.api import server as srv
    assert len(srv.rooms[code].seats) == 4


def test_peek_unknown_room_errors(client):
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "peek_room", "room": "ZZZZ"})
        m = _drain(a, "error")
    assert m["code"] == "room_not_found"


def test_peek_then_join_chosen_seat(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            b.send_json({"type": "join_room", "room": code,
                         "name": "james", "seat": want})
            st = _drain(b, "room")
            assert st["you"] == want
            mine = next(p for p in st["players"] if p["seat"] == want)
            assert mine["name"] == "james" and not mine["is_bot"]


def test_ready_ignores_disconnected_humans(client):
    """A player who drops at round end must stop being waited on."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code, "name": "james"})
            _drain(b, "room")
            room = srv.rooms[code]
            humans = [i for i, s in enumerate(room.seats) if not s.is_bot]
            assert len(humans) == 2
            room.ready.add(humans[0])
            assert srv.pending_ready(room) == {humans[1]}
        # b's socket is closed here; the drop must clear it from the tally.
        room = srv.rooms[code]
        assert srv.pending_ready(room) == set()
        assert humans[1] not in room.ready


def test_state_carries_ready_tally(client):
    """In-game broadcasts must include `ready` — the client renders it."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "start_game"})
        st = _drain(a, "state", tries=60)
        assert "ready" in st, "round-end tally missing from in-game state"
        srv.rooms[code].ready.add(0)
        assert "ready" in srv.state_for(srv.rooms[code], 0)
        assert srv.state_for(srv.rooms[code], 0)["ready"] == [0]


def test_seat_claim_chat_names_the_bot(client):
    """"took Bot 1's seat" — which seat, not just "a bot's seat"."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "peek_room", "room": code})
            seats = _drain(b, "room_seats")["seats"]
            want = [s["seat"] for s in seats if s["is_bot"]][-1]
            botname = next(s["name"] for s in seats if s["seat"] == want)
            b.send_json({"type": "join_room", "room": code,
                         "name": "jerry mbp", "seat": want})
            line = _drain(b, "chat")
    assert line["text"] == f"jerry mbp took {botname}'s seat"
    assert line["seat"] == -1


def test_two_clients_race_for_same_bot_seat(client):
    """The loser of a seat race must be refused, never silently reseated."""
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b, \
                client.websocket_connect("/ws") as c:
            b.send_json({"type": "peek_room", "room": code})
            want = [s["seat"] for s in _drain(b, "room_seats")["seats"]
                    if s["is_bot"]][0]
            b.send_json({"type": "join_room", "room": code,
                         "name": "first", "seat": want})
            assert _drain(b, "room")["you"] == want
            c.send_json({"type": "join_room", "room": code,
                         "name": "second", "seat": want})
            err = _drain(c, "error")
    assert err["code"] == "seat_unavailable"
    from shengji.api import server as srv
    assert srv.rooms[code].seats[want].name == "first"
    assert not any(sd.name == "second" for sd in srv.rooms[code].seats)


def test_malformed_seat_falls_back_to_any_bot(client):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "odd", "seat": True})   # bool is not a seat
            st = _drain(b, "room")
    assert st["you"] in (1, 2, 3)


def _start_game(client, a, to_play=False):
    """Room with 3 bots, game running, returns (code, room).

    With to_play=True this drives the REAL deal path (the fixture zeroes
    DEAL_DELAY and shortens the declare window) rather than advancing the
    round in-process — an in-process loop races the server's own deal task
    and both end up calling deal_next on the same round.
    """
    from shengji.api import server as srv

    code = _room_with_bots(a)
    a.send_json({"type": "start_game"})
    st = _drain(a, "state", tries=60)
    if to_play:
        for _ in range(400):
            if st.get("phase") == "play":
                break
            st = _drain(a, "state", tries=400)
        assert st.get("phase") == "play", "round never reached the play phase"
    return code, srv.rooms[code]


def test_claim_preserves_private_hand_and_ids(client):
    """The claimant gets that seat's REAL remaining cards; others see counts."""
    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        want = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        before = sorted(room.round.hands[want])
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "late", "seat": want})
            st = _drain(b, "state", tries=60)
            assert st["you"] == want
            got = sorted(c["code"] for c in st["hand"])
            assert got == before, "claimant did not receive the seat's hand"
            assert len({c["id"] for c in st["hand"]}) == len(st["hand"]), \
                "duplicate card ids handed to the claimant"
            # Everyone else still sees only public counts for that seat.
            other = next(p for p in st["players"] if p["seat"] != want)
            assert "hand" not in other and "cards_left" in other
        # And the seat's hand was not mutated by the claim itself.
        assert sorted(room.round.hands[want]) == before


def test_claim_during_bot_delay_is_atomic(client):
    """Claiming the seat whose bot turn is pending must cancel that bot move."""
    import asyncio

    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a, to_play=True)
        turn = room.round.turn
        assert turn is not None and room.round.phase == "play"
        if not room.seats[turn].is_bot:      # seat 0 (human) leads
            turn = next(i for i, sd in enumerate(room.seats) if sd.is_bot)
        hand_before = list(room.round.hands[turn])
        with client.websocket_connect("/ws") as b:
            b.send_json({"type": "join_room", "room": code,
                         "name": "sniper", "seat": turn})
            _drain(b, "state", tries=60)
            # pump_bots re-checks is_bot after sleeping; the seat is human now.
            assert not room.seats[turn].is_bot
            assert room.round.turn == turn, "bot moved for a claimed seat"
            assert list(room.round.hands[turn]) == hand_before
    del asyncio, srv


def test_disconnect_takeover_and_reconnect_resets_each_absence(client):
    """bot_announced must reset per absence, not latch after the first."""
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, room = _start_game(client, a)
        seat0 = room.seats[0]
        for absence in (1, 2):
            seat0.connected = False
            seat0.bot_announced = True          # as the watchdog would set it
            with client.websocket_connect("/ws") as b:
                b.send_json({"type": "join_room", "room": code, "name": "jerry"})
                _drain(b, "state", tries=60)
                me = srv.rooms[code].seats[0]
                assert me is seat0, "reconnect must reuse the SAME Seat object"
                assert not me.is_bot and me.connected
                assert not me.bot_announced, \
                    f"bot_announced still set after absence {absence}"
                assert me.name == "jerry"
        # Reclaiming must not have spawned extra seats.
        assert len(srv.rooms[code].seats) == 4


def test_reconnect_cancels_room_cleanup(client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        code, _ = _start_game(client, a)
    room = srv.rooms.get(code)
    assert room is not None, "room deleted immediately instead of after TTL"
    assert room.cleanup_task is not None
    with client.websocket_connect("/ws") as b:
        b.send_json({"type": "join_room", "room": code, "name": "jerry"})
        _drain(b, "state", tries=60)
        assert room.cleanup_task is None or room.cleanup_task.cancelled()


def test_claim_state_does_not_leak_across_rooms_on_one_socket(client):
    """Claiming a bot seat in room A must not label a later join of room B."""
    with client.websocket_connect("/ws") as a, \
            client.websocket_connect("/ws") as host_b:
        code_a, room_a = _start_game(client, a)
        # Room B has SPACE (one bot, two free seats), so a join there is an
        # ordinary lobby join — any "took ...'s seat" line is leaked state.
        host_b.send_json({"type": "create_room", "name": "hostb"})
        code_b = _drain(host_b, "room")["room"]
        host_b.send_json({"type": "add_bot"})
        with client.websocket_connect("/ws") as mover:
            want = next(i for i, sd in enumerate(room_a.seats) if sd.is_bot)
            mover.send_json({"type": "join_room", "room": code_a,
                             "name": "wanderer", "seat": want})
            first = _drain(mover, "chat")
            assert "took" in first["text"]
            mover.send_json({"type": "leave_room"})
            mover.send_json({"type": "join_room", "room": code_b,
                             "name": "wanderer"})
            lines = []
            for _ in range(30):
                m = mover.receive_json()
                if m.get("type") == "chat":
                    lines.append(m["text"])
                if m.get("type") in ("room", "state") and lines:
                    break
    joined = [t for t in lines if "wanderer" in t]
    assert joined and all("took" not in t for t in joined), \
        f"stale claim state leaked into the next room: {joined}"
