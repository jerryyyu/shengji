from __future__ import annotations

import copy

import pytest
import torch

from shengji.rl.world_afterstate import (
    OUTCOME_CLASSES, WorldAfterstateExampleV0, WorldAfterstateTensorsV0)
from shengji.rl.world_afterstate_model import (
    CAPACITY_SHAPES, new_world_afterstate_model)
from shengji.rl.world_afterstate_training import (
    TRAINING_AUTHORITY, WorldAfterstateTrainingError,
    WorldAfterstateTrainingConfigV0, collate_training_examples,
    evaluate_calibration_nll_nanonats, model_state_sha256, new_optimizer,
    select_common_epoch, train_epoch)


def _config(**changes):
    values = {
        "learning_rate_ppb": 1_000_000,
        "weight_decay_ppb": 10_000_000,
        "gradient_norm_milli": 1_000,
        "max_epochs": 12,
        "early_stop_patience": 3,
        "minimum_improvement_nanonats": 10,
    }
    values.update(changes)
    return WorldAfterstateTrainingConfigV0(**values)


def _example(index: int) -> WorldAfterstateExampleV0:
    from shengji.rl.world_afterstate import (
        HISTORY_EVENT_DIM, N_CARDS, PERSPECTIVE_DIM, PUBLIC_DIM,
        WORLD_RECEIVERS)
    history = torch.zeros((index % 3, HISTORY_EVENT_DIM), dtype=torch.float32)
    world = torch.zeros((WORLD_RECEIVERS, N_CARDS), dtype=torch.float32)
    world[0, index % N_CARDS] = 0.5
    tensors = WorldAfterstateTensorsV0(
        public=torch.zeros(PUBLIC_DIM, dtype=torch.float32).numpy(),
        history=history.numpy(), world=world.numpy(),
        perspective=torch.tensor([1.0, 0.0], dtype=torch.float32).numpy())
    return WorldAfterstateExampleV0(
        tensors=tensors, signed_level_category=index % OUTCOME_CLASSES,
        successor_sha256=f"{index:064x}")


def _batch(split="train"):
    return collate_training_examples(
        ["example-0", "example-1"], [_example(0), _example(1)],
        split=split)


def test_training_epoch_is_reproducible_and_score_free():
    config = _config()
    first = new_world_afterstate_model(71, CAPACITY_SHAPES["small"])
    second = new_world_afterstate_model(71, CAPACITY_SHAPES["small"])
    before = model_state_sha256(first)
    first_receipt = train_epoch(
        first, new_optimizer(first, config), (_batch(),), epoch=1,
        config=config)
    second_receipt = train_epoch(
        second, new_optimizer(second, config), (_batch(),), epoch=1,
        config=config)
    assert first_receipt == second_receipt
    assert before == first_receipt.model_state_sha256_before
    assert before != first_receipt.model_state_sha256_after
    first_receipt.validate()
    assert first_receipt.payload()["authority"] == TRAINING_AUTHORITY
    assert "signed_level_category" not in first_receipt.payload()


def test_training_refuses_calibration_and_duplicate_examples():
    config = _config()
    model = new_world_afterstate_model(72, CAPACITY_SHAPES["small"])
    with pytest.raises(WorldAfterstateTrainingError, match="split drift"):
        train_epoch(model, new_optimizer(model, config),
                    (_batch("calibration"),), epoch=1, config=config)
    with pytest.raises(WorldAfterstateTrainingError, match="split drift"):
        train_epoch(model, new_optimizer(model, config),
                    (_batch("report"),), epoch=1, config=config)
    batch = _batch()
    with pytest.raises(WorldAfterstateTrainingError, match="duplicate"):
        train_epoch(model, new_optimizer(model, config),
                    (batch, copy.deepcopy(batch)), epoch=1, config=config)


def test_calibration_evaluation_does_not_mutate_model():
    model = new_world_afterstate_model(73, CAPACITY_SHAPES["small"])
    before = model_state_sha256(model)
    model.train(True)
    value = evaluate_calibration_nll_nanonats(
        model, (_batch("calibration"),))
    assert value > 0
    assert model.training is True
    assert model_state_sha256(model) == before


def test_common_epoch_is_cohort_level_and_patience_bound():
    config = _config(early_stop_patience=2,
                     minimum_improvement_nanonats=10)
    rows = tuple((100, 80, 85, 84, 60) for _ in range(8))
    decision = select_common_epoch(rows, config=config)
    assert decision.selected_epoch == 2
    assert decision.stop_epoch == 4
    assert decision.stopped_for_patience is True
    assert decision.cohort_mean_loss_nanonats == (100, 80, 85, 84)
    assert decision.payload()["authority"] == TRAINING_AUTHORITY

    with pytest.raises(WorldAfterstateTrainingError, match="cohort drift"):
        select_common_epoch(rows[:-1], config=config)


def test_config_and_batch_fields_are_load_bearing():
    with pytest.raises(WorldAfterstateTrainingError, match="config drift"):
        _config(early_stop_patience=13).validate()
    batch = _batch()
    forged = copy.copy(batch)
    object.__setattr__(forged, "labels", torch.tensor([0, OUTCOME_CLASSES]))
    with pytest.raises(WorldAfterstateTrainingError, match="tensor drift"):
        forged.validate()


def test_epoch_and_common_receipt_fields_are_load_bearing():
    config = _config()
    model = new_world_afterstate_model(74, CAPACITY_SHAPES["small"])
    receipt = train_epoch(
        model, new_optimizer(model, config), (_batch(),), epoch=1,
        config=config)
    forged = copy.copy(receipt)
    object.__setattr__(forged, "model_state_sha256_after",
                       receipt.model_state_sha256_before)
    with pytest.raises(WorldAfterstateTrainingError, match="receipt drift"):
        forged.payload()

    decision = select_common_epoch(
        tuple((100, 90, 95) for _ in range(8)), config=config)
    forged_decision = copy.copy(decision)
    object.__setattr__(forged_decision, "selected_epoch", 0)
    with pytest.raises(WorldAfterstateTrainingError,
                       match="common epoch receipt drift"):
        forged_decision.payload()
