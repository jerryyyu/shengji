from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time

import pytest

from scripts import privileged_teacher_luna_boundary_canary as canary
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


@pytest.fixture(autouse=True)
def _disable_host_sandbox_for_script_fixture(monkeypatch):
    """Use a test-only Linux identity for the external script fixture.

    The production canary still requires sandbox enforcement on Darwin; this
    fixture substitutes only the unavailable host profile execution.
    """
    original = shutil.which
    monkeypatch.setattr(canary.sys, "platform", "linux")
    monkeypatch.setattr(canary.execution.shutil, "which",
                        lambda name: None if name == "sandbox-exec"
                        else original(name))
    production_run = canary.run

    def synthetic_run(**kwargs):
        # Unit fixtures explicitly select the short-delay path; receipts mark
        # it non-production and therefore cannot stand in for the real yield.
        if kwargs.get("terminal_wait_delay_seconds") is None:
            kwargs["terminal_wait_delay_seconds"] = 0
        return production_run(**kwargs)

    monkeypatch.setattr(canary, "run", synthetic_run)
    monkeypatch.setattr(canary, "_production_run_for_test", production_run,
                        raising=False)


FAKE = '''#!/usr/bin/env python3
import json, os, re, shlex, subprocess, sys, time
from pathlib import Path
prompt = sys.stdin.read()
assert "exec" in sys.argv and "--ephemeral" in sys.argv and "--json" in sys.argv
assert os.environ.get("PYTHONPATH") is None
assert os.environ.get("SHENGJI_FAST") is None
assert os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1"
tool_prefix = re.search(r"available commands are \\(each is passed as `cmd` to that wrapper\\):\\n\\s+(.+?) observe", prompt).group(1)
tool_argv = shlex.split(tool_prefix)
mailbox = Path(re.search(r"--mailbox\\s+(\\S+)", prompt).group(1))
final = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
mode = os.environ.get("CANARY_FAKE_MODE", "ok")
commands = []
if mode == "timeout": time.sleep(5)
def read_response(path):
    for _ in range(5000):
        if path.is_file():
            try:
                return json.loads(path.read_bytes())
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        time.sleep(.001)
    return None
def call(request, suffix):
    path = mailbox / ("request-" + suffix * 64 + ".json")
    raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.chmod(0o600)
    os.replace(temporary, path)
    response = mailbox / ("response-" + suffix * 64 + ".json")
    value = read_response(response)
    if value is None: sys.exit(3)
    args = []
    if request["op"] == "rollout":
        args = ["--decision", request["decision_sha256"], "--candidates",
                ",".join(str(item) for item in request["candidate_indices"]),
                "--continuations", ",".join(request["continuations"])]
    elif request["op"] == "play":
        args = ["--decision", request["decision_sha256"], "--candidate",
                str(request["candidate_index"]), "--confidence",
                request["confidence"]]
    command = shlex.join(("/bin/zsh", "-lc",
                          shlex.join(tool_argv + [request["op"]] + args)))
    commands.append((command, value))
    return value
first = call({"op": "play"} if mode == "play" else {"op": "observe"}, "a")
if mode == "play" or first.get("status") != "decision": sys.exit(3)
hook_command = None
hook_index = 0
def run_hook(active, last):
    global hook_index
    hook_index += 1
    suffix = format(hook_index, "x")
    request_path = mailbox / ("request-" + suffix * (64 // len(suffix))
                              + suffix[:64 % len(suffix)] + ".json")
    temporary = request_path.with_suffix(".tmp")
    temporary.write_bytes(b'{"hook_stop":true,"op":"observe"}\\n')
    temporary.chmod(0o600)
    os.replace(temporary, request_path)
    response_path = mailbox / ("response-" + request_path.stem.removeprefix(
        "request-") + ".json")
    response = read_response(response_path)
    if response is None:
        return subprocess.CompletedProcess(("hook",), 3, b"", b"")
    if response.get("hook_action") == "terminal":
        output = b""
    elif response.get("hook_action") == "block":
        output = b'{"decision":"block","reason":"Continue"}\\n'
    else:
        output = b""
    return subprocess.CompletedProcess(("hook",), 0, output, b"")
if mode != "no-hook":
    override = next(value for index, value in enumerate(sys.argv)
                    if index and sys.argv[index - 1] == "-c" and value.startswith("hooks.Stop="))
    quoted = re.search(r'command=("(?:\\\\.|[^"\\\\])*")', override).group(1)
    hook_command = json.loads(quoted)
    attempts = 3 if mode == "hook-overflow" else 1
    for _ in range(attempts):
        hook = run_hook(False, "early")
        if (hook.returncode != 0 or hook.stderr
                or json.loads(hook.stdout).get("decision") != "block"): sys.exit(4)
if mode == "early-exit": sys.exit(0)
rollout = call({"op": "rollout", "decision_sha256": first["decision_sha256"],
                "candidate_indices": [0], "continuations": ["smart-all"]}, "b")
if rollout.get("status") != "rollout_complete": sys.exit(3)
played = call({"op": "play", "decision_sha256": first["decision_sha256"],
               "candidate_index": 0, "confidence": "low"}, "c")
if played.get("status") != "waiting": sys.exit(3)
third = call({"op": "wait"}, "d")
if third.get("status") != "round_end": sys.exit(3)
token = third["completion_token"]
payload = {"schema": "privileged-teacher-luna-selfplay-final-response-v2", "status": "complete", "completion_token": token}
if mode == "bad-final": payload["status"] = "wrong"
final_raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
final.write_bytes(final_raw)
if mode != "no-hook":
    hook = run_hook(True, final_raw.decode())
    if hook.returncode != 0 or hook.stdout or hook.stderr: sys.exit(4)
events = [{"type": "thread.started"}]
for index, (command, response) in enumerate(commands):
    item = {"id": "command-" + str(index), "type": "command_execution",
            "command": command}
    events.extend([{"type": "item.started", "item": {
                       **item, "aggregated_output": "", "exit_code": None,
                       "status": "in_progress"}},
                   {"type": "item.completed", "item": {
                       **item, "aggregated_output": json.dumps(
                           response, sort_keys=True, separators=(",", ":")),
                       "exit_code": 0, "status": "completed"}}])
events.append({"type": "turn.completed", "usage": {k: 1 for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")}})
if mode == "bad-usage": events[1]["usage"].pop("reasoning_output_tokens")
if mode == "duplicate-turn": events.append(dict(events[-1]))
sys.stdout.write("\\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\\n")
if mode == "nonzero-after-terminal": sys.exit(9)
'''


