"""Build an inert Value-Afterstate V2 freeze from existing inputs."""

from __future__ import annotations

import os
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 freeze builder requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 freeze builder refuses PYTHONPATH")


def _require_runtime_environment() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise RuntimeError(
            "Value V2 requires SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")

from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if not sys.path or sys.path[0] != str(SERVER):
    sys.path.insert(0, str(SERVER))


def _preimport_bytecode_scan(
        prefixes: tuple[Path, ...] | None = None) -> None:
    """Refuse ignored bytecode before importing any project module."""
    roots = prefixes or (SERVER / "scripts", SERVER / "shengji")
    for prefix in roots:
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 freeze source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc")
                                              for name in files):
                raise RuntimeError(
                    "Value V2 freeze builder refuses source bytecode artifacts")


if __name__ == "__main__":
    _require_runtime_environment()
    _preimport_bytecode_scan()

import argparse  # noqa: E402

from shengji.rl import world_afterstate_v2_freeze_builder as _builder_module  # noqa: E402
from shengji.rl.world_afterstate_v2_freeze_builder import (
    build_execution_freeze, publish_freeze,
)  # noqa: E402
from shengji.rl.world_afterstate_v2_execution import (  # noqa: E402
    MAX_DEADLINE_SECONDS,
)


try:
    Path(_builder_module.__file__).resolve(strict=True).relative_to(
        SERVER.resolve(strict=True))
except (OSError, TypeError, ValueError) as exc:
    raise RuntimeError("Value V2 freeze builder module origin drift") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-git", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--capacity", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--continuation-policy", type=Path, required=True)
    parser.add_argument("--population-rehearsal", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int,
                        default=MAX_DEADLINE_SECONDS)
    parser.add_argument("--heartbeat-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path,
                        help="explicit new freeze file to publish")
    args = parser.parse_args(argv)
    freeze = build_execution_freeze(
        args.repo, args.source_git, args.protocol, args.capacity,
        args.population, args.config, args.seed,
        args.continuation_policy, args.evidence_root,
        args.deadline_seconds, args.heartbeat_seconds,
        population_rehearsal_path=args.population_rehearsal)
    if args.out is not None:
        publish_freeze(args.out, freeze)
    else:
        sys.stdout.buffer.write(freeze.canonical_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
