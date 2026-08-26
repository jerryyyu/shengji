#!/usr/bin/env python3
"""Freeze, execute, and verify one reviewed PT1 terminal-only recovery."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys


def _require_isolated_runtime() -> None:
    if (not sys.flags.safe_path or not sys.dont_write_bytecode
            or os.environ.get("PYTHONPATH")):
        raise RuntimeError("PT1 recovery requires Python -P -B and no PYTHONPATH")


def _private_bytes(path: Path, label: str) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o400):
        raise RuntimeError(f"{label} must be regular mode 0400 nlink 1")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "verify"))
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--recovery-root", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--freeze-output", type=Path)
    parser.add_argument("--source-review-commit")
    parser.add_argument("--review-marker", type=Path)
    parser.add_argument("--review-commit")
    args = parser.parse_args(argv)
    try:
        _require_isolated_runtime()
        from shengji.rl import privileged_teacher_pt1_recovery as recovery
        from shengji.rl.privileged_teacher_pt1_execution import _write_once
        if args.command == "freeze":
            if (args.source_root is None or args.recovery_root is None
                    or args.freeze_output is None
                    or args.source_review_commit is None):
                raise recovery.PT1RecoveryError(
                    "freeze requires source/recovery roots, output and source review")
            typed = recovery.freeze_terminal_recovery(
                source_evidence_root=args.source_root,
                recovery_evidence_root=args.recovery_root,
                source_review_commit=args.source_review_commit,
                review_marker=(_private_bytes(args.review_marker, "review marker")
                               if args.review_marker is not None else None))
            _write_once(args.freeze_output, typed.canonical_bytes())
            return 0
        if (args.freeze is None or args.recovery_root is None
                or args.review_marker is None or args.review_commit is None):
            raise recovery.PT1RecoveryError(
                "run/verify require freeze, recovery root, marker and review commit")
        typed = recovery.verify_recovery_freeze(
            _private_bytes(args.freeze, "recovery freeze"))
        marker = _private_bytes(args.review_marker, "review marker")
        if args.command == "run":
            recovery.run_terminal_recovery(
                typed, review_marker=marker, review_commit=args.review_commit)
        else:
            recovery.verify_terminal_recovery(
                args.recovery_root, typed, review_marker=marker,
                review_commit=args.review_commit)
        return 0
    except Exception as exc:
        print("PT1_TERMINAL_RECOVERY_FAILED", file=sys.stderr, flush=True)
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
