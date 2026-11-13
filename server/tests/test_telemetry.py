"""UI telemetry: the allow-list, the caps, and a sink apart from the game logs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shengji.api import telemetry
from tests.test_server_ws import _drain, _room_with_bots, client  # noqa: F401


@pytest.fixture()
def sink(tmp_path, monkeypatch):
    out = tmp_path / "telemetry"
    monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(out))
    return out


def _records(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(directory.glob("ui-*.jsonl")):
        rows.extend(json.loads(line) for line in f.read_text().splitlines())
    return rows


class _Sock:
    """A stand-in socket object: telemetry keeps its state on it."""


# allow-list

def test_unknown_fields_and_free_text_are_dropped():
    ev = telemetry.clean_event({"e": "tap", "t": 1200, "id": "play", "name": "Jerry",
                                "room": "ABCD", "card": "S5", "text": "hello"})
    assert ev == {"e": "tap", "t": 1200, "id": "play"}


@pytest.mark.parametrize("raw", [
    {"e": "tap", "id": "Jerry"},                          # not a known tap id
    {"e": "notice", "code": "You must follow suit."},     # server message text
    {"e": "notice", "code": "S5"},                        # a card code
    {"e": "screen", "name": "room ABCD"},
    {"e": "chat", "text": "hi"},                          # unknown event
    {"e": "ui_tap", "id": "play"},
    {"id": "play"},
    "tap",
])
def test_events_outside_the_allow_list_are_dropped(raw):
    assert telemetry.clean_event(raw) is None


def test_bounded_ints_refuse_bools_and_out_of_range():
    ev = telemetry.clean_event({"e": "turn_done", "phase": "play", "need": True,
                                "nth_turn": 31, "ms_total": -1, "sel_changes": 3,
                                "coach": 1, "by": "you", "lead": "pair"})
    assert ev == {"e": "turn_done", "phase": "play", "sel_changes": 3, "by": "you",
                  "lead": "pair"}


def test_message_stamps_only_known_forms():
    events, stamps = telemetry.clean_message(
        {"type": "client_event", "v": 1, "form": "phone-land", "first_visit": True,
         "events": [{"e": "tap", "id": "next_round"}]})
    assert events == [{"e": "tap", "id": "next_round"}]
    assert stamps == {"form": "phone-land", "first_visit": True}
    _, stamps = telemetry.clean_message({"v": 1, "form": "Jerry's iPhone", "events": []})
    assert stamps == {}


# caps

def test_at_most_50_events_per_message():
    msg = {"v": 1, "events": [{"e": "tap", "id": "play"}] * 60}
    events, _ = telemetry.clean_message(msg, raw_bytes=100)
    assert len(events) == telemetry.MAX_EVENTS_PER_MESSAGE == 50


def test_a_message_over_2kb_is_dropped_whole():
    msg = {"v": 1, "events": [{"e": "tap", "id": "play", "pad": "x" * 2100}]}
    assert telemetry.clean_message(msg) == ([], {})
    assert telemetry.clean_message({"v": 1, "events": [{"e": "tap", "id": "play"}]})[0]


def test_wrong_version_is_dropped():
    assert telemetry.clean_message({"v": 2, "events": [{"e": "tap", "id": "play"}]}) == ([], {})


def test_600_events_per_socket_per_hour(sink):
    sock = _Sock()
    msg = {"v": 1, "events": [{"e": "tap", "id": "play"}] * 20}
    written = sum(telemetry.receive(sock, msg, signed_in=False) for _ in range(40))
    assert written == telemetry.MAX_EVENTS_PER_HOUR == 600
    assert len(_records(sink)) == 600
    st = telemetry.state_for(sock)
    assert st.take(5, now=st.window_start + telemetry.HOUR) == 5   # a new hour


# sink

def test_sink_is_off_without_its_env_var(monkeypatch):
    monkeypatch.delenv("SHENGJI_TELEMETRY_DIR", raising=False)
    assert telemetry.telemetry_dir() is None
    assert telemetry.write([{"e": "tap", "id": "play"}]) is False


def test_sink_refuses_the_game_log_tree(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setenv("SHENGJI_LOG_DIR", str(logs))
    for inside in (logs, logs / "telemetry", Path("/data/logs"), Path("/data/logs/ui")):
        monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(inside))
        assert telemetry.telemetry_dir() is None, inside
    monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    assert telemetry.telemetry_dir() == (tmp_path / "telemetry").resolve()


def test_records_are_date_named_and_carry_no_identity(sink):
    sock = _Sock()
    n = telemetry.receive(sock, {"v": 1, "form": "wide", "first_visit": False,
                                 "events": [{"e": "screen", "t": 5, "name": "table",
                                             "prev": "room", "ms_on_prev": 900}]},
                          signed_in=True)
    assert n == 1
    (f,) = sink.glob("ui-*.jsonl")
    assert len(f.name) == len("ui-YYYYMMDD.jsonl")
    (rec,) = _records(sink)
    assert set(rec) == {"e", "t", "name", "prev", "ms_on_prev", "form", "first_visit",
                        "sid", "who", "build", "ts"}
    assert rec["who"] == "account" and len(rec["sid"]) == 16


def test_queue_events_share_the_socket_sid(sink):
    sock = _Sock()
    telemetry.receive(sock, {"v": 1, "events": [{"e": "tap", "id": "play"}]}, signed_in=False)
    assert telemetry.queue_event(sock, "join", who="guest", size=1, wait=0.0, queued=3,
                                 name="Jerry")
    assert not telemetry.queue_event(sock, "chat")
    tap, q = _records(sink)
    assert q["sid"] == tap["sid"]
    assert q == {"e": "queue", "q": "join", "who": "guest", "size": 1, "wait": 0.0,
                 "queued": 3, "sid": tap["sid"], "build": q["build"], "ts": q["ts"]}


# over the socket

def test_client_events_reach_the_sink_and_never_a_room_log(client, sink, tmp_path,
                                                           monkeypatch):
    from shengji.api import server as srv

    kinds: list[str] = []
    real = srv.Room.log_event

    def spy(self, kind, **data):
        kinds.append(kind)
        return real(self, kind, **data)

    monkeypatch.setattr(srv.Room, "log_event", spy)
    with client.websocket_connect("/ws") as ws:
        _room_with_bots(ws)
        ws.send_json({"type": "start_game"})
        _drain(ws, "state")
        ws.send_json({"type": "client_event", "v": 1, "form": "phone",
                      "events": [{"e": "tap", "t": 10, "id": "table_start", "name": "jerry"},
                                 {"e": "screen", "t": 20, "name": "table", "prev": "room",
                                  "ms_on_prev": 4000}]})
        ws.send_json({"type": "ping", "nonce": 7})
        _drain(ws, "pong")
    rows = _records(sink)
    assert [r["e"] for r in rows] == ["tap", "screen"]
    assert all("name" not in r or r["e"] == "screen" for r in rows)
    assert all(r["who"] == "guest" and r["form"] == "phone" for r in rows)
    assert kinds and not [k for k in kinds if k.startswith("ui_") or k == "client_event"]
    logs = (tmp_path / "logs").resolve()
    assert logs not in sink.resolve().parents
    for f in logs.rglob("*"):
        if f.is_file():
            assert "client_event" not in f.read_text(errors="ignore")
            assert "table_start" not in f.read_text(errors="ignore")
