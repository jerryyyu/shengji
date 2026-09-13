import json
from pathlib import Path

import pytest

from shengji.luna.benchmark_transport import BenchmarkTransport
from shengji.luna.transport import (CodexExecPlannerTransport, CodexTurnTransportError,
                                    InvocationResult)
from test_luna_transport import trace


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna"])
def test_model_command_usage_and_retained_response(tmp_path, model):
    final = {"cards": ["C3"], "evaluations": None, "memory": "lead"}
    def run(command, prompt, workspace, timeout):
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
