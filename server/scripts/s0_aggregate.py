"""Fail-closed aggregation and predeclared survivor choice for S0 shards."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import s0_run as S0  # noqa: E402
from shengji.evaluation import paired_by_seed  # noqa: E402


class AggregationRefused(RuntimeError):
    pass


def load(phase: str, pattern: str):
    manifests = []
    records = {}
    for path in sorted(glob.glob(pattern)):
        try:
            manifest = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("schema") != S0.SCHEMA or manifest.get("phase") != phase:
            continue
        if not manifest.get("promotable"):
            continue
        record_path = path.removesuffix(".manifest.json")
        if not os.path.exists(record_path):
            raise AggregationRefused(f"manifest has no records: {path}")
        manifests.append((path, manifest))
        for line in open(record_path):
            rec = json.loads(line)
            rec["_source"] = record_path
            records.setdefault(rec["label"], []).append(rec)
    return manifests, records


def validate(phase: str, manifests, records) -> list[str]:
    spec = S0.PROTOCOLS[phase]
    problems = []
    if len(manifests) != S0.SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected {S0.SHARD_COUNT}")
    indices = [m["shard_index"] for _, m in manifests]
    if sorted(indices) != list(range(S0.SHARD_COUNT)):
        problems.append(f"shard indices are {sorted(indices)}")
    for key in ("git_sha", "labels", "digests", "policy_contracts", "ballots",
                "report_worlds", "selection_rule"):
        values = {json.dumps(m.get(key), sort_keys=True) for _, m in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {key}")
    for path, manifest in manifests:
        if not manifest.get("complete") or manifest.get("problems"):
            problems.append(f"incomplete/failed manifest {path}")
        i = manifest["shard_index"]
        want_lo = spec["seed0"] + i * S0.CLUSTERS_PER_SHARD
        if manifest.get("seed0") != want_lo or \
                manifest.get("seed_hi") != want_lo + S0.CLUSTERS_PER_SHARD - 1:
            problems.append(f"shard {i}: seed block drift")

    expected_labels = set(spec["labels"])
    if set(records) != expected_labels:
        problems.append(f"labels {sorted(records)} != {sorted(expected_labels)}")
    expected_n = 2 * S0.TOTAL_CLUSTERS
    for label, recs in records.items():
        if len(recs) != expected_n:
            problems.append(f"{label}: {len(recs)} records, expected {expected_n}")
        keys = [(r["seed"], r["flip"]) for r in recs]
        dupes = len(keys) - len(set(keys))
        if dupes:
            problems.append(f"{label}: {dupes} duplicate seed/flip keys")
        want_policy = spec["labels"].get(label)
        if any(r.get("policy") != want_policy for r in recs):
            problems.append(f"{label}: policy identity drift")
    problems += S0.record_problems(records)
    return sorted(set(problems))


def contrast(records, a: str, b: str) -> dict:
    mean, half, n = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": n}


def choose_survivor(phase: str, records) -> tuple[str | None, dict]:
    stats = {}
    if phase == "s0a":
        for label in ("report_mean", "report_lcb", "uniform_work", "null"):
            stats[f"{label}-reference"] = contrast(records, label, "reference")
        ranked = sorted(
            ("report_mean", "report_lcb"),
            key=lambda label: (stats[f"{label}-reference"]["mean"],
                               label == "report_mean"), reverse=True)
        winner = ranked[0]
        effect = stats[f"{winner}-reference"]["mean"]
        compute = stats["uniform_work-reference"]["mean"]
        survivor = winner if effect > 0 and effect > compute else None
    else:
        for label in ("adaptive", "report_uniform", "random", "uniform_work",
                      "null"):
            stats[f"{label}-reference"] = contrast(records, label, "reference")
        stats["adaptive-report_uniform"] = contrast(
            records, "adaptive", "report_uniform")
        stats["adaptive-random"] = contrast(records, "adaptive", "random")
        survivor = ("adaptive"
                    if stats["adaptive-report_uniform"]["mean"] > 0 and
                    stats["adaptive-random"]["mean"] > 0
                    else "report_uniform")
    return survivor, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=tuple(S0.PROTOCOLS))
    ap.add_argument("--pattern", default="runs/logs/*.manifest.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    manifests, records = load(args.phase, args.pattern)
    problems = validate(args.phase, manifests, records)
    if problems:
        raise AggregationRefused("S0 aggregation refused:\n  - " +
                                 "\n  - ".join(problems))
    survivor, stats = choose_survivor(args.phase, records)
    labels = S0.PROTOCOLS[args.phase]["labels"]
    result = {
        "schema": "s0-mechanism-aggregate-v1", "phase": args.phase,
        "promotion": False,
        "note": "Mechanism-screen survivor only; production requires the "
                "independent 8,192-cluster confirmation.",
        "shards": [path for path, _ in manifests],
        "git_sha": manifests[0][1]["git_sha"],
        "clusters": S0.TOTAL_CLUSTERS,
        "stats": stats, "survivor_label": survivor,
        "survivor_policy": labels.get(survivor) if survivor else None,
        "record_counts": dict(Counter({k: len(v) for k, v in records.items()})),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.out:
        if os.path.exists(args.out):
            raise AggregationRefused(f"refusing to overwrite {args.out}")
        with open(args.out, "x") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
