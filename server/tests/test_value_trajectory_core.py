"""End-to-end witnesses for the minimal trajectory Value library."""

from __future__ import annotations

import copy

import numpy as np
import pytest
import torch

from shengji.harvest import rebuild, trajectory
from shengji.harvest.schema import finalize_record
from shengji.rl.value_afterstate import (
    OUTCOME_CLASSES,
    ValueAfterstateError,
    category_signed_level,
    example_from_trajectory_record,
    signed_level_category,
    tensors_after_action,
)
from shengji.rl.value_checkpoint import (
    ValueCheckpointError,
    load_checkpoint,
    save_checkpoint,
)
from shengji.rl.value_inference import predict_round, predict_tensors, score_actions
from shengji.rl.value_metrics import (
    absolute_value_error,
    expected_signed_level,
    fit_stratified_prior,
    paired_advantage_error,
    ranked_probability_score,
)
from shengji.rl.value_model import ValueModelConfig, ValueNetwork, model_state_sha256
from shengji.rl.value_training import (
    ValueTrainingError,
    collate_examples,
    evaluate_loss,
    fit,
)


SEED = 4_100_000
WORK = {"select_worlds": 2, "report_worlds": 30}


@pytest.fixture(scope="module")
def records():
    config = trajectory.build_config(
        seed0=SEED, explore_rate=0.0, explore_k=0, **WORK)
    rows, stats = trajectory.play_trajectory_round(config, 0, SEED, 0)
    assert stats["counts"]["decisions"] == len(rows) > 40
    return rows


@pytest.fixture(scope="module")
def examples(records):
    return [example_from_trajectory_record(row) for row in records]


@pytest.fixture(scope="module")
def independent_examples():
    config = trajectory.build_config(
        seed0=SEED + 1, explore_rate=0.0, explore_k=0, **WORK)
    rows, stats = trajectory.play_trajectory_round(
        config, 1, SEED + 1, 0)
    assert stats["counts"]["decisions"] == len(rows) > 40
    return [example_from_trajectory_record(row) for row in rows]


def _config(architecture="transformer"):
    return ValueModelConfig(
        architecture=architecture, width=16, history_layers=1,
        attention_heads=2, feedforward_width=32, max_history=100)


def test_record_action_builds_target_free_afterstate(records, examples):
    record, example = records[0], examples[0]
    example.validate()
    root = rebuild.state_for_record(record)
    direct = tensors_after_action(root, record["seat"], record["action"])
    assert direct.sha256() == example.input_sha256
    assert len(direct.history) == 1
    assert direct.world.shape == (5, 54)
    assert example.target_category == signed_level_category(
        record["outcome"]["attacker_points"], record["role"] == "attacker-team")

    # Policy/search metadata and every non-point outcome field are labels or
    # provenance, not features.  Changing them leaves input and target fixed.
    altered = copy.deepcopy(record)
    altered["policy"] = "not-a-model-feature"
    altered["ballot"] = [record["action"]]
    altered["allocation"] = None
    altered["preference"] = None
    altered["action_values"] = None
    altered["outcome"]["signed_level_utility"] = 999
    altered["outcome"]["winner_team"] = 99
    altered = finalize_record(altered)
    altered_example = example_from_trajectory_record(altered)
    assert altered_example.input_sha256 == example.input_sha256
    assert altered_example.target_category == example.target_category
    assert altered_example.deal_key == example.deal_key

    relabeled = copy.deepcopy(record)
    relabeled["outcome"]["attacker_points"] = (
        0 if record["outcome"]["attacker_points"] != 0 else 80)
    relabeled = finalize_record(relabeled)
    relabeled_example = example_from_trajectory_record(relabeled)
    assert relabeled_example.input_sha256 == example.input_sha256
    assert relabeled_example.target_category != example.target_category


def test_adapter_refuses_role_and_accepted_action_drift(records):
    role = finalize_record({
        **records[0],
        "role": ("defender-team" if records[0]["role"] == "attacker-team"
                 else "attacker-team"),
    })
    with pytest.raises(ValueAfterstateError, match="role disagrees"):
        example_from_trajectory_record(role)

    accepted = finalize_record({**records[0], "engine_play": ["BJ"]})
    with pytest.raises(ValueAfterstateError, match="engine-accepted action drift"):
        example_from_trajectory_record(accepted)


