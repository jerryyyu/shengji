from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

import teacher_stage_c_expanded_play_report_controller as CTRL


def _states() -> list[dict]:
    dimensions = CTRL.CAP.EXPECTED_PLAY_SCOPE
    values = []
    for index in range(480):
        values.append({
            "state_id": f"play-{index:03d}",
            "surface_type": "play",
            "stratum": dimensions["stratum"][index % len(
                dimensions["stratum"])],
            "phase": dimensions["phase"][index % len(
                dimensions["phase"])],
            "role": dimensions["role"][index % len(dimensions["role"])],
            "surface": dimensions["position"][index % len(
                dimensions["position"])],
            "candidates": [0, 1],
        })
    return values


def test_report_schedule_is_eight_equal_play_only_shards(monkeypatch) -> None:
    states = _states()
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 7)
    schedule = CTRL.build_report_schedule(states, surface="play")
    assert schedule["surface"] == "play"
    assert schedule["states"] == 480
    assert [shard["state_count"] for shard in schedule["shards"]] \
        == [60] * 8
    assert schedule["candidate_world_ceiling"] == 480 * 7
    assert schedule["schedule_sha256"] == CTRL._manifest_hash({
        key: value for key, value in schedule.items()
        if key != "schedule_sha256"
    })

    with pytest.raises(CTRL.ReportControllerRefused, match="surface drift"):
        CTRL.build_report_schedule(states, surface="bury")


def test_runtime_commands_bind_git_once_and_parse() -> None:
    import teacher_stage_c_report_runtime as runtime_module
    import teacher_stage_c_report_supervisor as supervisor_module

    schedule = CTRL.build_report_schedule(_states(), surface="play")
    commands = CTRL._commands(schedule)
    substitutions = {
        "{python}": "/pinned/python",
        "{git}": "a" * 40,
        "{packet_sha256}": "b" * 64,
        "{controller_review_record}": "/review/controller.md",
        "{fresh_report_review_record}": "/review/fresh.md",
        "{state_set_review_record}": "/review/states.md",
        "{receipt_sha256}": "c" * 64,
    }

    def expand(command: list[str]) -> list[str]:
        return [substitutions.get(value, value) for value in command]

    runtime = [commands["admit"], *commands["run_shards"],
               commands["evaluate"]]
    for command in runtime:
        expanded = expand(command)
        assert expanded.count("--expected-git") == 1
        parsed = runtime_module.parser().parse_args(expanded[2:])
        assert parsed.expected_git == "a" * 40

    supervise = expand(commands["supervise"])
    assert supervise.count("--expected-git") == 1
    parsed_supervisor = supervisor_module.parser().parse_args(supervise[2:])
    assert parsed_supervisor.expected_git == "a" * 40


@pytest.mark.parametrize(("wrapper", "expressions", "expected"), [
    (
        "teacher_stage_c_expanded_play_report_runtime",
        ("wrapper.BASE.CTRL.RUN_ID", "wrapper.BASE.RECEIPT_SCHEMA"),
        (CTRL.RUN_ID, CTRL.RUNTIME_RECEIPT_SCHEMA),
    ),
    (
        "teacher_stage_c_expanded_play_report_supervisor",
        ("wrapper.BASE.CTRL.RUN_ID", "wrapper.BASE.SCHEMA",
         "wrapper.BASE.REVIEW_MARKER"),
        (CTRL.RUN_ID, CTRL.SUPERVISOR_SCHEMA,
         CTRL.SUPERVISOR_REVIEW_MARKER),
    ),
])
def test_wrappers_select_expanded_play_controller(
        wrapper, expressions, expected) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(CTRL.REPO / "server"), str(CTRL.REPO / "server/scripts")))
    code = f"import {wrapper} as wrapper; " + "; ".join(
        f"print({expression})" for expression in expressions)
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=CTRL.REPO, check=True,
        capture_output=True, text=True, env=env)
    assert tuple(completed.stdout.splitlines()) == expected


