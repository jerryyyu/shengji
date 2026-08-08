"""Falsification tests for the one-shot champion-audit supervisor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "scripts" / \
        "teacher_champion_audit_supervisor.py"
    spec = importlib.util.spec_from_file_location("champion_supervisor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


S = _module()


FAKE_AUDIT = r'''#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("mode")
ap.add_argument("--receipt")
ap.add_argument("--expected-receipt-sha256")
ap.add_argument("--shard-index")
ap.add_argument("--shard-count")
ap.add_argument("--selection-worlds")
ap.add_argument("--report-worlds")
ap.add_argument("--input", action="append")
ap.add_argument("--expected-input-sha256", action="append")
ap.add_argument("--out", required=True)
args = ap.parse_args()
if args.mode == "label":
    print(json.dumps({"event": "progress", "shard": args.shard_index}),
          flush=True)
    if os.environ.get("FAKE_FAIL_SHARD") == args.shard_index:
        raise SystemExit(3)
    if os.environ.get("FAKE_MISSING_FINAL_SHARD") == args.shard_index:
        raise SystemExit(0)
    schema = ("wrong" if os.environ.get("FAKE_BAD_SHARD") == args.shard_index
              else "teacher-v1-champion-audit-shard-v2")
    Path(args.out).write_text(json.dumps({
        "schema": schema,
        "complete": True,
        "shard_index": int(args.shard_index),
        "shard_count": int(args.shard_count),
    }))
    if os.environ.get("FAKE_PARTIAL_SHARD") == args.shard_index:
        Path(args.out + ".partial").write_text("surviving partial")
    raise SystemExit(0)
verdict = os.environ.get("FAKE_GATE_VERDICT", "PASS")
passed = verdict == "PASS"
Path(args.out).write_text(json.dumps({
    "schema": "teacher-v1-champion-audit-gate-v2",
    "complete": True,
    "terminal": True,
    "extension_authorized": False,
    "verdict": verdict,
    "champion_fidelity_qualified": passed,
    "stage_c_authorized": passed,
}))
raise SystemExit(0 if passed else 4)
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, monkeypatch):
    root = tmp_path / "server"
    namespace = root / S.NAMESPACE
    namespace.mkdir(parents=True)
    script = root / S.AUDIT_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text(FAKE_AUDIT)
    compiled_engine = root / S.COMPILED_ENGINE
    compiled_engine.parent.mkdir(parents=True)
    compiled_engine.write_bytes(b"compiled-engine")
    receipt = namespace / S.RECEIPT_NAME
    receipt.write_text(json.dumps(S.expected_receipt_identity()))
    receipt_log = namespace / S.RECEIPT_LOG_NAME
    receipt_log.write_text("receipt complete\n")
    receipt_exit = namespace / S.RECEIPT_EXIT_NAME
    receipt_exit.write_text(json.dumps({
        "schema": S.RECEIPT_EXIT_SCHEMA,
        "complete": True,
        "returncode": 0,
    }))
    copied = []
    for name in S.PARENT_NAMES:
        parent = root / S.PARENT_NAMESPACE / name
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_text(f"parent {name}\n")
        copied.append({"path": str(S.PARENT_NAMESPACE / name),
                       "sha256": _sha(parent)})
    copied_state_assets = []
    for name, digest, source_git in S.STATE_ASSET_BINDINGS:
        state_asset = namespace / name
        state_asset.write_text(f"state asset {name}\n")
        digest = _sha(state_asset)
        copied_state_assets.append({
            "source_git": source_git,
            "source_path": f"/source/{name}",
            "path": str(S.NAMESPACE / name),
            "sha256": digest,
        })
    monkeypatch.setattr(S, "STATE_ASSET_BINDINGS", tuple(
        (name, item["sha256"], source_git)
        for (name, _digest, source_git), item in zip(
            S.STATE_ASSET_BINDINGS, copied_state_assets, strict=True)))
    monkeypatch.setattr(S, "AUDIT_SCRIPT_SHA256", _sha(script))
    monkeypatch.setattr(S, "COMPILED_ENGINE_SHA256", _sha(compiled_engine))
    monkeypatch.setattr(
        S, "_git", lambda _root, *args:
        S.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(
        S, "preflight_problems",
        lambda config, paths: S._artifact_problems(
            paths.receipt, config.expected_receipt_sha256))
    supervisor_sha = _sha(Path(S.__file__))
    preparation = namespace / S.PREPARATION_NAME
    preparation.write_text(json.dumps({
        "schema": S.PREPARATION_SCHEMA,
        "complete": True,
        "host": S.EXPECTED_HOST,
        "producer_git": S.PRODUCER_GIT,
        "consumed_git": S.CONSUMED_GIT,
        "fresh_asset_git": S.FRESH_ASSET_GIT,
        "audit_git": S.AUDIT_GIT,
        "audit_script_sha256": S.AUDIT_SCRIPT_SHA256,
        "python": S.EXPECTED_PYTHON_VERSION,
        "preparer_sha256": "d" * 64,
        "expected_supervisor_sha256": supervisor_sha,
        "receipt_identity": S.expected_receipt_identity(),
        "receipt": {"path": str(S.NAMESPACE / S.RECEIPT_NAME),
                    "sha256": _sha(receipt)},
        "receipt_log": {"path": str(S.NAMESPACE / S.RECEIPT_LOG_NAME),
                        "sha256": _sha(receipt_log)},
        "receipt_exit": {"path": str(S.NAMESPACE / S.RECEIPT_EXIT_NAME),
                         "sha256": _sha(receipt_exit), "returncode": 0},
        "copied_parents": copied,
        "copied_state_assets": copied_state_assets,
        "audit_labels_authorized": True,
        "retry_authorized": False,
        "production_promotion": False,
    }))
    config = S.Config(
        audit_root=root,
        python=Path(sys.executable),
        expected_receipt_sha256=_sha(receipt),
        expected_preparation_sha256=_sha(preparation),
        expected_preparer_sha256="d" * 64,
        expected_supervisor_sha256=supervisor_sha,
        heartbeat_seconds=0.05,
    )
    return config, S.paths_for(root)


def _restore_real_preflight(monkeypatch, paths):
    monkeypatch.setattr(S, "AUDIT_SCRIPT_SHA256", _sha(paths.audit_script))
    monkeypatch.setattr(
        S, "COMPILED_ENGINE_SHA256", _sha(paths.compiled_engine))
    monkeypatch.setattr(S, "STATE_ASSET_BINDINGS", tuple(
        (name, _sha(paths.namespace / name), source_git)
        for name, _digest, source_git in S.STATE_ASSET_BINDINGS))
    monkeypatch.setattr(
        S, "_git", lambda _root, *args:
        S.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")


def test_commands_pin_exact_eight_by_32_by_32_packet(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    commands = [S.label_command(config, paths, shard)
                for shard in range(S.SHARD_COUNT)]
    assert len(commands) == 8
    assert all(command[2] == "label" for command in commands)
    assert [command[command.index("--shard-index") + 1]
            for command in commands] == [str(index) for index in range(8)]
    assert all(command[command.index("--selection-worlds") + 1] == "32"
               for command in commands)
    assert all(command[command.index("--report-worlds") + 1] == "32"
               for command in commands)


def test_success_owns_all_wait_statuses_then_runs_one_gate(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    code, summary = S.run(config)
    assert code == 0
    assert summary["gate_verdict"] == "PASS"
    assert summary["retry_authorized"] is False
    assert all(path.is_file() for path in paths.labels)
    assert paths.gate.is_file()
    assert paths.progress_final.is_file()
    assert not paths.progress_partial.exists()
    exits = [json.loads(path.with_suffix(".exit.json").read_text())
             for path in paths.labels]
    assert [item["returncode"] for item in exits] == [0] * 8
    assert json.loads(paths.gate.with_suffix(".exit.json").read_text())[
        "returncode"] == 0


def test_one_label_failure_preserves_evidence_and_never_runs_gate(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_FAIL_SHARD", "3")
    with pytest.raises(S.SupervisorRefusal, match="label-03 exited 3"):
        S.run(config)
    assert not paths.gate.exists()
    assert paths.progress_partial.is_file()
    assert not paths.progress_final.exists()
    failed = paths.labels[3].with_suffix(".exit.json")
    assert json.loads(failed.read_text())["returncode"] == 3


def test_zero_exit_without_final_preserves_evidence_and_never_runs_gate(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MISSING_FINAL_SHARD", "3")
    with pytest.raises(
            S.SupervisorRefusal,
            match="label-03 exited zero without regular final"):
        S.run(config)
    assert not paths.gate.exists()
    assert paths.progress_partial.is_file()
    assert not paths.progress_final.exists()
    assert json.loads(paths.labels[3].with_suffix(
        ".exit.json").read_text())["returncode"] == 0


def test_zero_exit_with_surviving_partial_never_runs_gate(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_PARTIAL_SHARD", "4")
    with pytest.raises(
            S.SupervisorRefusal,
            match="label-04 exited zero with surviving partial"):
        S.run(config)
    assert not paths.gate.exists()
    assert paths.progress_partial.is_file()
    assert not paths.progress_final.exists()
    assert S.artifact_partial(paths.labels[4]).is_file()


def test_terminal_nonpass_is_preserved_without_retry(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_GATE_VERDICT", "FAIL")
    code, summary = S.run(config)
    assert code == 4
    assert summary["gate_verdict"] == "FAIL"
    assert summary["retry_authorized"] is False
    assert paths.gate.is_file()
    assert paths.progress_final.is_file()


def test_unknown_terminal_verdict_is_not_accepted(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_GATE_VERDICT", "BOGUS")
    with pytest.raises(S.SupervisorRefusal,
                       match="terminal gate exit/verdict contract drift"):
        S.run(config)
    assert paths.gate.is_file()
    assert paths.progress_partial.is_file()
    assert not paths.progress_final.exists()


def test_zero_exit_with_malformed_label_never_reaches_gate(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_BAD_SHARD", "5")
    with pytest.raises(S.SupervisorRefusal,
                       match="label 5 publication identity drift"):
        S.run(config)
    assert all(path.with_suffix(".exit.json").is_file()
               for path in paths.labels)
    assert not paths.gate.exists()
    assert paths.progress_partial.is_file()


def test_preexisting_output_refuses_before_any_child(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    paths.labels[0].write_text("collision")
    # Restore the real preflight around the fixture's fake Git identity.
    monkeypatch.undo()
    _restore_real_preflight(monkeypatch, paths)
    problems = S.preflight_problems(config, paths)
    assert any("one-shot output collision" in problem for problem in problems)


def test_child_environment_removes_experimental_flags(monkeypatch):
    for name in S.EXPERIMENTAL_FLAGS:
        monkeypatch.setenv(name, "1")
    env = S.child_environment()
    assert all(name not in env for name in S.EXPERIMENTAL_FLAGS)
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_REQUIRE_VOIDS"] == "1"


def test_real_preflight_is_pinned_to_mini(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.undo()
    _restore_real_preflight(monkeypatch, paths)
    monkeypatch.setattr(S.socket, "gethostname", lambda: "not-the-mini")
    assert "execution host not-the-mini, expected Jerrys-Mac-mini.local" in \
        S.preflight_problems(config, paths)


def test_preflight_rejects_receipt_partial_and_supervisor_drift(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    # Restore and exercise the real preflight rather than the run fixture's
    # narrow identity substitute.
    monkeypatch.undo()
    _restore_real_preflight(monkeypatch, paths)
    S.artifact_partial(paths.receipt).write_text("incomplete")
    changed = S.Config(
        **{**config.__dict__, "expected_supervisor_sha256": "0" * 64})
    problems = S.preflight_problems(changed, paths)
    assert any("receipt_v2.json.partial" in problem for problem in problems)
    assert "external supervisor SHA predeclaration drift" in problems


def test_preflight_requires_zero_exit_bound_preparation(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.undo()
    _restore_real_preflight(monkeypatch, paths)
    exit_payload = json.loads(paths.receipt_exit.read_text())
    exit_payload["returncode"] = 3
    paths.receipt_exit.write_text(json.dumps(exit_payload))
    problems = S.preflight_problems(config, paths)
    assert any("receipt exit" in problem or "zero exit" in problem
               for problem in problems)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("schema", "teacher-v1-champion-audit-receipt-v0"),
        ("complete", False),
        ("run_id", "teacher-v3-report-lcb-audit-v1-149m"),
        ("consumed_audit_state_set", {
            "path": str(S.NAMESPACE / "champion_audit_states_v2.json"),
            "sha256": S.AUDIT_STATE_SHA256,
        }),
        ("execution_predeclaration", {
            "git": "182d1df21697cedd722edfd3215ea1e2a7dd8753",
            "audit_script_sha256": "0" * 64,
        }),
    ),
)
def test_preflight_rejects_hash_bound_wrong_receipt_identity(
        tmp_path, monkeypatch, field, bad_value):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.undo()
    _restore_real_preflight(monkeypatch, paths)

    wrong_identity = S.expected_receipt_identity()
    wrong_identity[field] = bad_value
    paths.receipt.write_text(json.dumps(wrong_identity))
    preparation = json.loads(paths.preparation.read_text())
    preparation["receipt"]["sha256"] = _sha(paths.receipt)
    preparation["receipt_identity"] = wrong_identity
    paths.preparation.write_text(json.dumps(preparation))
    changed = S.Config(
        **{**config.__dict__,
           "expected_receipt_sha256": _sha(paths.receipt),
           "expected_preparation_sha256": _sha(paths.preparation)})

    problems = S.preflight_problems(changed, paths)
    assert "audit receipt authority/identity drift" in problems
    assert "audit preparation authority/identity drift" in problems
    with pytest.raises(S.SupervisorRefusal, match="preflight"):
        S.run(changed)
    assert not any(path.exists() for path in paths.labels)
    assert not paths.gate.exists()
