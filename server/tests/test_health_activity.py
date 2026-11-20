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

from tests.test_server_ws import _drain, _refuse_the_first_start, client  # noqa: F401
from native_switches import NATIVE_OFF

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ZERO = {"rooms_created": 0, "games_started": 0, "rounds_recorded": 0,
        "records_written": 0, "record_write_failures": 0,
        "account_link_failures": 0,
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
        a.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(a, "room")["room"]
        _drain(a, "state")
        act = _activity(client)
        assert act["rooms_created"] == 1
        assert act["games_started"] == 1
        assert act["rounds_recorded"] == 1
        assert act["record_write_failures"] == 0
        # The deal keeps appending after the first state frame; the file can
        # only be ahead of the counter, never behind it.
        lines = (server.LOG_DIR / f"{code}.jsonl").read_text().splitlines()
        assert 1 <= act["records_written"] <= len(lines)
        assert ISO_UTC.match(act["last_record_write"])
        assert json.loads(lines[0])["e"] == "round_start"
        assert json.loads(lines[0])["round"] == 1

        # Unauthenticated surface: no room code, no path.
        shown = json.dumps(act)
        assert code not in shown
        assert str(server.LOG_DIR) not in shown


def test_a_refused_create_counts_no_room(client, monkeypatch):
    """A create whose start is refused discards its room, so only the
    started one counts."""
    from shengji.api import server

    refused = _refuse_the_first_start(monkeypatch, server.IllegalPlay("Refused for the test."))
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(a, "room")["room"]
        _drain(a, "left")
        assert refused == [code]
        assert _activity(client)["rooms_created"] == 0
        a.send_json({"type": "create_room", "name": "jerry"})
        _drain(a, "room")
        _drain(a, "state")
        act = _activity(client)
        assert act["rooms_created"] == 1
        assert act["games_started"] == 1


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
        # The game path is untouched by the failing writer: the table starts,
        # the deal runs, and the gap between games started and rounds
        # recorded is what names the failure.
        a.send_json({"type": "create_room", "name": "jerry"})
        code = _drain(a, "room")["room"]
        st = _drain(a, "state")
        assert st["phase"] in ("deal", "declare", "bury", "play")
        act = _activity(client)
        assert act["games_started"] == 1
        assert act["rounds_recorded"] == 0
        assert act["records_written"] == 0
        assert act["record_write_failures"] >= 1
        assert act["last_record_write"] is None
        failure = act["last_record_failure"]
        assert failure["class"] == "OSError"
        assert failure["errno"] == errno.ENOSPC
        assert failure["errno_name"] == "ENOSPC"
        assert ISO_UTC.match(failure["at"])
        assert not (server.LOG_DIR / f"{code}.jsonl").exists()

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"
                    and "event logging failed" in r.getMessage()]
        assert len(warnings) == 1
        assert f"room {code} event logging failed (OSError errno=ENOSPC)" in warnings[0]
        assert "No space left" not in warnings[0]
        assert str(server.LOG_DIR) not in warnings[0]

        # Writes resume without a restart; the last failure stays on show.
        failing = False
        a.send_json({"type": "table_chat", "text": "again"})
        _drain(a, "chat")   # the deal's state frames interleave
        act = _activity(client)
        assert act["records_written"] >= 1
        assert ISO_UTC.match(act["last_record_write"])
        assert act["last_record_failure"]["errno_name"] == "ENOSPC"
        assert (server.LOG_DIR / f"{code}.jsonl").exists()
        failures = act["record_write_failures"]
        a.send_json({"type": "table_chat", "text": "and again"})
        _drain(a, "chat")
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


LATENCY_SWITCHES = ("SHENGJI_PV_ENCODE_PREFIX_CACHE", "SHENGJI_PV_SINGLE_CANDIDATE_FAST",
                    "SHENGJI_PV_LEAF_GREEDY_STREAM", "SHENGJI_PV_ENCODE_BATCH_FAST",
                    "SHENGJI_PV_LEGAL_NATIVE", "SHENGJI_PV_ENCODE_NATIVE",
                    "SHENGJI_PV_LEAF_CACHE_RELEASE", "SHENGJI_PV_LEAF_CLONE_FAST",
                    "SHENGJI_PV_LEAF_TRICK_CACHE")


