#!/usr/bin/env python3
"""Outcome-free S3a sizing receipt on fresh, non-screen states.

The registered S3a mechanism screen uses 136M states.  Timing that population
would expose registered outcomes before the compute decision.  This preflight
instead executes the exact v2 producer on two reserved 151M states, discards
the full records in memory, and persists only elapsed time and work counters.
It cannot authorize strength, a duel, promotion, or production deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT  # noqa: E402
import s3a_bury_pilot as S3A  # noqa: E402


SCHEMA = "s3a-bury-throughput-preflight-v1"
SEED0 = 151_000_000
STATE_COUNT = 2
SEED_HI = SEED0 + STATE_COUNT - 1
SAFETY_FACTOR = 2.0
FULL_STATES = S3A.TOTAL_STATES
STATES_PER_SHARD = S3A.STATES_PER_SHARD
CAP_KEYS = ("screen_fleet_hours", "screen_max_shard_wall_hours")
RECEIPT_KEYS = {
    "schema", "complete", "evidence_grade", "strength_scores_persisted",
    "raw_records_persisted", "registered_screen_states_consumed",
    "git_sha", "runtime_identity", "live_champion_parent", "s3a_schema",
    "states", "seed0", "seed_hi", "wall_seconds", "wall_seconds_by_state",
    "work_totals", "caps", "projections", "criteria", "sizing_admitted",
    "claim_boundary",
}
FORBIDDEN_OUTCOME_KEYS = {
    "arms", "candidates", "cards", "chosen_index", "deltas_vs_incumbent",
    "incumbent_values", "level_utility", "mean_gain_vs_incumbent",
    "raw_winner_index", "records", "selected_values", "stats",
    "values_by_world", "winner", "won",
}


class ProtocolRefused(RuntimeError):
    """The requested timing artifact cannot support the sizing claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=SERVER.parent, capture_output=True,
    ).returncode == 0


