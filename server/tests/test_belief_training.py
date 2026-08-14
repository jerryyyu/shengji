"""Privileged BELIEF-V1 training boundary and batching tests."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import numpy as np
import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_training import (
    BeliefTrainingError,
    build_training_example,
    collate_training_examples,
    training_batch_loss,
    validate_training_example,
)


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=10401, plays=5):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    return (rnd, build_actor_observation(rnd, rnd.turn, transcript),
            build_belief_targets(rnd, rnd.turn), transcript)


def _example(seed, decision_index=5):
    rnd, actor, target, _ = _state(seed, plays=decision_index)
    return actor, target, build_training_example(
        actor, target, round_seed=seed, decision_index=decision_index,
        actor_seat=rnd.turn, behavior_policy_ids=POLICIES)


def test_labels_are_privileged_bounded_and_separate_from_tensors():
    actor, target, example = _example(10403)
    validate_training_example(actor, target, example)
    assert example.privileged_targets_consumed is True
    assert example.runtime_artifact is False
    assert example.count_labels.shape == (54, 4)
    assert example.active_mask.shape == (54, 4)
    assert np.all(example.count_labels[~example.active_mask] == -1)
    assert np.all(example.count_labels[example.active_mask]
                  >= example.tensors.count_minimums[example.active_mask])
    assert np.all(example.count_labels[example.active_mask]
                  <= example.tensors.count_maximums[example.active_mask])


def test_public_twins_share_tensors_but_not_privileged_labels():
    rnd, actor, target, transcript = _state(10405)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    changed = copy.deepcopy(rnd)
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    twin_actor = build_actor_observation(changed, rnd.turn, transcript)
    twin_target = build_belief_targets(changed, rnd.turn)
    first = build_training_example(
        actor, target, round_seed=10405, decision_index=5,
        actor_seat=rnd.turn, behavior_policy_ids=POLICIES)
    second = build_training_example(
        twin_actor, twin_target, round_seed=10405, decision_index=5,
        actor_seat=rnd.turn, behavior_policy_ids=POLICIES)
    assert first.tensors.history_input_sha256 \
        == second.tensors.history_input_sha256
    assert first.tensors.card_features.tobytes() \
        == second.tensors.card_features.tobytes()
    assert first.privileged_target_sha256 != second.privileged_target_sha256
    assert first.count_labels.tobytes() != second.count_labels.tobytes()


def test_collation_pads_history_and_loss_backpropagates():
    _, _, first = _example(10407, decision_index=2)
    _, _, second = _example(10415, decision_index=9)
    # Fixed seeds are in the same split; this assertion makes the fixture
    # non-vacuous if the split hash ever changes.
    assert first.split == second.split
    batch = collate_training_examples((first, second))
    assert batch.events.shape[0] == 2
    assert batch.events.shape[1] == max(
        len(first.tensors.events), len(second.tensors.events))
    assert batch.event_lengths.tolist() == [
        len(first.tensors.events), len(second.tensors.events)]
    model = new_from_scratch_model(823748771)
    loss = training_batch_loss(model, batch)
    assert loss.ndim == 0 and torch.isfinite(loss)
    loss.backward()
    assert all(parameter.grad is not None for parameter in model.parameters())


def test_training_example_and_batch_refuse_drift_duplicates_and_cross_split():
    actor, target, example = _example(10409)
    labels = example.count_labels.copy()
    index = tuple(np.argwhere(example.active_mask)[0])
    labels[index] = 3
    with pytest.raises(BeliefTrainingError, match="derivation drift"):
        validate_training_example(
            actor, target, replace(example, count_labels=labels))
    with pytest.raises(BeliefTrainingError, match="duplicate"):
        collate_training_examples((example, example))
    other = None
    for seed in range(10411, 10500):
        candidate = _example(seed)[2]
        if candidate.split != example.split:
            other = candidate
            break
    assert other is not None
    with pytest.raises(BeliefTrainingError, match="crosses data splits"):
        collate_training_examples((example, other))
    forged = replace(example, count_labels=labels)
    with pytest.raises(BeliefTrainingError, match="label/bound"):
        collate_training_examples((forged,))