def test_healthz_reports_the_latency_switches_from_the_process_environment(
        client, tmp_path, monkeypatch):
    """The latency switches enter no served name, so ``/healthz`` shows them under
    ``pv_search``, read from the process environment the bot factory reads."""
    # imported before SHENGJI_PV_CKPT is set: its import registers the env's
    # served package, which this stand-in file is not
    import shengji.train.pv_search_policy  # noqa: F401

    package = tmp_path / "package.npz"
    package.write_bytes(b"stand-in")
    monkeypatch.setenv("SHENGJI_PV_CKPT", str(package))
    for key in LATENCY_SWITCHES:
        monkeypatch.delenv(key, raising=False)
    health = client.get("/healthz").json()["pv_search"]
    assert health["latency_switches"] == {"encode_prefix_cache": False, "single_candidate_fast": False,
                                          "leaf_greedy_stream": False, "encode_batch_fast": False, **NATIVE_OFF}
    for key in ("SHENGJI_PV_ENCODE_PREFIX_CACHE", "SHENGJI_PV_LEAF_GREEDY_STREAM",
                "SHENGJI_PV_ENCODE_BATCH_FAST"):
        monkeypatch.setenv(key, "1")
    health = client.get("/healthz").json()["pv_search"]
    assert health["latency_switches"] == {"encode_prefix_cache": True, "single_candidate_fast": False,
                                          "leaf_greedy_stream": True, "encode_batch_fast": True, **NATIVE_OFF}
    # a malformed switch is reported, not raised: health must answer
    monkeypatch.setenv("SHENGJI_PV_ENCODE_BATCH_FAST", "yes")
    assert "must be 0 or 1" in client.get("/healthz").json()["pv_search"]["error"]


def test_healthz_hashes_each_served_file_once(client, tmp_path, monkeypatch):
    """``/healthz`` runs on the event loop: a model file is hashed on the first
    call only, and again only when the file itself changes."""
    import os

    import shengji.train.pv_search_policy  # noqa: F401
    from shengji.ai import cwv_policy
    from shengji.api import server

    real = cwv_policy.file_sha256
    hashed = []

    def counting(path):
        hashed.append(str(path))
        return real(path)

    monkeypatch.setattr(cwv_policy, "file_sha256", counting)
    monkeypatch.setattr(server, "_FILE_SHA256", {})
    package, prior = tmp_path / "package.npz", tmp_path / "prior.pt"
    package.write_bytes(b"value stand-in")
    prior.write_bytes(b"prior stand-in")
    monkeypatch.setenv("SHENGJI_PV_CKPT", str(package))
    monkeypatch.setenv("SHENGJI_CWV_PRIOR_CKPT", str(prior))
    first = client.get("/healthz").json()
    assert sorted(hashed) == sorted([str(package), str(prior)])
    second = client.get("/healthz").json()
    assert len(hashed) == 2, "a second /healthz hashed the files again"
    assert second["pv_search"]["sha256"] == first["pv_search"]["sha256"] == real(package)
    assert second["prior"]["sha256"] == first["prior"]["sha256"] == real(prior)
    package.write_bytes(b"another value stand-in")
    os.utime(package, ns=(1, 1))
    assert client.get("/healthz").json()["pv_search"]["sha256"] == real(package)
    assert hashed.count(str(package)) == 2


def test_main_runs_uvicorn_with_a_ten_second_ping(monkeypatch):
    import sys
    from types import ModuleType

    from shengji.api import server

    calls = []
    fake = ModuleType("uvicorn")
    fake.run = lambda *args, **kwargs: calls.append((args, kwargs))
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    server.main()
    [(args, kwargs)] = calls
    assert args == ("shengji.api.server:app",)
    assert kwargs["ws_ping_interval"] == 10 and kwargs["ws_ping_timeout"] == 10
