"""Small, source-agnostic metrics and baseline for afterstate value models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .value_afterstate import (
    OUTCOME_CLASSES,
    ValueAfterstateError,
    ValueAfterstateExample,
    category_signed_level,
)


class ValueMetricError(ValueError):
    """A probability vector, outcome, pair, or prior population drifted."""


def _probability(value: Sequence[float]) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (OUTCOME_CLASSES,) or not bool(np.all(np.isfinite(result))) \
            or bool(np.any(result < 0.0)) or not np.isclose(
                float(result.sum()), 1.0, rtol=0.0, atol=1e-6):
        raise ValueMetricError("probability vector must be a finite simplex")
    return result


def ranked_probability_score(probability: Sequence[float],
                             target_category: int) -> float:
    """Normalized ordered-category RPS (zero is perfect)."""
    prediction = _probability(probability)
    try:
        category_signed_level(target_category)
    except ValueAfterstateError as exc:
        raise ValueMetricError("target category drift") from exc
    cumulative = np.cumsum(prediction)[:-1]
    truth = np.arange(OUTCOME_CLASSES - 1) >= target_category
    return float(np.mean(np.square(cumulative - truth.astype(np.float64))))


def expected_signed_level(probability: Sequence[float]) -> float:
    prediction = _probability(probability)
    support = np.asarray(
        [category_signed_level(index) for index in range(OUTCOME_CLASSES)],
        dtype=np.float64)
    return float(prediction @ support)


def absolute_value_error(probability: Sequence[float],
                         target_category: int) -> float:
    try:
        target = category_signed_level(target_category)
    except ValueAfterstateError as exc:
        raise ValueMetricError("target category drift") from exc
    return abs(expected_signed_level(probability) - target)


def paired_advantage_error(
        candidate_probability: Sequence[float],
        incumbent_probability: Sequence[float],
        candidate_category: int, incumbent_category: int) -> float:
    """Absolute error of predicted versus realized sibling-action advantage."""
    predicted = (expected_signed_level(candidate_probability)
                 - expected_signed_level(incumbent_probability))
    try:
        realized = (category_signed_level(candidate_category)
                    - category_signed_level(incumbent_category))
    except ValueAfterstateError as exc:
        raise ValueMetricError("paired target category drift") from exc
    return abs(predicted - realized)


@dataclass(frozen=True)
class StratifiedOutcomePrior:
    """Jeffreys-smoothed train-only baseline by phase and actor role."""

    global_probability: tuple[float, ...]
    strata_probability: tuple[tuple[str, tuple[float, ...]], ...]
    training_examples: int

    def validate(self) -> None:
        _probability(self.global_probability)
        if self.training_examples < 1:
            raise ValueMetricError("prior training population is empty")
        keys: set[str] = set()
        for key, probability in self.strata_probability:
            if key in keys or key not in {
                    f"{phase}|{role}" for phase in ("early", "middle", "late")
                    for role in ("attacker", "defender")}:
                raise ValueMetricError("prior stratum drift")
            keys.add(key)
            _probability(probability)

    def probability_for(self, stratum: str) -> tuple[float, ...]:
        self.validate()
        for key, probability in self.strata_probability:
            if key == stratum:
                return probability
        return self.global_probability


def _jeffreys(counts: np.ndarray) -> tuple[float, ...]:
    smoothed = np.asarray(counts, dtype=np.float64) + 0.5
    return tuple(float(value) for value in smoothed / smoothed.sum())


def fit_stratified_prior(
        examples: Iterable[ValueAfterstateExample]) -> StratifiedOutcomePrior:
    rows = list(examples)
    if not rows:
        raise ValueMetricError("prior training population is empty")
    global_counts = np.zeros(OUTCOME_CLASSES, dtype=np.int64)
    strata: dict[str, np.ndarray] = {}
    for row in rows:
        if type(row) is not ValueAfterstateExample:
            raise ValueMetricError("prior received a non-example row")
        try:
            row.validate()
        except ValueAfterstateError as exc:
            raise ValueMetricError("prior example drift") from exc
        global_counts[row.target_category] += 1
        strata.setdefault(
            row.stratum, np.zeros(OUTCOME_CLASSES, dtype=np.int64)
        )[row.target_category] += 1
    result = StratifiedOutcomePrior(
        global_probability=_jeffreys(global_counts),
        strata_probability=tuple(
            (key, _jeffreys(strata[key])) for key in sorted(strata)),
        training_examples=len(rows))
    result.validate()
    return result


def mean_metric(values: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    if not rows or not all(np.isfinite(value) for value in rows):
        raise ValueMetricError("metric population must be non-empty and finite")
    return float(sum(rows) / len(rows))
