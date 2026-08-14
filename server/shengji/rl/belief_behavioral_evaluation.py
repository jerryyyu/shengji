"""Exact C2/N1 behavioral-stratum scoring for BELIEF-V1 B2.

Confirmed public-choice signals are evaluated only for the hidden receiver
that emitted them and only until that seat acts again.  Candidate, target-
blind history-ablation, and exact REF-C ownership probabilities are scored on
the same receiver/count cells.  The round is the bootstrap unit.

This evaluator consumes privileged labels and separated signal audits.  It is
offline-only and has no model execution, training, sampler draw, filesystem,
policy, gameplay, strength, or deployment authority.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (
    PRIMARY_BOOTSTRAP_REPLICATES,
    REFERENCE_BRIER_CORRECTION,
    b2_split_round_seeds,
    protocol_sha256,
)
from .belief_behavioral import (
    SIGNAL_KINDS,
    BehavioralSignalRoundV1,
    behavioral_signal_exposures,
    validate_behavioral_signal_round,
)
from .belief_capture import CapturedBeliefRoundV1, validate_captured_round
from .belief_contract import canonical_json_bytes
from .belief_evaluation import (reopen_score_pair,
                                target_count_population)
from .belief_ownership import (
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    validate_ownership,
)
from .belief_refc_capture import (
    ReferenceCapturedRoundV1,
    validate_reference_captured_round,
)
from .belief_reference import REF_C_WORLD_COUNT


POOLED_STRATUM = "all-confirmed-choice-signals-v1"
BEHAVIORAL_STRATA = (POOLED_STRATUM, *SIGNAL_KINDS)
MIN_BEHAVIORAL_EXPOSURES = 500
HISTORY_ABLATION_RETAIN_CAP_PPB = 250_000_000
BEHAVIORAL_ROUND_SCHEMA = "belief-v1-b2-behavioral-round-score-v2"
BEHAVIORAL_STRATUM_SCORE_SCHEMA = (
    "belief-v1-b2-behavioral-round-stratum-score-v2")
BEHAVIORAL_RESULT_SCHEMA = "belief-v1-b2-behavioral-calibration-result-v2"
PPB = 1_000_000_000


class BeliefBehavioralEvaluationError(ValueError):
    """Behavioral evaluation inputs or exact statistics drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class BehavioralDecisionPredictionsV1:
    candidate: BeliefOwnershipV1
    history_ablated: BeliefOwnershipV1


@dataclass(frozen=True)
class BehavioralRoundStratumScoreV1:
    stratum: str
    public_receiver_decision_count: int
    confirmed_receiver_decision_count: int
    probability_cell_count: int
    raw_brier_denominator: int
    reference_raw_brier_numerator: int
    reference_finite_sample_bias_numerator: int
    brier_denominator: int
    reference_brier_numerator: int
    candidate_brier_numerator: int
    history_ablated_brier_numerator: int
    schema: str = BEHAVIORAL_STRATUM_SCORE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "stratum": self.stratum,
            "public_receiver_decision_count": (
                self.public_receiver_decision_count),
            "confirmed_receiver_decision_count": (
                self.confirmed_receiver_decision_count),
            "probability_cell_count": self.probability_cell_count,
            "count_brier": {
                "raw": {
                    "denominator": self.raw_brier_denominator,
                    "reference_numerator": (
                        self.reference_raw_brier_numerator),
                },
                "reference_finite_sample_bias_correction": {
                    "method": REFERENCE_BRIER_CORRECTION,
                    "world_count": REF_C_WORLD_COUNT,
                    "numerator": (
                        self.reference_finite_sample_bias_numerator),
                    "denominator": self.brier_denominator,
                },
                "bias_corrected": {
                    "denominator": self.brier_denominator,
                    "reference_numerator": self.reference_brier_numerator,
                    "candidate_numerator": self.candidate_brier_numerator,
                    "history_ablated_numerator": (
                        self.history_ablated_brier_numerator),
                },
            },
        }


