#!/usr/bin/env python3
"""Run one score-free PT-Luna multi-operation process-boundary canary."""
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
SCHEMA = "privileged-teacher-luna-boundary-canary-v4"
FAILURE_SCHEMA = "privileged-teacher-luna-boundary-canary-failure-v1"
MAX_HOOK_OBSERVES = 2
MODEL_COMMAND_SEQUENCE = ("observe", "rollout", "play", "wait")
CANARY_PROMPT_SUFFIX = """
Boundary-canary instruction: this synthetic decision exists only to prove the
production command/mailbox path. Issue exactly one rollout for candidate 0
with continuation smart-all, then play candidate 0 with low confidence. The
play response is waiting; follow the production instruction by invoking wait,
not observe, and finish only after wait returns round_end.
"""
FAILURE_REASON_BY_MESSAGE = {
    "canary mailbox contract refused": "mailbox-contract-refused",
    "canary command mailbox attribution refused":
        "command-attribution-refused",
    "canary hook attribution refused": "hook-attribution-refused",
    "canary model operation contract refused":
        "model-operation-contract-refused",
    "canary hook operation contract refused":
        "hook-operation-contract-refused",
    "canary subprocess did not complete": "subprocess-completion-refused",
    "canary final response drift": "final-response-refused",
    "canary subprocess deadline exceeded": "subprocess-deadline-exceeded",
    "production peer sandbox unavailable": "sandbox-unavailable",
    "canary output occupied": "namespace-occupied",
}
FAILURE_REASONS = frozenset({
    *FAILURE_REASON_BY_MESSAGE.values(), "boundary-validation-refused"})
_SHA_KEYS = ("prompt_sha256", "stdout_sha256", "final_sha256",
             "command_sha256", "hook_source_sha256",
             "hook_command_sha256", "hook_config_sha256",
             "canary_source_sha256", "execution_source_sha256",
             "codex_launcher_sha256", "sandbox_profile_sha256")
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


def _failure_reason(exc: BaseException) -> str:
    return FAILURE_REASON_BY_MESSAGE.get(
        str(exc), "boundary-validation-refused")


def _failure_receipt(exc: BaseException) -> dict[str, object]:
    body = {
        "schema": FAILURE_SCHEMA,
        "reason": _failure_reason(exc),
        "detail_sha256": _sha(str(exc).encode("utf-8")),
        "canary_source_sha256": _sha(Path(__file__).read_bytes()),
        "execution_source_sha256": _sha(Path(execution.__file__).read_bytes()),
        "opened": dict(_PRIVACY),
        "retained": dict(_PRIVACY),
        "authority": dict(luna.AUTHORITY),
    }
    body["receipt_sha256"] = _sha(canonical_json_bytes(body))
    return body


