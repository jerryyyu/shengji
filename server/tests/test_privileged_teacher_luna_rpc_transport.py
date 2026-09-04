"""Can-fail tests for the zero-tool Codex turn transport."""

from __future__ import annotations

import copy
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as selfplay
from shengji.rl import privileged_teacher_luna_rpc_transport as transport_module
from shengji.rl.privileged_teacher_luna_rpc_transport import (
    CODE_MODE_DISABLED_DIAGNOSTIC,
    CodexExecPlannerTransport,
    CodexProviderResourceError,
    CodexTurnTransportError,
    DISABLED_FEATURES,
    InvocationResult,
    PINNED_CODEX_VERSION,
    attest_codex_runtime,
    classify_refusal_redispatch_eligibility,
    validate_private_evidence,
    validate_private_refusal_evidence,
)
from shengji.rl.privileged_teacher_luna_turn_rpc import (
    DecisionPacket,
    PhaseContext,
    TeamMemory,
)
from shengji.rl.privileged_teacher_luna_canonical import canonical_json_bytes


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


def test_clean_contained_run_does_not_signal_a_reaped_process_group(
        tmp_path, monkeypatch):
    def refuse_post_wait_signal(_process_group, _signal):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(transport_module.os, "killpg",
                        refuse_post_wait_signal)
    exact = transport_module._default_run(
        (sys.executable, "-c", "pass"), b"", tmp_path, 5)
    assert exact.returncode == 0
    failed = transport_module._default_run(
        (sys.executable, "-c", "raise SystemExit(7)"), b"", tmp_path, 5)
    assert failed.returncode == 7


def test_cancellation_owns_process_group_cleanup_once(tmp_path, monkeypatch):
    manager = transport_module.ActiveCallManager()
    original_killpg = os.killpg
    calls = []
    lock = threading.Lock()
    def one_signal(process_group, sent_signal):
        with lock:
            calls.append((process_group, sent_signal))
            ordinal = len(calls)
        if ordinal > 1:
            raise PermissionError(1, "Operation not permitted")
        original_killpg(process_group, sent_signal)
    monkeypatch.setattr(transport_module.os, "killpg", one_signal)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            transport_module._default_run,
            (sys.executable, "-c", "import time; time.sleep(60)"),
            b"", tmp_path, 60, _active_call_manager=manager)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with manager._lock:
                if manager._calls:
                    break
            time.sleep(0.01)
        else:
            raise AssertionError("contained process was not registered")
        manager.terminate()
        result = future.result(timeout=5)
    assert result.returncode != 0
    assert len(calls) == 1


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
    final = {"schema": "pt-luna-provider-intent-v2",
             "decision_sha256": "a" * 64,
             "action": {"kind": "play", "candidate_index": 0,
                        "confidence": "low", "planning_note": "bounded"}}
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
    def __init__(self, *, mutate=None, stderr=b"", sleep_seconds=0,
                 returncode=0, write_final=True):
        self.mutate = mutate
        self.stderr = stderr
        self.sleep_seconds = sleep_seconds
        self.returncode = returncode
        self.write_final = write_final
        self.calls = []

    def __call__(self, command, prompt, workspace, timeout):
        self.calls.append((command, prompt, workspace, timeout))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        decision = packet_sha_from_prompt(prompt)
        final = {"schema": "pt-luna-provider-intent-v2",
                 "decision_sha256": decision,
                 "action": {"kind": "play", "candidate_index": 0,
                            "confidence": "low",
                            "planning_note": "bounded"}}
        final_path = Path(command[command.index("--output-last-message") + 1])
        if self.write_final:
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
        return InvocationResult(self.returncode,
                                trace(final, item_type=item_type, usage=usage),
                                self.stderr, 7)


def packet_sha_from_prompt(prompt: bytes) -> str:
    marker = b'"decision_sha256":"'
    start = prompt.index(marker) + len(marker)
    return prompt[start:start + 64].decode("ascii")