def test_controller_review_grants_one_report_but_no_strength() -> None:
    scope = CTRL.CAP._play_scope_contract(_states())
    packet = {
        "producer": {"git": "a" * 40, "sources": {
            "server/scripts/teacher_stage_c_expanded_play_report_controller.py":
                "1" * 64,
            CTRL.RUNTIME_SCRIPT_PATH: "2" * 64,
            CTRL.SUPERVISOR_SCRIPT_PATH: "3" * 64,
            "server/scripts/teacher_stage_c_report_runtime.py": "4" * 64,
            "server/scripts/teacher_stage_c_report_supervisor.py": "5" * 64,
        }},
        "packet_sha256": "6" * 64,
        "parents": {
            "capability_packet": {
                "external_sha256": "7" * 64,
                "review_record_sha256": "8" * 64,
                "review_claim_sha256": "9" * 64,
            },
            "fresh_report_selection": {
                "sealed_selection_sha256": "a" * 64,
            },
        },
        "selected_capability": copy.deepcopy(CTRL.CAP.EXPECTED_CAPABILITY),
        "play_scope_contract": scope,
        "checkpoint_manifest": [{}] * 8,
        "runtime_contract": {
            "host": "mini", "python": "3.14", "torch": "2.13",
            "numpy": "2.5"},
        "report_schedule": {
            "schedule_sha256": "b" * 64,
            "candidate_world_ceiling": 123,
        },
        "report_contract": {
            "states": 480,
            "durable_report_open_admission_slot": (
                f"server/runs/locks/{CTRL.RUN_ID}.report-open.consumed.json"),
        },
    }
    claim = CTRL.expected_review_claim(packet, "c" * 64)
    assert claim["play_scope_contract"] == scope
    assert claim["one_report_execution_authorized"] is True
    assert claim["composition_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_runtime_reuses_reviewed_capability_without_rescoring_training(
        monkeypatch, tmp_path: Path) -> None:
    capability = tmp_path / "capability.json"
    capability_review = tmp_path / "capability-review.md"
    evidence = tmp_path / "training"
    training_review = tmp_path / "training-review.md"
    capture = tmp_path / "capture"
    state_review = tmp_path / "state-review.md"
    fresh_review = tmp_path / "fresh-review.md"
    bury_review = tmp_path / "bury-review.md"
    frozen = {
        "parents": {
            "capability_packet": {
                "absolute_path": str(capability),
                "external_sha256": "1" * 64,
                "review_record_absolute_path": str(capability_review),
            },
            "training_evidence": {
                "absolute_path": str(evidence),
                "training_result_review_record_absolute_path":
                    str(training_review),
            },
            "capture_evidence": {
                "absolute_path": str(capture),
                "state_set_review_record_absolute_path": str(state_review),
                "fresh_report_review_record_absolute_path": str(fresh_review),
                "bury_result_review_record_absolute_path": str(bury_review),
            },
        },
    }
    frozen["packet_sha256"] = CTRL.self_hash(frozen, "packet_sha256")
    packet_path = tmp_path / CTRL.PACKET_PATH
    packet_path.parent.mkdir(parents=True)
    packet_path.write_bytes(CTRL.canonical_json(frozen))
    external = CTRL.sha256_file(packet_path)
    inputs = ({}, {}, {}, {}, [])
    calls = []

    def fake_inputs(**kwargs):
        calls.append(kwargs)
        return inputs

    def fake_build_packet(**kwargs):
        assert kwargs["_validated_inputs"] is inputs
        return frozen

    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL, "_build_inputs", fake_inputs)
    monkeypatch.setattr(CTRL, "build_packet", fake_build_packet)
    monkeypatch.setattr(CTRL, "_git", lambda *_args: "a" * 40)
    result = CTRL.validate_runtime_packet(
        path=packet_path, expected_sha256=external,
        fresh_report_review_record=fresh_review,
        state_set_review_record=state_review)
    assert result == (frozen, {}, {}, {}, [])
    assert len(calls) == 1
    assert calls[0]["recompute_capability"] is False
