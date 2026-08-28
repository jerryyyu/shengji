"""Adversarial witnesses for the paired PT-Luna0 public boundary."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from shengji.rl import privileged_teacher_full_ab as full
from shengji.rl import privileged_teacher_luna0_report as report
from shengji.rl import privileged_teacher_sol0 as sol0


def _design(**changes):
    values = {
        "seed_commitment_sha256": "1" * 64, "execution_git": "2" * 40,
        "native_sha256": "3" * 64, "hostname": full.MINI_HOSTNAME,
        "c0_external_sha256": "4" * 64, "c0_report_sha256": "5" * 64,
        "c0_execution_git": "6" * 40, "full_external_sha256": "7" * 64,
        "full_report_sha256": "8" * 64, "full_execution_git": "9" * 40,
        "codex_binary_sha256": "a" * 64, "codex_version": "codex-test",
        "python_binary_sha256": "b" * 64, "python_version": "python-test",
        "tool_script_sha256": "c" * 64, "sol0_external_sha256": "d" * 64,
        "sol0_report_sha256": "e" * 64, "sol0_execution_git": "f" * 40,
        "sol0_design_sha256": "0" * 64,
    }
    values.update(changes)
    return report.Luna0Design(**values)


def _parent(role="banker-team"):
    return {
        "treatment_team": 0 if role == "banker-team" else 1,
        "root_sha256": "c" * 64, "record_sha256": "d" * 64,
        "anchors": {"A": {"attacker_points": 80, "signed_level_utility": -1},
                    "B": {"attacker_points": 120, "signed_level_utility": 1}},
        "arms": {"C0-S": {"attacker_points": 80, "signed_level_utility": -1}},
    }


def _solrow():
    return {"status": "COMPLETE", "record_sha256": "f" * 64,
            "sol0": {"signed_level_utility": 1,
                     "model_wall_milliseconds": 900}}


def _outcome():
    telemetry = {field: 0 for field in sol0.PUBLIC_TELEMETRY_FIELDS}
    telemetry.update({"treatment_decisions": 3, "forced_decisions": 1,
                      "contested_decisions": 2, "observe_calls": 2,
                      "rollout_calls": 1, "unique_rollouts": 2,
                      "candidate_zero_selections": 1,
                      "selected_differs_from_candidate_zero": 1})
    continuations = {name: 0 for name in sol0.CONTINUATIONS}
    continuations["smart-all"] = 2
    confidence = {name: 0 for name in sol0.CONFIDENCE_LEVELS}
    confidence["low"] = 2
    work = {field: 0 for field in full._WORK_FIELDS}
    work.update({"search_calls": 1, "rollouts": 660, "sample_attempts": 330,
                 "accepted_worlds": 330, "verified_rollouts": 660})
    return {**sol0.Sol0Outcome(
        attacker_points=40, signed_level_utility=1, decision_count=60,
        telemetry=telemetry, continuation_counts=continuations,
        confidence_counts=confidence, opponent_work=work,
        transcript_sha256="a" * 64, model_output_sha256="b" * 64,
        model_exit_code=0, model_wall_milliseconds=1000).payload(),
        "model_reported_tokens": 100}


def test_luna_design_is_dedicated_and_model_pinned():
    assert _design().payload()["model"] == report.MODEL
    assert _design().payload()["token_comparison"] == \
        report.TOKEN_COMPARISON_STATUS
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="model identity"):
        _design(planner_model=sol0.MODEL)


def test_luna_subprocess_witness_binds_luna_model_and_effort(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(sol0.subprocess, "run", lambda command, **kwargs:
                        observed.append((command, kwargs)) or
                        subprocess.CompletedProcess(command, 0, stdout=b""))
    sol0._default_planner_process(
        SimpleNamespace(config=report.Luna0PlannerConfig()),
        workspace=tmp_path, mailbox_path=tmp_path / "mailbox",
        tool_script=Path(__file__), codex_binary=Path("/bin/codex"),
        prompt="planner", final_output_path=tmp_path / "final.json")
    command, kwargs = observed[0]
    assert command[command.index("-m") + 1] == report.MODEL
    assert command[command.index("-c") + 1] == 'model_reasoning_effort="high"'
    assert kwargs["timeout"] == report.Luna0PlannerConfig().max_session_wall_seconds


def test_paired_record_has_four_utility_contrasts_and_no_hidden_state():
    row = report._record_payload(
        coordinate=("2", 0, 0), role="banker-team", parent=_parent(),
        sol_row=_solrow(), outcome=_outcome(), private_evidence_sha256="e" * 64)
    assert row["contrasts"] == {"luna0_minus_sol0": 0, "luna0_minus_a": 2,
                                "luna0_minus_b": 0, "luna0_minus_c0_s": 2}
    assert not set(row).intersection({"hands", "buried", "events", "candidates",
                                      "prompt", "model_output"})
    report._validate_outcome(row["luna0"], banker=0, treatment_team=0)
    assert report._summaries([row])["efficiency"]["candidate"] is None


def test_incomplete_record_is_retained_and_cannot_gain_contrasts(monkeypatch):
    design, public, parents = _full_report_fixture(incomplete=True)
    monkeypatch.setattr(report, "validate_sol_report", lambda *a, **k: None)
    monkeypatch.setattr(report, "_parent_maps", lambda *a, **k: parents)
    bad = copy.deepcopy(public)
    bad["records"][0]["contrasts"] = {"luna0_minus_sol0": 0,
                                        "luna0_minus_a": 0,
                                        "luna0_minus_b": 0,
                                        "luna0_minus_c0_s": 0}
    bad["records"][0]["record_sha256"] = report._sha({
        k: v for k, v in bad["records"][0].items() if k != "record_sha256"})
    bad["summaries"] = report._summaries(bad["records"])
    bad["report_sha256"] = report._sha({k: v for k, v in bad.items()
                                         if k != "report_sha256"})
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="incomplete"):
        report.validate_report(bad, design, c0_report={},
                               c0_external_sha256="4" * 64,
                               full_report={}, full_external_sha256="7" * 64,
                               sol0_report={}, sol0_external_sha256="d" * 64)


def test_authority_and_token_arithmetic_are_checked(monkeypatch):
    design, public, parents = _full_report_fixture()
    monkeypatch.setattr(report, "validate_sol_report", lambda *a, **k: None)
    monkeypatch.setattr(report, "_parent_maps", lambda *a, **k: parents)
    bad = copy.deepcopy(public)
    bad["records"][0]["authority"] = {**report.AUTHORITY,
                                        "merge_authorized": True}
    bad["records"][0]["record_sha256"] = report._sha({
        k: v for k, v in bad["records"][0].items() if k != "record_sha256"})
    bad["report_sha256"] = report._sha({k: v for k, v in bad.items()
                                         if k != "report_sha256"})
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="identity"):
        report.validate_report(bad, design, c0_report={},
                               c0_external_sha256="4" * 64,
                               full_report={}, full_external_sha256="7" * 64,
                               sol0_report={}, sol0_external_sha256="d" * 64)
    bad = copy.deepcopy(public)
    bad["summaries"]["efficiency"]["wall_milliseconds"]["luna"]["total"] += 1
    bad["report_sha256"] = report._sha({k: v for k, v in bad.items()
                                         if k != "report_sha256"})
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="identity"):
        report.validate_report(bad, design, c0_report={},
                               c0_external_sha256="4" * 64,
                               full_report={}, full_external_sha256="7" * 64,
                               sol0_report={}, sol0_external_sha256="d" * 64)
    bad = copy.deepcopy(public)
    bad["summaries"]["efficiency"]["luna_reported_tokens"]["total"] += 1
    bad["report_sha256"] = report._sha({k: v for k, v in bad.items()
                                         if k != "report_sha256"})
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="identity"):
        report.validate_report(bad, design, c0_report={},
                               c0_external_sha256="4" * 64,
                               full_report={}, full_external_sha256="7" * 64,
                               sol0_report={}, sol0_external_sha256="d" * 64)


def _full_report_fixture(incomplete=False):
    design = _design()
    c0_records = {}
    sol_records = {}
    records = []
    index = 0
    for coordinate in design.root_coordinates:
        for role in full.ROLES:
            key = (*coordinate, role)
            parent = _parent(role)
            c0_records[key] = parent
            sol_row = {**_solrow(), "record_sha256": "f" * 64}
            sol_records[key] = sol_row
            outcome = None if incomplete and index == 0 else _outcome()
            records.append(report._record_payload(
                coordinate=coordinate, role=role, parent=parent,
                sol_row=sol_row, outcome=outcome,
                private_evidence_sha256="e" * 64,
                failure_sha256="f" * 64 if outcome is None else None))
            index += 1
    body = {"schema": report.SCHEMA,
            "status": "INCOMPLETE" if incomplete else "COMPLETE",
            "design": design.payload(),
            "completed_record_count": len(records) - int(incomplete),
            "incomplete_record_count": int(incomplete),
            "refusal_count": int(incomplete), "records": records,
            "summaries": report._summaries(records),
            "elapsed_seconds": 0.0, "authority": dict(report.AUTHORITY)}
    return design, {**body, "report_sha256": report._sha(body)}, \
        (c0_records, sol_records)


def test_sol_parent_must_be_complete_and_exactly_52_roles():
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="not complete"):
        report._require_complete_sol_report({"status": "INCOMPLETE",
                                             "completed_record_count": 51,
                                             "incomplete_record_count": 1,
                                             "records": []})

    design = _design()
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in full.ROLES}
    records = [{"trump_rank": rank, "banker": banker,
                "replicate": replicate, "role": role}
               for rank, banker, replicate, role in expected]
    records[0]["role"] = "not-a-role"
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="population"):
        report._require_sol0_population({"records": records}, expected)


def test_luna_failure_preserves_source_failure_identity(monkeypatch, tmp_path):
    design, _public, parents = _full_report_fixture()
    coordinate = design.root_coordinates[0]
    role = full.ROLES[0]
    key = (*coordinate, role)
    source = {"elapsed_seconds": 0.0, "records": [{
        "trump_rank": coordinate[0], "banker": coordinate[1],
        "replicate": coordinate[2], "role": role, "status": "INCOMPLETE",
        "private_evidence_sha256": "e" * 64, "failure_sha256": "a" * 64,
    }]}
    monkeypatch.setattr(report, "validate_sol_report", lambda *a, **k: None)
    monkeypatch.setattr(report, "_parent_maps", lambda *a, **k: parents)
    monkeypatch.setattr(report.sol_report, "run_dev", lambda *a, **k: source)
    monkeypatch.setattr(report, "_sol_design", lambda _payload: object())
    monkeypatch.setattr(report.sol_report, "validate_parents",
                        lambda *a, **k: object())
    monkeypatch.setattr(report.sol_report, "_run_root",
                        lambda coordinate, **k: tuple(
                            {**source["records"][0], "trump_rank": coordinate[0],
                             "banker": coordinate[1], "replicate": coordinate[2],
                             "role": item_role}
                            for item_role in full.ROLES))
    monkeypatch.setattr(report, "_sha_bytes", lambda _raw: "1" * 64)
    monkeypatch.setattr(report.platform, "node", lambda: design.hostname)
    monkeypatch.setattr(report.subprocess, "run", lambda *a, **k:
                        type("Completed", (), {"stdout": "codex-test"})())
    design = _design(seed_commitment_sha256="1" * 64,
                     codex_binary_sha256="1" * 64,
                     python_binary_sha256="1" * 64,
                     tool_script_sha256="1" * 64,
                     python_version=__import__("sys").version)
    (tmp_path / "tool").write_bytes(b"tool")
    (tmp_path / "codex").write_bytes(b"codex")
    private_root = tmp_path / "private"
    private_root.mkdir()
    private_root.chmod(0o700)
    result = report.run_dev(
        design, c0_report={}, c0_external_sha256="4" * 64, full_report={},
        full_external_sha256="7" * 64, sol0_report={"design": {}},
        sol0_external_sha256="d" * 64, seed_secret=b"s" * 32,
        private_root=private_root, tool_script=tmp_path / "tool",
        codex_binary=tmp_path / "codex", workers=2)
    assert result["records"][0]["failure_sha256"] == "a" * 64
    assert result["records"][0]["luna0"] is None


def test_worker_source_population_guard_rejects_dropped_role():
    design = _design()
    rows = [{"trump_rank": rank, "banker": banker, "replicate": replicate,
             "role": role}
            for rank, banker, replicate in design.root_coordinates
            for role in full.ROLES]
    rows.pop()
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="population"):
        report._validate_source_population(rows, design)


def test_recursive_public_leakage_is_refused(monkeypatch):
    design, public, parents = _full_report_fixture()
    monkeypatch.setattr(report, "validate_sol_report", lambda *a, **k: None)
    monkeypatch.setattr(report, "_parent_maps", lambda *a, **k: parents)
    public["summaries"]["leak"] = {"hidden_cards": ["secret"]}
    public["report_sha256"] = report._sha({k: v for k, v in public.items()
                                            if k != "report_sha256"})
    with pytest.raises(report.PrivilegedTeacherLuna0Error, match="leakage"):
        report.validate_report(public, design, c0_report={},
                               c0_external_sha256="4" * 64,
                               full_report={}, full_external_sha256="7" * 64,
                               sol0_report={}, sol0_external_sha256="d" * 64)
