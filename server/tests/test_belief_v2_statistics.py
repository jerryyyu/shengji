"""Human-mixture selection, max-stat rank, and scale-curve tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from shengji.rl.belief_v2_protocol import V2_RANKS
from shengji.rl.belief_v2_statistics import (
    BeliefV2StatisticsError,
    V2RoundScoreV1,
    evaluate_human_mixture_selection,
    evaluate_human_transfer_test,
    evaluate_label_control_test,
    evaluate_primary_test,
    evaluate_scale_curve,
    validate_round_population,
)


COHORTS = (
    "synthetic-primary", "human-mixture",
    "synthetic-scale-50", "synthetic-scale-25",
    "hard-geometry-label-permutation",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _row(
        source: str, split: str, rank: str, index: int, *,
        primary: int = 90_000_000, mixed: int = 90_200_000,
        scale50: int = 92_000_000, scale25: int = 94_000_000,
        control: int = 100_000_000):
    values = (primary, mixed, scale50, scale25, control)
    return V2RoundScoreV1(
        round_key=_sha(f"{source}-{split}-{rank}-{index}"),
        source_kind=source, split=split, trump_rank=rank,
        decision_count=60, reference_brier_ppb=100_000_000,
        reference_log_loss_nanonats=800_000_000,
        cohort_brier_ppb=tuple(zip(COHORTS, values, strict=True)),
        cohort_log_loss_nanonats=tuple(
            (cohort, 790_000_000 + offset * 1_000_000)
            for offset, cohort in enumerate(COHORTS)),
        cohort_member_brier_ppb=tuple(
            (cohort, (value,) * 8)
            for cohort, value in zip(COHORTS, values, strict=True)),
    )


def _synthetic(**changes):
    rows = []
    for rank in V2_RANKS:
        for index in range(100):
            row = _row("synthetic", "calibration", rank, index)
            rows.append(replace(row, **changes) if changes else row)
    return tuple(rows)


def _synthetic_test(**changes):
    rows = []
    for rank in V2_RANKS:
        for index in range(100):
            row = _row("synthetic", "test", rank, index)
            rows.append(replace(row, **changes) if changes else row)
    return tuple(rows)


def _human(*, primary=100_000_000, mixed=98_000_000):
    return tuple(_row(
        "human", "calibration", V2_RANKS[index % len(V2_RANKS)], index,
        primary=primary, mixed=mixed)
                 for index in range(20))


def _expected(rows):
    return tuple((row.round_key, row.trump_rank) for row in rows)


def test_clear_human_lift_with_small_rank_regression_selects_mixture():
    synthetic = _synthetic()
    human = _human()
    first = evaluate_human_mixture_selection(
        synthetic, human,
        expected_synthetic_rounds=_expected(synthetic),
        expected_human_rounds=_expected(human), cohort_ids=COHORTS)
    second = evaluate_human_mixture_selection(
        synthetic, human,
        expected_synthetic_rounds=_expected(synthetic),
        expected_human_rounds=_expected(human), cohort_ids=COHORTS)
    assert first == second
    assert first.retained is True
    assert first.refusal_reasons == ()
    assert first.human_bootstrap_lower_improvement_ppb == 2_000_000
    assert first.synthetic_bootstrap_upper_regression_ppb == 200_000
    assert set(dict(first.rank_round_counts).values()) == {100}
    assert set(dict(
        first.rank_familywise_upper_regression_ppb).values()) == {200_000}
    assert set(value for key, value in first.to_dict().items()
               if key.endswith("_authorized")) == {False}


def test_human_edge_aggregate_regression_and_rank_regression_fail_separately():
    synthetic = _synthetic()
    no_human_edge = _human(primary=100_000_000, mixed=100_000_000)
    result = evaluate_human_mixture_selection(
        synthetic, no_human_edge,
        expected_synthetic_rounds=_expected(synthetic),
        expected_human_rounds=_expected(no_human_edge), cohort_ids=COHORTS)
    assert result.refusal_reasons \
        == ("human-domain-lower-bound-not-positive",)

    aggregate = tuple(replace(
        row,
        cohort_brier_ppb=tuple(
            (cohort, 91_000_000 if cohort == "human-mixture" else value)
            for cohort, value in row.cohort_brier_ppb))
                      for row in synthetic)
    result = evaluate_human_mixture_selection(
        aggregate, _human(),
        expected_synthetic_rounds=_expected(aggregate),
        expected_human_rounds=_expected(_human()), cohort_ids=COHORTS)
    assert "synthetic-aggregate-material-regression" \
        in result.refusal_reasons
    assert "synthetic-rank-familywise-material-regression" \
        in result.refusal_reasons

    one_rank = tuple(replace(
        row,
        cohort_brier_ppb=tuple(
            (cohort, (91_000_000 if row.trump_rank == V2_RANKS[0]
                      else 90_000_000))
            if cohort == "human-mixture" else (cohort, value)
            for cohort, value in row.cohort_brier_ppb))
                     for row in synthetic)
    result = evaluate_human_mixture_selection(
        one_rank, _human(),
        expected_synthetic_rounds=_expected(one_rank),
        expected_human_rounds=_expected(_human()), cohort_ids=COHORTS)
    assert "synthetic-aggregate-material-regression" \
        not in result.refusal_reasons
    assert result.refusal_reasons \
        == ("synthetic-rank-familywise-material-regression",)


def test_scale_curve_reports_each_fraction_without_selecting_a_model():
    synthetic = _synthetic()
    result = evaluate_scale_curve(
        synthetic, expected_synthetic_rounds=_expected(synthetic),
        cohort_ids=COHORTS,
        scale_fractions=(("synthetic-scale-50", 1, 2),
                         ("synthetic-scale-25", 1, 4)))
    assert result.any_positive_data_scaling_signal is True
    assert [row.primary_mean_improvement_ppb for row in result.rows] \
        == [2_000_000, 4_000_000]
    assert all(row.positive_lower_bound for row in result.rows)
    assert result.to_dict()["gameplay_authorized"] is False


def test_population_order_rank_power_and_type_mutations_refuse():
    synthetic = _synthetic()
    with pytest.raises(BeliefV2StatisticsError, match="identity/order"):
        validate_round_population(
            (synthetic[1], synthetic[0], *synthetic[2:]),
            source_kind="synthetic", split="calibration",
            expected_rounds=_expected(synthetic), cohort_ids=COHORTS)
    with pytest.raises(BeliefV2StatisticsError, match="schema/value"):
        validate_round_population(
            (replace(synthetic[0], decision_count=True), *synthetic[1:]),
            source_kind="synthetic", split="calibration",
            expected_rounds=_expected(synthetic), cohort_ids=COHORTS)

    underpowered = tuple(
        row for index, row in enumerate(synthetic)
        if not (row.trump_rank == V2_RANKS[0] and index == 0))
    with pytest.raises(BeliefV2StatisticsError, match="underpowered"):
        evaluate_human_mixture_selection(
            underpowered, _human(),
            expected_synthetic_rounds=_expected(underpowered),
            expected_human_rounds=_expected(_human()), cohort_ids=COHORTS)


def test_member_population_and_cohort_order_are_closed():
    synthetic = _synthetic()
    bad_members = tuple(
        (cohort, values[:-1] if cohort == "human-mixture" else values)
        for cohort, values in synthetic[0].cohort_member_brier_ppb)
    with pytest.raises(BeliefV2StatisticsError, match="schema/value"):
        validate_round_population(
            (replace(synthetic[0],
                     cohort_member_brier_ppb=bad_members), *synthetic[1:]),
            source_kind="synthetic", split="calibration",
            expected_rounds=_expected(synthetic), cohort_ids=COHORTS)
    with pytest.raises(BeliefV2StatisticsError, match="schema/value"):
        validate_round_population(
            (replace(synthetic[0], cohort_brier_ppb=tuple(
                reversed(synthetic[0].cohort_brier_ppb))), *synthetic[1:]),
            source_kind="synthetic", split="calibration",
            expected_rounds=_expected(synthetic), cohort_ids=COHORTS)


def test_primary_test_passes_all_aggregate_member_log_and_rank_gates():
    rows = _synthetic_test()
    result = evaluate_primary_test(
        rows, selected_cohort_id="synthetic-primary",
        expected_synthetic_rounds=_expected(rows), cohort_ids=COHORTS)
    assert result.passed is True
    assert result.refusal_reasons == ()
    assert result.relative_brier_improvement_ppb == 100_000_000
    assert result.bootstrap_lower_improvement_ppb == 10_000_000
    assert result.positive_member_count == 8
    assert set(dict(
        result.rank_familywise_upper_regression_ppb).values()) \
        == {-10_000_000}
    assert result.to_dict()["sampler_implementation_authorized"] is False


def test_primary_test_gates_member_and_isolated_rank_failures():
    rows = _synthetic_test()
    weak_members = tuple(replace(
        row, cohort_member_brier_ppb=tuple(
            (cohort, ((90_000_000,) * 5 + (101_000_000,) * 3)
             if cohort == "synthetic-primary" else values)
            for cohort, values in row.cohort_member_brier_ppb))
                         for row in rows)
    result = evaluate_primary_test(
        weak_members, selected_cohort_id="synthetic-primary",
        expected_synthetic_rounds=_expected(weak_members),
        cohort_ids=COHORTS)
    assert "individual-member-sign-count-not-met" in result.refusal_reasons

    rank_regression = tuple(replace(
        row, cohort_brier_ppb=tuple(
            (cohort, (101_000_000 if row.trump_rank == V2_RANKS[0]
                      else value))
            for cohort, value in row.cohort_brier_ppb)
        if row.trump_rank == V2_RANKS[0] else row.cohort_brier_ppb)
                            for row in rows)
    result = evaluate_primary_test(
        rank_regression, selected_cohort_id="synthetic-primary",
        expected_synthetic_rounds=_expected(rank_regression),
        cohort_ids=COHORTS)
    assert "rank-familywise-material-regression" in result.refusal_reasons


def test_label_control_must_fail_to_learn_on_exact_test_population():
    rows = _synthetic_test()
    result = evaluate_label_control_test(
        rows, expected_synthetic_rounds=_expected(rows),
        cohort_ids=COHORTS)
    assert result.passed is True
    assert result.bootstrap_lower_improvement_ppb == 0

    learned = tuple(replace(row, cohort_brier_ppb=tuple(
        (cohort, 98_000_000 if cohort
         == "hard-geometry-label-permutation" else value)
        for cohort, value in row.cohort_brier_ppb)) for row in rows)
    result = evaluate_label_control_test(
        learned, expected_synthetic_rounds=_expected(learned),
        cohort_ids=COHORTS)
    assert result.passed is False
    assert result.unexpectedly_positive_lower_bound is True


def test_human_test_is_descriptive_separate_and_exact_n_is_reported():
    rows = tuple(replace(
        row, split="test",
        round_key=_sha(f"human-test-{index}"))
                 for index, row in enumerate(_human()))
    result = evaluate_human_transfer_test(
        rows, selected_cohort_id="human-mixture",
        expected_human_rounds=_expected(rows), cohort_ids=COHORTS)
    assert result.round_count == 20
    assert result.decision_count == 1_200
    assert result.mixed_minus_primary_mean_improvement_ppb == 2_000_000
    assert result.mixed_minus_primary_bootstrap_lower_ppb == 2_000_000
    payload = result.to_dict()
    assert payload["claim_scope"] \
        == "human-policy-domain-transfer-descriptive-only"
    assert payload["rank_mechanism_claim_authorized"] is False
    assert payload["strength_claim_authorized"] is False