@dataclass(frozen=True)
class BehavioralRoundScoreV1:
    round_seed: int
    reference_round_manifest_sha256: str
    public_signal_stream_sha256: str
    privileged_signal_stream_sha256: str
    candidate_model_schema: str
    candidate_model_sha256: str
    strata: tuple[BehavioralRoundStratumScoreV1, ...]
    schema: str = BEHAVIORAL_ROUND_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "reference_round_manifest_sha256": (
                self.reference_round_manifest_sha256),
            "public_signal_stream_sha256": self.public_signal_stream_sha256,
            "privileged_signal_stream_sha256": (
                self.privileged_signal_stream_sha256),
            "candidate_model_schema": self.candidate_model_schema,
            "candidate_model_sha256": self.candidate_model_sha256,
            "strata": [row.to_dict() for row in self.strata],
            "privileged_targets_consumed": True,
            "runtime_artifact": False,
        }


@dataclass(frozen=True)
class BehavioralStratumResultV1:
    stratum: str
    eligible_round_count: int
    confirmed_receiver_decision_count: int
    candidate_mean_brier_improvement_ppb: int
    candidate_bootstrap_lower_improvement_ppb: int
    history_ablated_mean_brier_improvement_ppb: int
    history_retained_fraction_ppb: int
    underpowered: bool
    candidate_lift_supported: bool
    history_ablation_collapsed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "stratum": self.stratum,
            "eligible_round_count": self.eligible_round_count,
            "confirmed_receiver_decision_count": (
                self.confirmed_receiver_decision_count),
            "candidate_mean_brier_improvement_ppb": (
                self.candidate_mean_brier_improvement_ppb),
            "candidate_bootstrap_lower_improvement_ppb": (
                self.candidate_bootstrap_lower_improvement_ppb),
            "history_ablated_mean_brier_improvement_ppb": (
                self.history_ablated_mean_brier_improvement_ppb),
            "history_retained_fraction_ppb": (
                self.history_retained_fraction_ppb),
            "minimum_receiver_decisions_for_claim": (
                MIN_BEHAVIORAL_EXPOSURES),
            "underpowered": self.underpowered,
            "candidate_lift_supported": self.candidate_lift_supported,
            "history_ablation_collapsed": self.history_ablation_collapsed,
        }


@dataclass(frozen=True)
class C2BehavioralResultV1:
    strata: tuple[BehavioralStratumResultV1, ...]
    pooled_behavioral_claim_passed: bool
    schema: str = BEHAVIORAL_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "bootstrap": {
                "unit": "complete-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "one_sided_percentile": 5,
            },
            "strata": [row.to_dict() for row in self.strata],
            "pooled_behavioral_claim_passed": (
                self.pooled_behavioral_claim_passed),
            "privileged_targets_consumed": True,
            "runtime_artifact": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _subset_brier(
        belief: BeliefOwnershipV1,
        counts: dict[tuple[str, str], int], receiver: str) \
        -> tuple[int, int, int]:
    rows = tuple(row for row in belief.probabilities
                 if row.receiver == receiver)
    if not rows:
        raise BeliefBehavioralEvaluationError(
            "behavioral receiver is outside ownership population")
    numerator = 0
    for row in rows:
        truth = counts[(row.card, receiver)]
        for index, probability in enumerate((
                row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)):
            target = PROBABILITY_SCALE if index == truth else 0
            numerator += (probability - target) ** 2
    return numerator, len(rows) * PROBABILITY_SCALE ** 2, len(rows) * 3


def _prediction_identity(
        predictions: tuple[BehavioralDecisionPredictionsV1, ...]) \
        -> tuple[str, str, tuple[str, ...]]:
    identities = set()
    for row in predictions:
        if type(row) is not BehavioralDecisionPredictionsV1 \
                or type(row.candidate) is not BeliefOwnershipV1 \
                or type(row.history_ablated) is not BeliefOwnershipV1:
            raise BeliefBehavioralEvaluationError(
                "behavioral prediction population drift")
        candidate = row.candidate
        ablated = row.history_ablated
        if (candidate.model_schema, candidate.model_sha256,
                candidate.behavior_policy_ids) != (
                ablated.model_schema, ablated.model_sha256,
                ablated.behavior_policy_ids):
            raise BeliefBehavioralEvaluationError(
                "history ablation model identity drift")
        identities.add((candidate.model_schema, candidate.model_sha256,
                        candidate.behavior_policy_ids))
    if len(identities) != 1:
        raise BeliefBehavioralEvaluationError(
            "behavioral candidate identity drift")
    return next(iter(identities))


