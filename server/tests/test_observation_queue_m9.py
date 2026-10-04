from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval.observation_queue import capture_queue, queue_unchanged, validate_queue_spec


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _m9_fixture(tmp_path: Path, schema: str = "codex-m9-reservation-v1"):
    panel = schema.endswith("panel-reservation-v1")
    lane = "m9-panel" if panel else "m9"
    reservation_dir = tmp_path / "queue"
    reservation_dir.mkdir(parents=True)
    reservation = reservation_dir / f"{lane}.json"
    launcher = tmp_path / f"{lane}.launcher"
    launcher.write_text(f"launcher {lane}\n")
    status = tmp_path / f"{lane}.status"
    packet_sha = "a" * 64
    _write_json(status, {
        "schema": "m9-panel-owner-terminal-v1" if panel else "m9-owner-terminal-v1",
        "packet_sha256": packet_sha,
        "process_status": "exited",
        "returncode": 0,
        "comparison_validated": False,
        "utc": "2026-10-04T00:00:00+00:00",
    })
    record = {
        "schema": schema,
        "lane": lane,
        "launcher": str(launcher),
        "launcher_sha256": _sha(launcher),
        "status": str(status),
        "pid": 424242,
        "packet_sha256": packet_sha,
        "seeds": [0, 1, 2],
        "count": 15 if panel else 12,
    }
    _write_json(reservation, record)
    entry = {
        "path": str(reservation),
        "sha256": _sha(reservation),
        "lane": lane,
        "launcher": str(launcher),
        "launcher_sha256": _sha(launcher),
        "status": str(status),
        "pid": 424242,
        "reservation_schema": schema,
        "status_sha256": _sha(status),
    }
    return {"reservation_dir": str(reservation_dir), "reservations": [entry]}, {
        "record": record, "reservation": reservation, "status": status,
        "entry": entry,
    }


def test_capture_accepts_original_and_panel_m9_records(tmp_path: Path) -> None:
    for schema in ("codex-m9-reservation-v1", "codex-m9-panel-reservation-v1"):
        spec, _ = _m9_fixture(tmp_path / schema)
        snapshot = capture_queue(spec, pid_alive=lambda _: False)
        assert queue_unchanged(spec, snapshot)


def test_capture_accepts_mixed_claude_and_m9_queue(tmp_path: Path) -> None:
    spec, paths = _m9_fixture(tmp_path / "m9")
    old_reservation = Path(spec["reservation_dir"]) / "claude.json"
    old_launcher = tmp_path / "old.launcher"
    old_launcher.write_text("old launcher\n")
    old_status = tmp_path / "old.status"
    old_status.write_text("2026-10-04T00:00:00Z old LANE DONE\n")
    _write_json(old_reservation, {
        "schema": "claude-reservation-v1", "lane": "old",
        "launcher": str(old_launcher), "launcher_sha256": _sha(old_launcher),
        "status": str(old_status), "seeds": [7], "count": 1,
    })
    spec["reservations"].append({
        "path": str(old_reservation), "sha256": _sha(old_reservation),
        "lane": "old", "launcher": str(old_launcher),
        "launcher_sha256": _sha(old_launcher), "status": str(old_status),
        "pid": 424243, "terminal_suffix": "old LANE DONE",
    })
    snapshot = capture_queue(spec, pid_alive=lambda _: False)
    assert len(snapshot["reservation_paths"]) == 2
    assert queue_unchanged(spec, snapshot)


@pytest.mark.parametrize("change", [
    "wrongkind", "packetsha", "count", "seeds", "statussha",
    "returncode_bool", "returncode_nonzero", "nonterminal", "pid_float",
    "pid_bool", "seed_bool",
])
def test_capture_rejects_invalid_m9_bindings(tmp_path: Path, change: str) -> None:
    spec, paths = _m9_fixture(tmp_path)
    if change == "wrongkind":
        paths["record"]["schema"] = "codex-m9-panel-reservation-v1"
    elif change == "packetsha":
        paths["record"]["packet_sha256"] = "b" * 64
    elif change == "count":
        paths["record"]["count"] = 15
    elif change == "seeds":
        paths["record"]["seeds"] = [0, 1, 3]
    elif change == "seed_bool":
        paths["record"]["seeds"] = [False, True, 2]
    elif change == "statussha":
        paths["entry"]["status_sha256"] = "0" * 64
    elif change == "returncode_bool":
        status = json.loads(paths["status"].read_text())
        status["returncode"] = False
        _write_json(paths["status"], status)
    elif change == "returncode_nonzero":
        status = json.loads(paths["status"].read_text())
        status["returncode"] = 1
        _write_json(paths["status"], status)
    elif change == "nonterminal":
        status = json.loads(paths["status"].read_text())
        status["process_status"] = "failed"
        _write_json(paths["status"], status)
    elif change == "pid_float":
        paths["record"]["pid"] = 424242.0
    elif change == "pid_bool":
        paths["record"]["pid"] = True
    if change in {"wrongkind", "packetsha", "count", "seeds", "seed_bool",
                  "pid_float", "pid_bool"}:
        _write_json(paths["reservation"], paths["record"])
        paths["entry"]["sha256"] = _sha(paths["reservation"])
    if change in {"returncode_bool", "returncode_nonzero", "nonterminal"}:
        paths["entry"]["status_sha256"] = _sha(paths["status"])
    with pytest.raises(ValueError):
        capture_queue(spec, pid_alive=lambda _: False)


def test_typed_m9_entry_rejects_legacy_suffix_fields(tmp_path: Path) -> None:
    spec, paths = _m9_fixture(tmp_path)
    spec["reservations"][0]["terminal_suffix"] = "m9 LANE DONE"
    with pytest.raises(ValueError):
        validate_queue_spec(spec)


def test_capture_rejects_live_m9_owner(tmp_path: Path) -> None:
    spec, _ = _m9_fixture(tmp_path)
    with pytest.raises(ValueError, match="alive"):
        capture_queue(spec, pid_alive=lambda _: True)


def test_queue_unchanged_detects_m9_status_mutation(tmp_path: Path) -> None:
    spec, paths = _m9_fixture(tmp_path)
    snapshot = capture_queue(spec, pid_alive=lambda _: False)
    paths["status"].write_text(paths["status"].read_text() + "\n")
    assert queue_unchanged(spec, snapshot) is False
