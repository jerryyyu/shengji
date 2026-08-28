#!/usr/bin/env python3
"""Publish one immutable, score-free V0 capacity receipt."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_capacity import (run_capacity,
                                                   validate_capacity_receipt)


def _publish(path: Path, raw: bytes) -> None:
    target = path.resolve()
    partial = target.with_name(f".{target.name}.partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise FileExistsError("capacity output namespace is occupied")
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(partial, 0o400)
    os.link(partial, target)
    partial.unlink()
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--out", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--fixture-count", type=int, default=26)
    value.add_argument("--workers", type=int, nargs="+",
                       default=[1, 2, 4, 8, 16])
    value.add_argument("--worker-repetitions", type=int, default=2)
    value.add_argument("--batch-sizes", type=int, nargs="+", default=[16, 64])
    value.add_argument("--model-steps", type=int, default=8)
    value.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"),
                       default="auto")
    return value


def main() -> None:
    args = parser().parse_args()
    repo = Path(__file__).resolve().parents[2]
    receipt = run_capacity(
        repo=repo, expected_git=args.expected_git,
        fixture_count=args.fixture_count, worker_counts=args.workers,
        worker_repetitions=args.worker_repetitions,
        batch_sizes=args.batch_sizes, model_steps=args.model_steps,
        device_name=args.device)
    validate_capacity_receipt(receipt)
    _publish(Path(args.out), canonical_json_bytes(receipt))


if __name__ == "__main__":
    main()
