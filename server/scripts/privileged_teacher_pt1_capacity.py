#!/usr/bin/env python3
"""Run and durably publish the score-redacted PT1 capacity packet."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile
import time

from shengji.rl.privileged_teacher_pt1_capacity import (
    CapacityDesign, PT1CapacityError, manifest_for, run_capacity,
    verify_capacity_report, verify_manifest,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise PT1CapacityError(f"capacity artifact mismatch: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.",
                                               dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o400)
        os.link(temporary, path)
        _fsync_directory(path.parent)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise PT1CapacityError(f"capacity artifact mismatch: {path}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
            _fsync_directory(path.parent)


def _write_progress(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.",
                                               dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
            _fsync_directory(path.parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--deadline-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.secret_file.is_symlink() or not args.secret_file.is_file():
            raise PT1CapacityError("capacity secret must be a regular file")
        secret_stat = args.secret_file.stat()
        if stat.S_IMODE(secret_stat.st_mode) != 0o400 or secret_stat.st_nlink != 1:
            raise PT1CapacityError("capacity secret must be mode 0400 and single-link")
        secret = args.secret_file.read_bytes()
        if len(secret) != 32:
            raise PT1CapacityError("capacity secret must be 32 bytes")
        design = CapacityDesign(
            capture_secret_sha256=__import__("hashlib").sha256(secret).hexdigest())
        deadline = (time.monotonic() + args.deadline_seconds
                    if args.deadline_seconds is not None else None)
        progress = args.output_dir / "progress.json"
        report = run_capacity(
            design, capture_secret=secret, deadline=deadline,
            progress_sink=lambda value: _write_progress(progress, value))
        verify_capacity_report(report, design=design)
        manifest = manifest_for(report)
        verify_manifest(manifest, report)
        _write_once(args.output_dir / "capacity.json", report.canonical_bytes())
        _write_once(args.output_dir / "manifest.json",
                    canonical_json_bytes(manifest))
        _write_progress(progress, {
            "completed_units": report.payload()["record_count"],
            "total_units": report.payload()["total_record_count"],
            "percent_basis_points": report.payload()["progress"]["percent_basis_points"],
            "status": report.payload()["status"],
            "truncated_by_deadline": report.payload()["truncated_by_deadline"]})
    except (OSError, ValueError, PT1CapacityError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
