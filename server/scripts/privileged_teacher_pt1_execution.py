#!/usr/bin/env python3
"""Freeze, initialize, execute/resume, and verify the PT1 scientific lane."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys


def _require_isolated_runtime() -> None:
    if (not sys.flags.safe_path or not sys.dont_write_bytecode
            or os.environ.get("PYTHONPATH")):
        raise RuntimeError("PT1 execution requires Python -P -B and no PYTHONPATH")


def _load():
    from shengji.rl import privileged_teacher_pt1_execution as execution
    from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
    return execution, canonical_json_bytes


def _private_bytes(path: Path, label: str) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o400):
        raise RuntimeError(f"{label} must be regular mode 0400 nlink 1")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "initialize", "run",
                                              "resume", "verify"))
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--freeze-output", type=Path)
    parser.add_argument("--capacity-report", type=Path)
    parser.add_argument("--capacity-manifest", type=Path)
    parser.add_argument("--scientific-secret-commitment")
    parser.add_argument("--capture-secret", type=Path)
    parser.add_argument("--review-marker", type=Path)
    parser.add_argument("--review-commit")
    parser.add_argument("--design-sha256")
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--deadline-nanoseconds", type=int)
    parser.add_argument("--worker-count", type=int, default=10)
    parser.add_argument("--resume-allowed", action="store_true")
    args = parser.parse_args(argv)
    execution = None
    try:
        _require_isolated_runtime()
        execution, canonical = _load()
        if args.command == "freeze":
            required = (args.capacity_report, args.capacity_manifest,
                        args.scientific_secret_commitment,
                        args.design_sha256, args.evidence_root)
            if any(value is None for value in required) or args.freeze_output is None:
                raise execution.PT1ExecutionError(
                    "freeze requires design, capacity, marker, commitment, evidence root")
            report = args.capacity_report.read_bytes()
            manifest = __import__("json").loads(args.capacity_manifest.read_bytes())
            freeze = execution.freeze_execution(
                design_sha256=args.design_sha256,
                scientific_capture_secret_sha256=args.scientific_secret_commitment,
                capacity_report=report, capacity_manifest=manifest,
                review_marker=(args.review_marker.read_bytes()
                               if args.review_marker is not None else None),
                evidence_root=args.evidence_root,
                deadline_nanoseconds=args.deadline_nanoseconds,
                worker_count=args.worker_count,
                resume_allowed=args.resume_allowed)
            execution._write_once(args.freeze_output, freeze.canonical_bytes())
            return 0
        if args.output_root is None:
            raise execution.PT1ExecutionError("--output-root is required")
        if args.freeze is None:
            raise execution.PT1ExecutionError("--freeze is required")
        freeze = execution.verify_freeze(args.freeze.read_bytes())
        if args.command == "initialize":
            if args.review_marker is None or args.review_commit is None:
                raise execution.PT1ExecutionError(
                    "--review-marker and --review-commit are required")
            execution.initialize_execution(
                freeze, args.output_root,
                review_marker=_private_bytes(args.review_marker, "review marker"),
                review_commit=args.review_commit)
            return 0
        if args.command == "verify":
            if (args.review_marker is None or args.capture_secret is None
                    or args.review_commit is None):
                raise execution.PT1ExecutionError(
                    "--review-marker, --review-commit and --capture-secret are required")
            execution.verify_execution(
                args.output_root, freeze, capture_secret=_private_bytes(
                    args.capture_secret, "capture secret"),
                review_marker=_private_bytes(args.review_marker, "review marker"),
                review_commit=args.review_commit)
            return 0
        if args.capture_secret is None:
            raise execution.PT1ExecutionError("--capture-secret is required")
        if args.review_marker is None or args.review_commit is None:
            raise execution.PT1ExecutionError(
                "--review-marker and --review-commit are required")
        if args.command == "resume" and freeze.resume_allowed is not True:
            raise execution.PT1ExecutionError("freeze does not authorize resume")
        secret = _private_bytes(args.capture_secret, "capture secret")
        if args.deadline_nanoseconds is not None:
            raise execution.PT1ExecutionError(
                "run/resume cannot override the frozen deadline")
        execution.run_execution(freeze, output_root=args.output_root,
                                capture_secret=secret,
                                review_marker=(_private_bytes(args.review_marker,
                                                              "review marker")
                                               if args.review_marker is not None else None),
                                review_commit=args.review_commit,
                                deadline=None)
        return 0
    except Exception as exc:
        if execution is not None and not isinstance(
                exc, (OSError, ValueError, RuntimeError,
                      execution.PT1ExecutionError)):
            raise
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
