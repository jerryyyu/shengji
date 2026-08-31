from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

import pytest

from scripts import privileged_teacher_luna_boundary_canary as canary
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


FAKE = '''#!/usr/bin/env python3
import json, os, re, shlex, subprocess, sys, time
from pathlib import Path
prompt = sys.stdin.read()
assert "exec" in sys.argv and "--ephemeral" in sys.argv and "--json" in sys.argv
assert os.environ.get("PYTHONPATH") is None
assert os.environ.get("SHENGJI_FAST") is None
assert os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1"
mailbox = Path(re.search(r"--mailbox\\s+(\\S+)", prompt).group(1))
final = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
mode = os.environ.get("CANARY_FAKE_MODE", "ok")
def call(request, suffix):
    path = mailbox / ("request-" + suffix * 64 + ".json")
    path.write_bytes(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\\n")
    path.chmod(0o600)
    response = mailbox / ("response-" + suffix * 64 + ".json")
    for _ in range(5000):
        if response.is_file(): break
        time.sleep(.001)
    if not response.is_file(): sys.exit(3)
    return json.loads(response.read_bytes())
first = call({"op": "play"} if mode == "play" else {"op": "observe"}, "a")
if mode == "play" or first.get("status") != "waiting": sys.exit(3)
hook_command = None
def run_hook(active, last):
    stop = {"hook_event_name": "Stop", "model": "gpt-5.6-luna",
            "turn_id": "fake", "cwd": str(Path.cwd()),
            "stop_hook_active": active, "last_assistant_message": last}
    return subprocess.run(shlex.split(hook_command), input=json.dumps(
        stop, sort_keys=True, separators=(",", ":")).encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env=os.environ.copy())
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
second = call({"op": "wait"}, "b")
if second.get("status") != "waiting": sys.exit(3)
third = call({"op": "wait"}, "c")
if third.get("status") != "round_end": sys.exit(3)
token = third["completion_token"]
payload = {"schema": "privileged-teacher-luna-selfplay-final-response-v2", "status": "complete", "completion_token": token}
if mode == "bad-final": payload["status"] = "wrong"
final_raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
final.write_bytes(final_raw)
if mode != "no-hook":
    hook = run_hook(True, final_raw.decode())
    if hook.returncode != 0 or hook.stdout or hook.stderr: sys.exit(4)
events = [{"type": "thread.started"}, {"type": "turn.completed", "usage": {k: 1 for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")}}]
if mode == "bad-usage": events[1]["usage"].pop("reasoning_output_tokens")
if mode == "duplicate-turn": events.append(dict(events[1]))
sys.stdout.write("\\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\\n")
'''


def _fake(tmp_path: Path) -> Path:
    path = tmp_path / "codex"
    path.write_text(FAKE)
    path.chmod(0o755)
    return path


def test_happy_path_is_real_subprocess_and_private_receipt(tmp_path):
    binary, output = _fake(tmp_path), tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(binary), "--output", str(output),
                        "--deadline-seconds", "10"]) == 0
    payload = json.loads(output.read_bytes())
    assert canary.reopen_receipt(output)["receipt_sha256"] == payload["receipt_sha256"]
    assert payload["model_first_op"] == payload["hook_first_op"] == "observe"
    assert payload["actual_subprocess"] is True
    assert payload["model_op_sequence"] == ["observe", "wait", "wait"]
    assert payload["model_op_counts"] == {"observe": 1, "wait": 2}
    assert payload["model_nonterminal_observed"] is True
    assert payload["hook_op_counts"] == {"observe": 1}
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
