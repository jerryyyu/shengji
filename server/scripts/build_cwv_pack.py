#!/usr/bin/env python3
"""Build the decoded pack (#531) for a set of data stores from their existing caches.

    python -P -B scripts/build_cwv_pack.py --data DIR [--data DIR ...] --cache-dir DIR \
        --out PACKDIR [--encoder-version 5] [--search-mean-sidecar DIR] [--force-float32 508 ...]

Discovers the stores exactly as the trainer does (same shard order), requires every cache
shard to exist and validate (it builds none), then writes the pack.  Train with
``--pack-dir PACKDIR``; the batch sequence is identical to the cache path.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.rl.encode_versions import ENC_VERSION  # noqa: E402
from shengji.train.cwv_data import cache_path, discover_store, read_meta, check_meta  # noqa: E402
from shengji.train.cwv_pack import build_pack  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", action="append", required=True)
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--encoder-version", type=int, default=ENC_VERSION)
    p.add_argument("--search-mean-sidecar", default=None)
    p.add_argument("--classify-shards", type=int, default=500)
    p.add_argument("--force-float32", type=int, action="append", default=[])
    a = p.parse_args(argv)
    say = lambda s: print(f"{time.strftime('%H:%M:%S')} {s}", flush=True)
    entries = []
    for path in a.data:
        store = discover_store(path, limit_clusters=None)
        for shard in store.shards:
            cp = cache_path(a.cache_dir, shard.sha256, history=False, version=a.encoder_version)
            if not Path(cp).is_file():
                raise SystemExit(f"{shard.label}: cache {cp} is missing; run the trainer's cache build first")
            check_meta(read_meta(cp), path=cp, shard_sha256=shard.sha256, history=False)
            entries.append((shard, str(cp)))
    say(f"{len(entries)} cached shards across {len(a.data)} stores")
    manifest = build_pack(entries, a.out, sidecar_dir=a.search_mean_sidecar,
                          classify_shards=a.classify_shards, force_float32=a.force_float32, progress=say)
    say(f"rows {manifest['rows']}, public {manifest['public_dim']} = {len(manifest['half_cols'])} byte + "
        f"{len(manifest['f32_cols'])} float32 columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
