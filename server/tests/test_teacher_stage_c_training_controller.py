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
            "decision": "DIAGNOSE_FROZEN_STAGE_C_ONLY",
            "fidelity_pass": True, "v11_recall_pass": False,
            "ordinary_anchor_regret": _gate_summary(
                "one_sided_95_ucb", 0.05),
            "hard_tail_regret": _gate_summary("one_sided_95_ucb", 0.08),
            "v11_recall_treatment_minus_matched_random": {
                "n": 48, "mean": 1.0 / 48.0,
                "one_sided_95_lcb": -0.057994909647547,
                "one_sided_95_ucb": 0.09966157631421366,
            },
        },
        "utility_published": True,
        "model_packet_review_authorized": False,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["aggregate_sha256"] = CTRL.self_hash(value, "aggregate_sha256")
    value["external_sha256"] = "f" * 64
    return value


def _fresh_report() -> dict:
    sealed = {
        "sealed_selection_sha256": "2" * 64,
        "fresh_report_state_ids_sha256": "3" * 64,
        "fresh_report_state_material_sha256": "4" * 64,
        "fresh_report_per_state_hashes_sha256": "5" * 64,
        "effective_state_ids_sha256": "6" * 64,
        "fresh_report_states": 512,
    }
    return {
        "packet_sha256": "7" * 64,
        "sealed_selection": sealed,
    }


def _fresh_review() -> dict:
    return {
        "schema": CTRL.FRESH.REVIEW_SCHEMA,
        "one_v11_free_training_controller_freeze_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "verdict": "PASS",
    }


def _dataset() -> dict:
    value = {
        "schema": CTRL.DATASET_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "split_counts": dict(CTRL.EXPECTED_SPLITS),
        "surface_counts": CTRL.EXPECTED_SURFACES,
        "fresh_report_selection": CTRL.fresh_report_dataset_contract(
            _fresh_report(), _fresh_review()),
        "candidate_provenance_contract":
            CTRL.candidate_provenance_contract(),
        "old_report_labels_quarantined": True,
        "report_rows_included": False,
        "report_label_shard_files_opened": 0,
        "fresh_report_states_materialized": False,
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


def test_label_fidelity_summary_admits_labels_but_not_v11() -> None:
    aggregate = _aggregate()
    summary = CTRL.label_fidelity_summary(aggregate, "f" * 64)
    assert summary["original_combined_decision"] \
        == "DIAGNOSE_FROZEN_STAGE_C_ONLY"
    assert summary["ordinary_anchor_regret_ucb"] == 0.05
    assert summary["hard_tail_regret_ucb"] == 0.08
    assert summary["v11_recall_lcb"] < 0
    assert summary["v11_recall_pass"] is False
    assert summary["v11_proposer_admitted"] is False
    assert summary["old_report_quarantined"] is True


def test_label_aggregate_requires_fidelity_pass_and_v11_free_route() -> None:
    aggregate = _aggregate()
    failed = copy.deepcopy(aggregate)
    failed["fidelity_gate"]["fidelity_pass"] = False
    failed["aggregate_sha256"] = CTRL.self_hash(failed, "aggregate_sha256")
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="V11-free"):
        CTRL.label_fidelity_summary(failed, "f" * 64)


def test_label_aggregate_reopens_without_old_report_authority(tmp_path) -> None:
    aggregate = _aggregate()
    aggregate.pop("external_sha256")
    path = tmp_path / "aggregate.json"
    path.write_bytes(CTRL.canonical_json(aggregate))
    digest = CTRL.sha256_file(path)
    reopened = CTRL.validate_label_aggregate(path, digest)
    assert reopened == aggregate


