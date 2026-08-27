"""Boundary witnesses for the PT-Cla0 Claude planner adapter and runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from shengji.rl import privileged_teacher_cla0 as cla0
from shengji.rl.privileged_teacher_sol0 import MAX_SESSION_WALL_SECONDS


def _load_script(name: str):
    script = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"),
                                                 script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_command_pins_model_allowlist_and_headless_shape(tmp_path):
    command = cla0.claude_planner_command(
        claude_binary=tmp_path / "claude",
        tool_command="/py -P -B /tool.py --mailbox /mb")
    assert command[0] == str(tmp_path / "claude")
    assert "-p" in command
    model_index = command.index("--model")
    assert command[model_index + 1] == cla0.CLAUDE_MODEL
    output_index = command.index("--output-format")
    assert command[output_index + 1] == "json"
    allowed_index = command.index("--allowedTools")
    assert command[allowed_index + 1] == \
        "Bash(/py -P -B /tool.py --mailbox /mb:*)"
    denied_index = command.index("--disallowedTools")
    denied = command[denied_index + 1].split(",")
    for tool in ("Write", "Edit", "WebFetch", "WebSearch", "Agent"):
        assert tool in denied
    turns_index = command.index("--max-turns")
    assert command[turns_index + 1] == str(cla0.MAX_PLANNER_TURNS)


def test_planner_process_scrubs_env_bounds_wall_and_writes_final(
        tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    envelope = json.dumps({
        "type": "result",
        "result": json.dumps({
            "schema": "privileged-teacher-sol0-final-response-v1",
            "status": "complete", "completion_token": "tok"}),
    }).encode("utf-8")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=envelope)

    monkeypatch.setenv("PYTHONPATH", "/poison")
    monkeypatch.setattr(cla0.subprocess, "run", fake_run)
    final_path = tmp_path / "final.json"
    completed = cla0.claude_planner_process(
        object(), workspace=tmp_path, mailbox_path=tmp_path / "mb",
        tool_script=tmp_path / "tool.py",
        codex_binary=tmp_path / "claude", prompt="PROMPT",
        final_output_path=final_path)
    assert completed.returncode == 0
    kwargs = captured["kwargs"]
    assert "PYTHONPATH" not in kwargs["env"]
    assert kwargs["timeout"] == MAX_SESSION_WALL_SECONDS
    assert kwargs["cwd"] == tmp_path
    assert kwargs["input"] == b"PROMPT"
    final = json.loads(final_path.read_bytes())
    assert final["completion_token"] == "tok"


def test_final_envelope_extraction_is_strict_with_single_fence_leniency():
    inner = json.dumps({"schema": "s", "status": "complete",
                        "completion_token": "t"})
    plain = json.dumps({"result": inner}).encode("utf-8")
    assert json.loads(cla0.extract_final_response(plain)) == json.loads(inner)
    fenced = json.dumps(
        {"result": f"```json\n{inner}\n```"}).encode("utf-8")
    assert json.loads(cla0.extract_final_response(fenced)) == \
        json.loads(inner)
    assert cla0.extract_final_response(b"not json") is None
    assert cla0.extract_final_response(json.dumps(
        {"result": 7}).encode("utf-8")) is None
    assert cla0.extract_final_response(b"[]") is None


def test_planner_process_leaves_no_final_on_malformed_envelope(
        tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=b"crash text")

    monkeypatch.setattr(cla0.subprocess, "run", fake_run)
    final_path = tmp_path / "final.json"
    completed = cla0.claude_planner_process(
        object(), workspace=tmp_path, mailbox_path=tmp_path / "mb",
        tool_script=tmp_path / "tool.py",
        codex_binary=tmp_path / "claude", prompt="PROMPT",
        final_output_path=final_path)
    assert completed.returncode == 1
    assert not final_path.exists()


def test_claude_binary_resolution_refuses_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(cla0, "which", lambda _name: None)
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude binary absent"):
        cla0.resolve_claude_binary()
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude binary absent"):
        cla0.resolve_claude_binary(tmp_path / "missing")


def test_claude_version_binds_model_tag_and_refuses_empty(monkeypatch,
                                                          tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0,
                                           stdout="9.9.9 (Claude Code)\n")

    monkeypatch.setattr(cla0.subprocess, "run", fake_run)
    version = cla0.claude_version(tmp_path / "claude")
    assert version == f"9.9.9 (Claude Code) [{cla0.CLAUDE_MODEL}]"

    def empty_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="\n")

    monkeypatch.setattr(cla0.subprocess, "run", empty_run)
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude version drift"):
        cla0.claude_version(tmp_path / "claude")


def test_model_allowlist_refuses_unknown_and_pins_per_model_command(
        tmp_path):
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude model identity drift"):
        cla0.require_claude_model("claude-9-mega")
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude model identity drift"):
        cla0.make_claude_planner_process("gpt-5.6-sol")
    for model in cla0.ALLOWED_CLAUDE_MODELS:
        command = cla0.claude_planner_command(
            claude_binary=tmp_path / "claude", tool_command="/t",
            model=model)
        assert command[command.index("--model") + 1] == model


def test_cla0_runner_reuses_reviewed_sol0_helpers_verbatim():
    cla0_runner = _load_script("run_privileged_teacher_cla0.py")
    assert cla0_runner._read_single_link is \
        cla0_runner._sol0._read_single_link
    assert cla0_runner._strict_report is cla0_runner._sol0._strict_report
    assert cla0_runner._publish_exclusive is \
        cla0_runner._sol0._publish_exclusive
    assert cla0_runner._run_with_frozen_design is \
        cla0_runner._sol0._run_with_frozen_design


def test_cla0_runner_frozen_design_gate_refuses_before_execution():
    cla0_runner = _load_script("run_privileged_teacher_cla0.py")

    class Design:
        def payload(self):
            return {"schema": "x"}

    calls: list[str] = []
    with pytest.raises(ValueError, match="frozen runtime design drift"):
        cla0_runner._run_with_frozen_design(
            Design(), "0" * 64, lambda: calls.append("external"))
    assert calls == []
