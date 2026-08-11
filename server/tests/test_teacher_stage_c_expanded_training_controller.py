from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

import teacher_stage_c_expanded_training_controller as CTRL
from shengji.rl import stage_c_model as MODEL


def _v1_target(*, hard_tail: bool = False) -> dict:
    value = {
        "schema": "teacher-stage-c-model-target-v1",
        "candidate_count": 3,
        "ranking_mean_signed_level_utility": [-0.5, 0.5, -1.5],
        "outcome_mean_signed_level_utility": [-0.5, 1.5, -1.5],
        "deeper_report_pair": ({
            "candidate_indices": [0, 1],
            "worlds": MODEL.HARD_REPORT_WORLDS,
            "replaced_all_candidate_pair": True,
        } if hard_tail else None),
    }
    value["target_sha256"] = CTRL.self_hash(value, "target_sha256")
    return value


def test_upgrade_target_adds_protected_candidate_zero_objective() -> None:
    ordinary = CTRL._upgrade_target(_v1_target())
    assert ordinary["schema"] == MODEL.TARGET_SCHEMA
    assert ordinary["candidate0_relative_advantage"] == pytest.approx(
        [0.0, 1.0, -1.0])
    assert ordinary["candidate0_relative_weight"] == [0.0, 1.0, 1.0]
    assert ordinary["target_sha256"] == CTRL.self_hash(
        ordinary, "target_sha256")

    hard_tail = CTRL._upgrade_target(_v1_target(hard_tail=True))
    assert hard_tail["candidate0_relative_advantage"] == pytest.approx(
        [0.0, 2.0, -1.0])
    assert hard_tail["candidate0_relative_weight"] == pytest.approx(
        [0.0, MODEL.HARD_REPORT_WORLDS / MODEL.HARD_SELECTION_WORLDS, 1.0])


def test_upgrade_target_refuses_identity_and_deeper_pair_drift() -> None:
    target = _v1_target()
    target["ranking_mean_signed_level_utility"][1] = 3.5
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="target identity"):
        CTRL._upgrade_target(target)

    target = _v1_target(hard_tail=True)
    target["deeper_report_pair"]["candidate_indices"] = [1, 2]
    target["target_sha256"] = CTRL.self_hash(target, "target_sha256")
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="deeper-pair"):
        CTRL._upgrade_target(target)


def test_schedule_is_a_matched_two_recipe_eight_seed_matrix() -> None:
    schedule = CTRL.build_schedule()
    assert schedule["cell_count"] == 96
    assert schedule["loss_recipes"] == list(MODEL.LOSS_RECIPES)
    assert schedule["single_seed_selection"] is False
    assert schedule["report_rows_included"] is False
    assert schedule["matched_ab_states_seeds_initialization_epochs"] is True

    matched: dict[tuple[str, int, float], list[dict]] = {}
    for cell in schedule["cells"]:
        key = (cell["surface"], cell["seed"], cell["curve_fraction"])
        matched.setdefault(key, []).append(cell)
    assert len(matched) == (
        len(MODEL.SURFACES)
        * len(MODEL.TRAINING_SEEDS)
        * len(MODEL.CURVE_FRACTIONS)
    )
    for pair in matched.values():
        assert {cell["loss_recipe"] for cell in pair} == set(
            MODEL.LOSS_RECIPES)
        assert len(pair) == 2
        assert pair[0]["design_states"] == pair[1]["design_states"]
        assert pair[0]["calib_states"] == pair[1]["calib_states"]
        assert pair[0]["epoch_grid"] == pair[1]["epoch_grid"]


def test_expanded_result_claim_opens_packet_review_not_training() -> None:
    packet = {
        "producer": {"git": "a" * 40},
        "schedule": {"schedule_sha256": "b" * 64},
        "result_contract": {
            "max_candidate_worlds": 13_136_320,
            "max_sampler_attempts": 89_278_720,
        },
    }
    aggregate = {
        "aggregate_sha256": "c" * 64,
        "work": {
            "candidate_worlds_attempted": 13_136_320,
            "candidate_worlds_completed": 13_136_320,
            "sampler_attempts": 2_231_968,
        },
    }
    claim = CTRL.expected_expanded_label_result_claim(
        aggregate=aggregate,
        aggregate_external_sha256="d" * 64,
        packet=packet,
        receipt_external_sha256="e" * 64,
    )
    assert claim["complete_rows"] == 5_504
    assert claim["refused_rows"] == 0
    assert claim["reused_labels_not_recomputed"] == 1_536
    assert claim["sealed_report_states"] == 512
    assert claim["one_expanded_training_controller_freeze_authorized"] is True
    assert claim["training_authorized"] is False
    assert claim["report_open_authorized"] is False
    assert claim["strength_claim"] is False


@pytest.mark.parametrize(
    "occupied",
    ("dataset", "dataset.partial", "packet", "packet.partial"),
)
def test_freeze_preflights_both_outputs_and_partials(
        monkeypatch, tmp_path: Path, occupied: str) -> None:
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL, "DATASET_PATH", "dataset.json")
    monkeypatch.setattr(CTRL, "PACKET_PATH", "packet.json")
    dataset = tmp_path / "dataset.json"
    packet = tmp_path / "packet.json"
    paths = {
        "dataset": dataset,
        "dataset.partial": Path(str(dataset) + ".partial"),
        "packet": packet,
        "packet.partial": Path(str(packet) + ".partial"),
    }
    paths[occupied].write_text("occupied\n")
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="existing output"):
        CTRL.require_freeze_outputs_available(dataset, packet)


def test_runtime_parent_check_binds_sealed_report_and_label_aggregate() -> None:
    sealed = {
        "states": 512,
        "state_ids_sha256": "1" * 64,
        "state_material_sha256": "2" * 64,
    }
    dataset = {
        "dataset_sha256": "3" * 64,
        "sealed_report_selection": sealed,
        "expanded_labels": {"aggregate_sha256": "4" * 64},
    }
    packet = {
        "parents": {
            "model_dataset": {
                "internal_sha256": dataset["dataset_sha256"],
                "design_states": 5_632,
                "calib_states": 1_408,
                "report_rows_included": False,
                "sealed_report_selection_sha256":
                    CTRL._manifest_hash(sealed),
            },
            "expanded_labels": {
                "controller_packet_sha256":
                    CTRL.EXPANDED_LABEL_CONTROLLER_SHA256,
                "aggregate_sha256": "4" * 64,
                "new_states": 5_504,
            },
        },
    }
    CTRL.validate_runtime_packet_parents(packet, dataset)
    drifted = copy.deepcopy(packet)
    drifted["parents"]["model_dataset"][
        "sealed_report_selection_sha256"] = "f" * 64
    with pytest.raises(
            CTRL.TrainingControllerRefused, match="parent drift"):
        CTRL.validate_runtime_packet_parents(drifted, dataset)


@pytest.mark.parametrize(
    "script",
    (
        "teacher_stage_c_expanded_training_runtime.py",
        "teacher_stage_c_expanded_training_supervisor.py",
    ),
)
def test_wrappers_select_expanded_controller(script: str) -> None:
    path = CTRL.REPO / "server/scripts" / script
    completed = subprocess.run(
        [sys.executable, str(path), "--help"],
        cwd=CTRL.REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "expanded" in path.name
