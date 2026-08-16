"""Portable checkpoint and device-neutral V2 cohort mechanics tests."""

from __future__ import annotations

import hashlib
from dataclasses import fields, replace

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
    _same_training_device,
    BeliefV2AcceleratorError,
    TRAINING_TENSOR_FIELDS,
    V2TrainingDeviceProfileV1,
    build_training_device_profile,
    canonical_training_device,
    cpu_checkpoint_clone,
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    move_training_batch_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
    validate_training_device_profile,
)
from shengji.rl.belief_v2_device_qualification import (
    build_qualification_plan,
    derive_qualification_result,
)
from shengji.rl.belief_v2_device_runner import execute_qualification_arm


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


def test_resolved_mps_zero_matches_the_unindexed_canonical_request():
    assert _same_training_device(
        torch.device("mps:0"), torch.device("mps"))
    assert _same_training_device(
        torch.device("cpu"), torch.device("cpu"))
    assert _same_training_device(
        torch.device("cuda:0"), torch.device("cuda:0"))
    assert not _same_training_device(
        torch.device("cuda:1"), torch.device("cuda:0"))
    assert not _same_training_device(
        torch.device("cpu"), torch.device("mps"))


@pytest.mark.skipif(
    not torch.backends.mps.is_built()
    or not torch.backends.mps.is_available(),
    reason="requires an available MPS device",
)
def test_mps_deterministic_training_path_completes_without_fallback():
    models = _models()
    move_models_to_device(models, device="mps")
    optimizers = tuple(new_v2_optimizer(model) for model in models)
    receipts = train_v2_cohort_epoch_stream(
        models, optimizers, iter((_batch(),)), epoch=1, device="mps")
    assert len(receipts) == len(models)
    assert all(receipt.decision_count == 2 for receipt in receipts)
    assert all(model_state_sha256(cpu_checkpoint_clone(model))
               == portable_model_state_sha256(model)
               for model in models)


def test_accelerator_profile_binds_physical_identity_and_capability_shape(
        monkeypatch):
    monkeypatch.setattr(
        "shengji.rl.belief_v2_accelerator.available_training_accelerators",
        lambda: ("mps",))
    with pytest.raises(BeliefV2AcceleratorError,
                       match="no available accelerator"):
        build_training_device_profile("cpu")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_accelerator.available_training_accelerators",
        lambda: ())
    cpu = build_training_device_profile("cpu")
    assert cpu.requested_device == "cpu"
    assert cpu.device_type == "cpu"
    assert cpu.device_index is None
    assert cpu.total_memory_bytes > 0
    validate_training_device_profile(cpu)
    with pytest.raises(BeliefV2AcceleratorError,
                       match="device profile identity"):
        validate_training_device_profile(replace(cpu, device_index=0))

    mps = V2TrainingDeviceProfileV1(
        requested_device="mps", device_type="mps", device_index=None,
        hardware_name="Apple-arm64-test", total_memory_bytes=16 * 1024**3,
        runtime_version="macOS-test", compute_capability_major=None,
        compute_capability_minor=None)
    validate_training_device_profile(mps)
    assert len(mps.sha256()) == 64
    with pytest.raises(BeliefV2AcceleratorError,
                       match="device profile identity"):
        validate_training_device_profile(replace(
            mps, hardware_name=""))
    with pytest.raises(BeliefV2AcceleratorError,
                       match="device profile identity"):
        validate_training_device_profile(replace(
            mps, compute_capability_major=8,
            compute_capability_minor=0))

    cuda = replace(
        mps, requested_device="cuda:0", device_type="cuda",
        device_index=0, hardware_name="NVIDIA-test",
        runtime_version="CUDA-test", compute_capability_major=8,
        compute_capability_minor=9)
    validate_training_device_profile(cuda)
    with pytest.raises(BeliefV2AcceleratorError,
                       match="device profile identity"):
        validate_training_device_profile(replace(
            cuda, device_index=1))


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


def test_runnable_qualification_cpu_arm_uses_exact_selected_batches():
    source = _batch()
    batches = tuple(replace(
        source, decision_keys=tuple(hashlib.sha256(
            f"qualification-{batch}-{index}".encode()).hexdigest()
            for index, _ in enumerate(source.decision_keys)))
                    for batch in range(32))
    plan = build_qualification_plan(
        execution_git="a" * 40, candidate_device="mps",
        batch_decision_keys=tuple(batch.decision_keys for batch in batches),
        batch_active_label_counts=tuple(
            int(batch.active_mask.sum()) for batch in batches),
        host_memory_cap_bytes=64 * 1024**3,
        device_memory_cap_bytes=16 * 1024**3)
    arm = execute_qualification_arm(
        plan, arm_index=0, selected_batches=batches)
    assert arm.device == "cpu"
    assert arm.actual_device == "cpu"
    assert arm.fallback_used is False
    assert arm.completed is True
    assert arm.decision_count == sum(
        len(batch.decision_keys) for batch in batches)
    assert arm.active_label_count == sum(
        int(batch.active_mask.sum()) for batch in batches)
    assert len(arm.member_checkpoint_sha256s) == 8
    assert len(arm.member_epoch_receipt_sha256s) == 8


def test_runnable_cpu_only_qualification_repeats_and_selects_cpu():
    source = _batch()
    batches = tuple(replace(
        source, decision_keys=tuple(hashlib.sha256(
            f"cpu-only-{batch}-{index}".encode()).hexdigest()
            for index, _ in enumerate(source.decision_keys)))
                    for batch in range(32))
    plan = build_qualification_plan(
        execution_git="a" * 40, candidate_device="cpu",
        batch_decision_keys=tuple(batch.decision_keys for batch in batches),
        batch_active_label_counts=tuple(
            int(batch.active_mask.sum()) for batch in batches),
        host_memory_cap_bytes=64 * 1024**3,
        device_memory_cap_bytes=0)
    arms = tuple(execute_qualification_arm(
        plan, arm_index=index, selected_batches=batches)
                 for index in range(len(plan.arm_order)))
    result = derive_qualification_result(plan, arms)
    assert result.selected_device == "cpu"
    assert result.accelerator_retained is False
    assert result.aggregate_cpu_wall_nanoseconds > 0
    assert result.aggregate_candidate_wall_nanoseconds == 0
    assert result.wall_reduction_ppb == 0