class CompletionDriftRun(FakeRun):
    def __call__(self, command, prompt, workspace, timeout):
        result = super().__call__(command, prompt, workspace, timeout)
        return InvocationResult(
            result.returncode,
            result.stdout.splitlines()[0] + b"\n",
            result.stderr, result.wall_ms)


def sealed_disposition(kind, message, *, stage="provider-response",
                       game_deadline_fired=False, call_timeout_fired=False):
    return {
        "stage": stage, "kind": kind,
        "game_deadline_fired": game_deadline_fired,
        "call_timeout_fired": call_timeout_fired,
        "exception_type": ("CodexProviderResourceError"
                            if kind == "provider-process"
                            else "CodexTurnTransportError"),
        "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
    }


def transport(tmp_path, fake, *, deadline_provider=None, timeout_seconds=90,
              policy_mode="free"):
    return CodexExecPlannerTransport(
        codex_binary="/usr/bin/true", temp_root=tmp_path,
        timeout_seconds=timeout_seconds, run_command=fake,
        runtime_attestor=lambda _: {
            "schema": "pt-luna-codex-tool-catalog-v1"},
        deadline_provider=deadline_provider, policy_mode=policy_mode)


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


def test_dynamic_game_deadline_reaches_run_seam(tmp_path):
    fake = FakeRun()
    active = transport(
        tmp_path, fake,
        deadline_provider=lambda: time.monotonic_ns() + 5_000_000_000,
        timeout_seconds=3)
    active.call(packet())
    assert len(fake.calls) == 1
    assert isinstance(fake.calls[0][3], int)
    assert 0 <= fake.calls[0][3] <= 3


def test_expired_game_deadline_refuses_before_run(tmp_path):
    fake = FakeRun()
    active = transport(
        tmp_path, fake,
        deadline_provider=lambda: time.monotonic_ns() - 1)
    with pytest.raises(CodexProviderResourceError, match="before dispatch"):
        active.call(packet())
    assert fake.calls == []


def test_late_contained_return_is_refused_before_response(tmp_path):
    fake = FakeRun(sleep_seconds=0.03)
    active = transport(
        tmp_path, fake,
        deadline_provider=lambda: time.monotonic_ns() + 10_000_000)
    with pytest.raises(CodexProviderResourceError, match="after dispatch"):
        active.call(packet())
    assert len(fake.calls) == 1