def _fake(tmp_path: Path) -> Path:
    path = tmp_path / "codex"
    path.write_text(FAKE)
    path.chmod(0o755)
    return path


def test_shared_mailbox_allows_repeat_observe_and_second_rollout(tmp_path):
    state = canary._CanaryState("a" * 64)
    with canary._CanaryMailbox(tmp_path / "mailbox", state=state) as mailbox:
        first = mailbox._dispatch({"op": "observe"})
        assert mailbox._dispatch({"op": "observe"}) == first
        request = {"op": "rollout", "decision_sha256": state.decision_sha256,
                   "candidate_indices": [0], "continuations": ["smart-all"]}
        assert mailbox._dispatch(request)["status"] == "rollout_complete"
        assert mailbox._dispatch(request)["status"] == "rollout_complete"


def test_canary_mailbox_owns_bounded_stop_hook_counter(tmp_path):
    state = canary._CanaryState("e" * 64)
    request = {"op": "observe",
               canary.execution.STOP_HOOK_REQUEST_FIELD: True}
    with canary._CanaryMailbox(tmp_path / "mailbox", state=state) as mailbox:
        actions = [mailbox._dispatch(request)[
            canary.execution.STOP_HOOK_ACTION_FIELD] for _ in range(3)]
    assert actions == ["block", "block", "exhausted"]