def build_behavioral_round_score(
        reference_round: ReferenceCapturedRoundV1,
        captured: CapturedBeliefRoundV1,
        signals: BehavioralSignalRoundV1,
        predictions: tuple[BehavioralDecisionPredictionsV1, ...]) \
        -> BehavioralRoundScoreV1:
    validate_reference_captured_round(reference_round)
    validate_captured_round(captured)
    if reference_round.captured.round_seed != captured.round_seed \
            or reference_round.captured.policy_seeds != captured.policy_seeds \
            or reference_round.captured.public_transcript \
            != captured.public_transcript \
            or reference_round.captured.actor_rows \
            != tuple(pair.actor_bytes for pair in captured.pairs):
        raise BeliefBehavioralEvaluationError(
            "behavioral reference/capture binding drift")
    validate_behavioral_signal_round(captured, signals)
    if type(predictions) is not tuple \
            or len(predictions) != len(captured.pairs):
        raise BeliefBehavioralEvaluationError(
            "behavioral prediction count drift")
    model_schema, model_sha, policies = _prediction_identity(predictions)
    exposures = behavioral_signal_exposures(captured, signals)
    by_decision: dict[str, list[Any]] = {}
    for exposure in exposures:
        by_decision.setdefault(exposure.decision_key, []).append(exposure)
    public_keys = {name: set() for name in BEHAVIORAL_STRATA}
    confirmed_keys = {name: set() for name in BEHAVIORAL_STRATA}
    # cells, raw denominator, raw reference, correction numerator,
    # corrected denominator, corrected reference/candidate/ablation.
    totals = {name: [0, 0, 0, 0, 0, 0, 0, 0]
              for name in BEHAVIORAL_STRATA}
    for pair, batch, prediction in zip(
            captured.pairs, reference_round.batches, predictions,
            strict=True):
        actor, target, metadata = reopen_score_pair(pair)
        reference = batch.ownership()
        try:
            validate_ownership(actor, prediction.candidate)
            validate_ownership(actor, prediction.history_ablated)
        except ValueError as exc:
            raise BeliefBehavioralEvaluationError(
                "behavioral ownership prediction refused") from exc
        if batch.actor.canonical_bytes() != actor.canonical_bytes() \
                or reference.behavior_policy_ids != policies \
                or prediction.candidate.actor_observation_sha256 \
                != actor.sha256() \
                or prediction.history_ablated.actor_observation_sha256 \
                != actor.sha256():
            raise BeliefBehavioralEvaluationError(
                "behavioral actor/policy binding drift")
        counts = target_count_population(actor, target)
        for exposure in by_decision.get(metadata["decision_key"], ()):
            names = (POOLED_STRATUM, exposure.signal_kind)
            for name in names:
                key = (metadata["decision_key"], exposure.receiver)
                public_keys[name].add(key)
                if not exposure.privileged_signal_confirmed \
                        or key in confirmed_keys[name]:
                    continue
                confirmed_keys[name].add(key)
                values = []
                denominator = None
                cells = None
                for belief in (reference, prediction.candidate,
                               prediction.history_ablated):
                    numerator, current_denominator, current_cells = (
                        _subset_brier(belief, counts, exposure.receiver))
                    if denominator is None:
                        denominator = current_denominator
                        cells = current_cells
                    elif (current_denominator, current_cells) != (
                            denominator, cells):
                        raise BeliefBehavioralEvaluationError(
                            "behavioral Brier population drift")
                    values.append(numerator)
                row = totals[name]
                bias = sum(
                    probability * (PROBABILITY_SCALE - probability)
                    for probability_row in reference.probabilities
                    if probability_row.receiver == exposure.receiver
                    for probability in (
                        probability_row.count_0_ppb,
                        probability_row.count_1_ppb,
                        probability_row.count_2_ppb))
                multiplier = REF_C_WORLD_COUNT - 1
                row[0] += cells
                row[1] += denominator
                row[2] += values[0]
                row[3] += bias
                row[4] += denominator * multiplier
                row[5] += values[0] * multiplier - bias
                row[6] += values[1] * multiplier
                row[7] += values[2] * multiplier
    strata = tuple(BehavioralRoundStratumScoreV1(
        stratum=name,
        public_receiver_decision_count=len(public_keys[name]),
        confirmed_receiver_decision_count=len(confirmed_keys[name]),
        probability_cell_count=totals[name][0],
        raw_brier_denominator=totals[name][1],
        reference_raw_brier_numerator=totals[name][2],
        reference_finite_sample_bias_numerator=totals[name][3],
        brier_denominator=totals[name][4],
        reference_brier_numerator=totals[name][5],
        candidate_brier_numerator=totals[name][6],
        history_ablated_brier_numerator=totals[name][7],
    ) for name in BEHAVIORAL_STRATA)
    result = BehavioralRoundScoreV1(
        round_seed=captured.round_seed,
        reference_round_manifest_sha256=reference_round.manifest_sha256(),
        public_signal_stream_sha256=hashlib.sha256(
            signals.public_bytes()).hexdigest(),
        privileged_signal_stream_sha256=hashlib.sha256(
            signals.privileged_bytes()).hexdigest(),
        candidate_model_schema=model_schema,
        candidate_model_sha256=model_sha, strata=strata)
    validate_behavioral_round_score(result)
    return result


