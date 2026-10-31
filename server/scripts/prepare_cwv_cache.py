#!/usr/bin/env python3
"""Build and reopen PV training caches without constructing or fitting a model.

Use the same data stores, cache directory and explicit encoder version for the
subsequent trainer. Existing compatible shard caches are reused by its builder.
The decoded residency budget bounds retained blocks, not encoder-worker memory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from shengji.rl.encode_versions import check_version  # noqa: E402
from shengji.train.cwv_data import prepare_stores  # noqa: E402


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", action="append", required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--encoder-version", type=int, required=True)
    parser.add_argument("--workers", type=positive, default=1)
    parser.add_argument("--resident-bytes", type=positive, default=64 * 1024 * 1024,
                        help="retained decoded-block budget (default: 64 MiB); not a total process limit")
    parser.add_argument("--limit-clusters", type=positive)
    parser.add_argument("--witness-seed", type=int, default=1)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--search-mean-sidecar", type=Path,
                        help="build missing teacher-target sidecars here and validate their consumption")
    args = parser.parse_args(argv)
    version = check_version(args.encoder_version)
    prepared = prepare_stores(
        args.data, args.cache_dir, limit_clusters=args.limit_clusters,
        version=version, history=args.history, witness_seed=args.witness_seed,
        cache_workers=args.workers, resident_bytes=args.resident_bytes,
        sidecar_dir=str(args.search_mean_sidecar) if args.search_mean_sidecar else None,
        progress=lambda message: print(message, file=sys.stderr, flush=True))
    store = prepared.block_store
    sidecars = None
    if args.search_mean_sidecar is not None:
        from shengji.train.search_mean_sidecar import (
            build_sidecar, check_sidecar_coverage, sidecar_path, summarize_attribution)
        built = reused = 0
        for shard, _path in store.entries:
            if sidecar_path(args.search_mean_sidecar, shard.sha256).is_file():
                reused += 1
            else:
                result = build_sidecar(shard.path, args.search_mean_sidecar)
                if result["shard_sha256"] != shard.sha256:
                    raise RuntimeError(f"source shard changed while building sidecar: {shard.path}")
                built += 1
        coverage = check_sidecar_coverage(
            args.search_mean_sidecar, [(shard.store, shard.sha256) for shard, _ in store.entries])
        sidecars = {"built": built, "reused": reused, "coverage": coverage,
                    "points_target_rows": 0, "level_target_rows": 0,
                    "attribution": summarize_attribution(
                        sidecar_path(args.search_mean_sidecar, shard.sha256)
                        for shard, _ in store.entries)}
    rows = 0
    for block in store.iter_blocks():
        rows += block.n
        if sidecars is not None:
            sidecars["points_target_rows"] += int(np.isfinite(block.search_mean_played).sum())
            sidecars["level_target_rows"] += int(np.isfinite(block.search_level_played).sum())
    if rows != sum(store.rows()):
        raise RuntimeError("decoded cache rows disagree with the trainer's index")
    print(json.dumps({
        "status": "PASS", "scope": "PV cache build and trainer block loading; no training",
        "encoder_version": version, "history": args.history,
        "stores": [str(Path(path).resolve()) for path in args.data],
        "cache_dir": str(args.cache_dir.resolve()), "counts": prepared.counts,
        "consumer_rows": rows, "decoded_bytes": store.nbytes,
        "resident_bytes": args.resident_bytes, "workers": args.workers,
        "search_mean_sidecars": sidecars,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
