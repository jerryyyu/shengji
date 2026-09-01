"""Can-fail witnesses for the PT-Luna structural Stop hook."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


HOOK = Path(__file__).parents[1] / "scripts" / "privileged_teacher_luna_stop_hook.py"


def _run_hook(tmp_path: Path, observed: dict[str, object] | None,
              last: str | None, *, stop_hook_active: bool = False,
              expect_observe: bool = True) -> tuple[int, bytes]:
    mailbox = tmp_path / "mailbox"
    mailbox.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mailbox.mkdir(mode=0o700, exist_ok=True)
    requests = 0
    request_payload: object = None
    done = threading.Event()

    def answer() -> None:
        nonlocal requests, request_payload
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not done.is_set():
            for request in mailbox.glob("request-*.json"):
                response = mailbox / request.name.replace("request-", "response-", 1)
                if response.exists():
                    continue
                request_payload = json.loads(request.read_bytes())
                if request_payload != {
                        "op": "observe",
                        execution.STOP_HOOK_REQUEST_FIELD: True}:
                    raise AssertionError("Stop hook must observe exactly")
                requests += 1
                value = dict(observed or {
                    "schema": luna.GAME_SCHEMA, "status": "decision"})
                if value.get("status") == "round_end":
                    action = "terminal"
                else:
                    ordinal = len(tuple(mailbox.glob("request-*.json")))
                    action = ("block" if ordinal
                              <= execution.MAX_STOP_HOOK_NONTERMINAL_BLOCKS
                              else "exhausted")
                value[execution.STOP_HOOK_ACTION_FIELD] = action
                response.write_bytes(canonical_json_bytes(value))
                response.chmod(0o400)
                done.set()
                return
            time.sleep(0.001)

    thread = threading.Thread(target=answer)
    if expect_observe:
        thread.start()
    stop = {"hook_event_name": "Stop", "model": luna.MODEL,
            "turn_id": "test", "cwd": str(tmp_path),
            "stop_hook_active": stop_hook_active,
            "last_assistant_message": last}
    config = execution.stop_hook_config(mailbox_path=mailbox,
                                        python=Path(sys.executable))
    command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
    argv = tuple(shlex.split(command))
    assert argv[0] == str(Path(sys.executable).absolute())
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("SHENGJI_FAST", None)
    process = subprocess.run(
        argv, cwd=tmp_path,
        input=canonical_json_bytes(stop), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, check=False, timeout=10)
    done.set()
    if expect_observe:
        thread.join(timeout=5)
    assert process.stderr == b""
    assert request_payload == ({
        "op": "observe", execution.STOP_HOOK_REQUEST_FIELD: True}
        if expect_observe else None)
    return requests, process.stdout


def test_early_prose_is_blocked_without_private_content(tmp_path):
    requests, raw = _run_hook(tmp_path, {"schema": luna.GAME_SCHEMA,
                                         "status": "decision",
                                         "hidden_observation": "secret"}, "done")
    payload = json.loads(raw)
    assert requests == 1
    assert payload["decision"] == "block"
    assert "model-visible exec" in payload["reason"]
    assert "tools.exec_command" in payload["reason"]
    assert "secret" not in raw.decode()
    assert "completion_token" not in raw.decode()


def test_round_end_wrong_token_gets_exact_private_correction(tmp_path):
    token = "a" * 64
    observed = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                "completion_token": token}
    wrong = json.dumps({"schema": execution.FINAL_RESPONSE_SCHEMA,
                        "status": "complete", "completion_token": "c" * 64},
                       sort_keys=True, separators=(",", ":"))
    requests, raw = _run_hook(tmp_path, observed, wrong)
    payload = json.loads(raw)
    assert requests == 1
    assert payload["decision"] == "block"
    assert token in payload["reason"]
    assert execution.FINAL_RESPONSE_SCHEMA in payload["reason"]


def test_nonterminal_stop_has_one_bounded_reentrant_continuation(tmp_path):
    observed = {"schema": luna.GAME_SCHEMA, "status": "decision"}
    requests, raw = _run_hook(tmp_path, observed, "early prose")
    assert requests == 1
    payload = json.loads(raw)
    assert payload["decision"] == "block"
    assert len(payload["reason"]) < 200

    requests, raw = _run_hook(
        tmp_path, observed, "early prose", stop_hook_active=True)
    assert requests == 1
    assert json.loads(raw)["decision"] == "block"

    # A third nonterminal Stop is nonblocking so the outer terminal-witness
    # gate refuses promptly instead of spending the full game wall in a loop.
    requests, raw = _run_hook(
        tmp_path, observed, "early prose", stop_hook_active=True)
    assert requests == 1
    assert raw == b""


def test_nullable_stop_message_is_accepted_but_nonterminal_still_blocks(tmp_path):
    requests, raw = _run_hook(
        tmp_path, {"schema": luna.GAME_SCHEMA, "status": "decision"}, None)
    assert requests == 1
    payload = json.loads(raw)
    assert payload["decision"] == "block"


def test_nullable_terminal_stop_message_gets_exact_private_correction(tmp_path):
    token = "d" * 64
    requests, raw = _run_hook(
        tmp_path, {"schema": luna.GAME_SCHEMA, "status": "round_end",
                   "completion_token": token}, None)
    assert requests == 1
    payload = json.loads(raw)
    assert payload["decision"] == "block"
    assert token in payload["reason"]
    assert execution.FINAL_RESPONSE_SCHEMA in payload["reason"]


def test_exact_terminal_response_is_allowed_even_after_prior_continuation(tmp_path):
    token = "b" * 64
    terminal = json.dumps({"schema": execution.FINAL_RESPONSE_SCHEMA,
                           "status": "complete", "completion_token": token},
                          sort_keys=True, separators=(",", ":"))
    requests, raw = _run_hook(
        tmp_path,
        {"schema": luna.GAME_SCHEMA, "status": "round_end",
         "completion_token": token}, terminal, stop_hook_active=True,
        expect_observe=True)
    assert requests == 1
    assert raw == b""


def test_malformed_stop_input_fails_closed_without_mailbox_observe(tmp_path):
    mailbox = tmp_path / "mailbox"
    mailbox.mkdir(mode=0o700)
    process = subprocess.run(
        (sys.executable, "-P", "-B", str(HOOK), "--mailbox", str(mailbox)),
        input=b"not-json", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={key: value for key, value in os.environ.items()
             if key != "PYTHONPATH"},
        check=False, timeout=10)
    assert process.returncode == 0
    assert json.loads(process.stdout)["decision"] == "block"
    assert not tuple(mailbox.iterdir())


def test_project_import_failure_fails_closed_without_traceback(tmp_path):
    """A missing project import still produces the bounded Stop response."""
    mailbox = tmp_path / "mailbox"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("SHENGJI_FAST", None)
    process = subprocess.run(
        (sys.executable, "-S", "-P", "-B", str(HOOK), "--mailbox",
         str(mailbox)),
        cwd=tmp_path, input=b"not-json", stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=environment, check=False, timeout=10)
    assert process.returncode == 0
    assert process.stderr == b""
    payload = json.loads(process.stdout)
    assert set(payload) == {"decision", "reason"}
    assert payload["decision"] == "block"
    assert len(payload["reason"]) < 200
