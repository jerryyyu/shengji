from __future__ import annotations

import copy

import pytest
import torch

from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_dataset import join_advantage_examples
from shengji.rl.world_afterstate_v1_model import (
    new_world_afterstate_advantage_model)
from shengji.rl.world_afterstate_v1_training import (
    AUTHORITY, AdvantageTrainingConfigV1,
    WorldAfterstateV1TrainingError, collate_training_pairs,
    evaluate_selection_loss_nano, model_state_sha256, new_optimizer,
    root_balanced_loss, select_common_epoch, train_epoch)

from test_world_afterstate_v1_dataset import _population


def _config(**changes):
    values = {
        "learning_rate_ppb": 1_000_000,
        "weight_decay_ppb": 10_000_000,
        "gradient_norm_milli": 1_000,
        "max_epochs": 12,
        "early_stop_patience": 3,
        "minimum_improvement_nanoloss": 10,
    }
    values.update(changes)
    return AdvantageTrainingConfigV1(**values)


def _joined():
    return list(join_advantage_examples(_population()))


def _batch(split="fit"):
    return collate_training_pairs(_joined(), split=split)


def test_training_epoch_is_deterministic_and_root_balanced():
    torch.set_num_threads(1)
    config = _config()
    first = new_world_afterstate_advantage_model(
        41, CAPACITY_SHAPES["small"])
    second = new_world_afterstate_advantage_model(
        41, CAPACITY_SHAPES["small"])
    before = model_state_sha256(first)
    first_receipt = train_epoch(
        first, new_optimizer(first, config), (_batch(),), epoch=1,
        config=config)
    second_receipt = train_epoch(
        second, new_optimizer(second, config), (_batch(),), epoch=1,
        config=config)
    assert first_receipt == second_receipt
    assert first_receipt.root_count == 2
    assert first_receipt.pair_count == 8
    assert first_receipt.model_state_sha256_before == before
    assert first_receipt.model_state_sha256_after != before
    assert first_receipt.payload()["authority"] == AUTHORITY


def test_fit_refuses_selection_and_audit_folds():
    config = _config()
    model = new_world_afterstate_advantage_model(
        42, CAPACITY_SHAPES["small"])
    with pytest.raises(WorldAfterstateV1TrainingError, match="split drift"):
        train_epoch(
            model, new_optimizer(model, config), (_batch("select"),),
            epoch=1, config=config)
    calibration = [
        copy.deepcopy(value) for value in _joined()
    ]
    for value in calibration:
        object.__setattr__(value.pair, "fold", "calibration")
    audit = collate_training_pairs(calibration, split="audit")
    with pytest.raises(WorldAfterstateV1TrainingError, match="split drift"):
        train_epoch(
            model, new_optimizer(model, config), (audit,),
            epoch=1, config=config)


def test_selection_loss_is_nonmutating_and_audit_is_refused():
    model = new_world_afterstate_advantage_model(
        43, CAPACITY_SHAPES["small"])
    before = model_state_sha256(model)
    model.train(True)
    value = evaluate_selection_loss_nano(model, (_batch("select"),))
    assert value >= 0
    assert model.training is True
    assert model_state_sha256(model) == before

    calibration = [copy.deepcopy(value) for value in _joined()]
    for row in calibration:
        object.__setattr__(row.pair, "fold", "calibration")
    audit = collate_training_pairs(calibration, split="audit")
    with pytest.raises(WorldAfterstateV1TrainingError, match="split drift"):
        evaluate_selection_loss_nano(model, (audit,))


def test_batch_requires_complete_contiguous_root_groups():
    rows = _joined()
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="incomplete root"):
        collate_training_pairs(rows[:-1], split="fit")
    interleaved = rows[::2] + rows[1::2]
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="split root"):
        collate_training_pairs(interleaved, split="fit")


def test_loss_weights_roots_equally_not_pairs():
    rows = []
    source = _population()
    state_ids = sorted({row.evaluation_outcome.state_group_id
                        for row in source})
    for row in source:
        state = row.evaluation_outcome.state_group_id
        if state == state_ids[0] and row.evaluation_outcome.candidate_index == 2:
            continue
        rows.append(row)
    batch = collate_training_pairs(
        list(join_advantage_examples(rows)), split="fit")
    predictions = torch.zeros_like(batch.tensors.targets)
    # State A has target 1 twice: Smooth-L1 root mean = 0.5.
    # State B has target 1 twice and 2 twice: root mean = 1.0.
    # Root-balanced mean is 0.75; the six-row mean would be 5/6.
    assert float(root_balanced_loss(predictions, batch)) == 0.75


def test_common_epoch_is_cohort_level_and_patience_bound():
    config = _config(
        early_stop_patience=2, minimum_improvement_nanoloss=10)
    losses = tuple((100, 80, 85, 84, 60) for _ in range(8))
    decision = select_common_epoch(losses, config=config)
    assert decision.selected_epoch == 2
    assert decision.stop_epoch == 4
    assert decision.stopped_for_patience is True
    assert decision.cohort_mean_loss_nano == (100, 80, 85, 84)
    assert decision.payload()["authority"] == AUTHORITY
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="cohort drift"):
        select_common_epoch(losses[:-1], config=config)


def test_config_batch_and_receipt_fields_are_load_bearing():
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="config drift"):
        _config(early_stop_patience=13).validate()
    batch = _batch()
    forged = copy.copy(batch)
    object.__setattr__(forged, "replicates", (0,) * len(batch.replicates))
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="sibling binding drift"):
        forged.validate()
    forged_key = copy.copy(batch)
    object.__setattr__(forged_key, "pair_keys",
                       ("forged",) + batch.pair_keys[1:])
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="sibling binding drift"):
        forged_key.validate()
    forged_tensor = copy.copy(batch)
    object.__setattr__(forged_tensor, "candidate_tensor_sha256s",
                       batch.incumbent_tensor_sha256s)
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="tensor binding drift"):
        forged_tensor.validate()
    forged_target = copy.copy(batch)
    object.__setattr__(forged_target, "target_levels",
                       (0,) * len(batch.target_levels))
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="sibling identity drift"):
        forged_target.validate()
    mutated_tensor = _batch()
    mutated_tensor.tensors.candidate.public[0, 0] += 1.0
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="tensor binding drift"):
        mutated_tensor.validate()
    mutated_target = _batch()
    mutated_target.tensors.targets[0] += 0.5
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="sibling identity drift"):
        mutated_target.validate()

    config = _config()
    model = new_world_afterstate_advantage_model(
        44, CAPACITY_SHAPES["small"])
    receipt = train_epoch(
        model, new_optimizer(model, config), (batch,), epoch=1,
        config=config)
    forged_receipt = copy.copy(receipt)
    object.__setattr__(forged_receipt, "model_state_sha256_after",
                       receipt.model_state_sha256_before)
    with pytest.raises(WorldAfterstateV1TrainingError,
                       match="epoch receipt drift"):
        forged_receipt.payload()
