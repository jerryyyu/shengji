"""Can-fail witnesses for the one-time R5 pre-test readiness proof."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import shengji.rl.belief_v2_readiness_controller as READINESS
import shengji.rl.belief_v2_terminal_controller as TERMINAL


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _fixture(tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    (root / "calibration" / "selection").mkdir(parents=True)
    cohort_ids = ("synthetic-primary", "label-control")
    freeze = SimpleNamespace(
        evidence_root=str(root),
        cohorts=tuple(SimpleNamespace(cohort_id=value)
                      for value in cohort_ids),
        sha256=lambda: _sha("freeze"))
    admission = SimpleNamespace(sha256=lambda: _sha("admission"))
    calibration = {
        "schema": "test-calibration",
        "calibration_passed": True,
        "selected_cohort_id": "synthetic-primary",
        "training_manifest_sha256s": {
            value: _sha(f"manifest-{value}") for value in cohort_ids},
    }
    cohorts = tuple(SimpleNamespace(
        cohort_id=value,
        model_sha256s=tuple(_sha(f"{value}-{index}") for index in range(8)))
                    for value in cohort_ids)
    training_hashes = tuple(calibration[
        "training_manifest_sha256s"].items())
    inputs = SimpleNamespace(sha256=lambda: _sha("training-input"))
    plan = SimpleNamespace(sha256=lambda: _sha("qualification-plan"))
    qualification = SimpleNamespace(
        canonical_bytes=lambda _plan: b"qualification\n")
    checkpoint_inputs = (
        {"schema": "input-manifest"}, inputs, cohorts, plan,
        qualification, training_hashes)
    full_calls = []

    def full(*args, **kwargs):
        full_calls.append((args, kwargs))
        assert not (root / "calibration" / "readiness").exists()
        return calibration

    monkeypatch.setattr(READINESS, "reopen_v2_calibration_selection", full)
    monkeypatch.setattr(
        READINESS, "reopen_v2_calibration_selection_checkpoint_identity",
        lambda *args, **kwargs: calibration)
    monkeypatch.setattr(
        READINESS, "_checkpoint_inputs",
        lambda *args, **kwargs: checkpoint_inputs)
    return (root, freeze, admission, calibration, checkpoint_inputs,
            full_calls)


def test_readiness_publishes_only_after_full_curve_proof_and_reopens(
        tmp_path, monkeypatch):
    (root, freeze, admission, calibration, checkpoint_inputs,
     full_calls) = _fixture(tmp_path, monkeypatch)
    progress = lambda *_args: None

    receipt = READINESS.publish_v2_calibration_readiness(
        root, freeze=freeze, admission=admission,
        inventory={}, group_split={}, expected_calibration=calibration,
        progress=progress)

    assert len(full_calls) == 1
    assert full_calls[0][1]["progress"] is progress
    assert receipt["full_saved_epoch_curve_reopen_completed"] is True
    assert receipt["published_before_test_open"] is True
    assert receipt["test_split_opened"] is False
    assert receipt["retry_authorized"] is False
    reopened = READINESS.reopen_v2_calibration_readiness(
        root / "calibration" / "readiness", freeze=freeze,
        admission=admission, inventory={}, group_split={})
    assert reopened[0] == receipt
    assert reopened[1] == calibration
    assert reopened[2:] == checkpoint_inputs


def test_readiness_full_proof_failure_cannot_publish_or_reach_test(
        tmp_path, monkeypatch):
    root, freeze, admission, _calibration, _inputs, _calls = _fixture(
        tmp_path, monkeypatch)
    monkeypatch.setattr(
        READINESS, "reopen_v2_calibration_selection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("injected saved-curve drift")))
    with pytest.raises(READINESS.BeliefV2ReadinessControllerError,
                       match="full calibration proof refused"):
        READINESS.publish_v2_calibration_readiness(
            root, freeze=freeze, admission=admission,
            inventory={}, group_split={})
    assert not (root / "calibration" / "readiness").exists()
    assert not (root / "terminal.partial").exists()

    monkeypatch.setattr(TERMINAL, "_stage_gate", lambda **kwargs: None)
    with pytest.raises(TERMINAL.BeliefV2TerminalControllerError,
                       match="lacks durable calibration readiness"):
        TERMINAL.run_v2_terminal(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", inventory={}, group_split={})
    assert not (root / "terminal.partial").exists()


def test_readiness_cannot_masquerade_as_pretest_after_attempt_exists(
        tmp_path, monkeypatch):
    root, freeze, admission, calibration, _inputs, full_calls = _fixture(
        tmp_path, monkeypatch)
    (root / "terminal.partial").mkdir()
    with pytest.raises(READINESS.BeliefV2ReadinessControllerError,
                       match="occupied test namespace"):
        READINESS.publish_v2_calibration_readiness(
            root, freeze=freeze, admission=admission,
            inventory={}, group_split={},
            expected_calibration=calibration)
    assert not full_calls
    assert not (root / "calibration" / "readiness").exists()


def test_readiness_receipt_tamper_is_not_a_curve_proof(
        tmp_path, monkeypatch):
    root, freeze, admission, calibration, _inputs, _calls = _fixture(
        tmp_path, monkeypatch)
    READINESS.publish_v2_calibration_readiness(
        root, freeze=freeze, admission=admission,
        inventory={}, group_split={}, expected_calibration=calibration)
    path = root / "calibration" / "readiness" / READINESS.READINESS_FILENAME
    raw = path.read_bytes().replace(
        b'"full_saved_epoch_curve_reopen_completed":true',
        b'"full_saved_epoch_curve_reopen_completed":false')
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o400)
    with pytest.raises(READINESS.BeliefV2ReadinessControllerError,
                       match="receipt reconstruction drift"):
        READINESS.reopen_v2_calibration_readiness(
            path.parent, freeze=freeze, admission=admission,
            inventory={}, group_split={})
