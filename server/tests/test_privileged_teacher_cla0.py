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


def test_claude_command_is_exactly_the_reviewed_isolated_shape(tmp_path):
    command = cla0.claude_planner_command(
        claude_binary=tmp_path / "claude",
        tool_command="/py -P -B /tool.py --mailbox /mb")
    assert command == (
        str(tmp_path / "claude"), "-p",
        "--model", cla0.CLAUDE_MODEL,
        "--effort", cla0.REASONING_EFFORT,
        "--output-format", "json",
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools", "Bash",
        "--allowedTools", "Bash(/py -P -B /tool.py --mailbox /mb:*)",
        "--disallowedTools", ",".join(cla0.DENIED_TOOLS),
        "--max-turns", str(cla0.MAX_PLANNER_TURNS),
    )
    for flag in cla0.ISOLATION_FLAGS:
        assert flag in command
    assert "--bare" not in command  # --bare blocks credential loading


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-poison")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-poison")
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
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in kwargs["env"]
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
    prosed = json.dumps({"result": (
        "I dumped 20 points on the HK-HK-HA throw and drained trumps.\n"
        + inner)}).encode("utf-8")
    assert json.loads(cla0.extract_final_response(prosed)) == \
        json.loads(inner)
    prose_only = json.dumps({"result": "no json here at all"}).encode()
    assert cla0.extract_final_response(prose_only) is None
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


def test_claude_version_is_raw_binary_output_at_gate_altitude(tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    fake.chmod(0o755)
    version = cla0.claude_version(fake)
    live = subprocess.run(
        (str(fake), "--version"), check=True, capture_output=True,
        text=True).stdout.strip()
    assert version == live == "9.9.9 (Claude Code)"
    assert "[" not in version

    empty = tmp_path / "empty"
    empty.write_text("#!/bin/sh\necho ''\n")
    empty.chmod(0o755)
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude version drift"):
        cla0.claude_version(empty)

    tagged = tmp_path / "tagged"
    tagged.write_text(
        "#!/bin/sh\necho '9.9.9 (Claude Code) [claude-fable-5]'\n")
    tagged.chmod(0o755)
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude version drift"):
        cla0.claude_version(tagged)


def test_inherited_run_dev_gate_expression_passes_with_cla0_design(tmp_path):
    """Replicates run_dev's exact binding comparison with a Cla0 design.

    The gate reruns ``<binary> --version`` and requires the raw stripped
    output to equal ``design.codex_version`` (privileged_teacher_sol0_report
    lines 415-425).  With ``claude_version()`` feeding the design, that
    expression must hold; with the previously-tagged form it must not.
    """
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    fake.chmod(0o755)
    design = _design(codex_version=cla0.claude_version(fake))
    live = subprocess.run(
        (str(fake.resolve()), "--version"), check=True,
        capture_output=True, text=True).stdout.strip()
    assert live == design.codex_version
    tagged_design = _design(
        codex_version="9.9.9 (Claude Code) [claude-fable-5]")
    assert live != tagged_design.codex_version


def _design(**overrides):
    fields = dict(
        seed_commitment_sha256="a" * 64, execution_git="b" * 40,
        native_sha256="c" * 64, hostname="Jerrys-Mac-mini.local",
        c0_external_sha256="d" * 64, c0_report_sha256="e" * 64,
        c0_execution_git="f" * 40, full_external_sha256="0" * 64,
        full_report_sha256="1" * 64, full_execution_git="2" * 40,
        codex_binary_sha256="3" * 64, codex_version="9.9.9 (Claude Code)",
        python_binary_sha256="4" * 64, python_version="3.14.3 test",
        tool_script_sha256="5" * 64)
    fields.update(overrides)
    return cla0.Cla0Design(**fields)


def test_design_payload_identifies_claude_and_matches_command(tmp_path):
    design = _design()
    payload = design.payload()
    assert payload["schema"] == cla0.CLA0_DESIGN_SCHEMA
    assert payload["model"] == cla0.CLAUDE_MODEL
    config = payload["planner_config"]
    assert config["planner"] == "claude-cli"
    assert config["reasoning_effort"] == cla0.REASONING_EFFORT == "high"
    assert config["isolation_flags"] == list(cla0.ISOLATION_FLAGS)
    assert config["tools"] == ["Bash"]
    assert config["max_planner_turns"] == cla0.MAX_PLANNER_TURNS
    command = cla0.claude_planner_command(
        claude_binary=tmp_path / "claude", tool_command="/t",
        model=payload["model"])
    assert command[command.index("--model") + 1] == payload["model"]
    assert command[command.index("--effort") + 1] == \
        config["reasoning_effort"]
    assert payload["codex_version"] == "9.9.9 (Claude Code)"
    from shengji.rl.privileged_teacher_sol0 import (
        MAX_EVALUATIONS_PER_DECISION, MAX_EVALUATIONS_PER_ROUND)
    assert config["max_evaluations_per_decision"] == \
        MAX_EVALUATIONS_PER_DECISION
    assert config["max_evaluations_per_round"] == MAX_EVALUATIONS_PER_ROUND
    with pytest.raises(cla0.PrivilegedTeacherSol0Error,
                       match="Claude model identity drift"):
        _design(claude_model="gpt-5.6-sol")


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
