"""Falsification tests for the corrected-S0-only S0e-v2 admission seam."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_deployment_choice_v2_parent as PARENT  # noqa: E402


def test_preterminal_parent_is_frozen_closed_and_stream_disjoint():
    assert PARENT.protocol_problems() == []
    lock = PARENT.load_lock()
    assert lock["transition"] == "PRETERMINAL"
    assert lock["authorized"] is False
    assert lock["dependency_audit_sha256"] is None
    witness = PARENT.stream_witness()
    assert witness == {
        "seed0": 148_000_000,
        "seed_hi": 148_016_383,
        "clusters": 16_384,
        "null_offset": 50_000_003,
        "cross_seed_collision_count": 0,
        "cross_seed_collisions": {},
    }
    null = PARENT.make_bot(PARENT.LABELS["current_null"], seed=7)
    current = PARENT.make_bot(PARENT.LABELS["current"], seed=7)
    assert null.NULL_SEED_OFFSET == 50_000_003
    assert null.N_DETERMINIZATIONS == current.N_DETERMINIZATIONS == 30
    assert null.rng.getstate() != current.rng.getstate()


def test_historical_lag17_offset_is_explicitly_falsified(monkeypatch):
    monkeypatch.setattr(PARENT, "NULL_OFFSET", 999_983)
    witness = PARENT.stream_witness()
    assert witness["cross_seed_collision_count"] == 2 * (16_384 - 17)
    assert "S0e-v2 population/null geometry drift" in \
        PARENT.protocol_problems()
    assert "S0e-v2 retains a cross-seed RNG collision" in \
        PARENT.protocol_problems()


def _write_authority(tmp_path, monkeypatch, *, promote: bool):
    output = tmp_path / "dependency.json"
    seal_path = tmp_path / "seal.json"
    seal_attempt_path = tmp_path / "seal.attempt.json"
    evaluation_path = tmp_path / "evaluate.attempt.json"
    monkeypatch.setattr(PARENT.DEPENDENCY, "OUTPUT", output)
    monkeypatch.setattr(PARENT.DEPENDENCY, "SEAL", seal_path)
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "SEAL_ATTEMPT", seal_attempt_path)
    monkeypatch.setattr(PARENT.DEPENDENCY, "EVALUATE_ATTEMPT", evaluation_path)
    input_set = "1" * 64
    seal_attempt_path.write_text("{\"sealed\": true}\n")
    seal = {
        "schema": PARENT.DEPENDENCY.SEAL_SCHEMA,
        "complete": True,
        "outcomes_parsed": False,
        "input_set_sha256": input_set,
        "seal_attempt_sha256": PARENT.sha256(seal_attempt_path),
    }
    seal_path.write_text(json.dumps(seal, sort_keys=True) + "\n")
    git_sha = "e" * 40
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "require_runtime", lambda: git_sha)
    evaluation = {
        "schema": PARENT.DEPENDENCY.ATTEMPT_SCHEMA,
        "action": "evaluate",
        "git_sha": git_sha,
        "selection_digest": PARENT.DEPENDENCY.stable_digest(
            PARENT.DEPENDENCY.SELECTION_RULE),
        "freeze_sha256": PARENT.sha256(PARENT.DEPENDENCY.FREEZE_PATH),
        "input_seal_path": str(seal_path),
        "input_seal_sha256": PARENT.sha256(seal_path),
        "started_unix_ns": 1,
        "outcomes_parsed": False,
    }
    evaluation_path.write_text(json.dumps(evaluation, sort_keys=True) + "\n")
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "load_and_verify_seal",
        lambda head, expected_sha256=None: seal
        if (head == git_sha and expected_sha256 == PARENT.sha256(seal_path))
        else (_ for _ in ()).throw(AssertionError("seal identity drift")),
    )
    state = ("S0_COMPLETE_PROMOTE" if promote
             else "S0_COMPLETE_SELECT_NONE")
    decision = ("PROMOTE mc-s0-adaptive" if promote
                else "SELECT NONE; production remains mc-strong")
    audit = {
        "schema": PARENT.DEPENDENCY.SCHEMA,
        "complete": True,
        "git_sha": git_sha,
        "selection_digest": PARENT.DEPENDENCY.stable_digest(
            PARENT.DEPENDENCY.SELECTION_RULE),
        "input_seal_path": str(seal_path),
        "input_seal_sha256": PARENT.sha256(seal_path),
        "input_set_sha256": input_set,
        "evaluation_attempt_path": str(evaluation_path),
        "evaluation_attempt_sha256": PARENT.sha256(evaluation_path),
        "original_terminal_state": state,
        "final_state": state,
        "final_production_decision": decision,
        "promotion_admissible": promote,
        "dependency_repair_pass": True if promote else None,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "raw_reopened": promote,
        "colours_analyzed": promote,
    }
    trusted = copy.deepcopy(audit)
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "read_sealed_inputs", lambda _seal: {})
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "verify_original_terminal",
        lambda _blobs: ({"state": state}, "packet", "a" * 64),
    )
    monkeypatch.setattr(
        PARENT.DEPENDENCY, "run", lambda *_args: copy.deepcopy(trusted))
    output.write_text(json.dumps(audit, sort_keys=True) + "\n")
    return output, seal_path, audit


@pytest.mark.parametrize("promote", [False, True])
def test_terminal_payload_binds_exact_corrected_output_and_seal(
        promote, tmp_path, monkeypatch):
    output, seal, _ = _write_authority(
        tmp_path, monkeypatch, promote=promote)
    payload = PARENT._derive_from_artifacts()
    assert payload["authorized"] is promote
    assert payload["dependency_audit_sha256"] == PARENT.sha256(output)
    assert payload["input_seal_sha256"] == PARENT.sha256(seal)
    assert payload["final_state"] == (
        "S0_COMPLETE_PROMOTE" if promote else "S0_COMPLETE_SELECT_NONE")


def test_missing_refused_or_inconsistent_correction_never_authorizes(
        tmp_path, monkeypatch):
    output, _, audit = _write_authority(
        tmp_path, monkeypatch, promote=True)
    output.unlink()
    with pytest.raises(PARENT.DEPENDENCY.AuditRefused):
        PARENT._derive_from_artifacts()

    output.write_text(json.dumps({
        **audit, "promotion_admissible": False,
    }, sort_keys=True) + "\n")
    with pytest.raises(PARENT.ParentRefused, match="contract drift"):
        PARENT._derive_from_artifacts()


def test_coherent_final_state_cannot_hide_corrupt_diagnostics(
        tmp_path, monkeypatch):
    output, _, audit = _write_authority(
        tmp_path, monkeypatch, promote=True)
    audit["raw_reopened"] = False
    output.write_text(json.dumps(audit, sort_keys=True) + "\n")
    with pytest.raises(PARENT.ParentRefused, match="sealed recomputation"):
        PARENT._derive_from_artifacts()


def test_seal_attempt_mutation_during_derivation_is_refused(
        tmp_path, monkeypatch):
    _write_authority(tmp_path, monkeypatch, promote=True)
    seal_attempt = PARENT.DEPENDENCY.SEAL_ATTEMPT
    read_regular_bytes = PARENT.DEPENDENCY.read_regular_bytes
    reads = 0

    def mutate_after_first_read(path):
        nonlocal reads
        value = read_regular_bytes(path)
        if Path(path) == seal_attempt and reads == 0:
            reads += 1
            seal_attempt.write_text("{\"sealed\": false}\n")
        return value

    monkeypatch.setattr(
        PARENT.DEPENDENCY, "read_regular_bytes", mutate_after_first_read)
    with pytest.raises(PARENT.ParentRefused, match="changed during"):
        PARENT._derive_from_artifacts()


def test_terminal_lock_reopens_bytes_and_select_none_stays_closed(
        tmp_path, monkeypatch):
    output, _, _ = _write_authority(
        tmp_path, monkeypatch, promote=False)
    terminal = PARENT._derive_from_artifacts()
    monkeypatch.setattr(
        PARENT, "require_clean_pushed_introduced", lambda **_kwargs: "head")
    monkeypatch.setattr(PARENT, "protocol_problems", lambda: [])
    monkeypatch.setattr(PARENT, "load_lock", lambda: terminal)
    assert PARENT.verify_terminal_lock(require_authorized=False) == terminal
    with pytest.raises(PARENT.ParentRefused, match="permanently closes"):
        PARENT.verify_terminal_lock()

    changed = json.loads(output.read_text())
    changed["input_set_sha256"] = "2" * 64
    output.write_text(json.dumps(changed, sort_keys=True) + "\n")
    with pytest.raises(PARENT.ParentRefused):
        PARENT.verify_terminal_lock(require_authorized=False)


def test_parent_lock_allows_only_one_committed_terminal_transition(
        tmp_path, monkeypatch):
    initial = PARENT.load_lock()
    terminal = copy.deepcopy(initial)
    terminal.update({
        "transition": "TERMINAL",
        "authorized": False,
        "dependency_audit_sha256": "a" * 64,
        "input_seal_sha256": "b" * 64,
        "input_set_sha256": "c" * 64,
        "final_state": "S0_COMPLETE_SELECT_NONE",
        "final_production_decision": (
            "SELECT NONE; production remains mc-strong"),
    })
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(terminal, sort_keys=True) + "\n")
    monkeypatch.setattr(PARENT, "LOCK_PATH", path)
    monkeypatch.setattr(
        PARENT, "git_blob",
        lambda _commit, _path: (
            json.dumps(initial, sort_keys=True) + "\n").encode(),
    )
    monkeypatch.setattr(PARENT, "file_commits", lambda _path: ["intro"])
    assert "uncommitted S0e-v2 parent transition is forbidden" in \
        PARENT.transition_problems(terminal)
    monkeypatch.setattr(
        PARENT, "file_commits", lambda _path: ["terminal", "intro"])
    monkeypatch.setattr(
        PARENT, "git_blob",
        lambda commit, _path: (
            json.dumps(terminal if commit == "terminal" else initial,
                       sort_keys=True) + "\n").encode(),
    )
    assert PARENT.transition_problems(terminal) == []

    rewritten = copy.deepcopy(terminal)
    rewritten.update({
        "authorized": True,
        "final_state": "S0_COMPLETE_PROMOTE",
        "final_production_decision": "PROMOTE mc-s0-adaptive",
    })
    path.write_text(json.dumps(rewritten, sort_keys=True) + "\n")
    assert "differs from latest Git transition" in \
        PARENT.transition_problems(rewritten)[0]

    path.write_text(json.dumps(terminal, sort_keys=True) + "\n")
    monkeypatch.setattr(
        PARENT, "file_commits",
        lambda _path: ["rewrite", "terminal", "intro"],
    )
    assert "more than one terminal transition" in \
        PARENT.transition_problems(terminal)[0]


def test_runtime_gate_requires_clean_pushed_exact_git_phase(monkeypatch):
    head = "f" * 40
    monkeypatch.setattr(
        PARENT, "git",
        lambda *args: "" if args == ("status", "--porcelain") else head,
    )
    monkeypatch.setattr(PARENT, "git_is_ancestor", lambda *_args: True)
    counts = {
        Path(PARENT.__file__): ["script-intro"],
        PARENT.FREEZE_PATH: ["freeze-intro"],
        PARENT.LOCK_PATH: ["lock-intro"],
    }
    monkeypatch.setattr(PARENT, "file_commits", lambda path: counts[path])
    monkeypatch.setattr(
        PARENT, "git_blob",
        lambda _commit, path: PARENT.DEPENDENCY.read_regular_bytes(path),
    )
    assert PARENT.require_clean_pushed_introduced(terminal=False) == head
    with pytest.raises(PARENT.ParentRefused, match="expected 2 pushed"):
        PARENT.require_clean_pushed_introduced(terminal=True)

    counts[PARENT.LOCK_PATH] = ["terminal", "lock-intro"]
    assert PARENT.require_clean_pushed_introduced(terminal=True) == head

    monkeypatch.setattr(PARENT, "git_is_ancestor", lambda *_args: False)
    with pytest.raises(PARENT.ParentRefused, match="not pushed"):
        PARENT.require_clean_pushed_introduced(terminal=True)

    monkeypatch.setattr(
        PARENT, "git", lambda *_args: " M authority.json")
    with pytest.raises(PARENT.ParentRefused, match="checkout is dirty"):
        PARENT.require_clean_pushed_introduced(terminal=False)


def test_render_and_verify_call_their_exact_runtime_phase(monkeypatch):
    phases = []

    def refuse(*, terminal):
        phases.append(terminal)
        raise PARENT.ParentRefused("runtime gate witness")

    monkeypatch.setattr(PARENT, "require_clean_pushed_introduced", refuse)
    with pytest.raises(PARENT.ParentRefused, match="runtime gate witness"):
        PARENT.derive_terminal_lock()
    with pytest.raises(PARENT.ParentRefused, match="runtime gate witness"):
        PARENT.verify_terminal_lock(require_authorized=False)
    assert phases == [False, True]
