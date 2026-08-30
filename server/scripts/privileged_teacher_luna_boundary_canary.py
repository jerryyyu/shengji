#!/usr/bin/env python3
"""Run one score-free PT-Luna process-boundary first-observe canary."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_controller as controller
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
SCHEMA = "privileged-teacher-luna-boundary-canary-v1"
_SHA_KEYS = ("prompt_sha256", "stdout_sha256", "final_sha256",
             "command_sha256", "hook_source_sha256",
             "hook_command_sha256", "hook_config_sha256",
             "canary_source_sha256", "execution_source_sha256",
             "codex_launcher_sha256")
_PRIVACY = {"outcomes": False, "actions": False, "trajectories": False,
            "model_prose": False}
def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
def _strict(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} malformed") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ValueError(f"{label} not canonical")
    return value
def _publish(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("canary output occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o400)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
class _ObserveOnlyMailbox:
    """Ephemeral mailbox; no request, observation, or token leaves this thread."""
    def __init__(self, path: Path):
        if path.exists() or path.is_symlink():
            raise ValueError("canary mailbox occupied")
        path.mkdir(mode=0o700)
        self.path = path
        self.token = secrets.token_hex(32)
        self.first_op: str | None = None
        self.counts: dict[str, int] = {}
        self.refused = False
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
    def _response(self, path: Path, value: dict[str, object]) -> None:
        raw = canonical_json_bytes(value)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o400)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                for request_path in sorted(self.path.glob("request-*.json")):
                    suffix = request_path.name.removeprefix("request-").removesuffix(".json")
                    if len(suffix) != 64 or any(c not in "0123456789abcdef" for c in suffix):
                        continue
                    response_path = self.path / f"response-{suffix}.json"
                    if response_path.exists():
                        continue
                    try:
                        request = _strict(request_path.read_bytes(), "canary request")
                    except Exception:
                        self.refused = True
                        response = {"status": "error", "error": "canary request refused"}
                    else:
                        if request != {"op": "observe"}:
                            self.refused = True
                            response = {"status": "error", "error": "observe-only canary refusal"}
                        else:
                            self.first_op = self.first_op or "observe"
                            self.counts["observe"] = self.counts.get("observe", 0) + 1
                            if self.counts["observe"] > 4:
                                self.refused = True
                                response = {"status": "error",
                                            "error": "canary operation limit"}
                            else:
                                response = {"schema": luna.GAME_SCHEMA,
                                            "status": "round_end",
                                            "completion_token": self.token}
                    self._response(response_path, response)
                self._stop.wait(0.002)
        except BaseException as exc:  # surfaced only as a generic refusal
            self.error = exc
    def __enter__(self) -> "_ObserveOnlyMailbox":
        self._thread.start()
        return self
    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive() or self.error is not None:
            raise ValueError("canary mailbox failed")
def _validate_runtime(runtime: object) -> None:
    if type(runtime) is not dict:
        raise ValueError("canary runtime identity drift")
    required = {"python_executable", "python_version", "python_sha256",
                "codex_binary", "codex_binary_sha256", "codex_version",
                "platform", "tool_script", "tool_script_sha256"}
    if set(runtime) != required:
        raise ValueError("canary runtime identity drift")
    for key in ("python_executable", "python_version", "codex_binary",
                "platform", "tool_script"):
        if type(runtime[key]) is not str or not runtime[key]:
            raise ValueError("canary runtime identity drift")
    for key in ("python_sha256", "codex_binary_sha256", "tool_script_sha256"):
        if (type(runtime[key]) is not str or len(runtime[key]) != 64
                or any(c not in "0123456789abcdef" for c in runtime[key])):
            raise ValueError("canary runtime identity drift")
    if runtime["codex_version"] is not None and type(runtime["codex_version"]) is not str:
        raise ValueError("canary runtime identity drift")
    for path_key, digest_key in (("python_executable", "python_sha256"),
                                 ("codex_binary", "codex_binary_sha256"),
                                 ("tool_script", "tool_script_sha256")):
        path = Path(runtime[path_key])
        if not path.is_file() or _sha(path.read_bytes()) != runtime[digest_key]:
            raise ValueError("canary runtime identity drift")
def reopen_receipt(path: Path) -> dict[str, object]:
    """Reopen and semantically validate a canary receipt."""
    raw = execution._read_regular(Path(path), mode=0o400, limit=1 << 20)
    payload = _strict(raw, "canary receipt")
    receipt_sha = payload.pop("receipt_sha256", None)
    if type(receipt_sha) is not str or receipt_sha != _sha(canonical_json_bytes(payload)):
        raise ValueError("canary receipt self-hash drift")
    expected = {"schema", "runtime_identity", "actual_subprocess",
                "returncode", "first_op",
                "op_counts", "codex_usage", "codex_event_type_counts",
                "prompt_sha256", "stdout_sha256", "final_sha256",
                "command_sha256", "hook_source_sha256",
                "hook_command_sha256", "hook_config_sha256",
                "canary_source_sha256", "execution_source_sha256",
                "codex_launcher", "codex_launcher_sha256", "opened",
                "retained", "authority"}
    if set(payload) != expected or payload["schema"] != SCHEMA:
        raise ValueError("canary receipt schema drift")
    _validate_runtime(payload["runtime_identity"])
    if (payload["actual_subprocess"] is not True
            or payload["returncode"] != 0
            or payload["first_op"] != "observe"):
        raise ValueError("canary receipt process drift")
    if (type(payload["op_counts"]) is not dict
            or set(payload["op_counts"]) != {"observe"}
            or type(payload["op_counts"].get("observe")) is not int \
            or not 1 <= payload["op_counts"]["observe"] <= 4):
        raise ValueError("canary receipt operation drift")
    if payload["opened"] != _PRIVACY or payload["retained"] != _PRIVACY:
        raise ValueError("canary receipt privacy drift")
    if payload["authority"] != luna.AUTHORITY:
        raise ValueError("canary receipt authority drift")
    for key in _SHA_KEYS:
        value = payload[key]
        if (type(value) is not str or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("canary receipt hash drift")
    if (payload["hook_source_sha256"] != execution.STOP_HOOK_SOURCE_SHA256
            or payload["canary_source_sha256"] != _sha(Path(__file__).read_bytes())
            or payload["execution_source_sha256"]
            != _sha(Path(execution.__file__).read_bytes())):
        raise ValueError("canary receipt source drift")
    launcher = Path(payload["codex_launcher"])
    if (type(payload["codex_launcher"]) is not str or not launcher.is_file()
            or _sha(launcher.read_bytes()) != payload["codex_launcher_sha256"]):
        raise ValueError("canary receipt launcher drift")
    usage = payload["codex_usage"]
    if (type(usage) is not dict or set(usage) != execution.CODEX_USAGE_KEYS
            or any(type(v) is not int or isinstance(v, bool) or v < 0
                   for v in usage.values())):
        raise ValueError("canary receipt usage drift")
    if type(payload["codex_event_type_counts"]) is not dict:
        raise ValueError("canary receipt event counts drift")
    return {**payload, "receipt_sha256": receipt_sha}
def run(*, codex_binary: Path, output: Path, deadline_seconds: int) -> dict[str, object]:
    if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int)
            or not 1 <= deadline_seconds <= 180):
        raise ValueError("deadline-seconds must be between 1 and 180")
    binary = Path(codex_binary).absolute()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Codex binary absent or not executable")
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError("canary output occupied")
    tool_script = Path(__file__).with_name("privileged_teacher_luna_selfplay_tool.py")
    runtime = execution.runtime_identity(codex_binary=binary, tool_script=tool_script)
    with tempfile.TemporaryDirectory(prefix="pt-luna-canary-", dir="/tmp") as temporary:
        workspace = Path(temporary)
        os.chmod(workspace, 0o700)
        mailbox_path = workspace / "mailbox"
        final_path = workspace / "final.json"
        prompt = execution.planner_prompt(mailbox_path=mailbox_path,
                                          tool_script=tool_script)
        command = execution.process_command(codex_binary=binary, workspace=workspace,
                                            mailbox_path=mailbox_path,
                                            final_output_path=final_path)
        hook = execution._stop_hook_binding(mailbox_path=mailbox_path)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("SHENGJI_FAST", None)
        environment["SHENGJI_REQUIRE_VOIDS"] = "1"
        with _ObserveOnlyMailbox(mailbox_path) as mailbox:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=workspace, env=environment,
                start_new_session=(os.name == "posix"))
            try:
                stdout, _ = process.communicate(
                    input=prompt.encode("utf-8"), timeout=deadline_seconds)
            except subprocess.TimeoutExpired as exc:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                process.communicate()
                raise ValueError("canary subprocess deadline exceeded") from exc
        if (mailbox.error is not None or mailbox.refused
                or mailbox.first_op != "observe" or not mailbox.counts
                or set(mailbox.counts) != {"observe"}):
            raise ValueError("canary mailbox contract refused")
        stdout = bytes(stdout or b"")
        usage = execution._codex_jsonl_usage(stdout)
        if (process.returncode != 0 or not final_path.is_file()
                or final_path.is_symlink()):
            raise ValueError("canary subprocess did not complete")
        final_raw = execution._read_process_file(final_path, limit=1 << 20)
        expected_final = canonical_json_bytes({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": mailbox.token})
        # Codex's last-message file is the assistant message itself and may
        # omit the canonical artifact newline.  Accept only those two byte
        # forms of the same exact terminal JSON.
        if final_raw not in (expected_final, expected_final.removesuffix(b"\n")):
            raise ValueError("canary final response drift")
        body = {"schema": SCHEMA, "runtime_identity": runtime,
                "actual_subprocess": True,
                "returncode": process.returncode, "first_op": mailbox.first_op,
                "op_counts": dict(sorted(mailbox.counts.items())),
                "codex_usage": usage,
                "codex_event_type_counts": controller._capacity_codex_events(stdout),
                "prompt_sha256": _sha(prompt.encode("utf-8")),
                "stdout_sha256": _sha(stdout), "final_sha256": _sha(final_raw),
                "command_sha256": _sha(canonical_json_bytes(list(command))),
                "hook_source_sha256": hook["script_sha256"],
                "hook_command_sha256": hook["command_sha256"],
                "hook_config_sha256": hook["config_sha256"],
                "canary_source_sha256": _sha(Path(__file__).read_bytes()),
                "execution_source_sha256": _sha(
                    Path(execution.__file__).read_bytes()),
                "codex_launcher": str(binary),
                "codex_launcher_sha256": _sha(binary.read_bytes()),
                "opened": dict(_PRIVACY), "retained": dict(_PRIVACY),
                "authority": dict(luna.AUTHORITY)}
    body["receipt_sha256"] = _sha(canonical_json_bytes(body))
    raw = canonical_json_bytes(body)
    _publish(Path(output), raw)
    return body
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        run(codex_binary=args.codex_binary, output=args.output,
            deadline_seconds=args.deadline_seconds)
    except Exception:
        print("refused: PT-Luna canary boundary validation failed", file=sys.stderr)
        return 2
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
