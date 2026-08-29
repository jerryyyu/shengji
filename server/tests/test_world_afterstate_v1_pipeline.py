from __future__ import annotations

import copy
import hashlib
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_audit_controller import (
    build_prediction_artifact_bytes, evaluate_sealed_predictions,
    reopen_prediction_artifact_bytes)
from shengji.rl.world_afterstate_v1_evaluation import (
    inference_population_sha256)
from shengji.rl.world_afterstate_v1_inference import (
    AUTHORITY as INFERENCE_AUTHORITY, COHORT_INPUT_NAMES,
    MANIFEST_SCHEMA as INFERENCE_MANIFEST_SCHEMA)
from shengji.rl.world_afterstate_v1_pipeline import (
    WorldAfterstateV1PipelineError, build_pipeline_build,
    publish_pipeline_build,
    reopen_pipeline_build, reopen_pipeline_directory)
from shengji.rl.world_afterstate_v1_rehearsal import (
    _audit_labels, _target_free_audit_batch,
    build_non_scientific_rehearsal)
from shengji.rl.world_afterstate_v1_result import (
    CONTROL_NAMES, derive_terminal_result)
from shengji.rl.world_afterstate_v1_training_controller import (
    CohortTrainingBuildV1, TRAINING_COHORTS, reopen_cohort_build)


def _scientific_build():
    rehearsal = build_non_scientific_rehearsal()
    files = dict(rehearsal.files)
    cohorts = {}
    models = {}
    for name in TRAINING_COHORTS:
        cohort = CohortTrainingBuildV1(
            manifest=json.loads(
                files[f"p1/cohorts/{name}/manifest.json"]),
            selected_checkpoint_raws=tuple(
                files[
                    f"p1/cohorts/{name}/checkpoints/member-{member:02d}.json"
                ] for member in range(8)))
        models[name], _manifest = reopen_cohort_build(cohort)
        cohorts[name] = cohort

    batches = {
        "natural": _target_free_audit_batch(identical=False),
        "identical-successor": _target_free_audit_batch(identical=True),
    }
    prediction_raws = {
        name: build_prediction_artifact_bytes(
            models=models[name],
            batch=batches[COHORT_INPUT_NAMES[name]],
            cohort_manifest=cohorts[name].manifest)
        for name in TRAINING_COHORTS
    }
    labels = _audit_labels()
    audits = {
        name: evaluate_sealed_predictions(prediction_raws[name], labels)
        for name in TRAINING_COHORTS
    }
    identical, _shuffled, _artifact = reopen_prediction_artifact_bytes(
        prediction_raws["identical-successor"])
    p0 = json.loads(files["p0/label-ceiling.json"])
    terminal = derive_terminal_result(
        p0, natural_result=audits["natural"]["natural_result"],
        control_results={
            name: audits[name]["natural_result"] for name in CONTROL_NAMES
        },
        identical_predictions_exact_zero=bool(identical) and all(
            row.advantage_microlevels == 0 for row in identical),
        world_shuffle_delta_result=audits[
            "natural"]["world_shuffle_delta_result"])
    inference_body = {
        "schema": INFERENCE_MANIFEST_SCHEMA,
        "population_manifest_sha256": "b" * 64,
        "audit_manifest_sha256": "c" * 64,
        "fold": "calibration",
        "group_count": 6,
        "pair_count": 12,
        "audit_count": 18,
        "audit_population_sha256": "d" * 64,
        "inference_population_sha256s": {
            name: inference_population_sha256(batch)
            for name, batch in batches.items()
        },
        "cohort_input_names": dict(COHORT_INPUT_NAMES),
        "identical_successor_changed_pair_count": 12,
        "identical_successor_dose_ppm": 1_000_000,
        "contains_outcome_labels": False,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
        "authority": dict(INFERENCE_AUTHORITY),
    }
    inference_manifest = {
        **inference_body,
        "manifest_sha256": hashlib.sha256(
            canonical_json_bytes(inference_body)).hexdigest(),
    }
    return build_pipeline_build(
        run_kind="reviewed-p1-pilot", label_ceiling=p0,
        subsplit_manifest=json.loads(files["p1/subsplit.json"]),
        control_evidence={
            name: json.loads(files[f"p1/controls/{name}.json"])
            for name in CONTROL_NAMES
        }, cohort_builds=cohorts, prediction_artifacts=prediction_raws,
        audit_results=audits, terminal_result=terminal,
        calibration_inference_manifest=inference_manifest)


def test_full_path_rehearsal_reopens_every_file_and_terminal(tmp_path):
    build = build_non_scientific_rehearsal()
    reopened = reopen_pipeline_build(build)
    assert reopened == build
    assert build.manifest["non_scientific_rehearsal"] is True
    assert build.manifest["report_rows_opened"] is False
    assert set(build.manifest["authority"].values()) == {False}
    assert build.manifest["file_count"] == 50

    root = tmp_path / "pipeline"
    publish_pipeline_build(root, build)
    assert reopen_pipeline_directory(root) == build


