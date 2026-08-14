"""Exact primary offline statistics for the BELIEF-V1 B2 decision.

Inputs are already-recomputed, equal-weight per-round proper scores for the
untouched test split.  The round—not a decision—is the uncertainty unit.  The
module applies the frozen mean-relative Brier floor, deterministic paired
round bootstrap, all-eight member sign check, and confirmatory log-loss sign.
It has no corpus reader, target, model, RNG outside the frozen bootstrap,
filesystem, gameplay, strength, or execution surface.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (
    PRIMARY_BOOTSTRAP_REPLICATES,
    PRIMARY_MEMBER_POSITIVE_MINIMUM,
    PRIMARY_RELATIVE_BRIER_FLOOR_PPB,
    REFERENCE_RELATIVE_DISAGREEMENT_CAP_PPB,
    b2_split_round_seeds,
    primary_bootstrap_seed,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_corpus import split_for_round_seed


ROUND_METRIC_SCHEMA = "belief-v1-b2-round-proper-score-v1"
C1_RESULT_SCHEMA = "belief-v1-b2-primary-calibration-result-v1"
N2_RESULT_SCHEMA = "belief-v1-b2-permuted-label-control-result-v1"
PPB = 1_000_000_000


class BeliefB2StatisticsError(ValueError):
    """The B2 proper-score population or frozen statistic drifted."""


def _round_divide(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or numerator < 0 or denominator <= 0:
        raise BeliefB2StatisticsError("statistic ratio input is invalid")
    return (2 * numerator + denominator) // (2 * denominator)


@dataclass(frozen=True)
class RoundProperScoreV1:
    round_seed: int
    decision_count: int
    reference_brier_ppb: int
    candidate_brier_ppb: int
    member_brier_ppb: tuple[int, ...]
    reference_log_loss_nanonats: int
    candidate_log_loss_nanonats: int
    schema: str = ROUND_METRIC_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "split": split_for_round_seed(self.round_seed),
            "decision_count": self.decision_count,
            "reference_brier_ppb": self.reference_brier_ppb,
            "candidate_brier_ppb": self.candidate_brier_ppb,
            "member_brier_ppb": list(self.member_brier_ppb),
            "reference_log_loss_nanonats": (
                self.reference_log_loss_nanonats),
            "candidate_log_loss_nanonats": (
                self.candidate_log_loss_nanonats),
        }


@dataclass(frozen=True)
class C1CalibrationResultV1:
    round_count: int
    reference_mean_brier_ppb: int
    candidate_mean_brier_ppb: int
    mean_brier_improvement_ppb: int
    relative_brier_improvement_ppb: int
    bootstrap_lower_brier_improvement_ppb: int
    member_mean_improvement_ppb: tuple[int, ...]
    positive_member_count: int
    mean_log_loss_improvement_nanonats: int
    passed: bool
    refusal_reasons: tuple[str, ...]
    schema: str = C1_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_count": self.round_count,
            "reference_mean_brier_ppb": self.reference_mean_brier_ppb,
            "candidate_mean_brier_ppb": self.candidate_mean_brier_ppb,
            "mean_brier_improvement_ppb": self.mean_brier_improvement_ppb,
            "relative_brier_improvement_ppb": (
                self.relative_brier_improvement_ppb),
            "bootstrap": {
                "unit": "complete-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "seed": primary_bootstrap_seed(),
                "one_sided_percentile": 5,
                "lower_brier_improvement_ppb": (
                    self.bootstrap_lower_brier_improvement_ppb),
            },
            "member_initialization_seeds": list(COHORT_SEEDS),
            "member_mean_improvement_ppb": list(
                self.member_mean_improvement_ppb),
            "positive_member_count": self.positive_member_count,
            "mean_log_loss_improvement_nanonats": (
                self.mean_log_loss_improvement_nanonats),
            "passed": self.passed,
            "refusal_reasons": list(self.refusal_reasons),
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


@dataclass(frozen=True)
class N2PermutedLabelResultV1:
    round_count: int
    mean_brier_improvement_ppb: int
    bootstrap_lower_brier_improvement_ppb: int
    unexpectedly_positive_lower_bound: bool
    passed: bool
    schema: str = N2_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "control": "hard-geometry-compatible-card-label-permutation-v1",
            "round_count": self.round_count,
            "mean_brier_improvement_ppb": self.mean_brier_improvement_ppb,
            "bootstrap": {
                "unit": "complete-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "seed": _n2_bootstrap_seed(),
                "one_sided_percentile": 5,
                "lower_brier_improvement_ppb": (
                    self.bootstrap_lower_brier_improvement_ppb),
            },
            "unexpectedly_positive_lower_bound": (
                self.unexpectedly_positive_lower_bound),
            "passed": self.passed,
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


def _validate_rounds(rounds: tuple[RoundProperScoreV1, ...], *, split: str) \
        -> None:
    if type(rounds) is not tuple or not rounds \
            or any(type(row) is not RoundProperScoreV1 for row in rounds):
        raise BeliefB2StatisticsError("round score population is malformed")
    seeds = tuple(row.round_seed for row in rounds)
    if seeds != b2_split_round_seeds(split):
        raise BeliefB2StatisticsError("round score split/order drift")
    for row in rounds:
        values = (
            row.reference_brier_ppb, row.candidate_brier_ppb,
            *row.member_brier_ppb, row.reference_log_loss_nanonats,
            row.candidate_log_loss_nanonats,
        )
        if row.schema != ROUND_METRIC_SCHEMA \
                or type(row.decision_count) is not int \
                or not 1 <= row.decision_count <= 128 \
                or type(row.member_brier_ppb) is not tuple \
                or len(row.member_brier_ppb) != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0 for value in values):
            raise BeliefB2StatisticsError("round score schema/value drift")


def reference_replicates_are_stable(
        left: tuple[RoundProperScoreV1, ...],
        right: tuple[RoundProperScoreV1, ...]) -> bool:
    """Apply the frozen calibration-only REF-C disagreement ceiling."""
    _validate_rounds(left, split="calibration")
    _validate_rounds(right, split="calibration")
    if tuple(row.round_seed for row in left) != tuple(
            row.round_seed for row in right):
        raise BeliefB2StatisticsError("reference replicate round drift")
    left_sum = sum(row.reference_brier_ppb for row in left)
    right_sum = sum(row.reference_brier_ppb for row in right)
    if left_sum + right_sum <= 0:
        raise BeliefB2StatisticsError("reference replicate Brier is empty")
    return (2 * abs(left_sum - right_sum) * PPB
            < REFERENCE_RELATIVE_DISAGREEMENT_CAP_PPB
            * (left_sum + right_sum))


def _n2_bootstrap_seed() -> int:
    return int.from_bytes(hashlib.sha256(
        b"belief-v1-b2|n2-permuted-label|paired-round-bootstrap").digest()[:8],
                          "big") & (2**63 - 1)


def evaluate_c1(
        rounds: tuple[RoundProperScoreV1, ...]) -> C1CalibrationResultV1:
    """Recompute the complete frozen primary B2 calibration decision."""
    _validate_rounds(rounds, split="test")
    count = len(rounds)
    reference_sum = sum(row.reference_brier_ppb for row in rounds)
    candidate_sum = sum(row.candidate_brier_ppb for row in rounds)
    if reference_sum <= 0:
        raise BeliefB2StatisticsError("test reference Brier is empty")
    differences = tuple(row.reference_brier_ppb - row.candidate_brier_ppb
                        for row in rounds)
    difference_sum = sum(differences)
    reference_mean = _round_divide(reference_sum, count)
    candidate_mean = _round_divide(candidate_sum, count)
    mean_improvement = difference_sum // count
    relative_improvement = difference_sum * PPB // reference_sum

    generator = random.Random(primary_bootstrap_seed())
    bootstrap_sums = [sum(differences[generator.randrange(count)]
                          for _ in range(count))
                      for _ in range(PRIMARY_BOOTSTRAP_REPLICATES)]
    bootstrap_sums.sort()
    lower_sum = bootstrap_sums[
        math.ceil(0.05 * PRIMARY_BOOTSTRAP_REPLICATES) - 1]
    lower = lower_sum // count
    member_improvements = tuple(
        sum(row.reference_brier_ppb - row.member_brier_ppb[index]
            for row in rounds) // count
        for index in range(len(COHORT_SEEDS)))
    positive_members = sum(value > 0 for value in member_improvements)
    log_improvement = sum(
        row.reference_log_loss_nanonats
        - row.candidate_log_loss_nanonats for row in rounds) // count
    reasons = []
    if relative_improvement < PRIMARY_RELATIVE_BRIER_FLOOR_PPB:
        reasons.append("mean-relative-brier-floor-not-met")
    if lower_sum <= 0:
        reasons.append("paired-round-bootstrap-lower-bound-not-positive")
    if positive_members < PRIMARY_MEMBER_POSITIVE_MINIMUM:
        reasons.append("individual-member-sign-count-not-met")
    if log_improvement < 0:
        reasons.append("smoothed-log-loss-materially-reversed")
    return C1CalibrationResultV1(
        round_count=count,
        reference_mean_brier_ppb=reference_mean,
        candidate_mean_brier_ppb=candidate_mean,
        mean_brier_improvement_ppb=mean_improvement,
        relative_brier_improvement_ppb=relative_improvement,
        bootstrap_lower_brier_improvement_ppb=lower,
        member_mean_improvement_ppb=member_improvements,
        positive_member_count=positive_members,
        mean_log_loss_improvement_nanonats=log_improvement,
        passed=not reasons,
        refusal_reasons=tuple(reasons),
    )


def evaluate_n2(
        rounds: tuple[RoundProperScoreV1, ...]) -> N2PermutedLabelResultV1:
    """Require the trainable permuted-label cohort to lack positive lift."""
    _validate_rounds(rounds, split="test")
    differences = tuple(row.reference_brier_ppb - row.candidate_brier_ppb
                        for row in rounds)
    count = len(differences)
    mean = sum(differences) // count
    generator = random.Random(_n2_bootstrap_seed())
    bootstrap = sorted(sum(
        differences[generator.randrange(count)] for _ in range(count))
        for _ in range(PRIMARY_BOOTSTRAP_REPLICATES))
    lower = bootstrap[
        math.ceil(0.05 * PRIMARY_BOOTSTRAP_REPLICATES) - 1] // count
    unexpectedly_positive = lower > 0
    return N2PermutedLabelResultV1(
        round_count=count,
        mean_brier_improvement_ppb=mean,
        bootstrap_lower_brier_improvement_ppb=lower,
        unexpectedly_positive_lower_bound=unexpectedly_positive,
        passed=not unexpectedly_positive)
