from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest

from scripts import privileged_teacher_luna_boundary_canary as canary
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


FAKE = '''#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
prompt = sys.stdin.read()
assert "exec" in sys.argv and "--ephemeral" in sys.argv and "--json" in sys.argv
assert "--dangerously-bypass-hook-trust" not in sys.argv
assert not any(value.startswith("hooks.Stop=") for value in sys.argv)
assert os.environ.get("PYTHONPATH") is None
assert os.environ.get("SHENGJI_FAST") is None
assert os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1"
mailbox = Path(re.search(r"--mailbox\\s+(\\S+)", prompt).group(1))
final = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
mode = os.environ.get("CANARY_FAKE_MODE", "ok")
events = [{"type": "thread.started"}, {"type": "turn.completed", "usage": {k: 1 for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")}}]
if mode == "bad-usage": events[1]["usage"].pop("reasoning_output_tokens")
if mode == "no-observe":
    payload = {"schema": "privileged-teacher-luna-selfplay-final-response-v2", "status": "complete", "completion_token": "0" * 64}
    final.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    sys.stdout.write("\\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\\n")
    sys.exit(0)
request = {"op": "play"} if mode == "play" else {"op": "observe"}
path = mailbox / ("request-" + "a" * 64 + ".json")
path.write_bytes(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\\n")
path.chmod(0o600)
response = mailbox / ("response-" + "a" * 64 + ".json")
for _ in range(5000):
    if response.is_file(): break
    time.sleep(.001)
if mode == "play" or not response.is_file(): sys.exit(3)
token = json.loads(response.read_bytes())["completion_token"]
payload = {"schema": "privileged-teacher-luna-selfplay-final-response-v2", "status": "complete", "completion_token": token}
if mode == "bad-final": payload["status"] = "wrong"
final_raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
final.write_bytes(final_raw)
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
    assert payload["transport"] == "plain-no-hook"
    assert payload["model_first_op"] == "observe"
    assert payload["actual_subprocess"] is True
    assert payload["model_op_counts"] == {"observe": 1}
    assert not any(key.startswith("hook_") for key in payload)
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


def test_missing_model_observation_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "no-observe")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert not output.exists()


@pytest.mark.parametrize("mode", ("bad-final", "bad-usage"))
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