def test_pipeline_wiring_refuses_coordinated_terminal_rewrite():
    build = build_non_scientific_rehearsal()
    files = dict(build.files)
    terminal = json.loads(files["p1/terminal.json"])
    terminal["control_action_gates_passed"] = {
        name: False for name in terminal["control_action_gates_passed"]}
    terminal["identical_predictions_exact_zero"] = True
    terminal["negative_controls_failed_on_demand"] = True
    terminal["world_signal_passed"] = False
    terminal["world_twin_packet_review_proposal_authorized"] = False
    if terminal["decision"] != "PASS_ACTION_ONLY_NO_WORLD_SIGNAL":
        terminal["natural_action_gates_passed"] = True
        terminal["decision"] = "PASS_ACTION_ONLY_NO_WORLD_SIGNAL"
        terminal["public_action_value_packet_review_proposal_authorized"] = True
    else:
        terminal["natural_action_gates_passed"] = False
        terminal["decision"] = "SELECT_NONE_NO_ACTION_ADVANTAGE"
        terminal["public_action_value_packet_review_proposal_authorized"] = False
    terminal_body = {
        key: value for key, value in terminal.items()
        if key != "result_sha256"}
    terminal["result_sha256"] = hashlib.sha256(
        canonical_json_bytes(terminal_body)).hexdigest()
    files["p1/terminal.json"] = canonical_json_bytes(terminal)

    manifest = copy.deepcopy(build.manifest)
    terminal_row = next(
        row for row in manifest["files"]
        if row["relative_path"] == "p1/terminal.json")
    terminal_row["byte_count"] = len(files["p1/terminal.json"])
    terminal_row["sha256"] = hashlib.sha256(
        files["p1/terminal.json"]).hexdigest()
    manifest["terminal_result_sha256"] = terminal["result_sha256"]
    manifest["terminal_decision"] = terminal["decision"]
    manifest_body = {
        key: value for key, value in manifest.items()
        if key != "manifest_sha256"}
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest_body)).hexdigest()
    forged = copy.copy(build)
    object.__setattr__(forged, "manifest", manifest)
    object.__setattr__(forged, "files", tuple(sorted(files.items())))
    with pytest.raises(
            WorldAfterstateV1PipelineError,
            match="terminal reconstruction drift"):
        reopen_pipeline_build(forged)


def test_scientific_pipeline_binds_each_cohort_to_its_target_free_input():
    build = _scientific_build()
    assert reopen_pipeline_build(build) == build
    assert build.manifest["run_kind"] == "reviewed-p1-pilot"
    assert build.manifest["non_scientific_rehearsal"] is False
    assert build.manifest["calibration_inference_manifest_sha256"] \
        == json.loads(dict(build.files)[
            "p1/calibration-input.json"])["manifest_sha256"]

    files = dict(build.files)
    natural = json.loads(files["p1/predictions/natural.json"])
    forged = json.loads(
        files["p1/predictions/identical-successor.json"])
    forged["input_population_sha256"] = natural[
        "input_population_sha256"]
    body = {key: value for key, value in forged.items()
            if key != "artifact_sha256"}
    forged["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    files["p1/predictions/identical-successor.json"] = \
        canonical_json_bytes(forged)
    broken = copy.copy(build)
    object.__setattr__(broken, "files", tuple(sorted(files.items())))
    with pytest.raises(
            WorldAfterstateV1PipelineError,
            match="pipeline build file binding drift"):
        reopen_pipeline_build(broken)

    with pytest.raises(
            WorldAfterstateV1PipelineError,
            match="calibration input/prediction binding drift"):
        build_pipeline_build(
            run_kind="reviewed-p1-pilot",
            label_ceiling=json.loads(files["p0/label-ceiling.json"]),
            subsplit_manifest=json.loads(files["p1/subsplit.json"]),
            control_evidence={
                name: json.loads(files[f"p1/controls/{name}.json"])
                for name in CONTROL_NAMES
            },
            cohort_builds={
                name: CohortTrainingBuildV1(
                    manifest=json.loads(
                        files[f"p1/cohorts/{name}/manifest.json"]),
                    selected_checkpoint_raws=tuple(
                        files[
                            f"p1/cohorts/{name}/checkpoints/member-{member:02d}.json"
                        ] for member in range(8)))
                for name in TRAINING_COHORTS
            },
            prediction_artifacts={
                name: files[f"p1/predictions/{name}.json"]
                for name in TRAINING_COHORTS
            },
            audit_results={
                name: json.loads(files[f"p1/audits/{name}.json"])
                for name in TRAINING_COHORTS
            },
            terminal_result=json.loads(files["p1/terminal.json"]),
            calibration_inference_manifest=json.loads(
                files["p1/calibration-input.json"]))
