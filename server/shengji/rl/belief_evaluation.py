"""Privileged offline proper scoring for BELIEF-V1 ownership predictions.

This module is deliberately evaluator-only.  It accepts an exact actor row,
its separately stored privileged target, one REF-C ownership distribution,
and one candidate distribution.  It validates all four objects, reconstructs
the hidden count labels, and emits an integer-only score artifact.  It has no
filesystem, sampler, RNG, model, training, policy, gameplay, or runtime use.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from .belief_contract import (ActorObservationV1, BeliefTargetsV1,
                              canonical_json_bytes)
from .belief_corpus import CorpusPairV1, validate_corpus_pair
from .belief_ownership import (KITTY_RECEIVER, PROBABILITY_SCALE,
                               BeliefOwnershipV1, count_brier_fraction,
                               receiver_sizes, validate_ownership)
from .belief_reference import REF_C_MODEL_SCHEMA, REF_C_WORLD_COUNT
from .belief_reopen import (actor_observation_from_dict,
                            belief_targets_from_dict)


DECISION_SCORE_SCHEMA = "belief-v1-offline-decision-proper-score-v1"
LOG_LOSS_SCALE = 1_000_000_000
JEFFREYS_PSEUDOCOUNT_NUMERATOR = 1
JEFFREYS_PSEUDOCOUNT_DENOMINATOR = 2


class BeliefEvaluationError(ValueError):
    """Offline scoring inputs or their recomputed artifact are invalid."""


def reopen_score_pair(
        pair: CorpusPairV1) -> tuple[ActorObservationV1, BeliefTargetsV1,
                                     dict[str, Any]]:
    """Authenticate one paired corpus row before any privileged scoring."""
    if type(pair) is not CorpusPairV1:
        raise BeliefEvaluationError("offline score requires an exact corpus pair")
    try:
        actor_row, target_row = validate_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        actor = actor_observation_from_dict(actor_row["actor"])
        target = belief_targets_from_dict(target_row["target"], actor=actor)
    except (TypeError, ValueError) as exc:
        raise BeliefEvaluationError("offline corpus pair reconstruction refused") \
            from exc
    metadata = {
        key: actor_row[key]
        for key in ("round_seed", "decision_index", "actor_seat",
                    "decision_key", "split")
    }
    if any(target_row[key] != value for key, value in metadata.items()):
        raise BeliefEvaluationError("offline corpus pair metadata drift")
    return actor, target, metadata


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def target_count_population(
        actor: ActorObservationV1,
        target: BeliefTargetsV1) -> dict[tuple[str, str], int]:
    """Return exact hidden receiver-count labels after typed target reopening."""
    if type(actor) is not ActorObservationV1 \
            or type(target) is not BeliefTargetsV1:
        raise BeliefEvaluationError(
            "offline score requires exact actor and target types")
    try:
        reopened = belief_targets_from_dict(target.to_dict(), actor=actor)
    except (TypeError, ValueError) as exc:
        raise BeliefEvaluationError(
            "offline target reconstruction refused") from exc
    if reopened != target:
        raise BeliefEvaluationError("offline target reconstruction drift")
    counts = {
        (card, receiver): 0
        for card, _ in actor.deductions.unseen
        for receiver, _ in receiver_sizes(actor)
    }
    for hand in target.other_hands:
        receiver = f"seat-relative-{hand.seat_relative}"
        for card, count in hand.cards:
            counts[(card, receiver)] = count
    if actor.hidden_burial_size:
        for card, count in target.hidden_burial:
            counts[(card, KITTY_RECEIVER)] = count
    if any(type(value) is not int or value not in (0, 1, 2)
           for value in counts.values()):
        raise BeliefEvaluationError("offline target count population drift")
    return counts


def _smoothed_count_log_loss_nanonats(
        belief: BeliefOwnershipV1,
        counts: dict[tuple[str, str], int]) -> int:
    """Jeffreys-smoothed mean count log loss at the frozen REF-C ESS."""
    denominator = (REF_C_WORLD_COUNT
                   + JEFFREYS_PSEUDOCOUNT_NUMERATOR * 3
                   / JEFFREYS_PSEUDOCOUNT_DENOMINATOR)
    losses = []
    for row in belief.probabilities:
        truth = counts[(row.card, row.receiver)]
        probability_ppb = (
            row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)[truth]
        probability = (
            probability_ppb / PROBABILITY_SCALE * REF_C_WORLD_COUNT
            + JEFFREYS_PSEUDOCOUNT_NUMERATOR
            / JEFFREYS_PSEUDOCOUNT_DENOMINATOR
        ) / denominator
        if not 0.0 < probability <= 1.0 or not math.isfinite(probability):
            raise BeliefEvaluationError("smoothed count probability is invalid")
        losses.append(-math.log(probability))
    if not losses:
        raise BeliefEvaluationError("offline score population is empty")
    value = round(math.fsum(losses) / len(losses) * LOG_LOSS_SCALE)
    if type(value) is not int or value < 0:
        raise BeliefEvaluationError("smoothed count log loss is invalid")
    return value


@dataclass(frozen=True)
class DecisionProperScoreV1:
    actor_observation_sha256: str
    privileged_target_sha256: str
    reference_ownership_sha256: str
    candidate_ownership_sha256: str
    behavior_policy_ids: tuple[str, ...]
    count_rows: int
    brier_denominator: int
    reference_brier_numerator: int
    candidate_brier_numerator: int
    brier_improvement_numerator: int
    reference_log_loss_nanonats: int
    candidate_log_loss_nanonats: int
    log_loss_improvement_nanonats: int
    privileged_targets_consumed: bool = True
    runtime_artifact: bool = False
    schema: str = DECISION_SCORE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "actor_observation_sha256": self.actor_observation_sha256,
            "privileged_target_sha256": self.privileged_target_sha256,
            "reference_ownership_sha256": self.reference_ownership_sha256,
            "candidate_ownership_sha256": self.candidate_ownership_sha256,
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "count_rows": self.count_rows,
            "count_brier": {
                "denominator": self.brier_denominator,
                "reference_numerator": self.reference_brier_numerator,
                "candidate_numerator": self.candidate_brier_numerator,
                "reference_minus_candidate_numerator": (
                    self.brier_improvement_numerator),
            },
            "smoothed_count_log_loss_nanonats": {
                "reference": self.reference_log_loss_nanonats,
                "candidate": self.candidate_log_loss_nanonats,
                "reference_minus_candidate": (
                    self.log_loss_improvement_nanonats),
                "scale": LOG_LOSS_SCALE,
                "reference_equivalent_sample_count": REF_C_WORLD_COUNT,
                "jeffreys_pseudocount": "0.5-per-count-cell",
            },
            "privileged_targets_consumed": self.privileged_targets_consumed,
            "runtime_artifact": self.runtime_artifact,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _score_decision(
        actor: ActorObservationV1, target: BeliefTargetsV1,
        reference: BeliefOwnershipV1,
        candidate: BeliefOwnershipV1) -> DecisionProperScoreV1:
    counts = target_count_population(actor, target)
    try:
        validate_ownership(actor, reference)
        validate_ownership(actor, candidate)
    except ValueError as exc:
        raise BeliefEvaluationError("offline ownership validation refused") \
            from exc
    if reference.model_schema != REF_C_MODEL_SCHEMA:
        raise BeliefEvaluationError("offline reference is not exact REF-C")
    if reference.behavior_policy_ids != candidate.behavior_policy_ids:
        raise BeliefEvaluationError("offline behavior-policy comparison drift")
    if tuple((row.card, row.receiver) for row in reference.probabilities) \
            != tuple((row.card, row.receiver)
                     for row in candidate.probabilities):
        raise BeliefEvaluationError("offline ownership population drift")
    reference_brier = count_brier_fraction(reference, counts)
    candidate_brier = count_brier_fraction(candidate, counts)
    if reference_brier[1] != candidate_brier[1]:
        raise BeliefEvaluationError("offline Brier denominator drift")
    reference_log = _smoothed_count_log_loss_nanonats(reference, counts)
    candidate_log = _smoothed_count_log_loss_nanonats(candidate, counts)
    return DecisionProperScoreV1(
        actor_observation_sha256=actor.sha256(),
        privileged_target_sha256=target.sha256(),
        reference_ownership_sha256=reference.sha256(),
        candidate_ownership_sha256=candidate.sha256(),
        behavior_policy_ids=reference.behavior_policy_ids,
        count_rows=len(reference.probabilities),
        brier_denominator=reference_brier[1],
        reference_brier_numerator=reference_brier[0],
        candidate_brier_numerator=candidate_brier[0],
        brier_improvement_numerator=(
            reference_brier[0] - candidate_brier[0]),
        reference_log_loss_nanonats=reference_log,
        candidate_log_loss_nanonats=candidate_log,
        log_loss_improvement_nanonats=reference_log - candidate_log,
    )


def score_corpus_decision(
        pair: CorpusPairV1,
        reference: BeliefOwnershipV1,
        candidate: BeliefOwnershipV1) -> DecisionProperScoreV1:
    """Build and recompute one score from an exact hash-bound corpus pair."""
    actor, target, _ = reopen_score_pair(pair)
    score = _score_decision(actor, target, reference, candidate)
    validate_decision_score(pair, reference, candidate, score)
    return score


def validate_decision_score(
        pair: CorpusPairV1,
        reference: BeliefOwnershipV1, candidate: BeliefOwnershipV1,
        score: DecisionProperScoreV1) -> None:
    actor, target, _ = reopen_score_pair(pair)
    if type(score) is not DecisionProperScoreV1 \
            or score.schema != DECISION_SCORE_SCHEMA \
            or score.privileged_targets_consumed is not True \
            or score.runtime_artifact is not False \
            or not all(_is_sha256(value) for value in (
                score.actor_observation_sha256,
                score.privileged_target_sha256,
                score.reference_ownership_sha256,
                score.candidate_ownership_sha256)):
        raise BeliefEvaluationError("offline score schema/authority drift")
    if score != _score_decision(actor, target, reference, candidate):
        raise BeliefEvaluationError("offline score derivation drift")