def test_private_provider_trace_reopens_and_coordinated_rehash_fails(tmp_path):
    fake = FakeRun()
    active = transport(tmp_path, fake)
    decision = packet()
    response = active.call(decision)
    private = active.take_private_evidence(decision, response)
    assert validate_private_evidence(
        private, packet=decision, response=response) == private
    legacy = copy.deepcopy(private)
    legacy["schema"] = transport_module.LEGACY_PRIVATE_EVIDENCE_SCHEMA
    legacy_body = {key: value for key, value in legacy.items()
                   if key != "evidence_sha256"}
    legacy["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(legacy_body)).hexdigest()
    assert validate_private_evidence(
        legacy, packet=decision, response=response) == legacy
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


def test_nested_phase_schema_structurally_separates_rollout_and_play(tmp_path):
    first = packet()
    from shengji.rl.privileged_teacher_luna_rpc_transport import intent_output_schema
    free = intent_output_schema(first)
    variants = free["properties"]["action"]["anyOf"]
    assert [row["properties"]["kind"]["const"] for row in variants] \
        == ["play", "rollout"]
    assert "candidate_indices" not in variants[0]["properties"]
    assert variants[1]["properties"]["candidate_indices"]["minItems"] == 1
    rollout = intent_output_schema(first, allowed_kinds=("rollout",))
    rollout_action = rollout["properties"]["action"]
    assert rollout_action["properties"]["kind"]["const"] == "rollout"
    assert rollout_action["properties"]["candidate_indices"]["minItems"] == 1
    play = intent_output_schema(first, allowed_kinds=("play",))
    play_action = play["properties"]["action"]
    assert play_action["properties"]["kind"]["const"] == "play"
    assert "candidate_indices" not in play_action["properties"]


def test_play_only_binds_nested_schema_prompt_and_private_request(tmp_path):
    decision = packet()
    fake = FakeRun()
    active = transport(tmp_path, fake, policy_mode="play-only")
    response = active.call(decision)
    private = active.take_private_evidence(decision, response)
    action_schema = private["output_schema"]["properties"]["action"]
    assert action_schema["properties"]["kind"]["const"] == "play"
    assert "candidate_indices" not in action_schema["properties"]
    assert private["request"]["policy_mode"] == "play-only"
    assert b"request one bounded rollout" not in fake.calls[0][1]
    assert b"If requesting rollouts" not in fake.calls[0][1]


def test_play_only_rejects_rollout_through_nested_parser(tmp_path):
    decision = packet()
    rollout = {"schema": "pt-luna-provider-intent-v2",
               "decision_sha256": decision.decision_sha256,
               "action": {"kind": "rollout", "candidate_indices": [0],
                           "continuations": ["smart-all"],
                           "planning_note": "look"}}

    class RolloutRun(FakeRun):
        def __call__(self, command, prompt, workspace, timeout):
            result = super().__call__(command, prompt, workspace, timeout)
            final_path = Path(command[command.index("--output-last-message") + 1])
            final_path.write_text(json.dumps(rollout), encoding="utf-8")
            return InvocationResult(
                result.returncode,
                trace(rollout), result.stderr, result.wall_ms)

    with pytest.raises(CodexTurnTransportError, match="policy kind drift"):
        transport(tmp_path, RolloutRun(), policy_mode="play-only").call(decision)


def test_refusal_redispatch_classifier_exact_positive_cases(tmp_path):
    decision = packet()
    drift_transport = transport(
        tmp_path, CompletionDriftRun(), policy_mode="play-only")
    with pytest.raises(CodexTurnTransportError, match="completion telemetry"):
        drift_transport.call(decision)
    drift_private = drift_transport.take_private_refusal_evidence(decision)
    assert drift_private is not None
    assert drift_private["usage"] is None
    assert drift_private["tool_event_count"] == 0
    assert classify_refusal_redispatch_eligibility(
        sealed_disposition("provider-schema", "Codex completion telemetry drift"),
        validate_private_refusal_evidence(drift_private, packet=decision)) \
        == "completion-telemetry-drift"


@pytest.mark.parametrize("kind,message,private_changes", [
    ("provider-process", "Codex turn process failed", {"returncode": 3}),
    ("provider-process", "Codex turn process failed", {"final_base64": None}),
    ("provider-process", "Codex turn process failed", {"tool_event_count": None}),
    ("provider-process", "Codex turn process failed", {"tool_event_count": 1}),
    ("provider-schema", "Codex completion telemetry drift", {}),
])
def test_refusal_redispatch_classifier_forbidden_cases(
        tmp_path, kind, message, private_changes):
    decision = packet()
    active = transport(tmp_path, FakeRun(returncode=3),
                       policy_mode="play-only")
    with pytest.raises(CodexTurnTransportError):
        active.call(decision)
    private = active.take_private_refusal_evidence(decision)
    assert private is not None
    private = {**private, **private_changes}
    if kind == "provider-schema":
        disposition = sealed_disposition(
            kind, message, game_deadline_fired=True)
    else:
        disposition = sealed_disposition(kind, message)
    assert classify_refusal_redispatch_eligibility(disposition, private) is None


def test_nonzero_unparseable_result_preserves_exact_private_bytes(tmp_path):
    final_bytes = b"not-json\x00final"
    stderr_bytes = b"provider-warning\xff"

    class OpaqueRun(FakeRun):
        def __call__(self, command, prompt, workspace, timeout):
            final_path = Path(command[command.index("--output-last-message") + 1])
            final_path.write_bytes(final_bytes)
            return InvocationResult(9, b"", stderr_bytes, 11)

    decision = packet()
    active = transport(tmp_path, OpaqueRun(), policy_mode="play-only")
    with pytest.raises(CodexProviderResourceError, match="process failed"):
        active.call(decision)
    private = active.take_private_refusal_evidence(decision)
    assert private is not None
    assert base64.b64decode(private["trace_base64"]) == b""
    assert base64.b64decode(private["stderr_base64"]) == stderr_bytes
    assert base64.b64decode(private["final_base64"]) == final_bytes
    assert private["trace_sha256"] == hashlib.sha256(b"").hexdigest()
    assert private["stderr_sha256"] == hashlib.sha256(stderr_bytes).hexdigest()
    assert private["final_sha256"] == hashlib.sha256(final_bytes).hexdigest()
    assert private["usage"] is None
    assert private["tool_event_count"] is None
    assert validate_private_refusal_evidence(
        private, packet=decision) == private


def test_nested_intent_parser_enforces_variant_phase_and_forced_kind():
    first = packet()
    play = {"schema": "pt-luna-provider-intent-v2",
            "decision_sha256": first.decision_sha256,
            "action": {"kind": "play", "candidate_index": 0,
                       "confidence": "medium", "planning_note": "play"}}
    with pytest.raises(CodexTurnTransportError, match="policy kind drift"):
        transport_module._provider_intent(
            play, first, allowed_kinds=("rollout",))

    rollout = {"schema": "pt-luna-provider-intent-v2",
               "decision_sha256": first.decision_sha256,
               "action": {"kind": "rollout", "candidate_indices": [],
                          "continuations": ["smart-all"],
                          "planning_note": "look"}}
    with pytest.raises(CodexTurnTransportError, match="rollout list empty"):
        transport_module._provider_intent(rollout, first)
    rollout["action"]["candidate_index"] = 0
    with pytest.raises(CodexTurnTransportError, match="rollout shape drift"):
        transport_module._provider_intent(rollout, first)

    rollout["action"].pop("candidate_index")
    rollout["action"]["candidate_indices"] = [0]
    third = replace(first, phase=PhaseContext(3), rollouts=({}, {}))
    with pytest.raises(CodexTurnTransportError, match="policy kind drift"):
        transport_module._provider_intent(rollout, third)


@pytest.mark.parametrize("mutation,match", [
    ("stale", "intent refused"),
    ("tool", "tool event"),
    ("usage", "token telemetry"),
    ("final-mismatch", "binding"),
])
def test_stale_tool_usage_and_final_binding_fail(mutation, match, tmp_path):
    with pytest.raises(CodexTurnTransportError, match=match):
        transport(tmp_path, FakeRun(mutate=mutation)).call(packet())


def test_diagnostic_stderr_is_sealed_but_does_not_override_valid_response(
        tmp_path):
    decision = packet()
    diagnostic = (
        b"ERROR codex_models_manager: failed to refresh available models: "
        b"timeout waiting for child process to exit\n")
    active = transport(tmp_path, FakeRun(stderr=diagnostic),
                       policy_mode="play-only")
    response = active.call(decision)
    private = active.take_private_evidence(decision, response)
    assert base64.b64decode(private["stderr_base64"]) == diagnostic
    assert private["response"]["stderr_sha256"] == hashlib.sha256(
        diagnostic).hexdigest()
    assert validate_private_evidence(
        private, packet=decision, response=response) == private
    legacy = copy.deepcopy(private)
    legacy["schema"] = transport_module.LEGACY_PRIVATE_EVIDENCE_SCHEMA
    legacy_body = {key: value for key, value in legacy.items()
                   if key != "evidence_sha256"}
    legacy["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(legacy_body)).hexdigest()
    with pytest.raises(CodexTurnTransportError,
                       match="legacy private stderr"):
        validate_private_evidence(
            legacy, packet=decision, response=response)


def test_oversized_stderr_refuses_before_acceptance(tmp_path):
    active = transport(
        tmp_path,
        FakeRun(stderr=b"x" * (transport_module.MAX_STDERR_BYTES + 1)),
        policy_mode="play-only")
    with pytest.raises(CodexProviderResourceError,
                       match="stderr size drift"):
        active.call(packet())


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
