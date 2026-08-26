"""Source-neutral model inference and exact round scoring for BELIEF-V1 V2.

V2 trains on the reviewed common public-history surface: final declaration,
engine-accepted plays, and no source-channel availability.  This module makes
that same transformation explicit at evaluation, binds REF-C and every model
to one mechanically equivalent scoring actor, and reduces exact per-decision
proper scores to complete-round units.

It has no filesystem, stage writer, test opener, sampler invocation, model
training, gameplay, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .belief_cohort import COHORT_SEEDS, ensemble_ownership
from .belief_artifacts import reopen_checkpoint_bundle
from .belief_checkpoint import reopen_model_checkpoint
from .belief_contract import ActorObservationV1, BeliefTargetsV1
from .belief_evaluation import (
    DecisionProperScoreV1,
    score_target_candidates,
)
from .belief_input import build_history_ownership_input
from .belief_model import (
    HistoryOwnershipModelV1,
    MODEL_SCHEMA,
    inference_logits,
    quantize_raw_count_weights,
)
from .belief_ownership import BeliefOwnershipV1, validate_ownership
from .belief_projection import project_count_weights
from .belief_refc_capture import (
    ReferenceWorldBatchV1,
    validate_reference_world_batch,
)
from .belief_v2_accelerator import portable_model_state_sha256
from .belief_v2_cohort_training import V2TrainedCohortArtifactsV1
from .belief_v2_common_surface import (
    V2CommonSurfaceTensorsV1,
    common_surface_actor,
    validate_common_surface_tensors,
)
from .belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from .belief_v2_statistics import V2RoundScoreV1, validate_v2_round_score


PPB = 1_000_000_000


class BeliefV2ScoringError(ValueError):
    """A V2 common actor, model, reference, or round score drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _round_divide(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefV2ScoringError("V2 scoring ratio input drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((2 * abs(numerator) + denominator)
                   // (2 * denominator))


def v2_scoring_actor(actor: ActorObservationV1) -> ActorObservationV1:
    """Return the exact complete-flag adapter used only for V2 mechanics."""
    try:
        common = common_surface_actor(actor)
        result = replace(
            common,
            declaration_history_complete=True,
            attempted_play_history_complete=True,
        )
        build_history_ownership_input(
            result, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    except ValueError as exc:
        raise BeliefV2ScoringError("V2 scoring actor derivation refused") \
            from exc
    return result


@dataclass(frozen=True)
class V2CohortModelsV1:
    cohort_id: str
    models: tuple[HistoryOwnershipModelV1, ...]
    model_sha256s: tuple[str, ...]


def validate_v2_cohort_models(value: V2CohortModelsV1) -> None:
    if type(value) is not V2CohortModelsV1 \
            or type(value.cohort_id) is not str or not value.cohort_id \
            or type(value.models) is not tuple \
            or len(value.models) != len(COHORT_SEEDS) \
            or any(type(model) is not HistoryOwnershipModelV1
                   for model in value.models) \
            or type(value.model_sha256s) is not tuple \
            or len(value.model_sha256s) != len(COHORT_SEEDS) \
            or len(set(value.model_sha256s)) != len(COHORT_SEEDS) \
            or any(not _is_sha256(digest)
                   for digest in value.model_sha256s):
        raise BeliefV2ScoringError("V2 scoring cohort population drift")
    for model, digest in zip(
            value.models, value.model_sha256s, strict=True):
        if next(model.parameters()).device.type != "cpu" \
                or portable_model_state_sha256(model) != digest:
            raise BeliefV2ScoringError(
                "V2 scoring cohort checkpoint identity drift")


def cohort_models_from_trained(
        trained: V2TrainedCohortArtifactsV1) -> V2CohortModelsV1:
    """Reopen every portable selected checkpoint for target-blind scoring."""
    if type(trained) is not V2TrainedCohortArtifactsV1 \
            or type(trained.checkpoint_bundles) is not tuple \
            or len(trained.checkpoint_bundles) != len(COHORT_SEEDS):
        raise BeliefV2ScoringError(
            "V2 trained scoring cohort population drift")
    models = []
    digests = []
    for raw in trained.checkpoint_bundles:
        try:
            checkpoint, receipt = reopen_checkpoint_bundle(raw)
            model = reopen_model_checkpoint(
                checkpoint, final_epoch_receipt=receipt)
        except ValueError as exc:
            raise BeliefV2ScoringError(
                "V2 scoring checkpoint reopen refused") from exc
        model.eval()
        models.append(model)
        digests.append(portable_model_state_sha256(model))
    result = V2CohortModelsV1(
        cohort_id=trained.cohort_id,
        models=tuple(models), model_sha256s=tuple(digests))
    validate_v2_cohort_models(result)
    return result


@dataclass(frozen=True)
class V2ScoringDecisionV1:
    decision_key: str
    source_actor: ActorObservationV1
    target: BeliefTargetsV1
    common: V2CommonSurfaceTensorsV1
    reference: ReferenceWorldBatchV1


def _validate_decision(value: V2ScoringDecisionV1) -> None:
    if type(value) is not V2ScoringDecisionV1 \
            or not _is_sha256(value.decision_key) \
            or type(value.source_actor) is not ActorObservationV1 \
            or type(value.target) is not BeliefTargetsV1 \
            or type(value.common) is not V2CommonSurfaceTensorsV1 \
            or type(value.reference) is not ReferenceWorldBatchV1:
        raise BeliefV2ScoringError("V2 scoring decision population drift")
    try:
        validate_common_surface_tensors(value.source_actor, value.common)
        validate_reference_world_batch(value.reference)
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring decision input refused") from exc
    expected = v2_scoring_actor(value.source_actor)
    reference_actor = v2_scoring_actor(value.reference.actor)
    if expected.canonical_bytes() != reference_actor.canonical_bytes():
        raise BeliefV2ScoringError(
            "V2 scoring reference public surface drift")


def _adapt_reference(
        actor: ActorObservationV1,
        batch: ReferenceWorldBatchV1) -> BeliefOwnershipV1:
    original = batch.ownership()
    result = replace(
        original,
        actor_observation_sha256=actor.sha256(),
        behavior_policy_ids=UNIVERSAL_POLICY_IDS,
    )
    try:
        validate_ownership(actor, result)
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring reference adaptation refused") from exc
    return result


def _predict_cohort(
        actor: ActorObservationV1,
        common: V2CommonSurfaceTensorsV1,
        cohort: V2CohortModelsV1, *, decision_key: str) \
        -> tuple[tuple[BeliefOwnershipV1, ...], BeliefOwnershipV1]:
    members = []
    for member_index, (model, model_sha) in enumerate(zip(
            cohort.models, cohort.model_sha256s, strict=True)):
        try:
            logits = inference_logits(model, common.tensors)
            raw = quantize_raw_count_weights(common.tensors, logits)
            prediction = project_count_weights(
                actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS,
                model_schema=MODEL_SCHEMA,
                model_sha256=model_sha, raw_weights=raw)
        except ValueError as exc:
            raise BeliefV2ScoringError(
                "V2 scoring member prediction refused: "
                f"decision_key={decision_key}, "
                f"cohort_id={cohort.cohort_id}, "
                f"member_index={member_index}, "
                f"model_sha256={model_sha}") from exc
        members.append(prediction)
    try:
        ensemble = ensemble_ownership(actor, tuple(members))
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring ensemble prediction refused") from exc
    return tuple(members), ensemble


def _score_ppb(numerator: int, denominator: int) -> int:
    return _round_divide(numerator * PPB, denominator)


def _mean(values: tuple[int, ...]) -> int:
    if not values:
        raise BeliefV2ScoringError("V2 scoring mean population is empty")
    return _round_divide(sum(values), len(values))


def _mean_brier(scores: tuple[DecisionProperScoreV1, ...], *,
                reference: bool) -> int:
    return _mean(tuple(_score_ppb(
        score.reference_brier_numerator if reference
        else score.candidate_brier_numerator,
        score.brier_denominator) for score in scores))


def score_v2_round(
        *, round_key: str, source_kind: str, split: str, trump_rank: str,
        decisions: tuple[V2ScoringDecisionV1, ...],
        cohorts: tuple[V2CohortModelsV1, ...]) -> V2RoundScoreV1:
    """Predict all frozen cohorts and reduce one complete round exactly."""
    if not _is_sha256(round_key) or source_kind not in {"synthetic", "human"} \
            or split not in {"calibration", "test"} \
            or type(trump_rank) is not str \
            or type(decisions) is not tuple or not decisions \
            or type(cohorts) is not tuple or not cohorts \
            or len({cohort.cohort_id for cohort in cohorts}) != len(cohorts):
        raise BeliefV2ScoringError("V2 scoring round identity drift")
    for decision in decisions:
        _validate_decision(decision)
    for cohort in cohorts:
        validate_v2_cohort_models(cohort)
    if len({decision.decision_key for decision in decisions}) \
            != len(decisions):
        raise BeliefV2ScoringError("V2 scoring decision duplicate")

    ensemble_scores: dict[str, list[DecisionProperScoreV1]] = {
        cohort.cohort_id: [] for cohort in cohorts}
    member_scores: dict[str, list[list[DecisionProperScoreV1]]] = {
        cohort.cohort_id: [[] for _ in COHORT_SEEDS] for cohort in cohorts}
    for decision in decisions:
        actor = v2_scoring_actor(decision.source_actor)
        reference = _adapt_reference(actor, decision.reference)
        for cohort in cohorts:
            members, ensemble = _predict_cohort(
                actor, decision.common, cohort,
                decision_key=decision.decision_key)
            if not reference.probabilities:
                if any(member.probabilities for member in members) \
                        or ensemble.probabilities:
                    raise BeliefV2ScoringError(
                        "V2 empty ownership population drift")
                continue
            scores = score_target_candidates(
                actor, decision.target, reference, (*members, ensemble))
            for index, score in enumerate(scores[:-1]):
                member_scores[cohort.cohort_id][index].append(score)
            ensemble_scores[cohort.cohort_id].append(scores[-1])
    if not any(ensemble_scores.values()):
        raise BeliefV2ScoringError(
            "V2 round has no informative ownership decisions")
    cohort_ids = tuple(cohort.cohort_id for cohort in cohorts)
    first = tuple(ensemble_scores[cohort_ids[0]])
    reference_brier = _mean_brier(first, reference=True)
    reference_log = _mean(tuple(
        score.reference_log_loss_nanonats for score in first))
    cohort_brier = []
    cohort_logs = []
    cohort_members = []
    for cohort_id in cohort_ids:
        scores = tuple(ensemble_scores[cohort_id])
        if tuple((row.actor_observation_sha256,
                  row.privileged_target_sha256,
                  row.reference_ownership_sha256,
                  row.reference_brier_numerator,
                  row.brier_denominator,
                  row.reference_log_loss_nanonats) for row in scores) \
                != tuple((row.actor_observation_sha256,
                           row.privileged_target_sha256,
                           row.reference_ownership_sha256,
                           row.reference_brier_numerator,
                           row.brier_denominator,
                           row.reference_log_loss_nanonats) for row in first):
            raise BeliefV2ScoringError(
                "V2 scoring reference cross-cohort drift")
        cohort_brier.append((cohort_id, _mean_brier(
            scores, reference=False)))
        cohort_logs.append((cohort_id, _mean(tuple(
            score.candidate_log_loss_nanonats for score in scores))))
        cohort_members.append((cohort_id, tuple(_mean_brier(
            tuple(rows), reference=False)
            for rows in member_scores[cohort_id])))
    result = V2RoundScoreV1(
        round_key=round_key, source_kind=source_kind, split=split,
        trump_rank=trump_rank, decision_count=len(decisions),
        reference_brier_ppb=reference_brier,
        reference_log_loss_nanonats=reference_log,
        cohort_brier_ppb=tuple(cohort_brier),
        cohort_log_loss_nanonats=tuple(cohort_logs),
        cohort_member_brier_ppb=tuple(cohort_members))
    try:
        validate_v2_round_score(result, cohort_ids=cohort_ids)
    except ValueError as exc:
        raise BeliefV2ScoringError("V2 round score validation refused") \
            from exc
    return result
