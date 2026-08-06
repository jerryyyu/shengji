"""Frozen current-compatibility gate for ``rl-override-v11pair``.

This is deliberately separate from the protected-anchor experiment.  First we
ask whether the exact v11pair policy that beat SmartBot still beats today's
compiled N=30 incumbent.  Only a superiority result on this immutable block
authorizes spending a fresh block on the anchor composition; an interval that
contains zero is not equivalence.

Eight full shards cover the predeclared BACKLOG block exactly once::

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
      scripts/v11_revalidate.py run --shard-index 0

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
      scripts/v11_revalidate.py aggregate \
      --out runs/logs/v11-current-v1.aggregate.json

No command here launches the later anchor test or changes production.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import (arm_ballots, paired_by_seed,  # noqa: E402
                                run_arm)


SCHEMA = "v11-current-revalidation-v1"
AGGREGATE_SCHEMA = "v11-current-revalidation-aggregate-v1"
SHARD_COUNT = 8
TOTAL_CLUSTERS = 2_048
CLUSTERS_PER_SHARD = TOTAL_CLUSTERS // SHARD_COUNT
# BACKLOG.md predeclared this block before implementation.  Do not substitute
# another convenient untouched range after inspecting any result.
SEED0 = 121_000_000
SEED_HI = SEED0 + TOTAL_CLUSTERS - 1
OPPONENT = "mc-strong"
LABELS = {
    "arm": "rl-override-v11pair",
    "null": "mc-strong-null",
    "reference": "mc-strong",
}
CHECKPOINT = SERVER / "snapshots_v11pair" / "ep07.npz"
CHECKPOINT_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
SELECTION_RULE = (
    "AUTHORIZE the separate protected-anchor experiment only if the paired "
    "95% lower bounds for v11-current and v11-null are both >0, and the "
    "mc-strong-null minus current interval contains zero, over exactly 2,048 "
    "fresh seed clusters. This is current compatibility, never production "
    "promotion; an interval containing zero is not equivalence."
)


class ProtocolRefused(RuntimeError):
    pass


def sha256(path: os.PathLike | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=SERVER.parent, check=True,
                          capture_output=True, text=True).stdout.strip()


def runtime_identity(fast) -> dict:
    """Every executable component that can change the registered estimand."""
    return {
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "digests": {
            "runner": sha256(__file__),
            "evaluation": sha256(SERVER / "shengji" / "evaluation.py"),
            "registry": sha256(SERVER / "shengji" / "ai" / "registry.py"),
            "mcbot": sha256(SERVER / "shengji" / "ai" / "mcbot.py"),
            "ballot": sha256(SERVER / "shengji" / "engine" / "ballot.py"),
            "torch_policy": sha256(
                SERVER / "shengji" / "rl" / "torch_policy.py"),
            "encoder": sha256(SERVER / "shengji" / "rl" / "encode.py"),
            "npnet": sha256(SERVER / "shengji" / "rl" / "npnet.py"),
            "fast_router": sha256(fast.__file__),
            "fast_binary": sha256(fast._fast.__file__),
            "checkpoint": sha256(CHECKPOINT),
        },
    }


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    return {
        "class": type(bot).__name__,
        "n_determinizations": getattr(bot, "N_DETERMINIZATIONS", None),
        "margin": getattr(bot, "MARGIN", None),
        "tractor_lock": getattr(bot, "TRACTOR_LOCK", None),
        "require_exact_work": getattr(bot, "REQUIRE_EXACT_WORK", None),
        "checkpoint_path": getattr(bot, "checkpoint_path", None),
        "checkpoint_sha256": getattr(bot, "checkpoint_sha256", None),
    }


def protocol_problems() -> list[str]:
    problems = []
    if TOTAL_CLUSTERS != 2_048 or SHARD_COUNT != 8 or \
            TOTAL_CLUSTERS % SHARD_COUNT:
        problems.append("registered cluster/shard geometry drifted")
    if SEED0 != 121_000_000 or SEED_HI != 121_002_047:
        problems.append("registered fresh seed block drifted")
    if LABELS != {"arm": "rl-override-v11pair",
                  "null": "mc-strong-null", "reference": "mc-strong"}:
        problems.append("registered policy labels drifted")
    if not CHECKPOINT.is_file():
        problems.append(f"missing frozen checkpoint {CHECKPOINT}")
    elif sha256(CHECKPOINT) != CHECKPOINT_SHA256:
        problems.append("frozen v11pair checkpoint SHA-256 drifted")

    try:
        contracts = {name: policy_contract(name) for name in LABELS.values()}
    except Exception as exc:
        problems.append(f"policy construction failed: {type(exc).__name__}: {exc}")
        contracts = {}
    arm = contracts.get("rl-override-v11pair", {})
    if arm.get("margin") != 0.02:
        problems.append(f"v11 override threshold is {arm.get('margin')!r}, not 0.02")
    if arm.get("checkpoint_path") != str(CHECKPOINT.resolve()):
        problems.append(
            f"v11 policy loaded {arm.get('checkpoint_path')!r}, not {CHECKPOINT}")
    if arm.get("checkpoint_sha256") != CHECKPOINT_SHA256:
        problems.append("v11 policy checkpoint bytes differ from manifest bytes")
    for name in ("mc-strong", "mc-strong-null"):
        cfg = contracts.get(name, {})
        if cfg.get("n_determinizations") != 30:
            problems.append(f"{name} is not N=30")
        if cfg.get("margin") != 5.0:
            problems.append(f"{name} fixed search margin is not 5.0")
        if cfg.get("tractor_lock") is not True:
            problems.append(f"{name} changed TRACTOR_LOCK")
    try:
        current = make_bot("mc-strong", seed=7)
        null = make_bot("mc-strong-null", seed=7)
        differing = [name for name in dir(current)
                     if name.isupper() and
                     getattr(current, name, None) != getattr(null, name, None)]
        if differing:
            problems.append(f"mc-strong-null policy drifted in {differing}")
        if current.rng.getstate() == null.rng.getstate():
            problems.append("mc-strong-null does not use a distinct RNG stream")
    except Exception as exc:
        problems.append(f"null construction failed: {type(exc).__name__}: {exc}")

    try:
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append(
                f"v11/current/null do not share one current MC ballot: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    return sorted(set(problems))


def record_problems(records: dict[str, list]) -> list[str]:
    """Strict sampler/work and exact paired-coverage gate for one shard."""
    problems = []
    expected = None
    for label, rows in records.items():
        keys = [(row["seed"], row["flip"]) for row in rows]
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip record")
        if expected is None:
            expected = set(keys)
        elif set(keys) != expected:
            problems.append(f"{label}: seed/flip coverage differs")
        for row in rows:
            for side in ("arm", "opp"):
                counters = row[side]
                attempts = int(counters.get("sample_attempts", 0))
                accepted = int(counters.get("accepted_worlds", 0))
                failed = int(counters.get("failed_worlds", 0))
                if attempts != accepted + failed:
                    problems.append(f"{label}/{side}: sampler counters do not reconcile")
                for field in ("failed_worlds", "rejected_worlds",
                              "short_searches", "zero_world", "void_fallbacks"):
                    if int(counters.get(field, 0)):
                        problems.append(f"{label}/{side}: nonzero {field}")
    return sorted(set(problems))


def _require_runtime() -> tuple[object, dict]:
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    return fast, runtime_identity(fast)


def run_shard(args) -> None:
    _, runtime = _require_runtime()
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused("v11 protocol drift:\n  - " + "\n  - ".join(problems))

    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if dirty and not args.smoke:
        raise ProtocolRefused("full v11 shard refuses a dirty tree")
    clusters = 2 if args.smoke else CLUSTERS_PER_SHARD
    seed0 = SEED0 + args.shard_index * CLUSTERS_PER_SHARD
    run_id = (f"{SCHEMA}_shard{args.shard_index:02d}_{head[:10]}" +
              ("_SMOKE" if args.smoke else ""))
    out = Path(args.out or f"runs/logs/{run_id}.jsonl")
    manifest_path = Path(str(out) + ".manifest.json")
    for path in (out, Path(str(out) + ".partial"), manifest_path,
                 Path(str(manifest_path) + ".partial")):
        if path.exists():
            raise ProtocolRefused(f"refusing to overwrite {path}")
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "promotable": not args.smoke,
        "git_sha": head,
        "tree_dirty": bool(dirty),
        "dirty_files": dirty.splitlines() if dirty else [],
        **runtime,
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS,
        "clusters": clusters,
        "seed0": seed0,
        "seed_hi": seed0 + clusters - 1,
        "opponent": OPPONENT,
        "labels": LABELS,
        "checkpoint": str(CHECKPOINT.relative_to(SERVER)),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "selection_rule": SELECTION_RULE,
        "policy_contracts": {name: policy_contract(name)
                             for name in LABELS.values()},
        "ballots": arm_ballots(LABELS.values()),
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    manifest_partial = Path(str(manifest_path) + ".partial")
    records_partial = Path(str(out) + ".partial")
    with manifest_partial.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    records = {}
    with records_partial.open("x") as fh:
        for label, policy in LABELS.items():
            print(f"\n{label}: {policy} vs {OPPONENT}", flush=True)
            records[label] = run_arm(label, policy, OPPONENT, clusters, seed0,
                                     fh, run_id)

    problems = record_problems(records)
    manifest["completed"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    manifest["problems"] = problems
    manifest["complete"] = not problems
    manifest["paired"] = {
        "arm-reference": _contrast(records, "arm", "reference"),
        "arm-null": _contrast(records, "arm", "null"),
        "null-reference": _contrast(records, "null", "reference"),
    }
    with manifest_partial.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    suffix = "" if not problems else ".FAILED"
    os.replace(records_partial, Path(str(out) + suffix))
    os.replace(manifest_partial, Path(str(manifest_path) + suffix))
    if problems:
        raise ProtocolRefused("v11 shard failed closed:\n  - " +
                              "\n  - ".join(problems))
    print(f"\nrecords: {out}\nmanifest: {manifest_path}")


def _load(pattern: str):
    manifests = []
    records: dict[str, list] = {}
    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("schema") != SCHEMA or not manifest.get("promotable"):
            continue
        record_path = Path(str(path).removesuffix(".manifest.json"))
        if not record_path.is_file():
            raise ProtocolRefused(f"manifest has no records: {path}")
        manifests.append((path, manifest))
        for line in record_path.read_text().splitlines():
            row = json.loads(line)
            row["_source"] = str(record_path)
            records.setdefault(row["label"], []).append(row)
    return manifests, records


def _manifest_runtime(manifest: dict) -> dict:
    return {key: manifest.get(key) for key in (
        "host", "python", "fast_engine", "require_voids", "digests")}


def _validate(manifests, records, current_runtime: dict,
              current_head: str) -> list[str]:
    problems = []
    if len(manifests) != SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected {SHARD_COUNT}")
    indices = [m.get("shard_index") for _, m in manifests]
    if sorted(i for i in indices if isinstance(i, int)) != list(range(SHARD_COUNT)):
        problems.append(f"shard indices are {indices}")
    for key in ("git_sha", "host", "python", "fast_engine", "require_voids",
                "digests", "labels", "ballots", "policy_contracts",
                "checkpoint_sha256", "selection_rule", "shard_count",
                "total_clusters"):
        values = {json.dumps(m.get(key), sort_keys=True) for _, m in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {key}")
    for path, manifest in manifests:
        if not manifest.get("complete") or manifest.get("problems"):
            problems.append(f"incomplete/failed manifest {path}")
        if manifest.get("tree_dirty") or not manifest.get("promotable"):
            problems.append(f"dirty/non-promotable manifest {path}")
        if manifest.get("git_sha") != current_head:
            problems.append(f"{path}: git SHA differs from verifier")
        if _manifest_runtime(manifest) != current_runtime:
            problems.append(f"{path}: runtime differs from verifier")
        i = manifest.get("shard_index")
        if isinstance(i, int):
            want = SEED0 + i * CLUSTERS_PER_SHARD
            if manifest.get("seed0") != want or \
                    manifest.get("seed_hi") != want + CLUSTERS_PER_SHARD - 1:
                problems.append(f"shard {i}: seed block drift")
        if manifest.get("clusters") != CLUSTERS_PER_SHARD:
            problems.append(f"{path}: cluster count drift")

    if set(records) != set(LABELS):
        problems.append(f"record labels {sorted(records)} != {sorted(LABELS)}")
    expected_keys = {(seed, flip)
                     for seed in range(SEED0, SEED_HI + 1)
                     for flip in (0, 1)}
    run_by_source = {
        str(path).removesuffix(".manifest.json"): manifest.get("run_id")
        for path, manifest in manifests
    }
    for label, rows in records.items():
        keys = [(row["seed"], row["flip"]) for row in rows]
        if len(rows) != 2 * TOTAL_CLUSTERS:
            problems.append(f"{label}: {len(rows)} records")
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip records")
        if set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
        if any(row.get("policy") != LABELS[label] for row in rows):
            problems.append(f"{label}: policy identity drift")
        if any(row.get("run") != run_by_source.get(row.get("_source"))
               for row in rows):
            problems.append(f"{label}: record/run identity drift")
    problems += record_problems(records)
    problems += protocol_problems()
    return sorted(set(problems))


def _contrast(records, a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": clusters}


def gate_criteria(stats: dict) -> dict[str, bool]:
    """The predeclared compatibility rule, isolated for falsification tests."""
    arm_ref = stats["arm-reference"]
    arm_null = stats["arm-null"]
    null_ref = stats["null-reference"]
    criteria = {
        "v11_current_lcb_gt_0": (
            arm_ref["mean"] - arm_ref["half_width_95"] > 0),
        "v11_null_lcb_gt_0": (
            arm_null["mean"] - arm_null["half_width_95"] > 0),
        "null_current_interval_contains_0": (
            abs(null_ref["mean"]) <= null_ref["half_width_95"]),
    }
    criteria["all"] = all(criteria.values())
    return criteria


def counter_totals(records: dict[str, list]) -> dict:
    fields = (
        "rollouts", "searches", "sample_attempts", "accepted_worlds",
        "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
        "void_fallbacks",
    )
    return {
        label: {
            side: {field: sum(int(row[side].get(field, 0)) for row in rows)
                   for field in fields}
            for side in ("arm", "opp")
        }
        for label, rows in records.items()
    }


def aggregate(args) -> None:
    _, runtime = _require_runtime()
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused("v11 aggregate refuses a dirty verifier tree")
    head = git("rev-parse", "HEAD")
    manifests, records = _load(args.pattern)
    problems = _validate(manifests, records, runtime, head)
    if problems:
        raise ProtocolRefused("v11 aggregation refused:\n  - " +
                              "\n  - ".join(problems))

    stats = {
        "arm-reference": _contrast(records, "arm", "reference"),
        "arm-null": _contrast(records, "arm", "null"),
        "null-reference": _contrast(records, "null", "reference"),
    }
    criteria = gate_criteria(stats)
    result = {
        "schema": AGGREGATE_SCHEMA,
        "git_sha": head,
        "clusters": TOTAL_CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "runtime_identity": runtime,
        "shards": [str(path) for path, _ in manifests],
        "record_counts": {label: len(rows) for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "stats": stats,
        "criteria": criteria,
        "anchor_test_authorized": criteria["all"],
        "production_promotion": False,
        "note": ("This gate establishes current compatibility only. The "
                 "protected-anchor policy still requires an independent "
                 "fresh paired superiority experiment."),
    }
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if args.out:
        path = Path(args.out)
        partial = Path(str(path) + ".partial")
        if path.exists() or partial.exists():
            raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with partial.open("x") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--out", default=None)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--pattern", default="runs/logs/*.manifest.json")
    agg.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.command == "run":
        run_shard(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
