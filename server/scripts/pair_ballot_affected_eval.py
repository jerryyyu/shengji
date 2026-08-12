#!/usr/bin/env python3
"""Evaluate pair retention only where the current lead ballot drops a pair.

This is the cheap exploration tier, not a deployment gate.  DEV and CALIB are
reusable.  REPORT is deliberately unavailable here and must get its own
one-shot controller only if the mechanism survives exploration.

For each frozen state the evaluator answers two separate questions on fresh,
common worlds:

1. Did equal-width pair retention change the action selected by the complete
   live report-LCB policy, and was that action better?
2. Was the best newly inserted pair better than the current policy's action,
   even when report-LCB did not exploit it?

That separation prevents a neutral result from throwing away a useful source:
it distinguishes candidate availability from downstream selection quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.teacher_v1 import attacker_level_utility

import pair_ballot_affected_states as STATES


SCHEMA = "pair-ballot-affected-eval-row-v1"
SHARD_SCHEMA = "pair-ballot-affected-eval-shard-v1"
ALLOWED_SPLITS = ("dev", "calib")
REPORT_WORLDS = 300
SEED_DOMAIN = "pair-ballot-affected-eval-v1"
CHAMPION = "mc-s0-report-lcb"
SOURCE_FIELDS = {"evaluator", "capture"}
RUNTIME_FIELDS = {*STATES.RUNTIME_FIELDS, "diagnostic_only"}
SHARD_FIELDS = {
    "schema", "source_path", "source_file_sha256",
    "source_artifact_sha256", "source_sha256s", "runtime", "split",
    "shard_index", "shard_count", "report_worlds", "rows", "results",
    "diagnostic_only", "strength_claim", "production_promotion",
    "production_deployment", "artifact_sha256",
}
RESULT_FIELDS = {
    "schema", "state_id", "state_sha256", "deal_seed", "split", "band",
    "role", "policy_root_seed", "external_report_seed", "current",
    "retained", "best_inserted_index", "best_inserted_pair",
    "policy_action_changed", "retained_raw_winner_is_inserted",
    "current_raw_winner_was_evicted", "external_report", "estimands",
    "candidate_world_work", "diagnostic_only", "strength_claim",
    "production_promotion", "production_deployment", "result_sha256",
}


class EvalRefused(RuntimeError):
    """The state population, policy dose, or evaluation work drifted."""


def evaluation_runtime() -> dict:
    """Authenticate the host while describing scored diagnostic work truthfully.

    The source-population producer is score-free, but this evaluator is not:
    it rolls actions through determinized worlds and records attacker points
    and acting-team utilities.  Reusing the capture runtime unchanged would
    falsely claim that no outcomes were computed.
    """
    runtime = dict(STATES._runtime(smoke=False))
    runtime.update({
        "score_free": False,
        "outcomes_computed": True,
        "diagnostic_only": True,
    })
    if set(runtime) != RUNTIME_FIELDS:
        raise EvalRefused("pair evaluation runtime field population drift")
    return runtime


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def seed_for(state_id: str, purpose: str) -> int:
    material = f"{SEED_DOMAIN}|{purpose}|{state_id}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:16], "big")


def _sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    )}


def _sampler_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {name: after[name] - before[name] for name in before}


def draw_worlds(rnd, seat: int, *, seed: int,
                count: int = REPORT_WORLDS) -> tuple[object, list, dict]:
    if count <= 0:
        raise EvalRefused("report world count must be positive")
    bot = make_bot(CHAMPION, seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    before = _sampler_snapshot(bot)
    worlds = []
    attempts = 0
    cap = count * int(bot.SAMPLE_ATTEMPT_FACTOR)
    while len(worlds) < count and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is not None:
            worlds.append(sampled)
    delta = _sampler_delta(before, _sampler_snapshot(bot))
    if (len(worlds) != count
            or delta["sample_attempts"] != attempts
            or delta["accepted_worlds"] != count
            or attempts != delta["accepted_worlds"] + delta["failed_worlds"]
            or delta["rejected_worlds"] > delta["failed_worlds"]):
        raise EvalRefused("strict external report sampler underfilled")
    return bot, worlds, {
        "requested": count,
        "accepted": len(worlds),
        "attempts": attempts,
        "attempt_cap": cap,
        "counters": delta,
    }


def run_policy(rnd, seat: int, *, retained: bool, seed: int,
               expected_ballot: list[list[str]]) -> tuple[object, dict]:
    bot = make_bot(CHAMPION, seed=seed)
    bot.RETAIN_ALL_LEAD_PAIRS = retained
    observed = bot._candidates(rnd, seat)
    if ([action_key(cards) for cards in observed]
            != [action_key(cards) for cards in expected_ballot]):
        raise EvalRefused("frozen affected-state ballot drift")
    action = bot.decide_play(rnd, seat)
    record = bot.last_decision_record
    if record is None:
        raise EvalRefused("search-reachable pair state took a search-free path")
    work = record.get("work", {})
    expected_selection = len(expected_ballot) * 30
    if (record.get("policy") != CHAMPION
            or record.get("played") != action
            or record.get("worlds") != 30
            or record.get("n_by_candidate") != [30] * len(expected_ballot)
            or work.get("selection_rollouts") != expected_selection
            or work.get("report_rollouts") != 600
            or work.get("total_rollouts") != expected_selection + 600
            or work.get("complete") is not True
            or record.get("alloc", {}).get("short") is not False):
        raise EvalRefused("live report-LCB decision dose drift")
    if len(record.get("means", [])) != len(expected_ballot):
        raise EvalRefused("live report-LCB selection means drift")
    return bot, {
        "action": list(action_key(action)),
        "reason": record["reason"],
        "raw_winner_index": record["raw_winner_index"],
        "report_candidate_index": record["report_candidate_index"],
        "played_index": record["played_index"],
        "selection_means": list(record["means"]),
        # Preserve the decision evidence, not only its conclusion.  Without
        # this fold record an aggregate could check that the selected action
        # was on the ballot, but could not check that the recorded LCB reason
        # actually implied the recorded played index.
        "report_fold": dict(record["report_fold"]),
        "work": dict(work),
        "sampler_counters": dict(record["sampler_counters"]["delta"]),
    }


def score_actions(bot, rnd, seat: int, worlds: list,
                  actions: list[tuple[str, list[str]]]) -> list[dict]:
    acting_is_attacker = rnd.is_attacker(seat)
    records = []
    seen = set()
    for label, cards in actions:
        key = action_key(cards)
        if key in seen:
            continue
        seen.add(key)
        raw_points = []
        utilities = []
        for hands, buried in worlds:
            points = float(bot._rollout(
                rnd, seat, hands, buried, list(cards)))
            raw_points.append(points)
            utility = attacker_level_utility(points)
            utilities.append(utility if acting_is_attacker else -utility)
        records.append({
            "label": label,
            "cards": list(key),
            "raw_attacker_points": raw_points,
            "acting_level_utilities": utilities,
            "mean_acting_level_utility": sum(utilities) / len(utilities),
        })
    return records


def _paired_mean(by_key: dict[tuple[str, ...], dict],
                 left: list[str], right: list[str]) -> float:
    lhs = by_key[action_key(left)]["acting_level_utilities"]
    rhs = by_key[action_key(right)]["acting_level_utilities"]
    if len(lhs) != len(rhs) or not lhs:
        raise EvalRefused("external report paired dose drift")
    return sum(a - b for a, b in zip(lhs, rhs, strict=True)) / len(lhs)


def evaluate_state(row: dict, *, report_worlds: int = REPORT_WORLDS) -> dict:
    if row.get("search_eligible") is not True:
        raise EvalRefused("evaluation row is not search-reachable")
    rnd = STATES.replay_state(row)
    seat = int(row["seat"])
    root_seed = seed_for(row["state_id"], "policy-root")
    _, current = run_policy(
        rnd, seat, retained=False, seed=root_seed,
        expected_ballot=row["current_ballot"])
    _, retained = run_policy(
        rnd, seat, retained=True, seed=root_seed,
        expected_ballot=row["retained_ballot"])

    inserted = {action_key(cards) for cards in row["inserted_actions"]}
    evicted = {action_key(cards) for cards in row["evicted_actions"]}
    retained_candidates = [action_key(cards)
                           for cards in row["retained_ballot"]]
    inserted_indices = [index for index, cards in enumerate(retained_candidates)
                        if cards in inserted]
    if not inserted_indices:
        raise EvalRefused("retained ballot contains no inserted pair")
    best_inserted_index = max(
        inserted_indices, key=lambda index: retained["selection_means"][index])
    best_inserted = list(retained_candidates[best_inserted_index])

    report_seed = seed_for(row["state_id"], "external-report")
    report_bot, worlds, sampler = draw_worlds(
        rnd, seat, seed=report_seed, count=report_worlds)
    report = score_actions(report_bot, rnd, seat, worlds, [
        ("current_policy", current["action"]),
        ("retained_policy", retained["action"]),
        ("best_inserted_pair", best_inserted),
    ])
    by_key = {action_key(item["cards"]): item for item in report}
    result = {
        "schema": SCHEMA,
        "state_id": row["state_id"],
        "state_sha256": row["state_sha256"],
        "deal_seed": row["deal_seed"],
        "split": row["split"],
        "band": row["band"],
        "role": row["role"],
        "policy_root_seed": root_seed,
        "external_report_seed": report_seed,
        "current": current,
        "retained": retained,
        "best_inserted_index": best_inserted_index,
        "best_inserted_pair": best_inserted,
        "policy_action_changed": current["action"] != retained["action"],
        "retained_raw_winner_is_inserted": action_key(
            row["retained_ballot"][retained["raw_winner_index"]]) in inserted,
        "current_raw_winner_was_evicted": action_key(
            row["current_ballot"][current["raw_winner_index"]]) in evicted,
        "external_report": {
            "worlds": report_worlds,
            "sampler": sampler,
            "actions": report,
        },
        "estimands": {
            "retained_policy_minus_current": _paired_mean(
                by_key, retained["action"], current["action"]),
            "best_inserted_pair_minus_current": _paired_mean(
                by_key, best_inserted, current["action"]),
        },
        "candidate_world_work": {
            "current_policy": current["work"]["total_rollouts"],
            "retained_policy": retained["work"]["total_rollouts"],
            "external_report": len(report) * report_worlds,
        },
        "diagnostic_only": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["result_sha256"] = STATES.sha256_bytes(STATES.canonical_json(result))
    return result


def load_population(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise EvalRefused("affected-state population missing/nonregular")
    payload = json.loads(path.read_bytes())
    try:
        STATES.validate_population(
            payload, source_path=path, replay=False, smoke=False)
    except STATES.CaptureRefused as exc:
        raise EvalRefused(
            f"affected-state population authority/content drift: {exc}") \
            from exc
    return payload


def run_shard(*, population: Path, split: str, shard_index: int,
              shard_count: int, out: Path,
              report_worlds: int = REPORT_WORLDS,
              progress_every: int = 4) -> dict:
    if split not in ALLOWED_SPLITS:
        raise EvalRefused("exploration evaluator permits DEV/CALIB only")
    if report_worlds != REPORT_WORLDS:
        raise EvalRefused("formal exploration report dose must be 300 worlds")
    if not 0 <= shard_index < shard_count:
        raise EvalRefused("shard index must satisfy 0 <= index < count")
    source = load_population(population)
    runtime = evaluation_runtime()
    source_sha256s = {
        "evaluator": STATES.sha256_file(__file__),
        "capture": STATES.sha256_file(STATES.__file__),
    }
    rows = [row for row in source["states"]
            if row["split"] == split
            and row["deal_seed"] % shard_count == shard_index]
    if not rows:
        raise EvalRefused("evaluation shard has no assigned states")
    results = []
    started = time.perf_counter()
    for complete, row in enumerate(rows, start=1):
        results.append(evaluate_state(row, report_worlds=report_worlds))
        if progress_every and (complete == 1 or complete % progress_every == 0
                               or complete == len(rows)):
            print(json.dumps({
                "event": "pair-affected-eval-progress-v1",
                "split": split,
                "shard_index": shard_index,
                "states_complete": complete,
                "states_total": len(rows),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SHARD_SCHEMA,
        "source_path": str(population),
        "source_file_sha256": STATES.sha256_file(population),
        "source_artifact_sha256": source["artifact_sha256"],
        "source_sha256s": source_sha256s,
        "runtime": runtime,
        "split": split,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "report_worlds": report_worlds,
        "rows": len(results),
        "results": results,
        "diagnostic_only": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["artifact_sha256"] = STATES.sha256_bytes(STATES.canonical_json(payload))
    STATES._write_exclusive(out, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--split", choices=ALLOWED_SPLITS, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--report-worlds", type=int, default=REPORT_WORLDS)
    parser.add_argument("--progress-every", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_shard(
            population=args.population, split=args.split,
            shard_index=args.shard_index, shard_count=args.shard_count,
            report_worlds=args.report_worlds,
            progress_every=args.progress_every, out=args.out)
    except (EvalRefused, STATES.CaptureRefused, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
