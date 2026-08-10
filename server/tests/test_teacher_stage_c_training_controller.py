from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import teacher_stage_c_training_controller as CTRL
from shengji.rl import stage_c_model as MODEL


def _gate_summary(key: str, value: float) -> dict:
    return {key: value, "n": 64, "mean": 0.0}


def _aggregate() -> dict:
    design_shards = [
        {"index": index,
         "split": "DESIGN" if index < 8 else "CALIB",
         "sha256": f"{index + 1:064x}",
         "row_sha256s_sha256": f"{index + 101:064x}"}
        for index in range(12)
    ]
    report_shards = [
        {"index": index, "split": "REPORT", "sha256": f"{index + 20:064x}",
         "row_sha256s_sha256": f"{index + 120:064x}"}
        for index in range(12, 16)
    ]
    value = {
        "schema": CTRL.LABEL_CTRL.AGGREGATE_SCHEMA,
        "run_id": CTRL.LABEL_CTRL.RUN_ID,
        "git": "a" * 40,
        "controller_packet_sha256": "b" * 64,
        "label_receipt_sha256": "c" * 64,
        "state_set_sha256": "d" * 64,
        "schedule_sha256": "e" * 64,
        "status": "COMPLETE",
        "states": 2048,
        "complete_rows": 2048,
        "refused_rows": 0,
        "work": {},
        "shards": design_shards + report_shards,
        "design_calib_manifest": {
            "splits": ["DESIGN", "CALIB"], "shards": design_shards,
            "states": 1536, "report_rows_included": False,
            "training_packet_review_authorized": False,
        },
        "sealed_report_manifest": {
            "split": "REPORT", "shards": report_shards, "states": 512,
            "sealed_from_training_and_seed_selection": True,
            "report_open_authorized": False,
        },
        "fidelity_gate": {
            "schema": "teacher-stage-c-label-fidelity-gate-v2",
            "decision": "AUTHORIZE_MODEL_PACKET_REVIEW",
            "fidelity_pass": True, "v11_recall_pass": True,
            "ordinary_anchor_regret": _gate_summary(
                "one_sided_95_ucb", 0.05),
            "hard_tail_regret": _gate_summary("one_sided_95_ucb", 0.08),
            "v11_recall_treatment_minus_matched_random": _gate_summary(
                "one_sided_95_lcb", 0.01),
        },
        "utility_published": True,
        "model_packet_review_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["aggregate_sha256"] = CTRL.self_hash(value, "aggregate_sha256")
    value["external_sha256"] = "f" * 64
    return value


def _fidelity_only_aggregate() -> dict:
    value = _aggregate()
    gate = value["fidelity_gate"]
    gate["decision"] = "DIAGNOSE_FROZEN_STAGE_C_ONLY"
    gate["v11_recall_pass"] = False
    gate["v11_recall_treatment_minus_matched_random"] = {
        "n": 48,
        "mean": 1.0 / 48.0,
        "one_sided_95_lcb": -0.057994909647547,
        "one_sided_95_ucb": 0.09966157631421366,
    }
    value["model_packet_review_authorized"] = False
    external = value.pop("external_sha256")
    value["aggregate_sha256"] = CTRL.self_hash(value, "aggregate_sha256")
    value["external_sha256"] = external
    return value


def _dataset() -> dict:
    value = {
        "schema": CTRL.DATASET_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "split_counts": dict(CTRL.EXPECTED_SPLITS),
        "surface_counts": CTRL.EXPECTED_SURFACES,
        "sealed_report_manifest_sha256": "1" * 64,
        "report_rows_included": False,
        "report_shard_files_opened": 0,
    }
    value["dataset_sha256"] = CTRL.self_hash(value, "dataset_sha256")
    return value


def test_training_schedule_is_exact_complete_and_separate_by_surface() -> None:
    schedule = CTRL.build_schedule()
    assert schedule["cell_count"] == 48
    assert schedule["full_curve_cells_for_calib_selection"] == 16
    assert schedule["single_seed_selection"] is False
    assert schedule["report_rows_included"] is False
    cells = {(value["surface"], value["seed"], value["curve_fraction"])
             for value in schedule["cells"]}
    assert cells == {
        (surface, seed, fraction)
        for surface in MODEL.SURFACES
        for seed in MODEL.TRAINING_SEEDS
        for fraction in MODEL.CURVE_FRACTIONS
    }
    assert len({value["result"] for value in schedule["cells"]}) == 48


def test_label_aggregate_review_claim_binds_gate_and_sealed_report() -> None:
    aggregate = _aggregate()
    claim = CTRL.expected_label_aggregate_review_claim(aggregate, "f" * 64)
    assert claim["fidelity_decision"] == "AUTHORIZE_MODEL_PACKET_REVIEW"
    assert claim["ordinary_anchor_regret_ucb"] == 0.05
    assert claim["hard_tail_regret_ucb"] == 0.08
    assert claim["v11_recall_lcb"] == 0.01
    assert claim["report_shards_opened_by_training_review"] == 0
    assert claim["training_authorized"] is False


def test_legacy_review_helper_refuses_fidelity_only_result() -> None:
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="combined gate"):
        CTRL.expected_label_aggregate_review_claim(
            _fidelity_only_aggregate(), "f" * 64)


