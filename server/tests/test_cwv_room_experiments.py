"""Real socket witnesses for opt-in W32; never changes ordinary rooms."""
import json

import pytest

from shengji.api import server as srv
from shengji.api.room_experiments import ShortlistTestRooms
from shengji.ai.registry import REGISTRY
from shengji.train.cwv_shortlist import CWVShortlistBot
from tests.test_cwv_numpy import _actual_export
from tests.test_server_ws import client, _drain

KEY = "local-test-only-key-with-32-characters"


@pytest.mark.parametrize("message", [
    {"test_policy": "w32", "test_access_key": KEY},
    {"test_policy": "mc-strong", "test_access_key": KEY},
])
def test_disabled_refuses_at_socket_without_creating_room(client, monkeypatch, message):
    monkeypatch.setattr(srv, "SHORTLIST_TEST_ROOMS", ShortlistTestRooms({}))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "name": "test", **message})
        assert _drain(ws, "error")["code"] == "test_room_unavailable"
        assert not srv.rooms
        # Refusal must not strand the socket or silently create a fallback room.
        ws.send_json({"type": "create_room", "name": "ordinary"})
        reply = _drain(ws, "room")
        assert "experimental_policy" not in reply


def _enable(monkeypatch, tmp_path):
    package, _ = _actual_export(tmp_path)
    config = ShortlistTestRooms({"SHENGJI_W32_TEST_ROOMS": "1",
                                "SHENGJI_W32_TEST_ACCESS_KEY": KEY,
                                "SHENGJI_W32_TEST_CKPT": str(package)})
    monkeypatch.setattr(srv, "SHORTLIST_TEST_ROOMS", config)
    return config


def test_real_creation_gate_shares_weights_not_rooms_and_excludes_logs(client, monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setenv("SHENGJI_BOT", "mc-s0-report-lcb")
    with client.websocket_connect("/ws") as normal, \
            client.websocket_connect("/ws") as first, \
            client.websocket_connect("/ws") as second, \
            client.websocket_connect("/ws") as excess:
        normal.send_json({"type": "create_room", "name": "normal"})
        ordinary_msg = _drain(normal, "room")
        ordinary = srv.rooms[ordinary_msg["room"]]
        assert not isinstance(ordinary.bot, CWVShortlistBot)
        assert type(ordinary.bot) is REGISTRY["mc-s0-report-lcb"]
        assert ordinary.experimental_policy is None
        assert ordinary.log_dir == srv.LOG_DIR
        assert "experimental_policy" not in ordinary_msg
        made = []
        for ws in (first, second):
            ws.send_json({"type": "create_room", "name": "test",
                          "test_policy": "w32", "test_access_key": KEY})
            result = _drain(ws, "room")
            assert result["experimental_policy"] == "w32"
            made.append(srv.rooms[result["room"]])
        a, b = made
        assert type(a.bot) is type(b.bot) is CWVShortlistBot
        assert a.bot is not b.bot and a.bot.rng is not b.bot.rng
        assert a.bot.evaluator.model._weights is b.bot.evaluator.model._weights
        assert a.bot.shortlist_config.worlds == 32 and a.bot.REPORT_FOLD_WORLDS == 300
        assert not a.log_dir.is_relative_to(srv.LOG_DIR)
        a.log_event("witness")
        logs = (a.log_dir / f"{a.code}.jsonl").read_text()
        assert KEY not in logs
        assert all(row["training_excluded"] and row["experimental_policy"] == "w32"
                   for row in map(json.loads, logs.splitlines()))
        excess.send_json({"type": "create_room", "test_policy": "w32",
                          "test_access_key": KEY})
        assert "limit" in _drain(excess, "error")["message"]
        assert len(srv.rooms) == 3
        # Joining a room with experimental fields cannot change its policy.
        excess.send_json({"type": "join_room", "room": ordinary.code,
                          "name": "guest", "test_policy": "w32", "test_access_key": KEY})
        assert "experimental_policy" not in _drain(excess, "room")
        assert ordinary.experimental_policy is None
        # The real in-game payload keeps the test marker, without starting search.
        monkeypatch.setattr(srv, "DEAL_DELAY", 60)
        for _ in range(3):
            first.send_json({"type": "add_bot"})
            _drain(first, "room")
        first.send_json({"type": "start_game"})
        assert _drain(first, "state")["experimental_policy"] == "w32"


@pytest.mark.parametrize("key", ["wrong", "", None, 7, "x" * 129])
def test_bad_key_refuses_before_model_load(client, monkeypatch, key):
    monkeypatch.setattr(srv, "SHORTLIST_TEST_ROOMS", ShortlistTestRooms({
        "SHENGJI_W32_TEST_ROOMS": "1", "SHENGJI_W32_TEST_ACCESS_KEY": KEY,
        "SHENGJI_W32_TEST_CKPT": "/missing/private-model.npz"}))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "test_policy": "w32", "test_access_key": key})
        error = _drain(ws, "error")
        assert error["code"] == "test_room_unavailable"
        assert "model" not in error["message"] and "private" not in repr(error)
        assert not srv.rooms


def test_missing_model_refuses_without_fallback_or_private_error(client, monkeypatch):
    monkeypatch.setattr(srv, "SHORTLIST_TEST_ROOMS", ShortlistTestRooms({
        "SHENGJI_W32_TEST_ROOMS": "1", "SHENGJI_W32_TEST_ACCESS_KEY": KEY,
        "SHENGJI_W32_TEST_CKPT": "/missing/private-model.npz"}))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "test_policy": "w32", "test_access_key": KEY})
        assert _drain(ws, "error")["message"] == "Shortlist test model unavailable."
        assert not srv.rooms


@pytest.mark.parametrize("suffix", ["", "nested"])
def test_experimental_room_cannot_write_into_ordinary_logs(tmp_path, monkeypatch, suffix):
    monkeypatch.setattr(srv, "LOG_DIR", tmp_path)
    with pytest.raises(ValueError, match="^test rooms require a disjoint log root$"):
        srv.Room(code="TEST", experimental_policy="w32", log_dir=tmp_path / suffix)


@pytest.mark.parametrize("env", [{"SHENGJI_W32_TEST_ROOMS": "yes"},
                                 {"SHENGJI_W32_TEST_ROOMS": "1"},
                                 {"SHENGJI_W32_TEST_ROOMS": "1", "SHENGJI_W32_TEST_ACCESS_KEY": KEY}])
def test_misconfiguration_fails(env):
    with pytest.raises(ValueError):
        ShortlistTestRooms(env)
