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
    srv.rooms.clear()
    return TestClient(srv.app)


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
