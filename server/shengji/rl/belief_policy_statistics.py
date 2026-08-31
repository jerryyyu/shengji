"""Cheap deterministic reduction for complete R4 policy result shards."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from .belief_policy_artifacts import validate_policy_root_result
from .belief_policy_protocol import (
    POLICY_RANKS,
    SELECTED_ROUNDS_PER_RANK,
    TARGET_ROUND_COUNT,
)
from .belief_policy_search import ARM_IDS, CONTROL_ARM, PRIMARY_ARM, PRODUCTION_ARM


TERMINAL_SCHEMA = "belief-r4-policy-diagnostic-terminal-v1"
BOOTSTRAP_REPLICATES = 10_000
ROUTE_SIGNAL = "PRIMARY_POLICY_SIGNAL"
ROUTE_CONTROL = "PRIMARY_NOT_SEPARATED_FROM_CONTROL"
ROUTE_NONE = "NO_PRIMARY_POLICY_SIGNAL"
ROUTE_SUPPORT = "PRIMARY_SIGNAL_NOT_INTERPRETABLE_PROPOSAL_SUPPORT"


class BeliefPolicyStatisticsError(ValueError):
    """A complete shard population, bootstrap, or route drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _divide(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefPolicyStatisticsError("policy ratio input drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((2 * abs(numerator) + denominator) // (2 * denominator))


def _mean_nano(values: tuple[int, ...]) -> int:
    if not values:
        raise BeliefPolicyStatisticsError("policy estimand population empty")
    return _divide(sum(values) * 1_000_000_000, len(values))


def _mean_ppb(values: tuple[bool, ...]) -> int:
    if not values:
        raise BeliefPolicyStatisticsError("policy rate population empty")
    return _divide(sum(values) * 1_000_000_000, len(values))


def _bootstrap_interval(
        by_rank: tuple[tuple[int, ...], ...]) -> dict[str, int]:
    if len(by_rank) != len(POLICY_RANKS) \
            or any(type(row) is not tuple
                   or len(row) != SELECTED_ROUNDS_PER_RANK
                   or any(type(value) is not int for value in row)
                   for row in by_rank):
        raise BeliefPolicyStatisticsError(
            "policy stratified bootstrap population drift")
    seed = int.from_bytes(hashlib.sha256(
        (TERMINAL_SCHEMA + "|rank-stratified-round-bootstrap-v1").encode(
            "ascii")).digest()[:8], "big")
    rng = random.Random(seed)
    samples = []
    for _ in range(BOOTSTRAP_REPLICATES):
        total = sum(
            row[rng.randrange(SELECTED_ROUNDS_PER_RANK)]
            for row in by_rank
            for _ in range(SELECTED_ROUNDS_PER_RANK))
        samples.append(_divide(total * 1_000_000_000, TARGET_ROUND_COUNT))
    samples.sort()
    lower_index = (25 * (BOOTSTRAP_REPLICATES - 1)) // 1000
    upper_index = (975 * (BOOTSTRAP_REPLICATES - 1)) // 1000
    flat = tuple(value for row in by_rank for value in row)
    return {
        "point_nanopoints": _mean_nano(flat),
        "bootstrap_lower_nanopoints": samples[lower_index],
        "bootstrap_upper_nanopoints": samples[upper_index],
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
    }


def reduce_policy_root_results(
        rows: tuple[dict[str, Any], ...], *,
        shard_sha256s: tuple[str, ...]) -> dict[str, Any]:
    """Reduce each verified shard once; never resample worlds or rollouts."""
    if type(rows) is not tuple or len(rows) != TARGET_ROUND_COUNT \
            or type(shard_sha256s) is not tuple \
            or len(shard_sha256s) != TARGET_ROUND_COUNT \
            or len(set(shard_sha256s)) != TARGET_ROUND_COUNT \
            or any(not _is_sha256(value) for value in shard_sha256s):
        raise BeliefPolicyStatisticsError(
            "policy terminal shard population drift")
    for row in rows:
        try:
            validate_policy_root_result(row)
        except ValueError as exc:
            raise BeliefPolicyStatisticsError(
                "policy terminal shard refused") from exc
    ordered = tuple(sorted(rows, key=lambda row: (
        POLICY_RANKS.index(row["coordinate"]["trump_rank"]),
        row["coordinate"]["rank_ordinal"])))
    identities = tuple((row["coordinate"]["trump_rank"],
                        row["coordinate"]["round_seed"])
                       for row in ordered)
    if len(set(identities)) != TARGET_ROUND_COUNT \
            or any(sum(identity[0] == rank for identity in identities)
                   != SELECTED_ROUNDS_PER_RANK for rank in POLICY_RANKS):
        raise BeliefPolicyStatisticsError(
            "policy terminal rank population drift")
    model_populations = {
        (tuple(row["models"]["primary"]["member_model_sha256s"]),
         tuple(row["models"]["control"]["member_model_sha256s"]))
        for row in ordered}
    if len(model_populations) != 1:
        raise BeliefPolicyStatisticsError(
            "policy terminal model population drift")

    def arm_map(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
        values = row["true_world"]["arms"]
        result = {value["arm_id"]: value for value in values}
        if tuple(result) != ARM_IDS:
            raise BeliefPolicyStatisticsError(
                "policy terminal arm population drift")
        return result

    mapped = tuple(arm_map(row) for row in ordered)
    primary_production = tuple(
        arms[PRIMARY_ARM]["true_world_value"]
        - arms[PRODUCTION_ARM]["true_world_value"] for arms in mapped)
    primary_control = tuple(
        arms[PRIMARY_ARM]["true_world_value"]
        - arms[CONTROL_ARM]["true_world_value"] for arms in mapped)

    def grouped(values: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
        return tuple(tuple(
            values[index * SELECTED_ROUNDS_PER_RANK
                   + offset]
            for offset in range(SELECTED_ROUNDS_PER_RANK))
            for index in range(len(POLICY_RANKS)))

    versus_production = _bootstrap_interval(grouped(primary_production))
    versus_control = _bootstrap_interval(grouped(primary_control))
    support_miss = tuple(not row["proposal_support"]["true_world_compatible"]
                         for row in ordered)
    if versus_production["bootstrap_lower_nanopoints"] > 0:
        if versus_control["bootstrap_lower_nanopoints"] <= 0:
            route = ROUTE_CONTROL
        elif any(support_miss):
            route = ROUTE_SUPPORT
        else:
            route = ROUTE_SIGNAL
    else:
        route = ROUTE_NONE
    oracle_agreement = {
        arm_id: _mean_ppb(tuple(
            arms[arm_id]["true_world_oracle_agreement"] for arms in mapped))
        for arm_id in ARM_IDS}
    final_flip = {
        arm_id: _mean_ppb(tuple(
            arms[arm_id]["final_action_flipped_vs_production"]
            for arms in mapped)) for arm_id in (PRIMARY_ARM, CONTROL_ARM)}
    nomination_flip = {
        arm_id: _mean_ppb(tuple(
            row["nominations"][ARM_IDS.index(arm_id)]["challenger_index"]
            != row["nominations"][0]["challenger_index"]
            for row in ordered)) for arm_id in (PRIMARY_ARM, CONTROL_ARM)}
    total_runtime = sum(row["work"]["total_nanoseconds"] for row in ordered)

    def weighting_summary(prefix: str) -> dict[str, Any]:
        result = {}
        for arm_id, suffix in ((PRIMARY_ARM, "primary"),
                               (CONTROL_ARM, "control")):
            values = tuple(
                row["weights"][f"{prefix}_{suffix}"] for row in ordered)
            alphas = sorted({value["alpha_ppb"] for value in values},
                            reverse=True)
            result[arm_id] = {
                "mean_applied_ess_ppb": _divide(
                    sum(value["ess_ppb"] for value in values),
                    TARGET_ROUND_COUNT),
                "mean_applied_max_weight_ppb": _divide(
                    sum(value["max_weight_ppb"] for value in values),
                    TARGET_ROUND_COUNT),
                "mean_untempered_ess_ppb": _divide(
                    sum(value["untempered_ess_ppb"] for value in values),
                    TARGET_ROUND_COUNT),
                "mean_untempered_max_weight_ppb": _divide(
                    sum(value["untempered_max_weight_ppb"]
                        for value in values), TARGET_ROUND_COUNT),
                "alpha_round_counts": {
                    str(alpha): sum(value["alpha_ppb"] == alpha
                                    for value in values)
                    for alpha in alphas},
            }
        return result

    def stratum_summary(labels: tuple[str, ...]) -> dict[str, Any]:
        if len(labels) != TARGET_ROUND_COUNT:
            raise BeliefPolicyStatisticsError(
                "policy stratum label population drift")
        result = {}
        for label in sorted(set(labels)):
            indices = tuple(index for index, value in enumerate(labels)
                            if value == label)
            result[label] = {
                "round_count": len(indices),
                "primary_minus_production_point_nanopoints": _mean_nano(
                    tuple(primary_production[index] for index in indices)),
                "primary_minus_control_point_nanopoints": _mean_nano(
                    tuple(primary_control[index] for index in indices)),
                "primary_oracle_agreement_ppb": _mean_ppb(tuple(
                    mapped[index][PRIMARY_ARM][
                        "true_world_oracle_agreement"] for index in indices)),
                "primary_final_action_flip_ppb": _mean_ppb(tuple(
                    mapped[index][PRIMARY_ARM][
                        "final_action_flipped_vs_production"]
                    for index in indices)),
            }
        return result

    actor_rows = tuple(row["actor"] for row in ordered)
    if any(type(actor) is not dict
           or type(actor.get("actor_is_attacker")) is not bool
           or type(actor.get("current_trick")) is not dict
           or type(actor["current_trick"].get("plays")) is not list
           for actor in actor_rows):
        raise BeliefPolicyStatisticsError(
            "policy secondary stratum actor drift")
    secondary_strata = {
        "trump_rank": stratum_summary(tuple(
            row["coordinate"]["trump_rank"] for row in ordered)),
        "actor_role": stratum_summary(tuple(
            "attacker" if actor["actor_is_attacker"] else "defender"
            for actor in actor_rows)),
        "lead_follow": stratum_summary(tuple(
            "lead" if not actor["current_trick"]["plays"] else "follow"
            for actor in actor_rows)),
        "decision_progress": stratum_summary(tuple(
            "early" if row["decision_index"] < 25 else
            "middle" if row["decision_index"] < 50 else "late"
            for row in ordered)),
    }
    return {
        "schema": TERMINAL_SCHEMA,
        "route": route,
        "round_count": TARGET_ROUND_COUNT,
        "rank_counts": {rank: SELECTED_ROUNDS_PER_RANK
                        for rank in POLICY_RANKS},
        "shard_sha256s": list(shard_sha256s),
        "primary_minus_production": versus_production,
        "primary_minus_control": versus_control,
        "oracle_agreement_ppb": oracle_agreement,
        "final_action_flip_dose_ppb": final_flip,
        "nomination_flip_dose_ppb": nomination_flip,
        "proposal_support_miss_count": sum(support_miss),
        "secondary_strata": secondary_strata,
        "weighting": {
            "selection": weighting_summary("selection"),
            "report": weighting_summary("report"),
        },
        "zero_weighting_dose_round_count": {
            PRIMARY_ARM: sum(
                row["weights"]["report_primary"]["alpha_ppb"] == 0
                for row in ordered),
            CONTROL_ARM: sum(
                row["weights"]["report_control"]["alpha_ppb"] == 0
                for row in ordered),
        },
        "runtime": {
            "total_root_nanoseconds": total_runtime,
            "total_root_cpu_nanoseconds": sum(
                row["work"]["total_cpu_nanoseconds"] for row in ordered),
            "mean_root_nanoseconds": _divide(
                total_runtime, TARGET_ROUND_COUNT),
            "phase_wall_nanoseconds": {
                phase: sum(row["work"][f"{phase}_nanoseconds"]
                           for row in ordered)
                for phase in ("inference", "sampling", "rollout")},
            "phase_cpu_nanoseconds": {
                phase: sum(row["work"][f"{phase}_cpu_nanoseconds"]
                           for row in ordered)
                for phase in ("inference", "sampling", "rollout")},
            "reference_attempts": sum(
                row["folds"]["proposal_reference"]["attempts"]
                for row in ordered),
            "selection_attempts": sum(
                row["folds"]["selection"]["attempts"]
                for row in ordered),
            "report_attempts": sum(
                row["folds"]["report"]["attempts"]
                for row in ordered),
        },
        "legality": {
            "validated_legal_world_count": sum(
                row["folds"][fold]["accepted_world_count"]
                for row in ordered
                for fold in ("proposal_reference", "selection", "report")),
            "illegal_world_count": 0,
            "all_world_folds_exact_and_validated": True,
        },
        "r4_test_opened": False,
        "r5_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