def test_canary_decision_is_production_shaped_and_empty_ballot_mutation_refuses():
    state = canary._CanaryState("b" * 64)
    observed = state.decision_response()
    assert len(observed["hands_by_seat"]) == 4
    assert observed["current_state"]
    assert observed["candidates"] and all(observed["candidates"])
    assert observed["budget"] == {
        "rollout_calls": 0,
        "rollout_calls_limit": canary.luna.sol0.MAX_ROLLOUT_CALLS_PER_DECISION,
        "used": 0, "round_used": 0,
        "decision_limit": canary.luna.sol0.MAX_EVALUATIONS_PER_DECISION,
        "round_limit": canary.luna.sol0.MAX_EVALUATIONS_PER_ROUND,
    }
    seat = observed["acting_seat"]
    assert all(not (canary.Counter(candidate)
                    - canary.Counter(observed["hands_by_seat"][seat]))
               for candidate in observed["candidates"])
    state.observation["candidates"] = [[]]
    with pytest.raises(ValueError, match="production decision fixture drift"):
        state.decision_response()


def test_happy_path_is_real_subprocess_and_private_receipt(tmp_path):
    binary, output = _fake(tmp_path), tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(binary), "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    assert canary.reopen_receipt(output)["receipt_sha256"] == payload["receipt_sha256"]
    assert payload["model_first_op"] == payload["hook_first_op"] == "observe"
    assert payload["actual_subprocess"] is True
    assert payload["schema"] == canary.SYNTHETIC_SCHEMA
    assert payload["production_yield_witness"] is False
    assert payload["code_mode_outer_yield_seconds"] == 60
    assert payload["code_mode_nested_yield_seconds"] == 30
    assert payload["terminal_wait_delay_seconds"] == 0
    assert payload["terminal_wait_delayed"] is False
    assert payload["model_op_sequence"] == list(canary.MODEL_COMMAND_SEQUENCE)
    assert payload["model_op_counts"] == {"observe": 1, "play": 1,
                                            "rollout": 1, "wait": 1}
    assert payload["model_command_count"] == 4
    assert payload["model_command_sequence"] == payload["model_op_sequence"]
    assert payload["hook_op_sequence"] == ["observe", "observe"]
    assert payload["model_nonterminal_observed"] is True
    assert payload["hook_op_counts"] == {"observe": 2}
    assert payload["codex_event_type_counts"]["turn.completed"] == 1
    assert payload["opened"] == payload["retained"] == canary._PRIVACY
    assert all(value is False for value in payload["authority"].values())
    assert "completion_token" not in output.read_text()
    info = output.stat()
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert info.st_nlink == 1
    assert payload["codex_launcher"] == str(binary.absolute())


def test_short_delayed_canary_wait_marks_terminal_lifecycle(tmp_path):
    state = canary._CanaryState(
        "c" * 64,
        terminal_wait_delay_seconds=
        canary.SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS)
    with canary._CanaryMailbox(tmp_path / "mailbox", state=state) as mailbox:
        first = mailbox._dispatch({"op": "observe"})
        rollout = mailbox._dispatch({
            "op": "rollout", "decision_sha256": state.decision_sha256,
            "candidate_indices": [0], "continuations": ["smart-all"]})
        assert rollout["status"] == "rollout_complete"
        played = mailbox._dispatch({
            "op": "play", "decision_sha256": first["decision_sha256"],
            "candidate_index": 0, "confidence": "low"})
        assert played["status"] == "waiting"
        started = time.monotonic()
        terminal = mailbox._dispatch({"op": "wait"})
        elapsed = time.monotonic() - started
    assert terminal["status"] == "round_end"
    assert state.terminal_wait_delayed is True
    assert elapsed >= canary.SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS


