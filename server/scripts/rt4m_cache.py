"""Build one RT4-M scratch cache partition from its completed joint checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import rt4m_joint
from sz2_cache_arm import WORKERS, write_partition
from sz2_polish_arm import polish_checkpoint

RT4_SAMPLE = dict(cap_rows=50_000_000, seed=1, chunks=43_454, rows=49_999_996,
                  of_chunks=59_533, of_rows=68_534_944)


def inputs(root, output, recipe_path):
    recipe, _, expected = rt4m_joint.recipe_inputs(root, recipe_path)
    checkpoint, digest = rt4m_joint.verify_completion(root)
    if json.loads((checkpoint.parent / "run.json").read_bytes()) != expected:
        raise ValueError("RT4-M-A completed with different trainer settings")
    with checkpoint.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("RT4-M-A best checkpoint differs from the trainer terminal")
    cache = output / "A" / f"{digest}-{rt4m_joint.RECIPE_SHA256}"
    return checkpoint, cache, recipe


def partition(root, output, worker, recipe_path):
    checkpoint, cache, recipe = inputs(root, output, recipe_path)
    return write_partition(checkpoint, cache, recipe, worker, sample_rows=RT4_SAMPLE["cap_rows"])


def polish(root, output, recipe_path):
    checkpoint, cache, recipe = inputs(root, output, recipe_path)
    return polish_checkpoint(checkpoint, cache, recipe, root / "A/polish", epochs=8, lr=1e-3,
                             expected_sample=RT4_SAMPLE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--worker", type=int, choices=range(WORKERS))
    stage.add_argument("--polish", action="store_true")
    args = parser.parse_args()
    try:
        if args.polish:
            return polish(args.root.resolve(), args.cache_root.resolve(), rt4m_joint.RECIPE)
        return partition(args.root.resolve(), args.cache_root.resolve(), args.worker, rt4m_joint.RECIPE)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid RT4-M cache: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
