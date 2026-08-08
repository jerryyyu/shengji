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
    schema = ("wrong" if os.environ.get("FAKE_BAD_SHARD") == args.shard_index
              else "teacher-v1-champion-audit-shard-v1")
    Path(args.out).write_text(json.dumps({
        "schema": schema,
        "complete": True,
        "shard_index": int(args.shard_index),
        "shard_count": int(args.shard_count),
    }))
    raise SystemExit(0)
verdict = os.environ.get("FAKE_GATE_VERDICT", "PASS")
Path(args.out).write_text(json.dumps({
    "schema": "teacher-v1-champion-audit-gate-v1",
    "complete": True,
    "terminal": True,
    "verdict": verdict,
}))
raise SystemExit(0 if verdict == "PASS" else 4)
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
    receipt = namespace / S.RECEIPT_NAME
    receipt.write_text("opaque receipt bytes\n")
    monkeypatch.setattr(S, "AUDIT_SCRIPT_SHA256", _sha(script))
    monkeypatch.setattr(
        S, "_git", lambda _root, *args:
        S.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(
        S, "preflight_problems",
        lambda config, paths: S._artifact_problems(
            paths.receipt, config.expected_receipt_sha256))
    config = S.Config(
        audit_root=root,
        python=Path(sys.executable),
        expected_receipt_sha256=_sha(receipt),
        expected_supervisor_sha256=_sha(Path(S.__file__)),
        heartbeat_seconds=0.05,
    )
    return config, S.paths_for(root)


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


def test_terminal_nonpass_is_preserved_without_retry(tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_GATE_VERDICT", "FAIL")
    code, summary = S.run(config)
    assert code == 4
    assert summary["gate_verdict"] == "FAIL"
    assert summary["retry_authorized"] is False
    assert paths.gate.is_file()
    assert paths.progress_final.is_file()


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
    monkeypatch.setattr(S, "AUDIT_SCRIPT_SHA256", _sha(paths.audit_script))
    monkeypatch.setattr(
        S, "_git", lambda _root, *args:
        S.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")
    problems = S.preflight_problems(config, paths)
    assert any("one-shot output collision" in problem for problem in problems)


def test_child_environment_removes_experimental_flags(monkeypatch):
    for name in S.EXPERIMENTAL_FLAGS:
        monkeypatch.setenv(name, "1")
    env = S.child_environment()
    assert all(name not in env for name in S.EXPERIMENTAL_FLAGS)
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_REQUIRE_VOIDS"] == "1"


def test_preflight_rejects_receipt_partial_and_supervisor_drift(
        tmp_path, monkeypatch):
    config, paths = _fixture(tmp_path, monkeypatch)
    # Restore and exercise the real preflight rather than the run fixture's
    # narrow identity substitute.
    monkeypatch.undo()
    monkeypatch.setattr(S, "AUDIT_SCRIPT_SHA256", _sha(paths.audit_script))
    monkeypatch.setattr(
        S, "_git", lambda _root, *args:
        S.AUDIT_GIT if args == ("rev-parse", "HEAD") else "")
    S.artifact_partial(paths.receipt).write_text("incomplete")
    changed = S.Config(
        **{**config.__dict__, "expected_supervisor_sha256": "0" * 64})
    problems = S.preflight_problems(changed, paths)
    assert any("receipt_v1.json.partial" in problem for problem in problems)
    assert "external supervisor SHA predeclaration drift" in problems