def test_delayed_wait_does_not_block_stop_hook_observe(tmp_path):
    state = canary._CanaryState("d" * 64, terminal_wait_delay_seconds=1)
    state.phase = "playing"
    result: dict[str, object] = {}
    with canary._CanaryMailbox(tmp_path / "mailbox", state=state) as mailbox:
        waiter = threading.Thread(
            target=lambda: result.update(canary.execution.tool_request(
                mailbox.path, {"op": "wait"})))
        waiter.start()
        assert state.terminal_wait_started.wait(timeout=1)
        started = time.monotonic()
        hooked = canary.execution.tool_request(
            mailbox.path, {"op": "observe",
                           canary.execution.STOP_HOOK_REQUEST_FIELD: True})
        hook_elapsed = time.monotonic() - started
        waiter.join(timeout=2)
        assert not waiter.is_alive()
    # The old single-threaded server returned only after the one-second wait.
    # Keep this well below that boundary so the test witnesses the wiring.
    assert hook_elapsed < 0.5
    assert hooked["status"] == "waiting"
    assert hooked[canary.execution.STOP_HOOK_ACTION_FIELD] == "block"
    assert result["status"] == "round_end"


def test_fake_clients_retry_visible_incomplete_model_and_hook_responses(
        tmp_path, monkeypatch):
    """The synthetic model must follow the production response-read protocol."""
    def delayed_response(_self, path, value):
        raw = canonical_json_bytes(value)
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o400)
        with os.fdopen(descriptor, "wb") as handle:
            # Publish the path before its canonical bytes. Both the model
            # command and Stop-hook readers must retry through this window.
            time.sleep(0.01)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())

    monkeypatch.setattr(canary._CanaryMailbox, "_response", delayed_response)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = canary.reopen_receipt(output)
    assert payload["model_command_sequence"] \
        == list(canary.MODEL_COMMAND_SEQUENCE)
    assert payload["hook_op_sequence"] == ["observe", "observe"]


