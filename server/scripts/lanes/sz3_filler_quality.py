"""Assess the completed SZ3 filler from a pinned UT-GEN2 store-check report.

The authorized scan handoff must publish the manifest and report digests together
from one scan of the completed store. The checker report itself names only a path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from sz3_filler import CAPTURE
import sz3_filler_generator as generator

RUN_ID = "traj-s1011000000-a89fd4006eaa"


def _pinned_json(path: Path, expected: str, limit: int) -> dict:
    if not generator._HEX_SHA.fullmatch(expected):
        raise ValueError(f"invalid expected SHA-256 for {path.name}")
    data = generator._read_metadata(path, limit)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"published SHA-256 differs for {path.name}")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path.name}")
    return value


def _count(fields: dict, name: str) -> int:
    value = fields.get(name) if isinstance(fields, dict) else None
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid count for {name}")
    return value


def _validate_manifest(manifest: dict, rounds: int, clusters: int) -> None:
    config = manifest["config"]
    window = manifest["seed_window"]
    if (manifest["schema"] != "shengji-trajectory-manifest-v1" or manifest["source"] != "trajectory"
            or manifest["record_schema"] != "shengji-decision-record-v1"
            or manifest["run_id"] != RUN_ID or config["run_id"] != RUN_ID or window["name"] != RUN_ID
            or manifest["identity"]["git_sha"] != generator.SHA or config["policy"] != generator.POLICY):
        raise ValueError("manifest identity differs from the SZ3 filler reservation")
    if (manifest["seed0"] != generator.SEED or config["seed0"] != generator.SEED
            or window["seed0"] != generator.SEED or window["clusters"] != clusters
            or window["purpose"] != "trajectory" or window["allow_seed_overlap"] is not False
            or window["span"] != [generator.SEED, generator.SEED + clusters] or window["conflicts"] != []):
        raise ValueError("manifest seed span differs from the SZ3 filler reservation")
    if (_count(manifest, "rounds") != rounds or _count(manifest["counts"], "rounds") != rounds
            or _count(manifest, "clusters") != clusters or len(manifest["shards"]) != clusters
            or manifest["merged"] is not None):
        raise ValueError("manifest completion counts differ")


def assess(*, manifest_sha256: str, check_sha256: str) -> dict:
    """Return the quality summary after verifying the authorized scan's digest pair."""
    rounds = generator.ROUNDS
    clusters = rounds // 2
    terminal = f"DONE rounds={rounds} clusters={clusters}\n".encode()
    if CAPTURE.is_symlink() or generator._read_metadata(CAPTURE / "terminal", 1024) != terminal:
        raise ValueError("expected the exact SZ3 filler DONE capture")
    store = CAPTURE / "store"
    if store.is_symlink():
        raise ValueError("SZ3 filler store is a symlink")
    # DONE marks the producer's completed sidecar checks. The saved scan verifies shard bytes.
    manifest = _pinned_json(store / "manifest.json", manifest_sha256, generator._METADATA_LIMIT)
    _validate_manifest(manifest, rounds, clusters)
    report = _pinned_json(CAPTURE / "store.check.json", check_sha256, generator._SIDECAR_LIMIT)
    if report["store"] != str(store):
        raise ValueError("saved report names a different store")

    counts = manifest["counts"]
    check = report["check"]
    if (_count(check, "clusters_manifest") != clusters or _count(check, "shards_manifest") != clusters):
        raise ValueError("saved report cluster counts differ")
    if _count(check, "bad_sha") or _count(check, "bad_count"):
        raise ValueError("saved report found a shard SHA-256 or row count fault")
    if _count(check, "short_searches") or _count(counts, "short_searches"):
        raise ValueError("short searches in completed capture")
    fallback_counts = ("play_fallback", "bury_fallback", "bury_belief_fallbacks")
    if check["fallbacks"] != {} or check["belief"] != {} or any(_count(counts, key) for key in fallback_counts):
        raise ValueError("play, bury or belief fallbacks in completed capture")
    play = _count(check, "play_rows")
    records = play + rounds
    if (play == 0 or set(check["kinds"]) != {"play", "bury"}
            or _count(check["kinds"], "play") != play or _count(check["kinds"], "bury") != rounds
            or _count(counts, "decisions") != play or _count(counts, "plays") != play
            or _count(counts, "bury_records") != rounds or _count(counts, "records") != records
            or sum(_count(shard, "records") for shard in manifest["shards"]) != records):
        raise ValueError("play, bury or total row counts differ")

    unified = check["unified"]
    if (_count(unified, "missed")
            or ("no_unified_entry" in unified and _count(unified, "no_unified_entry"))):
        raise ValueError("unified misses in completed capture")
    if (_count(unified, "shared") != play
            or any(_count(unified, name) for name in ("value_left", "reply_left", "trunk"))
            or not _count(unified, "value_rows") or not _count(unified, "reply_rows")):
        raise ValueError("incomplete unified readout coverage")

    timing = check.get("play_seconds", {})
    if not timing or _count(timing, "n") != play:
        raise ValueError("incomplete play timing coverage")
    for name in ("mean", "p50", "p95", "p99", "max"):
        seconds = timing[name]
        if type(seconds) not in (int, float) or seconds < 0 or not math.isfinite(seconds):
            raise ValueError(f"invalid play timing for {name}")
    over_3s = _count(timing, "over_3s")
    if not over_3s <= _count(timing, "over_1s") <= play:
        raise ValueError("invalid play timing threshold counts")
    return {"run_id": RUN_ID, "store": str(store), "rounds": rounds, "clusters": clusters,
            "play_rows": play, "bury_rows": rounds, "over_3s": over_3s}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-sha256", required=True, help="manifest digest from the authorized scan handoff")
    parser.add_argument("--check-sha256", required=True, help="store.check.json digest from the same handoff")
    args = parser.parse_args(argv)
    try:
        result = assess(manifest_sha256=args.manifest_sha256, check_sha256=args.check_sha256)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