def _positive_finite(value, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ProtocolRefused(f"{name} must be a positive finite number")
    return float(value)


def projections(wall_seconds: float) -> dict:
    wall_seconds = _positive_finite(wall_seconds, "preflight wall seconds")
    seconds_per_state = wall_seconds / STATE_COUNT
    return {
        "safety_factor": SAFETY_FACTOR,
        "seconds_per_state": seconds_per_state,
        "screen_fleet_hours": (
            seconds_per_state * FULL_STATES * SAFETY_FACTOR / 3_600),
        "screen_max_shard_wall_hours": (
            seconds_per_state * STATES_PER_SHARD * SAFETY_FACTOR / 3_600),
    }


def criteria(projected: dict, caps: dict) -> dict[str, bool]:
    result = {
        "screen_fleet_hours_within_cap": (
            projected["screen_fleet_hours"] <= caps["screen_fleet_hours"]),
        "screen_shard_wall_within_cap": (
            projected["screen_max_shard_wall_hours"] <=
            caps["screen_max_shard_wall_hours"]),
    }
    result["all"] = all(result.values())
    return result


def _integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolRefused(f"{name} must be a nonnegative integer")
    return value


def score_free_work(records: list[dict]) -> dict:
    """Extract only work accounting; no action or outcome leaves this call."""
    if len(records) != STATE_COUNT:
        raise ProtocolRefused(
            f"preflight produced {len(records)} states, expected {STATE_COUNT}")
    expected_seeds = list(range(SEED0, SEED_HI + 1))
    observed_seeds = [record.get("deal_seed") for record in records]
    if observed_seeds != expected_seeds:
        raise ProtocolRefused("preflight fresh state coverage drifted")
    if any(record.get("champion") != LIVE_PARENT.CHAMPION_POLICY
           for record in records):
        raise ProtocolRefused("preflight state used the wrong champion")

    candidate_worlds = {arm: 0 for arm in S3A.ARMS}
    folds = {
        name: {
            "requested_worlds": 0,
            "sample_attempts": 0,
            "accepted_worlds": 0,
            "failed_worlds": 0,
            "rejected_worlds": 0,
            "impossible_worlds": 0,
        }
        for name in ("selection", "report")
    }
    for record in records:
        arms = record.get("arms")
        named_folds = record.get("folds")
        if not isinstance(arms, dict) or not isinstance(named_folds, dict):
            raise ProtocolRefused("preflight state lacks work accounting")
        for arm in S3A.ARMS:
            work = arms.get(arm, {}).get("work", {})
            if work.get("complete") is not True:
                raise ProtocolRefused(f"{arm}: incomplete exact work")
            candidate_worlds[arm] += _integer(
                work.get("total_candidate_worlds"),
                f"{arm} total candidate worlds")
        for fold_name in folds:
            fold = named_folds.get(fold_name, {})
            counters = fold.get("sampler_counters", {})
            folds[fold_name]["requested_worlds"] += _integer(
                fold.get("requested_worlds"),
                f"{fold_name} requested worlds")
            for field in (
                    "sample_attempts", "accepted_worlds", "failed_worlds",
                    "rejected_worlds", "impossible_worlds"):
                folds[fold_name][field] += _integer(
                    counters.get(field), f"{fold_name} {field}")
    if len(set(candidate_worlds.values())) != 1:
        raise ProtocolRefused("S3a arms consumed unequal candidate-world work")
    for fold_name, totals in folds.items():
        if (totals["accepted_worlds"] != totals["requested_worlds"]
                or totals["sample_attempts"] != totals["accepted_worlds"]
                or any(totals[field] for field in (
                    "failed_worlds", "rejected_worlds", "impossible_worlds"))):
            raise ProtocolRefused(
                f"{fold_name}: sampler work is not exact and failure-free")
    return {
        "states": STATE_COUNT,
        "candidate_worlds_by_arm": candidate_worlds,
        "folds": folds,
    }


def _forbidden_receipt_keys(value, path: str = "") -> list[str]:
    problems = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            child_path = f"{path}.{key}" if path else str(key)
            if lowered in FORBIDDEN_OUTCOME_KEYS:
                problems.append(child_path)
            problems += _forbidden_receipt_keys(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems += _forbidden_receipt_keys(child, f"{path}[{index}]")
    return problems


def receipt_problems(payload: object, *, parent: dict, runtime: dict,
                     head: str, ancestry_checker=None) -> list[str]:
    if not isinstance(payload, dict):
        return ["throughput receipt is not an object"]
    problems = []
    if ancestry_checker is None:
        ancestry_checker = git_is_ancestor
    if set(payload) != RECEIPT_KEYS:
        problems.append("throughput receipt field set drifted")
    fixed = {
        "schema": SCHEMA,
        "complete": True,
        "evidence_grade": False,
        "strength_scores_persisted": False,
        "raw_records_persisted": False,
        "registered_screen_states_consumed": False,
        "runtime_identity": runtime,
        "live_champion_parent": parent,
        "s3a_schema": S3A.SCHEMA,
        "states": STATE_COUNT,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
    }
    for key, value in fixed.items():
        if payload.get(key) != value:
            problems.append(f"throughput receipt fixed field drift: {key}")
    receipt_head = payload.get("git_sha")
    if (not isinstance(receipt_head, str) or len(receipt_head) != 40
            or any(char not in "0123456789abcdef" for char in receipt_head)
            or not ancestry_checker(receipt_head, head)):
        problems.append("throughput receipt git is not an ancestor of verifier")
    problems += [f"live parent: {problem}"
                 for problem in LIVE_PARENT.parent_problems(parent)]
    wall = payload.get("wall_seconds")
    by_state = payload.get("wall_seconds_by_state")
    if (isinstance(wall, bool) or not isinstance(wall, (int, float))
            or not math.isfinite(wall) or wall <= 0
            or not isinstance(by_state, list) or len(by_state) != STATE_COUNT
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(value) or value <= 0
                   for value in by_state)
            or sum(by_state) > wall * 1.001):
        problems.append("throughput receipt wall-time accounting")
    caps = payload.get("caps")
    if not isinstance(caps, dict) or tuple(sorted(caps)) != tuple(sorted(CAP_KEYS)):
        problems.append("throughput receipt cap schema")
    else:
        try:
            normalized_caps = {
                key: _positive_finite(caps[key], key) for key in CAP_KEYS}
        except ProtocolRefused as exc:
            problems.append(str(exc))
        else:
            try:
                projected = projections(wall)
                decided = criteria(projected, normalized_caps)
            except (ProtocolRefused, KeyError, TypeError) as exc:
                problems.append(f"throughput projection: {exc}")
            else:
                if payload.get("projections") != projected:
                    problems.append("throughput projection arithmetic drifted")
                if payload.get("criteria") != decided:
                    problems.append("throughput capacity decision drifted")
                if payload.get("sizing_admitted") is not decided["all"]:
                    problems.append("throughput admission bit drifted")
    forbidden = _forbidden_receipt_keys(payload)
    if forbidden:
        problems.append(
            "throughput receipt persists forbidden outcome fields: " +
            ", ".join(forbidden[:5]))
    return sorted(set(problems))


def run_preflight(args) -> dict:
    parent, runtime, head = S3A.require_real_context()
    caps = {
        "screen_fleet_hours": _positive_finite(
            args.screen_fleet_hour_cap, "screen fleet-hour cap"),
        "screen_max_shard_wall_hours": _positive_finite(
            args.screen_shard_wall_hour_cap, "screen shard-wall cap"),
    }
    records = []
    wall_by_state = []
    started = time.perf_counter()
    for offset, seed in enumerate(range(SEED0, SEED_HI + 1), start=1):
        print(
            f"S3a throughput-only: starting {offset}/{STATE_COUNT}; "
            "strength outcomes hidden",
            flush=True,
        )
        state_started = time.perf_counter()
        records.append(S3A.run_state(seed, parent["champion_policy"]))
        wall_by_state.append(time.perf_counter() - state_started)
        print(
            f"S3a throughput-only: completed {offset}/{STATE_COUNT}; "
            "strength outcomes hidden",
            flush=True,
        )
    wall = time.perf_counter() - started
    work = score_free_work(records)
    # The full records contain the timing states' actions and outcomes.  They
    # are deliberately neither returned nor serialized.
    del records
    projected = projections(wall)
    decided = criteria(projected, caps)
    receipt = {
        "schema": SCHEMA,
        "complete": True,
        "evidence_grade": False,
        "strength_scores_persisted": False,
        "raw_records_persisted": False,
        "registered_screen_states_consumed": False,
        "git_sha": head,
        "runtime_identity": runtime,
        "live_champion_parent": parent,
        "s3a_schema": S3A.SCHEMA,
        "states": STATE_COUNT,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "wall_seconds": wall,
        "wall_seconds_by_state": wall_by_state,
        "work_totals": work,
        "caps": caps,
        "projections": projected,
        "criteria": decided,
        "sizing_admitted": decided["all"],
        "claim_boundary": (
            "Outcome-free operational sizing on fresh 151M states only; no "
            "registered 136M state, strength claim, duel, promotion or deploy."
        ),
    }
    problems = receipt_problems(
        receipt, parent=parent, runtime=runtime, head=head)
    if problems:
        raise ProtocolRefused("; ".join(problems))
    S3A.atomic_json_exclusive(args.out, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return receipt


def load_receipt(path: os.PathLike | str, expected_sha256: str, *,
                 parent: dict, runtime: dict, head: str) -> dict:
    path = Path(path).resolve()
    if (not path.is_file() or not is_sha256(expected_sha256)
            or sha256(path) != expected_sha256):
        raise ProtocolRefused("throughput receipt digest mismatch")
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"throughput receipt unreadable: {exc}") from exc
    problems = receipt_problems(
        payload, parent=parent, runtime=runtime, head=head)
    if problems:
        raise ProtocolRefused("; ".join(problems))
    return payload


def verify_receipt(args) -> dict:
    parent, runtime, head = S3A.require_real_context()
    payload = load_receipt(
        args.receipt, args.expected_receipt_sha256,
        parent=parent, runtime=runtime, head=head)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    run.add_argument("--screen-fleet-hour-cap", type=float, required=True)
    run.add_argument("--screen-shard-wall-hour-cap", type=float, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--expected-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "run":
        run_preflight(args)
    else:
        verify_receipt(args)


if __name__ == "__main__":
    try:
        main()
    except (ProtocolRefused, S3A.ProtocolRefused) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