def reopen_failure_receipt(path: Path) -> dict[str, object]:
    """Reopen the content-free evidence from a refused real canary."""
    raw = execution._read_regular(Path(path), mode=0o400, limit=1 << 20)
    payload = _strict(raw, "canary failure receipt")
    receipt_sha = payload.pop("receipt_sha256", None)
    if type(receipt_sha) is not str \
            or receipt_sha != _sha(canonical_json_bytes(payload)):
        raise ValueError("canary failure receipt self-hash drift")
    if (set(payload) != {"schema", "reason", "detail_sha256",
                         "canary_source_sha256", "execution_source_sha256",
                         "opened", "retained", "authority"}
            or payload["schema"] != FAILURE_SCHEMA
            or payload["reason"] not in FAILURE_REASONS
            or payload["opened"] != _PRIVACY
            or payload["retained"] != _PRIVACY
            or payload["authority"] != luna.AUTHORITY):
        raise ValueError("canary failure receipt schema drift")
    for key in ("detail_sha256", "canary_source_sha256",
                "execution_source_sha256"):
        value = payload[key]
        if (type(value) is not str or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("canary failure receipt hash drift")
    if (payload["canary_source_sha256"] != _sha(Path(__file__).read_bytes())
            or payload["execution_source_sha256"]
            != _sha(Path(execution.__file__).read_bytes())):
        raise ValueError("canary failure receipt source drift")
    return {**payload, "receipt_sha256": receipt_sha}
class _CanaryState:
    """Shared private state for the model and Stop-hook mailbox."""

    def __init__(self, token: str):
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("canary token identity drift")
        self.token = token
        self.phase = "decision"
        self.rollout_calls = 0
        self.terminal = False
        self.decision_sha256 = _sha(token.encode("ascii"))
        self.lock = threading.Lock()


class _CanaryMailbox:
    """Ephemeral mailbox; no request, observation, or token leaves this thread."""

    def __init__(self, path: Path, *, state: _CanaryState):
        if path.exists() or path.is_symlink():
            raise ValueError("canary mailbox occupied")
        path.mkdir(mode=0o700)
        self.path, self.state = path, state
        self.first_op: str | None = None
        self.sequence: list[str] = []
        self.counts: dict[str, int] = {}
        self.trace: list[dict[str, object]] = []
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

    def _dispatch(self, request: dict[str, object]) -> dict[str, object]:
        op = request.get("op")
        if type(op) is not str:
            raise ValueError("canary request shape drift")
        if op in ("observe", "wait") and set(request) != {"op"}:
            raise ValueError("canary request shape drift")
        self.first_op = self.first_op or op
        self.sequence.append(op)
        self.counts[op] = self.counts.get(op, 0) + 1
        with self.state.lock:
            if op == "observe":
                if self.state.phase in ("decision", "rolled"):
                    response = {"schema": luna.GAME_SCHEMA, "status": "decision",
                                "decision_sha256": self.state.decision_sha256,
                                "team": 0, "acting_seat": 0, "banker": 0,
                                "trump_rank": "2", "hands_by_seat": [],
                                "hidden_burial": [], "current_state": {},
                                "candidates": [[]],
                                "candidate_zero_is_production_prior": True,
                                "budget": {"rollout_calls": self.state.rollout_calls,
                                           "rollout_calls_limit": 2, "used": self.state.rollout_calls,
                                           "round_used": self.state.rollout_calls,
                                           "decision_limit": 16, "round_limit": 64}}
                elif self.state.phase == "playing":
                    self.state.terminal = True
                    self.state.phase = "terminal"
                    response = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                                "completion_token": self.state.token}
                else:
                    self.state.terminal = True
                    self.state.phase = "terminal"
                    response = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                                "completion_token": self.state.token}
            elif op == "wait":
                if self.state.phase == "playing":
                    self.state.terminal = True
                    self.state.phase = "terminal"
                    response = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                                "completion_token": self.state.token}
                elif self.state.phase == "terminal":
                    response = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                                "completion_token": self.state.token}
                else:
                    response = {"schema": luna.GAME_SCHEMA, "status": "waiting"}
            elif op == "rollout":
                if (self.state.phase not in ("decision", "rolled")
                        or self.state.rollout_calls >= 2
                        or set(request) != {"op", "decision_sha256",
                                             "candidate_indices", "continuations"}
                        or request.get("decision_sha256") != self.state.decision_sha256
                        or request.get("candidate_indices") != [0]
                        or request.get("continuations") != ["smart-all"]):
                    raise ValueError("canary model rollout drift")
                self.state.rollout_calls += 1
                self.state.phase = "rolled"
                response = {"schema": luna.GAME_SCHEMA, "status": "rollout_complete",
                            "new_evaluations": 1, "cached_evaluations": 0,
                            "results": [{"candidate_index": 0,
                                          "continuation": "smart-all",
                                          "rollout_points": 0,
                                          "team_signed_level_utility": 0}],
                            "budget": {"rollout_calls": self.state.rollout_calls,
                                       "rollout_calls_limit": 2,
                                       "used": self.state.rollout_calls,
                                       "round_used": self.state.rollout_calls,
                                       "decision_limit": 16, "round_limit": 64}}
            elif op == "play":
                if (self.state.phase != "rolled"
                        or set(request) != {"op", "decision_sha256",
                                             "candidate_index", "confidence"}
                        or request.get("decision_sha256") != self.state.decision_sha256
                        or request.get("candidate_index") != 0
                        or request.get("confidence") != "low"):
                    raise ValueError("canary model play drift")
                self.state.phase = "playing"
                response = {"schema": luna.GAME_SCHEMA, "status": "waiting",
                            "acting_team": 1}
            else:
                raise ValueError("canary mailbox operation limit")
            self.trace.append({"request": dict(request), "response": response,
                               "response_sha256": _sha(canonical_json_bytes(response))})
            return response

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
                        response = self._dispatch(request)
                    except Exception:
                        self.refused = True
                        response = {"status": "error", "error": "canary request refused"}
                    self._response(response_path, response)
                self._stop.wait(0.002)
        except BaseException as exc:  # surfaced only as a generic refusal
            self.error = exc
    def __enter__(self) -> "_CanaryMailbox":
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


def _bind_model_commands(records: tuple[dict[str, object], ...],
                         trace: list[dict[str, object]]) -> tuple[list[str], list[str]]:
    """Bind command records monotonically; unmatched observes are hook events."""
    matched: set[int] = set()
    cursor = 0
    model_sequence: list[str] = []
    for record in records:
        found = None
        for index in range(cursor, len(trace)):
            event = trace[index]
            if (type(event) is dict and event.get("request") == record["request"]
                    and event.get("response_sha256") == record["response_sha256"]):
                found = index
                break
        if found is None:
            raise ValueError("canary command mailbox attribution refused")
        matched.add(found)
        cursor = found + 1
        model_sequence.append(str(record["operation"]))
    residual = [event for index, event in enumerate(trace) if index not in matched]
    if (len(residual) > MAX_HOOK_OBSERVES
            or any(type(event) is not dict
                   or event.get("request") != {"op": "observe"}
                   for event in residual)):
        raise ValueError("canary hook attribution refused")
    return model_sequence, ["observe"] * len(residual)
