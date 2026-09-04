#!/usr/bin/env python3
"""Collect PT-Luna teacher games, or verify a sealed run root.

    luna collect --games N --seed-secret FILE --token-ceiling T --out ROOT
                 [--workers W] [--codex-binary P]
                 [--per-game-deadline-seconds S] [--wall-seconds S]
                 [--per-call-wall-reserve-ms MS]
                 [--per-game-token-cap T] [--per-call-token-reserve T]
    luna verify ROOT --seed-secret FILE

``collect`` derives the schedule and census from the seed secret, stamps
the runtime, and runs the supervisor under ROOT/private (0700) and
ROOT/public (0755); the sealed result is ROOT/public/terminal.json.  A
second ``collect`` on the same root reopens the sealed run instead of
dispatching.  ``verify`` rebuilds that terminal from the private
artifacts and the seed secret alone.  Both print one JSON line; the exit
status is 0 for a complete population and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.rl.privileged_teacher_luna_rpc_runtime import (  # noqa: E402
    source_identity,
)
from shengji.rl.privileged_teacher_luna_rpc_supervisor import (  # noqa: E402
    COMPLETE_STATE_SOURCE_ACQUISITION,
    DEFAULT_GAME_DEADLINE_SECONDS,
    DEFAULT_PER_CALL_TOKEN_RESERVE,
    DEFAULT_PER_CALL_WALL_RESERVE_MS,
    DEFAULT_PER_GAME_TOKEN_CAP,
    DEFAULT_WALL_SECONDS,
    DEFAULT_WORKERS,
    PTLunaRPCSupervisor,
    schedule_for_games,
    verify_run,
)


def _secret(path: Path) -> bytes:
    """Read exactly 32 secret bytes from a private, single-link regular file."""
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
        raise ValueError("seed secret must be a private 32-byte file")
    return raw


def _codex_binary(value: str) -> Path:
    resolved = shutil.which(value) if Path(value).name == value else value
    if resolved is None or not Path(resolved).is_file():
        raise ValueError(f"codex binary not found: {value}")
    return Path(resolved).resolve()


def _summary(result, root: Path) -> dict[str, object]:
    receipt = result.receipt
    return {"route": result.route,
            "receipt_sha256": receipt["receipt_sha256"],
            "completed_games": receipt["completed_games"],
            "failed_games": receipt["failed_games"],
            "pending_games": receipt["pending_games"],
            "resource_totals": receipt["resource_totals"],
            "terminal": str(Path(root) / "public" / "terminal.json")}


def collect(args: argparse.Namespace) -> int:
    secret = _secret(args.seed_secret)
    codex_binary = _codex_binary(args.codex_binary)
    root = Path(args.out)
    schedule = schedule_for_games(secret, args.games)
    runtime = source_identity(codex_binary)
    root.mkdir(parents=True, exist_ok=True)
    supervisor = PTLunaRPCSupervisor(
        seed_secret=secret, private_root=root / "private",
        public_root=root / "public", runtime=runtime, schedule=schedule,
        codex_binary=codex_binary, workers=args.workers,
        token_cap=args.token_ceiling,
        per_game_token_cap=args.per_game_token_cap,
        per_call_token_reserve=args.per_call_token_reserve,
        per_call_wall_reserve_milliseconds=args.per_call_wall_reserve_ms,
        per_game_deadline_seconds=args.per_game_deadline_seconds,
        wall_seconds=args.wall_seconds)
    result = supervisor.run()
    print(json.dumps(_summary(result, root), sort_keys=True))
    return 0 if result.route == COMPLETE_STATE_SOURCE_ACQUISITION else 1


def verify(args: argparse.Namespace) -> int:
    secret = _secret(args.seed_secret)
    result = verify_run(Path(args.root), seed_secret=secret)
    print(json.dumps(_summary(result, Path(args.root)), sort_keys=True))
    return 0 if result.route == COMPLETE_STATE_SOURCE_ACQUISITION else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luna", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("collect", help="collect N games into ROOT")
    run.add_argument("--games", type=int, required=True,
                     help="even game count; N // 2 clusters, both mirrors")
    run.add_argument("--seed-secret", type=Path, required=True,
                     help="private file holding exactly 32 secret bytes")
    run.add_argument("--token-ceiling", type=int, required=True,
                     help="shared token cap for the whole run")
    run.add_argument("--out", type=Path, required=True,
                     help="run root; ROOT/private and ROOT/public are created")
    run.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    run.add_argument("--codex-binary", default="codex")
    run.add_argument("--per-game-deadline-seconds", type=int,
                     default=DEFAULT_GAME_DEADLINE_SECONDS)
    run.add_argument("--wall-seconds", type=int, default=DEFAULT_WALL_SECONDS)
    run.add_argument("--per-call-wall-reserve-ms", type=int,
                     default=DEFAULT_PER_CALL_WALL_RESERVE_MS)
    run.add_argument("--per-game-token-cap", type=int,
                     default=DEFAULT_PER_GAME_TOKEN_CAP,
                     help="a game exceeding this is refused on its own")
    run.add_argument("--per-call-token-reserve", type=int,
                     default=DEFAULT_PER_CALL_TOKEN_RESERVE,
                     help="tokens reserved per provider call; a larger "
                          "response refuses only that game")
    run.set_defaults(handler=collect)
    check = commands.add_parser("verify", help="reopen and rebuild a sealed run")
    check.add_argument("root", type=Path)
    check.add_argument("--seed-secret", type=Path, required=True)
    check.set_defaults(handler=verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
