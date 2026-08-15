"""Portable checkpoint and device-neutral V2 cohort mechanics tests."""

from __future__ import annotations

from dataclasses import fields

import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import (
    evaluate_calibration_cohort_stream_nanonats,
    model_state_sha256,
    new_b2_optimizer,
    train_cohort_epoch_stream,
)
from shengji.rl.belief_training import (
    build_training_example,
    collate_training_examples,
)
from shengji.rl.belief_v2_accelerator import (
    BeliefV2AcceleratorError,
    TRAINING_TENSOR_FIELDS,
    canonical_training_device,
    cpu_checkpoint_clone,
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    move_training_batch_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)


POLICIES = ("mc-s0-report-lcb",)


@pytest.fixture(autouse=True)
def _deterministic_algorithms():
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(previous)


def _batch(split: str = "train"):
    seed = b2_split_round_seeds(split)[0]
    captured = _capture_with_policies(
        seed, POLICIES[0], champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])
    examples = tuple(build_training_example(
        pair, behavior_policy_ids=POLICIES)
                     for pair in captured.pairs[:2])
    return collate_training_examples(examples)


def _models():
    return tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)


def test_device_names_require_explicit_portable_identity():
    assert canonical_training_device("cpu") == "cpu"
    assert canonical_training_device("mps") == "mps"
    assert canonical_training_device("cuda:0") == "cuda:0"
    for value in ("", "cuda", "cpu:0", "mps:0", "metal", True):
        with pytest.raises(BeliefV2AcceleratorError):
            canonical_training_device(value)


def test_portable_hash_and_cpu_export_equal_unchanged_v1_checkpoint():
    model = new_from_scratch_model(COHORT_SEEDS[0])
    assert portable_model_state_sha256(model) == model_state_sha256(model)
    clone = cpu_checkpoint_clone(model)
    assert clone is not model
    assert model_state_sha256(clone) == model_state_sha256(model)
    assert all(left.data_ptr() != right.data_ptr()
               for left, right in zip(
                   model.parameters(), clone.parameters(), strict=True))


def test_batch_transfer_moves_every_and_only_tensor_field():
    batch = _batch()
    moved = move_training_batch_to_device(batch, device="cpu")
    tensor_fields = tuple(
        field.name for field in fields(batch)
        if isinstance(getattr(batch, field.name), torch.Tensor))
    assert tensor_fields == TRAINING_TENSOR_FIELDS
    assert all(getattr(moved, name).device.type == "cpu"
               for name in tensor_fields)
    assert moved.decision_keys == batch.decision_keys
    assert moved.split == batch.split
    assert moved.control_kind == batch.control_kind


def test_v2_cpu_path_is_receipt_and_checkpoint_identical_to_v1():
    batch = _batch()
    expected_models = _models()
    actual_models = _models()
    expected = train_cohort_epoch_stream(
        expected_models,
        tuple(new_b2_optimizer(model) for model in expected_models),
        iter((batch,)), epoch=1)
    move_models_to_device(actual_models, device="cpu")
    actual = train_v2_cohort_epoch_stream(
        actual_models,
        tuple(new_v2_optimizer(model) for model in actual_models),
        iter((batch,)), epoch=1, device="cpu")
    assert actual == expected
    assert tuple(portable_model_state_sha256(model)
                 for model in actual_models) \
        == tuple(model_state_sha256(model) for model in expected_models)

    calibration = _batch("calibration")
    expected_values = evaluate_calibration_cohort_stream_nanonats(
        expected_models, iter((calibration,)))
    actual_values = evaluate_v2_calibration_cohort_stream_nanonats(
        actual_models, iter((calibration,)), device="cpu")
    assert actual_values == expected_values
