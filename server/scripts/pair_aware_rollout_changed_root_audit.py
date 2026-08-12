#!/usr/bin/env python3
"""Fresh high-N audit of every v1 pair-aware root change.

The whole-round capacity result says v1 changes natural complete-round play,
but it intentionally publishes no utility.  Before spending a large sealed
screen, this reusable exploration takes all nine v1-vs-null changes from the
frozen 192-root dose and re-prices each action pair on fresh common worlds
under both historical and pair-aware continuations.

The roots were selected because finite search changed them.  Fresh worlds can
diagnose whether those selected changes survive more work; nine selected roots
still cannot establish whole-game or population strength.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent

import sys
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import pair_cap_rollout_root_audit as ROOT  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.pair_aware_rollout import make_pair_aware_bot  # noqa: E402


SCHEMA = "pair-aware-rollout-v1-changed-root-audit-v2"
DEFAULT_WORLDS = 4_096
SEED0 = 997_000_000
ATTEMPT_FACTOR = 40
MAX_WORKERS = 8


class V1AuditRefused(RuntimeError):
    """The selected v1 roots cannot support this bounded diagnostic."""


def changed_v1_rows(path: Path = ROOT.DEFAULT_DOSE) -> tuple[dict, list[dict]]:
    if ROOT.sha256(path) != ROOT.EXPECTED_DOSE_SHA256:
        raise V1AuditRefused("incremental-dose input hash drift")
    payload = json.loads(path.read_bytes())
    rows = [row for row in payload["rows"]
            if sorted(row["v1_action"]) != sorted(row["matched_null_action"])]
    if len(rows) != payload["aggregate"]["v1_root_changes"] or len(rows) != 9:
        raise V1AuditRefused("v1 changed-root population drift")
    if len({row["state_id"] for row in rows}) != len(rows):
        raise V1AuditRefused("v1 changed-root identity collision")
    return payload, rows


def _source_sha256s(dose: Path) -> dict[str, str]:
    paths = {
        "audit": SCRIPT,
        "shared_audit": SCRIPT.with_name("pair_cap_rollout_root_audit.py"),
        "dose_script": SCRIPT.with_name("pair_cap_rollout_incremental_dose.py"),
        "dose_artifact": dose,
        "pair_v1": SERVER / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: ROOT.sha256(path) for name, path in sorted(paths.items())}


def audit_root(row: dict, *, n_worlds: int, sample_seed: int) -> dict:
    rnd = ROOT.reconstruct_root(row)
    seat = int(row["seat"])
    incumbent = list(row["matched_null_action"])
    proposal = list(row["v1_action"])
    sampler = make_pair_aware_bot(treatment=True, seed=sample_seed)
    scorers = {
        "historical_matched_null": make_pair_aware_bot(
            treatment=False, seed=0),
        "v1_pair_aware": make_pair_aware_bot(treatment=True, seed=0),
    }
    values = {
        name: {"signed_point_delta": [], "signed_level_utility_delta": []}
        for name in scorers
    }
    memory = Memory(rnd, seat, own_kitty=True)
    before = sampler._sampler_snapshot()
    attempts = 0
    world_stream = hashlib.sha256()
    while len(values["v1_pair_aware"]["signed_point_delta"]) < n_worlds \
            and attempts < n_worlds * ATTEMPT_FACTOR:
        attempts += 1
        sampled = sampler._sample_hands(rnd, seat, memory)
        if sampled is None:
            continue
        hands, buried = sampled
        world_stream.update(ROOT._world_digest(hands, buried).encode())
        for name, scorer in scorers.items():
            point_delta, level_delta = ROOT._score_world(
                scorer, rnd, seat, hands, buried, incumbent, proposal)
            values[name]["signed_point_delta"].append(point_delta)
            values[name]["signed_level_utility_delta"].append(level_delta)
    used = len(values["v1_pair_aware"]["signed_point_delta"])
    if used != n_worlds:
        raise V1AuditRefused(
            f"{row['state_id']}: sampler underfilled {used}/{n_worlds}")
    sampler_work = ROOT._sampler_delta(sampler, before)
    if (sampler_work["accepted_worlds"] != n_worlds
            or sampler_work["sample_attempts"] != (
                sampler_work["accepted_worlds"]
                + sampler_work["failed_worlds"])):
        raise V1AuditRefused(f"{row['state_id']}: sampler work drift")
    true_hands = {other: list(rnd.hands[other]) for other in range(4)
                  if other != seat}
    true_world = {
        name: dict(zip(
            ("signed_point_delta", "signed_level_utility_delta"),
            ROOT._score_world(
                scorer, rnd, seat, true_hands, list(rnd.buried),
                incumbent, proposal),
        )) for name, scorer in scorers.items()
    }
    return {
        "state_id": row["state_id"],
        "deal_seed": row["deal_seed"],
        "completed_tricks": row["completed_tricks"],
        "phase_band": row["phase_band"],
        "role": row["role"],
        "seat": seat,
        "public_state_sha256": row["public_state_sha256"],
        "incumbent_action": incumbent,
        "v1_action": proposal,
        "original_decision_seed": row["decision_seed"],
        "sample_seed": sample_seed,
        "attempts": attempts,
        "sampler_work": sampler_work,
        "world_stream_sha256": world_stream.hexdigest(),
        "by_continuation": {
            name: {metric: ROOT.paired_moments(series)
                   for metric, series in metrics.items()}
            for name, metrics in values.items()
        },
        "generating_world_witness": true_world,
        "continuation_dose": {
            "historical_matched_null": scorers[
                "historical_matched_null"].pair_aware_telemetry(),
            "v1_pair_aware": scorers[
                "v1_pair_aware"].pair_aware_telemetry(),
        },
    }


def _audit_task(index: int, row: dict, n_worlds: int):
    return index, audit_root(
        row, n_worlds=n_worlds,
        sample_seed=SEED0 + index * 1_000_003)


def direction_summary(results: list[dict]) -> dict:
    summary = {}
    for metric in ("signed_level_utility_delta", "signed_point_delta"):
        summary[metric] = {}
        for policy in ("historical_matched_null", "v1_pair_aware"):
            intervals = [root["by_continuation"][policy][metric]
                         ["ci_two_sided_95"] for root in results]
            summary[metric][policy] = {
                "v1_action_positive_roots": sum(
                    low > 0 for low, _ in intervals),
                "incumbent_positive_roots": sum(
                    high < 0 for _, high in intervals),
                "unresolved_roots": sum(
                    low <= 0 <= high for low, high in intervals),
            }
    return summary


def run_audit(*, dose: Path = ROOT.DEFAULT_DOSE,
              n_worlds: int = DEFAULT_WORLDS, workers: int = 4) -> dict:
    if isinstance(n_worlds, bool) or not isinstance(n_worlds, int) \
            or n_worlds < 2 or n_worlds > 16_384:
        raise V1AuditRefused("world count must be an integer in [2, 16384]")
    if isinstance(workers, bool) or not isinstance(workers, int) \
            or not 1 <= workers <= MAX_WORKERS:
        raise V1AuditRefused("workers must be in [1, 8]")
    dose_payload, rows = changed_v1_rows(dose)
    finished = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(rows))) as executor:
        pending = {
            executor.submit(_audit_task, index, row, n_worlds): index
            for index, row in enumerate(rows)
        }
        for future in as_completed(pending):
            index, result = future.result()
            finished[index] = result
            print(json.dumps({
                "event": "pair-v1-changed-root-audit-progress-v1",
                "roots_complete": len(finished),
                "roots_total": len(rows),
                "state_id": result["state_id"],
            }, sort_keys=True), flush=True)
    results = [finished[index] for index in range(len(rows))]
    direction = direction_summary(results)
    payload = {
        "schema": SCHEMA,
        "git": ROOT.git("rev-parse", "HEAD"),
        "tree_dirty": bool(ROOT.git("status", "--porcelain")),
        "runtime": {
            "hostname": platform.node(),
            "python": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
            "workers": workers,
        },
        "source_sha256s": _source_sha256s(dose),
        "design": {
            "input_dose_sha256": ROOT.EXPECTED_DOSE_SHA256,
            "population": "all nine v1-vs-null changes in frozen natural dose",
            "worlds_per_root": n_worlds,
            "common_worlds_across_actions_and_continuation_policies": True,
            "primary_contrast": (
                "acting-team value of v1 action minus matched-null action"),
            "primary_metric": "signed_level_utility_delta",
            "secondary_metric": "signed_point_delta",
            "selection_warning": (
                "roots were selected after finite-search v1 changes; fresh "
                "worlds diagnose those roots but cannot establish population "
                "or whole-game strength"),
        },
        "input_dose_internal_sha256": dose_payload["internal_sha256"],
        "roots": results,
        "direction_summary_by_metric": direction,
        "exploration_only": True,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = ROOT.stable_digest(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dose", type=Path, default=ROOT.DEFAULT_DOSE)
    parser.add_argument("--worlds", type=int, default=DEFAULT_WORLDS)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = run_audit(
        dose=args.dose, n_worlds=args.worlds, workers=args.workers)
    ROOT.write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATION_ONLY",
        "direction_summary_by_metric": payload[
            "direction_summary_by_metric"],
        "output_sha256": ROOT.sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
