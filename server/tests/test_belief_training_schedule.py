"""Deterministic B2 batch schedule and common-epoch tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_training import build_training_example
from shengji.rl.belief_training_schedule import (
    BeliefTrainingScheduleError,
    BoundTrainingExampleV1,
    ordered_round_seeds_for_epoch,
    select_common_epoch,
    training_epoch_batches,
)


POLICIES = ("mc-s0-report-lcb",)


def _bound_examples(round_count=3, decisions=4, split="train"):
    result = []
    for seed in b2_split_round_seeds(split)[:round_count]:
        captured = _capture_with_policies(
            seed, POLICIES[0], champion_policy_seeds(seed),
            [HeuristicBot() for _ in range(4)])
        for pair in captured.pairs[:decisions]:
            result.append(BoundTrainingExampleV1(
                pair=pair, example=build_training_example(
                    pair, behavior_policy_ids=POLICIES)))
    return tuple(result)


def test_rounds_are_shuffled_deterministically_but_never_split():
    bound = _bound_examples()
    first_schedule, first_batches = training_epoch_batches(bound, epoch=1)
    repeated_schedule, repeated_batches = training_epoch_batches(
        bound, epoch=1)
    second_schedule, _ = training_epoch_batches(bound, epoch=2)
    assert first_schedule == repeated_schedule
    assert tuple(batch.decision_keys for batch in first_batches) \
        == tuple(batch.decision_keys for batch in repeated_batches)
    assert set(first_schedule.ordered_round_seeds) \
        == set(second_schedule.ordered_round_seeds)
    assert first_schedule.ordered_round_seeds \
        == ordered_round_seeds_for_epoch(
            tuple(item.example.round_seed for item in bound[::4]), epoch=1)
    for schedule in (first_schedule, second_schedule):
        position = {key: index for index, batch in enumerate(
            schedule.batch_decision_keys) for key in batch}
        for seed in schedule.ordered_round_seeds:
            keys = [item.example.decision_key for item in bound
                    if item.example.round_seed == seed]
            assert len({position[key] for key in keys}) == 1
    assert all(batch.split == "train" for batch in first_batches)


def test_schedule_refuses_target_drift_duplicate_gap_and_nontrain():
    bound = _bound_examples(round_count=2)
    changed_labels = bound[0].example.count_labels.copy()
    active = bound[0].example.active_mask
    index = tuple(zip(*active.nonzero(), strict=True))[0]
    changed_labels[index] = (changed_labels[index] + 1) % 3
    with pytest.raises(BeliefTrainingScheduleError, match="example refused"):
        training_epoch_batches((replace(
            bound[0], example=replace(
                bound[0].example, count_labels=changed_labels)),
                                *bound[1:]), epoch=1)
    with pytest.raises(BeliefTrainingScheduleError, match="duplicate"):
        training_epoch_batches((bound[0], bound[0], *bound[1:]), epoch=1)
    with pytest.raises(BeliefTrainingScheduleError, match="sequence"):
        training_epoch_batches((bound[1], *bound[4:]), epoch=1)
    calibration = _bound_examples(
        round_count=1, decisions=1, split="calibration")
    with pytest.raises(BeliefTrainingScheduleError, match="non-train"):
        training_epoch_batches(calibration, epoch=1)
    with pytest.raises(BeliefTrainingScheduleError, match="population"):
        ordered_round_seeds_for_epoch((1, 1), epoch=1)


def test_common_epoch_uses_cohort_mean_minimum_improvement_and_patience():
    losses = tuple((1_000_000, 850_000, 810_000, 805_000, 804_000,
                    803_000) for _ in range(8))
    decision = select_common_epoch(losses)
    assert decision.selected_epoch == 2
    assert decision.stop_epoch == 5
    assert decision.stopped_for_patience is True
    assert decision.cohort_mean_loss_nanonats \
        == (1_000_000, 850_000, 810_000, 805_000, 804_000)
    assert select_common_epoch(
        tuple((1_000_000,) for _ in range(8))).stopped_for_patience is False


def test_common_epoch_refuses_best_seed_missing_float_and_epoch_drift():
    losses = tuple((1_000_000, 800_000, 700_000) for _ in range(8))
    with pytest.raises(BeliefTrainingScheduleError, match="population"):
        select_common_epoch(losses[:-1])
    with pytest.raises(BeliefTrainingScheduleError, match="epoch count"):
        select_common_epoch((*losses[:-1], (1_000_000, 800_000)))
    with pytest.raises(BeliefTrainingScheduleError, match="value"):
        select_common_epoch((
            (1_000_000, 800_000, 700_000.0), *losses[1:]))
