#!/usr/bin/env python3
"""Run one score-free PT-Luna multi-operation process-boundary canary."""
from __future__ import annotations
import argparse
from collections import Counter
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
SCHEMA = "privileged-teacher-luna-boundary-canary-v5"
SYNTHETIC_SCHEMA = "privileged-teacher-luna-boundary-canary-synthetic-v2"
SYNTHETIC_DELAYED_SCHEMA = "privileged-teacher-luna-boundary-canary-synthetic-delay-v2"
FAILURE_SCHEMA = "privileged-teacher-luna-boundary-canary-failure-v3"
MAX_HOOK_OBSERVES = 3
CODE_MODE_OUTER_YIELD_SECONDS = (
    execution.CODE_MODE_OUTER_YIELD_MILLISECONDS // 1000)
CODE_MODE_NESTED_YIELD_SECONDS = (
    execution.CODE_MODE_NESTED_YIELD_MILLISECONDS // 1000)
PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS = 31
SYNTHETIC_TERMINAL_WAIT_DELAY_SECONDS = 0
SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS = 1
MODEL_COMMAND_SEQUENCE = ("observe", "rollout", "play", "wait")
CANARY_PROMPT_SUFFIX = """
Boundary-canary instruction: this synthetic decision exists only to prove the
production command/mailbox path. Issue exactly one rollout for candidate 0
with continuation smart-all, then play candidate 0 with low confidence. The
play response is waiting; follow the production instruction by invoking wait,
not observe, and finish only after wait returns round_end.
"""
FAILURE_REASON_BY_MESSAGE = {
    "canary mailbox server failed": "mailbox-server-error",
    "canary request contract refused": "request-contract-refused",
    "canary terminal not reached": "terminal-not-reached",
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
_DIAGNOSTIC_OPS = frozenset(("observe", "rollout", "play", "wait"))
_DIAGNOSTIC_PHASES = frozenset(
    ("decision", "rolled", "playing", "terminal", "unavailable"))
_PROCESS_RETURN_CLASSES = frozenset(("zero", "nonzero", "unavailable"))
_TERMINAL_EVENT_CLASSES = frozenset(
    ("turn-completed", "turn-failed", "absent-or-opaque"))
_OPAQUE = "opaque"


class _CanaryBoundaryError(ValueError):
    """A privacy-safe failure carrying only accepted operation geometry."""

    def __init__(self, message: str, *, accepted_ops: tuple[str, ...] = (),
                 phase: str = "unavailable",
                 process_return_class: str = "unavailable",
                 terminal_event_class: str = "absent-or-opaque",
                 model_mailbox_op_sequence: list[str] | str = _OPAQUE,
                 hook_observe_sequence: list[str] | str = _OPAQUE):
        super().__init__(message)
        if (type(accepted_ops) is not tuple
                or any(op not in _DIAGNOSTIC_OPS for op in accepted_ops)
                or phase not in _DIAGNOSTIC_PHASES
                or process_return_class not in _PROCESS_RETURN_CLASSES
                or terminal_event_class not in _TERMINAL_EVENT_CLASSES
                or not _valid_attribution_sequence(
                    model_mailbox_op_sequence, allow_opaque=True)
                or not _valid_attribution_sequence(
                    hook_observe_sequence, allow_opaque=True,
                    observe_only=True)):
            raise ValueError("canary failure diagnostic drift")
        self.accepted_ops = accepted_ops
        self.phase = phase
        self.process_return_class = process_return_class
        self.terminal_event_class = terminal_event_class
        self.model_mailbox_op_sequence = model_mailbox_op_sequence
        self.hook_observe_sequence = hook_observe_sequence


def _valid_attribution_sequence(value: object, *, allow_opaque: bool,
                                observe_only: bool = False) -> bool:
    if allow_opaque and value == _OPAQUE:
        return True
    if type(value) is not list:
        return False
    allowed = {"observe"} if observe_only else _DIAGNOSTIC_OPS
    return all(type(op) is str and op in allowed for op in value)


def _terminal_event_class(raw: bytes) -> str:
    """Reduce Codex JSONL to one allowlisted terminal event class."""
    terminal_events: list[str] = []
    try:
        for line in raw.splitlines():
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if type(event) is not dict or type(event.get("type")) is not str:
                return "absent-or-opaque"
            if event["type"] not in execution.CODEX_EVENT_TYPES:
                return "absent-or-opaque"
            if event["type"] in ("turn.completed", "turn.failed"):
                terminal_events.append(event["type"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "absent-or-opaque"
    if terminal_events == ["turn.completed"]:
        return "turn-completed"
    if terminal_events == ["turn.failed"]:
        return "turn-failed"
    return "absent-or-opaque"


def _command_attribution_present(raw: bytes) -> tuple[bool, bool]:
    """Return (command item seen, JSONL structure opaque) without retaining it."""
    command_seen = False
    try:
        for line in raw.splitlines():
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if (type(event) is not dict or type(event.get("type")) is not str
                    or event["type"] not in execution.CODEX_EVENT_TYPES):
                return command_seen, True
            if not event["type"].startswith("item."):
                continue
            item = event.get("item")
            if type(item) is not dict or type(item.get("type")) is not str:
                return command_seen, True
            if item["type"] == "command_execution":
                command_seen = True
    except (UnicodeDecodeError, json.JSONDecodeError):
        return command_seen, True
    return command_seen, False


def _derive_attribution(*, raw: bytes, mailbox_path: Path,
                        trace: list[dict[str, object]],
                        python_path: Path, tool_script_path: Path) \
        -> tuple[str, list[str] | str, list[str] | str]:
    """Derive only bounded process/mailbox attribution from private inputs."""
    terminal_class = _terminal_event_class(raw)
    command_seen, opaque = _command_attribution_present(raw)
    try:
        records = execution._codex_command_mailbox_records(
            raw, mailbox_path=mailbox_path, python_path=python_path,
            tool_script_path=tool_script_path, require_shell=True)
    except Exception:
        if not command_seen and not opaque:
            model_sequence: list[str] | str = []
            hook_sequence: list[str] | str = (
                ["observe"] * len(trace)
                if all(type(event) is dict
                       and event.get("request") in (
                           {"op": "observe"},
                           {"op": "observe",
                            execution.STOP_HOOK_REQUEST_FIELD: True})
                       for event in trace)
                else _OPAQUE)
            return terminal_class, model_sequence, hook_sequence
        return terminal_class, _OPAQUE, _OPAQUE
    try:
        model_sequence, hook_sequence = _bind_model_commands(records, trace)
    except Exception:
        return terminal_class, _OPAQUE, _OPAQUE
    return terminal_class, model_sequence, hook_sequence
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
    accepted_ops = (exc.accepted_ops
                    if isinstance(exc, _CanaryBoundaryError) else ())
    phase = exc.phase if isinstance(exc, _CanaryBoundaryError) else "unavailable"
    process_return_class = (exc.process_return_class
                            if isinstance(exc, _CanaryBoundaryError)
                            else "unavailable")
    terminal_event_class = (exc.terminal_event_class
                            if isinstance(exc, _CanaryBoundaryError)
                            else "absent-or-opaque")
    model_mailbox_op_sequence = (
        exc.model_mailbox_op_sequence
        if isinstance(exc, _CanaryBoundaryError) else _OPAQUE)
    hook_observe_sequence = (
        exc.hook_observe_sequence
        if isinstance(exc, _CanaryBoundaryError) else _OPAQUE)
    body = {
        "schema": FAILURE_SCHEMA,
        "reason": _failure_reason(exc),
        "detail_sha256": _sha(str(exc).encode("utf-8")),
        "canary_source_sha256": _sha(Path(__file__).read_bytes()),
        "execution_source_sha256": _sha(Path(execution.__file__).read_bytes()),
        "accepted_op_sequence": list(accepted_ops),
        "accepted_op_counts": {
            op: accepted_ops.count(op) for op in sorted(set(accepted_ops))},
        "terminal_phase": phase,
        "process_return_class": process_return_class,
        "terminal_event_class": terminal_event_class,
        "model_mailbox_op_sequence": model_mailbox_op_sequence,
        "hook_observe_sequence": hook_observe_sequence,
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
                         "accepted_op_sequence", "accepted_op_counts",
                         "terminal_phase", "process_return_class",
                         "terminal_event_class", "model_mailbox_op_sequence",
                         "hook_observe_sequence",
                         "opened", "retained", "authority"}
            or payload["schema"] != FAILURE_SCHEMA
            or payload["reason"] not in FAILURE_REASONS
            or payload["opened"] != _PRIVACY
            or payload["retained"] != _PRIVACY
            or payload["authority"] != luna.AUTHORITY):
        raise ValueError("canary failure receipt schema drift")
    if (payload["process_return_class"] not in _PROCESS_RETURN_CLASSES
            or payload["terminal_event_class"] not in _TERMINAL_EVENT_CLASSES
            or not _valid_attribution_sequence(
                payload["model_mailbox_op_sequence"], allow_opaque=True)
            or not _valid_attribution_sequence(
                payload["hook_observe_sequence"], allow_opaque=True,
                observe_only=True)):
        raise ValueError("canary failure diagnostic drift")
    sequence = payload["accepted_op_sequence"]
    counts = payload["accepted_op_counts"]
    if (type(sequence) is not list
            or any(op not in _DIAGNOSTIC_OPS for op in sequence)
            or type(counts) is not dict
            or counts != {op: sequence.count(op)
                          for op in sorted(set(sequence))}
            or payload["terminal_phase"] not in _DIAGNOSTIC_PHASES):
        raise ValueError("canary failure diagnostic drift")
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

    def __init__(self, token: str, *, terminal_wait_delay_seconds: int = 0):
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("canary token identity drift")
        if (isinstance(terminal_wait_delay_seconds, bool)
                or not isinstance(terminal_wait_delay_seconds, int)
                or not 0 <= terminal_wait_delay_seconds <= 180):
            raise ValueError("canary terminal wait delay drift")
        self.token = token
        self.terminal_wait_delay_seconds = terminal_wait_delay_seconds
        self.terminal_wait_delayed = False
        self.terminal_wait_inflight = False
        self.terminal_wait_started = threading.Event()
        self.phase = "decision"
        self.rollout_calls = 0
        self.terminal = False
        root = luna.build_root(bytes.fromhex(token), ("2", 0, 0))
        game = luna.LunaSelfPlayGame(root, coordinate=("2", 0, 0))
        observed = game.session(game.acting_team).observe()
        if observed.get("status") != "decision":
            raise ValueError("canary production decision fixture drift")
        self.observation = observed
        self.decision_sha256 = str(observed["decision_sha256"])
        self.lock = threading.Lock()

    def decision_response(self) -> dict[str, object]:
        """Return a deep, production-shaped decision with live canary budget."""
        # JSON round-trip is deliberate: it prevents a model-tool caller from
        # aliasing the private fixture while keeping exactly the public shape.
        response = json.loads(json.dumps(self.observation))
        hands = response.get("hands_by_seat")
        candidates = response.get("candidates")
        seat = response.get("acting_seat")
        if (type(hands) is not list or len(hands) != 4
                or isinstance(seat, bool) or not isinstance(seat, int)
                or not 0 <= seat < 4 or type(hands[seat]) is not list
                or type(candidates) is not list or not candidates
                or any(type(candidate) is not list or not candidate
                       for candidate in candidates)
                or any(Counter(candidate) - Counter(hands[seat])
                       for candidate in candidates)
                or type(response.get("current_state")) is not dict
                or not response["current_state"]
                or response.get("candidate_zero_is_production_prior") is not True):
            raise ValueError("canary production decision fixture drift")
        budget = response.get("budget")
        if (type(budget) is not dict
                or set(budget) != {"rollout_calls", "rollout_calls_limit",
                                   "used", "round_used", "decision_limit",
                                   "round_limit"}
                or budget["rollout_calls_limit"]
                != luna.sol0.MAX_ROLLOUT_CALLS_PER_DECISION
                or budget["decision_limit"]
                != luna.sol0.MAX_EVALUATIONS_PER_DECISION
                or budget["round_limit"]
                != luna.sol0.MAX_EVALUATIONS_PER_ROUND):
            raise ValueError("canary production decision fixture drift")
        budget.update(rollout_calls=self.rollout_calls,
                      used=self.rollout_calls,
                      round_used=self.rollout_calls)
        return response


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
        self._nonterminal_stop_blocks = 0
        self._record_lock = threading.Lock()
        self._inflight: set[Path] = set()
        self._workers: list[threading.Thread] = []
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
        hook_stop = (op == "observe"
                     and set(request) == {"op", execution.STOP_HOOK_REQUEST_FIELD}
                     and request.get(execution.STOP_HOOK_REQUEST_FIELD) is True)
        if (op == "observe" and set(request) != {"op"} and not hook_stop):
            raise ValueError("canary request shape drift")
        if op == "wait" and set(request) != {"op"}:
            raise ValueError("canary request shape drift")
        with self._record_lock:
            self.first_op = self.first_op or op
            self.sequence.append(op)
            self.counts[op] = self.counts.get(op, 0) + 1
        if op == "wait":
            with self.state.lock:
                phase = self.state.phase
                if phase == "playing":
                    self.state.terminal_wait_inflight = True
                    self.state.terminal_wait_started.set()
                    delay = self.state.terminal_wait_delay_seconds
                else:
                    delay = 0
            delayed = bool(delay) and not self._stop.wait(delay)
            with self.state.lock:
                if phase == "playing":
                    self.state.terminal_wait_delayed = delayed
                    self.state.terminal_wait_inflight = False
                    self.state.terminal = True
                    self.state.phase = "terminal"
                    response = {"schema": luna.GAME_SCHEMA,
                                "status": "round_end",
                                "completion_token": self.state.token}
                elif phase == "terminal":
                    response = {"schema": luna.GAME_SCHEMA,
                                "status": "round_end",
                                "completion_token": self.state.token}
                else:
                    response = {"schema": luna.GAME_SCHEMA,
                                "status": "waiting"}
        else:
            with self.state.lock:
                if op == "observe":
                    if self.state.phase in ("decision", "rolled"):
                        response = self.state.decision_response()
                    elif (self.state.phase == "playing"
                          and self.state.terminal_wait_inflight):
                        response = {"schema": luna.GAME_SCHEMA,
                                    "status": "waiting", "acting_team": 1}
                    elif self.state.phase == "playing":
                        self.state.terminal = True
                        self.state.phase = "terminal"
                        response = {"schema": luna.GAME_SCHEMA,
                                    "status": "round_end",
                                    "completion_token": self.state.token}
                    else:
                        self.state.terminal = True
                        self.state.phase = "terminal"
                        response = {"schema": luna.GAME_SCHEMA,
                                    "status": "round_end",
                                    "completion_token": self.state.token}
                    if hook_stop:
                        if response.get("status") == "round_end":
                            action = "terminal"
                        elif (self._nonterminal_stop_blocks
                              < execution.MAX_STOP_HOOK_NONTERMINAL_BLOCKS):
                            self._nonterminal_stop_blocks += 1
                            action = "block"
                        else:
                            action = "exhausted"
                        response = dict(response)
                        response[execution.STOP_HOOK_ACTION_FIELD] = action
                elif op == "rollout":
                    if (self.state.phase not in ("decision", "rolled")
                            or self.state.rollout_calls >= 2
                            or set(request) != {
                                "op", "decision_sha256", "candidate_indices",
                                "continuations"}
                            or request.get("decision_sha256")
                            != self.state.decision_sha256
                            or request.get("candidate_indices") != [0]
                            or request.get("continuations") != ["smart-all"]):
                        raise ValueError("canary model rollout drift")
                    self.state.rollout_calls += 1
                    self.state.phase = "rolled"
                    response = {
                        "schema": luna.GAME_SCHEMA,
                        "status": "rollout_complete", "new_evaluations": 1,
                        "cached_evaluations": 0,
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
                            or request.get("decision_sha256")
                            != self.state.decision_sha256
                            or request.get("candidate_index") != 0
                            or request.get("confidence") != "low"):
                        raise ValueError("canary model play drift")
                    self.state.phase = "playing"
                    response = {"schema": luna.GAME_SCHEMA,
                                "status": "waiting", "acting_team": 1}
                else:
                    raise ValueError("canary mailbox operation limit")
        with self._record_lock:
            self.trace.append({
                "request": dict(request), "response": response,
                "response_sha256": _sha(canonical_json_bytes(response))})
        return response

    def _serve_request(self, request_path: Path,
                       response_path: Path) -> None:
        try:
            try:
                request = _strict(request_path.read_bytes(), "canary request")
                response = self._dispatch(request)
            except Exception:
                with self._record_lock:
                    self.refused = True
                response = {"status": "error", "error": "canary request refused"}
            self._response(response_path, response)
        except BaseException as exc:
            self.error = exc
            self._stop.set()
        finally:
            with self._record_lock:
                self._inflight.discard(request_path)

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                for request_path in sorted(self.path.glob("request-*.json")):
                    suffix = request_path.name.removeprefix("request-").removesuffix(".json")
                    if len(suffix) != 64 or any(c not in "0123456789abcdef" for c in suffix):
                        continue
                    response_path = self.path / f"response-{suffix}.json"
                    with self._record_lock:
                        if (response_path.exists()
                                or request_path in self._inflight):
                            continue
                        self._inflight.add(request_path)
                    worker = threading.Thread(
                        target=self._serve_request,
                        args=(request_path, response_path), daemon=True)
                    with self._record_lock:
                        self._workers.append(worker)
                    worker.start()
                self._stop.wait(0.002)
        except BaseException as exc:  # surfaced only as a generic refusal
            self.error = exc
    def __enter__(self) -> "_CanaryMailbox":
        self._thread.start()
        return self
    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise ValueError("canary mailbox failed")
        with self._record_lock:
            workers = list(self._workers)
        for worker in workers:
            worker.join(timeout=5)
        if any(worker.is_alive() for worker in workers):
            raise ValueError("canary mailbox failed")
def _validate_runtime(runtime: object) -> None:
    if type(runtime) is not dict:
        raise ValueError("canary runtime identity drift")
    required = {"python_executable", "python_version", "python_sha256",
                "codex_binary", "codex_binary_sha256", "codex_version",
                "platform", "tool_script", "tool_script_sha256",
                "expected_tool_mode", "expected_shell_type",
                "expected_tool_name"}
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
    if (runtime["expected_tool_mode"] != execution.CODE_MODE_TOOL_MODE
            or runtime["expected_shell_type"] != execution.CODE_MODE_SHELL_TYPE
            or runtime["expected_tool_name"] != execution.CODE_MODE_TOOL_NAME):
        raise ValueError("canary code-mode identity drift")
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
    if (not records or not trace or type(trace[0]) is not dict
            or trace[0].get("request") != {"op": "observe"}):
        raise ValueError("canary model-origin first observe absent")
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
                   or event.get("request") != {
                       "op": "observe", execution.STOP_HOOK_REQUEST_FIELD: True}
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
                "code_mode_outer_yield_seconds",
                "code_mode_nested_yield_seconds",
                "terminal_wait_delay_seconds", "terminal_wait_delayed",
                "production_yield_witness",
                "codex_usage", "codex_event_type_counts",
                "prompt_sha256", "stdout_sha256", "final_sha256",
                "command_sha256", "hook_source_sha256",
                "hook_command_sha256", "hook_config_sha256",
                "canary_source_sha256", "execution_source_sha256",
                "codex_launcher", "codex_launcher_sha256", "sandbox_profile_sha256",
                "opened",
                "retained", "authority"}
    if (set(payload) != expected
            or payload["schema"] not in (SCHEMA, SYNTHETIC_SCHEMA,
                                           SYNTHETIC_DELAYED_SCHEMA)):
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
    outer_yield = payload["code_mode_outer_yield_seconds"]
    nested_yield = payload["code_mode_nested_yield_seconds"]
    wait_delay = payload["terminal_wait_delay_seconds"]
    delayed = payload["terminal_wait_delayed"]
    production = payload["production_yield_witness"]
    if (outer_yield != CODE_MODE_OUTER_YIELD_SECONDS
            or nested_yield != CODE_MODE_NESTED_YIELD_SECONDS
            or isinstance(wait_delay, bool) or not isinstance(wait_delay, int)
            or not 0 <= wait_delay <= 180 or type(delayed) is not bool
            or type(production) is not bool
            or delayed != (wait_delay > 0)):
        raise ValueError("canary code-mode yield witness drift")
    schema = payload["schema"]
    if (schema == SCHEMA
            and (not production
                 or wait_delay != PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS)):
        raise ValueError("canary production yield witness drift")
    if (schema == SYNTHETIC_SCHEMA
            and (production or wait_delay != SYNTHETIC_TERMINAL_WAIT_DELAY_SECONDS)):
        raise ValueError("canary synthetic yield witness drift")
    if (schema == SYNTHETIC_DELAYED_SCHEMA
            and (production
                 or wait_delay != SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS)):
        raise ValueError("canary synthetic delayed yield witness drift")
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
def run(*, codex_binary: Path, output: Path, deadline_seconds: int,
        terminal_wait_delay_seconds: int | None = None) -> dict[str, object]:
    if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int)
            or not 1 <= deadline_seconds <= 180):
        raise ValueError("deadline-seconds must be between 1 and 180")
    production_yield_witness = terminal_wait_delay_seconds is None
    terminal_wait_delay_seconds = (
        PRODUCTION_TERMINAL_WAIT_DELAY_SECONDS
        if production_yield_witness else terminal_wait_delay_seconds)
    if (isinstance(terminal_wait_delay_seconds, bool)
            or not isinstance(terminal_wait_delay_seconds, int)
            or not 0 <= terminal_wait_delay_seconds <= 180):
        raise ValueError("terminal-wait-delay-seconds must be between 0 and 180")
    if (production_yield_witness
            and not (CODE_MODE_NESTED_YIELD_SECONDS
                     < terminal_wait_delay_seconds
                     < CODE_MODE_OUTER_YIELD_SECONDS)):
        raise ValueError("production code-mode yield requirement drift")
    if (not production_yield_witness and terminal_wait_delay_seconds not in (
            SYNTHETIC_TERMINAL_WAIT_DELAY_SECONDS,
            SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS)):
        raise ValueError("unsupported synthetic terminal wait delay")
    binary = Path(codex_binary).absolute()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Codex binary absent or not executable")
    if sys.platform == "darwin" and execution.shutil.which("sandbox-exec") is None:
        raise ValueError("production peer sandbox unavailable")
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError("canary output occupied")
    tool_script = Path(__file__).with_name("privileged_teacher_luna_selfplay_tool.py")
    runtime = execution.runtime_identity(codex_binary=binary, tool_script=tool_script)
    if production_yield_witness:
        execution.validate_codex_model_surface(codex_binary=binary)
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
        state = _CanaryState(
            token, terminal_wait_delay_seconds=terminal_wait_delay_seconds)
        with _CanaryMailbox(mailbox_path, state=state) as mailbox:
            def boundary_error(message: str, raw: bytes,
                               returncode: int | None) -> _CanaryBoundaryError:
                accepted_ops = tuple(
                    str(event["request"]["op"]) for event in mailbox.trace)
                terminal_event_class, model_sequence, hook_sequence = (
                    _derive_attribution(
                        raw=bytes(raw), mailbox_path=mailbox_path,
                        trace=mailbox.trace, python_path=Path(sys.executable),
                        tool_script_path=tool_script))
                return _CanaryBoundaryError(
                    message, accepted_ops=accepted_ops, phase=state.phase,
                    process_return_class=(
                        "zero" if returncode == 0 else "nonzero"
                        if isinstance(returncode, int) else "unavailable"),
                    terminal_event_class=terminal_event_class,
                    model_mailbox_op_sequence=model_sequence,
                    hook_observe_sequence=hook_sequence)

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
                try:
                    timeout_stdout, timeout_stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired as drain_exc:
                    process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    timeout_stdout = bytes(drain_exc.stdout or exc.stdout or b"")
                    timeout_stderr = bytes(drain_exc.stderr or exc.stderr or b"")
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
                if len(timeout_stderr or b"") > execution.MAX_PROCESS_BYTES:
                    timeout_stderr = b""
                raise boundary_error(
                    "canary subprocess deadline exceeded",
                    bytes(timeout_stdout or b""), process.returncode) from exc
            if len(stderr or b"") > execution.MAX_PROCESS_BYTES:
                raise ValueError("canary stderr limit exceeded")
        stdout = bytes(stdout or b"")

        if mailbox.error is not None:
            raise boundary_error(
                "canary mailbox server failed", stdout, process.returncode)
        if mailbox.refused:
            raise boundary_error(
                "canary request contract refused", stdout, process.returncode)
        if not state.terminal:
            raise boundary_error(
                "canary terminal not reached", stdout, process.returncode)
        try:
            usage = execution._codex_jsonl_usage(stdout)
            records = execution._codex_command_mailbox_records(
                stdout, mailbox_path=mailbox_path,
                python_path=Path(sys.executable), tool_script_path=tool_script,
                require_shell=True)
        except Exception as exc:
            raise boundary_error(
                "canary command mailbox attribution refused", stdout,
                process.returncode) from exc
        try:
            model_sequence, hook_sequence = _bind_model_commands(
                records, mailbox.trace)
        except Exception as exc:
            raise boundary_error(
                "canary command mailbox attribution refused", stdout,
                process.returncode) from exc
        if model_sequence != list(MODEL_COMMAND_SEQUENCE):
            raise boundary_error(
                "canary model operation contract refused", stdout,
                process.returncode)
        if not 1 <= len(hook_sequence) <= MAX_HOOK_OBSERVES:
            raise boundary_error(
                "canary hook operation contract refused", stdout,
                process.returncode)
        if process.returncode != 0:
            raise boundary_error(
                "canary subprocess did not complete", stdout,
                process.returncode)
        if not final_path.is_file() or final_path.is_symlink():
            raise boundary_error(
                "canary subprocess did not complete", stdout,
                process.returncode)
        final_raw = execution._read_process_file(final_path, limit=1 << 20)
        expected_final = canonical_json_bytes({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": token})
        # Codex's last-message file is the assistant message itself and may
        # omit the canonical artifact newline.  Accept only those two byte
        # forms of the same exact terminal JSON.
        if final_raw not in (expected_final, expected_final.removesuffix(b"\n")):
            raise ValueError("canary final response drift")
        receipt_schema = (SCHEMA if production_yield_witness
                          else SYNTHETIC_SCHEMA
                          if terminal_wait_delay_seconds
                          == SYNTHETIC_TERMINAL_WAIT_DELAY_SECONDS
                          else SYNTHETIC_DELAYED_SCHEMA
                          if terminal_wait_delay_seconds
                          == SYNTHETIC_DELAYED_TERMINAL_WAIT_DELAY_SECONDS
                          else None)
        if receipt_schema is None:
            raise ValueError("unsupported synthetic terminal wait delay")
        body = {"schema": receipt_schema, "runtime_identity": runtime,
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
                "code_mode_outer_yield_seconds": CODE_MODE_OUTER_YIELD_SECONDS,
                "code_mode_nested_yield_seconds": CODE_MODE_NESTED_YIELD_SECONDS,
                "terminal_wait_delay_seconds": terminal_wait_delay_seconds,
                "terminal_wait_delayed": state.terminal_wait_delayed,
                "production_yield_witness": production_yield_witness,
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
    parser.add_argument("--terminal-wait-delay-seconds", type=int,
                        default=None,
                        help="explicit non-production delay override for tests")
    args = parser.parse_args(argv)
    try:
        run(codex_binary=args.codex_binary, output=args.output,
            deadline_seconds=args.deadline_seconds,
            terminal_wait_delay_seconds=args.terminal_wait_delay_seconds)
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
