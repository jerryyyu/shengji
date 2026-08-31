"""Three-arm common-world production-search aggregation witnesses."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.ai.mcbot import MCBot
from shengji.rl.belief_policy_search import (
    CONTROL_ARM,
    PRIMARY_ARM,
    PRODUCTION_ARM,
    BeliefPolicySearchError,
    finalize_three_arms,
    nominate_three_arms,
)
from shengji.rl.belief_policy_weighting import (
    PPB,
    common_tempered_world_weights,
)


CANDIDATES = (("C2",), ("C3",), ("C4",))


def _selection_weights():
    return common_tempered_world_weights(
        (1_000_000_000,) * 15 + (-1_000_000_000,) * 15,
        (0,) * 30,
    )


def _report_weights():
    return common_tempered_world_weights((0,) * 300, (0,) * 300)


def test_primary_can_nominate_differently_without_changing_common_values():
    primary, control = _selection_weights()
    selection = tuple(
        (0.0, 10.0, 0.0) if index < 15 else (0.0, 0.0, 12.0)
        for index in range(30))
    nominations = nominate_three_arms(
        CANDIDATES, selection,
        primary_weights=primary, control_weights=control)
    assert tuple(row.arm_id for row in nominations) == (
        PRODUCTION_ARM, PRIMARY_ARM, CONTROL_ARM)
    assert nominations[0].challenger_index == 2
    assert nominations[1].challenger_index == 1
    assert nominations[2].challenger_index == 2

    report_primary, report_control = _report_weights()
    decisions = finalize_three_arms(
        CANDIDATES, nominations,
        report_values_by_candidate=(
            (0, (0.0,) * 300),
            (1, (1.0,) * 300),
            (2, (2.0,) * 300),
        ),
        primary_weights=report_primary,
        control_weights=report_control)
    assert tuple(row.played_index for row in decisions) == (2, 1, 2)
    assert all(row.reason == "report_lcb_override" for row in decisions)


def test_report_union_must_cover_exactly_the_three_nominations():
    primary, control = _selection_weights()
    selection = tuple((0.0, 1.0, 2.0) for _ in range(30))
    nominations = nominate_three_arms(
        CANDIDATES, selection,
        primary_weights=primary, control_weights=control)
    report_primary, report_control = _report_weights()
    with pytest.raises(BeliefPolicySearchError, match="report union"):
        finalize_three_arms(
            CANDIDATES, nominations,
            report_values_by_candidate=((0, (0.0,) * 300),),
            primary_weights=report_primary,
            control_weights=report_control)


def test_primary_and_control_cannot_use_different_temperatures():
    primary, control = _selection_weights()
    forged = replace(control, alpha_ppb=(0 if primary.alpha_ppb else PPB))
    with pytest.raises(BeliefPolicySearchError, match="common temperature"):
        nominate_three_arms(
            CANDIDATES,
            tuple((0.0, 1.0, 2.0) for _ in range(30)),
            primary_weights=primary,
            control_weights=forged)


def test_negative_report_lcb_protects_incumbent():
    selection_primary, selection_control = _selection_weights()
    nominations = nominate_three_arms(
        CANDIDATES,
        tuple((0.0, 1.0, 2.0) for _ in range(30)),
        primary_weights=selection_primary,
        control_weights=selection_control)
    report_primary, report_control = _report_weights()
    decisions = finalize_three_arms(
        CANDIDATES, nominations,
        report_values_by_candidate=(
            (0, (1.0,) * 300),
            (2, (0.0,) * 300),
        ),
        primary_weights=report_primary,
        control_weights=report_control)
    assert all(row.played_index == 0 for row in decisions)
    assert all(row.report_lcb < 0 for row in decisions)


def test_production_arm_uses_literal_unweighted_moments():
    primary, control = common_tempered_world_weights(
        tuple(range(30)), tuple(range(30)))
    selection = tuple(
        (float(index % 5), float(index % 7), float(index % 11))
        for index in range(30))
    nominations = nominate_three_arms(
        CANDIDATES, selection,
        primary_weights=primary, control_weights=control)
    assert nominations[0].selection_means == tuple(
        sum(row[index] for row in selection) / len(selection)
        for index in range(len(CANDIDATES)))

    report_primary, report_control = _report_weights()
    incumbent = tuple(float(index % 4) for index in range(300))
    challenger = tuple(
        incumbent[index] + float((index % 9) - 4)
        for index in range(300))
    report = ((0, incumbent),
              (nominations[0].challenger_index, challenger))
    # Make every arm nominate the same challenger so the report union remains
    # exact while the production witness stays independent of ppb weights.
    aligned = tuple(replace(row, challenger_index=nominations[0].challenger_index)
                    for row in nominations)
    decision = finalize_three_arms(
        CANDIDATES, aligned, report,
        primary_weights=report_primary,
        control_weights=report_control)[0]
    deltas = tuple(left - right
                   for left, right in zip(challenger, incumbent, strict=True))
    total = sum(deltas)
    squared = sum(value * value for value in deltas)
    assert decision.report_gap == total / len(deltas)
    assert decision.report_se == MCBot._paired_se(
        total, squared, len(deltas))
