"""Offline regression for the recovered SmartBot CLI stream; no provider calls."""
import json
from pathlib import Path

import pytest

from shengji.luna.benchmark_transport import (
    CAPACITY_RETRY_DELAYS, BenchmarkTransport, _benchmark_events_and_usage,
)
from shengji.luna.transport import (
    CodexTurnTransportError, InvocationResult, _events_and_usage,
)
from test_luna_transport import trace


NOTICE = ("Reconnecting... 2/5 (stream disconnected before completion: "
          "WebSocket protocol error: Connection reset without closing handshake)")
FINAL = {"cards": ["C3"], "evaluations": None, "memory": "lead"}


def recovered_rows():
    rows = [json.loads(line) for line in trace(FINAL).splitlines()]
    rows.insert(3, {"type": "error", "message": NOTICE})
    return rows


def raw(rows):
    return b"\n".join(json.dumps(row).encode() for row in rows)


@pytest.mark.parametrize("option", [{}, {"accept_recovered_reconnects": False},
                                    {"accept_recovered_reconnects": True}])
@pytest.mark.parametrize("retries", [(), CAPACITY_RETRY_DELAYS])
def test_recovered_notice_requires_independent_opt_in(tmp_path, option, retries):
    stream = raw(recovered_rows())
    calls = []

    def run(command, prompt, workspace, timeout):
        calls.append(workspace)
        (workspace / "final.json").write_text(json.dumps(FINAL))
        return InvocationResult(0, stream, b"", 13746)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        capacity_retry_delays=retries, **option,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    enabled = option.get("accept_recovered_reconnects", False)
    if enabled:
        assert transport({}) == {"cards": ["C3"], "memory": "lead"}
    else:
        with pytest.raises(CodexTurnTransportError, match="trace event forbidden"):
            transport({})
    assert len(calls) == 1
    receipt = transport.calls[0]
    assert receipt["accepted"] is enabled
    assert receipt["accept_recovered_reconnects"] is enabled
    if enabled:
        assert receipt["recovered_reconnects"] == [{"type": "error", "message": NOTICE}]
        assert receipt["usage"]["input_tokens"] == 100
    else:
        assert "recovered_reconnects" not in receipt
    assert (Path(receipt["evidence_path"]) / "stdout.jsonl").read_bytes() == stream
    with pytest.raises(CodexTurnTransportError, match="trace event forbidden"):
        _events_and_usage(stream)  # legacy parser stays strict


@pytest.mark.parametrize("option", [None, 0, 1, "true", [], {}])
def test_reconnect_option_requires_boolean(tmp_path, option):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid option must refuse before runtime or dispatch")

    with pytest.raises(CodexTurnTransportError, match="reconnect option drift"):
        BenchmarkTransport(evidence_root=tmp_path,
                           accept_recovered_reconnects=option,
                           runtime_attestor=forbidden, run_command=forbidden)


@pytest.mark.parametrize("change", [
    "unknown_error", "extra_field", "before_turn", "after_completion",
    "repeated_notice", "decreasing_attempt", "out_of_range", "no_completion",
    "failed_turn", "tool", "no_usage", "second_turn", "late_message",
    "after_last_message",
])
def test_reconnect_does_not_hide_invalid_trace(change):
    rows = recovered_rows()
    if change == "unknown_error":
        rows[3]["message"] = "some other error"
    elif change == "extra_field":
        rows[3]["tool"] = "shell"
    elif change == "before_turn":
        rows.insert(0, rows.pop(3))
    elif change == "after_completion":
        rows.append(rows.pop(3))
    elif change == "after_last_message":
        rows.insert(-1, rows.pop(3))
    elif change == "repeated_notice":
        rows.insert(4, dict(rows[3]))
    elif change == "decreasing_attempt":
        rows.insert(4, {"type": "error", "message": NOTICE.replace("2/5", "1/5")})
    elif change == "out_of_range":
        rows[3]["message"] = NOTICE.replace("2/5", "6/5")
    elif change == "no_completion":
        rows.pop()
    elif change == "failed_turn":
        rows[-1] = {"type": "turn.failed", "error": {"message": "disconnected"}}
    elif change == "tool":
        rows.insert(4, {"type": "item.completed", "item": {
            "id": "tool", "type": "command_execution"}})
    elif change == "no_usage":
        rows[-1].pop("usage")
    elif change == "second_turn":
        rows.insert(4, {"type": "turn.started"})
    elif change == "late_message":
        rows.append(rows[-2])
    with pytest.raises(CodexTurnTransportError):
        _benchmark_events_and_usage(raw(rows))


@pytest.mark.parametrize("change", ["bad_final", "no_final", "nonzero_rc"])
def test_recovered_notice_still_requires_successful_matching_final(tmp_path, change):
    def run(command, prompt, workspace, timeout):
        if change != "no_final":
            answer = {**FINAL, "cards": ["C4"]} if change == "bad_final" else FINAL
            (workspace / "final.json").write_text(json.dumps(answer))
        return InvocationResult(1 if change == "nonzero_rc" else 0,
                                raw(recovered_rows()), b"", 12)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        accept_recovered_reconnects=True,
        runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"},
        run_command=run)
    with pytest.raises(CodexTurnTransportError):
        transport({})
    assert len(transport.calls) == 1
    assert not transport.calls[0]["accepted"]
