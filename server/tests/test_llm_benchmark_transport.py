import json
import hashlib
import os
import sys
import time
import subprocess
import venv
from pathlib import Path

import pytest

import shengji.luna.benchmark_transport as benchmark_transport
from shengji.luna.benchmark_transport import (CAPACITY_RETRY_DELAYS,
                                              BenchmarkTransport, output_schema)
from shengji.luna.transport import (CodexExecPlannerTransport, CodexTurnTransportError,
                                    CODE_MODE_DISABLED_DIAGNOSTIC,
                                    CodexProviderResourceError,
                                    InvocationResult, _events_and_usage)
from test_luna_transport import trace
from shengji.luna.canonical import canonical_json_bytes


CAPACITY_MESSAGE = "Selected model is at capacity. Please try a different model."


@pytest.mark.parametrize("rollout", [False, True])
def test_response_binding_joins_raw_final_to_normalized_reply(tmp_path, rollout):
    final = {"cards": None if rollout else ["C3"],
             "evaluations": [{"cards": ["H8"], "continuation": "heuristic-all"}]
                            if rollout else None,
             "memory": "remember"}
    # JSONL text and final file are semantically equal but byte-distinct.
    raw = json.dumps(final, indent=2).encode() + b"\n"
    captured = []

    def run(command, prompt, workspace, timeout):
        captured.append((prompt, workspace))
        (workspace / "final.json").write_bytes(raw)
        return InvocationResult(0, trace(final), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    for index in range(2):
        packet = {"request": index}
        answer = transport(packet)
        key = "evaluations" if rollout else "cards"
        assert answer == {key: final[key], "memory": "remember"}
        expected = {
            "schema": "benchmark-response-binding-v1",
            "packet_sha256": hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
            "final_sha256": hashlib.sha256(raw).hexdigest(),
            "reply_sha256": hashlib.sha256(canonical_json_bytes(answer)).hexdigest()}
        receipt = json.loads((captured[-1][1] / "receipt.json").read_bytes())
        assert receipt["accepted"] is True
        assert receipt["response_binding"] == expected
        assert transport.calls[-1]["response_binding"] == expected
        assert captured[-1][0].endswith(canonical_json_bytes(packet))
        assert expected["final_sha256"] != expected["reply_sha256"]
    assert (transport.calls[0]["response_binding"]["packet_sha256"] !=
            transport.calls[1]["response_binding"]["packet_sha256"])


@pytest.mark.parametrize("kind", ["mismatch", "shape", "malformed"])
def test_rejected_response_never_gets_an_accepted_binding(tmp_path, kind):
    final = {"cards": ["C3"], "evaluations": None, "memory": ""}
    if kind == "shape":
        final["evaluations"] = []
    def run(command, prompt, workspace, timeout):
        raw = b"not json" if kind == "malformed" else json.dumps(final).encode()
        (workspace / "final.json").write_bytes(raw)
        message = {**final, "memory": "different"} if kind == "mismatch" else final
        return InvocationResult(0, trace(message), b"", 1)
    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError):
        transport({})
    assert len(transport.calls) == 1
    receipt = transport.calls[0]
    assert receipt["accepted"] is False
    assert "response_binding" not in receipt
    saved = json.loads((Path(receipt["evidence_path"]) / "receipt.json").read_bytes())
    assert "response_binding" not in saved


def test_default_runner_uninstalled_venv_and_evidence_cwd(tmp_path, monkeypatch):
    from shengji.luna.transport import _default_run

    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(runtime)
    python = runtime / "bin" / "python"
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    probe = subprocess.run(
        [str(python), "-I", "-c",
         "import importlib.util; assert importlib.util.find_spec('shengji') is None"],
        cwd=workspace, capture_output=True, timeout=10)
    assert probe.returncode == 0, probe.stderr
    # An ambient source path must not be needed or passed to the child.
    monkeypatch.setenv("PYTHONPATH", "/nonexistent-source")
    monkeypatch.setattr(sys, "executable", str(python))
    result = _default_run((str(python), "-c",
        "import os,sys; assert 'PYTHONPATH' not in os.environ; "
        "sys.stdout.buffer.write(sys.stdin.buffer.read()); "
        "sys.stderr.write('diagnostic'); raise SystemExit(7)"),
        b"prompt-through-real-watchdog", workspace, 5)
    assert (result.returncode, result.stdout, result.stderr) == (
        7, b"prompt-through-real-watchdog", b"diagnostic")
    assert not (workspace / "timeout.json").exists()


def capacity_trace(*, malformed=False, tool=False):
    rows = [
        {"type": "thread.started", "thread_id": "capacity"},
        {"type": "item.completed", "item": {
            "id": "diagnostic", "type": "error",
            "message": CODE_MODE_DISABLED_DIAGNOSTIC}},
        {"type": "turn.started"},
        {"type": "error", "message": CAPACITY_MESSAGE},
        {"type": "turn.failed", "error": {"message": CAPACITY_MESSAGE}},
    ]
    if malformed:
        rows[-1]["error"]["extra"] = True
    if tool:
        rows[3] = {"type": "item.completed", "item": {
            "id": "tool", "type": "command_execution"}}
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


class FakeRetryClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic_ns(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds * 1_000_000_000


def test_real_timeout_retains_streams_and_benchmark_refuses_once(tmp_path):
    from shengji.luna.transport import _default_run, CodexProviderResourceError

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


def test_capacity_retry_succeeds_with_identical_serialized_request(tmp_path,
                                                                   monkeypatch):
    clock = FakeRetryClock()
    monkeypatch.setattr(benchmark_transport, "time", clock)
    final = {"cards": ["C3"], "evaluations": None, "memory": "lead"}
    prompts, schemas, commands = [], [], []

    def run(command, prompt, workspace, timeout):
        commands.append(command)
        prompts.append(prompt)
        schemas.append((workspace / "schema.json").read_bytes())
        if len(commands) == 1:
            return InvocationResult(1, capacity_trace(), b"", 1)
        (workspace / "final.json").write_text(json.dumps(final))
        return InvocationResult(0, trace(final), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    assert transport({"packet": 1}) == {"cards": ["C3"], "memory": "lead"}
    assert len(transport.calls) == 2
    assert prompts[0] == prompts[1] and schemas[0] == schemas[1]
    assert commands[0][commands[0].index("-m") + 1] == commands[1][commands[1].index("-m") + 1]
    assert commands[0][commands[0].index("--output-schema") + 1] != \
        commands[1][commands[1].index("--output-schema") + 1]
    assert transport.calls[0]["error_type"] == "provider_capacity"
    assert transport.calls[0]["attempt_ordinal"] == 1
    assert transport.calls[0]["backoff_planned"] is True
    assert clock.sleeps == [15]


def test_capacity_retry_is_disabled_by_default(tmp_path, monkeypatch):
    clock = FakeRetryClock()
    monkeypatch.setattr(benchmark_transport, "time", clock)
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(workspace)
        return InvocationResult(1, capacity_trace(), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError):
        transport({})
    assert len(calls) == len(transport.calls) == 1
    assert not transport.calls[0]["retry_enabled"]
    assert clock.sleeps == []


@pytest.mark.parametrize("delays", [None, [], [15, 30, 60], (15,),
                                  (15.0, 30, 60), (True, 30, 60), (0, 30, 60)])
def test_capacity_retry_schedule_is_exact(tmp_path, delays):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid retry schedule must refuse before runtime or dispatch")

    with pytest.raises(CodexTurnTransportError, match="capacity retry drift"):
        BenchmarkTransport(evidence_root=tmp_path, capacity_retry_delays=delays,
                           runtime_attestor=forbidden, run_command=forbidden)


def test_capacity_retry_exhaustion_is_four_bounded_attempts(tmp_path, monkeypatch):
    clock = FakeRetryClock()
    monkeypatch.setattr(benchmark_transport, "time", clock)
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append((workspace, timeout))
        return InvocationResult(1, capacity_trace(), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true", timeout_seconds=120,
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexProviderResourceError, match="capacity exhausted"):
        transport({})
    assert len(calls) == len(transport.calls) == 4
    assert clock.sleeps == [15, 30, 60]
    assert [receipt["attempt_ordinal"] for receipt in transport.calls] == [1, 2, 3, 4]
    assert all(receipt["error_type"] == "provider_capacity"
               for receipt in transport.calls)


def test_capacity_retry_stops_before_backoff_when_deadline_is_insufficient(
        tmp_path, monkeypatch):
    clock = FakeRetryClock()
    monkeypatch.setattr(benchmark_transport, "time", clock)
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(timeout)
        return InvocationResult(1, capacity_trace(), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true", timeout_seconds=10,
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexProviderResourceError,
                       match="deadline exceeded before capacity retry"):
        transport({})
    assert len(calls) == len(transport.calls) == 1
    assert clock.sleeps == []
    assert transport.calls[0]["error_type"] == "provider_capacity"
    assert transport.calls[0]["backoff_planned"] is False


@pytest.mark.parametrize("raw", [b"not-json\n", capacity_trace(malformed=True),
                                  capacity_trace(tool=True)])
def test_noncanonical_capacity_trace_never_retries(tmp_path, raw):
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(True)
        return InvocationResult(1, raw, b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError):
        transport({})
    assert len(calls) == len(transport.calls) == 1


@pytest.mark.parametrize("late", [False, True])
def test_retry_obeys_earlier_row_deadline(tmp_path, monkeypatch, late):
    from shengji.luna import transport as transport_module
    clock = FakeRetryClock()
    monkeypatch.setattr(benchmark_transport, "time", clock)
    monkeypatch.setattr(transport_module, "time", clock)
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(timeout)
        if late:
            clock.now = 11_000_000_000
        return InvocationResult(1, capacity_trace(), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true", timeout_seconds=300,
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        deadline_provider=lambda: 10_000_000_000,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexProviderResourceError, match="deadline exceeded"):
        transport({})
    assert calls == [10]
    assert clock.sleeps == []


@pytest.mark.parametrize("kind", ["timeout", "signal", "generic", "final", "usage", "action"])
def test_retry_does_not_hide_noncapacity_failures(tmp_path, kind):
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(workspace)
        if kind == "timeout":
            raise CodexProviderResourceError("synthetic timeout")
        if kind == "final":
            (workspace / "final.json").write_text("{}")
        raw = capacity_trace()
        if kind == "generic":
            raw = raw.replace(CAPACITY_MESSAGE.encode(), b"Authentication failed")
        if kind in ("usage", "action"):
            rows = [json.loads(line) for line in raw.splitlines()]
            if kind == "usage":
                rows[-1]["usage"] = {"input_tokens": 100}
            else:
                rows.insert(-1, {"type": "item.completed", "item": {
                    "type": "agent_message", "text": '{"cards":["C3"]}'}})
            raw = b"\n".join(json.dumps(row).encode() for row in rows)
        return InvocationResult(-9 if kind == "signal" else 1, raw, b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        capacity_retry_delays=CAPACITY_RETRY_DELAYS,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError):
        transport({})
    assert len(calls) == len(transport.calls) == 1