def test_production_success_cannot_use_short_wait_delay(tmp_path, monkeypatch):
    # The production path has no delay override; changing its frozen constant
    # must fail before a subprocess can mint a success receipt.
    monkeypatch.setattr(canary, "PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS", 0)
    with pytest.raises(ValueError, match="production code-mode yield"):
        canary._production_run_for_test(
            codex_binary=_fake(tmp_path), output=tmp_path / "receipt.json",
            deadline_seconds=10)
    monkeypatch.setattr(canary, "PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS", 31)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output), "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    payload["schema"] = canary.SCHEMA
    payload["production_yield_witness"] = True
    payload["terminal_wait_delay_seconds"] = 0
    payload["terminal_wait_delayed"] = False
    body = {key: value for key, value in payload.items()
            if key != "receipt_sha256"}
    payload["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    output.chmod(0o600)
    output.write_bytes(canonical_json_bytes(payload))
    output.chmod(0o400)
    with pytest.raises(ValueError, match="(production yield witness|code-mode yield witness)"):
        canary.reopen_receipt(output)


def test_production_receipt_requires_observed_delayed_wait(tmp_path):
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output), "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    payload.update({"schema": canary.SCHEMA,
                    "production_yield_witness": True,
                    "terminal_wait_delay_seconds":
                    canary.PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS,
                    "terminal_wait_delayed": False})
    body = {key: value for key, value in payload.items()
            if key != "receipt_sha256"}
    payload["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    output.chmod(0o600)
    output.write_bytes(canonical_json_bytes(payload))
    output.chmod(0o400)
    with pytest.raises(ValueError, match="yield witness"):
        canary.reopen_receipt(output)


def test_terminal_model_operation_follows_prompt_wait_contract(tmp_path):
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = canary.reopen_receipt(output)
    prompt = canary.execution.planner_prompt(
        mailbox_path=tmp_path / "mailbox", tool_script=tmp_path / "tool")
    assert "If it reports waiting, immediately call\nwait" in prompt
    assert payload["model_command_sequence"][-1] == "wait"
    assert payload["model_command_sequence"] == list(
        canary.MODEL_COMMAND_SEQUENCE)


def _assert_private_failure(output: Path) -> dict[str, object]:
    payload = canary.reopen_failure_receipt(output)
    assert payload["opened"] == payload["retained"] == canary._PRIVACY
    assert all(value is False for value in payload["authority"].values())
    assert set(payload["accepted_op_counts"]) <= canary._DIAGNOSTIC_OPS
    assert payload["terminal_phase"] in canary._DIAGNOSTIC_PHASES
    return payload


def _model_observe_witness(tmp_path: Path) -> tuple[bytes, list[dict[str, object]]]:
    """Build command-only JSONL without any model-authored text."""
    mailbox = tmp_path / "mailbox"
    tool = tmp_path / "tool.py"
    command = shlex.join(("/bin/zsh", "-lc", shlex.join((
        str(Path(sys.executable).absolute()), "-P", "-B", str(tool.resolve()),
        "--mailbox", str(mailbox), "observe"))))
    response = {"status": "decision"}
    output = canonical_json_bytes(response).decode("ascii").removesuffix("\n")
    item = {"id": "command", "type": "command_execution",
            "command": command, "aggregated_output": output,
            "exit_code": 0, "status": "completed"}
    started = {"type": "item.started", "item": {
        **item, "aggregated_output": "", "exit_code": None,
        "status": "in_progress"}}
    completed = {"type": "item.completed", "item": item}
    raw = (json.dumps(started, separators=(",", ":")) + "\n"
           + json.dumps(completed, separators=(",", ":")) + "\n").encode()
    trace = [{"request": {"op": "observe"}, "response": response,
              "response_sha256": canary._sha(canonical_json_bytes(response))}]
    return raw, trace


def test_clean_hook_observe_and_turn_completed_attribution(tmp_path):
    result = canary._derive_attribution(
        raw=b'{"type":"turn.completed"}\n', mailbox_path=tmp_path / "mailbox",
        trace=[{"request": {"op": "observe",
                            canary.execution.STOP_HOOK_REQUEST_FIELD: True}}],
        python_path=Path(sys.executable), tool_script_path=tmp_path / "tool.py")
    assert result == ("turn-completed", [], ["observe"])


def test_model_observe_only_is_nullable_stop_compatible(tmp_path):
    raw, trace = _model_observe_witness(tmp_path)
    assert canary._derive_attribution(
        raw=raw, mailbox_path=tmp_path / "mailbox", trace=trace,
        python_path=Path(sys.executable), tool_script_path=tmp_path / "tool.py") \
        == ("absent-or-opaque", ["observe"], [])


def test_model_observe_turn_failed_is_classified_without_error_text(tmp_path):
    raw, trace = _model_observe_witness(tmp_path)
    raw += b'{"type":"turn.failed"}\n'
    assert canary._derive_attribution(
        raw=raw, mailbox_path=tmp_path / "mailbox", trace=trace,
        python_path=Path(sys.executable), tool_script_path=tmp_path / "tool.py") \
        == ("turn-failed", ["observe"], [])


def test_model_and_residual_hook_observes_are_attributed_separately(tmp_path):
    raw, trace = _model_observe_witness(tmp_path)
    trace.append({"request": {
        "op": "observe", canary.execution.STOP_HOOK_REQUEST_FIELD: True}})
    assert canary._derive_attribution(
        raw=raw, mailbox_path=tmp_path / "mailbox", trace=trace,
        python_path=Path(sys.executable), tool_script_path=tmp_path / "tool.py") \
        == ("absent-or-opaque", ["observe"], ["observe"])


def test_first_op_play_refuses_with_private_failure_receipt(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "play")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = _assert_private_failure(output)
    assert payload["reason"] == "request-contract-refused"
    assert payload["accepted_op_sequence"] == []
    assert payload["terminal_phase"] == "decision"


def test_early_model_exit_is_distinct_from_invalid_request(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "early-exit")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = _assert_private_failure(output)
    assert payload["reason"] == "terminal-not-reached"
    assert payload["accepted_op_sequence"] == ["observe", "observe"]
    assert payload["terminal_phase"] == "decision"
    assert payload["process_return_class"] == "zero"
    assert payload["terminal_event_class"] == "absent-or-opaque"
    assert payload["model_mailbox_op_sequence"] == []
    assert payload["hook_observe_sequence"] == ["observe", "observe"]


def test_nonzero_after_terminal_retains_process_and_command_attribution(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "nonzero-after-terminal")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = _assert_private_failure(output)
    assert payload["reason"] == "subprocess-completion-refused"
    assert payload["process_return_class"] == "nonzero"
    assert payload["terminal_event_class"] == "turn-completed"
    assert payload["model_mailbox_op_sequence"] \
        == list(canary.MODEL_COMMAND_SEQUENCE)
    assert payload["hook_observe_sequence"] == ["observe", "observe"]


def test_timeout_retains_killed_process_class_without_private_output(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "timeout")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "1"]) == 2
    payload = _assert_private_failure(output)
    assert payload["reason"] == "subprocess-deadline-exceeded"
    assert payload["process_return_class"] == "nonzero"
    assert payload["terminal_event_class"] == "absent-or-opaque"
    assert payload["model_mailbox_op_sequence"] == []
    assert payload["hook_observe_sequence"] == []


