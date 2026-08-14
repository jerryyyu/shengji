"""Canonical BELIEF-V1 checkpoint package and reopener tests."""

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
from shengji.rl.belief_checkpoint import (
    BeliefCheckpointError,
    build_model_checkpoint,
    reopen_model_checkpoint,
    validate_model_checkpoint,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import (
    model_state_sha256,
    new_b2_optimizer,
    train_epoch,
)
from shengji.rl.belief_training import (
    build_training_example,
    collate_training_examples,
)


POLICIES = ("mc-s0-report-lcb",)


def _trained():
    seed = b2_split_round_seeds("train")[0]
    captured = _capture_with_policies(
        seed, POLICIES[0], champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])
    batch = collate_training_examples(tuple(build_training_example(
        pair, behavior_policy_ids=POLICIES)
                                            for pair in captured.pairs[:3]))
    model = new_from_scratch_model(495023836)
    receipt = train_epoch(
        model, new_b2_optimizer(model), (batch,), epoch=1)
    return model, receipt


def test_checkpoint_round_trip_is_byte_exact_and_target_free():
    model, receipt = _trained()
    checkpoint = build_model_checkpoint(
        model, initialization_seed=495023836, selected_epoch=1,
        final_epoch_receipt=receipt)
    validate_model_checkpoint(
        checkpoint, final_epoch_receipt=receipt)
    reopened = reopen_model_checkpoint(
        checkpoint, final_epoch_receipt=receipt)
    assert model_state_sha256(reopened) == model_state_sha256(model)
    assert all(torch.equal(left, right) for left, right in zip(
        reopened.state_dict().values(), model.state_dict().values(),
        strict=True))
    assert b'"contains_privileged_targets":false' in checkpoint.manifest_bytes
    assert b'"contains_corpus_rows":false' in checkpoint.manifest_bytes


def test_checkpoint_refuses_parameter_manifest_receipt_and_epoch_drift():
    model, receipt = _trained()
    checkpoint = build_model_checkpoint(
        model, initialization_seed=495023836, selected_epoch=1,
        final_epoch_receipt=receipt)
    changed = bytearray(checkpoint.parameter_blocks[0])
    changed[0] ^= 1
    with pytest.raises(BeliefCheckpointError, match="parameter binding"):
        validate_model_checkpoint(replace(
            checkpoint, parameter_blocks=(bytes(changed),
                                          *checkpoint.parameter_blocks[1:])),
                                  final_epoch_receipt=receipt)
    with pytest.raises(BeliefCheckpointError, match="identity/authority"):
        validate_model_checkpoint(replace(
            checkpoint, manifest_bytes=checkpoint.manifest_bytes.replace(
                b'"deployment_authorized":false',
                b'"deployment_authorized":true')),
                                  final_epoch_receipt=receipt)
    with pytest.raises(BeliefCheckpointError, match="identity/authority"):
        validate_model_checkpoint(
            checkpoint, final_epoch_receipt=replace(receipt, epoch=2))
