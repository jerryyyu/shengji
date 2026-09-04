#!/usr/bin/env python3
"""Launch one reviewed score-free PT-Luna RPC capacity census."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import sys

from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl.privileged_teacher_luna_rpc_io import publish_exclusive_bytes
from shengji.rl.privileged_teacher_luna_rpc_capacity import (
    RPCConcurrency,
    RealGameRunner,
    run_capacity,
    source_identity,
    validate_canary_receipt,
)
from shengji.rl.privileged_teacher_luna_rpc_supervisor import (
    SOURCE_REVIEW_PREFIX, authenticate_review_claim, source_review_claim,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


def _publish(path: Path, payload: object) -> None:
    publish_exclusive_bytes(path, canonical_json_bytes(payload))


def _physical_memory() -> int:
    result = subprocess.run(
        ("/usr/sbin/sysctl", "-n", "hw.memsize"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=5)
    if result.returncode != 0 or result.stderr:
        raise ValueError("physical memory probe failed")
    return int(result.stdout.decode("ascii").strip())


def _read_canary(path: Path) -> dict[str, object]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError("canary receipt read refused") from exc
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o222
            or any(getattr(before, key) != getattr(after, key)
                   for key in identity)):
        raise ValueError("canary receipt identity drift")
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ValueError("canary receipt canonical bytes drift")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-review-commit", required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--canary-receipt", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capacity-wall-seconds", type=int, default=14_400)
    parser.add_argument("--capacity-token-budget", type=int,
                        default=1_000_000_000)
    parser.add_argument("--scientific-wall-seconds", type=int, default=28_800)
    parser.add_argument("--scientific-token-budget", type=int,
                        default=1_000_000_000)
    parser.add_argument("--per-game-deadline-seconds", type=int, default=1_200)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("capacity output slot occupied")
    review = authenticate_review_claim(
        claim=source_review_claim(args.repo_root),
        prefix=SOURCE_REVIEW_PREFIX,
        review_commit=args.source_review_commit)
    if args.work_root.exists() and any(args.work_root.iterdir()):
        raise ValueError("capacity work namespace occupied")
    args.work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret = os.urandom(32)
    commitment = hashlib.sha256(secret).hexdigest()
    runtime = source_identity(args.codex_binary)
    canary = _read_canary(args.canary_receipt)
    canary_sha = validate_canary_receipt(
        canary, expected_runtime=runtime)
    if canary["source_review"] != review:
        raise ValueError("capacity source review binding drift")
    attempt = {"schema": "pt-luna-turn-rpc-capacity-attempt-v1",
               "secret_commitment_sha256": commitment,
               "canary_receipt_sha256": canary_sha,
               "source_review": review,
               "runtime": runtime,
               "capacity_wall_seconds": args.capacity_wall_seconds,
               "capacity_token_budget": args.capacity_token_budget,
               "scientific_wall_seconds": args.scientific_wall_seconds,
               "scientific_token_budget": args.scientific_token_budget,
               "per_game_deadline_seconds": args.per_game_deadline_seconds,
               "authority": dict(selfplay.AUTHORITY)}
    _publish(args.work_root / "attempt.json", attempt)
    def progress(row):
        print(canonical_json_bytes(row).decode(), end="", flush=True)
    def arm(row):
        body = {"schema": "pt-luna-turn-rpc-capacity-arm-checkpoint-v1",
                "arm": dict(row)}
        payload = {**body, "checkpoint_sha256": hashlib.sha256(
            canonical_json_bytes(body)).hexdigest()}
        _publish(args.work_root / f"arm-{row['workers']}.json", payload)
    result = run_capacity(
        canary_receipt=canary,
        capacity_secret=secret, codex_binary=args.codex_binary,
        temp_root=args.work_root, per_call_timeout_seconds=90,
        runtime=runtime,
        secret_commitment_sha256=commitment,
        source_review=review,
        per_game_deadline_ns=args.per_game_deadline_seconds * 1_000_000_000,
        physical_memory_bytes=_physical_memory(),
        capacity_wall_ns=args.capacity_wall_seconds * 1_000_000_000,
        capacity_token_budget=args.capacity_token_budget,
        scientific_wall_ns=args.scientific_wall_seconds * 1_000_000_000,
        scientific_token_budget=args.scientific_token_budget,
        progress_sink=progress, arm_sink=arm)
    _publish(args.output, result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"schema": "pt-luna-turn-rpc-capacity-failure-v1",
                          "failure_kind": type(exc).__name__,
                          "authority": selfplay.AUTHORITY}), file=sys.stderr)
        raise
