#!/usr/bin/env python3
"""Aggregate reusable DEV/CALIB pair-retention diagnostics by deal cluster.

This intentionally reports estimates and uncertainty without a SELECT_NONE
terminal.  Exploration should route the next mechanism:

* positive policy effect -> test natural-dose composition;
* positive inserted-pair headroom but neutral policy -> improve selection;
* neutral/negative headroom -> do not force pairs into the fixed ballot.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pair_ballot_affected_eval as EVAL
import pair_ballot_affected_states as STATES


SCHEMA = "pair-ballot-affected-eval-aggregate-v1"
METRICS = (
    "retained_policy_minus_current",
    "best_inserted_pair_minus_current",
)
POLICY_FIELDS = {
    "action", "reason", "raw_winner_index", "report_candidate_index",
    "played_index", "selection_means", "report_fold", "work",
    "sampler_counters",
}
WORK_FIELDS = {
    "selection_budget", "selection_rollouts", "report_budget",
    "report_rollouts", "total_budget", "total_rollouts", "complete",
}
COUNTER_FIELDS = {
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
}
REPORT_FOLD_FIELDS = {
    "gap", "se", "worlds", "attempts", "rejected", "complete", "seed",
    "fold", "rule", "critical", "statistic", "min_gain", "bound",
}
EXTERNAL_REPORT_FIELDS = {"worlds", "sampler", "actions"}
EXTERNAL_SAMPLER_FIELDS = {
    "requested", "accepted", "attempts", "attempt_cap", "counters",
}
EXTERNAL_ACTION_FIELDS = {
    "label", "cards", "raw_attacker_points", "acting_level_utilities",
    "mean_acting_level_utility",
}


def _finite_number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _nonnegative_int(value: object) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and value >= 0)


def _close(left: object, right: object) -> bool:
    return (_finite_number(left) and _finite_number(right)
            and math.isclose(float(left), float(right),
                             rel_tol=1e-12, abs_tol=1e-12))


def _canonical_action(value: object) -> tuple[str, ...]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(card, str) or not card for card in value)):
        raise EVAL.EvalRefused("pair evaluation action shape drift")
    key = EVAL.action_key(value)
    if value != list(key):
        raise EVAL.EvalRefused("pair evaluation action canonicalization drift")
    return key


def _validate_counters(counters: object, *, accepted: int) -> None:
    if (not isinstance(counters, dict) or set(counters) != COUNTER_FIELDS
            or any(not _nonnegative_int(value)
                   for value in counters.values())
            or counters["accepted_worlds"] != accepted
            or counters["sample_attempts"]
            != counters["accepted_worlds"] + counters["failed_worlds"]
            or counters["rejected_worlds"] > counters["failed_worlds"]
            or counters["impossible_worlds"] > counters["failed_worlds"]):
        raise EVAL.EvalRefused("pair evaluation sampler accounting drift")


def _validate_report_fold(fold: object, *, played_index: int,
                          report_index: int) -> None:
    if (not isinstance(fold, dict) or set(fold) != REPORT_FOLD_FIELDS
            or fold.get("fold") != "report"
            or fold.get("rule") != "lcb"
            or fold.get("bound")
            != "paired_student_t_one_sided_95_conservative_df>=29"
            or fold.get("complete") is not True
            or fold.get("worlds") != EVAL.REPORT_WORLDS
            or not _nonnegative_int(fold.get("attempts"))
            or not _nonnegative_int(fold.get("rejected"))
            or fold["attempts"] - fold["worlds"] != fold["rejected"]
            or not _nonnegative_int(fold.get("seed"))
            or not _finite_number(fold.get("gap"))
            or not _finite_number(fold.get("se"))
            or fold["se"] < 0
            or fold.get("critical") != 1.7
            or fold.get("min_gain") != 0.0
            or not _close(
                fold.get("statistic"),
                fold["gap"] - fold["critical"] * fold["se"])):
        raise EVAL.EvalRefused("pair evaluation report-fold evidence drift")
    expected_played = (report_index
                       if fold["statistic"] >= fold["min_gain"] else 0)
    if played_index != expected_played:
        raise EVAL.EvalRefused("pair evaluation report-fold decision drift")


def _validate_policy_record(record: object, *, ballot: list | None = None,
                            expected_report_seed: int | None = None) -> None:
    if not isinstance(record, dict) or set(record) != POLICY_FIELDS:
        raise EVAL.EvalRefused("pair evaluation policy record shape drift")
    action = _canonical_action(record.get("action"))
    means = record.get("selection_means")
    if (not isinstance(means, list) or len(means) < 2
            or any(not _finite_number(value) for value in means)):
        raise EVAL.EvalRefused("pair evaluation selection means drift")
    candidate_count = len(means)
    indices = [record.get(name) for name in (
        "raw_winner_index", "report_candidate_index", "played_index")]
    if any(not _nonnegative_int(index) or index >= candidate_count
           for index in indices):
        raise EVAL.EvalRefused("pair evaluation policy index drift")
    raw_index, report_index, played_index = indices
    reason = record.get("reason")
    if reason not in {"report_lcb_override", "report_lcb_below_min_gain"}:
        raise EVAL.EvalRefused("pair evaluation policy reason drift")

    selection_work = candidate_count * 30
    expected_work = {
        "selection_budget": selection_work,
        "selection_rollouts": selection_work,
        "report_budget": 2 * EVAL.REPORT_WORLDS,
        "report_rollouts": 2 * EVAL.REPORT_WORLDS,
        "total_budget": selection_work + 2 * EVAL.REPORT_WORLDS,
        "total_rollouts": selection_work + 2 * EVAL.REPORT_WORLDS,
        "complete": True,
    }
    work = record.get("work")
    if (not isinstance(work, dict) or set(work) != WORK_FIELDS
            or work != expected_work):
        raise EVAL.EvalRefused("pair evaluation policy work drift")
    _validate_counters(
        record.get("sampler_counters"), accepted=30 + EVAL.REPORT_WORLDS)
    _validate_report_fold(
        record.get("report_fold"), played_index=played_index,
        report_index=report_index)
    fold = record["report_fold"]
    if ((reason == "report_lcb_override")
            is not (fold["statistic"] >= fold["min_gain"])):
        raise EVAL.EvalRefused("pair evaluation policy reason/evidence drift")
    if expected_report_seed is not None and fold["seed"] != expected_report_seed:
        raise EVAL.EvalRefused("pair evaluation report-fold seed drift")

    if ballot is None:
        return
    if not isinstance(ballot, list) or len(ballot) != candidate_count:
        raise EVAL.EvalRefused("pair evaluation ballot/means drift")
    # Frozen source ballots preserve the production generator's card order;
    # result actions are canonicalised separately above.
    ballot_keys = [EVAL.action_key(cards) for cards in ballot]
    if action != ballot_keys[played_index]:
        raise EVAL.EvalRefused("pair evaluation played action/index drift")
    bot = EVAL.make_bot(EVAL.CHAMPION, seed=0)
    observed_raw = bot._pick_index(ballot, means, range(candidate_count))
    observed_report = bot._pick_index(
        ballot, means, range(1, candidate_count))
    if raw_index != observed_raw or report_index != observed_report:
        raise EVAL.EvalRefused("pair evaluation selection index drift")


def _validate_external_report(row: dict, *, report_worlds: int) -> None:
    report = row.get("external_report")
    if (not isinstance(report, dict)
            or set(report) != EXTERNAL_REPORT_FIELDS
            or report.get("worlds") != report_worlds):
        raise EVAL.EvalRefused("pair external report shape/dose drift")
    sampler = report.get("sampler")
    factor = int(EVAL.make_bot(
        EVAL.CHAMPION, seed=0).SAMPLE_ATTEMPT_FACTOR)
    if (not isinstance(sampler, dict)
            or set(sampler) != EXTERNAL_SAMPLER_FIELDS
            or sampler.get("requested") != report_worlds
            or sampler.get("accepted") != report_worlds
            or not _nonnegative_int(sampler.get("attempts"))
            or sampler["attempts"] < report_worlds
            or sampler.get("attempt_cap") != report_worlds * factor
            or sampler["attempts"] > sampler["attempt_cap"]):
        raise EVAL.EvalRefused("pair external report sampler drift")
    _validate_counters(sampler.get("counters"), accepted=report_worlds)
    if sampler["counters"]["sample_attempts"] != sampler["attempts"]:
        raise EVAL.EvalRefused("pair external report attempt drift")

    targets = [
        ("current_policy", row["current"]["action"]),
        ("retained_policy", row["retained"]["action"]),
        ("best_inserted_pair", row["best_inserted_pair"]),
    ]
    expected = []
    seen = set()
    for label, cards in targets:
        key = _canonical_action(cards)
        if key not in seen:
            seen.add(key)
            expected.append((label, key))
    actions = report.get("actions")
    if not isinstance(actions, list) or len(actions) != len(expected):
        raise EVAL.EvalRefused("pair external report action population drift")
    by_key = {}
    sign = 1.0 if row.get("role") == "attacker" else -1.0
    for record, (label, expected_key) in zip(actions, expected, strict=True):
        if (not isinstance(record, dict)
                or set(record) != EXTERNAL_ACTION_FIELDS
                or record.get("label") != label
                or _canonical_action(record.get("cards")) != expected_key):
            raise EVAL.EvalRefused("pair external report action binding drift")
        points = record.get("raw_attacker_points")
        utilities = record.get("acting_level_utilities")
        if (not isinstance(points, list) or not isinstance(utilities, list)
                or len(points) != report_worlds
                or len(utilities) != report_worlds
                or any(not _finite_number(value) for value in points)
                or any(not _finite_number(value) for value in utilities)):
            raise EVAL.EvalRefused("pair external report utility dose drift")
        expected_utilities = [
            sign * EVAL.attacker_level_utility(float(point))
            for point in points
        ]
        if any(not _close(observed, wanted)
               for observed, wanted in zip(
                   utilities, expected_utilities, strict=True)):
            raise EVAL.EvalRefused("pair external report utility mapping drift")
        if not _close(
                record.get("mean_acting_level_utility"),
                sum(utilities) / report_worlds):
            raise EVAL.EvalRefused("pair external report mean drift")
        by_key[expected_key] = record

    def paired(left: list[str], right: list[str]) -> float:
        lhs = by_key[EVAL.action_key(left)]["acting_level_utilities"]
        rhs = by_key[EVAL.action_key(right)]["acting_level_utilities"]
        return sum(a - b for a, b in zip(lhs, rhs, strict=True)) / report_worlds

    expected_estimands = {
        "retained_policy_minus_current": paired(
            row["retained"]["action"], row["current"]["action"]),
        "best_inserted_pair_minus_current": paired(
            row["best_inserted_pair"], row["current"]["action"]),
    }
    estimands = row.get("estimands")
    if (not isinstance(estimands, dict) or set(estimands) != set(METRICS)
            or any(not _close(estimands[name], value)
                   for name, value in expected_estimands.items())):
        raise EVAL.EvalRefused("pair evaluation estimand reconstruction drift")
    expected_work = {
        "current_policy": row["current"]["work"]["total_rollouts"],
        "retained_policy": row["retained"]["work"]["total_rollouts"],
        "external_report": len(actions) * report_worlds,
    }
    if row.get("candidate_world_work") != expected_work:
        raise EVAL.EvalRefused("pair evaluation total work reconstruction drift")


def _validate_result(row: object, *, split: str,
                     report_worlds: int) -> None:
    if (not isinstance(row, dict) or row.get("schema") != EVAL.SCHEMA
            or set(row) != EVAL.RESULT_FIELDS):
        raise EVAL.EvalRefused("pair evaluation result field population drift")
    body = dict(row)
    observed_sha = body.pop("result_sha256", None)
    if observed_sha != STATES.sha256_bytes(STATES.canonical_json(body)):
        raise EVAL.EvalRefused("pair evaluation result digest drift")
    state_id = row.get("state_id")
    if (not isinstance(state_id, str)
            or row.get("policy_root_seed") != EVAL.seed_for(
                state_id, "policy-root")
            or row.get("external_report_seed") != EVAL.seed_for(
                state_id, "external-report")
            or row.get("split") != split
            or row.get("band") not in STATES.BANDS
            or row.get("role") not in {"attacker", "defender"}
            or not _nonnegative_int(row.get("deal_seed"))
            or not isinstance(row.get("state_sha256"), str)
            or len(row["state_sha256"]) != 64
            or not _nonnegative_int(row.get("best_inserted_index"))
            or row.get("diagnostic_only") is not True
            or row.get("strength_claim") is not False
            or row.get("production_promotion") is not False
            or row.get("production_deployment") is not False
            or any(not isinstance(row.get(field), bool) for field in (
                "policy_action_changed", "retained_raw_winner_is_inserted",
                "current_raw_winner_was_evicted"))):
        raise EVAL.EvalRefused("pair evaluation result content/authority drift")
    _canonical_action(row.get("best_inserted_pair"))
    expected_policy_report_seed = EVAL.make_bot(
        EVAL.CHAMPION, seed=row["policy_root_seed"]).rng.getstate()
    # The live policy derives its report stream from the untouched initial RNG
    # state.  Keep the private derivation in one implementation rather than
    # duplicating its serialization here.
    from shengji.ai.mcbot import _child_seed
    expected_policy_report_seed = _child_seed(
        expected_policy_report_seed, "s0-report")
    _validate_policy_record(
        row.get("current"), expected_report_seed=expected_policy_report_seed)
    _validate_policy_record(
        row.get("retained"), expected_report_seed=expected_policy_report_seed)
    _validate_external_report(row, report_worlds=report_worlds)


def _validate_source_binding(result: dict, source: dict) -> None:
    for field in ("state_id", "state_sha256", "deal_seed", "split",
                  "band", "role"):
        if result.get(field) != source.get(field):
            raise EVAL.EvalRefused("pair aggregate state binding drift")
    current_ballot = source.get("current_ballot")
    retained_ballot = source.get("retained_ballot")
    _validate_policy_record(result.get("current"), ballot=current_ballot)
    _validate_policy_record(result.get("retained"), ballot=retained_ballot)

    inserted = {EVAL.action_key(cards)
                for cards in source.get("inserted_actions", [])}
    evicted = {EVAL.action_key(cards)
               for cards in source.get("evicted_actions", [])}
    best_index = result["best_inserted_index"]
    if (best_index >= len(retained_ballot)
            or EVAL.action_key(retained_ballot[best_index])
            != EVAL.action_key(result["best_inserted_pair"])
            or EVAL.action_key(result["best_inserted_pair"]) not in inserted):
        raise EVAL.EvalRefused("pair aggregate inserted-pair binding drift")
    inserted_indices = [
        index for index, cards in enumerate(retained_ballot)
        if EVAL.action_key(cards) in inserted
    ]
    observed_best = max(
        inserted_indices,
        key=lambda index: result["retained"]["selection_means"][index])
    if best_index != observed_best:
        raise EVAL.EvalRefused("pair aggregate best inserted selector drift")

    current = result["current"]
    retained = result["retained"]
    expected_flags = {
        "policy_action_changed": (
            EVAL.action_key(current["action"])
            != EVAL.action_key(retained["action"])),
        "retained_raw_winner_is_inserted": EVAL.action_key(
            retained_ballot[retained["raw_winner_index"]]) in inserted,
        "current_raw_winner_was_evicted": EVAL.action_key(
            current_ballot[current["raw_winner_index"]]) in evicted,
    }
    if any(result[name] is not value
           for name, value in expected_flags.items()):
        raise EVAL.EvalRefused("pair aggregate selector telemetry drift")


def _validate_scored_runtime(runtime: object) -> None:
    if (not isinstance(runtime, dict)
            or set(runtime) != EVAL.RUNTIME_FIELDS
            or runtime.get("tree_dirty") is not False
            or runtime.get("fast_engine") is not True
            or runtime.get("score_free") is not False
            or runtime.get("outcomes_computed") is not True
            or runtime.get("diagnostic_only") is not True
            or runtime.get("strength_claim") is not False
            or runtime.get("production_authority") is not False):
        raise EVAL.EvalRefused(
            "pair evaluation scored-runtime authority drift")


def load_shard(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise EVAL.EvalRefused("pair evaluation shard missing/nonregular")
    payload = json.loads(path.read_bytes())
    if payload.get("schema") != EVAL.SHARD_SCHEMA:
        raise EVAL.EvalRefused("pair evaluation shard schema drift")
    if set(payload) != EVAL.SHARD_FIELDS:
        raise EVAL.EvalRefused("pair evaluation shard field population drift")
    body = dict(payload)
    observed_sha = body.pop("artifact_sha256", None)
    if observed_sha != STATES.sha256_bytes(STATES.canonical_json(body)):
        raise EVAL.EvalRefused("pair evaluation shard digest drift")
    rows = payload.get("results")
    split = payload.get("split")
    report_worlds = payload.get("report_worlds")
    runtime = payload.get("runtime")
    sources = payload.get("source_sha256s")
    _validate_scored_runtime(runtime)
    if (split not in EVAL.ALLOWED_SPLITS
            or not isinstance(rows, list)
            or payload.get("rows") != len(rows)
            or isinstance(report_worlds, bool)
            or report_worlds != EVAL.REPORT_WORLDS
            or not isinstance(sources, dict)
            or set(sources) != EVAL.SOURCE_FIELDS
            or sources != {
                "evaluator": STATES.sha256_file(EVAL.__file__),
                "capture": STATES.sha256_file(STATES.__file__),
            }
            or payload.get("diagnostic_only") is not True
            or payload.get("strength_claim") is not False
            or payload.get("production_promotion") is not False
            or payload.get("production_deployment") is not False):
        raise EVAL.EvalRefused("pair evaluation shard content/authority drift")
    for row in rows:
        _validate_result(row, split=split, report_worlds=report_worlds)
    return payload


def weighted_cluster_stats(rows: list[dict], metric: str,
                           band_weights: dict[str, float]) -> dict:
    """Return a descriptive hybrid-weighted diagnostic.

    ``band_weights`` count every search-reachable omission event in the full
    capture stream.  Within a band, however, the frozen population retains
    only the first affected state per deal/band.  The resulting estimate is
    useful for routing exploration but is not an exact natural-decision or
    whole-round estimand.
    """
    if metric not in METRICS or not rows:
        raise EVAL.EvalRefused("unknown/empty pair diagnostic metric")
    by_band = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)
    if set(by_band) != set(STATES.BANDS) or set(band_weights) != set(STATES.BANDS):
        raise EVAL.EvalRefused("pair diagnostic band population drift")
    if (any(not _finite_number(weight) or weight <= 0
            for weight in band_weights.values())
            or not math.isclose(sum(band_weights.values()), 1.0,
                                abs_tol=1e-12)):
        raise EVAL.EvalRefused("pair diagnostic capture-event weights drift")
    means = {
        band: sum(row["estimands"][metric] for row in values) / len(values)
        for band, values in by_band.items()
    }
    estimate = sum(band_weights[band] * means[band] for band in STATES.BANDS)
    influence = defaultdict(float)
    observation_weights = {}
    for band in STATES.BANDS:
        weight = band_weights[band] / len(by_band[band])
        observation_weights[band] = weight
        for row in by_band[band]:
            influence[int(row["deal_seed"])] += (
                weight * (row["estimands"][metric] - means[band]))
    clusters = len(influence)
    se = (math.sqrt(clusters / (clusters - 1)
                    * sum(value * value for value in influence.values()))
          if clusters >= 2 else float("inf"))
    return {
        "metric": metric,
        "rows": len(rows),
        "deal_clusters": clusters,
        "capture_event_band_weighted_mean": estimate,
        "selected_population_mean": (
            sum(row["estimands"][metric] for row in rows) / len(rows)),
        "cluster_robust_se": se,
        "ci95": [estimate - 1.96 * se, estimate + 1.96 * se],
        "band_weights": dict(band_weights),
        "band_weight_unit": "all_search_reachable_omission_events",
        "within_band_sampling_unit":
            "first_affected_state_per_deal_band_in_frozen_population",
        "exact_natural_decision_estimand": False,
        "exact_whole_round_estimand": False,
        "observation_weights": observation_weights,
        "by_band": {
            band: {"n": len(by_band[band]), "mean": means[band]}
            for band in STATES.BANDS
        },
    }


def diagnostic_route(policy_mean: float, source_mean: float) -> str:
    if source_mean > 0 and policy_mean > 0:
        return "POLICY_AND_SOURCE_PROMISING_TEST_NATURAL_DOSE"
    if source_mean > 0:
        return "SOURCE_PROMISING_SELECTOR_NOT_EXPLOITING"
    if policy_mean > 0:
        return "POLICY_POSITIVE_WITHOUT_INSERTED_PAIR_HEADROOM_AUDIT_EVICTIONS"
    return "FIXED_WIDTH_RETENTION_NOT_PROMISING_TRY_CONTEXTUAL_PAIR_SOURCE"


def aggregate(*, population: Path, shard_paths: list[Path],
              split: str, out: Path) -> dict:
    if split not in EVAL.ALLOWED_SPLITS or not shard_paths:
        raise EVAL.EvalRefused("aggregate requires DEV/CALIB and shard inputs")
    source = EVAL.load_population(population)
    loaded = [(path, load_shard(path)) for path in shard_paths]
    loaded.sort(key=lambda item: item[1].get("shard_index", -1))
    shard_paths = [path for path, _ in loaded]
    shards = [shard for _, shard in loaded]
    shard_count = shards[0].get("shard_count")
    report_worlds = shards[0].get("report_worlds")
    runtime = shards[0].get("runtime")
    source_sha256s = shards[0].get("source_sha256s")
    expected_source_sha = STATES.sha256_file(population)
    indices = []
    rows = []
    for shard in shards:
        if (shard.get("split") != split
                or shard.get("shard_count") != shard_count
                or shard.get("report_worlds") != report_worlds
                or shard.get("runtime") != runtime
                or shard.get("source_sha256s") != source_sha256s
                or shard.get("source_file_sha256") != expected_source_sha
                or shard.get("source_artifact_sha256")
                != source["artifact_sha256"]):
            raise EVAL.EvalRefused("pair aggregate shard cohort drift")
        indices.append(shard.get("shard_index"))
        rows.extend(shard["results"])
    if (not isinstance(shard_count, int) or shard_count <= 0
            or sorted(indices) != list(range(shard_count))):
        raise EVAL.EvalRefused("pair aggregate shard population incomplete")
    expected = {row["state_id"]: row for row in source["states"]
                if row["split"] == split}
    observed = {row["state_id"]: row for row in rows}
    if len(observed) != len(rows) or set(observed) != set(expected):
        raise EVAL.EvalRefused("pair aggregate state population incomplete")
    for state_id, result in observed.items():
        _validate_source_binding(result, expected[state_id])

    weights = source.get("search_eligible_weights")
    stats = {metric: weighted_cluster_stats(rows, metric, weights)
             for metric in METRICS}
    counts = Counter(row["band"] for row in rows)
    dose = {
        "states": len(rows),
        "unique_deals": len({row["deal_seed"] for row in rows}),
        "by_band": dict(sorted(counts.items())),
        "policy_action_changes": sum(row["policy_action_changed"] for row in rows),
        "retained_raw_winner_inserted": sum(
            row["retained_raw_winner_is_inserted"] for row in rows),
        "current_raw_winner_evicted": sum(
            row["current_raw_winner_was_evicted"] for row in rows),
    }
    policy_mean = stats["retained_policy_minus_current"][
        "capture_event_band_weighted_mean"]
    source_mean = stats[
        "best_inserted_pair_minus_current"][
            "capture_event_band_weighted_mean"]
    payload = {
        "schema": SCHEMA,
        "split": split,
        "source_file_sha256": expected_source_sha,
        "source_artifact_sha256": source["artifact_sha256"],
        "source_sha256s": source_sha256s,
        "runtime": runtime,
        "inputs": [{
            "path": str(path),
            "file_sha256": STATES.sha256_file(path),
            "artifact_sha256": shard["artifact_sha256"],
            "shard_index": shard["shard_index"],
        } for path, shard in zip(shard_paths, shards, strict=True)],
        "shard_count": shard_count,
        "report_worlds": report_worlds,
        "dose": dose,
        "metrics": stats,
        "estimand_scope": {
            "band_weight_unit": "all_search_reachable_omission_events",
            "within_band_sampling_unit":
                "first_affected_state_per_deal_band_in_frozen_population",
            "exact_natural_decision_estimand": False,
            "exact_whole_round_estimand": False,
            "use": "exploration_route_only",
        },
        "diagnostic_route": diagnostic_route(policy_mean, source_mean),
        "terminal_selection": False,
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
    parser.add_argument("--split", choices=EVAL.ALLOWED_SPLITS, required=True)
    parser.add_argument("--shard", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        aggregate(
            population=args.population, shard_paths=args.shard,
            split=args.split, out=args.out)
    except (EVAL.EvalRefused, STATES.CaptureRefused, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
