"""Canonical resumable result shards for the R4 policy diagnostic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..ai.mcbot import MCBot, point_shy_pick_index
from .belief_artifacts import (
    publish_exclusive_bytes,
    stable_read_bytes,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_policy_evaluation import PolicyRootEvaluationV1
from .belief_policy_protocol import (
    REFERENCE_WORLD_COUNT,
    REPORT_WORLD_COUNT,
    SELECTION_WORLD_COUNT,
    policy_root_order_key,
    policy_round_coordinates,
)
from .belief_policy_search import (
    ARM_IDS,
    ArmDecisionV1,
    ArmNominationV1,
    finalize_three_arms,
    nominate_three_arms,
)
from .belief_policy_weighting import (
    TemperedWorldWeightsV1,
    common_tempered_world_weights,
    validate_tempered_world_weights,
)
from .belief_reopen import actor_observation_from_dict
from .belief_v2_freeze import CONTROL_COHORT_ID, PRIMARY_COHORT_ID
from .belief_v2_scoring import V2CohortModelsV1, validate_v2_cohort_models


POLICY_ROOT_RESULT_SCHEMA = "belief-r4-policy-root-result-v1"


class BeliefPolicyArtifactError(ValueError):
    """A policy root shard, derivation, or immutable slot drifted."""


def _sha(value: str) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefPolicyArtifactError(
                "policy result contains duplicate key")
        result[key] = value
    return result


def _strict(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                BeliefPolicyArtifactError(
                    "policy result contains nonfinite number")),
        )
    except BeliefPolicyArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefPolicyArtifactError(
            "policy result is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefPolicyArtifactError(
            "policy result is not canonical")
    return value


def _nano(value: float) -> int:
    return round(value * 1_000_000_000)


def _integral(value: float) -> int:
    if type(value) not in (int, float) or not float(value).is_integer():
        raise BeliefPolicyArtifactError(
            "policy rollout value is not an integer point total")
    return int(value)


def _weights_dict(value: TemperedWorldWeightsV1) -> dict[str, Any]:
    validate_tempered_world_weights(value)
    return {
        "alpha_ppb": value.alpha_ppb,
        "log_ratio_nanonats": list(value.log_ratio_nanonats),
        "normalized_weight_ppb": list(value.normalized_weight_ppb),
        "ess_ppb": value.ess_ppb,
        "max_weight_ppb": value.max_weight_ppb,
        "untempered_ess_ppb": value.untempered_ess_ppb,
        "untempered_max_weight_ppb": value.untempered_max_weight_ppb,
    }


def _weights_from_dict(value: Any) -> TemperedWorldWeightsV1:
    if type(value) is not dict or set(value) != {
            "alpha_ppb", "log_ratio_nanonats", "normalized_weight_ppb",
            "ess_ppb", "max_weight_ppb", "untempered_ess_ppb",
            "untempered_max_weight_ppb"} \
            or type(value["log_ratio_nanonats"]) is not list \
            or type(value["normalized_weight_ppb"]) is not list:
        raise BeliefPolicyArtifactError(
            "policy result weight schema drift")
    result = TemperedWorldWeightsV1(
        alpha_ppb=value["alpha_ppb"],
        log_ratio_nanonats=tuple(value["log_ratio_nanonats"]),
        normalized_weight_ppb=tuple(value["normalized_weight_ppb"]),
        ess_ppb=value["ess_ppb"],
        max_weight_ppb=value["max_weight_ppb"],
        untempered_ess_ppb=value["untempered_ess_ppb"],
        untempered_max_weight_ppb=value["untempered_max_weight_ppb"],
    )
    try:
        validate_tempered_world_weights(result)
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy result weight mechanics refused") from exc
    return result


def _nomination_dict(value: ArmNominationV1) -> dict[str, Any]:
    return {
        "arm_id": value.arm_id,
        "selection_mean_nanopoints": [
            _nano(item) for item in value.selection_means],
        "raw_winner_index": value.raw_winner_index,
        "challenger_index": value.challenger_index,
    }


def _decision_dict(value: ArmDecisionV1) -> dict[str, Any]:
    return {
        "arm_id": value.nomination.arm_id,
        "report_gap_nanopoints": _nano(value.report_gap),
        "report_se_nanopoints": _nano(value.report_se),
        "report_lcb_nanopoints": _nano(value.report_lcb),
        "played_index": value.played_index,
        "reason": value.reason,
    }


def _batch_summary(batch) -> dict[str, Any]:
    value = batch.manifest_dict()
    # Raw worlds are intentionally not duplicated into the result shard. The
    # immutable stream hash and exact accounting bind what the reducer used.
    return value


def build_policy_root_result(
        evaluation: PolicyRootEvaluationV1, *,
        primary: V2CohortModelsV1,
        control: V2CohortModelsV1) -> dict[str, Any]:
    if type(evaluation) is not PolicyRootEvaluationV1:
        raise BeliefPolicyArtifactError(
            "policy result evaluation type drift")
    if evaluation.true_world_is_privileged is not True:
        raise BeliefPolicyArtifactError(
            "policy result requires privileged scientific truth")
    try:
        validate_v2_cohort_models(primary)
        validate_v2_cohort_models(control)
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy result cohort refused") from exc
    if primary.cohort_id != PRIMARY_COHORT_ID \
            or control.cohort_id != CONTROL_COHORT_ID:
        raise BeliefPolicyArtifactError(
            "policy result cohort identity drift")
    root = evaluation.root
    selection_values = [
        [_integral(item) for item in row]
        for row in evaluation.selection_values]
    report_values = [{
        "candidate_index": index,
        "values": [_integral(item) for item in values],
    } for index, values in evaluation.report_values_by_candidate]
    true_values = [_integral(value) for value in evaluation.true_world_values]
    production_index = evaluation.decisions[0].played_index
    arms = []
    for decision in evaluation.decisions:
        played = decision.played_index
        arms.append({
            "arm_id": decision.nomination.arm_id,
            "played_index": played,
            "played_cards": list(root.candidates[played]),
            "true_world_value": true_values[played],
            "true_world_oracle_agreement": (
                played == evaluation.true_world_oracle_index),
            "final_action_flipped_vs_production": (
                played != production_index),
        })
    payload = {
        "schema": POLICY_ROOT_RESULT_SCHEMA,
        "coordinate": {
            "trump_rank": root.coordinate.trump_rank,
            "rank_index": root.coordinate.rank_index,
            "rank_ordinal": root.coordinate.rank_ordinal,
            "round_seed": root.coordinate.round_seed,
        },
        "decision_index": root.decision_index,
        "actor_seat": root.actor_seat,
        "actor": root.actor.to_dict(),
        "actor_sha256": root.actor.sha256(),
        "selection_key_sha256": root.selection_key.hex(),
        "candidates": [list(candidate) for candidate in root.candidates],
        "proposal_support": {
            "declaration_eligibility_count": len(
                root.actor.deductions.declaration_eligibility),
            "true_world_compatible": root.proposal_true_world_compatible,
        },
        "models": {
            "primary": {
                "cohort_id": primary.cohort_id,
                "member_model_sha256s": list(primary.model_sha256s),
            },
            "control": {
                "cohort_id": control.cohort_id,
                "member_model_sha256s": list(control.model_sha256s),
            },
        },
        "folds": {
            "proposal_reference": _batch_summary(
                evaluation.reference_batch),
            "selection": _batch_summary(evaluation.selection_batch),
            "report": _batch_summary(evaluation.report_batch),
        },
        "weights": {
            "selection_primary": _weights_dict(
                evaluation.primary_selection_weights),
            "selection_control": _weights_dict(
                evaluation.control_selection_weights),
            "report_primary": _weights_dict(
                evaluation.primary_report_weights),
            "report_control": _weights_dict(
                evaluation.control_report_weights),
        },
        "selection_values": selection_values,
        "nominations": [_nomination_dict(row)
                        for row in evaluation.nominations],
        "report_values": report_values,
        "decisions": [_decision_dict(row) for row in evaluation.decisions],
        "true_world": {
            "candidate_values": true_values,
            "oracle_index": evaluation.true_world_oracle_index,
            "arms": arms,
            "used_for_root_selection_or_weighting": False,
        },
        "work": {
            "reference_worlds": evaluation.work.reference_worlds,
            "selection_worlds": evaluation.work.selection_worlds,
            "report_worlds": evaluation.work.report_worlds,
            "selection_physical_rollouts": (
                evaluation.work.selection_physical_rollouts),
            "report_physical_rollouts": (
                evaluation.work.report_physical_rollouts),
            "report_logical_rollouts_per_arm": (
                evaluation.work.report_logical_rollouts_per_arm),
            "true_world_rollouts": evaluation.work.true_world_rollouts,
            "inference_nanoseconds": _nano(
                evaluation.work.inference_seconds),
            "inference_cpu_nanoseconds": _nano(
                evaluation.work.inference_cpu_seconds),
            "sampling_nanoseconds": _nano(
                evaluation.work.sampling_seconds),
            "sampling_cpu_nanoseconds": _nano(
                evaluation.work.sampling_cpu_seconds),
            "rollout_nanoseconds": _nano(
                evaluation.work.rollout_seconds),
            "rollout_cpu_nanoseconds": _nano(
                evaluation.work.rollout_cpu_seconds),
            "total_nanoseconds": _nano(evaluation.work.total_seconds),
            "total_cpu_nanoseconds": _nano(
                evaluation.work.total_cpu_seconds),
        },
        "contains_sampled_hidden_worlds": False,
        "contains_privileged_true_world_values": True,
        "r4_test_opened": False,
        "r5_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    validate_policy_root_result(payload)
    return payload


def _validate_batch_summary(
        value: Any, *, actor_sha256: str, world_count: int) -> None:
    expected_keys = {
        "schema", "actor_observation_sha256", "policy_name", "sampler_seed",
        "requested_world_count", "accepted_world_count", "attempts",
        "attempt_cap", "sampler_before", "sampler_after", "sampler_delta",
        "world_stream_sha256", "strict_void_sampling",
        "contains_round_outcome", "contains_privileged_target",
        "runtime_input", "gameplay_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(value) is not dict or set(value) != expected_keys \
            or value["actor_observation_sha256"] != actor_sha256 \
            or value["policy_name"] != "mc-s0-report-lcb" \
            or value["requested_world_count"] != world_count \
            or value["accepted_world_count"] != world_count \
            or type(value["attempts"]) is not int \
            or not world_count <= value["attempts"] <= value["attempt_cap"] \
            or value["attempt_cap"] != world_count * MCBot.SAMPLE_ATTEMPT_FACTOR \
            or not _sha(value["world_stream_sha256"]) \
            or value["strict_void_sampling"] is not True \
            or any(value[key] is not False for key in (
                "contains_round_outcome", "contains_privileged_target",
                "runtime_input", "gameplay_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefPolicyArtifactError(
            "policy result fold summary drift")


def validate_policy_root_result(value: dict[str, Any]) -> None:
    expected_keys = {
        "schema", "coordinate", "decision_index", "actor_seat", "actor",
        "actor_sha256", "selection_key_sha256", "candidates",
        "proposal_support", "models", "folds", "weights",
        "selection_values", "nominations", "report_values", "decisions",
        "true_world", "work", "contains_sampled_hidden_worlds",
        "contains_privileged_true_world_values", "r4_test_opened",
        "r5_authorized", "gameplay_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(value) is not dict or set(value) != expected_keys \
            or value["schema"] != POLICY_ROOT_RESULT_SCHEMA \
            or type(value["coordinate"]) is not dict \
            or set(value["coordinate"]) != {
                "trump_rank", "rank_index", "rank_ordinal", "round_seed"} \
            or type(value["decision_index"]) is not int \
            or value["decision_index"] < 0 \
            or type(value["actor_seat"]) is not int \
            or value["actor_seat"] not in range(4) \
            or not _sha(value["actor_sha256"]) \
            or not _sha(value["selection_key_sha256"]) \
            or value["contains_sampled_hidden_worlds"] is not False \
            or value["contains_privileged_true_world_values"] is not True \
            or any(value[key] is not False for key in (
                "r4_test_opened", "r5_authorized", "gameplay_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefPolicyArtifactError(
            "policy result schema/authority drift")
    coordinate = next((row for row in policy_round_coordinates()
                       if row.round_seed == value["coordinate"]["round_seed"]),
                      None)
    if coordinate is None or value["coordinate"] != {
            "trump_rank": coordinate.trump_rank,
            "rank_index": coordinate.rank_index,
            "rank_ordinal": coordinate.rank_ordinal,
            "round_seed": coordinate.round_seed,
            }:
        raise BeliefPolicyArtifactError(
            "policy result coordinate derivation drift")
    try:
        actor = actor_observation_from_dict(value["actor"])
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy result actor reconstruction refused") from exc
    if actor.sha256() != value["actor_sha256"] \
            or actor.trump_rank != coordinate.trump_rank \
            or value["selection_key_sha256"] != policy_root_order_key(
                coordinate, decision_index=value["decision_index"],
                actor_sha256=actor.sha256()).hex():
        raise BeliefPolicyArtifactError("policy result actor hash drift")
    candidates_raw = value["candidates"]
    if type(candidates_raw) is not list or len(candidates_raw) < 2 \
            or any(type(row) is not list or not row
                   or any(type(card) is not str or not card for card in row)
                   for row in candidates_raw):
        raise BeliefPolicyArtifactError("policy result ballot drift")
    candidates = tuple(tuple(row) for row in candidates_raw)
    if len(set(candidates)) != len(candidates):
        raise BeliefPolicyArtifactError("policy result ballot duplicate")
    models = value["models"]
    if type(models) is not dict or set(models) != {"primary", "control"}:
        raise BeliefPolicyArtifactError("policy result model schema drift")
    for label, cohort_id in (("primary", PRIMARY_COHORT_ID),
                             ("control", CONTROL_COHORT_ID)):
        row = models[label]
        if type(row) is not dict or set(row) != {
                "cohort_id", "member_model_sha256s"} \
                or row["cohort_id"] != cohort_id \
                or type(row["member_model_sha256s"]) is not list \
                or len(row["member_model_sha256s"]) != len(COHORT_SEEDS) \
                or len(set(row["member_model_sha256s"])) != len(COHORT_SEEDS) \
                or any(not _sha(digest)
                       for digest in row["member_model_sha256s"]):
            raise BeliefPolicyArtifactError(
                "policy result model population drift")
    folds = value["folds"]
    if type(folds) is not dict or set(folds) != {
            "proposal_reference", "selection", "report"}:
        raise BeliefPolicyArtifactError("policy result fold schema drift")
    _validate_batch_summary(
        folds["proposal_reference"], actor_sha256=actor.sha256(),
        world_count=REFERENCE_WORLD_COUNT)
    _validate_batch_summary(
        folds["selection"], actor_sha256=actor.sha256(),
        world_count=SELECTION_WORLD_COUNT)
    _validate_batch_summary(
        folds["report"], actor_sha256=actor.sha256(),
        world_count=REPORT_WORLD_COUNT)

    weights = value["weights"]
    if type(weights) is not dict or set(weights) != {
            "selection_primary", "selection_control",
            "report_primary", "report_control"}:
        raise BeliefPolicyArtifactError("policy result weight population drift")
    selection_primary = _weights_from_dict(weights["selection_primary"])
    selection_control = _weights_from_dict(weights["selection_control"])
    report_primary = _weights_from_dict(weights["report_primary"])
    report_control = _weights_from_dict(weights["report_control"])
    try:
        expected_selection_weights = common_tempered_world_weights(
            selection_primary.log_ratio_nanonats,
            selection_control.log_ratio_nanonats)
        expected_report_weights = common_tempered_world_weights(
            report_primary.log_ratio_nanonats,
            report_control.log_ratio_nanonats)
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy result common temperature reconstruction refused") from exc
    if (selection_primary, selection_control) \
            != expected_selection_weights \
            or (report_primary, report_control) != expected_report_weights:
        raise BeliefPolicyArtifactError(
            "policy result common temperature reconstruction drift")
    selection = value["selection_values"]
    if type(selection) is not list or len(selection) != SELECTION_WORLD_COUNT \
            or any(type(row) is not list or len(row) != len(candidates)
                   or any(type(item) is not int for item in row)
                   for row in selection):
        raise BeliefPolicyArtifactError(
            "policy result selection tensor drift")
    recomputed_nominations = nominate_three_arms(
        candidates, tuple(tuple(row) for row in selection),
        primary_weights=selection_primary,
        control_weights=selection_control)
    if value["nominations"] != [
            _nomination_dict(row) for row in recomputed_nominations]:
        raise BeliefPolicyArtifactError(
            "policy result nomination reconstruction drift")
    report_rows = value["report_values"]
    if type(report_rows) is not list \
            or any(type(row) is not dict
                   or set(row) != {"candidate_index", "values"}
                   or type(row["candidate_index"]) is not int
                   or type(row["values"]) is not list
                   or len(row["values"]) != REPORT_WORLD_COUNT
                   or any(type(item) is not int for item in row["values"])
                   for row in report_rows):
        raise BeliefPolicyArtifactError("policy result report tensor drift")
    recomputed_decisions = finalize_three_arms(
        candidates, recomputed_nominations,
        tuple((row["candidate_index"], tuple(row["values"]))
              for row in report_rows),
        primary_weights=report_primary,
        control_weights=report_control)
    if value["decisions"] != [
            _decision_dict(row) for row in recomputed_decisions]:
        raise BeliefPolicyArtifactError(
            "policy result decision reconstruction drift")
    true_world = value["true_world"]
    if type(true_world) is not dict or set(true_world) != {
            "candidate_values", "oracle_index", "arms",
            "used_for_root_selection_or_weighting"} \
            or type(true_world["candidate_values"]) is not list \
            or len(true_world["candidate_values"]) != len(candidates) \
            or any(type(item) is not int
                   for item in true_world["candidate_values"]) \
            or true_world["used_for_root_selection_or_weighting"] is not False:
        raise BeliefPolicyArtifactError(
            "policy result true-world population drift")
    oracle = point_shy_pick_index(
        candidates, true_world["candidate_values"], range(len(candidates)),
        epsilon=MCBot.POINT_SHY_EPS)
    if true_world["oracle_index"] != oracle \
            or type(true_world["arms"]) is not list \
            or len(true_world["arms"]) != len(ARM_IDS):
        raise BeliefPolicyArtifactError(
            "policy result true-world oracle drift")
    production_index = recomputed_decisions[0].played_index
    expected_arms = []
    for decision in recomputed_decisions:
        played = decision.played_index
        expected_arms.append({
            "arm_id": decision.nomination.arm_id,
            "played_index": played,
            "played_cards": list(candidates[played]),
            "true_world_value": true_world["candidate_values"][played],
            "true_world_oracle_agreement": played == oracle,
            "final_action_flipped_vs_production": played != production_index,
        })
    if true_world["arms"] != expected_arms:
        raise BeliefPolicyArtifactError(
            "policy result true-world arm reconstruction drift")
    support = value["proposal_support"]
    if type(support) is not dict or set(support) != {
            "declaration_eligibility_count", "true_world_compatible"} \
            or support["declaration_eligibility_count"] \
            != len(actor.deductions.declaration_eligibility) \
            or type(support["true_world_compatible"]) is not bool:
        raise BeliefPolicyArtifactError(
            "policy result proposal support drift")
    work = value["work"]
    if type(work) is not dict or set(work) != {
            "reference_worlds", "selection_worlds", "report_worlds",
            "selection_physical_rollouts", "report_physical_rollouts",
            "report_logical_rollouts_per_arm", "true_world_rollouts",
            "inference_nanoseconds", "sampling_nanoseconds",
            "rollout_nanoseconds", "total_nanoseconds",
            "inference_cpu_nanoseconds", "sampling_cpu_nanoseconds",
            "rollout_cpu_nanoseconds", "total_cpu_nanoseconds"} \
            or work["reference_worlds"] != REFERENCE_WORLD_COUNT \
            or work["selection_worlds"] != SELECTION_WORLD_COUNT \
            or work["report_worlds"] != REPORT_WORLD_COUNT \
            or work["selection_physical_rollouts"] \
            != SELECTION_WORLD_COUNT * len(candidates) \
            or work["report_physical_rollouts"] \
            != REPORT_WORLD_COUNT * len(report_rows) \
            or work["report_logical_rollouts_per_arm"] \
            != 2 * REPORT_WORLD_COUNT \
            or work["true_world_rollouts"] != len(candidates) \
            or any(type(work[key]) is not int or work[key] < 0 for key in (
                "inference_nanoseconds", "sampling_nanoseconds",
                "rollout_nanoseconds", "total_nanoseconds",
                "inference_cpu_nanoseconds", "sampling_cpu_nanoseconds",
                "rollout_cpu_nanoseconds", "total_cpu_nanoseconds")):
        raise BeliefPolicyArtifactError("policy result work drift")


def publish_policy_root_result(
        path: Path, evaluation: PolicyRootEvaluationV1, *,
        primary: V2CohortModelsV1,
        control: V2CohortModelsV1) -> str:
    raw = canonical_json_bytes(build_policy_root_result(
        evaluation, primary=primary, control=control))
    try:
        return publish_exclusive_bytes(path, raw)
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy root result publication refused") from exc


def reopen_policy_root_result(path: Path) -> dict[str, Any]:
    value, _, _ = reopen_policy_root_result_with_sha256(path)
    return value


def reopen_policy_root_result_with_sha256(
        path: Path) -> tuple[dict[str, Any], str, int]:
    """Read once; return the validated value, digest, and exact byte count."""
    try:
        raw = stable_read_bytes(path)
    except ValueError as exc:
        raise BeliefPolicyArtifactError(
            "policy root result stable read refused") from exc
    value = _strict(raw)
    validate_policy_root_result(value)
    return value, hashlib.sha256(raw).hexdigest(), len(raw)
