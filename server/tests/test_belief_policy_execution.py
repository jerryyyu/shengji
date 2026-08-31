"""Freeze derivation and capacity-receipt can-fail witnesses."""

from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from shengji.rl import belief_policy_execution as EXECUTION
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_policy_controller import CAPACITY_WORKER_ARMS
from shengji.rl.belief_policy_execution import (
    BeliefPolicyExecutionError,
    MAX_SCIENTIFIC_WALL_NANOSECONDS,
    authenticate_capacity_envelope_source,
    authenticate_scientific_freeze_review,
    build_freeze,
    validate_capacity_receipt,
    validate_freeze,
)


def _arm(workers: int) -> dict:
    tasks = [{
        "coordinate_index": index,
        "qualified": True,
        "wall_nanoseconds": 100,
        "cpu_nanoseconds": 90,
        "max_rss_bytes": 1_000,
        "reference_worlds": 256,
        "selection_physical_rollouts": 60,
        "report_physical_rollouts": 600,
    } for index in range(workers)]
    return {
        "workers": workers,
        "task_count": workers,
        "tasks": tasks,
        "wall_nanoseconds": 100,
        "cpu_nanoseconds": 90 * workers,
        "aggregate_cpu_utilization_ppb": 900_000_000 * workers,
        "max_child_rss_bytes": 1_000,
        "projected_process_rss_bytes": 1_000 * workers,
        "host_memory_bytes": 1_000_000,
        "swap_used_bytes_before": 0,
        "swap_used_bytes_after": 0,
        "passed": True,
    }


def _receipt() -> dict:
    return {
        "schema": "belief-r4-policy-capacity-receipt-v1",
        "execution_git": "1" * 40,
        "source_manifest_sha256": "2" * 64,
        "cpu_count": 16,
        "arms": [_arm(workers) for workers in CAPACITY_WORKER_ARMS],
        "selected_workers": 13,
        "headroom_workers": 15,
        "selected_max_root_wall_nanoseconds": 100,
        "scientific_wall_estimate_nanoseconds": 100 * 8 * 2,
        "contains_actions": False,
        "contains_outcomes": False,
        "r4_test_opened": False,
        "scientific_execution_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _envelope() -> dict:
    return {
        "schema": "belief-r4-policy-capacity-envelope-v1",
        "source": {
            "execution_git": "1" * 40,
            "file_count": 100,
            "source_manifest_sha256": "2" * 64,
        },
        "runtime": {"compatibility_sha256": "3" * 64},
        "models": {
            "r4_freeze_sha256": "4" * 64,
            "r4_admission_sha256": "5" * 64,
            "r4_review_marker_sha256": "6" * 64,
            "common_calibration_sha256": "7" * 64,
            "primary_trained_manifest_sha256": "8" * 64,
            "control_trained_manifest_sha256": "9" * 64,
            "primary_model_sha256s": [f"{index + 10:064x}"
                                       for index in range(8)],
            "control_model_sha256s": [f"{index + 20:064x}"
                                       for index in range(8)],
        },
        "source_review_commit": "5" * 40,
        "source_review_marker_sha256": "6" * 64,
        "receipt": _receipt(),
        "scientific_execution_authorized": False,
        "r4_test_opened": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def test_freeze_uses_predeclared_measured_pace_rule(tmp_path: Path):
    freeze = build_freeze(
        canonical_json_bytes(_envelope()),
        evidence_root=(tmp_path / "evidence").resolve(),
        model_root=(tmp_path / "models").resolve())
    validate_freeze(freeze)
    assert freeze["workers"] == 13
    assert freeze["headroom_workers"] == 15
    assert freeze["scientific_wall_cap_nanoseconds"] \
        > freeze["scientific_wall_estimate_nanoseconds"]
    assert freeze["scientific_wall_cap_nanoseconds"] \
        <= MAX_SCIENTIFIC_WALL_NANOSECONDS
    assert freeze["authority"]["scientific_execution_authorized"] is False


def test_capacity_selection_and_authority_checks_can_fail():
    receipt = _receipt()
    receipt["selected_workers"] = 8
    with pytest.raises(
            BeliefPolicyExecutionError,
            match="capacity selection reconstruction drift"):
        validate_capacity_receipt(receipt)


def test_freeze_and_run_boundaries_reauthenticate_review_provenance(
        monkeypatch, tmp_path: Path):
    envelope = _envelope()
    marker = b"authenticated-source-review\n"
    envelope["source_review_marker_sha256"] = hashlib.sha256(
        marker).hexdigest()
    monkeypatch.setattr(
        EXECUTION, "build_source_identity",
        lambda _repo, expected_git: envelope["source"])
    calls = []

    def authenticate(**kwargs):
        calls.append(kwargs)
        return marker

    monkeypatch.setattr(EXECUTION, "authenticate_review", authenticate)
    assert authenticate_capacity_envelope_source(
        repo=tmp_path.resolve(), envelope=envelope) == marker
    assert calls[-1]["review_commit"] == envelope["source_review_commit"]
    assert calls[-1]["prefix"] == EXECUTION.SOURCE_REVIEW_PREFIX

    freeze = build_freeze(
        canonical_json_bytes(envelope),
        evidence_root=(tmp_path / "evidence").resolve(),
        model_root=(tmp_path / "models").resolve())
    admission = {"review_commit": "a" * 40}
    freeze_marker = b"authenticated-freeze-review\n"
    monkeypatch.setattr(
        EXECUTION, "authenticate_review", lambda **kwargs: freeze_marker)
    authenticate_scientific_freeze_review(
        repo=tmp_path.resolve(), freeze=freeze,
        admission=admission, marker=freeze_marker)
    with pytest.raises(
            BeliefPolicyExecutionError,
            match="scientific freeze review provenance drift"):
        authenticate_scientific_freeze_review(
            repo=tmp_path.resolve(), freeze=freeze,
            admission=admission, marker=b"forged\n")
    receipt = _receipt()
    receipt["contains_outcomes"] = True
    with pytest.raises(
            BeliefPolicyExecutionError,
            match="capacity receipt reconstruction drift"):
        validate_capacity_receipt(receipt)
