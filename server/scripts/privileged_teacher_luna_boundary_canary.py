#!/usr/bin/env python3
"""Run one score-free PT-Luna process-boundary first-observe canary."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_controller as controller
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
SCHEMA = "privileged-teacher-luna-boundary-canary-v2"
FAILURE_SCHEMA = "privileged-teacher-luna-boundary-canary-failure-v1"
_FAILURE_STAGES = frozenset(("admission", "runtime", "transport", "mailbox",
                             "usage", "final-validation"))
_FAILURE_REASONS = frozenset((
    "invalid-deadline", "binary-invalid", "runtime-identity-refused",
    "transport-launch-refused", "subprocess-deadline-exceeded",
    "subprocess-completion-refused", "subprocess-output-too-large",
    "mailbox-server-error",
    "request-contract-refused", "usage-malformed", "final-response-refused",
    "boundary-validation-refused"))
_SHA_KEYS = ("prompt_sha256", "stdout_sha256", "stderr_sha256", "final_sha256",
             "command_sha256",
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


def _optional_sha(path: Path) -> str | None:
    try:
        return _sha(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


@dataclass
class _FailureContext:
    """Only bounded, non-content facts that may survive a failed canary."""

    started: float = field(default_factory=time.perf_counter)
    stage: str = "admission"
    runtime_identity: dict[str, object] | None = None
    codex_launcher: str | None = None
    codex_launcher_sha256: str | None = None
    command_sha256: str | None = None
    prompt_sha256: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stderr_byte_count: int | None = None
    final_sha256: str | None = None
    returncode: int | None = None
    final_present: bool = False
    mailbox_op_counts: dict[str, int] = field(default_factory=dict)


class _CanaryFailure(ValueError):
    def __init__(self, context: _FailureContext, stage: str, reason_code: str):
        if stage not in _FAILURE_STAGES or reason_code not in _FAILURE_REASONS:
            raise ValueError("canary failure classification drift")
        super().__init__("PT-Luna canary boundary validation failed")
        self.context = context
        self.stage = stage
        self.reason_code = reason_code


def _fail(context: _FailureContext, stage: str, reason_code: str) -> None:
    context.stage = stage
    raise _CanaryFailure(context, stage, reason_code)


def _failure_receipt(failure: _CanaryFailure) -> dict[str, object]:
    context = failure.context
    body: dict[str, object] = {
        "schema": FAILURE_SCHEMA,
        "status": "failure",
        "transport": "plain-no-hook",
        "stage": failure.stage,
        "reason_code": failure.reason_code,
        "elapsed_wall_seconds": max(0.0, time.perf_counter() - context.started),
        "runtime_identity": context.runtime_identity,
        "returncode": context.returncode,
        "final_present": context.final_present,
        "mailbox_op_counts": dict(sorted(context.mailbox_op_counts.items())),
        "prompt_sha256": context.prompt_sha256,
        "stdout_sha256": context.stdout_sha256,
        "stderr_sha256": context.stderr_sha256,
        "stderr_byte_count": context.stderr_byte_count,
        "final_sha256": context.final_sha256,
        "command_sha256": context.command_sha256,
        "canary_source_sha256": _optional_sha(Path(__file__)),
        "execution_source_sha256": _optional_sha(Path(execution.__file__)),
        "codex_launcher": context.codex_launcher,
        "codex_launcher_sha256": context.codex_launcher_sha256,
        "opened": dict(_PRIVACY),
        "retained": dict(_PRIVACY),
        "authority": dict(luna.AUTHORITY),
    }
    body["receipt_sha256"] = _sha(canonical_json_bytes(body))
    return body


def _valid_optional_sha(value: object) -> bool:
    return (value is None or
            (type(value) is str and len(value) == 64
             and all(char in "0123456789abcdef" for char in value)))


class _ObserveOnlyMailbox:
    """Ephemeral mailbox; no request, observation, or token leaves this thread."""
    def __init__(self, path: Path, *, token: str):
        if path.exists() or path.is_symlink():
            raise ValueError("canary mailbox occupied")
        path.mkdir(mode=0o700)
        self.path = path
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("canary token identity drift")
        self.token = token
        self.first_op: str | None = None
        self.counts: dict[str, int] = {}
        self.refused = False
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
    def _response(self, path: Path, value: dict[str, object]) -> None:
        raw = canonical_json_bytes(value)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.partial")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o400)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # The model must never observe the final response name until every
            # byte is complete. Hard-link publication is atomic and refuses an
            # already occupied response instead of replacing it.
            os.link(temporary, path, follow_symlinks=False)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
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
    if payload.get("schema") == FAILURE_SCHEMA:
        expected_failure = {
            "schema", "status", "transport", "stage", "reason_code",
            "elapsed_wall_seconds", "runtime_identity", "returncode",
            "final_present", "mailbox_op_counts", "prompt_sha256",
            "stdout_sha256", "stderr_sha256", "stderr_byte_count",
            "final_sha256", "command_sha256",
            "canary_source_sha256", "execution_source_sha256",
            "codex_launcher", "codex_launcher_sha256", "opened", "retained",
            "authority",
        }
        if (set(payload) != expected_failure
                or payload["status"] != "failure"
                or payload["transport"] != "plain-no-hook"
                or payload["stage"] not in _FAILURE_STAGES
                or payload["reason_code"] not in _FAILURE_REASONS):
            raise ValueError("canary failure receipt schema drift")
        elapsed = payload["elapsed_wall_seconds"]
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed) or elapsed < 0):
            raise ValueError("canary failure elapsed wall drift")
        runtime_identity = payload["runtime_identity"]
        if runtime_identity is not None:
            _validate_runtime(runtime_identity)
        returncode = payload["returncode"]
        if (returncode is not None
                and (isinstance(returncode, bool) or not isinstance(returncode, int))):
            raise ValueError("canary failure process drift")
        if type(payload["final_present"]) is not bool:
            raise ValueError("canary failure final drift")
        counts = payload["mailbox_op_counts"]
        if (type(counts) is not dict
                or set(counts) - {"observe"}
                or any(type(value) is not int or isinstance(value, bool)
                       or value < 0 for value in counts.values())):
            raise ValueError("canary failure mailbox drift")
        for key in ("prompt_sha256", "stdout_sha256", "stderr_sha256",
                    "final_sha256",
                    "command_sha256", "canary_source_sha256",
                    "execution_source_sha256", "codex_launcher_sha256"):
            if not _valid_optional_sha(payload[key]):
                raise ValueError("canary failure hash drift")
        stderr_byte_count = payload["stderr_byte_count"]
        if (stderr_byte_count is not None
                and (type(stderr_byte_count) is not int
                     or stderr_byte_count < 0)):
            raise ValueError("canary failure process drift")
        if ((payload["stderr_sha256"] is None)
                != (stderr_byte_count is None)):
            raise ValueError("canary failure process drift")
        launcher = payload["codex_launcher"]
        if launcher is not None and type(launcher) is not str:
            raise ValueError("canary failure launcher drift")
        if payload["canary_source_sha256"] != _sha(Path(__file__).read_bytes()):
            raise ValueError("canary failure source drift")
        if (payload["execution_source_sha256"]
                != _sha(Path(execution.__file__).read_bytes())):
            raise ValueError("canary failure source drift")
        if (payload["codex_launcher"] is not None
                and payload["codex_launcher_sha256"] is None):
            raise ValueError("canary failure launcher drift")
        if payload["opened"] != _PRIVACY or payload["retained"] != _PRIVACY:
            raise ValueError("canary failure privacy drift")
        if payload["authority"] != luna.AUTHORITY:
            raise ValueError("canary failure authority drift")
        return {**payload, "receipt_sha256": receipt_sha}
    expected = {"schema", "transport", "runtime_identity", "actual_subprocess",
                "returncode", "model_first_op", "model_op_counts",
                "codex_usage", "codex_event_type_counts",
                "prompt_sha256", "stdout_sha256", "stderr_sha256",
                "stderr_byte_count", "final_sha256",
                "command_sha256",
                "canary_source_sha256", "execution_source_sha256",
                "codex_launcher", "codex_launcher_sha256", "opened",
                "retained", "authority"}
    if (set(payload) != expected or payload["schema"] != SCHEMA
            or payload["transport"] != "plain-no-hook"):
        raise ValueError("canary receipt schema drift")
    _validate_runtime(payload["runtime_identity"])
    if (payload["actual_subprocess"] is not True or payload["returncode"] != 0):
        raise ValueError("canary receipt process drift")
    if (payload["model_first_op"] != "observe"
            or type(payload["model_op_counts"]) is not dict
            or set(payload["model_op_counts"]) != {"observe"}
            or type(payload["model_op_counts"].get("observe")) is not int
            or not 1 <= payload["model_op_counts"]["observe"] <= 4):
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
    if (payload["canary_source_sha256"] != _sha(Path(__file__).read_bytes())
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
    if (type(payload["stderr_byte_count"]) is not int
            or payload["stderr_byte_count"] < 0):
        raise ValueError("canary receipt process drift")
    return {**payload, "receipt_sha256": receipt_sha}


def reopen_failure_receipt(path: Path) -> dict[str, object]:
    """Reopen and validate a content-free failure receipt."""
    payload = reopen_receipt(path)
    if payload.get("schema") != FAILURE_SCHEMA:
        raise ValueError("canary receipt is not a failure receipt")
    return payload


def _unexpected_failure(context: _FailureContext) -> _CanaryFailure:
    reason_by_stage = {
        "runtime": "runtime-identity-refused",
        "transport": "transport-launch-refused",
        "mailbox": "mailbox-server-error",
        "usage": "usage-malformed",
        "final-validation": "final-response-refused",
    }
    return _CanaryFailure(
        context, context.stage,
        reason_by_stage.get(context.stage, "boundary-validation-refused"))


def run(*, codex_binary: Path, output: Path, deadline_seconds: int) -> dict[str, object]:
    context = _FailureContext()
    output_path = Path(output)
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("canary output occupied")
    try:
        if (isinstance(deadline_seconds, bool)
                or not isinstance(deadline_seconds, int)
                or not 1 <= deadline_seconds <= 180):
            _fail(context, "admission", "invalid-deadline")
        binary = Path(codex_binary).absolute()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            _fail(context, "admission", "binary-invalid")
        context.codex_launcher_sha256 = _optional_sha(binary)
        context.codex_launcher = (str(binary)
                                  if context.codex_launcher_sha256 is not None
                                  else None)
        tool_script = Path(__file__).with_name(
            "privileged_teacher_luna_selfplay_tool.py")
        context.stage = "runtime"
        runtime = execution.runtime_identity(codex_binary=binary,
                                             tool_script=tool_script)
        context.runtime_identity = runtime
        _validate_runtime(runtime)
        with tempfile.TemporaryDirectory(
                prefix="pt-luna-canary-", dir="/tmp") as temporary:
            try:
                workspace = Path(temporary)
                os.chmod(workspace, 0o700)
                model_mailbox_path = workspace / "model_mailbox"
                final_path = workspace / "final.json"
                prompt = execution.planner_prompt(
                    mailbox_path=model_mailbox_path, tool_script=tool_script)
                prompt_raw = prompt.encode("utf-8")
                context.prompt_sha256 = _sha(prompt_raw)
                command = execution._plain_process_command(
                    codex_binary=binary, workspace=workspace,
                    final_output_path=final_path)
                context.command_sha256 = _sha(
                    canonical_json_bytes(list(command)))
                environment = dict(os.environ)
                environment.pop("PYTHONPATH", None)
                environment.pop("SHENGJI_FAST", None)
                environment["SHENGJI_REQUIRE_VOIDS"] = "1"
                token = secrets.token_hex(32)
                context.stage = "mailbox"
                with _ObserveOnlyMailbox(
                        model_mailbox_path, token=token) as model_mailbox:
                    try:
                        process = subprocess.Popen(
                            command, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=workspace, env=environment,
                            start_new_session=(os.name == "posix"))
                    except Exception:
                        _fail(context, "transport", "transport-launch-refused")
                    try:
                        stdout, stderr = process.communicate(
                            input=prompt_raw, timeout=deadline_seconds)
                    except subprocess.TimeoutExpired:
                        try:
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except ProcessLookupError:
                            pass
                        stdout, stderr = process.communicate()
                        stdout = bytes(stdout or b"")
                        stderr = bytes(stderr or b"")
                        context.stdout_sha256 = _sha(stdout)
                        context.stderr_sha256 = _sha(stderr)
                        context.stderr_byte_count = len(stderr)
                        context.returncode = process.returncode
                        context.mailbox_op_counts = dict(
                            sorted(model_mailbox.counts.items()))
                        _fail(context, "transport",
                              "subprocess-deadline-exceeded")
                    stdout = bytes(stdout or b"")
                    stderr = bytes(stderr or b"")
                    context.returncode = process.returncode
                    context.mailbox_op_counts = dict(
                        sorted(model_mailbox.counts.items()))
                context.mailbox_op_counts = dict(
                    sorted(model_mailbox.counts.items()))
                context.stdout_sha256 = _sha(stdout)
                context.stderr_sha256 = _sha(stderr)
                context.stderr_byte_count = len(stderr)
                if len(stdout) > 1 << 20 or len(stderr) > 1 << 20:
                    _fail(context, "transport", "subprocess-output-too-large")
                context.final_present = (
                    final_path.is_file() and not final_path.is_symlink())
                final_raw = b""
                if context.final_present:
                    context.stage = "final-validation"
                    final_raw = execution._read_process_file(
                        final_path, limit=1 << 20)
                    context.final_sha256 = _sha(final_raw)
                if (model_mailbox.error is not None or model_mailbox.refused
                        or model_mailbox.first_op != "observe"
                        or not model_mailbox.counts
                        or set(model_mailbox.counts) != {"observe"}):
                    _fail(context, "mailbox", "request-contract-refused")
                if process.returncode != 0:
                    _fail(context, "transport", "subprocess-completion-refused")
                context.stage = "usage"
                try:
                    usage = execution._codex_jsonl_usage(stdout)
                except Exception:
                    _fail(context, "usage", "usage-malformed")
                if not context.final_present:
                    _fail(context, "final-validation",
                          "final-response-refused")
                expected_final = canonical_json_bytes({
                    "schema": execution.FINAL_RESPONSE_SCHEMA,
                    "status": "complete", "completion_token": token})
                # Codex's last-message file is the assistant message itself
                # and may omit the canonical artifact newline. Accept only
                # those two byte forms of the same exact terminal JSON.
                if final_raw not in (
                        expected_final, expected_final.removesuffix(b"\n")):
                    _fail(context, "final-validation",
                          "final-response-refused")
                body = {
                    "schema": SCHEMA, "transport": "plain-no-hook",
                    "runtime_identity": runtime, "actual_subprocess": True,
                    "returncode": process.returncode,
                    "model_first_op": model_mailbox.first_op,
                    "model_op_counts": dict(
                        sorted(model_mailbox.counts.items())),
                    "codex_usage": usage,
                    "codex_event_type_counts":
                        controller._capacity_codex_events(stdout),
                    "prompt_sha256": context.prompt_sha256,
                    "stdout_sha256": context.stdout_sha256,
                    "stderr_sha256": context.stderr_sha256,
                    "stderr_byte_count": context.stderr_byte_count,
                    "final_sha256": context.final_sha256,
                    "command_sha256": context.command_sha256,
                    "canary_source_sha256": _sha(Path(__file__).read_bytes()),
                    "execution_source_sha256": _sha(
                        Path(execution.__file__).read_bytes()),
                    "codex_launcher": str(binary),
                    "codex_launcher_sha256": context.codex_launcher_sha256,
                    "opened": dict(_PRIVACY), "retained": dict(_PRIVACY),
                    "authority": dict(luna.AUTHORITY),
                }
                body["receipt_sha256"] = _sha(canonical_json_bytes(body))
                _publish(output_path, canonical_json_bytes(body))
                return body
            except _CanaryFailure as failure:
                # The immutable receipt is outside the temporary workspace and
                # is sealed before TemporaryDirectory.__exit__ may clean it.
                _publish(
                    output_path,
                    canonical_json_bytes(_failure_receipt(failure)))
                raise
            except Exception:
                failure = _unexpected_failure(context)
                _publish(
                    output_path,
                    canonical_json_bytes(_failure_receipt(failure)))
                raise failure
    except _CanaryFailure:
        raise
    except Exception:
        # The exception text is intentionally discarded. The receipt contains
        # only bounded state from the context and a closed classification.
        raise _unexpected_failure(context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    # An occupied or linked slot is an admission refusal: never launch a
    # planner and never replace the existing bytes with a diagnostic.
    if output.exists() or output.is_symlink():
        print("refused: PT-Luna canary output occupied", file=sys.stderr)
        return 2
    try:
        run(codex_binary=args.codex_binary, output=args.output,
            deadline_seconds=args.deadline_seconds)
    except Exception as exc:
        failure = (exc if isinstance(exc, _CanaryFailure) else _CanaryFailure(
            _FailureContext(), "admission", "boundary-validation-refused"))
        if not output.exists() and not output.is_symlink():
            try:
                _publish(output, canonical_json_bytes(_failure_receipt(failure)))
            except Exception:
                # The O_EXCL publication rule is fail-closed if another writer
                # claimed the slot while this attempt was running.
                pass
        print("refused: PT-Luna canary boundary validation failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
