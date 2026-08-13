#!/usr/bin/env python3
"""Telemetry-only capacity probe for the opened bury/S6 DEV workbench.

Reconstruct opened DEV, make its reviewed 32-shape + 32-anchor selection, choose
the widest ballot, and time one common world across all three continuation
modes. Values are discarded; only work/timing/dose/identity are published.
Normal review is the gate: no PASS parser, admission, or deploy authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))
import bury_lead_combo_dev_journal as JOURNAL  # noqa: E402
import bury_lead_combo_exploration as EXPLORE  # noqa: E402
import bury_lead_combo_population as POPULATION  # noqa: E402
from shengji.ai import throw_rollout as CONTINUATION  # noqa: E402

SCHEMA = "bury-lead-combo-capacity-exploration-v1"
MODES = CONTINUATION.S6_CONTINUATION_MODES
BASE_SEED = 20_260_813
ATTEMPT_FACTOR = 20
MAX_COMBOS = 1_088
EXPECTED_PYTHON = "3.14.4"
RUNTIME_FIELDS = frozenset({
    "git", "tree_dirty", "python", "fast_binary_sha256",
    "population_source_sha256", "scorer_source_sha256",
    "continuation_source_sha256", "journal_source_sha256",
    "controller_source_sha256",
})
SELECTION_FIELDS = frozenset({
    "population_id", "census_states", "shape_rich_states",
    "hash_uniform_anchor_states", "selected_states", "selection_sha256",
    "selection_rows_sha256", "widest_state_sha256",
})
WORK_FIELDS = frozenset({
    "worlds_requested", "worlds_used", "attempts", "attempt_cap",
    "candidate_rollouts", "requested_candidate_rollouts",
    "candidate_rollout_cap", "common_worlds", "complete",
})
SAMPLER_FIELDS = frozenset({
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
})
DOSE_FIELDS = frozenset({
    "schema", "mode", "deterministic", "actor_visible", "recursive_mc",
    "exploration_only", "before", "after", "delta",
})
ARM_FIELDS = frozenset({
    "mode", "state_id", "deal_seed", "candidate_count", "ballot_sha256",
    "pre_rng_sha256", "post_rng_sha256", "sampled_world_commitment",
    "elapsed_seconds", "work", "sampler_delta", "continuation_dose",
    "raw_candidate_values_discarded",
})
RESULT_FIELDS = frozenset({
    "schema", "runtime", "selection", "capacity_state", "arms",
    "capacity_complete", "candidate_rollouts", "total_arm_seconds",
    "telemetry_only", "opened_reusable_dev", "source_outcomes_read",
    "outcomes_published",
    "confirmatory_inference", "strength_claim",
    "production_promotion", "production_deployment", "internal_sha256",
})
FORBIDDEN_KEYS = frozenset({
    "hands", "buried", "sampled_buried", "bury_cards", "lead_cards",
    "candidates", "rng_state", "world_values", "attacker_points",
    "winner", "winner_team", "utility", "mean_banker_value",
    "raw_winner_index", "raw_gap_vs_candidate_zero",
    "paired_gap_vs_candidate_zero", "paired_se_vs_candidate_zero",
})
class CapacityRefused(RuntimeError):
    """The diagnostic cannot honor its telemetry-only contract."""
def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=list).encode()
def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()
def _sha256(path: Path) -> str:
    return JOURNAL.sha256_file(path)
def _hex(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))
def _git_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))
def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0
def _row_problems(row: object) -> list[str]:
    if not isinstance(row, Mapping) or set(row) != POPULATION.SELECTION_ROW_KEYS:
        return ["capacity row fields"]
    seed, count = row.get("deal_seed"), row.get("combo_count")
    if (not _nonnegative_int(seed)
            or not POPULATION.DEAL_SEED0 <= seed <
            POPULATION.DEAL_SEED0 + POPULATION.POPULATION_STATES
            or not _nonnegative_int(count) or not 1 <= count <= MAX_COMBOS):
        return ["capacity row numeric identity"]
    state_prefix = f"{POPULATION.POPULATION_ID}:deal:{seed}:banker:"
    source_prefix = f"s3a-bury-pilot-v2:deal:{seed}:banker:"
    state_id, source_id = row.get("state_id"), row.get("source_state_id")
    group, reason = row.get("selection_group"), row.get("selection_reason")
    if (not isinstance(state_id, str) or not state_id.startswith(state_prefix)
            or state_id.removeprefix(state_prefix) not in {"0", "1", "2", "3"}
            or source_id != source_prefix + state_id.removeprefix(state_prefix)
            or group not in {"shape_rich", "hash_uniform_anchor"}
            or (group == "shape_rich" and reason not in POPULATION.METRICS)
            or (group == "hash_uniform_anchor"
                and reason != "uniform_anchor")):
        return ["capacity row semantic identity"]
    return []
def _forbidden(value: object, path: str = "$") -> list[str]:
    problems = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                problems.append(f"forbidden field {path}.{key}")
            problems.extend(_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(_forbidden(child, f"{path}[{index}]"))
    return problems
def _write_exclusive(path: Path, value: Mapping[str, object]) -> None:
    """Atomically publish one artifact, refusing links and overwrites."""
    if os.path.lexists(path):
        raise CapacityRefused(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temp.open("xb") as handle:
            handle.write(_canonical(dict(value)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)
    except FileExistsError as exc:
        raise CapacityRefused(f"concurrent writer owns {path}") from exc
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

def _runtime(expected_git: str) -> dict:
    if not _git_sha(expected_git):
        raise CapacityRefused("expected Git is not a full lowercase SHA")
    try:
        runtime = dict(JOURNAL.strict_runtime())
    except JOURNAL.JournalRefused as exc:
        raise CapacityRefused(str(exc)) from exc
    runtime["controller_source_sha256"] = _sha256(SCRIPT)
    if (set(runtime) != RUNTIME_FIELDS
            or runtime.get("tree_dirty") is not False
            or runtime.get("git") != expected_git
            or runtime.get("python") != EXPECTED_PYTHON):
        raise CapacityRefused("runtime identity field drift")
    for field in RUNTIME_FIELDS - {"git", "tree_dirty", "python"}:
        if not _hex(runtime.get(field)):
            raise CapacityRefused(f"runtime {field} is not a digest")
    return runtime

def _selection() -> tuple[dict, dict]:
    rows = [
        POPULATION.census_state(seed)
        for seed in range(
            POPULATION.DEAL_SEED0,
            POPULATION.DEAL_SEED0 + POPULATION.POPULATION_STATES)
    ]
    selection = POPULATION.select_dev_states(rows)
    problems = POPULATION.selection_problems(selection)
    if problems:
        raise CapacityRefused("; ".join(problems))
    selected = selection["selection"]
    if (selected["shape_rich"] != 32
            or selected["hash_uniform_anchor"] != 32
            or selected["total"] != 64):
        raise CapacityRefused("selection is not the reviewed 32+32 slice")
    summary = {
        "population_id": POPULATION.POPULATION_ID,
        "census_states": POPULATION.POPULATION_STATES,
        "shape_rich_states": 32,
        "hash_uniform_anchor_states": 32,
        "selected_states": 64,
        "selection_sha256": _digest(selection),
        "selection_rows_sha256": selected["rows_sha256"],
    }
    row = dict(min(
        selected["rows"],
        key=lambda item: (-int(item["combo_count"]), str(item["state_id"]))))
    problems = _row_problems(row)
    if problems:
        raise CapacityRefused("; ".join(problems))
    summary["widest_state_sha256"] = _digest(row)
    return summary, row

def _capture_samples(bot) -> list[str]:
    original = bot._sample_hands
    commitments: list[str] = []

    def wrapped(rnd, seat, memory):
        sampled = original(rnd, seat, memory)
        if sampled is not None:
            hands, buried = sampled
            if buried:
                raise CapacityRefused(
                    "pre-bury sampler exposed a hidden kitty")
            commitments.append(_digest({"hands": hands, "buried": []}))
        return sampled

    bot._sample_hands = wrapped
    return commitments

def _dose_problems(dose: object, mode: str) -> list[str]:
    if not isinstance(dose, Mapping) or set(dose) != DOSE_FIELDS:
        return [f"{mode} continuation-dose fields"]
    problems = []
    expected = {
        "schema": "s6-throw-rollout-dose-v1",
        "mode": mode,
        "deterministic": True,
        "actor_visible": True,
        "recursive_mc": False,
        "exploration_only": True,
    }
    if any(dose.get(key) != value for key, value in expected.items()):
        problems.append(f"{mode} continuation contract")
    before = dose.get("before")
    after = dose.get("after")
    delta = dose.get("delta")
    if mode == "baseline":
        if (before, after, delta) != (None, None, None):
            problems.append("baseline continuation counters")
    else:
        fields = set(CONTINUATION.S6_ROLLOUT_COUNTER_FIELDS)
        if any(not isinstance(item, Mapping) or set(item) != fields
               for item in (before, after, delta)):
            problems.append(f"{mode} continuation counter fields")
        else:
            if any(not _nonnegative_int(value)
                   for item in (before, after, delta)
                   for value in item.values()):
                problems.append(f"{mode} continuation counter values")
            elif any(before[name] != 0 for name in fields):
                problems.append(f"{mode} continuation counter origin")
            elif (any(delta[name] != after[name] for name in fields)
                  or any(delta[name] != after[name] - before[name]
                         for name in fields)):
                problems.append(f"{mode} continuation counter delta")
            else:
                try:
                    CONTINUATION.S6ThrowRolloutPolicy._validate(dict(delta))
                except AssertionError:
                    problems.append(f"{mode} continuation reconciliation")
                if delta.get("play_calls", 0) <= 0:
                    problems.append(f"{mode} continuation did not execute")
    return problems

def _work_problems(work: object, sampler: object, count: int) -> list[str]:
    if (not isinstance(work, Mapping) or set(work) != WORK_FIELDS
            or not isinstance(sampler, Mapping)
            or set(sampler) != SAMPLER_FIELDS):
        return ["work/sampler fields"]
    numeric = [work[key] for key in (
        "worlds_requested", "worlds_used", "attempts", "attempt_cap",
        "candidate_rollouts", "requested_candidate_rollouts",
        "candidate_rollout_cap",
    )] + list(sampler.values())
    expected = {
        "worlds_requested": 1, "worlds_used": 1,
        "attempt_cap": ATTEMPT_FACTOR, "candidate_rollouts": count,
        "requested_candidate_rollouts": count, "candidate_rollout_cap": count,
        "common_worlds": True, "complete": True,
    }
    problems = []
    if any(not _nonnegative_int(value) for value in numeric) \
            or any(work.get(key) != value for key, value in expected.items()):
        problems.append("exact work")
    if (work.get("attempts", -1) > ATTEMPT_FACTOR
            or sampler.get("accepted_worlds") != 1
            or sampler.get("sample_attempts") != work.get("attempts")
            or sampler.get("sample_attempts") !=
            sampler.get("accepted_worlds", 0) + sampler.get("failed_worlds", 0)
            or sampler.get("rejected_worlds", 0) >
            sampler.get("failed_worlds", 0)
            or sampler.get("impossible_worlds") != 0):
        problems.append("sampler reconciliation")
    return problems

def _measure(mode: str, row: Mapping[str, object], *,
             scorer: Callable = EXPLORE.score_state,
             clock: Callable[[], float] = time.monotonic) -> dict:
    problems = _row_problems(row)
    if problems:
        raise CapacityRefused("; ".join(problems))
    seed = int(row["deal_seed"])
    rnd, incumbent, _ = POPULATION.build_bury_state(seed, POPULATION.CHAMPION)
    if rnd.banker is None or rnd.phase != "bury":
        raise CapacityRefused("capacity reconstruction lost acting banker")
    if str(row["state_id"]).rsplit(":", 1)[-1] != str(rnd.banker):
        raise CapacityRefused("capacity row banker differs from reconstruction")
    bot = POPULATION.make_bot(
        POPULATION.CHAMPION,
        seed=JOURNAL.state_rng_seed(str(row["state_id"]), BASE_SEED))
    commitments = _capture_samples(bot)
    started = clock()
    raw = scorer(
        rnd, rnd.banker, bot=bot, incumbent_bury=incumbent, worlds=1,
        attempt_factor=ATTEMPT_FACTOR,
        max_candidate_rollouts=int(row["combo_count"]),
        continuation_mode=mode)
    elapsed = clock() - started
    work = raw.get("work")
    sampler = raw.get("sampler_counters")
    scoring = raw.get("scoring_contract")
    dose = raw.get("continuation_dose")
    count = int(row["combo_count"])
    scoring_fields = {
        "bot_class", "baseline_rollout_policy_class", "continuation_mode",
        "continuation_policy_class", "continuation_actor_visible",
        "recursive_mc_continuation", "level_objective", "exact_endgame",
        "perspective",
    }
    expected_policy = (
        "HeuristicBot" if mode == "baseline" else "S6ThrowRolloutPolicy")
    if (raw.get("schema") != EXPLORE.SCHEMA
            or raw.get("status") != "COMPLETE_EXPLORATION"
            or raw.get("candidate_count") != count
            or not isinstance(scoring, Mapping)
            or set(scoring) != scoring_fields
            or scoring.get("continuation_mode") != mode
            or scoring.get("bot_class") != "MCS0ReportLCB"
            or scoring.get("baseline_rollout_policy_class") != "HeuristicBot"
            or scoring.get("continuation_policy_class") != expected_policy
            or scoring.get("continuation_actor_visible") is not True
            or scoring.get("recursive_mc_continuation") is not False
            or scoring.get("level_objective") is not False
            or scoring.get("exact_endgame") is not False
            or scoring.get("perspective") !=
            "banker_value_is_negative_attacker_objective"
            or len(commitments) != 1
            or not isinstance(sampler, Mapping)
            or set(sampler) != {"before", "after", "delta"}
            or not isinstance(sampler.get("delta"), Mapping)
            or _work_problems(work, sampler.get("delta"), count)
            or not isinstance(elapsed, (int, float))
            or isinstance(elapsed, bool)
            or not math.isfinite(elapsed) or elapsed < 0):
        raise CapacityRefused(f"{mode} capacity contract drift")
    problems = _dose_problems(dose, mode)
    if problems:
        raise CapacityRefused("; ".join(problems))
    arm = {
        "mode": mode,
        "state_id": row["state_id"],
        "deal_seed": seed,
        "candidate_count": count,
        "ballot_sha256": _digest(raw["ballot"]),
        "pre_rng_sha256": _digest(raw["rng_state"]),
        "post_rng_sha256": _digest(bot.rng.getstate()),
        "sampled_world_commitment": commitments[0],
        "elapsed_seconds": float(elapsed),
        "work": dict(work),
        "sampler_delta": dict(sampler["delta"]),
        "continuation_dose": dict(dose),
        "raw_candidate_values_discarded": count,
    }
    if set(arm) != ARM_FIELDS or _forbidden(arm):
        raise CapacityRefused(f"{mode} telemetry output drift")
    return arm

def result_problems(value: object, *, expected_git: str | None = None) \
        -> list[str]:
    if not isinstance(value, Mapping):
        return ["result is not an object"]
    problems = _forbidden(value)
    if set(value) != RESULT_FIELDS or value.get("schema") != SCHEMA:
        problems.append("result fields or schema")
    material = dict(value)
    digest = material.pop("internal_sha256", None)
    if digest != _digest(material):
        problems.append("result digest")
    expected = {
        "capacity_complete": True, "telemetry_only": True,
        "opened_reusable_dev": True, "source_outcomes_read": False,
        "outcomes_published": False, "confirmatory_inference": False,
        "strength_claim": False, "production_promotion": False,
        "production_deployment": False,
    }
    if any(value.get(key) is not target for key, target in expected.items()):
        problems.append("authority boundary")
    runtime, selection, row, arms = (
        value.get("runtime"), value.get("selection"),
        value.get("capacity_state"), value.get("arms"))
    if (not isinstance(runtime, Mapping) or set(runtime) != RUNTIME_FIELDS
            or runtime.get("tree_dirty") is not False
            or (expected_git is not None and runtime.get("git") != expected_git)
            or runtime.get("python") != EXPECTED_PYTHON
            or not _git_sha(runtime.get("git"))
            or any(not _hex(runtime.get(field)) for field in RUNTIME_FIELDS
                   - {"git", "tree_dirty", "python"})):
        problems.append("runtime fields")
    if (not isinstance(selection, Mapping)
            or set(selection) != SELECTION_FIELDS
            or selection.get("population_id") != POPULATION.POPULATION_ID
            or selection.get("census_states") != POPULATION.POPULATION_STATES
            or selection.get("shape_rich_states") != 32
            or selection.get("hash_uniform_anchor_states") != 32
            or selection.get("selected_states") != 64
            or not _hex(selection.get("selection_sha256"))
            or not _hex(selection.get("selection_rows_sha256"))
            or selection.get("widest_state_sha256") != _digest(row)):
        problems.append("selection fields")
    count = row.get("combo_count") if isinstance(row, Mapping) else None
    if _row_problems(row):
        problems.append("capacity state")
    if (not isinstance(arms, list) or len(arms) != len(MODES)
            or any(not isinstance(arm, Mapping) or set(arm) != ARM_FIELDS
                   for arm in arms)):
        problems.append("arm fields")
        return sorted(set(problems))
    if [arm["mode"] for arm in arms] != list(MODES):
        problems.append("arm order")
    for field in (
            "state_id", "deal_seed", "candidate_count", "ballot_sha256",
            "pre_rng_sha256", "post_rng_sha256", "sampled_world_commitment",
            "work", "sampler_delta"):
        if len({_digest(arm[field]) for arm in arms}) != 1:
            problems.append(f"common-world {field}")
    for mode, arm in zip(MODES, arms, strict=True):
        work, sampler = arm["work"], arm["sampler_delta"]
        arm_elapsed = arm.get("elapsed_seconds")
        if (arm["mode"] != mode or arm["state_id"] != row.get("state_id")
                or arm["deal_seed"] != row.get("deal_seed")
                or arm["candidate_count"] != count
                or _work_problems(work, sampler, count)
                or any(not _hex(arm[field]) for field in (
                    "ballot_sha256", "pre_rng_sha256", "post_rng_sha256",
                    "sampled_world_commitment"))
                or not isinstance(arm_elapsed, (int, float))
                or isinstance(arm_elapsed, bool)
                or not math.isfinite(arm_elapsed) or arm_elapsed < 0
                or arm["raw_candidate_values_discarded"] != count
                or _dose_problems(arm["continuation_dose"], mode)):
            problems.append(f"{mode} arm contract")
    if value.get("candidate_rollouts") != len(MODES) * count:
        problems.append("candidate rollout total")
    elapsed = value.get("total_arm_seconds")
    if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
            or not math.isfinite(elapsed)
            or elapsed != sum(float(arm["elapsed_seconds"]) for arm in arms)):
        problems.append("elapsed total")
    return sorted(set(problems))

def build_result(expected_git: str, *, measure: Callable = _measure) -> dict:
    runtime = _runtime(expected_git)
    selection, row = _selection()
    arms = []
    for mode in MODES:
        print(json.dumps({"stage": "capacity", "mode": mode}),
              file=sys.stderr, flush=True)
        arms.append(measure(mode, row))
    value = {
        "schema": SCHEMA,
        "runtime": runtime,
        "selection": selection,
        "capacity_state": row,
        "arms": arms,
        "capacity_complete": True,
        "candidate_rollouts": len(MODES) * int(row["combo_count"]),
        "total_arm_seconds": sum(float(arm["elapsed_seconds"]) for arm in arms),
        "telemetry_only": True,
        "opened_reusable_dev": True,
        "source_outcomes_read": False,
        "outcomes_published": False,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = _digest(value)
    problems = result_problems(value, expected_git=expected_git)
    if problems:
        raise CapacityRefused("; ".join(problems))
    return value

def run(output: Path, expected_git: str, *,
        build: Callable[[], dict] | None = None) -> dict:
    if os.path.lexists(output):
        raise CapacityRefused(f"refusing to overwrite {output}")
    value = build_result(expected_git) if build is None else build()
    problems = result_problems(value, expected_git=expected_git)
    if problems:
        raise CapacityRefused("; ".join(problems))
    _write_exclusive(output, value)
    return value

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-git", required=True)
    args = parser.parse_args(argv)
    print(_canonical(run(args.output, args.expected_git)).decode())

if __name__ == "__main__":
    main()
