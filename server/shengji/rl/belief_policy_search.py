"""Pure three-arm production-search aggregation for the R4 policy probe.

World generation and rollouts happen elsewhere.  This module consumes one
common candidate/value tensor, nominates each arm's report challenger with the
literal production point-shy rule, and applies the production protected-
incumbent LCB to fresh common report values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..ai.mcbot import MCBot, point_shy_pick_index
from .belief_policy_weighting import (
    TemperedWorldWeightsV1,
    validate_tempered_world_weights,
    weighted_mean_and_se,
)


PRODUCTION_ARM = "production-mc-lcb"
PRIMARY_ARM = "r4-synthetic-primary"
CONTROL_ARM = "r4-label-control"
ARM_IDS = (PRODUCTION_ARM, PRIMARY_ARM, CONTROL_ARM)
REPORT_T_CRITICAL = MCBot.REPORT_T_CRITICAL
REPORT_MIN_GAIN = MCBot.REPORT_MIN_GAIN
POINT_SHY_EPS = MCBot.POINT_SHY_EPS


class BeliefPolicySearchError(ValueError):
    """A common ballot, value tensor, arm weight, or report fold drifted."""


@dataclass(frozen=True)
class ArmNominationV1:
    arm_id: str
    selection_means: tuple[float, ...]
    raw_winner_index: int
    challenger_index: int


@dataclass(frozen=True)
class ArmDecisionV1:
    nomination: ArmNominationV1
    report_gap: float
    report_se: float
    report_lcb: float
    played_index: int
    reason: str


def _validate_candidates(candidates: tuple[tuple[str, ...], ...]) -> None:
    if type(candidates) is not tuple or len(candidates) < 2 \
            or any(type(candidate) is not tuple or not candidate
                   or any(type(card) is not str or not card
                          for card in candidate)
                   for candidate in candidates) \
            or len(set(candidates)) != len(candidates):
        raise BeliefPolicySearchError("policy diagnostic ballot drift")


def _validate_value_matrix(
        values: tuple[tuple[float, ...], ...], *,
        world_count: int, candidate_count: int) -> None:
    if type(values) is not tuple or len(values) != world_count \
            or any(type(row) is not tuple or len(row) != candidate_count
                   or any(type(value) not in (int, float)
                          or not math.isfinite(value) for value in row)
                   for row in values):
        raise BeliefPolicySearchError(
            "policy diagnostic value matrix drift")


def _validate_learned_weight_pair(
        primary: TemperedWorldWeightsV1,
        control: TemperedWorldWeightsV1, *, world_count: int) -> None:
    try:
        validate_tempered_world_weights(primary)
        validate_tempered_world_weights(control)
    except ValueError as exc:
        raise BeliefPolicySearchError(
            "policy diagnostic learned weights refused") from exc
    if primary.world_count != world_count \
            or control.world_count != world_count \
            or primary.alpha_ppb != control.alpha_ppb:
        raise BeliefPolicySearchError(
            "policy diagnostic common temperature drift")


def _candidate_means(
        values: tuple[tuple[float, ...], ...],
        weights: tuple[int, ...]) -> tuple[float, ...]:
    return tuple(weighted_mean_and_se(
        tuple(row[index] for row in values), weights)[0]
        for index in range(len(values[0])))


def _production_candidate_means(
        values: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    """Reproduce production's unweighted accumulation without ppb rounding."""
    return tuple(
        sum(row[index] for row in values) / len(values)
        for index in range(len(values[0])))


def _production_mean_and_se(
        values: tuple[float, ...]) -> tuple[float, float]:
    """Use the literal production paired-mean moment calculation."""
    total = sum(values)
    squared = sum(value * value for value in values)
    return total / len(values), MCBot._paired_se(total, squared, len(values))


