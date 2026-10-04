"""Fail-closed, bounded checks for the completed observation queue.

The queue is read-only evidence supplied by the caller.  Every path, digest,
identity stamp, process state, and terminal status is checked before an
admission may reuse the queue.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from .observation_lease import _nonsymlink_ancestry, file_stamp


_MAX_GUARD_BYTES = 16 * 1024
_MAX_RESERVATION_BYTES = 64 * 1024
_MAX_STATUS_BYTES = 1024 * 1024
_QUEUE_SCHEMA = "claude-reservation-v1"
_QUEUE_KEYS = frozenset({"reservation_dir", "reservations"})
_RESERVATION_KEYS = frozenset({
    "path", "sha256", "lane", "launcher", "launcher_sha256", "status", "pid",
    "terminal_suffix",
})
_RESUMED_RESERVATION_KEYS = _RESERVATION_KEYS | {"resumed_status_sha256"}
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_RUNPVC_LANE = re.compile(r"^runPVC[1-9][0-9]*$")
_LINE_BREAKS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise ValueError(f"nonfinite JSON constant: {token}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _parse_finite_object(raw: bytes) -> dict[str, Any]:
    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        return value

    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant,
                       parse_float=finite_float)
    if type(value) is not dict:
        raise ValueError("guard JSON must be an object")
    return value


def _canonical_absolute(value: Any, label: str) -> Path:
    if type(value) is not str or not value or not value.startswith("/"):
        raise ValueError(f"{label} must be canonical absolute path")
    path = Path(value)
    if str(path) != value or ".." in path.parts or not _nonsymlink_ancestry(path):
        raise ValueError(f"{label} must be canonical absolute path")
    return path


def _strict_sha(value: Any, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _valid_terminal_suffix(suffix: Any, lane: Any) -> bool:
    if type(suffix) is not str or not suffix or any(char in suffix for char in _LINE_BREAKS):
        return False
    if suffix.endswith("LANE DONE"):
        return True
    return (type(lane) is str and _RUNPVC_LANE.fullmatch(lane) is not None
            and suffix == f"=== {lane} DONE ===")


def validate_queue_spec(spec: Any) -> dict[str, Any]:
    """Validate the immutable shape and pins for a completed queue."""

    if type(spec) is not dict or set(spec) != _QUEUE_KEYS:
        raise ValueError("queue spec fields mismatch")
    reservation_dir = _canonical_absolute(spec["reservation_dir"], "reservation_dir")
    reservations = spec["reservations"]
    if type(reservations) is not list or not reservations:
        raise ValueError("reservations must be a non-empty list")
    seen: set[str] = set()
    seen_status: set[str] = set()
    for index, entry in enumerate(reservations):
        if type(entry) is not dict or set(entry) not in (
                _RESERVATION_KEYS, _RESUMED_RESERVATION_KEYS):
            raise ValueError(f"reservation[{index}] fields mismatch")
        path = _canonical_absolute(entry["path"], f"reservation[{index}].path")
        status = _canonical_absolute(entry["status"], f"reservation[{index}].status")
        launcher = _canonical_absolute(entry["launcher"], f"reservation[{index}].launcher")
        if path.parent != reservation_dir or path.name in {"", ".", ".."}:
            raise ValueError("reservation path must be an immediate child")
        if status.name in {"", ".", ".."}:
            raise ValueError("status path is malformed")
        if str(path) in seen or str(status) in seen_status or str(path) == str(status):
            raise ValueError("reservation paths must be unique")
        seen.add(str(path))
        seen_status.add(str(status))
        _strict_sha(entry["sha256"], f"reservation[{index}].sha256")
        _strict_sha(entry["launcher_sha256"], f"reservation[{index}].launcher_sha256")
        if "resumed_status_sha256" in entry:
            _strict_sha(entry["resumed_status_sha256"],
                        f"reservation[{index}].resumed_status_sha256")
        if type(entry["lane"]) is not str or not entry["lane"]:
            raise ValueError("lane must be non-empty")
        if type(entry["pid"]) is not int or entry["pid"] <= 1:
            raise ValueError("pid must be a strict integer greater than one")
        if not _valid_terminal_suffix(entry["terminal_suffix"], entry["lane"]):
            raise ValueError("terminal_suffix must end with LANE DONE or name a runPVC lane")
    launcher_hashes: dict[str, str] = {}
    for entry in reservations:
        launcher = str(Path(entry["launcher"]))
        prior = launcher_hashes.setdefault(launcher, entry["launcher_sha256"])
        if prior != entry["launcher_sha256"]:
            raise ValueError("shared launcher has conflicting SHA")
    return spec


def _stable_read(path: Path, limit: int) -> tuple[bytes, tuple[int, int, int, int, int]]:
    """Read a bounded file only when its identity is stable around the read."""

    before = file_stamp(path)
    if before[2] > limit:
        raise ValueError(f"file exceeds bounded read: {path}")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    after = file_stamp(path)
    if len(raw) > limit or before != after:
        raise ValueError(f"file changed during bounded read: {path}")
    return raw, after


def _default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        raise ValueError(f"cannot determine pid {pid}") from exc
    return True


def _status_terminal(raw: bytes, suffix: str,
                     resumed_status_sha256: str | None = None) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("status is not UTF-8") from exc
    lines = text.splitlines()
    terminal_indices = [index for index, line in enumerate(lines)
                        if len(line) >= 21 and _TIMESTAMP.fullmatch(line[:20])
                        and line[20:] == " " + suffix]
    if len(terminal_indices) != 1:
        raise ValueError("status must contain exactly one terminal line")
    markers = ("REFUSING:", "ABORTED", "STOPPED", "ABORT:", "STOP:")
    if resumed_status_sha256 is not None:
        if hashlib.sha256(raw).hexdigest() != resumed_status_sha256:
            raise ValueError("resumed status SHA mismatch")
        terminal_index = terminal_indices[0]
        if any(index >= terminal_index and marker in line
               for index, line in enumerate(lines) for marker in markers):
            raise ValueError("status contains a refusal after terminal")
    elif any(marker in line for line in lines for marker in markers):
        raise ValueError("status contains an explicit refusal marker")


def capture_queue(spec: Any, *, pid_alive=None) -> dict[str, Any]:
    """Capture queue identities after validating every completed reservation."""

    spec = validate_queue_spec(spec)
    reservation_dir = Path(spec["reservation_dir"])
    if (not reservation_dir.is_dir() or reservation_dir.is_symlink()
            or not _nonsymlink_ancestry(reservation_dir)):
        raise ValueError("reservation directory must be a regular nonsymlink directory")
    directory_stat = reservation_dir.stat()
    directory_identity = [directory_stat.st_dev, directory_stat.st_ino]
    entries = spec["reservations"]
    expected_dir_paths = {str(Path(entry["path"])) for entry in entries}
    actual_dir_paths = {str(path) for path in reservation_dir.iterdir()}
    if actual_dir_paths != expected_dir_paths:
        raise ValueError("reservation directory entries differ from queue spec")
    files: dict[str, list[int]] = {}
    launcher_stamps: dict[str, tuple[int, int, int, int, int]] = {}
    pid_alive_fn = _default_pid_alive if pid_alive is None else pid_alive
    if not callable(pid_alive_fn):
        raise ValueError("pid_alive must be callable")
    for entry in entries:
        reservation_path = Path(entry["path"])
        raw, stamp = _stable_read(reservation_path, _MAX_RESERVATION_BYTES)
        try:
            record = _parse_finite_object(raw)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("reservation JSON is malformed") from exc
        if (record.get("schema") != _QUEUE_SCHEMA
                or record.get("lane") != entry["lane"]
                or record.get("launcher") != entry["launcher"]
                or record.get("launcher_sha256") != entry["launcher_sha256"]
                or record.get("status") != entry["status"]):
            raise ValueError("reservation metadata does not match queue spec")
        seeds = record.get("seeds")
        if (type(seeds) is not list or not seeds
                or any(type(seed) is not int or seed <= 0 for seed in seeds)):
            raise ValueError("reservation seeds must be positive strict integers")
        if type(record.get("count")) is not int or record["count"] <= 0:
            raise ValueError("reservation count must be a positive strict integer")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("reservation SHA mismatch")
        files[str(reservation_path)] = list(stamp)
        launcher_path = Path(entry["launcher"])
        if str(launcher_path) not in launcher_stamps:
            launcher_before = file_stamp(launcher_path)
            launcher_raw = launcher_path.read_bytes()
            launcher_after = file_stamp(launcher_path)
            if launcher_before != launcher_after:
                raise ValueError("launcher changed during read")
            if hashlib.sha256(launcher_raw).hexdigest() != entry["launcher_sha256"]:
                raise ValueError("launcher SHA mismatch")
            launcher_stamps[str(launcher_path)] = launcher_after
        status_path = Path(entry["status"])
        status_raw, status_stamp = _stable_read(status_path, _MAX_STATUS_BYTES)
        _status_terminal(status_raw, entry["terminal_suffix"],
                         entry.get("resumed_status_sha256"))
        if pid_alive_fn(entry["pid"]):
            raise ValueError("reservation process is still alive")
        files[str(status_path)] = list(status_stamp)
        files[str(launcher_path)] = list(launcher_stamps[str(launcher_path)])
    after_dir = reservation_dir.stat()
    if ([after_dir.st_dev, after_dir.st_ino] != directory_identity
            or {str(path) for path in reservation_dir.iterdir()} != expected_dir_paths):
        raise ValueError("reservation directory changed during capture")
    for path_string, captured in files.items():
        if list(file_stamp(Path(path_string))) != captured:
            raise ValueError("captured file changed after read")
    return {
        "directory_identity": directory_identity,
        "files": {key: files[key] for key in sorted(files)},
        "reservation_paths": sorted(str(Path(entry["path"])) for entry in entries),
    }


def queue_unchanged(spec: Any, snapshot: Any, *, owned_record=None) -> bool:
    """Return whether a captured queue remains unchanged, allowing one owner file."""

    try:
        spec = validate_queue_spec(spec)
        if (type(snapshot) is not dict
                or set(snapshot) != {"directory_identity", "files", "reservation_paths"}):
            return False
        reservation_dir = Path(spec["reservation_dir"])
        if (type(snapshot["directory_identity"]) is not list
                or len(snapshot["directory_identity"]) != 2
                or any(type(value) is not int for value in snapshot["directory_identity"])):
            return False
        stat = reservation_dir.stat()
        if [stat.st_dev, stat.st_ino] != snapshot["directory_identity"]:
            return False
        expected = {str(Path(entry["path"])) for entry in spec["reservations"]}
        expected.update(str(Path(entry["status"])) for entry in spec["reservations"])
        expected.update(str(Path(entry["launcher"])) for entry in spec["reservations"])
        files = snapshot["files"]
        if type(files) is not dict or set(files) != expected:
            return False
        if (type(snapshot["reservation_paths"]) is not list
                or any(type(stamp) is not list or len(stamp) != 5
                       or any(type(value) is not int for value in stamp)
                       for stamp in files.values())):
            return False
        if snapshot["reservation_paths"] != sorted(
                str(Path(entry["path"])) for entry in spec["reservations"]):
            return False
        expected_records = {str(Path(entry["path"])) for entry in spec["reservations"]}
        if owned_record is not None:
            if type(owned_record) is not dict or set(owned_record) != {"path", "stamp"}:
                return False
            own_path = _canonical_absolute(owned_record["path"], "own reservation path")
            own_stamp = owned_record["stamp"]
            if (own_path.parent != reservation_dir or str(own_path) in expected
                    or type(own_stamp) is not list or len(own_stamp) != 5
                    or any(type(value) is not int for value in own_stamp)
                    or list(file_stamp(own_path)) != own_stamp):
                return False
            expected_records.add(str(own_path))
        if {str(path) for path in reservation_dir.iterdir()} != expected_records:
            return False
        for path_string in sorted(expected):
            if list(file_stamp(Path(path_string))) != files[path_string]:
                return False
        return True
    except (OSError, TypeError, ValueError):
        return False


def write_exclusive_json(path: Path, payload: Any) -> None:
    """Write one canonical finite JSON file without overwriting an existing file."""

    path = Path(path)
    if (not _nonsymlink_ancestry(path.parent) or path.parent.is_symlink()
            or not path.parent.is_dir()):
        raise ValueError("JSON parent must be a regular nonsymlink directory")
    raw = _canonical(payload)
    with path.open("xb") as handle:
        handle.write(raw)


def guard_release(path: Path, expected: dict[str, Any]) -> bool:
    """Validate a canonical finite JSON release guard without changing it."""

    path = Path(path)
    try:
        expected_raw = _canonical(expected)
        if len(expected_raw) > _MAX_GUARD_BYTES:
            return False
        before = file_stamp(path)
        if before[2] > _MAX_GUARD_BYTES:
            return False
        with path.open("rb") as handle:
            raw = handle.read(_MAX_GUARD_BYTES + 1)
        if len(raw) > _MAX_GUARD_BYTES:
            return False
        actual = _parse_finite_object(raw)
        if _canonical(actual) != expected_raw:
            return False
        if file_stamp(path) != before:
            return False
        return True
    except (OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False


__all__ = [
    "capture_queue", "file_stamp", "guard_release", "queue_unchanged",
    "validate_queue_spec", "write_exclusive_json",
]
