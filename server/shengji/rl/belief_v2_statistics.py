"""Exact calibration selection and scale statistics for BELIEF-V1 V2.

Every input is an already-recomputed equal-weight per-round score.  The round
is the uncertainty unit.  Human-mixture selection requires a positive human
calibration lower bound and simultaneous aggregate plus all-rank non-regression
against the synthetic primary.  Data-scale arms are reported separately.

This module has no target reader, model, RNG outside the frozen bootstrap,
filesystem, test opener, sampler, gameplay, or execution authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from .belief_b2_protocol import (
    PRIMARY_BOOTSTRAP_REPLICATES,
    PRIMARY_MEMBER_POSITIVE_MINIMUM,
    PRIMARY_RELATIVE_BRIER_FLOOR_PPB,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_freeze import (
    CONTROL_COHORT_ID,
    HUMAN_COHORT_ID,
    PRIMARY_COHORT_ID,
    RANK_CALIBRATION_MINIMUM_ROUNDS,
    RANK_MATERIAL_REGRESSION_TOLERANCE_PPB,
    RANK_MULTIPLICITY_RULE,
)
from .belief_v2_protocol import V2_RANKS


ROUND_SCORE_SCHEMA = "belief-v1-v2-round-score-v1"
HUMAN_SELECTION_SCHEMA = "belief-v1-v2-human-selection-result-v1"
SCALE_CURVE_SCHEMA = "belief-v1-v2-scale-curve-result-v1"
PRIMARY_TEST_SCHEMA = "belief-v1-v2-primary-test-result-v1"
CONTROL_TEST_SCHEMA = "belief-v1-v2-label-control-test-result-v1"
HUMAN_TRANSFER_SCHEMA = "belief-v1-v2-human-transfer-result-v1"
PPB = 1_000_000_000
BOOTSTRAP_CHUNK = 256


class BeliefV2StatisticsError(ValueError):
    """A V2 score population, bootstrap, or frozen gate drifted."""


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _round_divide(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefV2StatisticsError("V2 statistic ratio input drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((2 * abs(numerator) + denominator)
                   // (2 * denominator))


def _bootstrap_seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefV2StatisticsError("V2 bootstrap label drift")
    return int.from_bytes(hashlib.sha256(
        f"belief-v1-v2-bootstrap-v1|{label}".encode("ascii")).digest()[:8],
                          "big") & (2**63 - 1)


def _percentile_bootstrap_mean(
        differences: tuple[int, ...], *, label: str,
        percentile: int) -> int:
    if type(differences) is not tuple or not differences \
            or any(type(value) is not int for value in differences) \
            or percentile not in (5, 95):
        raise BeliefV2StatisticsError("V2 bootstrap input drift")
    values = np.asarray(differences, dtype=np.int64)
    generator = np.random.Generator(np.random.PCG64(_bootstrap_seed(label)))
    sums = np.empty(PRIMARY_BOOTSTRAP_REPLICATES, dtype=np.int64)
    count = len(values)
    for start in range(0, PRIMARY_BOOTSTRAP_REPLICATES, BOOTSTRAP_CHUNK):
        size = min(BOOTSTRAP_CHUNK,
                   PRIMARY_BOOTSTRAP_REPLICATES - start)
        indices = generator.integers(
            0, count, size=(size, count), dtype=np.int64)
        sums[start:start + size] = values[indices].sum(axis=1)
    sums.sort()
    position = ((percentile * PRIMARY_BOOTSTRAP_REPLICATES + 99) // 100 - 1)
    return _round_divide(int(sums[position]), count)


def _rounded_mean_vector(sums: np.ndarray, count: int) -> np.ndarray:
    """Round signed int64 sums to nearest integer without float conversion."""
    if not isinstance(sums, np.ndarray) or sums.dtype != np.int64 \
            or type(count) is not int or count <= 0:
        raise BeliefV2StatisticsError("V2 bootstrap mean vector drift")
    magnitude = (2 * np.abs(sums) + count) // (2 * count)
    return np.where(sums < 0, -magnitude, magnitude).astype(np.int64)


@dataclass(frozen=True)
class V2RoundScoreV1:
    round_key: str
    source_kind: str
    split: str
    trump_rank: str
    decision_count: int
    reference_brier_ppb: int
    reference_log_loss_nanonats: int
    cohort_brier_ppb: tuple[tuple[str, int], ...]
    cohort_log_loss_nanonats: tuple[tuple[str, int], ...]
    cohort_member_brier_ppb: tuple[tuple[str, tuple[int, ...]], ...]
    schema: str = ROUND_SCORE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_key": self.round_key,
            "source_kind": self.source_kind,
            "split": self.split,
            "trump_rank": self.trump_rank,
            "decision_count": self.decision_count,
            "reference_brier_ppb": self.reference_brier_ppb,
            "reference_log_loss_nanonats": (
                self.reference_log_loss_nanonats),
            "cohorts": [{
                "cohort_id": cohort_id,
                "brier_ppb": dict(self.cohort_brier_ppb)[cohort_id],
                "log_loss_nanonats": dict(
                    self.cohort_log_loss_nanonats)[cohort_id],
                "member_brier_ppb": list(dict(
                    self.cohort_member_brier_ppb)[cohort_id]),
            } for cohort_id, _ in self.cohort_brier_ppb],
        }


def _validate_round_score(
        row: V2RoundScoreV1, *, cohort_ids: tuple[str, ...]) -> None:
    if type(row) is not V2RoundScoreV1 or row.schema != ROUND_SCORE_SCHEMA \
            or not _is_sha256(row.round_key) \
            or row.source_kind not in {"synthetic", "human"} \
            or row.split not in {"calibration", "test"} \
            or row.trump_rank not in V2_RANKS \
            or type(row.decision_count) is not int \
            or not 1 <= row.decision_count <= 128 \
            or type(row.reference_brier_ppb) is not int \
            or row.reference_brier_ppb < 0 \
            or type(row.reference_log_loss_nanonats) is not int \
            or row.reference_log_loss_nanonats < 0 \
            or type(row.cohort_brier_ppb) is not tuple \
            or tuple(key for key, _ in row.cohort_brier_ppb) != cohort_ids \
            or type(row.cohort_log_loss_nanonats) is not tuple \
            or tuple(key for key, _ in row.cohort_log_loss_nanonats) \
            != cohort_ids \
            or type(row.cohort_member_brier_ppb) is not tuple \
            or tuple(key for key, _ in row.cohort_member_brier_ppb) \
            != cohort_ids \
            or any(type(value) is not int or value < 0
                   for _, value in (*row.cohort_brier_ppb,
                                    *row.cohort_log_loss_nanonats)) \
            or any(type(values) is not tuple
                   or len(values) != len(COHORT_SEEDS)
                   or any(type(value) is not int or value < 0
                          for value in values)
                   for _, values in row.cohort_member_brier_ppb):
        raise BeliefV2StatisticsError("V2 round score schema/value drift")


def validate_round_population(
        rows: tuple[V2RoundScoreV1, ...], *,
        source_kind: str, split: str,
        expected_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...]) -> None:
    if type(rows) is not tuple or not rows \
            or type(expected_rounds) is not tuple \
            or len(rows) != len(expected_rounds) \
            or type(cohort_ids) is not tuple or not cohort_ids \
            or len(set(cohort_ids)) != len(cohort_ids):
        raise BeliefV2StatisticsError("V2 round score population drift")
    for row in rows:
        _validate_round_score(row, cohort_ids=cohort_ids)
    if tuple((row.round_key, row.trump_rank) for row in rows) \
            != expected_rounds \
            or any(row.source_kind != source_kind or row.split != split
                   for row in rows) \
            or len({row.round_key for row in rows}) != len(rows):
        raise BeliefV2StatisticsError("V2 round score identity/order drift")


def _cohort_values(
        rows: tuple[V2RoundScoreV1, ...], cohort_id: str,
        field: str = "cohort_brier_ppb") -> tuple[int, ...]:
    return tuple(dict(getattr(row, field))[cohort_id] for row in rows)


def _max_stat_rank_upper_bounds(
        rows: tuple[V2RoundScoreV1, ...], *,
        treatment_id: str, comparator_id: str,
        label: str) -> tuple[tuple[str, int], ...]:
    grouped = {
        rank: tuple(
            dict(row.cohort_brier_ppb)[treatment_id]
            - dict(row.cohort_brier_ppb)[comparator_id]
            for row in rows if row.trump_rank == rank)
        for rank in V2_RANKS
    }
    if any(len(values) < RANK_CALIBRATION_MINIMUM_ROUNDS
           for values in grouped.values()):
        raise BeliefV2StatisticsError(
            "V2 rank calibration population is underpowered")
    observed = {
        rank: _round_divide(sum(values), len(values))
        for rank, values in grouped.items()
    }
    generator = np.random.Generator(np.random.PCG64(_bootstrap_seed(label)))
    maxima = np.empty(PRIMARY_BOOTSTRAP_REPLICATES, dtype=np.int64)
    arrays = {rank: np.asarray(values, dtype=np.int64)
              for rank, values in grouped.items()}
    for start in range(0, PRIMARY_BOOTSTRAP_REPLICATES, BOOTSTRAP_CHUNK):
        size = min(BOOTSTRAP_CHUNK,
                   PRIMARY_BOOTSTRAP_REPLICATES - start)
        deviations = []
        for rank in V2_RANKS:
            values = arrays[rank]
            indices = generator.integers(
                0, len(values), size=(size, len(values)), dtype=np.int64)
            means = _rounded_mean_vector(
                values[indices].sum(axis=1), len(values))
            deviations.append(means - observed[rank])
        maxima[start:start + size] = np.stack(deviations, axis=1).max(axis=1)
    maxima.sort()
    critical = int(maxima[
        (95 * PRIMARY_BOOTSTRAP_REPLICATES + 99) // 100 - 1])
    return tuple((rank, observed[rank] + critical) for rank in V2_RANKS)


@dataclass(frozen=True)
class V2HumanSelectionResultV1:
    synthetic_round_count: int
    human_round_count: int
    human_mean_brier_improvement_ppb: int
    human_bootstrap_lower_improvement_ppb: int
    synthetic_mean_regression_ppb: int
    synthetic_bootstrap_upper_regression_ppb: int
    rank_round_counts: tuple[tuple[str, int], ...]
    rank_mean_regression_ppb: tuple[tuple[str, int], ...]
    rank_familywise_upper_regression_ppb: tuple[tuple[str, int], ...]
    retained: bool
    refusal_reasons: tuple[str, ...]
    schema: str = HUMAN_SELECTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_cohort_id": HUMAN_COHORT_ID,
            "comparator_cohort_id": PRIMARY_COHORT_ID,
            "synthetic_round_count": self.synthetic_round_count,
            "human_round_count": self.human_round_count,
            "human_mean_brier_improvement_ppb": (
                self.human_mean_brier_improvement_ppb),
            "human_bootstrap": {
                "unit": "complete-human-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "seed": _bootstrap_seed("human-mixture-human-lower"),
                "one_sided_percentile": 5,
                "lower_improvement_ppb": (
                    self.human_bootstrap_lower_improvement_ppb),
            },
            "synthetic_mean_regression_ppb": (
                self.synthetic_mean_regression_ppb),
            "synthetic_bootstrap": {
                "unit": "complete-synthetic-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "seed": _bootstrap_seed("human-mixture-synthetic-upper"),
                "one_sided_percentile": 95,
                "upper_regression_ppb": (
                    self.synthetic_bootstrap_upper_regression_ppb),
            },
            "rank_round_counts": dict(self.rank_round_counts),
            "rank_mean_regression_ppb": dict(
                self.rank_mean_regression_ppb),
            "rank_familywise_upper_regression_ppb": dict(
                self.rank_familywise_upper_regression_ppb),
            "rank_multiplicity_rule": RANK_MULTIPLICITY_RULE,
            "material_regression_tolerance_ppb": (
                RANK_MATERIAL_REGRESSION_TOLERANCE_PPB),
            "retained": self.retained,
            "refusal_reasons": list(self.refusal_reasons),
            "privileged_targets_consumed": True,
            "test_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_human_mixture_selection(
        synthetic_rows: tuple[V2RoundScoreV1, ...],
        human_rows: tuple[V2RoundScoreV1, ...], *,
        expected_synthetic_rounds: tuple[tuple[str, str], ...],
        expected_human_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...]) -> V2HumanSelectionResultV1:
    """Apply the sole calibration-only human-mixture retention rule."""
    if PRIMARY_COHORT_ID not in cohort_ids or HUMAN_COHORT_ID not in cohort_ids:
        raise BeliefV2StatisticsError("V2 human selection cohort drift")
    validate_round_population(
        synthetic_rows, source_kind="synthetic", split="calibration",
        expected_rounds=expected_synthetic_rounds, cohort_ids=cohort_ids)
    validate_round_population(
        human_rows, source_kind="human", split="calibration",
        expected_rounds=expected_human_rounds, cohort_ids=cohort_ids)
    human_differences = tuple(
        primary - mixed for primary, mixed in zip(
            _cohort_values(human_rows, PRIMARY_COHORT_ID),
            _cohort_values(human_rows, HUMAN_COHORT_ID), strict=True))
    synthetic_regressions = tuple(
        mixed - primary for primary, mixed in zip(
            _cohort_values(synthetic_rows, PRIMARY_COHORT_ID),
            _cohort_values(synthetic_rows, HUMAN_COHORT_ID), strict=True))
    human_mean = _round_divide(
        sum(human_differences), len(human_differences))
    human_lower = _percentile_bootstrap_mean(
        human_differences, label="human-mixture-human-lower", percentile=5)
    synthetic_mean = _round_divide(
        sum(synthetic_regressions), len(synthetic_regressions))
    synthetic_upper = _percentile_bootstrap_mean(
        synthetic_regressions,
        label="human-mixture-synthetic-upper", percentile=95)
    rank_counts = tuple((rank, sum(
        row.trump_rank == rank for row in synthetic_rows))
                        for rank in V2_RANKS)
    rank_means = tuple((rank, _round_divide(sum(
        dict(row.cohort_brier_ppb)[HUMAN_COHORT_ID]
        - dict(row.cohort_brier_ppb)[PRIMARY_COHORT_ID]
        for row in synthetic_rows if row.trump_rank == rank), count))
                       for rank, count in rank_counts)
    rank_upper = _max_stat_rank_upper_bounds(
        synthetic_rows, treatment_id=HUMAN_COHORT_ID,
        comparator_id=PRIMARY_COHORT_ID,
        label="human-mixture-rank-max-upper")
    primary_synthetic = _cohort_values(
        synthetic_rows, PRIMARY_COHORT_ID)
    aggregate_reference = sum(primary_synthetic)
    reasons = []
    if human_lower <= 0:
        reasons.append("human-domain-lower-bound-not-positive")
    if synthetic_upper * PPB \
            >= RANK_MATERIAL_REGRESSION_TOLERANCE_PPB \
            * _round_divide(aggregate_reference, len(primary_synthetic)):
        reasons.append("synthetic-aggregate-material-regression")
    primary_rank_mean = {
        rank: _round_divide(sum(
            dict(row.cohort_brier_ppb)[PRIMARY_COHORT_ID]
            for row in synthetic_rows if row.trump_rank == rank), count)
        for rank, count in rank_counts
    }
    if any(upper * PPB
           >= RANK_MATERIAL_REGRESSION_TOLERANCE_PPB
           * primary_rank_mean[rank] for rank, upper in rank_upper):
        reasons.append("synthetic-rank-familywise-material-regression")
    return V2HumanSelectionResultV1(
        synthetic_round_count=len(synthetic_rows),
        human_round_count=len(human_rows),
        human_mean_brier_improvement_ppb=human_mean,
        human_bootstrap_lower_improvement_ppb=human_lower,
        synthetic_mean_regression_ppb=synthetic_mean,
        synthetic_bootstrap_upper_regression_ppb=synthetic_upper,
        rank_round_counts=rank_counts,
        rank_mean_regression_ppb=rank_means,
        rank_familywise_upper_regression_ppb=rank_upper,
        retained=not reasons, refusal_reasons=tuple(reasons))


@dataclass(frozen=True)
class V2ScaleCurveRowV1:
    cohort_id: str
    decision_fraction_numerator: int
    decision_fraction_denominator: int
    primary_mean_improvement_ppb: int
    bootstrap_lower_improvement_ppb: int
    positive_lower_bound: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "decision_fraction": {
                "numerator": self.decision_fraction_numerator,
                "denominator": self.decision_fraction_denominator,
            },
            "primary_mean_improvement_ppb": (
                self.primary_mean_improvement_ppb),
            "bootstrap_lower_improvement_ppb": (
                self.bootstrap_lower_improvement_ppb),
            "positive_lower_bound": self.positive_lower_bound,
        }


@dataclass(frozen=True)
class V2ScaleCurveResultV1:
    synthetic_round_count: int
    rows: tuple[V2ScaleCurveRowV1, ...]
    any_positive_data_scaling_signal: bool
    schema: str = SCALE_CURVE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "synthetic_round_count": self.synthetic_round_count,
            "bootstrap_unit": "complete-synthetic-round",
            "bootstrap_replicates": PRIMARY_BOOTSTRAP_REPLICATES,
            "rows": [row.to_dict() for row in self.rows],
            "any_positive_data_scaling_signal": (
                self.any_positive_data_scaling_signal),
            "privileged_targets_consumed": True,
            "test_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_scale_curve(
        synthetic_rows: tuple[V2RoundScoreV1, ...], *,
        expected_synthetic_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...],
        scale_fractions: tuple[tuple[str, int, int], ...]) \
        -> V2ScaleCurveResultV1:
    if PRIMARY_COHORT_ID not in cohort_ids \
            or type(scale_fractions) is not tuple or not scale_fractions \
            or any(type(row) is not tuple or len(row) != 3
                   or row[0] not in cohort_ids or row[0] == PRIMARY_COHORT_ID
                   or type(row[1]) is not int or type(row[2]) is not int
                   or not 0 < row[1] < row[2]
                   for row in scale_fractions) \
            or len({row[0] for row in scale_fractions}) \
            != len(scale_fractions):
        raise BeliefV2StatisticsError("V2 scale curve identity drift")
    validate_round_population(
        synthetic_rows, source_kind="synthetic", split="calibration",
        expected_rounds=expected_synthetic_rounds, cohort_ids=cohort_ids)
    primary = _cohort_values(synthetic_rows, PRIMARY_COHORT_ID)
    results = []
    for cohort_id, numerator, denominator in scale_fractions:
        scale = _cohort_values(synthetic_rows, cohort_id)
        differences = tuple(left - right for left, right in zip(
            scale, primary, strict=True))
        mean = _round_divide(sum(differences), len(differences))
        lower = _percentile_bootstrap_mean(
            differences, label=f"scale-curve|{cohort_id}|lower",
            percentile=5)
        results.append(V2ScaleCurveRowV1(
            cohort_id=cohort_id,
            decision_fraction_numerator=numerator,
            decision_fraction_denominator=denominator,
            primary_mean_improvement_ppb=mean,
            bootstrap_lower_improvement_ppb=lower,
            positive_lower_bound=lower > 0))
    return V2ScaleCurveResultV1(
        synthetic_round_count=len(synthetic_rows), rows=tuple(results),
        any_positive_data_scaling_signal=any(
            row.positive_lower_bound for row in results))


@dataclass(frozen=True)
class V2PrimaryTestResultV1:
    selected_cohort_id: str
    round_count: int
    reference_mean_brier_ppb: int
    candidate_mean_brier_ppb: int
    mean_brier_improvement_ppb: int
    relative_brier_improvement_ppb: int
    bootstrap_lower_improvement_ppb: int
    member_mean_improvement_ppb: tuple[int, ...]
    positive_member_count: int
    mean_log_loss_improvement_nanonats: int
    rank_round_counts: tuple[tuple[str, int], ...]
    rank_mean_regression_ppb: tuple[tuple[str, int], ...]
    rank_familywise_upper_regression_ppb: tuple[tuple[str, int], ...]
    passed: bool
    refusal_reasons: tuple[str, ...]
    schema: str = PRIMARY_TEST_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "selected_cohort_id": self.selected_cohort_id,
            "round_count": self.round_count,
            "reference_mean_brier_ppb": self.reference_mean_brier_ppb,
            "candidate_mean_brier_ppb": self.candidate_mean_brier_ppb,
            "mean_brier_improvement_ppb": self.mean_brier_improvement_ppb,
            "relative_brier_improvement_ppb": (
                self.relative_brier_improvement_ppb),
            "bootstrap": {
                "unit": "complete-synthetic-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "seed": _bootstrap_seed(
                    f"primary-test|{self.selected_cohort_id}|lower"),
                "one_sided_percentile": 5,
                "lower_improvement_ppb": (
                    self.bootstrap_lower_improvement_ppb),
            },
            "member_initialization_seeds": list(COHORT_SEEDS),
            "member_mean_improvement_ppb": list(
                self.member_mean_improvement_ppb),
            "positive_member_count": self.positive_member_count,
            "mean_log_loss_improvement_nanonats": (
                self.mean_log_loss_improvement_nanonats),
            "rank_round_counts": dict(self.rank_round_counts),
            "rank_mean_regression_ppb": dict(
                self.rank_mean_regression_ppb),
            "rank_familywise_upper_regression_ppb": dict(
                self.rank_familywise_upper_regression_ppb),
            "rank_multiplicity_rule": RANK_MULTIPLICITY_RULE,
            "material_regression_tolerance_ppb": (
                RANK_MATERIAL_REGRESSION_TOLERANCE_PPB),
            "passed": self.passed,
            "refusal_reasons": list(self.refusal_reasons),
            "privileged_targets_consumed": True,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_primary_test(
        synthetic_rows: tuple[V2RoundScoreV1, ...], *,
        selected_cohort_id: str,
        expected_synthetic_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...]) -> V2PrimaryTestResultV1:
    """Evaluate the calibration-selected candidate on the sole test split."""
    if selected_cohort_id not in {PRIMARY_COHORT_ID, HUMAN_COHORT_ID} \
            or selected_cohort_id not in cohort_ids:
        raise BeliefV2StatisticsError("V2 primary selected cohort drift")
    validate_round_population(
        synthetic_rows, source_kind="synthetic", split="test",
        expected_rounds=expected_synthetic_rounds, cohort_ids=cohort_ids)
    candidate = _cohort_values(synthetic_rows, selected_cohort_id)
    reference = tuple(row.reference_brier_ppb for row in synthetic_rows)
    if sum(reference) <= 0:
        raise BeliefV2StatisticsError("V2 test reference Brier is empty")
    differences = tuple(left - right for left, right in zip(
        reference, candidate, strict=True))
    count = len(differences)
    difference_sum = sum(differences)
    reference_mean = _round_divide(sum(reference), count)
    candidate_mean = _round_divide(sum(candidate), count)
    mean_improvement = _round_divide(difference_sum, count)
    relative = difference_sum * PPB // sum(reference)
    lower = _percentile_bootstrap_mean(
        differences,
        label=f"primary-test|{selected_cohort_id}|lower", percentile=5)
    members = tuple(dict(
        row.cohort_member_brier_ppb)[selected_cohort_id]
                    for row in synthetic_rows)
    member_improvements = tuple(_round_divide(sum(
        row.reference_brier_ppb - member[index]
        for row, member in zip(synthetic_rows, members, strict=True)), count)
                                for index in range(len(COHORT_SEEDS)))
    positive_members = sum(value > 0 for value in member_improvements)
    candidate_log = _cohort_values(
        synthetic_rows, selected_cohort_id,
        field="cohort_log_loss_nanonats")
    log_improvement = _round_divide(sum(
        row.reference_log_loss_nanonats - value
        for row, value in zip(synthetic_rows, candidate_log, strict=True)),
        count)
    rank_counts = tuple((rank, sum(
        row.trump_rank == rank for row in synthetic_rows))
                        for rank in V2_RANKS)
    rank_means = tuple((rank, _round_divide(sum(
        dict(row.cohort_brier_ppb)[selected_cohort_id]
        - row.reference_brier_ppb
        for row in synthetic_rows if row.trump_rank == rank), rank_count))
                       for rank, rank_count in rank_counts)
    rank_upper = _max_stat_rank_upper_bounds_against_reference(
        synthetic_rows, treatment_id=selected_cohort_id,
        label=f"primary-test|{selected_cohort_id}|rank-max-upper")
    reference_rank_mean = {
        rank: _round_divide(sum(
            row.reference_brier_ppb for row in synthetic_rows
            if row.trump_rank == rank), rank_count)
        for rank, rank_count in rank_counts
    }
    reasons = []
    if relative < PRIMARY_RELATIVE_BRIER_FLOOR_PPB:
        reasons.append("mean-relative-brier-floor-not-met")
    if lower <= 0:
        reasons.append("paired-round-bootstrap-lower-bound-not-positive")
    if positive_members < PRIMARY_MEMBER_POSITIVE_MINIMUM:
        reasons.append("individual-member-sign-count-not-met")
    if log_improvement < 0:
        reasons.append("smoothed-log-loss-materially-reversed")
    if any(upper * PPB
           >= RANK_MATERIAL_REGRESSION_TOLERANCE_PPB
           * reference_rank_mean[rank] for rank, upper in rank_upper):
        reasons.append("rank-familywise-material-regression")
    return V2PrimaryTestResultV1(
        selected_cohort_id=selected_cohort_id, round_count=count,
        reference_mean_brier_ppb=reference_mean,
        candidate_mean_brier_ppb=candidate_mean,
        mean_brier_improvement_ppb=mean_improvement,
        relative_brier_improvement_ppb=relative,
        bootstrap_lower_improvement_ppb=lower,
        member_mean_improvement_ppb=member_improvements,
        positive_member_count=positive_members,
        mean_log_loss_improvement_nanonats=log_improvement,
        rank_round_counts=rank_counts,
        rank_mean_regression_ppb=rank_means,
        rank_familywise_upper_regression_ppb=rank_upper,
        passed=not reasons, refusal_reasons=tuple(reasons))


def _max_stat_rank_upper_bounds_against_reference(
        rows: tuple[V2RoundScoreV1, ...], *,
        treatment_id: str, label: str) -> tuple[tuple[str, int], ...]:
    """Apply the same max-statistic to candidate-minus-REF-C regressions."""
    proxy = tuple(V2RoundScoreV1(
        round_key=row.round_key, source_kind=row.source_kind,
        split=row.split, trump_rank=row.trump_rank,
        decision_count=row.decision_count,
        reference_brier_ppb=row.reference_brier_ppb,
        reference_log_loss_nanonats=row.reference_log_loss_nanonats,
        cohort_brier_ppb=(
            ("__reference__", row.reference_brier_ppb),
            (treatment_id, dict(row.cohort_brier_ppb)[treatment_id])),
        cohort_log_loss_nanonats=(
            ("__reference__", row.reference_log_loss_nanonats),
            (treatment_id,
             dict(row.cohort_log_loss_nanonats)[treatment_id])),
        cohort_member_brier_ppb=(
            ("__reference__", (row.reference_brier_ppb,) * len(COHORT_SEEDS)),
            (treatment_id,
             dict(row.cohort_member_brier_ppb)[treatment_id])),
    ) for row in rows)
    return _max_stat_rank_upper_bounds(
        proxy, treatment_id=treatment_id, comparator_id="__reference__",
        label=label)


@dataclass(frozen=True)
class V2LabelControlTestResultV1:
    round_count: int
    mean_brier_improvement_ppb: int
    bootstrap_lower_improvement_ppb: int
    unexpectedly_positive_lower_bound: bool
    passed: bool
    schema: str = CONTROL_TEST_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cohort_id": CONTROL_COHORT_ID,
            "round_count": self.round_count,
            "mean_brier_improvement_ppb": self.mean_brier_improvement_ppb,
            "bootstrap_lower_improvement_ppb": (
                self.bootstrap_lower_improvement_ppb),
            "unexpectedly_positive_lower_bound": (
                self.unexpectedly_positive_lower_bound),
            "passed": self.passed,
            "privileged_targets_consumed": True,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_label_control_test(
        synthetic_rows: tuple[V2RoundScoreV1, ...], *,
        expected_synthetic_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...]) -> V2LabelControlTestResultV1:
    if CONTROL_COHORT_ID not in cohort_ids:
        raise BeliefV2StatisticsError("V2 label control cohort drift")
    validate_round_population(
        synthetic_rows, source_kind="synthetic", split="test",
        expected_rounds=expected_synthetic_rounds, cohort_ids=cohort_ids)
    differences = tuple(
        row.reference_brier_ppb
        - dict(row.cohort_brier_ppb)[CONTROL_COHORT_ID]
        for row in synthetic_rows)
    mean = _round_divide(sum(differences), len(differences))
    lower = _percentile_bootstrap_mean(
        differences, label="label-control-test|lower", percentile=5)
    unexpected = lower > 0
    return V2LabelControlTestResultV1(
        round_count=len(differences),
        mean_brier_improvement_ppb=mean,
        bootstrap_lower_improvement_ppb=lower,
        unexpectedly_positive_lower_bound=unexpected,
        passed=not unexpected)


@dataclass(frozen=True)
class V2HumanTransferCohortV1:
    cohort_id: str
    reference_mean_brier_ppb: int
    candidate_mean_brier_ppb: int
    mean_brier_improvement_ppb: int
    bootstrap_lower_improvement_ppb: int
    bootstrap_upper_improvement_ppb: int
    mean_log_loss_improvement_nanonats: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "reference_mean_brier_ppb": self.reference_mean_brier_ppb,
            "candidate_mean_brier_ppb": self.candidate_mean_brier_ppb,
            "mean_brier_improvement_ppb": self.mean_brier_improvement_ppb,
            "bootstrap_lower_improvement_ppb": (
                self.bootstrap_lower_improvement_ppb),
            "bootstrap_upper_improvement_ppb": (
                self.bootstrap_upper_improvement_ppb),
            "mean_log_loss_improvement_nanonats": (
                self.mean_log_loss_improvement_nanonats),
        }


@dataclass(frozen=True)
class V2HumanTransferResultV1:
    round_count: int
    decision_count: int
    selected_cohort_id: str
    cohorts: tuple[V2HumanTransferCohortV1, ...]
    mixed_minus_primary_mean_improvement_ppb: int
    mixed_minus_primary_bootstrap_lower_ppb: int
    mixed_minus_primary_bootstrap_upper_ppb: int
    schema: str = HUMAN_TRANSFER_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_count": self.round_count,
            "decision_count": self.decision_count,
            "selected_cohort_id": self.selected_cohort_id,
            "cohorts": [row.to_dict() for row in self.cohorts],
            "mixed_minus_primary": {
                "mean_improvement_ppb": (
                    self.mixed_minus_primary_mean_improvement_ppb),
                "bootstrap_lower_ppb": (
                    self.mixed_minus_primary_bootstrap_lower_ppb),
                "bootstrap_upper_ppb": (
                    self.mixed_minus_primary_bootstrap_upper_ppb),
            },
            "bootstrap": {
                "unit": "complete-human-round",
                "replicates": PRIMARY_BOOTSTRAP_REPLICATES,
                "one_sided_or_descriptive_only": "descriptive-two-sided-v1",
            },
            "claim_scope": "human-policy-domain-transfer-descriptive-only",
            "rank_mechanism_claim_authorized": False,
            "privileged_targets_consumed": True,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_human_transfer_test(
        human_rows: tuple[V2RoundScoreV1, ...], *,
        selected_cohort_id: str,
        expected_human_rounds: tuple[tuple[str, str], ...],
        cohort_ids: tuple[str, ...]) -> V2HumanTransferResultV1:
    """Report human test transfer without granting a rank or strength claim."""
    if selected_cohort_id not in {PRIMARY_COHORT_ID, HUMAN_COHORT_ID} \
            or any(cohort not in cohort_ids
                   for cohort in (PRIMARY_COHORT_ID, HUMAN_COHORT_ID)):
        raise BeliefV2StatisticsError("V2 human transfer cohort drift")
    validate_round_population(
        human_rows, source_kind="human", split="test",
        expected_rounds=expected_human_rounds, cohort_ids=cohort_ids)
    reference = tuple(row.reference_brier_ppb for row in human_rows)
    if sum(reference) <= 0:
        raise BeliefV2StatisticsError("V2 human reference Brier is empty")
    cohort_results = []
    differences_by_cohort = {}
    for cohort_id in (PRIMARY_COHORT_ID, HUMAN_COHORT_ID):
        candidate = _cohort_values(human_rows, cohort_id)
        differences = tuple(left - right for left, right in zip(
            reference, candidate, strict=True))
        differences_by_cohort[cohort_id] = differences
        logs = _cohort_values(
            human_rows, cohort_id, field="cohort_log_loss_nanonats")
        cohort_results.append(V2HumanTransferCohortV1(
            cohort_id=cohort_id,
            reference_mean_brier_ppb=_round_divide(
                sum(reference), len(reference)),
            candidate_mean_brier_ppb=_round_divide(
                sum(candidate), len(candidate)),
            mean_brier_improvement_ppb=_round_divide(
                sum(differences), len(differences)),
            bootstrap_lower_improvement_ppb=_percentile_bootstrap_mean(
                differences, label=f"human-test|{cohort_id}|lower",
                percentile=5),
            bootstrap_upper_improvement_ppb=_percentile_bootstrap_mean(
                differences, label=f"human-test|{cohort_id}|upper",
                percentile=95),
            mean_log_loss_improvement_nanonats=_round_divide(sum(
                row.reference_log_loss_nanonats - value
                for row, value in zip(human_rows, logs, strict=True)),
                len(human_rows))))
    paired = tuple(mixed - primary for primary, mixed in zip(
        differences_by_cohort[PRIMARY_COHORT_ID],
        differences_by_cohort[HUMAN_COHORT_ID], strict=True))
    return V2HumanTransferResultV1(
        round_count=len(human_rows),
        decision_count=sum(row.decision_count for row in human_rows),
        selected_cohort_id=selected_cohort_id,
        cohorts=tuple(cohort_results),
        mixed_minus_primary_mean_improvement_ppb=_round_divide(
            sum(paired), len(paired)),
        mixed_minus_primary_bootstrap_lower_ppb=_percentile_bootstrap_mean(
            paired, label="human-test|mixed-minus-primary|lower",
            percentile=5),
        mixed_minus_primary_bootstrap_upper_ppb=_percentile_bootstrap_mean(
            paired, label="human-test|mixed-minus-primary|upper",
            percentile=95))
