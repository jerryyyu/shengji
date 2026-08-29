"""Public-report and pre-play binding witnesses for PT-Sol0."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from shengji.rl import privileged_teacher_full_ab as full
from shengji.rl import privileged_teacher_sol0 as sol0
from shengji.rl import privileged_teacher_sol0_report as report


_SECRET = b"pt-full-private-seed-material!!!"


def _work(searches: int = 1) -> dict[str, int]:
    values = {field: 0 for field in full._WORK_FIELDS}
    values.update({
        "search_calls": searches,
        "rollouts": 660 * searches,
        "sample_attempts": 330 * searches,
        "accepted_worlds": 330 * searches,
        "verified_rollouts": 660 * searches,
    })
    return values


def _telemetry() -> dict[str, int]:
    values = {field: 0 for field in sol0.PUBLIC_TELEMETRY_FIELDS}
    values.update({
        "treatment_decisions": 3,
        "forced_decisions": 1,
        "contested_decisions": 2,
        "observe_calls": 2,
        "rollout_calls": 1,
        "unique_rollouts": 2,
        "candidate_zero_selections": 1,
        "selected_differs_from_candidate_zero": 1,
    })
    return values


def _outcome() -> sol0.Sol0Outcome:
    continuations = {name: 0 for name in sol0.CONTINUATIONS}
    continuations["smart-all"] = 2
    confidence = {name: 0 for name in sol0.CONFIDENCE_LEVELS}
    confidence["low"] = 2
    return sol0.Sol0Outcome(
        attacker_points=40,
        signed_level_utility=1,
        decision_count=60,
        telemetry=_telemetry(),
        continuation_counts=continuations,
        confidence_counts=confidence,
        opponent_work=_work(),
        transcript_sha256="a" * 64,
        model_output_sha256="b" * 64,
        model_exit_code=0,
        model_wall_milliseconds=1000,
    )


def _parent(role: str = "banker-team") -> dict[str, object]:
    treatment = 0 if role == "banker-team" else 1
    return {
        "treatment_team": treatment,
        "root_sha256": "c" * 64,
        "record_sha256": "d" * 64,
        "anchors": {
            "A": {"attacker_points": 80, "signed_level_utility": -1},
            "B": {"attacker_points": 120, "signed_level_utility": 1},
        },
        "arms": {
            "C0-S": {"attacker_points": 80,
                      "signed_level_utility": -1},
        },
    }


def _design(**kwargs) -> report.Sol0Design:
    values = {
        "seed_commitment_sha256": "1" * 64,
        "execution_git": "2" * 40,
        "native_sha256": "3" * 64,
        "hostname": full.MINI_HOSTNAME,
        "c0_external_sha256": "4" * 64,
        "c0_report_sha256": "5" * 64,
        "c0_execution_git": "6" * 40,
        "full_external_sha256": "7" * 64,
        "full_report_sha256": "8" * 64,
        "full_execution_git": "9" * 40,
        "codex_binary_sha256": "a" * 64,
        "codex_version": "codex-test",
        "python_binary_sha256": "b" * 64,
        "python_version": "python-test",
        "tool_script_sha256": "c" * 64,
    }
    values.update(kwargs)
    return report.Sol0Design(**values)


def test_design_binds_luna_without_changing_the_sol_default():
    sol_design = _design()
    assert sol_design.payload()["model"] == sol0.MODEL
    assert sol_design.payload()["planner_config"]["model"] == sol0.MODEL
    assert "planner_model" not in report.Sol0Design.__dataclass_fields__


def test_public_record_contains_hashes_and_aggregates_not_private_state():
    row = report._record_payload(
        coordinate=("2", 0, 0), role="banker-team", parent=_parent(),
        outcome=_outcome(), private_evidence_sha256="e" * 64)
    assert row["status"] == "COMPLETE"
    assert row["contrasts"] == {
        "sol0_minus_a": 2,
        "sol0_minus_b": 0,
        "sol0_minus_c0_s": 2,
    }
    assert not set(row).intersection({
        "hands", "buried", "events", "model_output", "candidates"})
    assert row["sol0"]["transcript_sha256"] == "a" * 64


def test_exact_opponent_work_check_can_fail():
    payload = _outcome().payload()
    report._validate_outcome(payload, banker=0, treatment_team=0)
    corrupted = copy.deepcopy(payload)
    corrupted["opponent_work"]["rollouts"] = 0
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="outcome identity drift"):
        report._validate_outcome(corrupted, banker=0, treatment_team=0)


def test_both_role_roots_are_bound_before_any_external_play(monkeypatch,
                                                            tmp_path: Path):
    design = full.FullABDesign(
        seed_commitment_sha256=hashlib.sha256(_SECRET).hexdigest(),
        execution_git="a" * 40, native_sha256="b" * 64,
        hostname=full.MINI_HOSTNAME)
    coordinate = design.root_coordinates[0]
    root = full._build_root(design, _SECRET, *coordinate)
    root_sha = full._root_sha256(root)
    parents = {
        (*coordinate, "banker-team"):
            {**_parent("banker-team"), "root_sha256": root_sha},
        (*coordinate, "attacker-team"):
            {**_parent("attacker-team"), "root_sha256": "f" * 64},
    }
    calls = {"count": 0}

    def forbidden(**_kwargs):
        calls["count"] += 1
        raise AssertionError("external planner must not start")

    monkeypatch.setattr(report, "_run_role", forbidden)
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="reconstructed C0 root drift"):
        report._run_root(
            full_design=design, c0_records=parents,
            seed_secret=_SECRET, coordinate=coordinate,
            private_root=tmp_path, tool_script=Path(__file__),
            codex_binary=Path(__file__), planner_process=None,
            planner_config=report.Sol0PlannerConfig(),
            role_completed=None)
    assert calls["count"] == 0


def test_incomplete_record_keeps_anchor_and_attempt_identity():
    row = report._record_payload(
        coordinate=("2", 0, 0), role="banker-team", parent=_parent(),
        outcome=None, private_evidence_sha256="e" * 64,
        failure_sha256="f" * 64)
    assert row["status"] == "INCOMPLETE"
    assert row["sol0"] is None and row["contrasts"] is None
    assert row["anchors"]["C0-S"]["attacker_points"] == 80
