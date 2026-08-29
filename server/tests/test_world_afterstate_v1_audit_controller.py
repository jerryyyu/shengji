from __future__ import annotations

import copy
import hashlib
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_audit_controller import (
    WorldAfterstateV1AuditControllerError,
    build_prediction_artifact_bytes, evaluate_sealed_predictions,
    reopen_prediction_artifact_bytes, validate_sealed_audit_result)
from shengji.rl.world_afterstate_v1_evaluation import collate_inference_pairs
from shengji.rl.world_afterstate_v1_training_controller import (
    reopen_cohort_build)

from test_world_afterstate_v1_evaluation import _calibration
from test_world_afterstate_v1_training_controller import _run


def _batch(joined):
    unique = [joined[index] for index in range(0, len(joined), 2)]
    return collate_inference_pairs(
        state_group_ids=[value.pair.state_group_id for value in unique],
        candidate_indexes=[value.pair.candidate_index for value in unique],
        incumbent_successor_sha256s=[
            value.pair.incumbent_successor_sha256 for value in unique],
        candidate_successor_sha256s=[
            value.pair.candidate_successor_sha256 for value in unique],
        incumbent_tensors=[
            value.example.incumbent.tensors for value in unique],
        candidate_tensors=[
            value.example.candidate.tensors for value in unique])


def _artifact():
    build = _run()
    models, manifest = reopen_cohort_build(build)
    joined = _calibration()
    return build_prediction_artifact_bytes(
        models=models, batch=_batch(joined), cohort_manifest=manifest), joined


def _rehash(value):
    body = {key: item for key, item in value.items()
            if key != "artifact_sha256"}
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    return canonical_json_bytes(value)


def test_target_free_predictions_seal_before_audit_labels_open():
    raw, joined = _artifact()
    natural, shuffled, artifact = reopen_prediction_artifact_bytes(raw)
    assert len(natural) == len(shuffled) > 0
    assert artifact["world_shuffle_applied"] is True
    assert artifact["audit_labels_opened"] is False
    assert b'"advantage_levels"' not in raw
    assert b'"target_levels"' not in raw
    assert b'"signed_level_category"' not in raw

    result = evaluate_sealed_predictions(raw, joined)
    validate_sealed_audit_result(result)
    assert result["audit_labels_opened"] is True
    assert result["report_rows_opened"] is False
    assert result["world_shuffle_result"] is not None
    assert result["world_shuffle_delta_result"] is not None


def test_prediction_population_and_model_bindings_have_teeth():
    raw, _joined = _artifact()
    forged = json.loads(raw)
    forged["natural_predictions"][0]["advantage_microlevels"] += 1
    with pytest.raises(WorldAfterstateV1AuditControllerError,
                       match="natural prediction population binding drift"):
        reopen_prediction_artifact_bytes(_rehash(forged))

    build = _run()
    models, manifest = reopen_cohort_build(build)
    altered = copy.deepcopy(models)
    next(altered[0].parameters()).data.add_(1.0)
    with pytest.raises(WorldAfterstateV1AuditControllerError,
                       match="model cohort binding drift"):
        build_prediction_artifact_bytes(
            models=altered, batch=_batch(_calibration()),
            cohort_manifest=manifest)


def test_training_control_artifact_cannot_claim_world_shuffle():
    build = _run(
        cohort_name="action-association-permutation", controlled=True)
    models, manifest = reopen_cohort_build(build)
    joined = _calibration()
    raw = build_prediction_artifact_bytes(
        models=models, batch=_batch(joined), cohort_manifest=manifest)
    natural, shuffled, artifact = reopen_prediction_artifact_bytes(raw)
    assert natural
    assert shuffled == ()
    assert artifact["world_shuffle_applied"] is False
    result = evaluate_sealed_predictions(raw, joined)
    validate_sealed_audit_result(result)
    assert result["world_shuffle_result"] is None
    assert result["world_shuffle_delta_result"] is None
