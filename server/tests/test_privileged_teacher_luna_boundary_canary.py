from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys

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


FAKE = '''#!/usr/bin/env python3
import json, os, re, shlex, subprocess, sys, time
from pathlib import Path
prompt = sys.stdin.read()
assert "exec" in sys.argv and "--ephemeral" in sys.argv and "--json" in sys.argv
assert os.environ.get("PYTHONPATH") is None
assert os.environ.get("SHENGJI_FAST") is None
assert os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1"
tool_prefix = re.search(r"Use only this tool:\\n\\s+(.+?) observe", prompt).group(1)
tool_argv = shlex.split(tool_prefix)
mailbox = Path(re.search(r"--mailbox\\s+(\\S+)", prompt).group(1))
final = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
mode = os.environ.get("CANARY_FAKE_MODE", "ok")
commands = []
def call(request, suffix):
    path = mailbox / ("request-" + suffix * 64 + ".json")
    path.write_bytes(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\\n")
    path.chmod(0o600)
    response = mailbox / ("response-" + suffix * 64 + ".json")
    for _ in range(5000):
        if response.is_file(): break
        time.sleep(.001)
    if not response.is_file(): sys.exit(3)
    value = json.loads(response.read_bytes())
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
    request_path.write_bytes(b'{"op":"observe"}\\n')
    request_path.chmod(0o600)
    response_path = mailbox / ("response-" + request_path.stem.removeprefix(
        "request-") + ".json")
    for _ in range(5000):
        if response_path.is_file(): break
        time.sleep(.001)
    if not response_path.is_file():
        return subprocess.CompletedProcess(("hook",), 3, b"", b"")
    response = json.loads(response_path.read_bytes())
    if response.get("status") == "round_end":
        output = b""
    else:
        output = b'{"decision":"block","reason":"Continue"}\\n'
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
rollout = call({"op": "rollout", "decision_sha256": first["decision_sha256"],
                "candidate_indices": [0], "continuations": ["smart-all"]}, "b")
if rollout.get("status") != "rollout_complete": sys.exit(3)
played = call({"op": "play", "decision_sha256": first["decision_sha256"],
               "candidate_index": 0, "confidence": "low"}, "c")
if played.get("status") != "waiting": sys.exit(3)
third = call({"op": "observe"}, "d")
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


def test_happy_path_is_real_subprocess_and_private_receipt(tmp_path):
    binary, output = _fake(tmp_path), tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(binary), "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    assert canary.reopen_receipt(output)["receipt_sha256"] == payload["receipt_sha256"]
    assert payload["model_first_op"] == payload["hook_first_op"] == "observe"
    assert payload["actual_subprocess"] is True
    assert payload["model_op_sequence"] == ["observe", "rollout", "play", "observe"]
    assert payload["model_op_counts"] == {"observe": 2, "play": 1,
                                            "rollout": 1}
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


def test_first_op_play_refuses_and_publishes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "play")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert not output.exists()


def test_missing_stop_hook_observation_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "no-hook")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "mode", ("bad-final", "bad-usage", "duplicate-turn", "hook-overflow"))
def test_malformed_final_or_telemetry_refuses(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("CANARY_FAKE_MODE", mode)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert not output.exists()


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