@pytest.mark.parametrize("architecture", ["gru", "transformer"])
def test_shared_model_contract_for_gru_and_transformer(examples, architecture):
    torch.manual_seed(7)
    model = ValueNetwork(_config(architecture))
    batch = collate_examples(examples[:3])
    logits = model(
        batch.tensors.public, batch.tensors.history,
        batch.tensors.history_mask, batch.tensors.world,
        batch.tensors.perspective)
    assert logits.shape == (3, OUTCOME_CLASSES)
    predictions = predict_tensors(model, [row.tensors for row in examples[:3]])
    assert len(predictions) == 3
    assert all(sum(row.probability) == pytest.approx(1.0) for row in predictions)


def test_metrics_and_train_only_prior(examples):
    target = examples[0].target_category
    perfect = np.zeros(OUTCOME_CLASSES, dtype=np.float64)
    perfect[target] = 1.0
    assert ranked_probability_score(perfect, target) == 0.0
    assert absolute_value_error(perfect, target) == 0.0
    assert expected_signed_level(perfect) == category_signed_level(target)
    assert paired_advantage_error(perfect, perfect, target, target) == 0.0

    prior = fit_stratified_prior(examples[:12])
    assert prior.training_examples == 12
    probability = prior.probability_for(examples[0].stratum)
    assert sum(probability) == pytest.approx(1.0)
    assert ranked_probability_score(probability, target) >= 0.0


def test_validation_loss_early_stop_and_checkpoint_round_trip(
        examples, independent_examples, tmp_path):
    torch.manual_seed(11)
    model = ValueNetwork(_config("gru"))
    train = [examples[0]] * 8
    validation = [independent_examples[0]] * 2
    assert examples[0].deal_key != independent_examples[0].deal_key
    initial_loss = evaluate_loss(model, validation, batch_size=2)
    initial_state = model_state_sha256(model)
    receipt = fit(
        model, train, validation, max_epochs=8, patience=3, batch_size=4,
        learning_rate=0.01, weight_decay=0.0, seed=12)
    assert receipt.best_epoch >= 1
    assert receipt.best_epoch == min(
        receipt.epochs, key=lambda row: row.validation_loss).epoch
    assert evaluate_loss(model, validation, batch_size=2) == pytest.approx(
        min(row.validation_loss for row in receipt.epochs))
    assert model_state_sha256(model) != initial_state

    before = predict_tensors(model, [examples[0].tensors])[0]
    path = tmp_path / "value.pt"
    assert len(save_checkpoint(path, model, metadata={"best_epoch": receipt.best_epoch})) == 64
    reopened, metadata = load_checkpoint(path)
    after = predict_tensors(reopened, [examples[0].tensors])[0]
    assert metadata == {"best_epoch": receipt.best_epoch}
    assert model_state_sha256(reopened) == model_state_sha256(model)
    assert after.probability == before.probability

    payload = torch.load(path, weights_only=True)
    payload["state_sha256"] = "0" * 64
    bad = tmp_path / "bad.pt"
    torch.save(payload, bad)
    with pytest.raises(ValueCheckpointError, match="logical state hash drift"):
        load_checkpoint(bad)

    with pytest.raises(ValueTrainingError, match="deal populations overlap"):
        fit(model, train, [examples[0]], max_epochs=1, patience=1)


def test_action_scoring_uses_engine_afterstates_without_mutating_root(records):
    model = ValueNetwork(_config("transformer"))
    searched = next(row for row in records if len(row["ballot"]) >= 2)
    root = rebuild.state_for_record(searched)
    hand_before = [list(hand) for hand in root.hands]
    scored = score_actions(
        model, root, searched["seat"], searched["ballot"][:2])
    assert len(scored) == 2
    assert [list(hand) for hand in root.hands] == hand_before
    assert all(len(row.prediction.probability) == OUTCOME_CLASSES for row in scored)


def test_terminal_prediction_bypasses_the_model(records):
    from shengji.rl.value_afterstate import apply_action

    last = records[-1]
    root = rebuild.state_for_record(last)
    terminal, _accepted = apply_action(root, last["seat"], last["action"])
    assert terminal.phase == "round_end"

    class MustNotRun:
        def __call__(self, *args, **kwargs):
            raise AssertionError("terminal inference called the model")

    prediction = predict_round(MustNotRun(), terminal, last["seat"])
    category = signed_level_category(
        terminal.attacker_points, terminal.is_attacker(last["seat"]))
    assert prediction.probability[category] == 1.0
    assert sum(value != 0.0 for value in prediction.probability) == 1
