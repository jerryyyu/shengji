#!/usr/bin/env python3
"""Run the bounded PT-Full A/A0/B open-DEV diagnostic on Mini."""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT-Full runner requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess


def _publish_exclusive(path: Path, raw: bytes) -> None:
    output = path.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("PT-Full output already exists")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise


def _seed_secret(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError("PT-Full seed secret open refused") from exc
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 33)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or len(raw) != 32):
            raise ValueError("PT-Full seed secret identity drift")
        return raw
    finally:
        os.close(descriptor)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--seed-secret", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise ValueError("PT-Full runner refuses PYTHONPATH")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ValueError("PT-Full runner requires strict native mode")
    repo = Path(__file__).resolve().parents[2]
    if (_git(repo, "rev-parse", "HEAD") != args.expected_git
            or _git(repo, "status", "--porcelain", "--untracked-files=all")
            or platform.node() != "Jerrys-Mac-mini.local"):
        raise ValueError("PT-Full source or Mini host identity drift")
    from shengji.engine import fast
    if not fast.activate():
        raise ValueError("PT-Full runner requires active native engine")
    from shengji.rl.privileged_teacher_full_ab import (
        FullABDesign,
        report_bytes,
        run_dev,
    )

    def progress(row: dict[str, object]) -> None:
        print("PT_FULL_PROGRESS " + json.dumps(
            row, sort_keys=True, separators=(",", ":")), flush=True)

    secret = _seed_secret(args.seed_secret)
    design = FullABDesign(
        seed_commitment_sha256=hashlib.sha256(secret).hexdigest(),
        execution_git=args.expected_git,
        native_sha256=hashlib.sha256(
            Path(fast._fast.__file__).read_bytes()).hexdigest(),
        hostname="Jerrys-Mac-mini.local",
    )
    report = run_dev(
        design, seed_secret=secret, workers=args.workers,
        progress_sink=progress)
    raw = report_bytes(report, design)
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
