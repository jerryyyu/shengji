from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_audit_controller import (
    reopen_prediction_artifact_bytes)
from shengji.rl.world_afterstate_v1_execution import (
    WorldAfterstateV1ExecutionError, build_target_free_prediction_build,
    publish_target_free_prediction_build,
    reopen_calibration_labels, reopen_target_free_prediction_build,
    reopen_target_free_prediction_directory, reopen_training_values)
from shengji.rl.world_afterstate_v1_experiment import FREEZE_SCHEMA
from shengji.rl.world_afterstate_v1_rehearsal import (
    build_non_scientific_rehearsal)
from shengji.rl.world_afterstate_v1_training_controller import (
    CohortTrainingBuildV1, TRAINING_COHORTS)

from test_world_afterstate_v1_inference import _fixture

import shengji.rl.world_afterstate_v1_execution as execution


def _cohorts():
    rehearsal = build_non_scientific_rehearsal()
    files = dict(rehearsal.files)
    return {
        name: CohortTrainingBuildV1(
            manifest=json.loads(
                files[f"p1/cohorts/{name}/manifest.json"]),
            selected_checkpoint_raws=tuple(
                files[
                    f"p1/cohorts/{name}/checkpoints/member-{member:02d}.json"
                ] for member in range(8)))
        for name in TRAINING_COHORTS
    }


def test_target_free_prediction_packet_binds_natural_and_identical_inputs(
        tmp_path):
    population, audit_manifest, _root, materials = _fixture(tmp_path)
    freeze = {
        "schema": FREEZE_SCHEMA,
        "freeze_sha256": "f" * 64,
        "population": {
            "calibration_group_count": 52,
            "calibration_audit_count": 104,
            "calibration_pair_count": 52,
        },
    }
    build = build_target_free_prediction_build(
        freeze=freeze, population_manifest=population,
        audit_manifest=audit_manifest, audit_materials=materials,
        cohort_builds=_cohorts())
    assert reopen_target_free_prediction_build(build) == build
    files = dict(build.files)
    identical, _shuffled, artifact = reopen_prediction_artifact_bytes(
        files["predictions/identical-successor.json"])
    assert identical
    assert all(row.advantage_microlevels == 0 for row in identical)
    inference = json.loads(files["calibration-input.json"])
    assert artifact["input_population_sha256"] == inference[
        "inference_population_sha256s"]["identical-successor"]
    assert artifact["input_population_sha256"] != inference[
        "inference_population_sha256s"]["natural"]

    output = tmp_path / "prediction-packet"
    publish_target_free_prediction_build(output, build)
    assert reopen_target_free_prediction_directory(output) == build


def test_prediction_packet_refuses_coordinated_wrong_cohort_input(tmp_path):
    population, audit_manifest, _root, materials = _fixture(tmp_path)
    freeze = {
        "schema": FREEZE_SCHEMA,
        "freeze_sha256": "f" * 64,
        "population": {
            "calibration_group_count": 52,
            "calibration_audit_count": 104,
            "calibration_pair_count": 52,
        },
    }
    build = build_target_free_prediction_build(
        freeze=freeze, population_manifest=population,
        audit_manifest=audit_manifest, audit_materials=materials,
        cohort_builds=_cohorts())
    forged = copy.deepcopy(build)
    files = dict(forged.files)
    inference = json.loads(files["calibration-input.json"])
    inference["cohort_input_names"]["identical-successor"] = "natural"
    inference_body = {key: value for key, value in inference.items()
                      if key != "manifest_sha256"}
    inference["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(inference_body)).hexdigest()
    files["calibration-input.json"] = canonical_json_bytes(inference)
    manifest = copy.deepcopy(forged.manifest)
    row = next(row for row in manifest["files"]
               if row["relative_path"] == "calibration-input.json")
    row["byte_count"] = len(files["calibration-input.json"])
    row["sha256"] = hashlib.sha256(
        files["calibration-input.json"]).hexdigest()
    manifest["calibration_inference_manifest_sha256"] = inference[
        "manifest_sha256"]
    manifest_body = {key: value for key, value in manifest.items()
                     if key != "manifest_sha256"}
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest_body)).hexdigest()
    with pytest.raises(WorldAfterstateV1ExecutionError,
                       match="calibration inference manifest drift"):
        reopen_target_free_prediction_build(type(build)(
            manifest=manifest,
            files=tuple((path, files[path]) for path in sorted(files))))


def test_scientific_row_readers_pin_train_and_calibration_folds(monkeypatch):
    calls = []
    population = {"manifest_sha256": "a" * 64}
    dataset = {"manifest_sha256": "b" * 64}
    monkeypatch.setattr(
        execution, "_validate_frozen_input",
        lambda *args, **kwargs: (b"{}\n", population)
        if "population" in kwargs["label"] else (b"{}\n", dataset))
    monkeypatch.setattr(execution, "validate_population_manifest",
                        lambda value: None)
    monkeypatch.setattr(execution, "validate_dataset_manifest",
                        lambda value, *, population_manifest: None)

    class Reopened:
        row_sha256 = "c" * 64

    def reopen(_dataset, *, population_manifest, row_root, allowed_folds,
               **_kwargs):
        calls.append(allowed_folds)
        count = 3906 if allowed_folds == ("train",) else 624
        return tuple(({
            "state_group_id": f"{index % 52:064x}",
            "candidate_index": index % 2, "replicate": 0,
        }, Reopened()) for index in range(count))

    monkeypatch.setattr(execution, "reopen_dataset_manifest", reopen)
    monkeypatch.setattr(execution, "_row_population_sha",
                        lambda rows: "d" * 64)
    train_values = tuple(object() for _ in range(1589))
    monkeypatch.setattr(execution, "join_advantage_examples",
                        lambda rows: train_values)
    pair_manifest = {"manifest_sha256": "e" * 64}
    monkeypatch.setattr(execution, "build_advantage_manifest",
                        lambda *args, **kwargs: pair_manifest)
    monkeypatch.setattr(execution, "_capacity_artifacts", lambda build: {
        "p1/advantage-manifest.json": pair_manifest})
    freeze = {
        "schema": FREEZE_SCHEMA,
        "v0_inputs": {
            "population_external_sha256": "0" * 64,
            "population_manifest_sha256": "a" * 64,
            "dataset_external_sha256": "1" * 64,
            "dataset_manifest_sha256": "b" * 64,
        },
        "learner": {"row_workers": 4},
        "population": {
            "train_row_count": 3906, "pair_count": 1589,
            "train_row_population_sha256": "d" * 64,
            "calibration_label_row_count": 624,
            "calibration_label_pair_count": 520,
        },
    }
    assert reopen_training_values(
        freeze=freeze, capacity_build=object(),
        population_path=Path(__file__),
        dataset_manifest_path=Path(__file__), row_root=Path(__file__),
        deadline_monotonic_ns=10**30) == train_values

    class Pair:
        def __init__(self, index):
            self.state_group_id = f"{index % 52:064x}"

    calibration_values = tuple(
        type("Joined", (), {"pair": Pair(index)})()
        for index in range(520))
    monkeypatch.setattr(execution, "join_advantage_examples",
                        lambda rows: calibration_values)
    assert reopen_calibration_labels(
        freeze=freeze, population_path=Path(__file__),
        dataset_manifest_path=Path(__file__), row_root=Path(__file__),
        deadline_monotonic_ns=10**30) == calibration_values
    assert calls == [("train",), ("calibration",)]
