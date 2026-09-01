#!/usr/bin/env python3
"""Build or execute the immutable PT-Luna turn-RPC collection freeze."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl.privileged_teacher_luna_rpc_io import publish_exclusive_bytes
from shengji.rl.privileged_teacher_luna_rpc_capacity import (
    source_identity, validate_capacity_receipt,
)
from shengji.rl.privileged_teacher_luna_rpc_collection import (
    RPCGameAttemptRunner, ScientificBudgetLedger,
)
from shengji.rl.privileged_teacher_luna_rpc_supervisor import (
    FREEZE_REVIEW_PREFIX, SOURCE_REVIEW_PREFIX,
    RPCSupervisorError, run_population,
    authenticate_review_claim, freeze_review_claim,
    launch_freeze_payload, source_review_claim, validate_launch_freeze,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


def _read(path: Path) -> dict[str, object]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if info.st_size > 64 << 20:
                raise ValueError(f"artifact size refused: {path}")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError(f"artifact read refused: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or stat.S_IMODE(info.st_mode) & 0o222:
        raise ValueError(f"artifact identity refused: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"artifact JSON refused: {path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ValueError(f"artifact canonical bytes refused: {path}")
    return value


def _secret(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            raw = os.read(descriptor, 33)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError("seed secret read refused") from exc
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or stat.S_IMODE(info.st_mode) & 0o077 \
            or any(getattr(info, key) != getattr(after, key)
                   for key in identity) \
            or len(raw) != 32:
        raise ValueError("seed secret identity drift")
    return raw


def _publish(path: Path, payload: object, *, private: bool) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"output slot occupied: {path}")
    path.parent.mkdir(mode=0o700 if private else 0o755,
                      parents=True, exist_ok=True)
    parent_info = path.parent.stat(follow_symlinks=False)
    if path.parent.is_symlink() or not stat.S_ISDIR(parent_info.st_mode) \
            or (private and (parent_info.st_uid != os.getuid()
                             or stat.S_IMODE(parent_info.st_mode) != 0o700)):
        raise ValueError(f"output parent identity refused: {path.parent}")
    publish_exclusive_bytes(
        path, canonical_json_bytes(payload), mode=0o400 if private else 0o444)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source-review-claim")
    source.add_argument("--repo-root", type=Path, required=True)
    freeze_claim = commands.add_parser("freeze-review-claim")
    freeze_claim.add_argument("--freeze", type=Path, required=True)
    build = commands.add_parser("build-freeze")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--seed-secret-file", type=Path, required=True)
    build.add_argument("--capacity-receipt", type=Path, required=True)
    build.add_argument("--codex-binary", type=Path, required=True)
    build.add_argument("--private-root", type=Path, required=True)
    build.add_argument("--public-root", type=Path, required=True)
    build.add_argument("--namespace", required=True)
    build.add_argument("--freeze-output", type=Path, required=True)
    build.add_argument("--census-output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--repo-root", type=Path, required=True)
    run.add_argument("--seed-secret-file", type=Path, required=True)
    run.add_argument("--capacity-receipt", type=Path, required=True)
    run.add_argument("--codex-binary", type=Path, required=True)
    run.add_argument("--private-root", type=Path, required=True)
    run.add_argument("--public-root", type=Path, required=True)
    run.add_argument("--namespace", required=True)
    run.add_argument("--freeze", type=Path, required=True)
    run.add_argument("--census", type=Path, required=True)
    run.add_argument("--review-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "source-review-claim":
        print(canonical_json_bytes(
            source_review_claim(args.repo_root)).decode(), end="")
        return 0
    if args.command == "freeze-review-claim":
        print(canonical_json_bytes(
            freeze_review_claim(_read(args.freeze))).decode(), end="")
        return 0
    secret = _secret(args.seed_secret_file)
    capacity = _read(args.capacity_receipt)
    validate_capacity_receipt(capacity)
    source_auth = authenticate_review_claim(
        claim=source_review_claim(args.repo_root),
        prefix=SOURCE_REVIEW_PREFIX,
        review_commit=capacity["source_review"]["review_commit"])
    if source_auth != capacity["source_review"]:
        raise RPCSupervisorError("capacity source review authentication drift")
    runtime = source_identity(args.codex_binary)
    if runtime != capacity["runtime"]:
        raise RPCSupervisorError("live runtime differs from capacity")
    census = selfplay.root_census(secret).serialized()
    if args.command == "build-freeze":
        freeze = launch_freeze_payload(
            repo_root=args.repo_root, seed_secret=secret, census=census,
            capacity_receipt=capacity, runtime=runtime,
            private_root=args.private_root, public_root=args.public_root,
            namespace=args.namespace)
        _publish(args.census_output, census, private=True)
        _publish(args.freeze_output, freeze, private=False)
        print(canonical_json_bytes({
            "freeze_sha256": freeze["freeze_sha256"],
            "census_sha256": census["census_sha256"]}).decode(), end="")
        return 0
    freeze = _read(args.freeze)
    stored_census = _read(args.census)
    if stored_census != census:
        raise RPCSupervisorError("scientific census drift")
    validate_launch_freeze(
        freeze, repo_root=args.repo_root, seed_secret=secret,
        census=census, capacity_receipt=capacity, runtime=runtime,
        private_root=args.private_root, public_root=args.public_root,
        namespace=args.namespace)
    review = authenticate_review_claim(
        claim=freeze_review_claim(freeze), prefix=FREEZE_REVIEW_PREFIX,
        review_commit=args.review_commit)
    receipt = run_population(
        seed_secret=secret, private_root=args.private_root,
        public_root=args.public_root, runtime=runtime,
        admission=review, capacity_receipt=capacity,
        codex_binary=args.codex_binary,
        launch_freeze=freeze,
        root_census=census,
        per_call_token_reserve=freeze["per_call_token_reserve"],
        per_call_wall_reserve_milliseconds=
            freeze["per_call_wall_reserve_milliseconds"],
        ledger_namespace=args.namespace,
        workers=freeze["selected_workers"])
    print(canonical_json_bytes({
        "route": receipt["route"],
        "receipt_sha256": receipt["receipt_sha256"]}).decode(), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
