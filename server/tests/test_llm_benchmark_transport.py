import json
import os
import sys
import time
from pathlib import Path

import pytest

from shengji.luna.benchmark_transport import BenchmarkTransport, output_schema
from shengji.luna.transport import (CodexExecPlannerTransport, CodexTurnTransportError,
                                    InvocationResult, _events_and_usage)
from test_luna_transport import trace


def test_real_timeout_retains_streams_and_benchmark_refuses_once(tmp_path, monkeypatch):
    from shengji.luna import transport as transport_module
    from shengji.luna.transport import _default_run, CodexProviderResourceError

    # The test venv may have an editable install of a different worktree.
    # Exercise this source's real watchdog, not that stale installed module.
    start = transport_module._start_contained_process
    def start_current_source(command, *, workspace, env, active_calls):
        env = {**env, "PYTHONPATH": str(Path(transport_module.__file__).resolve().parents[2])}
        return start(command, workspace=workspace, env=env, active_calls=active_calls)
    monkeypatch.setattr(transport_module, "_start_contained_process", start_current_source)
    completed = _default_run((sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'OUT'); "
        "sys.stderr.buffer.write(b'ERR'); raise SystemExit(7)"), b"", tmp_path, 5)
    assert (completed.returncode, completed.stdout, completed.stderr) == (7, b"OUT", b"ERR")
    assert not (tmp_path / "timeout.json").exists()

    calls = []
    def run(command, prompt, workspace, timeout):
        calls.append(workspace)
        return _default_run((sys.executable, "-c",
            "import os,sys,time; "
            "print(os.getpid(), flush=True); "
            "print('diagnostic', file=sys.stderr, flush=True); "
            "time.sleep(60)"), prompt, workspace, timeout)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true", timeout_seconds=1,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexProviderResourceError,
                       match="^Codex turn deadline exceeded$"):
        transport({})
    assert len(calls) == len(transport.calls) == 1
    workspace = calls[0]
    stdout = (workspace / "stdout.jsonl").read_text()
    assert len(stdout.splitlines()) == 1  # no duplicated timeout prefix
    pid = int(stdout)
    assert (workspace / "stderr.txt").read_bytes() == b"diagnostic\n"
    evidence = json.loads((workspace / "timeout.json").read_bytes())
    assert evidence["accepted"] is False
    assert evidence["timeout_seconds"] == 1
    assert evidence["wall_ms"] >= 1000
    assert evidence["returncode"] < 0
    receipt = json.loads((workspace / "receipt.json").read_bytes())
    assert receipt["accepted"] is False
    assert receipt["error"] == "CodexProviderResourceError: Codex turn deadline exceeded"
    assert not (workspace / "final.json").exists()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna"])
def test_model_command_usage_and_retained_response(tmp_path, model):
    final = {"cards": ["C3"], "evaluations": None, "memory": "lead"}
    def run(command, prompt, workspace, timeout):
        assert b"Only the first play defines the lead" in prompt
        assert b"current observation overrides stale memory" in prompt
        assert command[command.index("-m") + 1] == model
        assert "--ignore-user-config" in command
        assert "--ignore-rules" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert timeout == 90
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(final))
        return InvocationResult(0, trace(final), b"", 12)
    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true", model=model,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    assert transport({"observation": {}, "memory": ""}) == {"cards": ["C3"], "memory": "lead"}
    receipt = transport.calls[0]
    assert receipt["accepted"] and receipt["usage"]["input_tokens"] == 100
    assert (Path(receipt["evidence_path"]) / "stdout.jsonl").read_bytes() == trace(final)


def test_legacy_transport_still_refuses_sol(tmp_path):
    with pytest.raises(CodexTurnTransportError, match="identity drift"):
        CodexExecPlannerTransport(codex_binary="/usr/bin/true", model="gpt-5.6-sol")


def test_forbidden_tool_event_retained_as_failure(tmp_path):
    final = {"cards": ["C3"], "evaluations": None, "memory": ""}
    def run(command, prompt, workspace, timeout):
        (workspace / "final.json").write_text(json.dumps(final))
        return InvocationResult(0, trace(final, item_type="command_execution"), b"", 12)
    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError, match="tool event forbidden"):
        transport({})
    assert transport.calls[0]["accepted"] is False
    assert (Path(transport.calls[0]["evidence_path"]) / "receipt.json").exists()


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_final_answers_are_identical_or_refused(tmp_path, conflicting):
    final = {"cards": ["C3"], "evaluations": None, "memory": "lead"}
    rows = [json.loads(line) for line in trace(final).splitlines()]
    duplicate = json.loads(json.dumps(rows[-2]))
    duplicate["item"]["id"] = "item_1"
    if conflicting:
        duplicate["item"]["text"] = json.dumps({**final, "cards": ["C4"]})
    rows.insert(-1, duplicate)
    raw = b"\n".join(json.dumps(row).encode() for row in rows)
    # The default shared parser must not silently change existing callers.
    with pytest.raises(CodexTurnTransportError, match="^Codex completion telemetry drift$"):
        _events_and_usage(raw)

    def run(command, prompt, workspace, timeout):
        (workspace / "final.json").write_text(json.dumps(final))
        return InvocationResult(0, raw, b"", 12)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    if conflicting:
        with pytest.raises(CodexTurnTransportError, match="^benchmark final/message mismatch$"):
            transport({})
    else:
        assert transport({}) == {"cards": ["C3"], "memory": "lead"}
        assert transport.calls[0]["usage"]["input_tokens"] == 100
        assert transport.calls[0]["usage"]["output_tokens"] == 20
    assert transport.calls[0]["accepted"] is not conflicting
    assert (Path(transport.calls[0]["evidence_path"]) / "stdout.jsonl").read_bytes() == raw


def test_rollout_schema_expresses_existing_call_limits():
    arrays = output_schema()["properties"]["evaluations"]["anyOf"][0]
    assert arrays["minItems"] == 1
    assert arrays["maxItems"] == 16


@pytest.mark.parametrize("change", ["memory", "cards"])
def test_cli_final_output_wins_over_intermediate_message(tmp_path, change):
    first = {"cards": ["C3"], "evaluations": None, "memory": "draft"}
    final = {**first, change: "revised" if change == "memory" else ["C4"]}
    rows = [json.loads(line) for line in trace(first).splitlines()]
    last = json.loads(json.dumps(rows[-2]))
    last["item"].update(id="item_final", text=json.dumps(final))
    rows.insert(-1, last)
    raw = b"\n".join(json.dumps(row).encode() for row in rows)

    def run(command, prompt, workspace, timeout):
        (workspace / "final.json").write_text(json.dumps(final))
        return InvocationResult(0, raw, b"", 12)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    assert transport({}) == {"cards": final["cards"], "memory": final["memory"]}
    assert transport.calls[0]["usage"]["input_tokens"] == 100
    assert (Path(transport.calls[0]["evidence_path"]) / "stdout.jsonl").read_bytes() == raw
    with pytest.raises(CodexTurnTransportError, match="^Codex completion telemetry drift$"):
        _events_and_usage(raw)


def test_final_message_mode_rejects_message_after_completion():
    rows = [json.loads(line) for line in trace({"cards": ["C3"]}).splitlines()]
    rows.append(rows[-2])
    raw = b"\n".join(json.dumps(row).encode() for row in rows)
    with pytest.raises(CodexTurnTransportError, match="^Codex final-message ordering drift$"):
        _events_and_usage(raw, use_final_message=True)
