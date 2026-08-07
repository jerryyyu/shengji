"""Falsification tests for the outcome-blind S0 refusal closeout."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_dependency_refusal_closeout as CLOSE  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def _authority_fixture(monkeypatch, tmp_path: Path):
    seal = tmp_path / "seal.json"
    seal_attempt = tmp_path / "seal-attempt.json"
    evaluation = tmp_path / "evaluate-attempt.json"
    state = tmp_path / "state.json"
    freeze = tmp_path / "freeze.json"
    original_output = tmp_path / "original-output.json"
    canonical = tmp_path / "canonical.bin"
    canonical.write_bytes(b"opaque outcome-bearing bytes")
    freeze.write_text("{}\n")
    seal_attempt.write_text("sealed attempt\n")
    input_snapshot = {
        "canonical.bin": {
            "sha256": CLOSE.sha256_bytes(canonical.read_bytes()),
            "size": canonical.stat().st_size,
        },
    }
    seal_value = {
        "canonical_input_count": 18,
        "input_set_sha256": "i" * 64,
        "inputs": input_snapshot,
        "outcomes_parsed": False,
    }
    _write_json(seal, seal_value)
    evaluation_value = {
        "schema": CLOSE.AUDIT.ATTEMPT_SCHEMA,
        "action": "evaluate",
        "git_sha": "h" * 40,
        "selection_digest": CLOSE.AUDIT.stable_digest(
            CLOSE.AUDIT.SELECTION_RULE),
        "freeze_sha256": CLOSE.sha256(freeze),
        "input_seal_path": str(seal),
        "input_seal_sha256": CLOSE.sha256(seal),
        "started_unix_ns": 123,
        "outcomes_parsed": False,
    }
    _write_json(evaluation, evaluation_value)
    state_value = {
        "status": "BLOCKED",
        "error": "RuntimeError: packet stdout differs from durable packet",
    }
    _write_json(state, state_value)

    monkeypatch.setattr(CLOSE.AUDIT, "SEAL", seal)
    monkeypatch.setattr(CLOSE.AUDIT, "SEAL_ATTEMPT", seal_attempt)
    monkeypatch.setattr(CLOSE.AUDIT, "EVALUATE_ATTEMPT", evaluation)
    monkeypatch.setattr(CLOSE.AUDIT, "FREEZE_PATH", freeze)
    monkeypatch.setattr(CLOSE.AUDIT, "OUTPUT", original_output)
    monkeypatch.setattr(CLOSE, "STATE", state)
    monkeypatch.setattr(CLOSE, "SEALED_HEAD", "h" * 40)
    monkeypatch.setattr(CLOSE, "EXPECTED_SEAL_SHA256", CLOSE.sha256(seal))
    monkeypatch.setattr(
        CLOSE, "EXPECTED_SEAL_ATTEMPT_SHA256", CLOSE.sha256(seal_attempt))
    monkeypatch.setattr(
        CLOSE, "EXPECTED_EVALUATION_ATTEMPT_SHA256", CLOSE.sha256(evaluation))
    monkeypatch.setattr(CLOSE, "EXPECTED_INPUT_SET_SHA256", "i" * 64)
    monkeypatch.setattr(
        CLOSE, "EXPECTED_BLOCKED_STATE_SHA256", CLOSE.sha256(state))
    monkeypatch.setattr(
        CLOSE.AUDIT, "load_and_verify_seal",
        lambda head, expected_sha256=None: (
            seal_value if head == "h" * 40
            and expected_sha256 == CLOSE.sha256(seal) else None),
    )
    monkeypatch.setattr(
        CLOSE.AUDIT, "canonical_input_paths", lambda: (canonical,))
    snapshots = []

    def snapshot(_paths):
        snapshots.append(True)
        return copy.deepcopy(input_snapshot)

    monkeypatch.setattr(CLOSE.AUDIT, "snapshot_inputs", snapshot)
    monkeypatch.setattr(
        CLOSE.AUDIT, "read_sealed_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("outcome bytes must never be decoded")),
    )
    return {
        "seal": seal,
        "seal_value": seal_value,
        "evaluation": evaluation,
        "evaluation_value": evaluation_value,
        "state": state,
        "state_value": state_value,
        "snapshots": snapshots,
    }


def test_closeout_is_structurally_unable_to_promote():
    result = CLOSE._result("a" * 40, "b" * 64)
    assert result["final_state"] == "S0_COMPLETE_SELECT_NONE"
    assert result["final_production_decision"] == \
        "SELECT NONE; production remains mc-strong"
    assert result["promotion_admissible"] is False
    assert result["dependency_repair_pass"] is None
    assert result["outcomes_parsed"] is False
    assert result["outcome_records_decoded"] is False
    assert result["automatic_deployment"] is False
    assert result["retry_or_extension_authorized"] is False
    assert "separately approved manual production" in result["claim_boundary"]
    assert not any(
        word in key for key in result
        for word in ("mean", "effect", "utility", "win_rate", "criteria")
    )


def test_authority_validation_hashes_twice_and_never_decodes_inputs(
        monkeypatch, tmp_path):
    fixture = _authority_fixture(monkeypatch, tmp_path)
    result = CLOSE.validate_burned_authority()
    assert result["evaluation"]["outcomes_parsed"] is False
    assert result["state"]["status"] == "BLOCKED"
    assert fixture["snapshots"] == [True, True]


@pytest.mark.parametrize(("field", "value", "message"), [
    ("action", "retry", "identity drift"),
    ("outcomes_parsed", True, "identity drift"),
    ("git_sha", "x" * 40, "identity drift"),
])
def test_evaluation_attempt_mutants_refuse(
        monkeypatch, tmp_path, field, value, message):
    fixture = _authority_fixture(monkeypatch, tmp_path)
    mutated = dict(fixture["evaluation_value"])
    mutated[field] = value
    _write_json(fixture["evaluation"], mutated)
    monkeypatch.setattr(
        CLOSE, "EXPECTED_EVALUATION_ATTEMPT_SHA256",
        CLOSE.sha256(fixture["evaluation"]),
    )
    with pytest.raises(CLOSE.CloseoutRefused, match=message):
        CLOSE.validate_burned_authority()


def test_blocked_state_reason_is_exact(monkeypatch, tmp_path):
    fixture = _authority_fixture(monkeypatch, tmp_path)
    mutated = dict(fixture["state_value"])
    mutated["error"] = "RuntimeError: some other failure"
    _write_json(fixture["state"], mutated)
    monkeypatch.setattr(
        CLOSE, "EXPECTED_BLOCKED_STATE_SHA256", CLOSE.sha256(fixture["state"]))
    with pytest.raises(CLOSE.CloseoutRefused, match="refusal state drift"):
        CLOSE.validate_burned_authority()


def test_existing_dependency_decision_refuses_closeout(monkeypatch, tmp_path):
    _authority_fixture(monkeypatch, tmp_path)
    CLOSE.AUDIT.OUTPUT.write_text("unexpected decision\n")
    with pytest.raises(CLOSE.CloseoutRefused, match="unexpectedly published"):
        CLOSE.validate_burned_authority()


def test_changed_sealed_input_refuses_without_decoding(monkeypatch, tmp_path):
    fixture = _authority_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        CLOSE.AUDIT, "snapshot_inputs",
        lambda _paths: {
            "canonical.bin": {"sha256": "x" * 64, "size": 1},
        },
    )
    with pytest.raises(CLOSE.CloseoutRefused, match="canonical inputs changed"):
        CLOSE.validate_burned_authority()
    assert fixture["evaluation_value"]["outcomes_parsed"] is False


def test_failed_close_consumes_attempt_and_cannot_retry(monkeypatch, tmp_path):
    attempt = tmp_path / "close.attempt.json"
    output = tmp_path / "close.json"
    monkeypatch.setattr(CLOSE, "ATTEMPT", attempt)
    monkeypatch.setattr(CLOSE, "OUTPUT", output)
    monkeypatch.setattr(CLOSE, "require_runtime", lambda **_kwargs: "a" * 40)
    monkeypatch.setattr(
        CLOSE, "validate_burned_authority",
        lambda: (_ for _ in ()).throw(CLOSE.CloseoutRefused("mutant")),
    )

    with pytest.raises(CLOSE.CloseoutRefused, match="mutant"):
        CLOSE.close()
    assert attempt.is_file()
    assert not output.exists()
    with pytest.raises(CLOSE.CloseoutRefused, match="already attempted"):
        CLOSE.close()


def test_close_writes_attempt_before_validation_and_is_nonretryable(
        monkeypatch, tmp_path):
    attempt = tmp_path / "close.attempt.json"
    output = tmp_path / "close.json"
    monkeypatch.setattr(CLOSE, "ATTEMPT", attempt)
    monkeypatch.setattr(CLOSE, "OUTPUT", output)
    monkeypatch.setattr(CLOSE, "require_runtime", lambda **_kwargs: "a" * 40)

    def validate():
        assert attempt.is_file()
        return {"evaluation": {"outcomes_parsed": False}}

    monkeypatch.setattr(CLOSE, "validate_burned_authority", validate)
    result = CLOSE.close()
    assert output.is_file()
    assert json.loads(output.read_text()) == result
    assert result["closeout_attempt_sha256"] == CLOSE.sha256(attempt)
    with pytest.raises(CLOSE.CloseoutRefused, match="already attempted"):
        CLOSE.close()


def test_terminal_lock_can_only_close_preterminal_parent(monkeypatch):
    preterminal = {
        "schema": CLOSE.PARENT.SCHEMA,
        "transition": "PRETERMINAL",
        "authorized": False,
        "dependency_audit_sha256": None,
        "input_seal_sha256": None,
        "input_set_sha256": None,
        "final_state": None,
        "final_production_decision": None,
        "freeze_sha256": "f" * 64,
        "binding_rule": CLOSE.PARENT.BINDING_RULE,
    }
    monkeypatch.setattr(CLOSE.PARENT, "load_lock", lambda: preterminal)
    output = CLOSE._result("a" * 40, "b" * 64)
    lock = CLOSE.terminal_lock(output, "c" * 64)
    assert lock["transition"] == "TERMINAL"
    assert lock["authorized"] is False
    assert lock["dependency_audit_sha256"] == "c" * 64
    assert lock["final_state"] == CLOSE.FINAL_STATE

    terminal = {**preterminal, "transition": "TERMINAL"}
    monkeypatch.setattr(CLOSE.PARENT, "load_lock", lambda: terminal)
    with pytest.raises(CLOSE.CloseoutRefused, match="not preterminal"):
        CLOSE.terminal_lock(output, "c" * 64)
