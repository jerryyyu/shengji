from __future__ import annotations

import copy

import pytest
import torch

from shengji.rl.world_afterstate_v1_controls import (
    AUTHORITY, WorldAfterstateV1ControlError,
    action_association_permutation, complete_world_shuffle,
    collate_control_training_pairs, identical_successor_control,
    label_permutation,
    validate_control_evidence)
from shengji.rl.world_afterstate_v1_dataset import join_advantage_examples
from shengji.rl.world_afterstate_v1_evaluation import collate_inference_pairs
from shengji.rl.world_afterstate_v1_model import (
    new_world_afterstate_advantage_model, successor_tensor_sha256)
from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_training import (
    AdvantageTrainingConfigV1, new_optimizer, train_epoch)

from test_world_afterstate_v1_dataset import _population, _row


def _joined():
    return list(join_advantage_examples(_population()))


def test_identical_successor_is_exact_for_every_pair_and_measured():
    natural = _joined()
    rows, evidence = identical_successor_control(natural)
    assert len(rows) == len(natural)
    assert evidence["dose_ppm"] == 1_000_000
    assert evidence["changed_count"] == len(natural)
    assert evidence["authority"] == AUTHORITY
    validate_control_evidence(evidence)
    assert all(successor_tensor_sha256(row.incumbent)
               == successor_tensor_sha256(row.candidate) for row in rows)


def test_action_association_rotates_within_root_at_full_dose():
    natural = _joined()
    rows, evidence = action_association_permutation(natural)
    assert evidence["dose_ppm"] == 1_000_000
    assert [row.target_levels for row in rows] \
        == [value.pair.advantage_levels for value in natural]
    assert all(row.incumbent_donor_key.startswith(
        f"{row.natural.pair.state_group_id}:") for row in rows)


def test_label_permutation_preserves_inputs_and_requires_real_dose():
    rows = []
    for state_index, state in enumerate(("a", "b", "c", "d")):
        for candidate in range(3):
            for replicate in range(2):
                rows.append(_row(
                    state, candidate, replicate,
                    100 + replicate + candidate * (state_index + 1)))
    natural = list(join_advantage_examples(rows))
    controlled, evidence = label_permutation(natural)
    assert evidence["dose_ppm"] == 1_000_000
    assert sorted(row.target_levels for row in controlled) \
        == sorted(value.pair.advantage_levels for value in natural)
    assert all(row.incumbent_tensor_sha256
               == successor_tensor_sha256(row.natural.example.incumbent.tensors)
               and row.candidate_tensor_sha256
               == successor_tensor_sha256(row.natural.example.candidate.tensors)
               for row in controlled)

    with pytest.raises(WorldAfterstateV1ControlError,
                       match="below its minimum dose"):
        label_permutation(_joined())


def test_complete_world_shuffle_changes_only_world_channel():
    natural = _joined()
    unique = [natural[index] for index in range(0, len(natural), 2)]
    batch = collate_inference_pairs(
        state_group_ids=[value.pair.state_group_id for value in unique],
        candidate_indexes=[value.pair.candidate_index for value in unique],
        incumbent_successor_sha256s=[
            value.pair.incumbent_successor_sha256 for value in unique],
        candidate_successor_sha256s=[
            value.pair.candidate_successor_sha256 for value in unique],
        incumbent_tensors=[value.example.incumbent.tensors for value in unique],
        candidate_tensors=[value.example.candidate.tensors for value in unique])
    shuffled, evidence = complete_world_shuffle(batch)
    assert evidence["changed_count"] > 0
    assert torch.equal(batch.incumbent.public, shuffled.incumbent.public)
    assert torch.equal(batch.candidate.history, shuffled.candidate.history)
    assert torch.equal(batch.incumbent.perspective,
                       shuffled.incumbent.perspective)
    assert not torch.equal(batch.candidate.world, shuffled.candidate.world)


def test_control_row_tensor_binding_has_teeth():
    rows, evidence = identical_successor_control(_joined())
    forged = copy.copy(rows[0])
    object.__setattr__(forged, "candidate_tensor_sha256", "f" * 64)
    with pytest.raises(WorldAfterstateV1ControlError,
                       match="tensor binding drift"):
        forged.validate()
    forged_evidence = copy.deepcopy(evidence)
    forged_evidence["changed_count"] -= 1
    with pytest.raises(WorldAfterstateV1ControlError,
                       match="dose reconstruction drift"):
        validate_control_evidence(forged_evidence)


def test_named_controls_reach_optimizer_as_distinct_bound_populations():
    natural = _joined()
    identical, _ = identical_successor_control(natural)
    association, _ = action_association_permutation(natural)
    varied_rows = []
    for state_index, state in enumerate(("a", "b", "c", "d")):
        for candidate in range(3):
            for replicate in range(2):
                varied_rows.append(_row(
                    state, candidate, replicate,
                    100 + replicate + candidate * (state_index + 1)))
    labels, _ = label_permutation(
        list(join_advantage_examples(varied_rows)))
    controls = (identical, association, labels)
    config = AdvantageTrainingConfigV1(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=2,
        early_stop_patience=1,
        minimum_improvement_nanoloss=0)
    receipts = []
    models = []
    batches = []
    for index, controlled in enumerate(controls):
        batch = collate_control_training_pairs(controlled, split="fit")
        batches.append(batch)
        model = new_world_afterstate_advantage_model(
            700 + index, CAPACITY_SHAPES["small"])
        receipt = train_epoch(
            model, new_optimizer(model, config), (batch,), epoch=1,
            config=config)
        receipts.append(receipt)
        models.append(model)
    assert len({receipt.population_sha256 for receipt in receipts}) == 3
    assert batches[0].candidate_tensor_sha256s == tuple(
        row.candidate_tensor_sha256 for row in identical)
    assert batches[1].candidate_tensor_sha256s == tuple(
        row.candidate_tensor_sha256 for row in association)
    assert batches[2].target_levels == tuple(
        row.target_levels for row in labels)
    assert batches[2].target_levels != tuple(
        row.natural.pair.advantage_levels for row in labels)

    identical_batch = collate_control_training_pairs(
        identical, split="select")
    with torch.no_grad():
        prediction = models[0](
            identical_batch.tensors.incumbent,
            identical_batch.tensors.candidate)
    assert torch.equal(prediction, torch.zeros_like(prediction))
