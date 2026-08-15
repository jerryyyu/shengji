"""Mechanically valid BELIEF-V1 negative-control tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_controls import (
    BeliefControlError,
    build_control_example,
    collate_control_examples,
    validate_control_example,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import (
    BeliefTrainerError,
    evaluate_calibration_loss_nanonats,
    new_b2_optimizer,
    train_epoch,
)
from shengji.rl.belief_training import (
    HISTORY_ABLATION_CONTROL,
    LABEL_PERMUTATION_CONTROL,
)


POLICIES = ("mc-s0-report-lcb",)


def _pairs(decisions=8, split="train"):
    seed = b2_split_round_seeds(split)[0]
    captured = _capture_with_policies(
        seed, POLICIES[0], champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])
    return captured.pairs[:decisions]


def test_history_ablation_preserves_event_multiset_and_labels_but_changes_order():
    examples = tuple(build_control_example(
        pair, behavior_policy_ids=POLICIES,
        control_kind=HISTORY_ABLATION_CONTROL) for pair in _pairs())
    dosed = [example for example in examples if example.changed_event_rows]
    assert dosed
    for example in examples:
        source = example.source
        assert sorted(row.tobytes() for row in example.transformed_events) \
            == sorted(row.tobytes() for row in source.tensors.events)
        assert np.array_equal(
            example.transformed_count_labels, source.count_labels)
        validate_control_example(example)


def test_label_control_preserves_every_hard_margin_and_has_natural_dose():
    examples = tuple(build_control_example(
        pair, behavior_policy_ids=POLICIES,
        control_kind=LABEL_PERMUTATION_CONTROL) for pair in _pairs())
    assert sum(example.changed_label_cells for example in examples) > 0
    for example in examples:
        source = example.source
        labels = example.transformed_count_labels
        active = source.active_mask
        assert np.array_equal(labels.sum(axis=1),
                              source.count_labels.sum(axis=1))
        assert np.array_equal(labels.sum(axis=0),
                              source.count_labels.sum(axis=0))
        assert np.all(labels[active] >= source.tensors.count_minimums[active])
        assert np.all(labels[active] <= source.tensors.count_maximums[active])
        validate_control_example(example)


def test_controls_collate_train_and_cannot_masquerade_or_mix():
    pairs = _pairs(decisions=4)
    history = tuple(build_control_example(
        pair, behavior_policy_ids=POLICIES,
        control_kind=HISTORY_ABLATION_CONTROL) for pair in pairs)
    labels = tuple(build_control_example(
        pair, behavior_policy_ids=POLICIES,
        control_kind=LABEL_PERMUTATION_CONTROL) for pair in pairs)
    history_batch = collate_control_examples(history)
    model = new_from_scratch_model(495023836)
    with pytest.raises(BeliefTrainerError, match="inference-only"):
        train_epoch(
            model, new_b2_optimizer(model), (history_batch,), epoch=1)
    calibration_history = tuple(build_control_example(
        pair, behavior_policy_ids=POLICIES,
        control_kind=HISTORY_ABLATION_CONTROL)
                                for pair in _pairs(
                                    decisions=4, split="calibration"))
    assert evaluate_calibration_loss_nanonats(
        model, (collate_control_examples(calibration_history),)) > 0

    label_batch = collate_control_examples(labels)
    receipt = train_epoch(
        model, new_b2_optimizer(model), (label_batch,), epoch=1)
    assert receipt.control_kind == LABEL_PERMUTATION_CONTROL
    assert receipt.batch_schema \
        == "belief-v1-negative-control-training-batch-v1"
    with pytest.raises(BeliefControlError, match="mixes"):
        collate_control_examples((history[0], labels[1]))

    changed = history[0].transformed_events.copy()
    changed[0, 0] += 1
    with pytest.raises(BeliefControlError, match="derivation"):
        validate_control_example(replace(
            history[0], transformed_events=changed))
