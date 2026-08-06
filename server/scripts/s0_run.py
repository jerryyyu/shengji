"""Fail-closed, sharded S0 mechanism screen and confirmation.

S0a separates the report decision rule from extra compute. S0b (run only after
S0a chooses a rule) separates deterministic adaptive allocation from its
random-allocation attribution control. S0c confirms exactly the survivor named
by S0b on an independent 8,192-cluster block. Every label in a shard plays the
same mirrored deals against the same production `mc-strong` opponent.

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
import platform
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.registry import S0_REPORT_WORLDS, make_bot  # noqa: E402
from shengji.evaluation import (arm_ballots, paired_by_seed,  # noqa: E402
                                run_arm)


SCHEMA = "s0-protocol-v2"
SHARD_COUNT = 8
TOTAL_CLUSTERS = 2048
CLUSTERS_PER_SHARD = TOTAL_CLUSTERS // SHARD_COUNT
CONFIRM_CLUSTERS = 8192
OPPONENT = "mc-strong"

PROTOCOLS = {
    "s0a": {
        "kind": "screen",
        "seed0": 132_000_000,
        "total_clusters": TOTAL_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": None,
        "parent_policy": None,
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
        "kind": "screen",
        "seed0": 133_000_000,
        "total_clusters": TOTAL_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0a",
        "parent_policy": "mc-s0-report-mean",
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
        "kind": "screen",
        "seed0": 134_000_000,
        "total_clusters": TOTAL_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0a",
        "parent_policy": "mc-s0-report-lcb",
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
    # Exactly one confirmation protocol may run: the one whose arm matches the
    # survivor in the bound S0b aggregate. All four possibilities are frozen
    # before S0a is inspected, and share one untouched seed block because only
    # one can be admitted by the parent gate.
    "s0c-report-mean": {
        "kind": "confirmation",
        "seed0": 135_000_000,
        "total_clusters": CONFIRM_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0b-mean",
        "parent_policy": "mc-s0-report-mean",
        "labels": {
            "arm": "mc-s0-report-mean",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "PROMOTE only if arm-reference and arm-null paired two-sided 95% "
            "lower bounds are both >0 and the mc-strong null-reference lower "
            "bound is <=0, over exactly 8,192 fresh seed clusters."),
    },
    "s0c-report-lcb": {
        "kind": "confirmation",
        "seed0": 135_000_000,
        "total_clusters": CONFIRM_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0b-lcb",
        "parent_policy": "mc-s0-report-lcb",
        "labels": {
            "arm": "mc-s0-report-lcb",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "PROMOTE only if arm-reference and arm-null paired two-sided 95% "
            "lower bounds are both >0 and the mc-strong null-reference lower "
            "bound is <=0, over exactly 8,192 fresh seed clusters."),
    },
    "s0c-adaptive-mean": {
        "kind": "confirmation",
        "seed0": 135_000_000,
        "total_clusters": CONFIRM_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0b-mean",
        "parent_policy": "mc-s0-adaptive-mean",
        "labels": {
            "arm": "mc-s0-adaptive-mean",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "PROMOTE only if arm-reference and arm-null paired two-sided 95% "
            "lower bounds are both >0 and the mc-strong null-reference lower "
            "bound is <=0, over exactly 8,192 fresh seed clusters."),
    },
    "s0c-adaptive-lcb": {
        "kind": "confirmation",
        "seed0": 135_000_000,
        "total_clusters": CONFIRM_CLUSTERS,
        "shard_count": SHARD_COUNT,
        "parent_phase": "s0b-lcb",
        "parent_policy": "mc-s0-adaptive",
        "labels": {
            "arm": "mc-s0-adaptive",
            "null": "mc-strong-null",
            "reference": "mc-strong",
        },
        "selection": (
            "PROMOTE only if arm-reference and arm-null paired two-sided 95% "
            "lower bounds are both >0 and the mc-strong null-reference lower "
            "bound is <=0, over exactly 8,192 fresh seed clusters."),
    },
}


def phase_shard_count(phase: str) -> int:
    return int(PROTOCOLS[phase]["shard_count"])


def phase_total_clusters(phase: str) -> int:
    return int(PROTOCOLS[phase]["total_clusters"])


def phase_clusters_per_shard(phase: str) -> int:
    total = phase_total_clusters(phase)
    count = phase_shard_count(phase)
    if total % count:
        raise ValueError(f"{phase}: {total} clusters do not divide {count} shards")
    return total // count


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
    if phase_total_clusters(phase) % phase_shard_count(phase):
        problems.append("total clusters do not divide the shard count")
    if labels.get("reference") != OPPONENT:
        problems.append("reference must be the production opponent")
    if spec["kind"] == "confirmation":
        if set(labels) != {"arm", "null", "reference"}:
            problems.append("confirmation labels must be arm/null/reference")
        if labels.get("null") != "mc-strong-null":
            problems.append("confirmation null must be mc-strong-null")
        if labels.get("arm") != spec.get("parent_policy"):
            problems.append("confirmation arm must equal its parent survivor")
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


def parent_identity(path: str | None, spec: dict, sha: str) -> dict | None:
    """Bind a child phase to the machine-readable aggregate that admitted it."""
    want_phase = spec.get("parent_phase")
    if want_phase is None:
        if path:
            raise SystemExit("s0a has no parent; refuse an accidental parent")
        return None
    if not path:
        raise SystemExit(f"{want_phase} aggregate is required via --parent")
    try:
        with open(path) as fh:
            parent = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read parent aggregate {path}: {exc}") from exc
    expected = {
        "schema": "s0-mechanism-aggregate-v1",
        "phase": want_phase,
        "survivor_policy": spec.get("parent_policy"),
        "git_sha": sha,
        "clusters": TOTAL_CLUSTERS,
    }
    drift = [f"{key}={parent.get(key)!r}, expected {value!r}"
             for key, value in expected.items() if parent.get(key) != value]
    if parent.get("promotion") is not False:
        drift.append("parent mechanism screen must have promotion=false")
    if drift:
        raise SystemExit("parent aggregate does not admit this phase:\n  - " +
                         "\n  - ".join(drift))
    return {
        "sha256": digest(path), "schema": parent["schema"],
        "phase": parent["phase"], "git_sha": parent["git_sha"],
        "clusters": parent.get("clusters"),
        "survivor_label": parent.get("survivor_label"),
        "survivor_policy": parent["survivor_policy"],
    }


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
                if c.get("void_fallbacks", 0):
                    problems.append(f"{label}: void-relaxed sampled world")
                    break
    return sorted(set(problems))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=tuple(PROTOCOLS))
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--parent", default=None,
                    help="aggregate that machine-admitted this child phase")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    spec = PROTOCOLS[args.phase]
    shard_count = phase_shard_count(args.phase)
    clusters_per_shard = phase_clusters_per_shard(args.phase)
    if not 0 <= args.shard_index < shard_count:
        raise SystemExit(f"shard-index must satisfy 0 <= i < {shard_count}")
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
    parent = parent_identity(args.parent, spec, sha)
    clusters = 2 if args.smoke else clusters_per_shard
    seed0 = spec["seed0"] + args.shard_index * clusters_per_shard
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
        "host": os.uname().nodename, "python": platform.python_version(),
        "fast_engine": True, "require_voids": True,
        "kind": spec["kind"], "parent": parent,
        "shard_index": args.shard_index, "shard_count": shard_count,
        "total_clusters": phase_total_clusters(args.phase),
        "clusters": clusters,
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
            "fast_router": digest(fast.__file__),
            "fast_binary": digest(fast._fast.__file__),
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
