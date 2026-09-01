from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from scripts import privileged_teacher_luna_boundary_canary as canary
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


DIAGNOSTIC = b"private provider diagnostic: never retain\n"


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
if mode == "timeout": time.sleep(5)
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
if mode == "prompt-order-wrong-token": payload["completion_token"] = "f" * 64
final_raw = json.dumps(
    payload, sort_keys=(mode not in ("prompt-order-final", "prompt-order-wrong-token")),
    separators=(",", ":"), ensure_ascii=True).encode()
if mode != "absent-final": final.write_bytes(final_raw)
sys.stdout.write("\\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\\n")
sys.stderr.write("private provider diagnostic: never retain\\n")
if mode == "nonzero": sys.exit(9)
'''


def _fake(tmp_path: Path) -> Path:
    path = tmp_path / "codex"
    path.write_text(FAKE)
    path.chmod(0o755)
    return path


def test_mailbox_response_name_appears_only_after_complete_bytes(
        tmp_path, monkeypatch):
    mailbox = canary._ObserveOnlyMailbox(
        tmp_path / "mailbox", token="0" * 64)
    response = mailbox.path / f"response-{'a' * 64}.json"
    value = {"schema": "witness", "status": "complete"}
    expected = canonical_json_bytes(value)
    original_link = os.link
    link_observations = []

    def witness(source, destination, **kwargs):
        link_observations.append(
            (Path(source).read_bytes(), Path(destination).exists()))
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(canary.os, "link", witness)
    mailbox._response(response, value)

    assert link_observations == [(expected, False)]
    assert response.read_bytes() == expected
    assert not tuple(mailbox.path.glob("*.partial"))


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
    assert payload["stderr_sha256"] == hashlib.sha256(DIAGNOSTIC).hexdigest()
    assert payload["stderr_byte_count"] == len(DIAGNOSTIC)
    assert "private provider diagnostic" not in output.read_text()


def test_prompt_order_final_is_semantically_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "prompt-order-final")
    output = tmp_path / "receipt.json"
    assert canary.main([
        "--codex-binary", str(_fake(tmp_path)), "--output", str(output),
        "--deadline-seconds", "10"]) == 0
    payload = canary.reopen_receipt(output)
    assert payload["model_op_counts"] == {"observe": 1}
    assert payload["final_sha256"] is not None
    assert "completion_token" not in output.read_text()


def test_prompt_order_wrong_token_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "prompt-order-wrong-token")
    output = tmp_path / "receipt.json"
    assert canary.main([
        "--codex-binary", str(_fake(tmp_path)), "--output", str(output),
        "--deadline-seconds", "10"]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == "final-validation"
    assert payload["reason_code"] == "final-response-refused"
    assert payload["mailbox_op_counts"] == {"observe": 1}
    assert payload["final_sha256"] is not None
    assert "completion_token" not in output.read_text()


def test_first_op_play_refuses_with_a_durable_private_receipt(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "play")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == "mailbox"
    assert payload["reason_code"] == "request-contract-refused"
    assert payload["mailbox_op_counts"] == {}
    assert payload["stderr_sha256"] is not None
    assert "private provider diagnostic" not in output.read_text()


def test_missing_model_observation_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "no-observe")
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == "mailbox"
    assert payload["reason_code"] == "request-contract-refused"


@pytest.mark.parametrize("mode", ("bad-final", "bad-usage"))
def test_malformed_final_or_telemetry_refuses(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("CANARY_FAKE_MODE", mode)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == ("usage" if mode == "bad-usage"
                                 else "final-validation")
    assert payload["reason_code"] == ("usage-malformed" if mode == "bad-usage"
                                      else "final-response-refused")
    assert payload["final_present"] is True
    assert payload["final_sha256"] is not None
    assert payload["stderr_sha256"] == hashlib.sha256(DIAGNOSTIC).hexdigest()
    assert payload["stderr_byte_count"] == len(DIAGNOSTIC)
    assert "private provider diagnostic" not in output.read_text()


def test_occupied_output_refuses_before_launch(tmp_path):
    output = tmp_path / "receipt.json"
    output.write_bytes(b"occupied")
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    assert output.read_bytes() == b"occupied"


@pytest.mark.parametrize("mode,stage,reason", (
    ("absent-final", "final-validation", "final-response-refused"),
    ("nonzero", "transport", "subprocess-completion-refused"),
    ("timeout", "transport", "subprocess-deadline-exceeded"),
))
def test_typed_process_failures_are_durable_and_privacy_safe(
        tmp_path, monkeypatch, mode, stage, reason):
    monkeypatch.setenv("CANARY_FAKE_MODE", mode)
    output = tmp_path / "receipt.json"
    deadline = "1" if mode == "timeout" else "10"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", deadline]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == stage
    assert payload["reason_code"] == reason
    assert payload["elapsed_wall_seconds"] >= 0
    assert payload["final_present"] is (mode == "nonzero")
    assert payload["mailbox_op_counts"] == ({} if mode == "timeout"
                                             else {"observe": 1})
    assert payload["opened"] == payload["retained"] == canary._PRIVACY
    assert all(value is False for value in payload["authority"].values())
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    assert payload["receipt_sha256"] == hashlib.sha256(
        canonical_json_bytes({k: v for k, v in payload.items()
                              if k != "receipt_sha256"})).hexdigest()


def test_mailbox_server_failure_is_typed_without_exception_text(
        tmp_path, monkeypatch):
    def fail_response(_self, _path, _value):
        raise OSError("private mailbox path")
    monkeypatch.setattr(canary._ObserveOnlyMailbox, "_response", fail_response)
    output = tmp_path / "receipt.json"
    assert canary.main(["--codex-binary", str(_fake(tmp_path)), "--output", str(output),
                        "--deadline-seconds", "10"]) == 2
    payload = canary.reopen_failure_receipt(output)
    assert payload["stage"] == "mailbox"
    assert payload["reason_code"] == "mailbox-server-error"
    assert "private mailbox path" not in output.read_text()


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


def test_failure_receipt_is_sealed_before_temporary_cleanup(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_FAKE_MODE", "bad-usage")
    output = tmp_path / "receipt.json"
    original = canary.tempfile.TemporaryDirectory
    cleanup_observations = []

    class Witness:
        def __init__(self, *args, **kwargs):
            self.inner = original(*args, **kwargs)

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, *args):
            cleanup_observations.append(
                (output.is_file(), stat.S_IMODE(output.stat().st_mode)))
            return self.inner.__exit__(*args)

    monkeypatch.setattr(canary.tempfile, "TemporaryDirectory", Witness)
    assert canary.main([
        "--codex-binary", str(_fake(tmp_path)), "--output", str(output),
        "--deadline-seconds", "10"]) == 2
    assert cleanup_observations == [(True, 0o400)]
    assert canary.reopen_failure_receipt(output)["reason_code"] == (
        "usage-malformed")
