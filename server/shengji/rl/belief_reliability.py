"""Held-out receiver-count reliability for BELIEF-V1 ownership outputs.

V1 emits calibrated probabilities for counts 0/1/2 at each card/receiver
cell.  This evaluator scores exactly those probabilities—never an invented
independent joint hand—and reports fixed ten-bin ECE plus an exact rational
reliability slope overall and by public actor strata.

Inputs are exact hash-bound corpus pairs and target-blind ownership artifacts.
Privileged targets are consumed only while building this offline report.  The
module has no model, sampler, RNG, filesystem, policy, gameplay, or authority.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from ..engine.cards import Ordering, TRUMP, points
from .belief_contract import canonical_json_bytes
from .belief_corpus import CorpusPairV1
from .belief_evaluation import reopen_score_pair, target_count_population
from .belief_ownership import (PROBABILITY_SCALE, BeliefOwnershipV1,
                               count_brier_fraction, validate_ownership)


RELIABILITY_SCHEMA = "belief-v1-b2-count-reliability-report-v1"
RELIABILITY_STRATUM_SCHEMA = "belief-v1-b2-count-reliability-stratum-v1"
BIN_COUNT = 10
MIN_STRATUM_CELLS = 1000
LINEAR_EXPECTATION_SCHEMA = (
    "belief-v1-b2-linear-expectation-reliability-v1")


class BeliefReliabilityError(ValueError):
    """The offline reliability population or derivation drifted."""


@dataclass(frozen=True)
class ReliabilityExampleV1:
    pair: CorpusPairV1
    prediction: BeliefOwnershipV1


@dataclass(frozen=True)
class ReliabilityBinV1:
    lower_probability_ppb: int
    upper_probability_ppb: int
    probability_cell_count: int
    predicted_probability_sum_ppb: int
    observed_probability_sum_ppb: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower_probability_ppb": self.lower_probability_ppb,
            "upper_probability_ppb": self.upper_probability_ppb,
            "probability_cell_count": self.probability_cell_count,
            "predicted_probability_sum_ppb": (
                self.predicted_probability_sum_ppb),
            "observed_probability_sum_ppb": (
                self.observed_probability_sum_ppb),
        }


@dataclass(frozen=True)
class ReliabilityStratumV1:
    name: str
    decision_count: int
    probability_cell_count: int
    brier_numerator: int
    brier_denominator: int
    ece_ppb: int
    reliability_slope_numerator: int
    reliability_slope_denominator: int
    reliability_slope_defined: bool
    underpowered: bool
    bins: tuple[ReliabilityBinV1, ...]
    schema: str = RELIABILITY_STRATUM_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "decision_count": self.decision_count,
            "probability_cell_count": self.probability_cell_count,
            "brier": {"numerator": self.brier_numerator,
                      "denominator": self.brier_denominator},
            "ece_ppb": self.ece_ppb,
            "reliability_slope": {
                "numerator": self.reliability_slope_numerator,
                "denominator": self.reliability_slope_denominator,
                "defined": self.reliability_slope_defined,
            },
            "minimum_cells_for_claim": MIN_STRATUM_CELLS,
            "underpowered": self.underpowered,
            "bins": [row.to_dict() for row in self.bins],
        }


@dataclass(frozen=True)
class LinearExpectationReliabilityV1:
    metric: str
    stratum: str
    decision_count: int
    receiver_metric_count: int
    mean_signed_error_count_ppb: int
    mean_absolute_error_count_ppb: int
    squared_error_numerator: int
    squared_error_denominator: int
    reliability_slope_numerator: int
    reliability_slope_denominator: int
    reliability_slope_defined: bool
    underpowered: bool
    schema: str = LINEAR_EXPECTATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "metric": self.metric,
            "stratum": self.stratum,
            "decision_count": self.decision_count,
            "receiver_metric_count": self.receiver_metric_count,
            "mean_signed_error_count_ppb": (
                self.mean_signed_error_count_ppb),
            "mean_absolute_error_count_ppb": (
                self.mean_absolute_error_count_ppb),
            "mean_squared_error": {
                "numerator": self.squared_error_numerator,
                "denominator": self.squared_error_denominator,
            },
            "reliability_slope": {
                "numerator": self.reliability_slope_numerator,
                "denominator": self.reliability_slope_denominator,
                "defined": self.reliability_slope_defined,
            },
            "minimum_cells_for_claim": MIN_STRATUM_CELLS,
            "underpowered": self.underpowered,
        }


@dataclass(frozen=True)
class CountReliabilityReportV1:
    split: str
    model_schema: str
    model_sha256: str
    behavior_policy_ids: tuple[str, ...]
    decision_count: int
    strata: tuple[ReliabilityStratumV1, ...]
    linear_expectations: tuple[LinearExpectationReliabilityV1, ...]
    schema: str = RELIABILITY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "split": self.split,
            "model_schema": self.model_schema,
            "model_sha256": self.model_sha256,
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "decision_count": self.decision_count,
            "bin_edges_ppb": [index * PROBABILITY_SCALE // BIN_COUNT
                              for index in range(BIN_COUNT + 1)],
            "strata": [row.to_dict() for row in self.strata],
            "linear_expectations": [
                row.to_dict() for row in self.linear_expectations],
            "privileged_targets_consumed": True,
            "runtime_artifact": False,
            "joint_posterior_claimed": False,
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
class _Cell:
    probability_ppb: int
    observed: int


@dataclass(frozen=True)
class _LinearCell:
    metric: str
    receiver: str
    predicted_count_ppb: int
    observed_count: int


@dataclass(frozen=True)
class _Decision:
    decision_key: str
    split: str
    model_schema: str
    model_sha256: str
    behavior_policy_ids: tuple[str, ...]
    strata: tuple[str, ...]
    cells: tuple[_Cell, ...]
    linear_cells: tuple[_LinearCell, ...]
    brier: tuple[int, int]


def _public_strata(actor: Any) -> tuple[str, ...]:
    trick_count = len(actor.completed_tricks)
    phase = "early" if trick_count < 8 else "mid" if trick_count < 17 else "late"
    return (
        "all",
        f"role:{'attacker' if actor.actor_is_attacker else 'defender'}",
        f"phase:{phase}",
        f"declaration:{'no-trump' if actor.trump_is_nt else 'suit-trump'}",
        f"kitty:{'hidden' if actor.hidden_burial_size else 'actor-known'}",
    )


def _rounded_ratio(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefReliabilityError("reliability ratio is invalid")
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _slope(covariance: int, variance: int) -> tuple[int, int, bool]:
    if variance < 0:
        raise BeliefReliabilityError("reliability slope variance is negative")
    if variance == 0:
        return 0, 0, False
    divisor = math.gcd(abs(covariance), variance)
    return covariance // divisor, variance // divisor, True


def _decision(example: ReliabilityExampleV1) -> _Decision:
    if type(example) is not ReliabilityExampleV1 \
            or type(example.pair) is not CorpusPairV1 \
            or type(example.prediction) is not BeliefOwnershipV1:
        raise BeliefReliabilityError("reliability example type drift")
    try:
        actor, target, metadata = reopen_score_pair(example.pair)
    except ValueError as exc:
        raise BeliefReliabilityError(
            "reliability corpus pair reconstruction refused") from exc
    try:
        validate_ownership(actor, example.prediction)
    except ValueError as exc:
        raise BeliefReliabilityError("reliability prediction refused") from exc
    counts = target_count_population(actor, target)
    cells = []
    row_by_key = {}
    for row in example.prediction.probabilities:
        row_by_key[(row.card, row.receiver)] = row
        truth = counts[(row.card, row.receiver)]
        for count, probability in enumerate((
                row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)):
            cells.append(_Cell(
                probability_ppb=probability,
                observed=int(count == truth)))
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    unseen_cards = tuple(card for card, _ in actor.deductions.unseen)
    suit_cards = {
        suit: tuple(card for card in unseen_cards
                    if ordering.eff_suit(card) == suit)
        for suit in (*tuple("SHDC"), TRUMP)
    }
    linear_cells = []
    for receiver, _ in example.prediction.receiver_sizes:
        def append_metric(metric: str, cards: tuple[str, ...], *,
                          pair_probability: bool = False) -> None:
            if pair_probability:
                predicted = sum(row_by_key[(card, receiver)].count_2_ppb
                                for card in cards)
                observed = sum(counts[(card, receiver)] == 2
                               for card in cards)
            else:
                predicted = sum(row_by_key[
                    (card, receiver)].expected_count_ppb for card in cards)
                observed = sum(counts[(card, receiver)] for card in cards)
            linear_cells.append(_LinearCell(
                metric=metric, receiver=receiver,
                predicted_count_ppb=predicted,
                observed_count=observed))

        for suit, cards in suit_cards.items():
            if cards:
                metric = ("trump-length" if suit == TRUMP
                          else f"suit-length:{suit}")
                append_metric(metric, cards)
        point_cards = tuple(card for card in unseen_cards if points(card) > 0)
        append_metric("point-card-count", point_cards)
        append_metric("pair-count", unseen_cards, pair_probability=True)
    return _Decision(
        decision_key=metadata["decision_key"],
        split=metadata["split"],
        model_schema=example.prediction.model_schema,
        model_sha256=example.prediction.model_sha256,
        behavior_policy_ids=example.prediction.behavior_policy_ids,
        strata=_public_strata(actor), cells=tuple(cells),
        linear_cells=tuple(linear_cells),
        brier=count_brier_fraction(example.prediction, counts))


def _stratum(name: str, decisions: tuple[_Decision, ...]) \
        -> ReliabilityStratumV1:
    cells = tuple(cell for decision in decisions for cell in decision.cells)
    if not cells:
        raise BeliefReliabilityError("reliability stratum is empty")
    bins = []
    ece_numerator = 0
    for index in range(BIN_COUNT):
        selected = tuple(cell for cell in cells if min(
            cell.probability_ppb * BIN_COUNT // PROBABILITY_SCALE,
            BIN_COUNT - 1) == index)
        predicted = sum(cell.probability_ppb for cell in selected)
        observed = sum(cell.observed for cell in selected) * PROBABILITY_SCALE
        ece_numerator += abs(predicted - observed)
        bins.append(ReliabilityBinV1(
            lower_probability_ppb=index * PROBABILITY_SCALE // BIN_COUNT,
            upper_probability_ppb=(index + 1) * PROBABILITY_SCALE // BIN_COUNT,
            probability_cell_count=len(selected),
            predicted_probability_sum_ppb=predicted,
            observed_probability_sum_ppb=observed,
        ))
    n = len(cells)
    sum_x = sum(cell.probability_ppb for cell in cells)
    sum_y = sum(cell.observed * PROBABILITY_SCALE for cell in cells)
    covariance = n * sum(
        cell.probability_ppb * cell.observed * PROBABILITY_SCALE
        for cell in cells) - sum_x * sum_y
    variance = n * sum(cell.probability_ppb ** 2 for cell in cells) \
        - sum_x ** 2
    slope_numerator, slope_denominator, slope_defined = _slope(
        covariance, variance)
    return ReliabilityStratumV1(
        name=name, decision_count=len(decisions),
        probability_cell_count=n,
        brier_numerator=sum(row.brier[0] for row in decisions),
        brier_denominator=sum(row.brier[1] for row in decisions),
        ece_ppb=(ece_numerator + n // 2) // n,
        reliability_slope_numerator=slope_numerator,
        reliability_slope_denominator=slope_denominator,
        reliability_slope_defined=slope_defined,
        underpowered=n < MIN_STRATUM_CELLS,
        bins=tuple(bins),
    )


def _linear_reliability(
        metric: str, stratum: str, decisions: tuple[_Decision, ...]) \
        -> LinearExpectationReliabilityV1:
    cells = tuple(
        cell for decision in decisions for cell in decision.linear_cells
        if cell.metric == metric)
    if not cells:
        raise BeliefReliabilityError("linear reliability stratum is empty")
    errors = tuple(
        cell.predicted_count_ppb - cell.observed_count * PROBABILITY_SCALE
        for cell in cells)
    n = len(cells)
    sum_x = sum(cell.predicted_count_ppb for cell in cells)
    sum_y = sum(cell.observed_count * PROBABILITY_SCALE for cell in cells)
    covariance = n * sum(
        cell.predicted_count_ppb * cell.observed_count * PROBABILITY_SCALE
        for cell in cells) - sum_x * sum_y
    variance = n * sum(cell.predicted_count_ppb ** 2 for cell in cells) \
        - sum_x ** 2
    slope_numerator, slope_denominator, slope_defined = _slope(
        covariance, variance)
    return LinearExpectationReliabilityV1(
        metric=metric, stratum=stratum,
        decision_count=len(decisions), receiver_metric_count=n,
        mean_signed_error_count_ppb=_rounded_ratio(sum(errors), n),
        mean_absolute_error_count_ppb=_rounded_ratio(
            sum(abs(error) for error in errors), n),
        squared_error_numerator=sum(error ** 2 for error in errors),
        squared_error_denominator=n * PROBABILITY_SCALE ** 2,
        reliability_slope_numerator=slope_numerator,
        reliability_slope_denominator=slope_denominator,
        reliability_slope_defined=slope_defined,
        underpowered=n < MIN_STRATUM_CELLS,
    )


def build_count_reliability_report(
        examples: tuple[ReliabilityExampleV1, ...]) \
        -> CountReliabilityReportV1:
    if type(examples) is not tuple or not examples:
        raise BeliefReliabilityError("reliability population is empty")
    decisions = tuple(_decision(example) for example in examples)
    identities = {(row.split, row.model_schema, row.model_sha256,
                   row.behavior_policy_ids) for row in decisions}
    if len(identities) != 1:
        raise BeliefReliabilityError("reliability model/split identity drift")
    keys = [row.decision_key for row in decisions]
    if len(keys) != len(set(keys)):
        raise BeliefReliabilityError("reliability duplicate decision")
    names = tuple(sorted({name for row in decisions for name in row.strata},
                         key=lambda name: (name != "all", name)))
    strata = tuple(_stratum(
        name, tuple(row for row in decisions if name in row.strata))
                   for name in names)
    metrics = tuple(sorted({cell.metric for row in decisions
                            for cell in row.linear_cells}))
    linear = tuple(
        _linear_reliability(
            metric, name,
            tuple(row for row in decisions if name in row.strata))
        for metric in metrics for name in names
        if any(cell.metric == metric
               for row in decisions if name in row.strata
               for cell in row.linear_cells)
    )
    split, model_schema, model_sha, policies = next(iter(identities))
    return CountReliabilityReportV1(
        split=split, model_schema=model_schema, model_sha256=model_sha,
        behavior_policy_ids=policies, decision_count=len(decisions),
        strata=strata, linear_expectations=linear)
