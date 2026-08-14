"""Frozen B2 primary-statistic and reference-stability tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
)
from shengji.rl.belief_b2_statistics import (
    BeliefB2StatisticsError,
    RoundProperScoreV1,
    evaluate_c1,
    evaluate_n2,
    reference_replicates_are_stable,
)
def _round(seed, *, reference=100_000_000, candidate=98_000_000,
           members=None, ref_log=800_000_000, candidate_log=790_000_000):
    if members is None:
        members = (98_500_000,) * 8
    return RoundProperScoreV1(
        round_seed=seed, decision_count=76,
        reference_brier_ppb=reference,
        candidate_brier_ppb=candidate,
        member_brier_ppb=members,
        reference_log_loss_nanonats=ref_log,
        candidate_log_loss_nanonats=candidate_log,
    )


def test_clear_lift_passes_every_primary_gate_deterministically():
    rounds = tuple(_round(seed) for seed in b2_split_round_seeds("test"))
    first = evaluate_c1(rounds)
    second = evaluate_c1(rounds)
    assert first == second
    assert first.passed is True
    assert first.refusal_reasons == ()
    assert first.relative_brier_improvement_ppb == 20_000_000
    assert first.bootstrap_lower_brier_improvement_ppb == 2_000_000
    assert first.positive_member_count == 8
    assert first.mean_log_loss_improvement_nanonats == 10_000_000
    assert set(value for key, value in first.to_dict().items()
               if key.endswith("_authorized")) == {False}


def test_aggregate_floor_lcb_member_and_log_gates_are_independent():
    seeds = b2_split_round_seeds("test")
    base = tuple(_round(seed) for seed in seeds)

    floor = tuple(replace(row, candidate_brier_ppb=99_600_000)
                  for row in base)
    assert evaluate_c1(floor).refusal_reasons \
        == ("mean-relative-brier-floor-not-met",)

    noisy = tuple(replace(
        row, candidate_brier_ppb=(80_000_000 if index < len(base) // 2
                                 else 125_000_000))
                  for index, row in enumerate(base))
    noisy_result = evaluate_c1(noisy)
    assert "paired-round-bootstrap-lower-bound-not-positive" \
        in noisy_result.refusal_reasons

    weak_members = tuple(replace(
        row, member_brier_ppb=(98_000_000,) * 5 + (101_000_000,) * 3)
                         for row in base)
    assert "individual-member-sign-count-not-met" \
        in evaluate_c1(weak_members).refusal_reasons

    reversed_log = tuple(replace(row, candidate_log_loss_nanonats=810_000_000)
                         for row in base)
    assert "smoothed-log-loss-materially-reversed" \
        in evaluate_c1(reversed_log).refusal_reasons


def test_reference_replicate_stability_uses_strict_relative_ceiling():
    seeds = b2_split_round_seeds("calibration")
    left = tuple(_round(seed, reference=100_000_000) for seed in seeds)
    inside = tuple(_round(seed, reference=100_100_000) for seed in seeds)
    outside = tuple(_round(seed, reference=100_200_000) for seed in seeds)
    assert reference_replicates_are_stable(left, inside) is True
    assert reference_replicates_are_stable(left, outside) is False


def test_permuted_label_control_must_not_have_positive_lower_bound():
    seeds = b2_split_round_seeds("test")
    chance = tuple(_round(seed, candidate=100_000_000) for seed in seeds)
    result = evaluate_n2(chance)
    assert result.passed is True
    assert result.bootstrap_lower_brier_improvement_ppb == 0
    assert result.unexpectedly_positive_lower_bound is False
    assert all(result.to_dict()[key] is False
               for key in result.to_dict() if key.endswith("_authorized"))

    leaked = tuple(_round(seed, candidate=98_000_000) for seed in seeds)
    result = evaluate_n2(leaked)
    assert result.bootstrap_lower_brier_improvement_ppb > 0
    assert result.unexpectedly_positive_lower_bound is True
    assert result.passed is False


def test_statistics_refuse_bool_negative_duplicate_order_and_wrong_split():
    test_seeds = b2_split_round_seeds("test")
    rows = tuple(_round(seed) for seed in test_seeds)
    with pytest.raises(BeliefB2StatisticsError, match="schema/value"):
        evaluate_c1((replace(rows[0], candidate_brier_ppb=True), *rows[1:]))
    with pytest.raises(BeliefB2StatisticsError, match="schema/value"):
        evaluate_c1((replace(rows[0], candidate_brier_ppb=-1), *rows[1:]))
    with pytest.raises(BeliefB2StatisticsError, match="split/order"):
        evaluate_c1((rows[1], rows[0], *rows[2:]))
    with pytest.raises(BeliefB2StatisticsError, match="split/order"):
        evaluate_c1((rows[0], rows[0], *rows[2:]))
    calibration_seed = b2_split_round_seeds("calibration")[0]
    with pytest.raises(BeliefB2StatisticsError, match="split/order"):
        evaluate_c1((_round(calibration_seed),))