def test_fresh_report_exact_review_marker_is_the_freeze_authority(
        monkeypatch, tmp_path) -> None:
    packet = _fresh_report()
    review_claim = _fresh_review()
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL.FRESH, "PACKET_PATH", "fresh.json")
    monkeypatch.setattr(
        CTRL.FRESH, "validate_packet", lambda **kwargs: packet)
    monkeypatch.setattr(
        CTRL.FRESH, "expected_review_claim",
        lambda value, digest: review_claim)
    path = tmp_path / "fresh.json"
    path.write_text("{}\n")
    review = tmp_path / "review.md"
    review.write_text(
        CTRL.FRESH.REVIEW_MARKER
        + json.dumps(review_claim, sort_keys=True, separators=(",", ":"))
        + "\n")
    reopened, claim = CTRL.validate_fresh_report(
        path, CTRL.FRESH_REPORT_PACKET_SHA256, review, tmp_path / "state.md")
    assert reopened == packet
    assert claim == review_claim


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
    aggregate = _aggregate()
    fresh = _fresh_report()
    review = _fresh_review()
    packet = CTRL.build_packet(
        git="a" * 40, dataset=_dataset(), dataset_external_sha256="2" * 64,
        aggregate=aggregate, fresh_report=fresh,
        fresh_report_review=review)
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
    assert packet["parents"]["label_aggregate"][
        "original_combined_decision"] == "DIAGNOSE_FROZEN_STAGE_C_ONLY"
    assert packet["parents"]["label_aggregate"][
        "old_report_labels_quarantined"] is True
    assert packet["parents"]["fresh_report_selection"][
        "external_sha256"] == CTRL.FRESH_REPORT_PACKET_SHA256
    claim = CTRL.expected_review_claim(packet, "3" * 64)
    assert claim["training_supervisor_sha256"] == "a" * 64
    assert claim["training_cells"] == 48
    assert claim["training_seeds"] == 8
    assert claim["execution_host"] == "mini"
    assert claim["one_training_execution_authorized"] is True
    assert claim["v11_inference_authorized"] is False
    assert claim["fresh_report_states_materialized"] is False
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
    assert claim["supervisor_handled_signals"] == [
        "SIGHUP", "SIGINT", "SIGTERM"]
    assert claim["supervisor_signals_deferred_until_child_registered"] is True
    assert claim["supervisor_terminates_all_owned_children"] is True
    assert claim["supervisor_orphaned_cells_authorized"] is False
    assert claim["supervisor_resume_authorized"] is False
    assert claim["supervisor_retry_authorized"] is False
    assert packet["result_contract"]["supervision"] == {
        "max_concurrent_cells": 8,
        "heartbeat_seconds": 30,
        "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
        "signals_deferred_until_child_registered": True,
        "terminates_all_owned_children": True,
        "orphaned_cells_authorized": False,
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
    monkeypatch.setattr(
        CTRL.LABEL, "_load_v11",
        lambda: pytest.fail("V11 must not load in the training controller"))
    monkeypatch.setattr(
        CTRL, "_validate_label_shard_without_v11",
        lambda *args, **kwargs: None)
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
        state_set={"states": states}, aggregate=aggregate,
        fresh_report=_fresh_report(), fresh_report_review=_fresh_review())
    assert opened == [str(path) for path in expected_paths]
    assert dataset["report_label_shard_files_opened"] == 0
    assert dataset["report_rows_included"] is False
    assert dataset["fresh_report_states_materialized"] is False
    assert "sealed_report_shards" not in dataset
    assert dataset["candidate_provenance_contract"] == {
        "teacher_targets": "mc_counterfactual_signed_level_utility",
        "all_reviewed_candidate_actions_retained": True,
        "candidate_actions_authenticated_by_reviewed_capture": True,
        "candidate_source_tags_in_examples": False,
        "candidate_source_tags_in_model_inputs": False,
        "v11_origin_actions_are_source_agnostic_examples": True,
        "v11_checkpoint_use_after_label_generation": "none",
        "training_controller_loads_v11": False,
        "training_runtime_loads_v11": False,
        "v11_proposer_admitted_for_inference": False,
        "inference_must_not_load_v11": True,
    }
    assert {split: {surface: len(values) for surface, values in surfaces.items()}
            for split, surfaces in dataset["examples"].items()} \
        == CTRL.EXPECTED_SURFACES


