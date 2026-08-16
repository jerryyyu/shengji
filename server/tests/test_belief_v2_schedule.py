"""Realized V2 population, work-match, and round-group schedule tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_v2_device_qualification import (
    build_qualification_plan_from_primary,
)
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
)
from shengji.rl.belief_v2_schedule import (
    BeliefV2ScheduleError,
    V2TrainingRowV1,
    realization_set_sha256,
    realize_v2_cohorts,
    training_row,
    validate_v2_cohort_realizations,
)
from shengji.rl.belief_v2_training import (
    build_synthetic_training_example,
    collate_v2_training_examples,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _plans():
    primary = V2CohortPlanV1(
        cohort_id="synthetic-primary", kind="synthetic-primary",
        synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
        synthetic_fraction_numerator=1, synthetic_fraction_denominator=1,
        human_selection_rule=NO_HUMAN_DECISIONS,
        work_match_rule=PRIMARY_WORK_RULE, comparator_cohort_id=None)
    return (
        primary,
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _rows(source: str, count: int, per_round: int = 2):
    return tuple(V2TrainingRowV1(
        decision_key=_sha(f"{source}-decision-{index}"),
        round_group_key=_sha(f"{source}-round-{index // per_round}"),
        source_kind=source,
        active_label_count=100 + index,
        example_sha256=_sha(f"{source}-example-{index}"),
    ) for index in range(count))


def _realized():
    plans = _plans()
    synthetic = _rows("synthetic", 20)
    human = _rows("human", 4)
    return plans, synthetic, human, realize_v2_cohorts(
        plans, synthetic_rows=synthetic, human_rows=human)


def test_all_four_populations_have_exact_work_and_comparator_bindings():
    plans, synthetic, human, values = _realized()
    validate_v2_cohort_realizations(
        plans, synthetic_rows=synthetic, human_rows=human,
        candidates=values)
    by_kind = {value.kind: value for value in values}
    primary = by_kind["synthetic-primary"]
    control = by_kind["hard-geometry-label-permutation"]
    mixed = by_kind["human-mixture"]
    scale = by_kind["synthetic-scale"]
    assert primary.synthetic_decision_count == 20
    assert primary.human_decision_count == 0
    assert control.decision_population_sha256 \
        == primary.decision_population_sha256
    assert control.batch_schedule_sha256 == primary.batch_schedule_sha256
    assert mixed.synthetic_decision_count == 16
    assert mixed.human_decision_count == 4
    assert len(mixed.rows) == len(primary.rows) == 20
    assert len(mixed.removed_synthetic_decision_keys) == 4
    assert scale.synthetic_decision_count == 10
    assert scale.human_decision_count == 0
    assert len(realization_set_sha256(values)) == 64
    assert all(value.to_dict()["training_authorized"] is False
               for value in values)


def test_primary_schedule_feeds_exact_device_qualification_plan():
    plans = _plans()
    values = realize_v2_cohorts(
        plans, synthetic_rows=_rows("synthetic", 8192, per_round=256),
        human_rows=_rows("human", 1))
    primary = next(value for value in values
                   if value.kind == "synthetic-primary")
    assert len(primary.batches) == 32
    qualification = build_qualification_plan_from_primary(
        execution_git="a" * 40, candidate_device="mps",
        primary=primary, host_memory_cap_bytes=1024,
        device_memory_cap_bytes=1024)
    assert qualification.full_schedule_sha256
    assert qualification.selected_batch_indices == tuple(range(32))
    assert qualification.decision_count == 8192


def test_selected_round_group_is_never_split_between_batches():
    _, _, _, values = _realized()
    for value in values:
        batch_by_key = {
            key: index for index, batch in enumerate(value.batches)
            for key in batch
        }
        group_batches = {}
        for row in value.rows:
            group_batches.setdefault(row.round_group_key, set()).add(
                batch_by_key[row.decision_key])
        assert all(len(indices) == 1 for indices in group_batches.values())


def test_fully_known_final_decision_remains_in_positive_supervision_batch():
    captured = _capture_with_policies(
        2, CHAMPION_POLICY, (101, 102, 103, 104),
        [HeuristicBot() for _ in range(4)])
    examples = tuple(
        build_synthetic_training_example(pair) for pair in captured.pairs)
    assert len(examples) == 84
    assert int(examples[-1].active_mask.sum()) == 0
    assert all(int(example.active_mask.sum()) > 0
               for example in examples[:-1])

    rows = tuple(training_row(example) for example in examples)
    values = realize_v2_cohorts(
        _plans(), synthetic_rows=rows, human_rows=_rows("human", 4))
    primary = next(value for value in values
                   if value.kind == "synthetic-primary")
    assert len(primary.rows) == len(examples)
    assert any(row.active_label_count == 0 for row in primary.rows)
    active_by_key = {
        row.decision_key: row.active_label_count for row in primary.rows}
    assert all(sum(active_by_key[key] for key in batch) > 0
               for batch in primary.batches)

    batch = collate_v2_training_examples(examples)
    assert int(batch.active_mask[-1].sum()) == 0
    assert int(batch.active_mask.sum()) == primary.active_label_count > 0


def test_realized_schedule_refuses_a_wholly_unsupervised_batch():
    negative = replace(
        _rows("synthetic", 5)[0], active_label_count=-1)
    with pytest.raises(BeliefV2ScheduleError,
                       match="realized training row drift"):
        realize_v2_cohorts(
            _plans(), synthetic_rows=(
                negative, *_rows("synthetic", 5)[1:]),
            human_rows=_rows("human", 1))

    synthetic = tuple(replace(row, active_label_count=0)
                      for row in _rows("synthetic", 5))
    with pytest.raises(BeliefV2ScheduleError,
                       match="batch has no active supervision"):
        realize_v2_cohorts(
            _plans(), synthetic_rows=synthetic,
            human_rows=_rows("human", 1))


def test_multiple_frozen_scale_fractions_form_one_nested_learning_curve():
    plans = (*_plans(), V2CohortPlanV1(
        cohort_id="synthetic-scale-25", kind="synthetic-scale",
        synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
        synthetic_fraction_numerator=1, synthetic_fraction_denominator=4,
        human_selection_rule=NO_HUMAN_DECISIONS,
        work_match_rule=SCALE_WORK_RULE,
        comparator_cohort_id="synthetic-primary"))
    synthetic = _rows("synthetic", 20)
    human = _rows("human", 4)
    values = realize_v2_cohorts(
        plans, synthetic_rows=synthetic, human_rows=human)
    validate_v2_cohort_realizations(
        plans, synthetic_rows=synthetic, human_rows=human,
        candidates=values)
    half = next(value for value in values
                if value.cohort_id == "synthetic-scale-50")
    quarter = next(value for value in values
                   if value.cohort_id == "synthetic-scale-25")
    assert half.synthetic_decision_count == 10
    assert quarter.synthetic_decision_count == 5
    assert {row.decision_key for row in quarter.rows} \
        < {row.decision_key for row in half.rows}


def test_input_order_and_active_label_values_cannot_select_decisions():
    plans, synthetic, human, natural = _realized()
    reordered = realize_v2_cohorts(
        plans, synthetic_rows=tuple(reversed(synthetic)),
        human_rows=tuple(reversed(human)))
    assert tuple(value.canonical_bytes() for value in reordered) \
        == tuple(value.canonical_bytes() for value in natural)

    changed_synthetic = tuple(replace(
        row, active_label_count=row.active_label_count + 1000)
        for row in synthetic)
    changed = realize_v2_cohorts(
        plans, synthetic_rows=changed_synthetic, human_rows=human)
    natural_by_kind = {value.kind: value for value in natural}
    changed_by_kind = {value.kind: value for value in changed}
    assert changed_by_kind["human-mixture"].removed_synthetic_decision_keys \
        == natural_by_kind["human-mixture"].removed_synthetic_decision_keys
    assert tuple(row.decision_key
                 for row in changed_by_kind["synthetic-scale"].rows) \
        == tuple(row.decision_key
                 for row in natural_by_kind["synthetic-scale"].rows)


def test_reopener_refuses_coordinated_population_schedule_and_receipt_edits():
    plans, synthetic, human, values = _realized()
    mixed_index = next(index for index, value in enumerate(values)
                       if value.kind == "human-mixture")
    mixed = values[mixed_index]

    candidates = list(values)
    candidates[mixed_index] = replace(
        mixed, removed_synthetic_decision_keys=(
            _sha("forged-removal"),
            *mixed.removed_synthetic_decision_keys[1:]))
    with pytest.raises(BeliefV2ScheduleError, match="reconstruction"):
        validate_v2_cohort_realizations(
            plans, synthetic_rows=synthetic, human_rows=human,
            candidates=tuple(candidates))

    candidates = list(values)
    first_batch = mixed.batches[0]
    candidates[mixed_index] = replace(
        mixed, batches=((first_batch[1], first_batch[0], *first_batch[2:]),
                        *mixed.batches[1:]),
        batch_schedule_sha256=_sha("coordinated-forgery"))
    with pytest.raises(BeliefV2ScheduleError):
        validate_v2_cohort_realizations(
            plans, synthetic_rows=synthetic, human_rows=human,
            candidates=tuple(candidates))


def test_human_fraction_duplicate_identity_and_plan_rule_drift_refuse():
    plans = _plans()
    synthetic = _rows("synthetic", 20)
    with pytest.raises(BeliefV2ScheduleError, match="fraction"):
        realize_v2_cohorts(
            plans, synthetic_rows=synthetic,
            human_rows=_rows("human", 5))

    duplicate = replace(
        _rows("human", 4)[0], decision_key=synthetic[0].decision_key)
    with pytest.raises(BeliefV2ScheduleError, match="identity"):
        realize_v2_cohorts(
            plans, synthetic_rows=synthetic,
            human_rows=(duplicate, *_rows("human", 4)[1:]))

    changed_plans = tuple(
        replace(plan, human_selection_rule=NO_HUMAN_DECISIONS)
        if plan.kind == "human-mixture" else plan for plan in plans)
    with pytest.raises(BeliefV2ScheduleError, match="selection rule"):
        realize_v2_cohorts(
            changed_plans, synthetic_rows=synthetic,
            human_rows=_rows("human", 4))

    changed_plans = tuple(
        replace(plan, work_match_rule=PRIMARY_WORK_RULE)
        if plan.kind == "human-mixture" else plan for plan in plans)
    with pytest.raises(BeliefV2ScheduleError, match="selection rule"):
        realize_v2_cohorts(
            changed_plans, synthetic_rows=synthetic,
            human_rows=_rows("human", 4))
