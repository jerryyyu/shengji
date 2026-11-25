"""Build one RT4-M scratch cache partition from its completed joint checkpoint."""
import argparse
from pathlib import Path
import sys

import rt4m_joint
from shengji.train.unified_readout import CACHE_DEFAULT_ENCODE_ROUNDS
from sz2_cache_arm import MEDIUM_ENCODE_ROUNDS, WORKERS, write_partition
from sz2_polish_arm import polish_checkpoint

RT4_SAMPLE = dict(cap_rows=50_000_000, seed=1, chunks=43_454, rows=49_999_996,
                  of_chunks=59_533, of_rows=68_534_944)


def inputs(root, output, recipe_path, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS):
    if encode_rounds not in (CACHE_DEFAULT_ENCODE_ROUNDS, MEDIUM_ENCODE_ROUNDS):
        raise ValueError("unsupported RT4-M cache encode size")
    checkpoint, digest, recipe = rt4m_joint.completed_inputs(root, recipe_path)
    identity = f"{digest}-{rt4m_joint.RECIPE_SHA256}"
    if encode_rounds != CACHE_DEFAULT_ENCODE_ROUNDS:
        identity += f"-encode{encode_rounds}"
    cache = output / "A" / identity
    return checkpoint, cache, recipe


def partition(root, output, worker, recipe_path, *, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS):
    checkpoint, cache, recipe = inputs(root, output, recipe_path, encode_rounds)
    return write_partition(checkpoint, cache, recipe, worker, encode_rounds=encode_rounds,
                           sample_rows=RT4_SAMPLE["cap_rows"])


def polish(root, output, recipe_path, *, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS):
    checkpoint, cache, recipe = inputs(root, output, recipe_path, encode_rounds)
    return polish_checkpoint(checkpoint, cache, recipe, root / "A/polish", epochs=8, lr=1e-3,
                             expected_sample=RT4_SAMPLE, expected_encode_rounds=encode_rounds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--encode-rounds-per-batch", type=int, choices=(CACHE_DEFAULT_ENCODE_ROUNDS, MEDIUM_ENCODE_ROUNDS),
                        default=CACHE_DEFAULT_ENCODE_ROUNDS)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--worker", type=int, choices=range(WORKERS))
    stage.add_argument("--polish", action="store_true")
    args = parser.parse_args()
    try:
        if args.polish:
            return polish(args.root.resolve(), args.cache_root.resolve(), rt4m_joint.RECIPE,
                          encode_rounds=args.encode_rounds_per_batch)
        return partition(args.root.resolve(), args.cache_root.resolve(), args.worker, rt4m_joint.RECIPE,
                         encode_rounds=args.encode_rounds_per_batch)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid RT4-M cache: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
