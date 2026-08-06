"""Fail-closed aggregation and predeclared survivor choice for S0 shards."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

SOURCE_SERVER = os.environ.get(
    "S0_SOURCE_SERVER",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.path.insert(0, SOURCE_SERVER)
sys.path.insert(0, os.path.join(SOURCE_SERVER, "scripts"))

import s0_run as S0  # noqa: E402
from shengji.evaluation import paired_by_seed  # noqa: E402


class AggregationRefused(RuntimeError):
    pass


def manifest_runtime(manifest: dict) -> dict:
    return {
        "host": manifest.get("host"),
        "python": manifest.get("python"),
        "fast_engine": manifest.get("fast_engine"),
        "require_voids": manifest.get("require_voids"),
        "experimental_sampler_flags": manifest.get(
            "experimental_sampler_flags"),
        "digests": manifest.get("digests"),
    }


def runtime_identity(manifests) -> dict:
    """Require and return one exact runtime identity for a complete phase."""
    if not manifests:
        raise AggregationRefused("cannot derive runtime identity without manifests")
    runtimes = [manifest_runtime(manifest) for _, manifest in manifests]
    first = runtimes[0]
    required = (
        "host", "python", "fast_engine", "require_voids",
        "experimental_sampler_flags", "digests",
    )
    missing = [key for key in required if first.get(key) in (None, "", {})]
    if missing:
        raise AggregationRefused(f"runtime identity missing {missing}")
    if first["experimental_sampler_flags"] != []:
        raise AggregationRefused(
            "runtime identity experimental sampler/ballot flags are not "
            "an explicit empty list")
    if any(runtime != first for runtime in runtimes[1:]):
        raise AggregationRefused("shards disagree on exact runtime identity")
    digests = first["digests"]
    if not isinstance(digests, dict) or not digests.get("fast_binary"):
        raise AggregationRefused("runtime identity lacks compiled binary digest")
    return first


def aggregate_parent_identity(manifests, runtime: dict) -> dict | None:
    """Bind the phase runtime into the exact parent aggregate hash chain."""
    parent = manifests[0][1].get("parent")
    if parent is None:
        return None
    if not isinstance(parent, dict) or not parent.get("sha256"):
        raise AggregationRefused("child phase lacks an exact parent hash")
    bound = parent.get("runtime_identity")
    if bound is not None and bound != runtime:
        raise AggregationRefused("child manifest parent runtime identity drift")
    result = dict(parent)
    # Older frozen runners bind the whole parent aggregate by SHA but do not
    # duplicate its runtime fields.  The independently verified aggregate adds
    # the exact child runtime here; s0_packet proves it equals the hashed parent.
    result["runtime_identity"] = runtime
    return result


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
    shard_count = S0.phase_shard_count(phase)
    total_clusters = S0.phase_total_clusters(phase)
    clusters_per_shard = S0.phase_clusters_per_shard(phase)
    if len(manifests) != shard_count:
        problems.append(f"found {len(manifests)} shards, expected {shard_count}")
    indices = [m["shard_index"] for _, m in manifests]
    if sorted(indices) != list(range(shard_count)):
        problems.append(f"shard indices are {sorted(indices)}")
    for key in ("git_sha", "host", "labels", "digests", "policy_contracts", "ballots",
                "report_worlds", "selection_rule", "kind", "parent",
                "shard_count", "total_clusters", "python",
                "experimental_sampler_flags"):
        values = {json.dumps(m.get(key), sort_keys=True) for _, m in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {key}")
    for path, manifest in manifests:
        if not manifest.get("complete") or manifest.get("problems"):
            problems.append(f"incomplete/failed manifest {path}")
        if manifest.get("tree_dirty") or not manifest.get("promotable"):
            problems.append(f"non-promotable/dirty manifest {path}")
        if manifest.get("fast_engine") is not True or \
                manifest.get("require_voids") is not True:
            problems.append(f"wrong engine/sampler mode in {path}")
        i = manifest["shard_index"]
        want_lo = spec["seed0"] + i * clusters_per_shard
        if manifest.get("seed0") != want_lo or \
                manifest.get("seed_hi") != want_lo + clusters_per_shard - 1:
            problems.append(f"shard {i}: seed block drift")
        if manifest.get("clusters") != clusters_per_shard:
            problems.append(f"shard {i}: cluster count drift")
    if manifests:
        try:
            runtime_identity(manifests)
        except AggregationRefused as exc:
            problems.append(str(exc))

    expected_labels = set(spec["labels"])
    if set(records) != expected_labels:
        problems.append(f"labels {sorted(records)} != {sorted(expected_labels)}")
    expected_keys = {
        (seed, flip)
        for seed in range(spec["seed0"], spec["seed0"] + total_clusters)
        for flip in (0, 1)
    }
    expected_n = len(expected_keys)
    run_by_source = {
        path.removesuffix(".manifest.json"): manifest.get("run_id")
        for path, manifest in manifests
    }
    for label, recs in records.items():
        if len(recs) != expected_n:
            problems.append(f"{label}: {len(recs)} records, expected {expected_n}")
        keys = [(r["seed"], r["flip"]) for r in recs]
        dupes = len(keys) - len(set(keys))
        if dupes:
            problems.append(f"{label}: {dupes} duplicate seed/flip keys")
        if set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        want_policy = spec["labels"].get(label)
        if any(r.get("policy") != want_policy for r in recs):
            problems.append(f"{label}: policy identity drift")
        if any(r.get("run") != run_by_source.get(r.get("_source")) for r in recs):
            problems.append(f"{label}: record/run manifest identity drift")
    problems += S0.protocol_problems(phase)
    problems += S0.record_problems(records)
    return sorted(set(problems))


def contrast(records, a: str, b: str) -> dict:
    mean, half, n = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": n}


def counter_totals(records) -> dict:
    fields = (
        "rollouts", "searches", "sample_attempts", "accepted_worlds",
        "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
        "void_fallbacks",
    )
    return {
        label: {
            side: {field: sum(int(row[side].get(field, 0)) for row in recs)
                   for field in fields}
            for side in ("arm", "opp")
        }
        for label, recs in records.items()
    }


def confirmation_criteria(stats: dict) -> dict[str, bool]:
    """Derive the registered S0c lower-bound gate from recomputed statistics."""
    criteria = {
        "arm_reference_lcb_gt_0": (
            stats["arm-reference"]["mean"] -
            stats["arm-reference"]["half_width_95"] > 0),
        "arm_null_lcb_gt_0": (
            stats["arm-null"]["mean"] -
            stats["arm-null"]["half_width_95"] > 0),
        "null_reference_lcb_not_gt_0": (
            stats["null-reference"]["mean"] -
            stats["null-reference"]["half_width_95"] <= 0),
    }
    criteria["all"] = all(criteria.values())
    return criteria


def choose_survivor(phase: str, records) -> tuple[str | None, dict]:
    stats = {}
    if phase == "s0a":
        for label in ("report_mean", "report_lcb", "uniform_work", "null"):
            stats[f"{label}-reference"] = contrast(records, label, "reference")
        for label in ("report_mean", "report_lcb"):
            stats[f"{label}-uniform_work"] = contrast(
                records, label, "uniform_work")
        ranked = sorted(
            ("report_mean", "report_lcb"),
            key=lambda label: (stats[f"{label}-reference"]["mean"],
                               label == "report_mean"), reverse=True)
        winner = ranked[0]
        effect = stats[f"{winner}-reference"]["mean"]
        direct = stats[f"{winner}-uniform_work"]["mean"]
        survivor = winner if effect > 0 and direct > 0 else None
    elif phase.startswith("s0b-"):
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
    else:
        stats["arm-reference"] = contrast(records, "arm", "reference")
        stats["null-reference"] = contrast(records, "null", "reference")
        stats["arm-null"] = contrast(records, "arm", "null")
        survivor = "arm" if confirmation_criteria(stats)["all"] else None
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
    runtime = runtime_identity(manifests)
    labels = S0.PROTOCOLS[args.phase]["labels"]
    confirmation = S0.PROTOCOLS[args.phase]["kind"] == "confirmation"
    criteria = None
    if confirmation:
        criteria = confirmation_criteria(stats)
    result = {
        "schema": "s0-mechanism-aggregate-v1", "phase": args.phase,
        "promotion": bool(confirmation and survivor),
        "note": ("PROMOTE only when every frozen confirmation criterion "
                 "passes; otherwise S0 is SELECT NONE."
                 if confirmation else
                 "Mechanism-screen survivor only; production requires the "
                 "independent 8,192-cluster confirmation."),
        "shards": [path for path, _ in manifests],
        "git_sha": manifests[0][1]["git_sha"],
        "parent": aggregate_parent_identity(manifests, runtime),
        "runtime_identity": runtime,
        "clusters": S0.phase_total_clusters(args.phase),
        "seed0": S0.PROTOCOLS[args.phase]["seed0"],
        "seed_hi": (S0.PROTOCOLS[args.phase]["seed0"] +
                    S0.phase_total_clusters(args.phase) - 1),
        "hosts": sorted({manifest.get("host") for _, manifest in manifests}),
        "stats": stats, "criteria": criteria, "survivor_label": survivor,
        "survivor_policy": labels.get(survivor) if survivor else None,
        "record_counts": {key: len(value) for key, value in records.items()},
        "counter_totals": counter_totals(records),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.out:
        if os.path.exists(args.out):
            raise AggregationRefused(f"refusing to overwrite {args.out}")
        with open(args.out, "x") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