def test_fidelity_consumption_claim_admits_labels_but_not_v11() -> None:
    aggregate = _fidelity_only_aggregate()
    claim = CTRL.expected_label_fidelity_review_claim(
        aggregate, "f" * 64)
    assert claim["original_combined_decision"] \
        == "DIAGNOSE_FROZEN_STAGE_C_ONLY"
    assert claim["label_fidelity_pass"] is True
    assert claim["v11_recall_pass"] is False
    assert claim["v11_proposer_admitted"] is False
    assert claim["one_v11_free_training_controller_freeze_authorized"] \
        is True
    assert claim["training_authorized"] is False

    failed = copy.deepcopy(aggregate)
    failed["fidelity_gate"]["fidelity_pass"] = False
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="fidelity-only"):
        CTRL.expected_label_fidelity_review_claim(failed, "f" * 64)


def test_label_aggregate_and_exact_review_marker_reopen(tmp_path) -> None:
    aggregate = _fidelity_only_aggregate()
    aggregate.pop("external_sha256")
    path = tmp_path / "aggregate.json"
    path.write_bytes(CTRL.canonical_json(aggregate))
    digest = CTRL.sha256_file(path)
    claim = CTRL.expected_label_fidelity_review_claim(aggregate, digest)
    review = tmp_path / "review.md"
    review.write_text(
        CTRL.LABEL_FIDELITY_REVIEW_MARKER
        + json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n")
    reopened, reopened_claim = CTRL.validate_label_aggregate(
        path, digest, review)
    assert reopened == aggregate
    assert reopened_claim == claim


def test_packet_exposes_only_training_review_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        CTRL, "_source_sha256s",
        lambda: {path: "a" * 64 for path in CTRL.SOURCE_PATHS})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {
        "host": "mini", "python": "3.14", "torch": "2.13",
        "numpy": "2.5", "device": "cpu", "cpu_threads_per_cell": 1,
        "max_concurrent_cells": 8,
        "heartbeat": "one JSON record after every epoch",
    })
    aggregate = _fidelity_only_aggregate()
    review = CTRL.expected_label_fidelity_review_claim(aggregate, "f" * 64)
    packet = CTRL.build_packet(
        git="a" * 40, dataset=_dataset(), dataset_external_sha256="2" * 64,
        aggregate=aggregate, aggregate_review=review)
    assert packet["authority"] == {
        "examples_materialized": True,
        "training_started": False,
        "one_training_execution_authorized": False,
        "v11_inference_authorized": False,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert packet["parents"]["label_aggregate"] == {
        "external_sha256": aggregate["external_sha256"],
        "internal_sha256": aggregate["aggregate_sha256"],
        "review_schema": CTRL.LABEL_FIDELITY_REVIEW_SCHEMA,
        "review_claim_sha256": CTRL._manifest_hash(review),
        "original_combined_decision": "DIAGNOSE_FROZEN_STAGE_C_ONLY",
        "label_fidelity_pass": True,
        "v11_proposer_admitted": False,
    }
    claim = CTRL.expected_review_claim(packet, "3" * 64)
    assert claim["training_supervisor_sha256"] == "a" * 64
    assert claim["training_cells"] == 48
    assert claim["training_seeds"] == 8
    assert claim["execution_host"] == "mini"
    assert claim["one_training_execution_authorized"] is True
    assert claim["v11_inference_authorized"] is False
    assert claim["report_open_authorized"] is False
    assert packet["result_contract"]["curve_diagnostics"][
        "selection_eligible_curve_fraction"] == 1.0
    assert packet["result_contract"]["curve_diagnostics"][
        "smaller_curves_are_diagnostic_only"] is True
    assert packet["result_contract"]["selected_ensemble_models"] == 8
    assert packet["result_contract"]["single_capability_selection"] is True
    assert claim["single_capability_selection"] is True
    assert claim["max_concurrent_cells"] == 8
    assert claim["supervisor_heartbeat_seconds"] == 30
    assert claim["supervisor_resume_authorized"] is False
    assert claim["supervisor_retry_authorized"] is False
    assert packet["result_contract"]["supervision"] == {
        "max_concurrent_cells": 8,
        "heartbeat_seconds": 30,
        "starts_all_frozen_cells": True,
        "resume_authorized": False,
        "retry_authorized": False,
        "aggregate_only_after_all_cells_exit_zero": True,
    }


def test_manifest_order_refuses_report_reentry_or_swapped_shards() -> None:
    aggregate = _aggregate()
    assert len(CTRL._design_calib_manifest(aggregate)) == 12
    swapped = copy.deepcopy(aggregate)
    swapped["design_calib_manifest"]["shards"][0]["split"] = "REPORT"
    with pytest.raises(CTRL.TrainingControllerRefused, match="order"):
        CTRL._design_calib_manifest(swapped)
    reordered = copy.deepcopy(aggregate)
    reordered["design_calib_manifest"]["shards"][0:2] = list(reversed(
        reordered["design_calib_manifest"]["shards"][0:2]))
    with pytest.raises(CTRL.TrainingControllerRefused, match="order"):
        CTRL._design_calib_manifest(reordered)


def test_dataset_materialization_opens_only_design_and_calib_shards(
        monkeypatch) -> None:
    aggregate = _aggregate()
    states = []
    shards = []
    cursor = 0
    opened = []
    split_surfaces = {
        "DESIGN": ["play"] * 960 + ["bury"] * 64,
        "CALIB": ["play"] * 480 + ["bury"] * 32,
    }
    for index in range(12):
        split = "DESIGN" if index < 8 else "CALIB"
        local = index if index < 8 else index - 8
        surfaces = split_surfaces[split][local * 128:(local + 1) * 128]
        ids = []
        rows = []
        for surface in surfaces:
            state_id = f"state-{cursor}"
            cursor += 1
            ids.append(state_id)
            states.append({
                "state_id": state_id, "split": split,
                "surface_type": surface,
            })
            rows.append({"state_id": state_id, "split": split})
        shards.append({
            "status": "COMPLETE", "refused_rows": 0, "split": split,
            "state_ids": ids, "rows": rows,
            "row_sha256s": [f"{index + 200:064x}"] * 128,
        })
        aggregate["design_calib_manifest"]["shards"][index][
            "row_sha256s_sha256"] = CTRL.sha256_bytes(CTRL.canonical_json(
                shards[-1]["row_sha256s"]))
    states.extend({
        "state_id": f"report-{index}", "split": "REPORT",
        "surface_type": "play",
    } for index in range(512))
    packet = {"schedule": {"shards": [
        {"split": "DESIGN" if index < 8 else (
            "CALIB" if index < 12 else "REPORT"),
         "local_shard": index if index < 8 else (
             index - 8 if index < 12 else index - 12)}
        for index in range(16)
    ]}}
    expected_paths = [CTRL._expected_label_shard_path(packet, index)
                      for index in range(12)]
    sha_by_path = {
        str(path): aggregate["design_calib_manifest"]["shards"][index]["sha256"]
        for index, path in enumerate(expected_paths)
    }
    shard_by_path = {str(path): shards[index]
                     for index, path in enumerate(expected_paths)}

    def fake_sha(path):
        opened.append(str(path))
        return sha_by_path[str(path)]

    monkeypatch.setattr(CTRL, "sha256_file", fake_sha)
    monkeypatch.setattr(CTRL, "load_json", lambda path: shard_by_path[str(path)])
    monkeypatch.setattr(CTRL.LABEL, "_load_v11", lambda: object())
    monkeypatch.setattr(CTRL.LABEL, "validate_shard", lambda *args, **kwargs: None)
    monkeypatch.setattr(CTRL.CAPTURE, "replay_state", lambda state: object())
    monkeypatch.setattr(
        CTRL.MODEL, "materialize_example",
        lambda state, row, rnd: {
            "state_id": state["state_id"], "split": state["split"],
            "surface_type": state["surface_type"],
        })
    monkeypatch.setattr(
        CTRL.TRAIN, "validate_population", lambda *args, **kwargs: None)
    dataset = CTRL.materialize_dataset(
        label_packet=packet, label_receipt_sha256="a" * 64,
        state_set={"states": states}, aggregate=aggregate)
    assert opened == [str(path) for path in expected_paths]
    assert dataset["report_shard_files_opened"] == 0
    assert dataset["report_rows_included"] is False
    assert dataset["candidate_provenance_contract"] == {
        "teacher_targets": "mc_counterfactual_signed_level_utility",
        "all_reviewed_candidate_actions_retained": True,
        "candidate_source_tags_in_examples": False,
        "candidate_source_tags_in_model_inputs": False,
        "v11_origin_actions_are_source_agnostic_examples": True,
        "v11_checkpoint_use": "frozen_parent_revalidation_only",
        "v11_proposer_admitted_for_inference": False,
        "inference_must_not_load_v11": True,
    }
    assert {split: {surface: len(values) for surface, values in surfaces.items()}
            for split, surfaces in dataset["examples"].items()} \
        == CTRL.EXPECTED_SURFACES


def test_aggregate_claim_changes_when_report_manifest_changes() -> None:
    aggregate = _fidelity_only_aggregate()
    before = CTRL.expected_label_fidelity_review_claim(aggregate, "f" * 64)
    changed = copy.deepcopy(aggregate)
    changed["sealed_report_manifest"]["shards"][0]["sha256"] = "9" * 64
    after = CTRL.expected_label_fidelity_review_claim(changed, "f" * 64)
    assert before["sealed_report_manifest_sha256"] \
        != after["sealed_report_manifest_sha256"]


def _label_packet(runtime_sources: dict[str, str], shard_slots: list[str]) -> dict:
    value = {
        "schema": CTRL.LABEL_CTRL.SCHEMA,
        "packet_id": CTRL.LABEL_CTRL.PACKET_ID,
        "run_id": CTRL.LABEL_CTRL.RUN_ID,
        "producer": {
            "git": "a" * 40,
            "tree_dirty": False,
            "promotable": True,
        },
        "runtime_mode": {"compiled": True, "strict_voids": True},
        "runtime_sources": runtime_sources,
        "result_contract": {"shard_admission_slots": shard_slots},
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "labels_computed": False,
            "one_label_execution_authorized": False,
            "training_authorized": False,
            "report_open_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    value["packet_sha256"] = CTRL.LABEL_CTRL.self_hash(value)
    return value


def test_training_accepts_reviewed_label_parent_from_different_git_only_when_sources_match(
        monkeypatch, tmp_path: Path) -> None:
    sources = {"server/scripts/label.py": "1" * 64}
    slots = [f"server/runs/locks/shard-{index}.json" for index in range(16)]
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL.LABEL_CTRL, "runtime_sources", lambda: sources)
    monkeypatch.setattr(
        CTRL.LABEL_CTRL, "require_shard_admission_slots_ignored",
        lambda: slots)
    monkeypatch.setattr(
        CTRL.LABEL_CTRL.CAPTURE_CTRL, "require_runtime_mode",
        lambda: {"compiled": True, "strict_voids": True})
    path = tmp_path / CTRL.LABEL_CTRL.CONTROLLER_PACKET_PATH
    path.parent.mkdir(parents=True)
    packet = _label_packet(sources, slots)
    path.write_bytes(CTRL.canonical_json(packet))
    digest = CTRL.sha256_file(path)

    reopened = CTRL._reviewed_upstream_label_packet(path, digest)
    assert reopened["producer"]["git"] == "a" * 40
    assert reopened["external_sha256"] == digest

    monkeypatch.setattr(
        CTRL.LABEL_CTRL, "runtime_sources",
        lambda: {"server/scripts/label.py": "2" * 64})
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="identity/source/authority"):
        CTRL._reviewed_upstream_label_packet(path, digest)
