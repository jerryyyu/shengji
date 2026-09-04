#!/usr/bin/env python3
"""Collect PT-Luna teacher games, or verify a sealed run root.

    luna collect --games N --token-ceiling T --out ROOT [--seed-secret FILE]
                 [--workers W] [--codex-binary P]
                 [--per-game-deadline-seconds S] [--wall-seconds S]
                 [--per-call-wall-reserve-ms MS]
                 [--per-game-token-cap T] [--per-call-token-reserve T]
    luna verify ROOT [--seed-secret FILE]

``collect`` derives the schedule and census from the seed secret, stamps
the runtime, and runs the supervisor under ROOT/private (0700) and
ROOT/public (0755); the sealed result is ROOT/public/terminal.json.  The
census must cover every trump mode with 52 unique roots, which is a
property of the secret rather than of the run: a supplied ``--seed-secret``
that does not cover is refused before any runtime, ledger, or attempt is
set up and before any token is spent, and when the flag is omitted
``collect`` draws fresh 32-byte secrets until one covers, then seals it as
ROOT/private/seed_secret (0400) before any game starts.  A second
``collect`` on the same root reopens the sealed run instead of
dispatching, reading that file when the flag is omitted.  ``verify``
rebuilds the terminal from the private artifacts and the seed secret
alone, likewise reading ROOT/private/seed_secret when the flag is omitted.
Both print one JSON line (including ``seed_secret_path``); the exit status
is 0 for a complete population and 1 otherwise.
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

from shengji.luna import game as selfplay  # noqa: E402
from shengji.luna.atomic_io import (  # noqa: E402
    AtomicPublishError,
    partial_path,
    promote_partial,
    publish_exclusive_bytes,
    recover_linked_partial,
)
from shengji.luna.runtime import (  # noqa: E402
    source_identity,
)
from shengji.luna.supervisor import (  # noqa: E402
    COMPLETE_STATE_SOURCE_ACQUISITION,
    DEFAULT_GAME_DEADLINE_SECONDS,
    DEFAULT_PER_CALL_TOKEN_RESERVE,
    DEFAULT_PER_CALL_WALL_RESERVE_MS,
    DEFAULT_PER_GAME_TOKEN_CAP,
    DEFAULT_WALL_SECONDS,
    DEFAULT_WORKERS,
    PTLunaRPCSupervisor,
    _mkdir_private,
    schedule_for_games,
    verify_run,
)


SEED_SECRET_NAME = "seed_secret"
SEED_DRAW_ATTEMPTS = 256


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


def _seed_secret_path(root: Path) -> Path:
    return Path(root) / "private" / SEED_SECRET_NAME


def _census_shortfall(secret: bytes) -> str | None:
    """Say why ``secret`` fails the supervisor's root census, or ``None``.

    The verdict is the supervisor's own: ``schedule_for_games`` builds the
    census through ``root_census``, which refuses unless the 52 fresh roots
    are unique and every trump mode appears.  Only the diagnostic (modes
    covered, unique roots) is computed here, and only after a refusal.
    """
    try:
        selfplay.root_census(secret)
    except selfplay.PrivilegedTeacherLunaSelfPlayError as exc:
        coordinates = selfplay.LunaDesign().root_coordinates
        modes: set[str] = set()
        roots: set[str] = set()
        for coordinate in coordinates:
            root = selfplay.build_root(secret, coordinate)
            modes.add(selfplay.root_trump_mode(root))
            roots.add(selfplay.root_identity(root))
        covered = ",".join(m for m in selfplay.TRUMP_MODES if m in modes)
        missing = ",".join(m for m in selfplay.TRUMP_MODES if m not in modes)
        return (f"{exc}; trump modes covered {covered or 'none'}, "
                f"missing {missing or 'none'}; "
                f"{len(roots)}/{len(coordinates)} unique roots")
    return None


def _require_coverage(secret: bytes, path: Path) -> None:
    """Refuse a supplied secret whose census the supervisor would refuse."""
    shortfall = _census_shortfall(secret)
    if shortfall is not None:
        raise ValueError(
            f"seed secret {path} does not cover the root census ({shortfall});"
            " omit --seed-secret so collect draws a covering secret into"
            " ROOT/private/seed_secret, or supply another")


def _fresh_secret() -> bytes:
    return os.urandom(32)


def _draw_covering_secret() -> bytes:
    """Draw fresh 32-byte secrets until one covers the root census."""
    shortfall = None
    for _attempt in range(SEED_DRAW_ATTEMPTS):
        secret = _fresh_secret()
        shortfall = _census_shortfall(secret)
        if shortfall is None:
            return secret
    raise ValueError(
        f"no covering seed secret in {SEED_DRAW_ATTEMPTS} draws"
        f" (last: {shortfall}); the root census cannot be covered under"
        " this engine build")


def _refuse_used_root(root: Path) -> None:
    """Never draw a fresh secret into a root that already holds a run."""
    private_root = Path(root) / "private"
    if not (private_root.exists() or private_root.is_symlink()):
        return
    try:
        entries = os.listdir(private_root)
    except OSError as exc:
        raise ValueError(f"private run root {private_root} unreadable") from exc
    if entries:
        raise ValueError(
            f"run root {root} already holds private artifacts but no"
            f" private/{SEED_SECRET_NAME}; supply --seed-secret for it")


def _recover_sealed_secret(root: Path) -> bytes | None:
    """Return the run's sealed secret, finishing an interrupted seal first.

    The seal is ``publish_exclusive_bytes``: stage ``.seed_secret.partial``,
    fsync, link it to ``seed_secret``, unlink the stage.  A death inside it
    leaves one of two recoverable states -- only the staged file (complete
    bytes, never linked) or both names on one two-link inode -- and both
    are finished here with the publisher's own helpers.  Anything else is
    left to the generic used-root refusal.  Returns ``None`` when neither
    name exists.
    """
    sealed = _seed_secret_path(root)
    staged = partial_path(sealed)
    final_present = sealed.exists() or sealed.is_symlink()
    staged_present = staged.exists() or staged.is_symlink()
    if not final_present and not staged_present:
        return None
    if final_present and staged_present:
        try:
            recover_linked_partial(sealed, mode=0o400)
        except AtomicPublishError as exc:
            raise ValueError(
                f"seed secret seal recovery refused: {sealed}") from exc
        return _secret(sealed)
    if staged_present:
        others = sorted(set(os.listdir(sealed.parent)) - {staged.name})
        if others:
            raise ValueError(
                f"run root {root} holds a staged seed secret beside other"
                f" private artifacts {others}; supply --seed-secret for it")
        try:
            raw = _secret(staged)
        except ValueError as exc:
            raise ValueError(
                f"staged seed secret {staged} is not a complete private"
                " 32-byte file; remove it so collect can draw a fresh"
                " secret") from exc
        _require_coverage(raw, staged)
        try:
            promote_partial(sealed, raw, mode=0o400)
        except AtomicPublishError as exc:
            raise ValueError(
                f"seed secret seal recovery refused: {sealed}") from exc
        if _secret(sealed) != raw:
            raise ValueError(f"seed secret publication drift: {sealed}")
        return raw
    return _secret(sealed)


def _publish_seed_secret(path: Path, secret: bytes) -> None:
    """Seal a drawn secret as a private 0400 file before any game starts."""
    _mkdir_private(path.parent, "private supervisor root")
    try:
        publish_exclusive_bytes(path, secret, mode=0o400)
    except AtomicPublishError as exc:
        raise ValueError(f"seed secret publication refused: {path}") from exc
    if _secret(path) != secret:
        raise ValueError(f"seed secret publication drift: {path}")


def _codex_binary(value: str) -> Path:
    resolved = shutil.which(value) if Path(value).name == value else value
    if resolved is None or not Path(resolved).is_file():
        raise ValueError(f"codex binary not found: {value}")
    return Path(resolved).resolve()


def _summary(result, root: Path, seed_secret_path: Path) -> dict[str, object]:
    receipt = result.receipt
    return {"route": result.route,
            "receipt_sha256": receipt["receipt_sha256"],
            "completed_games": receipt["completed_games"],
            "failed_games": receipt["failed_games"],
            "pending_games": receipt["pending_games"],
            "resource_totals": receipt["resource_totals"],
            "seed_secret_path": str(seed_secret_path),
            "terminal": str(Path(root) / "public" / "terminal.json")}


def collect(args: argparse.Namespace) -> int:
    root = Path(args.out)
    sealed_path = _seed_secret_path(root)
    drawn = None
    if args.seed_secret is not None:
        seed_path = args.seed_secret
        secret = _secret(seed_path)
        _require_coverage(secret, seed_path)
    else:
        seed_path = sealed_path
        secret = _recover_sealed_secret(root)
        if secret is None:
            _refuse_used_root(root)
            secret = drawn = _draw_covering_secret()
    codex_binary = _codex_binary(args.codex_binary)
    schedule = schedule_for_games(secret, args.games)
    runtime = source_identity(codex_binary)
    root.mkdir(parents=True, exist_ok=True)
    if drawn is not None:
        _publish_seed_secret(sealed_path, drawn)
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
    print(json.dumps(_summary(result, root, seed_path), sort_keys=True))
    return 0 if result.route == COMPLETE_STATE_SOURCE_ACQUISITION else 1


def verify(args: argparse.Namespace) -> int:
    root = Path(args.root)
    seed_path = args.seed_secret
    if seed_path is None:
        seed_path = _seed_secret_path(root)
        if not (seed_path.exists() or seed_path.is_symlink()):
            raise ValueError(
                f"verify needs --seed-secret: {seed_path} does not exist")
    secret = _secret(seed_path)
    result = verify_run(root, seed_secret=secret)
    print(json.dumps(_summary(result, root, seed_path), sort_keys=True))
    return 0 if result.route == COMPLETE_STATE_SOURCE_ACQUISITION else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luna", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("collect", help="collect N games into ROOT")
    run.add_argument("--games", type=int, required=True,
                     help="even game count; N // 2 clusters, both mirrors")
    run.add_argument("--seed-secret", type=Path, default=None,
                     help="private file holding exactly 32 secret bytes; when "
                          "omitted, collect draws a secret whose census covers "
                          "every trump mode and seals it as "
                          "ROOT/private/seed_secret (0400)")
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
    check.add_argument("--seed-secret", type=Path, default=None,
                       help="defaults to ROOT/private/seed_secret")
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
