from __future__ import annotations

import copy
from pathlib import Path

import pytest

import teacher_stage_c_protected_anchor_controller as CTRL


def _example(means: list[float], *, state_id: str = "s") -> dict:
    return {
        "state_id": state_id,
        "target": {
            "candidate_count": len(means),
            "ranking_mean_signed_level_utility": means,
        },
    }


def _cohort_row(threshold: float, median: float,
                positive: int = 8) -> dict:
    return {
        "threshold": threshold,
        "cohort": {
            "positive_seeds": positive,
            "median_teacher_improvement_vs_candidate0": median,
        },
    }


def test_protected_policy_uses_strict_margin_and_candidate0_fallback() -> None:
    examples = [_example([0.0, 0.2, 1.0])]
    ranks = [[0.0, 0.1, 0.2]]
    tied = CTRL.protected_metrics(examples, ranks, threshold=0.2)
    assert tied["overrides"] == 0
    assert tied["mean_teacher_improvement_vs_candidate0"] == 0.0

    active = CTRL.protected_metrics(examples, ranks, threshold=0.199)
    assert active["overrides"] == 1
    assert active["helpful_overrides"] == 1
    assert active["mean_teacher_improvement_vs_candidate0"] == 1.0


def test_protected_policy_selects_best_alternative_not_candidate0() -> None:
    examples = [_example([0.0, -2.0, 0.5])]
    metrics = CTRL.protected_metrics(
        examples, [[10.0, 10.3, 10.5]], threshold=0.2)
    assert metrics["overrides"] == 1
    assert metrics["helpful_overrides"] == 1
    assert metrics["mean_teacher_improvement_vs_candidate0"] == 0.5


def test_ensemble_is_mean_rank_logit_per_candidate() -> None:
    rows = CTRL.ensemble_rank_rows([
        [[0.0, 1.0], [2.0, 4.0, 6.0]],
        [[2.0, 3.0], [4.0, 8.0, 12.0]],
    ])
    assert rows == [[1.0, 2.0], [3.0, 6.0, 9.0]]


def test_design_threshold_selection_ignores_calib_preferences() -> None:
    design = [_cohort_row(value, 0.01 - abs(value - 0.2))
              for value in CTRL.THRESHOLD_GRID]
    assert CTRL.choose_design_threshold(design) == 0.2

    # A separate CALIB table can prefer another threshold; it is not an input
    # to the selector and therefore cannot move the frozen DESIGN choice.
    calib = [_cohort_row(value, 1.0 if value == 0.5 else -1.0)
             for value in CTRL.THRESHOLD_GRID]
    assert CTRL.choose_design_threshold(design) == 0.2
    assert CTRL.choose_design_threshold(calib) == 0.5


def test_design_threshold_tie_prefers_more_seeds_then_lower_threshold() -> None:
    rows = [_cohort_row(value, -1.0, 0)
            for value in CTRL.THRESHOLD_GRID]
    by_threshold = {value["threshold"]: value for value in rows}
    by_threshold[0.1]["cohort"].update(
        median_teacher_improvement_vs_candidate0=0.01,
        positive_seeds=7,
    )
    by_threshold[0.2]["cohort"].update(
        median_teacher_improvement_vs_candidate0=0.01,
        positive_seeds=8,
    )
    assert CTRL.choose_design_threshold(rows) == 0.2
    by_threshold[0.1]["cohort"]["positive_seeds"] = 8
    assert CTRL.choose_design_threshold(rows) == 0.1


def test_review_claim_is_bounded_before_external_review() -> None:
    packet = {
        "producer": {"git": "a" * 40},
        "packet_sha256": "b" * 64,
        "parent": {
            "training_aggregate_sha256": "c" * 64,
            "terminal_decision": "SELECT_NONE",
        },
        "checkpoint_manifest_sha256": "d" * 64,
        "diagnostics_sha256": "e" * 64,
        "capability": {
            "surface": "play", "head": "ranking", "epoch": 32,
            "threshold": 0.2, "seeds": list(CTRL.MODEL.TRAINING_SEEDS),
        },
        "diagnostics": {
            "selected_design": {
                "cohort": {
                    "positive_seeds": 8,
                    "median_teacher_improvement_vs_candidate0": 0.01,
                },
                "ensemble": {
                    "mean_teacher_improvement_vs_candidate0": 0.02,
                },
            },
            "selected_calib": {
                "cohort": {
                    "positive_seeds": 7,
                    "median_teacher_improvement_vs_candidate0": 0.005,
                },
                "ensemble": {
                    "mean_teacher_improvement_vs_candidate0": 0.006,
                },
            },
        },
    }
    claim = CTRL.expected_review_claim(packet, "f" * 64)
    assert claim["one_protected_report_controller_freeze_authorized"] is True
    assert claim["report_open_authorized"] is False
    assert claim["report_execution_authorized"] is False
    assert claim["composition_authorized"] is False
    assert claim["whole_game_screen_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_packet_self_hash_detects_authority_mutation() -> None:
    packet = {
        "schema": CTRL.SCHEMA,
        "authority": {"report_open_authorized": False},
    }
    packet["packet_sha256"] = CTRL.self_hash(packet, "packet_sha256")
    changed = copy.deepcopy(packet)
    changed["authority"]["report_open_authorized"] = True
    assert changed["packet_sha256"] != CTRL.self_hash(
        changed, "packet_sha256")


def test_json_loader_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}\n")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(CTRL.ProtectedAnchorRefused, match="regular/unlinked"):
        CTRL.load_json(link)


def test_parent_replay_requires_executed_source_identity(
        monkeypatch, tmp_path: Path) -> None:
    current = tmp_path / "current"
    evidence = tmp_path / "evidence"
    logical = "server/scripts/runtime.py"
    (current / "server/scripts").mkdir(parents=True)
    (evidence / "server/scripts").mkdir(parents=True)
    (current / logical).write_text("same\n")
    (evidence / logical).write_text("same\n")
    monkeypatch.setattr(CTRL, "REPO", current)
    monkeypatch.setattr(CTRL.TRAIN_CTRL, "SOURCE_PATHS", (logical,))
    CTRL._require_parent_runtime_identity(evidence)
    (evidence / logical).write_text("different\n")
    with pytest.raises(CTRL.ProtectedAnchorRefused, match="source drift"):
        CTRL._require_parent_runtime_identity(evidence)


def test_parent_constants_bind_terminal_select_none_without_report() -> None:
    assert CTRL.PARENT_GIT == "18a6fa133c16973206b9f19cccba493476714bee"
    assert CTRL.TRAINING_AGGREGATE_SHA256 == (
        "7023b3aa08f399d582576b9998e5078db56d82a91eb2a41db228b4e2572fc4fb"
    )
    assert CTRL.SURFACE == "play"
    assert CTRL.HEAD == "ranking"
    assert CTRL.EPOCH == 32
    assert CTRL.EXPECTED_SELECTED_THRESHOLD == 0.2
