"""Fail-closed, sharded S0 mechanism screen.

S0a separates the report decision rule from extra compute.  S0b (run only
after S0a chooses a rule) separates deterministic adaptive allocation from its
random-allocation attribution control.  Every label in a shard plays the same
mirrored deals against the same production `mc-strong` opponent.

Full S0a shard example (8 shards, one per worker):

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 .venv/bin/python \
      scripts/s0_run.py s0a --shard-index 0

Use ``--smoke --out /tmp/...`` for a two-cluster mechanics check.  Smoke output
is permanently marked non-promotable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.registry import S0_REPORT_WORLDS, make_bot  # noqa: E402
from shengji.evaluation import (arm_ballots, paired_by_seed,  # noqa: E402
                                run_arm)


SCHEMA = "s0-mechanism-screen-v1"
SHARD_COUNT = 8
TOTAL_CLUSTERS = 2048
CLUSTERS_PER_SHARD = TOTAL_CLUSTERS // SHARD_COUNT
OPPONENT = "mc-strong"

PROTOCOLS = {
    "s0a": {
        "seed0": 132_000_000,
        "labels": {
            "report_mean": "mc-s0-report-mean",
            "report_lcb": "mc-s0-report-lcb",
            "uniform_work": "mc-s0-uniform-work",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "Among report_mean/report_lcb, carry forward the larger paired "
            "point estimate only if it is >0 versus reference and > the "
            "equal-work uniform control. This is screen selection, never "
            "production promotion; ties go to report_mean (simpler rule)."),
    },
    "s0b-mean": {
        "seed0": 133_000_000,
        "labels": {
            "adaptive": "mc-s0-adaptive-mean",
            "report_uniform": "mc-s0-report-mean",
            "random": "mc-s0-random-mean",
            "uniform_work": "mc-s0-uniform-work",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "Adaptive replaces report_uniform only if adaptive minus "
            "report_uniform >0 and adaptive minus random >0 by paired point "
            "estimate. Otherwise the S0a rule remains the survivor."),
    },
    "s0b-lcb": {
        "seed0": 134_000_000,
        "labels": {
            "adaptive": "mc-s0-adaptive",
            "report_uniform": "mc-s0-report-lcb",
            "random": "mc-s0-random",
            "uniform_work": "mc-s0-uniform-work",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "Adaptive replaces report_uniform only if adaptive minus "
            "report_uniform >0 and adaptive minus random >0 by paired point "
            "estimate. Otherwise the S0a rule remains the survivor."),
    },
}


def digest(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=1)
    return {key: getattr(bot, key, None) for key in (
        "N_DETERMINIZATIONS", "REQUIRE_EXACT_WORK",
        "EXTRA_SELECTION_WORK", "ADAPTIVE_ALLOCATION", "RANDOM_ALLOCATION",
        "REPORT_FOLD_WORLDS", "REPORT_RULE", "REPORT_MIN_GAIN",
        "REPORT_ALPHA", "REPORT_T_CRITICAL", "MARGIN")}


def protocol_problems(phase: str) -> list[str]:
    spec = PROTOCOLS[phase]
    labels = spec["labels"]
    problems = []
    if labels.get("reference") != OPPONENT:
        problems.append("reference must be the production opponent")
    for label, name in labels.items():
        cfg = policy_contract(name)
        if name.startswith("mc-s0-report") or name.startswith("mc-s0-adaptive") \
                or name.startswith("mc-s0-random"):
            if cfg["REPORT_FOLD_WORLDS"] != S0_REPORT_WORLDS:
                problems.append(f"{label}: report dose drifted to "
                                f"{cfg['REPORT_FOLD_WORLDS']}")
            if not cfg["REQUIRE_EXACT_WORK"]:
                problems.append(f"{label}: exact work is off")
            if cfg["REPORT_MIN_GAIN"] != 0.0:
                problems.append(f"{label}: REPORT_MIN_GAIN is not zero")
        if name == "mc-s0-uniform-work":
            if cfg["EXTRA_SELECTION_WORK"] != 2 * S0_REPORT_WORLDS:
                problems.append("uniform-work control does not match 2R")
    return problems


def record_problems(records: dict[str, list]) -> list[str]:
    problems = []
    expected_keys = None
    for label, recs in records.items():
        keys = {(r["seed"], r["flip"]) for r in recs}
        if len(keys) != len(recs):
            problems.append(f"{label}: duplicate seed/flip records")
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            problems.append(f"{label}: deal coverage differs from other arms")
        for r in recs:
            for side_name in ("arm", "opp"):
                c = r[side_name]
                if c.get("sample_attempts", 0) != (c.get("accepted_worlds", 0)
                                                    + c.get("failed_worlds", 0)):
                    problems.append(f"{label}: sampler counters do not reconcile")
                    break
                if c.get("short_searches", 0):
                    problems.append(f"{label}: short registered search dose")
                    break
                if c.get("zero_world", 0):
                    problems.append(f"{label}: zero-world search")
                    break
    return sorted(set(problems))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=tuple(PROTOCOLS))
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not 0 <= args.shard_index < SHARD_COUNT:
        raise SystemExit("shard-index must satisfy 0 <= i < 8")
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise SystemExit("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise SystemExit("compiled engine requested but not active")
    problems = protocol_problems(args.phase)
    if problems:
        raise SystemExit("S0 policy contract drift:\n  - " + "\n  - ".join(problems))

    sha = git("rev-parse", "HEAD")
    dirty_text = git("status", "--porcelain")
    if dirty_text and not args.smoke:
        raise SystemExit("full S0 shard refuses a dirty tree")
    spec = PROTOCOLS[args.phase]
    clusters = 2 if args.smoke else CLUSTERS_PER_SHARD
    seed0 = (spec["seed0"] + args.shard_index * CLUSTERS_PER_SHARD)
    run_id = (f"{SCHEMA}_{args.phase}_shard{args.shard_index:02d}_"
              f"{sha[:10]}" + ("_SMOKE" if args.smoke else ""))
    out = args.out or f"runs/logs/{run_id}.jsonl"
    manifest_path = out + ".manifest.json"
    for path in (out, out + ".partial", manifest_path,
                 manifest_path + ".partial"):
        if os.path.exists(path):
            raise SystemExit(f"refusing to overwrite {path}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    labels = spec["labels"]
    policies = list(labels.values())
    manifest = {
        "schema": SCHEMA, "phase": args.phase, "run_id": run_id,
        "promotable": not args.smoke, "git_sha": sha,
        "tree_dirty": bool(dirty_text),
        "dirty_files": dirty_text.splitlines() if dirty_text else [],
        "shard_index": args.shard_index, "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS, "clusters": clusters,
        "seed0": seed0, "seed_hi": seed0 + clusters - 1,
        "opponent": OPPONENT, "labels": labels,
        "selection_rule": spec["selection"],
        "report_worlds": S0_REPORT_WORLDS,
        "policy_contracts": {name: policy_contract(name)
                             for name in sorted(set(policies))},
        "ballots": arm_ballots(sorted(set(policies))),
        "digests": {
            "runner": digest(__file__),
            "evaluation": digest(Path(__file__).parents[1] / "shengji" /
                                 "evaluation.py"),
            "mcbot": digest(Path(__file__).parents[1] / "shengji" / "ai" /
                             "mcbot.py"),
            "registry": digest(Path(__file__).parents[1] / "shengji" / "ai" /
                                "registry.py"),
        },
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    with open(manifest_path + ".partial", "x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    records = {}
    with open(out + ".partial", "x") as fh:
        for label, policy in labels.items():
            print(f"\n{label}: {policy} vs {OPPONENT}", flush=True)
            records[label] = run_arm(
                label, policy, OPPONENT, clusters, seed0, fh, run_id)

    problems = record_problems(records)
    manifest["completed"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    manifest["problems"] = problems
    manifest["complete"] = not problems
    manifest["paired_vs_reference"] = {}
    for label, recs in records.items():
        mean, half, n = paired_by_seed(recs, records["reference"])
        manifest["paired_vs_reference"][label] = {
            "mean": mean, "half_width_95": half, "clusters": n}
        print(f"{label:16} {mean:+.3f} +/- {half:.3f} vs reference n={n}")
    with open(manifest_path + ".partial", "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    suffix = "" if not problems else ".FAILED"
    os.replace(out + ".partial", out + suffix)
    os.replace(manifest_path + ".partial", manifest_path + suffix)
    if problems:
        raise SystemExit("S0 shard failed closed:\n  - " + "\n  - ".join(problems))
    print(f"\nrecords: {out}\nmanifest: {manifest_path}")


if __name__ == "__main__":
    main()