def nominate_three_arms(
        candidates: tuple[tuple[str, ...], ...],
        selection_values: tuple[tuple[float, ...], ...], *,
        primary_weights: TemperedWorldWeightsV1,
        control_weights: TemperedWorldWeightsV1) \
        -> tuple[ArmNominationV1, ArmNominationV1, ArmNominationV1]:
    """Nominate one non-incumbent report challenger per arm."""
    _validate_candidates(candidates)
    world_count = primary_weights.world_count
    _validate_learned_weight_pair(
        primary_weights, control_weights, world_count=world_count)
    _validate_value_matrix(
        selection_values, world_count=world_count,
        candidate_count=len(candidates))
    arm_weights = (
        (PRODUCTION_ARM, None),
        (PRIMARY_ARM, primary_weights.normalized_weight_ppb),
        (CONTROL_ARM, control_weights.normalized_weight_ppb),
    )
    rows = []
    for arm_id, weights in arm_weights:
        means = (_production_candidate_means(selection_values)
                 if weights is None else
                 _candidate_means(selection_values, weights))
        raw_winner = point_shy_pick_index(
            candidates, means, range(len(candidates)), epsilon=POINT_SHY_EPS)
        challenger = point_shy_pick_index(
            candidates, means, range(1, len(candidates)),
            epsilon=POINT_SHY_EPS)
        rows.append(ArmNominationV1(
            arm_id=arm_id,
            selection_means=means,
            raw_winner_index=raw_winner,
            challenger_index=challenger,
        ))
    return tuple(rows)


def finalize_three_arms(
        candidates: tuple[tuple[str, ...], ...],
        nominations: tuple[
            ArmNominationV1, ArmNominationV1, ArmNominationV1],
        report_values_by_candidate: tuple[
            tuple[int, tuple[float, ...]], ...], *,
        primary_weights: TemperedWorldWeightsV1,
        control_weights: TemperedWorldWeightsV1) \
        -> tuple[ArmDecisionV1, ArmDecisionV1, ArmDecisionV1]:
    """Apply the fresh-fold protected-incumbent report rule to every arm."""
    _validate_candidates(candidates)
    if type(nominations) is not tuple or len(nominations) != len(ARM_IDS) \
            or tuple(row.arm_id for row in nominations) != ARM_IDS \
            or any(type(row) is not ArmNominationV1
                   or type(row.challenger_index) is not int
                   or not 1 <= row.challenger_index < len(candidates)
                   or type(row.raw_winner_index) is not int
                   or not 0 <= row.raw_winner_index < len(candidates)
                   or type(row.selection_means) is not tuple
                   or len(row.selection_means) != len(candidates)
                   for row in nominations):
        raise BeliefPolicySearchError(
            "policy diagnostic nomination population drift")
    world_count = primary_weights.world_count
    _validate_learned_weight_pair(
        primary_weights, control_weights, world_count=world_count)
    if type(report_values_by_candidate) is not tuple:
        raise BeliefPolicySearchError(
            "policy diagnostic report value population drift")
    report_values = {}
    for index, values in report_values_by_candidate:
        if type(index) is not int or not 0 <= index < len(candidates) \
                or index in report_values \
                or type(values) is not tuple or len(values) != world_count \
                or any(type(value) not in (int, float)
                       or not math.isfinite(value) for value in values):
            raise BeliefPolicySearchError(
                "policy diagnostic report value population drift")
        report_values[index] = values
    expected = {0, *(row.challenger_index for row in nominations)}
    if set(report_values) != expected:
        raise BeliefPolicySearchError(
            "policy diagnostic report union drift")
    arm_weights = (
        None,
        primary_weights.normalized_weight_ppb,
        control_weights.normalized_weight_ppb,
    )
    decisions = []
    for nomination, weights in zip(nominations, arm_weights, strict=True):
        deltas = tuple(
            challenger - incumbent
            for challenger, incumbent in zip(
                report_values[nomination.challenger_index],
                report_values[0], strict=True))
        gap, se = (_production_mean_and_se(deltas)
                   if weights is None else
                   weighted_mean_and_se(deltas, weights))
        lcb = gap - REPORT_T_CRITICAL * se
        overrides = lcb >= REPORT_MIN_GAIN
        decisions.append(ArmDecisionV1(
            nomination=nomination,
            report_gap=gap,
            report_se=se,
            report_lcb=lcb,
            played_index=(nomination.challenger_index if overrides else 0),
            reason=("report_lcb_override" if overrides
                    else "report_lcb_below_min_gain"),
        ))
    return tuple(decisions)
