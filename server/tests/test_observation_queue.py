from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval.observation_queue import (
    capture_queue,
    file_stamp,
    guard_release,
    queue_unchanged,
    validate_queue_spec,
    write_exclusive_json,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _queue_fixture(tmp_path: Path) -> tuple[dict, dict[str, Path]]:
    reservation_dir = tmp_path / "reservations"
    reservation_dir.mkdir()
    entries = []
    paths: dict[str, Path] = {"reservation_dir": reservation_dir}
    for name, lane, suffix in (
        ("screen.json", "screen-a", "screen-a LANE DONE"),
        ("datagen.json", "runPVC7", "=== runPVC7 DONE ==="),
    ):
        launcher = tmp_path / f"{lane}.launcher"
        launcher.write_bytes(f"synthetic {lane}\n".encode())
        status = tmp_path / f"{lane}.status"
        status.write_text(
            f"2026-10-04T00:00:00Z started {lane}\n"
            f"2026-10-04T00:00:01Z {suffix}\n"
        )
        record = {
            "schema": "claude-reservation-v1",
            "lane": lane,
            "launcher": str(launcher),
            "launcher_sha256": _sha(launcher),
            "status": str(status),
            "seeds": [7, 11],
            "count": 3,
        }
        reservation = reservation_dir / name
        reservation.write_bytes(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )
        entries.append({
            "path": str(reservation),
            "sha256": _sha(reservation),
            "lane": lane,
            "launcher": str(launcher),
            "launcher_sha256": record["launcher_sha256"],
            "status": str(status),
            "pid": 999999,
            "terminal_suffix": suffix,
        })
        paths[lane] = reservation
        paths[f"{lane}.status"] = status
        paths[f"{lane}.launcher"] = launcher
    return {"reservation_dir": str(reservation_dir), "reservations": entries}, paths


def test_capture_accepts_screen_and_runpvc_datagen_and_reuses_snapshot(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)

    snapshot = capture_queue(spec, pid_alive=lambda _: False)

    assert snapshot["reservation_paths"] == sorted(
        [str(paths["screen-a"]), str(paths["runPVC7"])]
    )
    assert queue_unchanged(spec, snapshot) is True


def test_capture_refuses_live_pid(tmp_path: Path) -> None:
    spec, _ = _queue_fixture(tmp_path)
    with pytest.raises(ValueError, match="alive"):
        capture_queue(spec, pid_alive=lambda _: True)


def test_capture_refuses_unknown_extra_reservation(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    extra = paths["reservation_dir"] / "unexpected.json"
    extra.write_text("{}")

    with pytest.raises(ValueError, match="entries differ"):
        capture_queue(spec, pid_alive=lambda _: False)


def test_queue_unchanged_refuses_drift_and_symlink_entries(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    snapshot = capture_queue(spec, pid_alive=lambda _: False)

    paths["runPVC7.status"].write_text(
        "2026-10-04T00:00:02Z === runPVC7 DONE ===\n"
    )
    assert queue_unchanged(spec, snapshot) is False

    link = paths["reservation_dir"] / "foreign-link"
    link.symlink_to(paths["runPVC7.status"])
    assert queue_unchanged(spec, snapshot) is False


def test_validate_rejects_symlink_ancestry(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    real = paths["reservation_dir"]
    alias = tmp_path / "reservation-alias"
    alias.symlink_to(real, target_is_directory=True)
    spec["reservation_dir"] = str(alias)

    with pytest.raises(ValueError):
        validate_queue_spec(spec)


@pytest.mark.parametrize(
    "status_text",
    [
        "2026-10-04T00:00:00Z runPVC7 DONE\n",
        "2026-10-04T00:00:00Z === runPVC7 DONE ===\n"
        "2026-10-04T00:00:01Z === runPVC7 DONE ===\n",
    ],
)
def test_capture_refuses_wrong_or_duplicate_terminal(tmp_path: Path, status_text: str) -> None:
    spec, paths = _queue_fixture(tmp_path)
    paths["runPVC7.status"].write_text(status_text)

    with pytest.raises(ValueError):
        capture_queue(spec, pid_alive=lambda _: False)


def _resumed_status(spec: dict, paths: dict[str, Path], text: str, pin: str | None = None):
    status = paths["runPVC7.status"]
    status.write_text(text)
    entry = next(item for item in spec["reservations"] if item["lane"] == "runPVC7")
    if pin is None:
        entry.pop("resumed_status_sha256", None)
    else:
        entry["resumed_status_sha256"] = pin
    return status


def test_stop_before_done_requires_matching_reviewed_status_pin(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    text = (
        "2026-10-04T00:00:00Z STOPPED: resumed after supervisor review\n"
        "2026-10-04T00:00:01Z === runPVC7 DONE ===\n"
    )
    status = _resumed_status(spec, paths, text)
    with pytest.raises(ValueError, match="explicit refusal"):
        capture_queue(spec, pid_alive=lambda _: False)

    _resumed_status(spec, paths, text, _sha(status))
    snapshot = capture_queue(spec, pid_alive=lambda _: False)
    assert str(status) in snapshot["files"]


def test_resumed_status_wrong_pin_is_refused(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    status = _resumed_status(
        spec, paths,
        "2026-10-04T00:00:00Z STOPPED: resumed\n"
        "2026-10-04T00:00:01Z === runPVC7 DONE ===\n",
        "0" * 64,
    )
    assert _sha(status) != "0" * 64
    with pytest.raises(ValueError, match="resumed status SHA mismatch"):
        capture_queue(spec, pid_alive=lambda _: False)


def test_resumed_status_refuses_marker_after_terminal(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    text = (
        "2026-10-04T00:00:00Z === runPVC7 DONE ===\n"
        "2026-10-04T00:00:01Z STOPPED: late refusal\n"
    )
    status = _resumed_status(spec, paths, text, None)
    _resumed_status(spec, paths, text, _sha(status))
    with pytest.raises(ValueError, match="refusal after terminal"):
        capture_queue(spec, pid_alive=lambda _: False)


def test_resumed_status_requires_one_terminal_line(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    text = (
        "2026-10-04T00:00:00Z === runPVC7 DONE ===\n"
        "2026-10-04T00:00:01Z === runPVC7 DONE ===\n"
    )
    status = _resumed_status(spec, paths, text, None)
    _resumed_status(spec, paths, text, _sha(status))
    with pytest.raises(ValueError, match="exactly one terminal"):
        capture_queue(spec, pid_alive=lambda _: False)


def test_capture_refuses_malformed_duplicate_key_json(tmp_path: Path) -> None:
    spec, paths = _queue_fixture(tmp_path)
    paths["runPVC7"].write_bytes(
        b'{"schema":"claude-reservation-v1","schema":"other"}'
    )
    with pytest.raises(ValueError, match="malformed"):
        capture_queue(spec, pid_alive=lambda _: False)


@pytest.mark.parametrize(
    "suffix",
    ["DONE", "runPVC7 DONE", "=== runPVC7 DONE ===\n", "=== runPVCX DONE ==="],
)
def test_validate_rejects_arbitrary_done_suffixes(tmp_path: Path, suffix: str) -> None:
    spec, _ = _queue_fixture(tmp_path)
    spec["reservations"][1]["terminal_suffix"] = suffix
    with pytest.raises(ValueError):
        validate_queue_spec(spec)


def test_guard_release_is_canonical_and_wrong_release_refused(tmp_path: Path) -> None:
    release = tmp_path / "RELEASE.json"
    write_exclusive_json(release, {"schema": "m9-release-v1", "ok": True})

    assert guard_release(release, {"ok": True, "schema": "m9-release-v1"}) is True
    assert guard_release(release, {"schema": "wrong-release", "ok": True}) is False

    release.write_bytes(b"not-json")
    assert guard_release(release, {"schema": "m9-release-v1", "ok": True}) is False


def test_guard_release_refuses_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"ok":true}')
    link = tmp_path / "release.json"
    link.symlink_to(target)
    assert guard_release(link, {"ok": True}) is False
    with pytest.raises(ValueError):
        file_stamp(link)
