"""Build an inert Value-Afterstate V2 freeze from existing inputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shengji.rl.world_afterstate_v2_freeze_builder import (
    build_execution_freeze, publish_freeze,
)


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
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, default=12 * 60 * 60)
    parser.add_argument("--heartbeat-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path,
                        help="explicit new freeze file to publish")
    args = parser.parse_args(argv)
    freeze = build_execution_freeze(
        args.repo, args.source_git, args.protocol, args.capacity,
        args.population, args.config, args.seed,
        args.continuation_policy, args.evidence_root,
        args.deadline_seconds, args.heartbeat_seconds)
    if args.out is not None:
        publish_freeze(args.out, freeze)
    else:
        sys.stdout.buffer.write(freeze.canonical_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
