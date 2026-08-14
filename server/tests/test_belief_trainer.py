"""Deterministic B2 optimizer, loss, and checkpoint mechanics tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import (
    BeliefTrainerError,
    evaluate_calibration_loss_nanonats,
    evaluate_calibration_cohort_stream_nanonats,
    evaluate_calibration_stream_nanonats,
    model_state_sha256,
    new_b2_optimizer,
    train_epoch,
    train_cohort_epoch_stream,
    train_epoch_stream,
)
from shengji.rl.belief_training import (
    build_training_example,
    collate_training_examples,
)


POLICIES = ("mc-s0-report-lcb",)


def _batch(split="train", decisions=3, seed_index=0):
    seed = b2_split_round_seeds(split)[seed_index]
    captured = _capture_with_policies(
        seed, POLICIES[0], champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])
    examples = tuple(build_training_example(
        pair, behavior_policy_ids=POLICIES)
                     for pair in captured.pairs[:decisions])
    return collate_training_examples(examples)


def test_same_seed_batch_and_optimizer_are_bit_reproducible():
    batch = _batch()
    first = new_from_scratch_model(495023836)
    second = new_from_scratch_model(495023836)
    first_receipt = train_epoch(
        first, new_b2_optimizer(first), (batch,), epoch=1)
    second_receipt = train_epoch(
        second, new_b2_optimizer(second), (batch,), epoch=1)
    assert first_receipt == second_receipt
    assert first_receipt.model_state_sha256_before \
        != first_receipt.model_state_sha256_after
    assert model_state_sha256(first) == model_state_sha256(second)
    assert all(torch.equal(left, right) for left, right in zip(
        first.state_dict().values(), second.state_dict().values(), strict=True))


def test_calibration_is_weighted_finite_and_does_not_mutate_model():
    batch = _batch(split="calibration")
    model = new_from_scratch_model(847673502)
    before = model_state_sha256(model)
    value = evaluate_calibration_loss_nanonats(model, (batch,))
    assert type(value) is int and value > 0
    assert model_state_sha256(model) == before


def test_trainer_refuses_optimizer_split_duplicate_and_nonfinite_drift():
    train = _batch()
    model = new_from_scratch_model(1041799603)
    optimizer = new_b2_optimizer(model)
    optimizer.param_groups[0]["lr"] = 1.0
    with pytest.raises(BeliefTrainerError, match="configuration"):
        train_epoch(model, optimizer, (train,), epoch=1)
    calibration = _batch(split="calibration")
    with pytest.raises(BeliefTrainerError, match="authority/split"):
        train_epoch(model, new_b2_optimizer(model), (calibration,), epoch=1)
    with pytest.raises(BeliefTrainerError, match="duplicate"):
        train_epoch(model, new_b2_optimizer(model), (train, train), epoch=1)

    bad_labels = train.count_labels.clone()
    active_index = tuple(int(value)
                         for value in train.active_mask.nonzero()[0])
    bad_labels[active_index] = 99
    with pytest.raises(BeliefTrainerError, match="batch loss refused"):
        train_epoch(model, new_b2_optimizer(model),
                    (replace(train, count_labels=bad_labels),), epoch=1)


def test_streaming_epoch_and_calibration_match_materialized_mechanics():
    train_batches = (_batch(decisions=2, seed_index=0),
                     _batch(decisions=2, seed_index=1))
    materialized = new_from_scratch_model(495023836)
    streamed = new_from_scratch_model(495023836)
    expected = train_epoch(
        materialized, new_b2_optimizer(materialized), train_batches, epoch=1)
    actual = train_epoch_stream(
        streamed, new_b2_optimizer(streamed), iter(train_batches), epoch=1)
    assert actual == expected
    assert model_state_sha256(streamed) == model_state_sha256(materialized)

    calibration = (_batch(split="calibration", decisions=2, seed_index=0),
                   _batch(split="calibration", decisions=2, seed_index=1))
    assert evaluate_calibration_stream_nanonats(
        streamed, iter(calibration)) == evaluate_calibration_loss_nanonats(
            streamed, calibration)


def test_streaming_trainer_refuses_empty_and_cross_batch_duplicates():
    model = new_from_scratch_model(1041799603)
    with pytest.raises(BeliefTrainerError, match="population drift"):
        train_epoch_stream(
            model, new_b2_optimizer(model), iter(()), epoch=1)
    train = _batch(decisions=2)
    with pytest.raises(BeliefTrainerError, match="duplicate"):
        train_epoch_stream(
            model, new_b2_optimizer(model), iter((train, train)), epoch=1)
    with pytest.raises(BeliefTrainerError, match="mutated model"):
        evaluate_calibration_stream_nanonats(model, iter(()))


def test_cohort_stream_matches_individual_member_mechanics():
    batches = (_batch(decisions=2, seed_index=0),
               _batch(decisions=2, seed_index=1))
    seeds = (495023836, 847673502, 1041799603, 588875658,
             442958256, 517235703, 1114290105, 823748771)
    models = tuple(new_from_scratch_model(seed) for seed in seeds)
    optimizers = tuple(new_b2_optimizer(model) for model in models)
    comparison = new_from_scratch_model(seeds[0])
    expected = train_epoch_stream(
        comparison, new_b2_optimizer(comparison), iter(batches), epoch=1)
    receipts = train_cohort_epoch_stream(
        models, optimizers, iter(batches), epoch=1)
    assert receipts[0] == expected
    assert model_state_sha256(models[0]) == model_state_sha256(comparison)

    calibration = (_batch(split="calibration", decisions=2, seed_index=0),
                   _batch(split="calibration", decisions=2, seed_index=1))
    values = evaluate_calibration_cohort_stream_nanonats(
        models, iter(calibration))
    assert len(values) == 8
    assert values[0] == evaluate_calibration_loss_nanonats(
        models[0], calibration)
