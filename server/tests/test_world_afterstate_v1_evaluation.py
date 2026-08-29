from __future__ import annotations

import copy

import pytest

from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_dataset import join_advantage_examples
from shengji.rl.world_afterstate_v1_evaluation import (
    AUTHORITY, AdvantagePredictionV1, WorldAfterstateV1EvaluationError,
    collate_inference_pairs, evaluate_advantage_audit, predict_advantages,
    inference_population_sha256, prediction_population_sha256,
    validate_advantage_audit_result)
from shengji.rl.world_afterstate_v1_model import (
    new_world_afterstate_advantage_model)

from test_world_afterstate_v1_dataset import _population


def _calibration():
    rows = _population()
    for row in rows:
        object.__setattr__(row.evaluation_outcome, "fold", "calibration")
    return list(join_advantage_examples(rows))


def _predictions(joined, *, positive=True, positive_members=8):
    first_by_candidate = {}
    for value in joined:
        first_by_candidate.setdefault(
            (value.pair.state_group_id, value.pair.candidate_index), value)
    rows = []
    for (state, candidate), value in sorted(first_by_candidate.items()):
        for member in range(8):
            rows.append(AdvantagePredictionV1(
                state_group_id=state, candidate_index=candidate,
                incumbent_successor_sha256=
                    value.pair.incumbent_successor_sha256,
                candidate_successor_sha256=
                    value.pair.candidate_successor_sha256,
                member_index=member, model_state_sha256=f"{member + 1:064x}",
                advantage_microlevels=(
                    candidate * 1_000_000
                    if positive and member < positive_members
                    else (-candidate * 1_000_000 if positive else 0))))
    return rows


def test_target_free_prediction_has_no_label_surface_and_is_nonmutating():
    joined = _calibration()
    unique = [joined[index] for index in range(0, len(joined), 2)]
    batch = collate_inference_pairs(
        state_group_ids=[value.pair.state_group_id for value in unique],
        candidate_indexes=[value.pair.candidate_index for value in unique],
        incumbent_successor_sha256s=[
            value.pair.incumbent_successor_sha256 for value in unique],
        candidate_successor_sha256s=[
            value.pair.candidate_successor_sha256 for value in unique],
        incumbent_tensors=[value.example.incumbent.tensors for value in unique],
        candidate_tensors=[value.example.candidate.tensors for value in unique])
    assert not hasattr(batch, "targets")
    assert not hasattr(batch, "advantage_levels")
    model = new_world_afterstate_advantage_model(
        101, CAPACITY_SHAPES["small"])
    model.train(True)
    rows = predict_advantages(model, batch, member_index=0)
    assert len(rows) == len(unique)
    assert model.training is True
    assert len(inference_population_sha256(batch)) == 64
    assert len(prediction_population_sha256(rows)) == 64
    mutated = copy.deepcopy(batch)
    mutated.candidate.world[0, 0, 0] = (
        0.0 if mutated.candidate.world[0, 0, 0] != 0.0 else 1.0)
    assert inference_population_sha256(mutated) \
        != inference_population_sha256(batch)


def test_positive_action_signal_passes_all_nonredundant_gates():
    joined = _calibration()
    result = evaluate_advantage_audit(
        joined, _predictions(joined), bootstrap_replicates=10_000)
    validate_advantage_audit_result(result)
    assert result["passed"] is True
    assert result["positive_member_count"] == 8
    assert result["selection_dose_ppm"] == 1_000_000
    assert result["action_utility_microlevels"] \
        == result["simple_regret_improvement_microlevels"]
    assert result["authority"] == AUTHORITY


def test_zero_predictions_fail_action_and_dose_gates():
    joined = _calibration()
    result = evaluate_advantage_audit(
        joined, _predictions(joined, positive=False),
        bootstrap_replicates=200)
    assert result["passed"] is False
    assert result["selected_nonincumbent_state_count"] == 0
    assert result["selection_dose_ppm"] == 0


def test_member_stability_can_fail_while_ensemble_action_gates_pass():
    joined = _calibration()
    result = evaluate_advantage_audit(
        joined, _predictions(joined, positive_members=5),
        bootstrap_replicates=200)
    assert result["advantage_error_improvement_microlevels"][
        "bootstrap_lower"] > 0
    assert result["action_utility_microlevels"]["bootstrap_lower"] > 0
    assert result["selection_dose_ppm"] == 1_000_000
    assert result["positive_member_count"] == 5
    assert result["passed"] is False


def test_audit_refuses_missing_member_and_cross_successor_binding():
    joined = _calibration()
    predictions = _predictions(joined)
    with pytest.raises(WorldAfterstateV1EvaluationError,
                       match="prediction binding drift"):
        evaluate_advantage_audit(
            joined, predictions[:-1], bootstrap_replicates=200)
    forged = copy.copy(predictions[0])
    object.__setattr__(forged, "candidate_successor_sha256", "f" * 64)
    with pytest.raises(WorldAfterstateV1EvaluationError,
                       match="prediction binding drift"):
        evaluate_advantage_audit(
            joined, [forged, *predictions[1:]], bootstrap_replicates=200)
    duplicate_model = [copy.copy(row) for row in predictions]
    for row in duplicate_model:
        if row.member_index == 1:
            object.__setattr__(row, "model_state_sha256", "1".zfill(64))
    with pytest.raises(WorldAfterstateV1EvaluationError,
                       match="model cohort drift"):
        evaluate_advantage_audit(
            joined, duplicate_model, bootstrap_replicates=200)


def test_result_identity_and_gate_fields_have_teeth():
    joined = _calibration()
    result = evaluate_advantage_audit(
        joined, _predictions(joined), bootstrap_replicates=10_000)
    validate_advantage_audit_result(result)
    forged = copy.deepcopy(result)
    forged["simple_regret_improvement_microlevels"]["mean"] += 1
    with pytest.raises(WorldAfterstateV1EvaluationError,
                       match="regret/utility identity drift"):
        validate_advantage_audit_result(forged)
    forged = copy.deepcopy(result)
    forged["passed"] = False
    with pytest.raises(WorldAfterstateV1EvaluationError,
                       match="reconstruction drift"):
        validate_advantage_audit_result(forged)
