"""Compare completed, paired cwv-shortlist screens recorded in times.jsonl."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys


TIMINGS = set("""
    arm_prior_secs arm_search_secs arm_wide_secs baseline_search_secs belief_ms
    bury_belief_ms decision_cpu_seconds decision_wall_seconds elapsed_seconds
    exact_lead_seconds model_seconds rollout_seconds shortlist_wall_seconds wall_secs
    arm_over_baseline_decision_cpu arm_over_baseline_decision_wall
    decision_wall_target_status p50_seconds p90_seconds total_seconds max_seconds
""".split())


def difference(a, b, source_files, path=()):
    if type(a) is not type(b):
        return path
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return path + ("keys",)
        for key in a:
            if key in TIMINGS:
                continue
            if key == "seconds" and any(item in path for item in
                                        ("decisions", "declare_decisions", "bury_decisions")):
                continue
            if "decision_latency" in path and key in {"max", "p50", "p95", "p99", "above_seconds"}:
                continue
            if path[-1:] == ("source_sha256",) and key in source_files:
                continue
            mismatch = difference(a[key], b[key], source_files, path + (key,))
            if mismatch is not None:
                return mismatch
    elif isinstance(a, list):
        if len(a) != len(b):
            return path + ("length",)
        for i, (x, y) in enumerate(zip(a, b)):
            mismatch = difference(x, y, source_files, path + (i,))
            if mismatch is not None:
                return mismatch
    elif a != b:
        return path
    return None


def read_pair(root, seed, clusters, sources):
    dirs = [root / f"{arm}-{seed}" for arm in ("base", "trial")]
    files = {"cluster-%05d.json" % i for i in range(clusters)}
    for folder in dirs:
        if {f.name for f in folder.glob("cluster-*.json")} != files:
            raise ValueError(f"{folder}: incomplete or unexpected shard set")
    for name in ["summary.json", *sorted(files)]:
        docs = [json.loads((folder / name).read_text()) for folder in dirs]
        for doc in docs:
            if name == "summary.json":
                if not (doc["schema"] == "cwv-shortlist-summary-v1" and doc["complete"]
                        and doc["work_accounting_complete"] and not doc["problems"]
                        and not doc["refused"] and doc["seed0"] == seed
                        and doc["requested_clusters"] == doc["completed_clusters"] == clusters
                        and doc["rounds"] == 2 * clusters
                        and all(doc["decision_latency"][role]["timeouts"] == 0
                                for role in ("arm", "baseline"))):
                    raise ValueError(f"{root}/{seed}: invalid summary")
            else:
                index = int(name[8:13])
                if not (doc["schema"] == "cwv-shortlist-shard-v1" and doc["cluster"] == index
                        and doc["seed"] == seed + index and len(doc["records"]) == 2
                        and Counter((t["mirror"], t["side"]) for t in doc["decision_traces"])
                        == {(m, side): 2 for m in (0, 1) for side in ("arm", "baseline")}
                        and all(trace["decisions"] for trace in doc["decision_traces"])):
                    raise ValueError(f"{root}/{seed}/{name}: incomplete shard")
        mismatch = difference(*docs, sources)
        if mismatch is not None:
            raise ValueError(f"{root}/{seed}/{name}: difference at {mismatch}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repetitions", nargs="+", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--clusters", type=int, required=True)
    parser.add_argument("--changed-source", action="append", default=[])
    args = parser.parse_args()
    if (args.clusters < 1 or len(set(args.seeds)) != len(args.seeds)
            or len(set(p.resolve() for p in args.repetitions)) != len(args.repetitions)):
        parser.error("expected distinct seeds and repetitions, and a positive cluster count")
    totals = {"base": 0.0, "trial": 0.0}
    for root in args.repetitions:
        rows = {}
        for line in (root / "times.jsonl").read_text().splitlines():
            row = json.loads(line)
            key = row["seed"], row["arm"]
            if key in rows or not math.isfinite(row["wall"]) or row["wall"] <= 0:
                raise ValueError(f"{root}: invalid or duplicate timing for {key}")
            rows[key] = row["wall"]
        if rows.keys() != {(seed, arm) for seed in args.seeds for arm in totals}:
            raise ValueError(f"{root}: timing rows differ from requested pairs")
        for seed in args.seeds:
            read_pair(root, seed, args.clusters, args.changed_source)
            for arm in totals:
                totals[arm] += rows[seed, arm]
    print(json.dumps({"pairs": len(args.seeds) * len(args.repetitions), "wall_seconds": totals,
                      "wall_reduction_percent": 100 * (1 - totals["trial"] / totals["base"])}))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, TypeError) as exc:
        sys.exit(str(exc))
