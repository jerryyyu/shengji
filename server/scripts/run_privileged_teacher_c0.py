#!/usr/bin/env python3
"""Run the bounded PT C0 consumer ladder on Mini's sealed PT-Full roots."""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT C0 runner requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess


def _read_single_link(path: Path, *, mode: int, label: str) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError(f"PT C0 {label} open refused") from exc
    try:
        before = os.fstat(descriptor)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = tuple(getattr(before, field) for field in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")) == \
            tuple(getattr(after, field) for field in (
                "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
        if (not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != mode
                or not stable
                or len(raw) != before.st_size):
            raise ValueError(f"PT C0 {label} identity drift")
        return raw
    finally:
        os.close(descriptor)


def _publish_exclusive(path: Path, raw: bytes) -> None:
    output = path.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("PT C0 output already exists")
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _strict_report(raw: bytes) -> dict[str, object]:
    from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PT C0 parent report is not canonical JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise ValueError("PT C0 parent report is not canonical JSON")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--parent-report", type=Path, required=True)
    parser.add_argument("--expected-parent-external-sha256", required=True)
    parser.add_argument("--expected-parent-report-sha256", required=True)
    parser.add_argument("--expected-parent-git", required=True)
    parser.add_argument("--seed-secret", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise ValueError("PT C0 runner refuses PYTHONPATH")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ValueError("PT C0 runner requires strict native mode")
    repo = Path(__file__).resolve().parents[2]
    if (_git(repo, "rev-parse", "HEAD") != args.expected_git
            or _git(repo, "status", "--porcelain", "--untracked-files=all")
            or platform.node() != "Jerrys-Mac-mini.local"):
        raise ValueError("PT C0 source or Mini host identity drift")
    ancestry = subprocess.run(
        ("git", "merge-base", "--is-ancestor", args.expected_parent_git,
         args.expected_git), cwd=repo, check=False)
    if ancestry.returncode != 0:
        raise ValueError("PT C0 source does not descend from PT-Full")
    from shengji.engine import fast
    if not fast.activate():
        raise ValueError("PT C0 runner requires active native engine")
    from shengji.rl.privileged_teacher_c0 import (
        C0Design,
        report_bytes,
        run_dev,
    )

    parent_raw = _read_single_link(
        args.parent_report, mode=0o400, label="parent report")
    parent_external = hashlib.sha256(parent_raw).hexdigest()
    if parent_external != args.expected_parent_external_sha256:
        raise ValueError("PT C0 parent external SHA-256 drift")
    parent = _strict_report(parent_raw)
    if parent.get("report_sha256") != args.expected_parent_report_sha256:
        raise ValueError("PT C0 parent internal SHA-256 drift")
    parent_design = parent.get("design")
    if (type(parent_design) is not dict
            or parent_design.get("execution_git") != args.expected_parent_git):
        raise ValueError("PT C0 parent Git drift")
    secret = _read_single_link(
        args.seed_secret, mode=0o600, label="seed secret")
    if len(secret) != 32:
        raise ValueError("PT C0 seed secret identity drift")
    design = C0Design(
        seed_commitment_sha256=hashlib.sha256(secret).hexdigest(),
        execution_git=args.expected_git,
        native_sha256=hashlib.sha256(
            Path(fast._fast.__file__).read_bytes()).hexdigest(),
        hostname="Jerrys-Mac-mini.local",
        parent_external_sha256=parent_external,
        parent_report_sha256=args.expected_parent_report_sha256,
        parent_execution_git=args.expected_parent_git,
    )

    def progress(row: dict[str, object]) -> None:
        print("PT_C0_PROGRESS " + json.dumps(
            row, sort_keys=True, separators=(",", ":")), flush=True)

    report = run_dev(
        design, parent_report=parent, seed_secret=secret,
        workers=args.workers, progress_sink=progress,
        parent_external_sha256=parent_external)
    raw = report_bytes(
        report, design, parent,
        parent_external_sha256=parent_external)
    _publish_exclusive(args.out, raw)
    print(json.dumps({
        "status": report["status"],
        "completed_roots": report["completed_roots"],
        "record_count": report["record_count"],
        "played_round_count": report["played_round_count"],
        "report_sha256": report["report_sha256"],
        "output": str(args.out.resolve()),
        "scientific_execution_authorized": False,
        "strength_claim_authorized": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