def validate_behavioral_round_score(result: BehavioralRoundScoreV1) -> None:
    if type(result) is not BehavioralRoundScoreV1 \
            or result.schema != BEHAVIORAL_ROUND_SCHEMA \
            or type(result.round_seed) is not int \
            or type(result.candidate_model_schema) is not str \
            or not result.candidate_model_schema \
            or not all(_is_sha256(value) for value in (
                    result.reference_round_manifest_sha256,
                    result.public_signal_stream_sha256,
                    result.privileged_signal_stream_sha256,
                    result.candidate_model_sha256)) \
            or type(result.strata) is not tuple \
            or tuple(row.stratum for row in result.strata) \
            != BEHAVIORAL_STRATA:
        raise BeliefBehavioralEvaluationError(
            "behavioral round score schema/identity drift")
    for row in result.strata:
        nonnegative = (
            row.public_receiver_decision_count,
            row.confirmed_receiver_decision_count,
            row.probability_cell_count, row.raw_brier_denominator,
            row.reference_raw_brier_numerator,
            row.reference_finite_sample_bias_numerator,
            row.brier_denominator,
            row.candidate_brier_numerator,
            row.history_ablated_brier_numerator)
        if type(row) is not BehavioralRoundStratumScoreV1 \
                or row.schema != BEHAVIORAL_STRATUM_SCORE_SCHEMA \
                or type(row.reference_brier_numerator) is not int \
                or any(type(value) is not int or value < 0
                       for value in nonnegative) \
                or row.confirmed_receiver_decision_count \
                > row.public_receiver_decision_count \
                or (row.confirmed_receiver_decision_count == 0) \
                != (row.brier_denominator == 0) \
                or row.probability_cell_count % 3 \
                or row.raw_brier_denominator != (
                    row.probability_cell_count // 3
                    * PROBABILITY_SCALE ** 2) \
                or row.brier_denominator != (
                    row.raw_brier_denominator
                    * (REF_C_WORLD_COUNT - 1)) \
                or row.reference_brier_numerator != (
                    row.reference_raw_brier_numerator
                    * (REF_C_WORLD_COUNT - 1)
                    - row.reference_finite_sample_bias_numerator) \
                or max(row.reference_brier_numerator,
                       row.candidate_brier_numerator,
                       row.history_ablated_brier_numerator) \
                > 2 * row.brier_denominator \
                or (row.brier_denominator == 0
                    and (row.reference_brier_numerator != 0
                         or any(nonnegative[2:]))):
            raise BeliefBehavioralEvaluationError(
                "behavioral round score value drift")


