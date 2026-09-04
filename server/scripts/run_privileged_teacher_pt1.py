#!/usr/bin/env python3
"""Execute a bounded PT1 state list and seal a recoverable packet.

The state provider is code, not a result packet: it must expose
``load_states()`` returning ``(public_round, true_round)`` pairs.  Each pair
is evaluated by the PT1 core.  Existing packet, manifest, and record bytes are
write-once; a mismatching restart is refused.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time

from shengji.rl.privileged_teacher_pt1 import (
    PrivilegedTeacherPT1Error,
    canonical_json_bytes,
    manifest_for,
    run_pt1,
    seal_true_world,
    TrueWorld,
)


def _fsync_directory(path: Path) -> None:
    """Durably publish directory-entry changes for this artifact directory."""
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise PrivilegedTeacherPT1Error(f"existing artifact bytes mismatch: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise PrivilegedTeacherPT1Error(
                    f"existing artifact bytes mismatch: {path}")
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
            _fsync_directory(path.parent)


def _advance_checkpoint(path: Path, data: bytes) -> None:
    """Atomically advance a checkpoint only along its existing prefix."""
    try:
        new = json.loads(data.decode("ascii"))
    except Exception as exc:
        raise PrivilegedTeacherPT1Error("checkpoint update is not canonical") from exc
    if canonical_json_bytes(new) != data or not isinstance(new, dict) \
            or new.get("schema") != "privileged-teacher-pt1-search-checkpoint-v1":
        raise PrivilegedTeacherPT1Error("checkpoint update is not canonical PT1")
    if (not isinstance(new.get("records"), list)
            or new.get("completed_units") != len(new["records"])
            or type(new.get("truncated_by_deadline")) is not bool):
        raise PrivilegedTeacherPT1Error("checkpoint progress drift")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise PrivilegedTeacherPT1Error("checkpoint path is not a regular file")
        old_data = path.read_bytes()
        try:
            old = json.loads(old_data.decode("ascii"))
        except Exception as exc:
            raise PrivilegedTeacherPT1Error("existing checkpoint is not canonical") from exc
        if canonical_json_bytes(old) != old_data or not isinstance(old, dict) \
                or old.get("schema") != new["schema"]:
            raise PrivilegedTeacherPT1Error("existing checkpoint is not canonical PT1")
        old_rows = old.get("records")
        new_rows = new.get("records")
        if (not isinstance(old_rows, list) or old.get("completed_units") != len(old_rows)
                or type(old.get("truncated_by_deadline")) is not bool
                or not isinstance(new_rows, list)
                or len(new_rows) < len(old_rows)
                or new_rows[:len(old_rows)] != old_rows):
            raise PrivilegedTeacherPT1Error("checkpoint is stale or divergent")
        if len(new_rows) == len(old_rows):
            completing_same_prefix = (
                old.get("truncated_by_deadline") is True
                and new.get("truncated_by_deadline") is False
                and new.get("completed_units") == old.get("completed_units"))
            if old_data != data and not completing_same_prefix:
                raise PrivilegedTeacherPT1Error("checkpoint is stale or divergent")
            if old_data == data:
                return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_progress(path: Path, payload: dict[str, object]) -> None:
    data = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
            _fsync_directory(path.parent)


def _load_states(path: Path):
    if path.is_symlink() or not path.is_file():
        raise PrivilegedTeacherPT1Error("state provider must be a regular file")
    spec = importlib.util.spec_from_file_location("pt1_state_provider", path)
    if spec is None or spec.loader is None:
        raise PrivilegedTeacherPT1Error("state provider cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loader = getattr(module, "load_states", None)
    if not callable(loader):
        raise PrivilegedTeacherPT1Error("state provider must define load_states()")
    states = []
    for public, true in loader():
        # A provider may return a sealed capability or an exact true Round;
        # it may not provide a precomputed PT1 record.
        if type(true) is TrueWorld:
            sealed = true
        else:
            sealed = seal_true_world(true)
        states.append((public, sealed))
    return states


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", required=True, type=Path,
                        help="Python provider defining load_states()")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seeds", default="0,1,2,3")
    parser.add_argument("--deadline-seconds", type=float)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        seeds = tuple(int(value) for value in args.seeds.split(",") if value != "")
        if any(seed < 0 for seed in seeds):
            raise PrivilegedTeacherPT1Error("seeds must be nonnegative")
        states = _load_states(args.states)
        checkpoint_path = args.output_dir / "checkpoint.json"
        if args.resume and not checkpoint_path.exists():
            raise PrivilegedTeacherPT1Error("resume checkpoint missing")
        checkpoint = checkpoint_path.read_bytes() if args.resume and checkpoint_path.exists() else None
        deadline = (time.monotonic() + args.deadline_seconds
                    if args.deadline_seconds is not None else None)
        progress_path = args.output_dir / "progress.json"

        def publish_checkpoint(data: bytes) -> None:
            _advance_checkpoint(checkpoint_path, data)
            checkpoint_payload = json.loads(data.decode("ascii"))
            _write_progress(progress_path, {
                "completed_units": checkpoint_payload["completed_units"],
                "total_units": len(states) * len(seeds),
                "status": "TRUNCATED",
                "truncated_by_deadline": True,
            })

        packet = run_pt1(
            states, seeds=seeds, deadline=deadline, checkpoint=checkpoint,
            checkpoint_sink=publish_checkpoint)
        # The complete checkpoint is durable before any final artifact.  A
        # crash at either final write therefore resumes in a finalizable state.
        _advance_checkpoint(checkpoint_path, packet.checkpoint)
        # A deadline prefix is represented by checkpoint/progress only.  The
        # sealed packet and manifest are written once, after completion; this
        # leaves the same output directory resumable without replacing a
        # supposedly final artifact.
        if packet.status == "COMPLETE":
            packet_bytes = canonical_json_bytes(packet.payload())
            manifest_bytes = canonical_json_bytes(manifest_for(packet))
            _write_once(args.output_dir / "packet.json", packet_bytes)
            _write_once(args.output_dir / "manifest.json", manifest_bytes)
        _write_progress(progress_path, {
            "completed_units": packet.progress["completed_units"],
            "total_units": packet.progress["total_units"],
            "status": packet.status,
            "truncated_by_deadline": packet.truncated_by_deadline})
    except (OSError, ValueError, PrivilegedTeacherPT1Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