def reopen_receipt(path: Path) -> dict[str, object]:
    """Reopen and semantically validate a canary receipt."""
    raw = execution._read_regular(Path(path), mode=0o400, limit=1 << 20)
    payload = _strict(raw, "canary receipt")
    receipt_sha = payload.pop("receipt_sha256", None)
    if type(receipt_sha) is not str or receipt_sha != _sha(canonical_json_bytes(payload)):
        raise ValueError("canary receipt self-hash drift")
    expected = {"schema", "runtime_identity", "actual_subprocess", "returncode",
                "model_first_op", "model_op_counts", "model_op_sequence",
                "model_nonterminal_observed", "hook_first_op", "hook_op_counts",
                "hook_op_sequence", "model_command_count",
                "model_command_sequence", "sandbox_enforced",
                "codex_usage", "codex_event_type_counts",
                "prompt_sha256", "stdout_sha256", "final_sha256",
                "command_sha256", "hook_source_sha256",
                "hook_command_sha256", "hook_config_sha256",
                "canary_source_sha256", "execution_source_sha256",
                "codex_launcher", "codex_launcher_sha256", "sandbox_profile_sha256",
                "opened",
                "retained", "authority"}
    if set(payload) != expected or payload["schema"] != SCHEMA:
        raise ValueError("canary receipt schema drift")
    _validate_runtime(payload["runtime_identity"])
    if (payload["actual_subprocess"] is not True or payload["returncode"] != 0):
        raise ValueError("canary receipt process drift")
    if (payload["model_first_op"] != "observe"
            or payload["model_op_sequence"] != list(MODEL_COMMAND_SEQUENCE)
            or payload["model_op_counts"] != {"observe": 1, "play": 1,
                                                "rollout": 1, "wait": 1}
            or payload["model_nonterminal_observed"] is not True):
        raise ValueError("canary receipt model operation drift")
    if (payload["model_command_count"] != 4
            or payload["model_command_sequence"]
            != list(MODEL_COMMAND_SEQUENCE)):
        raise ValueError("canary receipt command witness drift")
    hook_counts = payload["hook_op_counts"]
    if (payload["hook_first_op"] != "observe" or type(hook_counts) is not dict
            or set(hook_counts) != {"observe"}
            or type(hook_counts.get("observe")) is not int
            or not 1 <= hook_counts["observe"] <= MAX_HOOK_OBSERVES):
        raise ValueError("canary receipt hook operation drift")
    if (type(payload["hook_op_sequence"]) is not list
            or payload["hook_op_sequence"] != ["observe"] * hook_counts["observe"]):
        raise ValueError("canary receipt hook operation drift")
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
    if (type(payload["sandbox_enforced"]) is not bool
            or (payload["runtime_identity"]["platform"] == "darwin"
                and payload["sandbox_enforced"] is not True)):
        raise ValueError("canary receipt sandbox drift")
    launcher = Path(payload["codex_launcher"])
    if (type(payload["codex_launcher"]) is not str or not launcher.is_file()
            or _sha(launcher.read_bytes()) != payload["codex_launcher_sha256"]):
        raise ValueError("canary receipt launcher drift")
    usage = payload["codex_usage"]
    if (type(usage) is not dict or set(usage) != execution.CODEX_USAGE_KEYS
            or any(type(v) is not int or isinstance(v, bool) or v < 0
                   for v in usage.values())):
        raise ValueError("canary receipt usage drift")
    if (type(payload["codex_event_type_counts"]) is not dict
            or payload["codex_event_type_counts"].get("turn.completed") != 1):
        raise ValueError("canary receipt event counts drift")
    return {**payload, "receipt_sha256": receipt_sha}