def _score_ppb(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefBehavioralEvaluationError(
            "behavioral score denominator is empty")
    sign = -1 if numerator < 0 else 1
    return sign * ((2 * abs(numerator) * PPB + denominator)
                   // (2 * denominator))


def _bootstrap_seed(stratum: str) -> int:
    return int.from_bytes(hashlib.sha256(
        f"{protocol_sha256()}|c2-bootstrap|{stratum}".encode(
            "ascii")).digest()[:8], "big") & (2**63 - 1)


def evaluate_c2(
        rounds: tuple[BehavioralRoundScoreV1, ...]) -> C2BehavioralResultV1:
    if type(rounds) is not tuple \
            or any(type(row) is not BehavioralRoundScoreV1 for row in rounds) \
            or tuple(row.round_seed for row in rounds) \
            != b2_split_round_seeds("test"):
        raise BeliefBehavioralEvaluationError(
            "behavioral test round population/order drift")
    for row in rounds:
        validate_behavioral_round_score(row)
    identities = {(row.candidate_model_schema, row.candidate_model_sha256)
                  for row in rounds}
    if len(identities) != 1:
        raise BeliefBehavioralEvaluationError(
            "behavioral test model identity drift")
    results = []
    for index, name in enumerate(BEHAVIORAL_STRATA):
        scored = tuple(row.strata[index] for row in rounds
                       if row.strata[index].brier_denominator > 0)
        exposures = sum(
            round_score.strata[index].confirmed_receiver_decision_count
            for round_score in rounds)
        if scored:
            candidate_differences = tuple(
                _score_ppb(row.reference_brier_numerator,
                           row.brier_denominator)
                - _score_ppb(row.candidate_brier_numerator,
                             row.brier_denominator)
                for row in scored)
            history_differences = tuple(
                _score_ppb(row.reference_brier_numerator,
                           row.brier_denominator)
                - _score_ppb(row.history_ablated_brier_numerator,
                             row.brier_denominator)
                for row in scored)
            candidate_mean = sum(candidate_differences) // len(scored)
            history_mean = sum(history_differences) // len(scored)
            generator = random.Random(_bootstrap_seed(name))
            bootstrap = sorted(sum(
                candidate_differences[generator.randrange(len(scored))]
                for _ in range(len(scored)))
                for _ in range(PRIMARY_BOOTSTRAP_REPLICATES))
            lower = bootstrap[
                math.ceil(0.05 * PRIMARY_BOOTSTRAP_REPLICATES) - 1] \
                // len(scored)
            retained = (history_mean * PPB // candidate_mean
                        if candidate_mean > 0 else PPB)
        else:
            candidate_mean = history_mean = lower = 0
            retained = PPB
        underpowered = exposures < MIN_BEHAVIORAL_EXPOSURES
        supported = not underpowered and lower > 0
        collapsed = (candidate_mean > 0
                     and history_mean * PPB
                     <= candidate_mean * HISTORY_ABLATION_RETAIN_CAP_PPB)
        results.append(BehavioralStratumResultV1(
            stratum=name, eligible_round_count=len(scored),
            confirmed_receiver_decision_count=exposures,
            candidate_mean_brier_improvement_ppb=candidate_mean,
            candidate_bootstrap_lower_improvement_ppb=lower,
            history_ablated_mean_brier_improvement_ppb=history_mean,
            history_retained_fraction_ppb=retained,
            underpowered=underpowered,
            candidate_lift_supported=supported,
            history_ablation_collapsed=collapsed))
    pooled = results[0]
    return C2BehavioralResultV1(
        strata=tuple(results),
        pooled_behavioral_claim_passed=(
            pooled.candidate_lift_supported
            and pooled.history_ablation_collapsed))
