"""The process-lifetime activity counters behind ``/healthz``.

Production can go a week without a new room log, and from outside that looks
the same whether nobody played or every write failed.  These tests pin what
the health endpoint shows for each case: zeros on a fresh process, the room
and game path moving the counters, and a write failure counted with its errno
while the game carries on.
"""
from __future__ import annotations

import errno
import json
import re
from types import SimpleNamespace

import pytest

from tests.test_server_ws import _drain, _room_with_bots, client  # noqa: F401

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ZERO = {"rooms_created": 0, "games_started": 0, "rounds_recorded": 0,
        "records_written": 0, "record_write_failures": 0,
        "last_record_write": None, "last_record_failure": None}


@pytest.fixture(autouse=True)
def fresh_activity(monkeypatch):
    """Counters live for the process; each test starts its own."""
    from shengji.api import server

    activity = server.Activity()
    monkeypatch.setattr(server, "ACTIVITY", activity)
    return activity


def _activity(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    return response.json()["activity"]


def test_fresh_app_reports_zero_activity(client):
    from shengji.api import server

    assert server.Activity().health() == ZERO
    assert _activity(client) == ZERO


def test_room_game_and_records_move_their_counters(client):
    from shengji.api import server

    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        assert _activity(client) == {**ZERO, "rooms_created": 1}

        # A chat is the first record a lobby can write: a record without a round.
        a.send_json({"type": "chat", "text": "hello"})
        _drain(a, "chat")
        act = _activity(client)
        assert act["records_written"] == 1
        assert act["rounds_recorded"] == 0 and act["games_started"] == 0
        assert act["record_write_failures"] == 0
        assert ISO_UTC.match(act["last_record_write"])
        assert act["last_record_failure"] is None

        a.send_json({"type": "start_game"})
        _drain(a, "state", tries=60)
        act = _activity(client)
        assert act["rooms_created"] == 1
        assert act["games_started"] == 1
        assert act["rounds_recorded"] == 1
        assert act["record_write_failures"] == 0
        # The deal keeps appending after the first state frame; the file can
        # only be ahead of the counter, never behind it.
        lines = (server.LOG_DIR / f"{code}.jsonl").read_text().splitlines()
        assert 2 <= act["records_written"] <= len(lines)
        assert [json.loads(line)["e"] for line in lines[:2]] == ["chat", "round_start"]

        # Unauthenticated surface: no room code, no path.
        shown = json.dumps(act)
        assert code not in shown
        assert str(server.LOG_DIR) not in shown


def test_write_failure_is_counted_with_its_errno_and_the_game_goes_on(
        client, caplog, monkeypatch):
    from shengji.api import server

    failing = True

    def fake_open(*args, **kwargs):
        if failing:
            raise OSError(errno.ENOSPC, "No space left on device")
        return open(*args, **kwargs)

    monkeypatch.setattr(server, "open", fake_open, raising=False)
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        a.send_json({"type": "chat", "text": "hello"})
        _drain(a, "chat")
        act = _activity(client)
        assert act["records_written"] == 0
        assert act["record_write_failures"] == 1
        assert act["last_record_write"] is None
        failure = act["last_record_failure"]
        assert failure["class"] == "OSError"
        assert failure["errno"] == errno.ENOSPC
        assert failure["errno_name"] == "ENOSPC"
        assert ISO_UTC.match(failure["at"])

        # The game path is untouched by the failing writer: the table starts,
        # the deal runs, and the gap between games started and rounds
        # recorded is what names the failure.
        a.send_json({"type": "start_game"})
        st = _drain(a, "state", tries=60)
        assert st["phase"] in ("deal", "declare", "bury", "play")
        act = _activity(client)
        assert act["games_started"] == 1
        assert act["rounds_recorded"] == 0
        assert act["records_written"] == 0
        assert act["record_write_failures"] >= 2
        assert not (server.LOG_DIR / f"{code}.jsonl").exists()

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"
                    and "event logging failed" in r.getMessage()]
        assert len(warnings) == 1
        assert f"room {code} event logging failed (OSError errno=ENOSPC)" in warnings[0]
        assert "No space left" not in warnings[0]
        assert str(server.LOG_DIR) not in warnings[0]

        # Writes resume without a restart; the last failure stays on show.
        failing = False
        a.send_json({"type": "chat", "text": "again"})
        _drain(a, "chat", tries=400)   # the deal's state frames interleave
        act = _activity(client)
        assert act["records_written"] >= 1
        assert ISO_UTC.match(act["last_record_write"])
        assert act["last_record_failure"]["errno_name"] == "ENOSPC"
        assert (server.LOG_DIR / f"{code}.jsonl").exists()
        failures = act["record_write_failures"]
        a.send_json({"type": "chat", "text": "and again"})
        _drain(a, "chat", tries=400)
        act = _activity(client)
        assert act["record_write_failures"] == failures
        assert act["records_written"] >= 2


def test_real_filesystem_failure_records_the_platform_errno(tmp_path, caplog):
    """A log root that is a file: the OS raises, the counter names it."""
    from shengji.api import server

    log_dir = tmp_path / "logs"
    log_dir.write_text("not a directory")
    room = server.Room(code="ORD", log_dir=log_dir, bot=SimpleNamespace())
    room.log_event("probe", cards=["private cards"])

    assert server.ACTIVITY.record_write_failures == 1
    assert server.ACTIVITY.records_written == 0
    failure = server.ACTIVITY.health()["last_record_failure"]
    assert failure["class"] == "FileExistsError"
    assert failure["errno"] == errno.EEXIST
    assert failure["errno_name"] == "EEXIST"
    assert "(FileExistsError errno=EEXIST)" in caplog.text
    assert "private" not in caplog.text
    assert str(log_dir) not in caplog.text
    assert not room.evaluation_invalidated


def test_errno_without_a_platform_name_is_reported_as_its_number():
    from shengji.api import server

    activity = server.Activity()
    activity.record_failed(OSError(99999, "unnamed"))
    failure = activity.health()["last_record_failure"]
    assert failure == {"at": failure["at"], "class": "OSError",
                       "errno": 99999, "errno_name": None}
    activity.record_failed(OSError("no errno at all"))
    failure = activity.health()["last_record_failure"]
    assert failure["errno"] is None and failure["errno_name"] is None
    assert activity.record_write_failures == 2
