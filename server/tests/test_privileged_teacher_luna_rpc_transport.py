"""Can-fail tests for the zero-tool Codex turn transport."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl import privileged_teacher_luna_rpc_transport as transport_module
from shengji.rl.privileged_teacher_luna_rpc_transport import (
    CODE_MODE_DISABLED_DIAGNOSTIC,
    CodexExecPlannerTransport,
    CodexTurnTransportError,
    DISABLED_FEATURES,
    InvocationResult,
    PINNED_CODEX_VERSION,
    attest_codex_runtime,
    validate_private_evidence,
    validate_private_refusal_evidence,
)
from shengji.rl.privileged_teacher_luna_turn_rpc import (
    DecisionPacket,
    PhaseContext,
    TeamMemory,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SECRET = b"luna-rpc-transport-secret-32b!!!"
assert len(SECRET) == 32


def test_parent_death_watchdog_kills_provider_process(tmp_path):
    pid_path = tmp_path / "provider.pid"
    command = (
        sys.executable, "-c",
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)", str(pid_path))
    manager = transport_module.ActiveCallManager()
    process, controller_fd = transport_module._start_contained_process(
        command, workspace=tmp_path, env=dict(os.environ),
        active_calls=manager)
    provider_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_path.exists():
            time.sleep(0.01)
        assert pid_path.exists()
        provider_pid = int(pid_path.read_text())
        os.close(controller_fd)
        controller_fd = -1
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(provider_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        with pytest.raises(ProcessLookupError):
            os.kill(provider_pid, 0)
    finally:
        if controller_fd >= 0:
            manager.release(process.pid, controller_fd)
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait(timeout=5)
        if provider_pid is not None:
            try:
                os.kill(provider_pid, 9)
            except ProcessLookupError:
                pass


def test_contained_run_proxies_exact_result_and_enforces_timeout(tmp_path):
    exact = transport_module._default_run(
        (sys.executable, "-c",
         "import sys; sys.stdout.buffer.write(b'OUT'); "
         "sys.stderr.buffer.write(b'ERR'); raise SystemExit(7)"),
        b"prompt", tmp_path, 5)
    assert (exact.returncode, exact.stdout, exact.stderr) == (7, b"OUT", b"ERR")
    started = time.monotonic()
    with pytest.raises(transport_module.CodexProviderResourceError,
                       match="deadline"):
        transport_module._default_run(
            (sys.executable, "-c", "import time; time.sleep(60)"),
            b"", tmp_path, 1)
    assert time.monotonic() - started < 5


def test_active_call_manager_kills_concurrent_groups_and_helper_orphan(
        tmp_path):
    processes = []
    provider_pids = []
    manager = transport_module.ActiveCallManager()
    for index in range(2):
        pid_path = tmp_path / f"provider-{index}.pid"
        command = (
            sys.executable, "-c",
            "import os,pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
            "time.sleep(60)", str(pid_path))
        process, watchdog_fd = transport_module._start_contained_process(
            command, workspace=tmp_path, env=dict(os.environ),
            active_calls=manager)
        processes.append((process, watchdog_fd))
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            paths = [tmp_path / f"provider-{index}.pid" for index in range(2)]
            if all(path.exists() for path in paths):
                provider_pids = [int(path.read_text()) for path in paths]
                break
            time.sleep(0.01)
        assert len(provider_pids) == 2
        # Kill only one helper first.  The manager must still own and reap its
        # surviving child while independently cancelling the other group.
        os.kill(processes[0][0].pid, 9)
        processes[0][0].wait(timeout=5)
        manager.terminate()
        for process, _watchdog_fd in processes:
            process.wait(timeout=5)
        for provider_pid in provider_pids:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    os.kill(provider_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.01)
            with pytest.raises(ProcessLookupError):
                os.kill(provider_pid, 0)
    finally:
        manager.terminate()
        for process, watchdog_fd in processes:
            manager.release(process.pid, watchdog_fd)
            if process.poll() is None:
                os.killpg(process.pid, 9)
                process.wait(timeout=5)
        for provider_pid in provider_pids:
            try:
                os.kill(provider_pid, 9)
            except ProcessLookupError:
                pass


def packet():
    coordinate = ("2", 0, 0)
    game = selfplay.LunaSelfPlayGame(
        selfplay.build_root(SECRET, coordinate), coordinate=coordinate,
        seed_secret=SECRET)
    team = game.acting_team
    assert team in (0, 1)
    observation = game.session(team).observe()
    memory = TeamMemory.initial(
        team, selfplay._state_digest(game.rnd, team))
    return DecisionPacket.from_observation(
        observation, coordinate=coordinate, mirror=0, team=team,
        decision_index=0, memory=memory, phase=PhaseContext())


def trace(final: dict[str, object], *, item_type="agent_message",
          usage: dict[str, int] | None = None) -> bytes:
    usage = usage or {
        "input_tokens": 100, "cached_input_tokens": 10,
        "cache_write_input_tokens": 0, "output_tokens": 20,
        "reasoning_output_tokens": 5}
    rows = [
        {"type": "thread.started", "thread_id": "test"},
        {"type": "item.completed", "item": {
            "id": "diagnostic", "type": "error",
            "message": CODE_MODE_DISABLED_DIAGNOSTIC}},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {
            "id": "item_0", "type": item_type,
            "text": json.dumps(final, separators=(",", ":"))}},
        {"type": "turn.completed", "usage": usage},
    ]
    return b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in rows)


def test_trace_requires_exact_fail_closed_diagnostic_before_turn():
    final = {"schema": "pt-luna-provider-intent-v1",
             "decision_sha256": "a" * 64, "kind": "play",
             "candidate_index": 0, "confidence": "low",
             "candidate_indices": [], "continuations": [],
             "planning_note": "bounded"}
    raw = trace(final)
    from shengji.rl import privileged_teacher_luna_rpc_transport as module
    module._events_and_usage(raw)

    rows = [json.loads(line) for line in raw.splitlines()]
    without = b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in rows
        if not (row["type"] == "item.completed"
                and row["item"]["type"] == "error"))
    with pytest.raises(CodexTurnTransportError,
                       match="completion telemetry drift"):
        module._events_and_usage(without)

    rows[1]["item"]["message"] += " changed"
    changed = b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in rows)
    with pytest.raises(CodexTurnTransportError,
                       match="fail-closed diagnostic drift"):
        module._events_and_usage(changed)

    rows = [json.loads(line) for line in raw.splitlines()]
    diagnostic = rows.pop(1)
    rows.insert(3, diagnostic)
    reordered = b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in rows)
    with pytest.raises(CodexTurnTransportError,
                       match="fail-closed diagnostic drift"):
        module._events_and_usage(reordered)


class FakeRun:
    def __init__(self, *, mutate=None, stderr=b""):
        self.mutate = mutate
        self.stderr = stderr
        self.calls = []

    def __call__(self, command, prompt, workspace, timeout):
        self.calls.append((command, prompt, workspace, timeout))
        decision = packet_sha_from_prompt(prompt)
        final = {"schema": "pt-luna-provider-intent-v1",
                 "decision_sha256": decision, "kind": "play",
                 "candidate_index": 0, "confidence": "low",
                 "candidate_indices": [], "continuations": [],
                 "planning_note": "bounded"}
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.write_text(json.dumps(final), encoding="utf-8")
        item_type = "agent_message"
        usage = None
        if self.mutate == "stale":
            final["decision_sha256"] = "0" * 64
            final_path.write_text(json.dumps(final), encoding="utf-8")
        elif self.mutate == "tool":
            item_type = "command_execution"
        elif self.mutate == "usage":
            usage = {"input_tokens": 1, "output_tokens": 1}
        elif self.mutate == "final-mismatch":
            final_path.write_text("{}", encoding="utf-8")
        return InvocationResult(0, trace(final, item_type=item_type, usage=usage),
                                self.stderr, 7)


def packet_sha_from_prompt(prompt: bytes) -> str:
    marker = b'"decision_sha256":"'
    start = prompt.index(marker) + len(marker)
    return prompt[start:start + 64].decode("ascii")


def transport(tmp_path, fake):
    return CodexExecPlannerTransport(
        codex_binary="/usr/bin/true", temp_root=tmp_path,
        run_command=fake, runtime_attestor=lambda _: {
            "schema": "pt-luna-codex-tool-catalog-v1"})


def test_valid_call_has_no_tool_surface_and_binds_usage(tmp_path):
    fake = FakeRun()
    response = transport(tmp_path, fake).call(packet())
    assert response.intent.candidate_index == 0
    assert response.usage.cached_input_tokens == 10
    assert response.usage.reasoning_output_tokens == 5
    command, prompt, workspace, timeout = fake.calls[0]
    assert "--sandbox" in command and command[command.index("--sandbox") + 1] == "read-only"
    assert all(("--disable", feature) in tuple(zip(command, command[1:]))
               for feature in DISABLED_FEATURES)
    assert command[-1] == "-"
    assert b'"hands_by_seat"' in prompt
    assert timeout == 90
    assert not workspace.exists()


def test_private_provider_trace_reopens_and_coordinated_rehash_fails(tmp_path):
    fake = FakeRun()
    active = transport(tmp_path, fake)
    decision = packet()
    response = active.call(decision)
    private = active.take_private_evidence(decision, response)
    assert validate_private_evidence(
        private, packet=decision, response=response) == private
    with pytest.raises(CodexTurnTransportError,
                       match="private evidence absent"):
        active.take_private_evidence(decision, response)

    forged = copy.deepcopy(private)
    forged["response"]["returncode"] = 1
    body = {key: value for key, value in forged.items()
            if key != "evidence_sha256"}
    forged["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(CodexTurnTransportError,
                       match="response derivation drift"):
        validate_private_evidence(forged, packet=decision, response=response)


def test_canary_phase_schema_forces_nonempty_rollout_then_empty_play(tmp_path):
    first = packet()
    from shengji.rl.privileged_teacher_luna_rpc_transport import intent_output_schema
    rollout = intent_output_schema(first, allowed_kinds=("rollout",))
    assert rollout["properties"]["kind"]["enum"] == ["rollout"]
    assert rollout["properties"]["candidate_indices"]["minItems"] == 1
    play = intent_output_schema(first, allowed_kinds=("play",))
    assert play["properties"]["kind"]["enum"] == ["play"]
    assert play["properties"]["candidate_indices"]["maxItems"] == 0


@pytest.mark.parametrize("mutation,match", [
    ("stale", "intent refused"),
    ("tool", "tool event"),
    ("usage", "token telemetry"),
    ("final-mismatch", "binding"),
])
def test_stale_tool_usage_and_final_binding_fail(mutation, match, tmp_path):
    with pytest.raises(CodexTurnTransportError, match=match):
        transport(tmp_path, FakeRun(mutate=mutation)).call(packet())


def test_any_stderr_fails_closed(tmp_path):
    with pytest.raises(CodexTurnTransportError, match="stderr"):
        transport(tmp_path, FakeRun(stderr=b"warning\n")).call(packet())


def test_tool_refusal_retains_exact_trace_usage_and_rejects_rehash(tmp_path):
    decision = packet()
    active = transport(tmp_path, FakeRun(mutate="tool"))
    with pytest.raises(CodexTurnTransportError, match="tool event"):
        active.call(decision)
    private = active.take_private_refusal_evidence(decision)
    assert private is not None
    assert private["usage"]["total_tokens"] == 120
    assert private["tool_event_count"] == 1
    assert validate_private_refusal_evidence(
        private, packet=decision) == private

    forged = copy.deepcopy(private)
    trace_rows = [json.loads(line) for line in base64.b64decode(
        forged["trace_base64"]).splitlines()]
    trace_rows[-1]["usage"]["input_tokens"] += 1
    forged_trace = b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in trace_rows)
    forged["trace_base64"] = base64.b64encode(
        forged_trace).decode("ascii")
    forged["trace_sha256"] = hashlib.sha256(forged_trace).hexdigest()
    body = {key: value for key, value in forged.items()
            if key != "evidence_sha256"}
    forged["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(CodexTurnTransportError,
                       match="refusal derivation drift"):
        validate_private_refusal_evidence(forged, packet=decision)


def test_runtime_attestation_requires_every_tool_feature_off(tmp_path):
    binary = tmp_path / "codex"
    rows = "\n".join(
        f"{feature} stable false" for feature in DISABLED_FEATURES)
    binary.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = \"--version\" ]; then echo '{PINNED_CODEX_VERSION}'; "
        "else cat <<'EOF'\n" + rows + "\nEOF\nfi\n",
        encoding="utf-8")
    binary.chmod(0o700)
    receipt = attest_codex_runtime(binary)
    assert receipt["disabled_features"] == list(DISABLED_FEATURES)
    assert len(receipt["feature_catalog_sha256"]) == 64

    binary.write_text(
        binary.read_text().replace("unified_exec stable false",
                                   "unified_exec stable true"),
        encoding="utf-8")
    with pytest.raises(CodexTurnTransportError, match="catalog is not empty"):
        attest_codex_runtime(binary)