def test_label_shard_revalidation_never_reconstructs_v11_proposals(
        monkeypatch) -> None:
    schedule = {
        "split": "DESIGN", "local_shard": 0,
        "state_ids": ["state-0"], "state_ids_sha256": "1" * 64,
        "audit_state_ids": [], "state_count": 1,
        "candidate_worlds": 10,
    }
    packet = {
        "external_sha256": "2" * 64,
        "producer": {"git": "a" * 40},
        "parents": {"state_set": {"external_sha256": "3" * 64}},
        "schedule": {"schedule_sha256": "4" * 64, "shards": [schedule]},
    }
    row = {"state_id": "state-0", "status": "COMPLETE",
           "row_sha256": "5" * 64}
    work = {"candidate_worlds_attempted": 10}
    shard = {
        "schema": CTRL.LABEL_CTRL.SHARD_SCHEMA,
        "run_id": CTRL.LABEL_CTRL.RUN_ID,
        "git": "a" * 40,
        "controller_packet_sha256": "2" * 64,
        "label_receipt_sha256": "6" * 64,
        "state_set_sha256": "3" * 64,
        "schedule_sha256": "4" * 64,
        "shard_index": 0,
        "split": "DESIGN",
        "local_shard": 0,
        "state_ids": ["state-0"],
        "state_ids_sha256": "1" * 64,
        "audit_state_ids": [],
        "shard_admission_slot":
            CTRL.LABEL_CTRL.shard_admission_logical_path(0),
        "shard_admission_file_sha256": "7" * 64,
        "status": "COMPLETE",
        "complete_rows": 1,
        "refused_rows": 0,
        "rows": [row],
        "row_sha256s": ["5" * 64],
        "work": work,
        "expected_candidate_worlds": 10,
        "candidate_world_ceiling_respected": True,
        "training_authorized": False,
        "report_open_authorized": False,
    }
    shard["shard_sha256"] = CTRL.LABEL._self_hash(shard, "shard_sha256")
    checked = []
    monkeypatch.setattr(
        CTRL.CAPTURE, "_validate_candidates",
        lambda *args, **kwargs: pytest.fail("V11 proposal reconstruction ran"))
    monkeypatch.setattr(
        CTRL.LABEL, "_validate_shard_slot", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        CTRL.LABEL, "_state_map",
        lambda state_set: {"state-0": state_set["states"][0]})
    monkeypatch.setattr(CTRL.CAPTURE, "replay_state", lambda state: object())
    monkeypatch.setattr(
        CTRL.LABEL, "validate_label_row",
        lambda state, rnd, value, audit_expected: checked.append(value))
    monkeypatch.setattr(CTRL.LABEL, "_work_from_rows", lambda rows: work)
    CTRL._validate_label_shard_without_v11(
        shard, packet=packet, receipt_sha256="6" * 64,
        state_set={"states": [{"state_id": "state-0"}]}, index=0)
    assert checked == [row]


def test_fresh_report_digest_changes_training_packet(monkeypatch) -> None:
    monkeypatch.setattr(
        CTRL, "_source_sha256s",
        lambda: {path: "a" * 64 for path in CTRL.SOURCE_PATHS})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {
        "host": "mini", "python": "3.14", "torch": "2.13",
        "numpy": "2.5", "device": "cpu", "cpu_threads_per_cell": 1,
        "max_concurrent_cells": 8,
    })
    before = CTRL.build_packet(
        git="a" * 40, dataset=_dataset(), dataset_external_sha256="8" * 64,
        aggregate=_aggregate(), fresh_report=_fresh_report(),
        fresh_report_review=_fresh_review())
    changed = _fresh_report()
    changed["sealed_selection"]["fresh_report_state_ids_sha256"] = "9" * 64
    changed_dataset = _dataset()
    changed_dataset["fresh_report_selection"] = \
        CTRL.fresh_report_dataset_contract(changed, _fresh_review())
    changed_dataset["dataset_sha256"] = CTRL.self_hash(
        changed_dataset, "dataset_sha256")
    after = CTRL.build_packet(
        git="a" * 40, dataset=changed_dataset,
        dataset_external_sha256="9" * 64,
        aggregate=_aggregate(), fresh_report=changed,
        fresh_report_review=_fresh_review())
    assert before["packet_sha256"] != after["packet_sha256"]


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
