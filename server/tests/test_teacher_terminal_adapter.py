"""Falsification tests for the outcome-independent Teacher terminal router."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = (Path(__file__).parents[1] / "scripts" /
            "teacher_terminal_adapter.py")
    spec = importlib.util.spec_from_file_location("teacher_terminal_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _module()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime():
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "python": "3.14.6",
        "adapter_source_sha256": _sha(Path(A.__file__)),
    }


def _gate(verdict: str) -> dict:
    passed = verdict == "PASS"
    return {
        "schema": A.AUDIT_GATE_SCHEMA,
        "audit_id": A.AUDIT_ID,
        "complete": True,
        "terminal": True,
        "extension_authorized": False,
        "verdict": verdict,
        "champion_fidelity_qualified": passed,
        "stage_c_authorized": passed,
        "producer_run_id": A.RUN_ID,
        "git": A.AUDIT_GIT,
        "tree_dirty": False,
        "promotable": True,
        "host": A.EXPECTED_HOST,
        "python": A.EXPECTED_PYTHON,
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "source_digests": {
            "audit_script": A.AUDIT_SCRIPT_SHA256,
            "compiled_engine": A.COMPILED_ENGINE_SHA256,
        },
        "folds_contract": A.EXPECTED_FOLDS,
        "continuation_contract": A.EXPECTED_CONTINUATION,
        "n_states": 64,
        "problems": [] if passed else ["registered terminal miss"],
        "producer_receipt": {
            "path": A.RECEIPT_PATH,
            "sha256": A.RECEIPT_SHA256,
            "run_id": A.RUN_ID,
            "nonce": "8" * 64,
        },
        "stage_b_state_set": {
            "path": f"{A.PARENT_NAMESPACE}/stage_b_states.json",
            "sha256": A.STAGE_B_STATE_SHA256,
        },
        "stage_b_gate": {
            "path": f"{A.PARENT_NAMESPACE}/stage_b_gate_v2.json",
            "sha256": A.STAGE_B_GATE_SHA256,
        },
        "consumed_audit_state_set": {
            "path": (
                f"{A.AUDIT_NAMESPACE}/"
                "champion_audit_consumed_states_v1.json"),
            "sha256": A.CONSUMED_AUDIT_STATE_SHA256,
        },
        "audit_state_set": {
            "path": f"{A.AUDIT_NAMESPACE}/champion_audit_states_v2.json",
            "sha256": A.AUDIT_STATE_SHA256,
        },
        "cheap_inputs": [{
            "path": f"/sealed/cheap-{index}.json",
            "sha256": f"{index + 21:064x}",
            "shard_index": index,
        } for index in range(8)],
        "n30_inputs": [{
            "path": f"/sealed/n30-{index}.json",
            "sha256": f"{index + 31:064x}",
            "shard_index": index,
        } for index in range(8)],
        "inputs": [{
            "path": f"/sealed/champion_audit_v2_shard{index:02d}.json",
            "sha256": f"{index + 1:064x}",
            "shard_index": index,
        } for index in range(8)],
    }


def _events(verdict: str, gate_sha: str) -> list[dict]:
    code = 0 if verdict == "PASS" else 4
    return [
        {
            "schema": A.SUPERVISOR_SCHEMA,
            "phase": "supervisor",
            "status": "admitted",
            "run_id": A.RUN_ID,
            "host": A.EXPECTED_HOST,
            "audit_git": A.AUDIT_GIT,
            "audit_script_sha256": A.AUDIT_SCRIPT_SHA256,
            "supervisor_sha256": A.SUPERVISOR_SCRIPT_SHA256,
            "receipt_sha256": A.RECEIPT_SHA256,
            "preparation_sha256": A.PREPARATION_SHA256,
            "preparer_sha256": A.PREPARER_SCRIPT_SHA256,
            "execution_predeclaration": {
                "git": A.AUDIT_GIT,
                "audit_script_sha256": A.AUDIT_SCRIPT_SHA256,
            },
            "shard_count": 8,
            "selection_worlds": 32,
            "report_worlds": 32,
        },
        {
            "schema": A.SUPERVISOR_SCHEMA,
            "phase": "supervisor",
            "status": "terminal",
            "run_id": A.RUN_ID,
            "host": A.EXPECTED_HOST,
            "audit_git": A.AUDIT_GIT,
            "audit_script_sha256": A.AUDIT_SCRIPT_SHA256,
            "supervisor_sha256": A.SUPERVISOR_SCRIPT_SHA256,
            "receipt_sha256": A.RECEIPT_SHA256,
            "preparation_sha256": A.PREPARATION_SHA256,
            "preparer_sha256": A.PREPARER_SCRIPT_SHA256,
            "gate_sha256": gate_sha,
            "gate_verdict": verdict,
            "gate_returncode": code,
            "retry_authorized": False,
            "label_sha256s": [f"{index + 1:064x}" for index in range(8)],
        },
    ]


def _fixture(tmp_path: Path, monkeypatch, verdict: str = "PASS"):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(_gate(verdict), sort_keys=True))
    progress = tmp_path / "supervisor.jsonl"
    events = _events(verdict, _sha(gate))
    progress.write_text("".join(json.dumps(event) + "\n" for event in events))
    monkeypatch.setattr(A, "runtime_contract", lambda _expected: _runtime())
    config = A.Config(
        gate=gate,
        expected_gate_sha256=_sha(gate),
        supervisor_progress=progress,
        expected_supervisor_sha256=_sha(progress),
        expected_git="a" * 40,
    )
    return config


def test_pass_emits_design_only_hard_tail_packet(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch, "PASS")
    out = tmp_path / "adapter.json"
    payload = A.create(config, out)
    assert payload["branch"] == "PASS"
    assert payload["contract"]["decision"] == "DESIGN_HARD_TAIL_STAGE_C"
    assert payload["contract"]["live_parent"]["policy"] == \
        "mc-s0-report-lcb"
    assert payload["contract"]["label_routing_required"][
        "uncertainty_or_disagreement"] == "gold_report_lcb_or_deeper"
    assert payload["compute_authorized"] is False
    assert payload["bulk_label_authorized"] is False
    assert payload["training_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["audit_retry_authorized"] is False
    assert payload["evidence"]["consumed_audit_state_sha256"] == \
        A.CONSUMED_AUDIT_STATE_SHA256
    assert payload["evidence"]["fresh_audit_state_sha256"] == \
        A.AUDIT_STATE_SHA256
    assert not A.artifact_partial(out).exists()
    assert A.verify(config, out, _sha(out)) == payload


@pytest.mark.parametrize("verdict", ["FAIL", "INCONCLUSIVE"])
def test_nonpass_emits_existing_evidence_diagnostic_only(
        tmp_path, monkeypatch, verdict):
    config = _fixture(tmp_path, monkeypatch, verdict)
    payload = A.create(config, tmp_path / "adapter.json")
    assert payload["branch"] == "NONPASS"
    contract = payload["contract"]
    assert contract["decision"] == "DIAGNOSE_EXISTING_AUDIT_ONLY"
    assert contract["new_states_authorized"] is False
    assert contract["new_worlds_authorized"] is False
    assert contract["same_recipe_extension_authorized"] is False
    assert payload["compute_authorized"] is False


def test_unknown_or_internally_inconsistent_verdict_refuses(
        tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch, "PASS")
    gate = json.loads(config.gate.read_text())
    gate["verdict"] = "MAYBE"
    config.gate.write_text(json.dumps(gate, sort_keys=True))
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=_sha(config.gate),
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=config.expected_supervisor_sha256,
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="terminal verdict"):
        A.reopen_inputs(config)


def test_gate_hash_mutation_refuses(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    config.gate.write_text(config.gate.read_text() + "\n")
    with pytest.raises(A.AdapterRefusal, match="artifact SHA drift"):
        A.create(config, tmp_path / "adapter.json")


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("swap_consumed", "consumed_audit_state_set binding"),
        ("drop_retry_admission", "continuation contract"),
        ("wrong_host", "execution identity"),
        ("wrong_engine", "script identity"),
    ),
)
def test_gate_refuses_fresh_lineage_or_runtime_drift(
        tmp_path, monkeypatch, mutation, message):
    config = _fixture(tmp_path, monkeypatch)
    gate = json.loads(config.gate.read_text())
    if mutation == "swap_consumed":
        gate["consumed_audit_state_set"] = dict(gate["audit_state_set"])
    elif mutation == "drop_retry_admission":
        gate["continuation_contract"].pop("admission")
    elif mutation == "wrong_host":
        gate["host"] = "jerrys-macbook-air"
    else:
        gate["source_digests"]["compiled_engine"] = "3" * 64
    config.gate.write_text(json.dumps(gate, sort_keys=True))
    changed = A.Config(
        gate=config.gate,
        expected_gate_sha256=_sha(config.gate),
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=config.expected_supervisor_sha256,
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match=message):
        A.create(changed, tmp_path / "adapter.json")


def test_supervisor_receipt_must_match_gate(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    events = [json.loads(line)
              for line in config.supervisor_progress.read_text().splitlines()]
    events[-1]["receipt_sha256"] = "5" * 64
    config.supervisor_progress.write_text(
        "".join(json.dumps(event) + "\n" for event in events))
    changed = A.Config(
        gate=config.gate,
        expected_gate_sha256=config.expected_gate_sha256,
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=_sha(config.supervisor_progress),
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="terminal binding"):
        A.create(changed, tmp_path / "adapter.json")


@pytest.mark.parametrize(
    ("target", "field", "message"),
    (
        ("gate", "sha256", "receipt binding"),
        ("admitted", "preparation_sha256", "admitted identity"),
        ("terminal", "preparer_sha256", "terminal binding"),
    ),
)
def test_exact_launch_receipt_and_preparation_are_literal(
        tmp_path, monkeypatch, target, field, message):
    config = _fixture(tmp_path, monkeypatch)
    if target == "gate":
        gate = json.loads(config.gate.read_text())
        gate["producer_receipt"][field] = "4" * 64
        config.gate.write_text(json.dumps(gate, sort_keys=True))
        changed = A.Config(
            gate=config.gate,
            expected_gate_sha256=_sha(config.gate),
            supervisor_progress=config.supervisor_progress,
            expected_supervisor_sha256=config.expected_supervisor_sha256,
            expected_git=config.expected_git,
        )
    else:
        events = [json.loads(line) for line in
                  config.supervisor_progress.read_text().splitlines()]
        events[0 if target == "admitted" else -1][field] = "4" * 64
        config.supervisor_progress.write_text(
            "".join(json.dumps(event) + "\n" for event in events))
        changed = A.Config(
            gate=config.gate,
            expected_gate_sha256=config.expected_gate_sha256,
            supervisor_progress=config.supervisor_progress,
            expected_supervisor_sha256=_sha(config.supervisor_progress),
            expected_git=config.expected_git,
        )
    with pytest.raises(A.AdapterRefusal, match=message):
        A.create(changed, tmp_path / "adapter.json")


def test_surviving_input_partial_refuses(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    A.artifact_partial(config.gate).write_text("partial")
    with pytest.raises(A.AdapterRefusal, match="artifact partial exists"):
        A.create(config, tmp_path / "adapter.json")


def test_supervisor_must_end_in_exact_terminal_event(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    with config.supervisor_progress.open("a") as handle:
        handle.write(json.dumps({
            "schema": A.SUPERVISOR_SCHEMA,
            "phase": "label",
            "status": "heartbeat",
        }) + "\n")
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=config.expected_gate_sha256,
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=_sha(config.supervisor_progress),
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="final terminal event"):
        A.create(config, tmp_path / "adapter.json")


def test_gate_and_supervisor_verdict_must_match(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch, "PASS")
    events = [json.loads(line)
              for line in config.supervisor_progress.read_text().splitlines()]
    events[-1]["gate_verdict"] = "FAIL"
    config.supervisor_progress.write_text(
        "".join(json.dumps(event) + "\n" for event in events))
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=config.expected_gate_sha256,
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=_sha(config.supervisor_progress),
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="terminal binding"):
        A.create(config, tmp_path / "adapter.json")


def test_gate_input_item_schema_is_exact(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    gate = json.loads(config.gate.read_text())
    gate["inputs"][0]["innocent"] = "outcome-carrying-extension"
    config.gate.write_text(json.dumps(gate, sort_keys=True))
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=_sha(config.gate),
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=config.expected_supervisor_sha256,
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="input item schema"):
        A.create(config, tmp_path / "adapter.json")


def test_gate_inputs_and_supervisor_labels_must_match_exactly(
        tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    events = [json.loads(line)
              for line in config.supervisor_progress.read_text().splitlines()]
    events[-1]["label_sha256s"] = [
        f"{index + 11:064x}" for index in range(8)]
    config.supervisor_progress.write_text(
        "".join(json.dumps(event) + "\n" for event in events))
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=config.expected_gate_sha256,
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=_sha(config.supervisor_progress),
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="label digest binding"):
        A.create(config, tmp_path / "adapter.json")


def test_gate_input_shards_must_be_canonical_and_ordered(
        tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    gate = json.loads(config.gate.read_text())
    gate["inputs"][0]["shard_index"] = 7
    config.gate.write_text(json.dumps(gate, sort_keys=True))
    config = A.Config(
        gate=config.gate,
        expected_gate_sha256=_sha(config.gate),
        supervisor_progress=config.supervisor_progress,
        expected_supervisor_sha256=config.expected_supervisor_sha256,
        expected_git=config.expected_git,
    )
    with pytest.raises(A.AdapterRefusal, match="ordered shard population"):
        A.create(config, tmp_path / "adapter.json")


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    out = tmp_path / "adapter.json"
    out.write_text("owned")
    with pytest.raises(A.AdapterRefusal, match="existing output"):
        A.create(config, out)
    assert out.read_text() == "owned"


def test_adapter_mutation_fails_independent_reopen(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    out = tmp_path / "adapter.json"
    A.create(config, out)
    payload = json.loads(out.read_text())
    payload["compute_authorized"] = True
    out.write_text(json.dumps(payload))
    with pytest.raises(A.AdapterRefusal, match="full recomputation drift"):
        A.verify(config, out, _sha(out))
