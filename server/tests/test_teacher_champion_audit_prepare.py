"""Falsification tests for champion-audit one-shot preparation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "scripts" / \
        "teacher_champion_audit_prepare.py"
    spec = importlib.util.spec_from_file_location("champion_prepare", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


P = _module()


def _supervisor_module():
    path = Path(__file__).parents[1] / "scripts" / \
        "teacher_champion_audit_supervisor.py"
    spec = importlib.util.spec_from_file_location(
        "champion_prepare_supervisor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FAKE_AUDIT = r'''#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("mode")
ap.add_argument("--run-id")
ap.add_argument("--expected-audit-git")
ap.add_argument("--expected-audit-script-sha256")
ap.add_argument("--stage-b-state-set")
ap.add_argument("--expected-stage-b-state-set-sha256")
ap.add_argument("--audit-state-set")
ap.add_argument("--expected-audit-state-set-sha256")
ap.add_argument("--stage-b-gate")
ap.add_argument("--expected-stage-b-gate-sha256")
ap.add_argument("--cheap", action="append")
ap.add_argument("--expected-cheap-sha256", action="append")
ap.add_argument("--n30", action="append")
ap.add_argument("--expected-n30-sha256", action="append")
ap.add_argument("--out")
args = ap.parse_args()
Path(args.out).write_text(json.dumps({
    "schema": "teacher-v1-champion-audit-receipt-v1",
    "complete": True,
    "run_id": args.run_id,
    "execution_predeclaration": {
        "git": args.expected_audit_git,
        "audit_script_sha256": args.expected_audit_script_sha256,
    },
}))
print("receipt complete", flush=True)
'''


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, monkeypatch):
    producer = tmp_path / "producer"
    audit = tmp_path / "audit"
    pns = producer / P.NAMESPACE
    ans = audit / P.NAMESPACE
    pns.mkdir(parents=True)
    ans.mkdir(parents=True)
    script = audit / P.AUDIT_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text(FAKE_AUDIT)
    audit_state = ans / P.AUDIT_STATE_NAME
    audit_state.write_text("audit state")
    monkeypatch.setattr(P, "AUDIT_SCRIPT_SHA256", P.sha256_file(script))
    monkeypatch.setattr(P, "AUDIT_STATE_SHA256", P.sha256_file(audit_state))
    state = pns / P.STAGE_B_STATE_NAME
    state_sha = _write_json(state, {"state": "frozen"})
    monkeypatch.setattr(P, "STAGE_B_STATE_SHA256", state_sha)

    populations = {}
    for kind, role, receipt_name in (
            ("cheap", "stage-b-cheap", P.CHEAP_RECEIPT_NAME),
            ("gold", "stage-b-gold", P.GOLD_RECEIPT_NAME)):
        receipt = pns / receipt_name
        receipt_payload = {
            "schema": "teacher-v1-producer-receipt-v1",
            "complete": True,
            "role": role,
            "run_id": f"{kind}-run",
            "nonce": ("a" if kind == "cheap" else "b") * 64,
        }
        receipt_sha = _write_json(receipt, receipt_payload)
        binding = {
            "path": str(P.NAMESPACE / receipt_name),
            "sha256": receipt_sha,
            "role": role,
            "run_id": receipt_payload["run_id"],
            "nonce": receipt_payload["nonce"],
        }
        items = []
        for shard in range(P.SHARDS):
            name = f"stage_b_{kind}_v2_shard{shard:02d}.json"
            path = pns / name
            digest = _write_json(path, {"producer_receipt": binding,
                                        "shard_index": shard})
            items.append({"path": str(P.NAMESPACE / name),
                          "sha256": digest, "shard_index": shard})
        populations[kind] = items
    gate = pns / P.STAGE_B_GATE_NAME
    gate_sha = _write_json(gate, {
        "schema": "teacher-v1-gate-v1",
        "complete": True,
        "stage": "B",
        "verdict": "PASS",
        "stage_c_authorized": True,
        "problems": [],
        "state_set": {"path": str(P.NAMESPACE / P.STAGE_B_STATE_NAME),
                      "sha256": state_sha},
        "cheap_inputs": populations["cheap"],
        "gold_inputs": populations["gold"],
    })
    monkeypatch.setattr(
        P, "_git", lambda root, *args:
        (P.PRODUCER_GIT if root == producer else P.AUDIT_GIT)
        if args == ("rev-parse", "HEAD") else "")
    preparer_sha = P.sha256_file(Path(P.__file__))
    config = P.Config(
        producer_root=producer,
        audit_root=audit,
        python=Path(sys.executable),
        expected_gate_sha256=gate_sha,
        expected_preparer_sha256=preparer_sha,
        expected_supervisor_sha256="c" * 64,
    )
    monkeypatch.setattr(P, "EXPECTED_PYTHON_VERSION",
                        f"Python {sys.version.split()[0]}")
    return config, P.paths_for(config)


def test_exact_twenty_parent_population_and_receipt_command(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    parents = P.parent_population(config, paths)
    assert len(parents["ordered"]) == 20
    command = P._receipt_command(config, paths, parents)
    assert command[2] == "receipt"
    assert command.count("--cheap") == 8
    assert command.count("--n30") == 8
    assert command[command.index("--run-id") + 1] == P.RUN_ID


def test_prepare_copies_exact_parents_and_persists_real_receipt_exit(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    receipt_sha, preparation_sha = P.prepare(config)
    assert P.sha256_file(paths.receipt) == receipt_sha
    assert P.sha256_file(paths.preparation) == preparation_sha
    summary = json.loads(paths.preparation.read_text())
    assert summary["audit_labels_authorized"] is True
    assert summary["retry_authorized"] is False
    assert len(summary["copied_parents"]) == 20
    assert json.loads(paths.receipt_exit.read_text())["returncode"] == 0
    assert all((config.audit_root / item["path"]).is_file()
               for item in summary["copied_parents"])


def test_nonpass_gate_refuses_before_copy_or_receipt(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    gate = config.producer_root / P.NAMESPACE / P.STAGE_B_GATE_NAME
    payload = json.loads(gate.read_text())
    payload["verdict"] = "FAIL"
    config = P.Config(
        **{**config.__dict__,
           "expected_gate_sha256": _write_json(gate, payload)})
    with pytest.raises(P.PreparationRefusal,
                       match="not an exact terminal PASS"):
        P.prepare(config)
    assert not paths.receipt.exists()
    assert not (config.audit_root / P.NAMESPACE /
                P.STAGE_B_STATE_NAME).exists()


def test_parent_sha_drift_refuses_before_copy(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    parents = P.gate_parents(config, paths)
    relative, _digest = parents["cheap_inputs"][0]
    (config.producer_root / relative).write_text("drift")
    with pytest.raises(P.PreparationRefusal, match="artifact SHA drift"):
        P.prepare(config)
    assert not paths.receipt.exists()


def test_output_collision_refuses_preflight(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    paths.receipt.write_text("collision")
    problems = P.preflight_problems(config, paths)
    assert any("one-shot output collision" in problem for problem in problems)


def test_copy_publication_never_overwrites(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"source bytes")
    destination.write_bytes(b"keep me")
    with pytest.raises(P.PreparationRefusal, match="collision"):
        P._copy_exclusive(source, destination, P.sha256_file(source))
    assert destination.read_bytes() == b"keep me"


def test_parent_population_collision_is_found_before_first_copy(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    last = config.audit_root / P.NAMESPACE / P.STAGE_B_GATE_NAME
    last.write_text("collision")
    with pytest.raises(P.PreparationRefusal,
                       match="destination collisions before copy"):
        P.prepare(config)
    first = config.audit_root / P.NAMESPACE / P.STAGE_B_STATE_NAME
    assert not first.exists()


def test_same_producer_and_audit_root_refuses_preflight(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    changed = P.Config(
        **{**config.__dict__, "producer_root": config.audit_root})
    assert "producer and audit roots must be distinct" in \
        P.preflight_problems(changed, paths)


def test_preparation_is_accepted_by_real_supervisor_preflight(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    supervisor = _supervisor_module()
    supervisor_sha = supervisor.sha256_file(Path(supervisor.__file__))
    config = P.Config(
        **{**config.__dict__,
           "expected_supervisor_sha256": supervisor_sha})
    receipt_sha, preparation_sha = P.prepare(config)

    monkeypatch.setattr(
        supervisor, "AUDIT_SCRIPT_SHA256", P.AUDIT_SCRIPT_SHA256)
    monkeypatch.setattr(
        supervisor, "EXPECTED_PYTHON_VERSION", P.EXPECTED_PYTHON_VERSION)
    monkeypatch.setattr(
        supervisor, "_git", lambda _root, *args:
        supervisor.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")
    supervisor_config = supervisor.Config(
        audit_root=config.audit_root,
        python=config.python,
        expected_receipt_sha256=receipt_sha,
        expected_preparation_sha256=preparation_sha,
        expected_preparer_sha256=config.expected_preparer_sha256,
        expected_supervisor_sha256=supervisor_sha,
    )
    assert supervisor.preflight_problems(
        supervisor_config,
        supervisor.paths_for(config.audit_root),
    ) == []