def run(*, codex_binary: Path, output: Path, deadline_seconds: int) -> dict[str, object]:
    if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int)
            or not 1 <= deadline_seconds <= 180):
        raise ValueError("deadline-seconds must be between 1 and 180")
    binary = Path(codex_binary).absolute()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Codex binary absent or not executable")
    if sys.platform == "darwin" and execution.shutil.which("sandbox-exec") is None:
        raise ValueError("production peer sandbox unavailable")
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError("canary output occupied")
    tool_script = Path(__file__).with_name("privileged_teacher_luna_selfplay_tool.py")
    runtime = execution.runtime_identity(codex_binary=binary, tool_script=tool_script)
    with tempfile.TemporaryDirectory(prefix="pt-luna-canary-", dir="/tmp") as temporary:
        workspace = Path(temporary)
        os.chmod(workspace, 0o700)
        # Keep one mailbox path for the model tool and the production Stop
        # hook.  A sibling peer path is denied by the same profile shape used
        # by run_luna_game, even though this canary has no peer process.
        mailbox_path = (workspace / "mailbox").resolve()
        peer_workspace = (workspace / "peer").resolve()
        peer_workspace.mkdir(mode=0o700)
        peer_trace = workspace / "peer-trace.json"
        profile_path = workspace / "sandbox.sb"
        profile_raw = execution.sandbox_profile(
            workspace=workspace, peer_workspace=peer_workspace,
            peer_outputs=(peer_trace,))
        _publish(profile_path, profile_raw.encode("utf-8"))
        final_path = workspace / "final.json"
        prompt = execution.planner_prompt(mailbox_path=mailbox_path,
                                          tool_script=tool_script) \
            + CANARY_PROMPT_SUFFIX
        command = execution.process_command(codex_binary=binary, workspace=workspace,
                                            mailbox_path=mailbox_path,
                                            final_output_path=final_path,
                                            peer_workspace=peer_workspace,
                                            peer_outputs=(peer_trace,),
                                            sandbox_profile_path=profile_path)
        hook = execution._stop_hook_binding(mailbox_path=mailbox_path)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("SHENGJI_FAST", None)
        environment["SHENGJI_REQUIRE_VOIDS"] = "1"
        token = secrets.token_hex(32)
        state = _CanaryState(token)
        with _CanaryMailbox(mailbox_path, state=state) as mailbox:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=workspace, env=environment,
                start_new_session=(os.name == "posix"))
            try:
                stdout, stderr = process.communicate(
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
            if len(stderr or b"") > execution.MAX_PROCESS_BYTES:
                raise ValueError("canary stderr limit exceeded")
        if mailbox.error is not None or mailbox.refused or not state.terminal:
            raise ValueError("canary mailbox contract refused")
        stdout = bytes(stdout or b"")
        usage = execution._codex_jsonl_usage(stdout)
        records = execution._codex_command_mailbox_records(
            stdout, mailbox_path=mailbox_path,
            python_path=Path(sys.executable), tool_script_path=tool_script,
            require_shell=True)
        model_sequence, hook_sequence = _bind_model_commands(records, mailbox.trace)
        if model_sequence != list(MODEL_COMMAND_SEQUENCE):
            raise ValueError("canary model operation contract refused")
        if not 1 <= len(hook_sequence) <= MAX_HOOK_OBSERVES:
            raise ValueError("canary hook operation contract refused")
        if (process.returncode != 0 or not final_path.is_file()
                or final_path.is_symlink()):
            raise ValueError("canary subprocess did not complete")
        final_raw = execution._read_process_file(final_path, limit=1 << 20)
        expected_final = canonical_json_bytes({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": token})
        # Codex's last-message file is the assistant message itself and may
        # omit the canonical artifact newline.  Accept only those two byte
        # forms of the same exact terminal JSON.
        if final_raw not in (expected_final, expected_final.removesuffix(b"\n")):
            raise ValueError("canary final response drift")
        body = {"schema": SCHEMA, "runtime_identity": runtime,
                "actual_subprocess": True,
                "returncode": process.returncode,
                "model_first_op": model_sequence[0],
                "model_op_counts": {key: model_sequence.count(key)
                                    for key in sorted(set(model_sequence))},
                "model_op_sequence": list(model_sequence),
                "model_nonterminal_observed": True,
                "hook_first_op": hook_sequence[0],
                "hook_op_counts": {"observe": len(hook_sequence)},
                "hook_op_sequence": list(hook_sequence),
                "model_command_count": len(records),
                "model_command_sequence": list(model_sequence),
                "sandbox_enforced": command[0] == str(
                    execution.shutil.which("sandbox-exec"))
                if sys.platform == "darwin" else False,
                "codex_usage": usage,
                "codex_event_type_counts": controller._capacity_codex_events(stdout),
                "prompt_sha256": _sha(prompt.encode("utf-8")),
                "stdout_sha256": _sha(stdout), "final_sha256": _sha(final_raw),
                "command_sha256": _sha(canonical_json_bytes(list(command))),
                "hook_source_sha256": hook["script_sha256"],
                "hook_command_sha256": hook["command_sha256"],
                "hook_config_sha256": hook["config_sha256"],
                "sandbox_profile_sha256": _sha(profile_path.read_bytes()),
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
    except Exception as exc:
        reason = _failure_reason(exc)
        try:
            if not args.output.exists() and not args.output.is_symlink():
                _publish(args.output, canonical_json_bytes(_failure_receipt(exc)))
        except Exception:
            pass
        print("refused: PT-Luna canary boundary validation failed "
              f"({reason})", file=sys.stderr)
        return 2
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