def test_mailbox_server_failure_has_own_privacy_safe_reason(
        tmp_path, monkeypatch):
    def fail_response(_self, _path, _value):
        raise OSError("private path detail")

    monkeypatch.setattr(canary._CanaryMailbox, "_response", fail_response)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = _assert_private_failure(output)
    assert payload["reason"] == "mailbox-server-error"
    assert payload["accepted_op_sequence"] == ["observe"]
    assert payload["terminal_phase"] == "decision"
    assert "private path detail" not in output.read_text()


def test_missing_stop_hook_observation_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "no-hook")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    _assert_private_failure(output)


def test_operation_mismatch_publishes_exact_private_failure_reason(
        tmp_path, monkeypatch):
    def refuse(**_kwargs):
        raise ValueError("canary model operation contract refused")
    monkeypatch.setattr(canary, "run", refuse)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert _assert_private_failure(output)["reason"] \
        == "model-operation-contract-refused"


def test_failure_reason_allowlist_refuses_coordinated_rehash(
        tmp_path, monkeypatch):
    def refuse(**_kwargs):
        raise ValueError("canary model operation contract refused")
    monkeypatch.setattr(canary, "run", refuse)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)),
                        "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = json.loads(output.read_bytes())
    payload["reason"] = "unallowlisted-reason"
    body = {key: value for key, value in payload.items()
            if key != "receipt_sha256"}
    payload["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    output.chmod(0o600)
    output.write_bytes(canonical_json_bytes(payload))
    output.chmod(0o400)
    with pytest.raises(ValueError, match="schema drift"):
        canary.reopen_failure_receipt(output)


@pytest.mark.parametrize(
    "mode", ("bad-final", "bad-usage", "duplicate-turn", "hook-overflow"))
def test_malformed_final_or_telemetry_refuses(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("CANARY_FAKE_MODE", mode)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    _assert_private_failure(output)


def test_occupied_output_refuses_before_launch(tmp_path):
    output = tmp_path / "receipt.json"
    output.write_bytes(b"occupied")
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert output.read_bytes() == b"occupied"


def test_tampered_and_coordinated_receipts_refuse(tmp_path):
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    payload["model_first_op"] = "play"
    body = {k: v for k, v in payload.items() if k != "receipt_sha256"}
    payload["receipt_sha256"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    output.chmod(0o600)
    output.write_bytes(canonical_json_bytes(payload))
    output.chmod(0o400)
    with pytest.raises(ValueError, match="operation drift"):
        canary.reopen_receipt(output)


def test_temporary_workspace_is_removed(tmp_path, monkeypatch):
    binary, output = _fake(tmp_path), tmp_path / "receipt.json"
    paths = []
    original = canary.tempfile.TemporaryDirectory
    def capture(*args, **kwargs):
        instance = original(*args, **kwargs)
        paths.append(Path(instance.name))
        return instance
    monkeypatch.setattr(canary.tempfile, "TemporaryDirectory", capture)
    assert canary.main(["--codex-binary", str(binary), "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    assert paths and not paths[0].exists()
