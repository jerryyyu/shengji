"""Ephemeral zero-tool Codex transport for supervisor-owned PT-Luna turns.

The model receives one immutable decision packet and can only return a strict
JSON intent.  It never receives a Shengji mailbox, shell command, MCP server,
or engine mutation capability.  The supervisor validates the response before
the turn driver can execute a rollout or play.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from . import privileged_teacher_luna_selfplay as selfplay
from .privileged_teacher_luna_turn_rpc import (
    CONFIDENCE_LEVELS,
    CONTINUATIONS,
    DecisionPacket,
    Intent,
    PlannerResponse,
    TurnRPCError,
    TurnValidationError,
    Usage,
)
from .privileged_teacher_pt0 import canonical_json_bytes


MODEL = selfplay.MODEL
REASONING_EFFORT = "medium"
PINNED_CODEX_VERSION = "codex-cli 0.149.0"
CODE_MODE_DISABLED_DIAGNOSTIC = (
    "Code Mode is unavailable because code-mode host is disabled. "
    "Code mode will fail closed; enable `features.code_mode_host` and install "
    "`codex-code-mode-host`."
)
MAX_TRACE_BYTES = 16 << 20
MAX_FINAL_BYTES = 1 << 20
CODEX_USAGE_KEYS = frozenset({
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
})
DISABLED_FEATURES = (
    "plugins",
    "skill_search",
    "apps",
    "hooks",
    "multi_agent",
    "goals",
    "unified_exec",
    "shell_tool",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "view_image",
    "code_mode",
    "code_mode_host",
    "code_mode_only",
    "remote_plugin",
    "recommended_plugins",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "workspace_dependencies",
)


class CodexTurnTransportError(TurnRPCError):
    """The isolated Codex subprocess or its evidence was refused."""


class CodexProviderResourceError(CodexTurnTransportError):
    """The provider process, timeout, or response availability failed."""


class CodexToolEventError(CodexTurnTransportError):
    """The isolated Codex subprocess emitted a forbidden tool item."""


PRIVATE_EVIDENCE_SCHEMA = "pt-luna-codex-private-evidence-v1"
PRIVATE_REFUSAL_EVIDENCE_SCHEMA = (
    "pt-luna-codex-private-refusal-evidence-v1")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CodexTurnTransportError("duplicate JSON key")
        result[key] = value
    return result


def _strict_json(raw: bytes, label: str) -> object:
    if not raw or len(raw) > MAX_FINAL_BYTES:
        raise CodexTurnTransportError(f"{label} size drift")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_no_duplicate_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexTurnTransportError(f"{label} JSON drift") from exc
    return value


def intent_output_schema(packet: DecisionPacket, *,
                         allowed_kinds: tuple[str, ...] | None = None) \
        -> dict[str, object]:
    """Return the phase- and ballot-bound model output schema."""
    # The Responses structured-output subset requires a root object and all
    # properties to be required.  Keep that root closed while placing the
    # play/rollout union in one required nested object.  This structurally
    # prevents an empty rollout without making a play carry fake sentinels.
    default = (("play",) if packet.phase.phase >= 3
               else ("play", "rollout"))
    kinds = list(default if allowed_kinds is None else allowed_kinds)
    if not kinds or any(kind not in default for kind in kinds):
        raise CodexTurnTransportError("Codex allowed intent kind drift")
    play = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "const": "play"},
            "candidate_index": {"type": "integer", "minimum": 0,
                                "maximum": len(packet.candidates) - 1},
            "confidence": {"type": "string",
                           "enum": list(CONFIDENCE_LEVELS)},
            "planning_note": {"type": "string", "maxLength": 2048},
        },
        "required": ["kind", "candidate_index", "confidence",
                     "planning_note"],
        "additionalProperties": False,
    }
    rollout = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "const": "rollout"},
            "candidate_indices": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": {"type": "integer", "minimum": 0,
                          "maximum": len(packet.candidates) - 1}},
            "continuations": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": {"type": "string",
                          "enum": list(CONTINUATIONS)}},
            "planning_note": {"type": "string", "maxLength": 2048},
        },
        "required": ["kind", "candidate_indices", "continuations",
                     "planning_note"],
        "additionalProperties": False,
    }
    variants = {"play": play, "rollout": rollout}
    action = (variants[kinds[0]] if len(kinds) == 1
              else {"anyOf": [variants[kind] for kind in kinds]})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "schema": {
                "type": "string", "const": "pt-luna-provider-intent-v2"},
            "decision_sha256": {
                "type": "string", "const": packet.decision_sha256},
            "action": action,
        },
        "required": ["schema", "decision_sha256", "action"],
        "additionalProperties": False,
    }


def _provider_intent(
        value: object, packet: DecisionPacket, *,
        allowed_kinds: tuple[str, ...] | None = None) -> Intent:
    expected = {"schema", "decision_sha256", "action"}
    if type(value) is not dict or set(value) != expected \
            or value.get("schema") != "pt-luna-provider-intent-v2" \
            or value.get("decision_sha256") != packet.decision_sha256:
        raise CodexTurnTransportError("Codex intent refused: shape or decision drift")
    action = value.get("action")
    if type(action) is not dict:
        raise CodexTurnTransportError("Codex intent refused: action shape drift")
    kind = action.get("kind")
    permitted = (("play",) if packet.phase.phase >= 3
                 else ("play", "rollout")) \
        if allowed_kinds is None else allowed_kinds
    if kind not in permitted:
        raise CodexTurnTransportError("Codex intent refused: policy kind drift")
    if kind == "play":
        if set(action) != {"kind", "candidate_index", "confidence",
                           "planning_note"} \
                or action.get("confidence") not in CONFIDENCE_LEVELS:
            raise CodexTurnTransportError("Codex intent refused: play shape drift")
        try:
            return Intent("play", packet.decision_sha256,
                          candidate_index=action["candidate_index"],
                          confidence=action["confidence"],
                          planning_note=action["planning_note"])
        except TurnValidationError as exc:
            raise CodexTurnTransportError("Codex intent refused") from exc
    if kind == "rollout" and packet.phase.phase < 3:
        if set(action) != {"kind", "candidate_indices", "continuations",
                           "planning_note"} \
                or type(action.get("candidate_indices")) is not list \
                or type(action.get("continuations")) is not list:
            raise CodexTurnTransportError("Codex intent refused: rollout shape drift")
        candidates = action["candidate_indices"]
        continuations = action["continuations"]
        if not candidates or not continuations:
            raise CodexTurnTransportError(
                "Codex intent refused: rollout list empty")
        if len(candidates) > 4 or len(continuations) > 4 \
                or len(candidates) * len(continuations) > 16:
            raise CodexTurnTransportError(
                "Codex intent refused: rollout candidate budget drift")
        if any(isinstance(index, bool) or not isinstance(index, int)
               or not 0 <= index < len(packet.candidates)
               for index in candidates):
            raise CodexTurnTransportError(
                "Codex intent refused: rollout candidate range drift")
        if len(set(candidates)) != len(candidates):
            raise CodexTurnTransportError(
                "Codex intent refused: duplicate rollout candidate")
        if (any(type(name) is not str or name not in CONTINUATIONS
                for name in continuations)
                or len(set(continuations)) != len(continuations)):
            raise CodexTurnTransportError(
                "Codex intent refused: rollout continuation drift")
        try:
            return Intent("rollout", packet.decision_sha256,
                          candidate_indices=tuple(candidates),
                          continuations=tuple(continuations),
                          planning_note=action["planning_note"])
        except TurnValidationError as exc:
            raise CodexTurnTransportError("Codex intent refused") from exc
    raise CodexTurnTransportError("Codex intent refused: phase or kind drift")


def planner_prompt(packet: DecisionPacket, *, policy_mode: str = "free") -> str:
    if policy_mode == "canary-rollout-then-play":
        phase_rule = ("This boundary canary requires one rollout batch now."
                      if packet.phase.phase == 1 else
                      "The boundary rollout is complete; you must play now.")
        action_rule = ("Return one nested action: a play has candidate_index and "
                       "confidence, while a rollout has nonempty "
                       "candidate_indices and continuations.")
        action_details = ("If requesting rollouts, choose 1–4 distinct candidate "
                          "indices and 1–4 distinct continuation names. Never "
                          "repeat an index or continuation; their Cartesian "
                          "product must be at most 16.")
        context_rule = ("the ordered legal candidate ballot, prior rollout "
                        "results, the exact phase budget, and your team-private "
                        "bounded strategy note")
    elif policy_mode == "free":
        phase_rule = (
            "You may either play now or request one bounded rollout batch."
            if packet.phase.phase < 3 else
            "Both rollout opportunities are spent; you must play now.")
        action_rule = ("Return one nested action: a play has candidate_index and "
                       "confidence, while a rollout has nonempty "
                       "candidate_indices and continuations.")
        action_details = ("If requesting rollouts, choose 1–4 distinct candidate "
                          "indices and 1–4 distinct continuation names. Never "
                          "repeat an index or continuation; their Cartesian "
                          "product must be at most 16.")
        context_rule = ("the ordered legal candidate ballot, prior rollout "
                        "results, the exact phase budget, and your team-private "
                        "bounded strategy note")
    elif policy_mode == "play-only":
        phase_rule = "You must play now; no alternate action is permitted."
        action_rule = ("Return exactly one nested play action with "
                       "candidate_index and confidence.")
        action_details = "Do not return any other action shape."
        context_rule = ("the ordered legal candidate ballot, the exact phase "
                        "budget, and your team-private bounded strategy note")
    else:
        raise CodexTurnTransportError("Codex planner policy mode drift")
    payload = canonical_json_bytes(packet.payload()).decode("utf-8").rstrip("\n")
    return f"""You are PT-Luna, one partnership in a full-information Shengji teacher game.
The engine/supervisor owns all mechanics. You have no tools and must return one
JSON object matching the supplied schema. {action_rule} Maximize final
signed-level utility
for team {packet.team}; do not substitute raw attacker points for team utility.

The packet contains the complete private engine state, {context_rule}.
Candidate index 0 is the production prior. Never invent a card, candidate,
state transition, or planning result. {phase_rule} Use planning_note for a
concise team plan; it is private to your team. {action_details}

DECISION_PACKET_JSON
{payload}
"""


@dataclass(frozen=True)
class InvocationResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    wall_ms: int


RunCommand = Callable[[tuple[str, ...], bytes, Path, int], InvocationResult]
RuntimeAttestor = Callable[[Path | str], dict[str, object]]
DeadlineProvider = Callable[[], int]


class ActiveCallManager:
    """Own liveness FDs and process groups for one controller instance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[int, int] = {}
        self._stopped = False

    def register(self, process_group: int, watchdog_fd: int) -> None:
        with self._lock:
            admitted = (not self._stopped
                        and process_group not in self._calls)
            if admitted:
                self._calls[process_group] = watchdog_fd
        if not admitted:
            try:
                os.close(watchdog_fd)
            except OSError:
                pass
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise CodexProviderResourceError(
                "Codex process-group registration refused")

    def release(self, process_group: int, watchdog_fd: int) -> None:
        owned = False
        with self._lock:
            if self._calls.get(process_group) == watchdog_fd:
                self._calls.pop(process_group, None)
                owned = True
        # Cancellation owns closure after it removes the mapping.  Never
        # close an already-removed descriptor: its integer may be reused.
        if owned:
            try:
                os.close(watchdog_fd)
            except OSError:
                pass

    def terminate(self) -> None:
        with self._lock:
            self._stopped = True
            active = tuple(self._calls.items())
            self._calls.clear()
        for process_group, watchdog_fd in active:
            try:
                os.close(watchdog_fd)
            except OSError:
                pass
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _start_contained_process(command: tuple[str, ...], *, workspace: Path,
                             env: dict[str, str],
                             active_calls: ActiveCallManager) \
        -> tuple[subprocess.Popen[bytes], int]:
    """Launch one RPC behind a pipe-triggered parent-death watchdog."""
    read_fd, write_fd = os.pipe()
    wrapper = (
        sys.executable, "-B", "-m",
        "shengji.rl.privileged_teacher_luna_rpc_watchdog",
        str(read_fd), *command)
    try:
        process = subprocess.Popen(
            wrapper, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=workspace, env=env,
            start_new_session=True, pass_fds=(read_fd,))
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    active_calls.register(process.pid, write_fd)
    return process, write_fd


def _default_run(command: tuple[str, ...], prompt: bytes, workspace: Path,
                 timeout_seconds: int, *,
                 _active_call_manager: ActiveCallManager | None = None) \
        -> InvocationResult:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    active_calls = _active_call_manager or ActiveCallManager()
    started = time.monotonic_ns()
    try:
        process, watchdog_fd = _start_contained_process(
            command, workspace=workspace, env=env,
            active_calls=active_calls)
    except OSError as exc:
        raise CodexProviderResourceError("Codex turn launch failed") from exc
    try:
        stdout, stderr = process.communicate(input=prompt,
                                             timeout=timeout_seconds)
        returncode = int(process.returncode or 0)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise CodexProviderResourceError(
            "Codex turn deadline exceeded") from exc
    finally:
        # Kill the recorded group even if the helper leader already exited:
        # a helper-only crash must not orphan its Codex descendant.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.communicate()
        active_calls.release(process.pid, watchdog_fd)
    wall_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    return InvocationResult(returncode, stdout, stderr, wall_ms)


def attest_codex_runtime(codex_binary: Path | str) -> dict[str, object]:
    """Prove the pinned CLI exposes none of the tool-bearing feature catalog."""
    binary = Path(codex_binary).resolve()
    if not binary.is_file():
        raise CodexTurnTransportError("Codex binary absent")
    disabled_args = [item for feature in DISABLED_FEATURES
                     for item in ("-c", f"features.{feature}=false")]
    try:
        version = subprocess.run(
            (str(binary), "--version"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=5)
        catalog = subprocess.run(
            (str(binary), *disabled_args, "features", "list"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodexTurnTransportError("Codex runtime attestation failed") from exc
    version_text = version.stdout.decode("utf-8").strip()
    if version.returncode != 0 or version.stderr \
            or version_text != PINNED_CODEX_VERSION:
        raise CodexTurnTransportError("Codex version is not pinned")
    if catalog.returncode != 0 or catalog.stderr:
        raise CodexTurnTransportError("Codex feature catalog unavailable")
    values: dict[str, bool] = {}
    for line in catalog.stdout.decode("utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] in ("true", "false"):
            values[parts[0]] = parts[-1] == "true"
    if any(feature not in values or values[feature]
           for feature in DISABLED_FEATURES):
        raise CodexTurnTransportError("Codex tool catalog is not empty")
    return {"schema": "pt-luna-codex-tool-catalog-v1",
            "version": version_text,
            "binary_sha256": _sha_bytes(binary.read_bytes()),
            "disabled_features": list(DISABLED_FEATURES),
            "feature_catalog_sha256": _sha_bytes(catalog.stdout)}


def _events_and_usage(raw: bytes) -> tuple[list[dict[str, object]], dict[str, int], str]:
    if not raw or len(raw) > MAX_TRACE_BYTES:
        raise CodexTurnTransportError("Codex JSONL size drift")
    events: list[dict[str, object]] = []
    messages: list[str] = []
    diagnostics = 0
    turn_started = False
    for line in raw.splitlines():
        if not line:
            continue
        value = _strict_json(line, "Codex JSONL event")
        if type(value) is not dict or type(value.get("type")) is not str:
            raise CodexTurnTransportError("Codex JSONL event drift")
        event = value
        events.append(event)
        if event["type"] == "turn.started":
            if turn_started:
                raise CodexTurnTransportError("Codex turn-start telemetry drift")
            turn_started = True
        elif event["type"] == "item.completed":
            item = event.get("item")
            if type(item) is not dict:
                raise CodexToolEventError("Codex tool event forbidden")
            if item.get("type") == "error":
                if turn_started or set(item) != {"id", "type", "message"} \
                        or type(item.get("id")) is not str \
                        or item.get("message") != CODE_MODE_DISABLED_DIAGNOSTIC:
                    raise CodexTurnTransportError(
                        "Codex fail-closed diagnostic drift")
                diagnostics += 1
            elif item.get("type") == "agent_message" \
                    and type(item.get("text")) is str:
                if not turn_started:
                    raise CodexTurnTransportError(
                        "Codex agent-message ordering drift")
                messages.append(item["text"])
            else:
                raise CodexToolEventError("Codex tool event forbidden")
        elif event["type"] not in {
                "thread.started", "turn.started", "turn.completed"}:
            raise CodexTurnTransportError("Codex trace event forbidden")
    completed = [event for event in events if event["type"] == "turn.completed"]
    if diagnostics != 1 or not turn_started \
            or len(completed) != 1 or len(messages) != 1:
        raise CodexTurnTransportError("Codex completion telemetry drift")
    usage = completed[0].get("usage")
    if type(usage) is not dict or set(usage) != CODEX_USAGE_KEYS or any(
            isinstance(usage[key], bool) or not isinstance(usage[key], int)
            or usage[key] < 0 for key in CODEX_USAGE_KEYS):
        raise CodexTurnTransportError("Codex token telemetry drift")
    return events, {key: usage[key] for key in CODEX_USAGE_KEYS}, messages[0]


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: object, label: str) -> bytes:
    if type(value) is not str:
        raise CodexTurnTransportError(f"Codex {label} evidence drift")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise CodexTurnTransportError(
            f"Codex {label} evidence drift") from exc


def _refusal_trace_facts(raw: bytes, wall_ms: int) \
        -> tuple[dict[str, object] | None, int | None]:
    """Extract facts that remain trustworthy from an invalid provider trace."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_TRACE_BYTES:
        return None, None
    try:
        events = [_strict_json(line, "Codex refusal JSONL event")
                  for line in raw.splitlines() if line]
    except CodexTurnTransportError:
        return None, None
    if any(type(event) is not dict for event in events):
        return None, None
    tool_count = 0
    for event in events:
        if event.get("type") not in {
                "thread.started", "turn.started", "turn.completed",
                "item.completed"}:
            return None, None
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if type(item) is not dict:
            return None, None
        if item.get("type") == "error":
            if set(item) != {"id", "type", "message"} \
                    or type(item.get("id")) is not str \
                    or item.get("message") != CODE_MODE_DISABLED_DIAGNOSTIC:
                return None, None
        elif item.get("type") == "agent_message":
            if type(item.get("text")) is not str:
                return None, None
        else:
            tool_count += 1
    completed = [event for event in events
                 if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        return None, tool_count
    usage = completed[0].get("usage")
    if type(usage) is not dict or set(usage) != CODEX_USAGE_KEYS or any(
            isinstance(usage[key], bool) or not isinstance(usage[key], int)
            or usage[key] < 0 for key in CODEX_USAGE_KEYS):
        return None, tool_count
    parsed = Usage(
        usage["input_tokens"], usage["output_tokens"],
        usage["input_tokens"] + usage["output_tokens"], wall_ms,
        usage["cached_input_tokens"], usage["cache_write_input_tokens"],
        usage["reasoning_output_tokens"])
    return parsed.payload(), tool_count


def _validate_request_binding(
        request: object, schema: object, prompt: bytes,
        packet: DecisionPacket | None) -> tuple[str, ...] | None:
    request_keys = {"schema", "model", "reasoning_effort", "policy_mode",
                    "disabled_features", "packet_sha256", "memory_sha256",
                    "prompt_sha256", "output_schema_sha256",
                    "timeout_seconds"}
    if type(request) is not dict or type(schema) is not dict \
            or set(request) != request_keys \
            or request.get("schema") != "pt-luna-codex-request-v1" \
            or request.get("model") != MODEL \
            or request.get("reasoning_effort") != REASONING_EFFORT \
            or request.get("disabled_features") != list(DISABLED_FEATURES) \
            or request.get("prompt_sha256") != _sha_bytes(prompt) \
            or request.get("output_schema_sha256") != _sha(schema):
        raise CodexTurnTransportError("Codex private request derivation drift")
    policy_mode = request.get("policy_mode")
    if policy_mode not in ("free", "canary-rollout-then-play", "play-only"):
        raise CodexTurnTransportError("Codex private policy-mode drift")
    if packet is None:
        return None
    if policy_mode == "canary-rollout-then-play":
        allowed = (("rollout",) if packet.phase.phase == 1 else ("play",))
    elif policy_mode == "free":
        allowed = None
    elif policy_mode == "play-only":
        allowed = ("play",)
    if request.get("packet_sha256") != packet.sha256 \
            or request.get("memory_sha256") != packet.memory.sha256 \
            or prompt != planner_prompt(packet, policy_mode=policy_mode).encode(
                "utf-8") \
            or schema != intent_output_schema(packet, allowed_kinds=allowed):
        raise CodexTurnTransportError("Codex private packet binding drift")
    return allowed


def validate_private_refusal_evidence(
        payload: object, *, packet: DecisionPacket | None = None) \
        -> dict[str, object]:
    """Reopen exact bytes and derived usage from a refused provider result."""
    keys = {"schema", "request", "prompt_base64", "output_schema",
            "returncode", "wall_ms", "final_base64", "trace_base64",
            "stderr_base64", "trace_sha256", "stderr_sha256",
            "final_sha256", "usage", "tool_event_count",
            "evidence_sha256"}
    if type(payload) is not dict or set(payload) != keys \
            or payload.get("schema") != PRIVATE_REFUSAL_EVIDENCE_SCHEMA:
        raise CodexTurnTransportError(
            "Codex private refusal evidence schema drift")
    body = {key: value for key, value in payload.items()
            if key != "evidence_sha256"}
    if payload["evidence_sha256"] != _sha(body):
        raise CodexTurnTransportError(
            "Codex private refusal evidence seal drift")
    prompt = _unb64(payload["prompt_base64"], "refusal prompt")
    trace = _unb64(payload["trace_base64"], "refusal trace")
    stderr = _unb64(payload["stderr_base64"], "refusal stderr")
    final_value = payload["final_base64"]
    final = None if final_value is None else _unb64(
        final_value, "refusal final")
    if isinstance(payload["returncode"], bool) \
            or not isinstance(payload["returncode"], int) \
            or isinstance(payload["wall_ms"], bool) \
            or not isinstance(payload["wall_ms"], int) \
            or payload["wall_ms"] < 0 \
            or payload["trace_sha256"] != _sha_bytes(trace) \
            or payload["stderr_sha256"] != _sha_bytes(stderr) \
            or payload["final_sha256"] != (
                None if final is None else _sha_bytes(final)):
        raise CodexTurnTransportError(
            "Codex private refusal byte binding drift")
    _validate_request_binding(
        payload["request"], payload["output_schema"], prompt, packet)
    usage, tool_count = _refusal_trace_facts(trace, payload["wall_ms"])
    if payload["usage"] != usage or payload["tool_event_count"] != tool_count:
        raise CodexTurnTransportError(
            "Codex private refusal derivation drift")
    return dict(payload)


_STDERR_REFUSAL_MESSAGE_SHA256 = _sha_bytes(
    b"Codex turn stderr refused")
_COMPLETION_DRIFT_MESSAGE_SHA256 = _sha_bytes(
    b"Codex completion telemetry drift")


def _refusal_final_is_valid(payload: dict[str, object]) -> bool:
    """Check the sealed final is a play intent without returning its bytes."""
    request = payload.get("request")
    schema = payload.get("output_schema")
    final_value = payload.get("final_base64")
    if type(request) is not dict or request.get("policy_mode") != "play-only" \
            or type(schema) is not dict or final_value is None:
        return False
    try:
        final_raw = _unb64(final_value, "refusal final")
        final = _strict_json(final_raw, "Codex refusal final")
    except CodexTurnTransportError:
        return False
    if type(final) is not dict or set(final) != {
            "schema", "decision_sha256", "action"} \
            or final.get("schema") != "pt-luna-provider-intent-v2":
        return False
    properties = schema.get("properties")
    decision_schema = (None if type(properties) is not dict else
                       properties.get("decision_sha256"))
    action_schema = (None if type(properties) is not dict else
                     properties.get("action"))
    if type(decision_schema) is not dict \
            or decision_schema.get("const") != final.get("decision_sha256"):
        return False
    action_properties = (None if type(action_schema) is not dict else
                         action_schema.get("properties"))
    kind_schema = (None if type(action_properties) is not dict else
                   action_properties.get("kind"))
    candidate_schema = (None if type(action_properties) is not dict else
                        action_properties.get("candidate_index"))
    if type(action_schema) is not dict or type(kind_schema) is not dict \
            or type(candidate_schema) is not dict \
            or kind_schema.get("const") != "play":
        return False
    action = final.get("action")
    if type(action) is not dict or set(action) != {
            "kind", "candidate_index", "confidence", "planning_note"} \
            or action.get("kind") != "play" \
            or isinstance(action.get("candidate_index"), bool) \
            or not isinstance(action.get("candidate_index"), int) \
            or action["candidate_index"] < 0 \
            or action["candidate_index"] > candidate_schema.get(
                "maximum", -1) \
            or action.get("confidence") not in CONFIDENCE_LEVELS \
            or type(action.get("planning_note")) is not str \
            or len(action["planning_note"].encode("utf-8")) > 2048:
        return False
    return True


def classify_refusal_redispatch_eligibility(
        sealed_disposition: object,
        validated_private_refusal: object) -> str | None:
    """Return the sole reviewed redispatch classes, or ``None``.

    ``validated_private_refusal`` is the private payload after
    :func:`validate_private_refusal_evidence`; only its sealed scalar facts
    are inspected here.  The return value is intentionally a public class,
    never private provider bytes.
    """
    if type(sealed_disposition) is not dict \
            or type(validated_private_refusal) is not dict:
        return None
    disposition = sealed_disposition
    private = validated_private_refusal
    if disposition.get("stage") != "provider-response" \
            or disposition.get("game_deadline_fired") is not False \
            or disposition.get("call_timeout_fired") is not False:
        return None
    if private.get("returncode") != 0 \
            or isinstance(private.get("returncode"), bool) \
            or private.get("tool_event_count") != 0 \
            or isinstance(private.get("tool_event_count"), bool) \
            or not _refusal_final_is_valid(private):
        return None
    try:
        stderr = _unb64(private.get("stderr_base64"),
                        "refusal stderr")
    except CodexTurnTransportError:
        return None
    if (disposition.get("kind") == "provider-process"
            and disposition.get("exception_type")
            == "CodexProviderResourceError"
            and disposition.get("message_sha256")
            == _STDERR_REFUSAL_MESSAGE_SHA256 and stderr):
        return "stderr-nonempty"
    if (not stderr and disposition.get("kind") == "provider-schema"
            and disposition.get("exception_type")
            == "CodexTurnTransportError"
            and disposition.get("message_sha256")
            == _COMPLETION_DRIFT_MESSAGE_SHA256):
        return "completion-telemetry-drift"
    return None


def validate_private_evidence(
        payload: object, *, packet: DecisionPacket | None = None,
        response: PlannerResponse | None = None) -> dict[str, object]:
    """Independently reopen the exact provider request/final/JSONL bytes."""
    keys = {"schema", "request", "prompt_base64", "output_schema",
            "response", "final_base64", "trace_base64", "stderr_base64",
            "evidence_sha256"}
    if type(payload) is not dict or set(payload) != keys \
            or payload.get("schema") != PRIVATE_EVIDENCE_SCHEMA:
        raise CodexTurnTransportError("Codex private evidence schema drift")
    body = {key: value for key, value in payload.items()
            if key != "evidence_sha256"}
    if payload["evidence_sha256"] != _sha(body):
        raise CodexTurnTransportError("Codex private evidence seal drift")
    request = payload["request"]
    response_body = payload["response"]
    schema = payload["output_schema"]
    if type(request) is not dict or type(response_body) is not dict \
            or type(schema) is not dict:
        raise CodexTurnTransportError("Codex private evidence body drift")
    prompt = _unb64(payload["prompt_base64"], "prompt")
    final_raw = _unb64(payload["final_base64"], "final")
    trace = _unb64(payload["trace_base64"], "trace")
    stderr = _unb64(payload["stderr_base64"], "stderr")
    if stderr:
        raise CodexTurnTransportError("Codex private stderr evidence drift")
    final = _strict_json(final_raw, "Codex private final")
    _, raw_usage, message = _events_and_usage(trace)
    if _strict_json(message.encode("utf-8"), "Codex private message") != final:
        raise CodexTurnTransportError("Codex private final binding drift")
    expected_response = {
        "schema": "pt-luna-codex-response-v1",
        "final": final,
        "usage": {
            "schema": "pt-luna-usage-v1",
            "input_tokens": raw_usage["input_tokens"],
            "cached_input_tokens": raw_usage["cached_input_tokens"],
            "cache_write_input_tokens": raw_usage[
                "cache_write_input_tokens"],
            "output_tokens": raw_usage["output_tokens"],
            "reasoning_output_tokens": raw_usage[
                "reasoning_output_tokens"],
            "total_tokens": (raw_usage["input_tokens"]
                             + raw_usage["output_tokens"]),
            "wall_ms": response_body.get("usage", {}).get("wall_ms")
                if type(response_body.get("usage")) is dict else None,
        },
        "trace_sha256": _sha_bytes(trace),
        "stderr_sha256": _sha_bytes(stderr),
        "returncode": 0,
    }
    if response_body != expected_response:
        raise CodexTurnTransportError("Codex private response derivation drift")
    allowed = _validate_request_binding(request, schema, prompt, packet)
    if response is not None:
        mismatch = (response.provider_request_sha256 != _sha(request)
                    or response.provider_response_sha256 != _sha(response_body)
                    or response.usage.payload() != response_body["usage"])
        if packet is not None:
            mismatch = mismatch or _provider_intent(
                final, packet, allowed_kinds=allowed) != response.intent
        if mismatch:
            raise CodexTurnTransportError("Codex private response binding drift")
    return dict(payload)


class CodexExecPlannerTransport:
    """Make one isolated ChatGPT-authenticated Codex call per decision phase."""

    def __init__(self, *, codex_binary: Path | str = "codex",
                 model: str = MODEL,
                 reasoning_effort: str = REASONING_EFFORT,
                 timeout_seconds: int = 90,
                 temp_root: Path | None = None,
                 run_command: RunCommand = _default_run,
                 policy_mode: str = "free",
                 runtime_attestor: RuntimeAttestor = attest_codex_runtime,
                 deadline_provider: DeadlineProvider | None = None):
        binary = shutil.which(str(codex_binary)) if Path(str(codex_binary)).name == str(codex_binary) \
            else str(Path(codex_binary))
        if binary is None or not Path(binary).is_file():
            raise CodexTurnTransportError("Codex binary absent")
        if model != MODEL or reasoning_effort != REASONING_EFFORT:
            raise CodexTurnTransportError("Codex planner identity drift")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) \
                or not 1 <= timeout_seconds <= 1200:
            raise CodexTurnTransportError("Codex turn timeout drift")
        if temp_root is not None and not Path(temp_root).is_dir():
            raise CodexTurnTransportError("Codex temp root absent")
        if policy_mode not in ("free", "canary-rollout-then-play", "play-only"):
            raise CodexTurnTransportError("Codex planner policy mode drift")
        if not callable(runtime_attestor):
            raise CodexTurnTransportError("Codex runtime attestor absent")
        if deadline_provider is not None and not callable(deadline_provider):
            raise CodexTurnTransportError("Codex deadline provider absent")
        runtime = runtime_attestor(Path(binary))
        if type(runtime) is not dict \
                or runtime.get("schema") != "pt-luna-codex-tool-catalog-v1":
            raise CodexTurnTransportError("Codex runtime attestation drift")
        self.codex_binary = str(Path(binary).resolve())
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.temp_root = None if temp_root is None else Path(temp_root)
        self.run_command = run_command
        self.policy_mode = policy_mode
        self.deadline_provider = deadline_provider
        self.runtime = dict(runtime)
        self._private_evidence: dict[str, dict[str, object]] = {}
        self._private_refusal_evidence: dict[str, dict[str, object]] = {}

    def _allowed_kinds(self, packet: DecisionPacket) -> tuple[str, ...] | None:
        if self.policy_mode == "free":
            return None
        if self.policy_mode == "play-only":
            return ("play",)
        return ("rollout",) if packet.phase.phase == 1 else ("play",)

    def _command(self, *, workspace: Path, schema_path: Path,
                 final_path: Path) -> tuple[str, ...]:
        command = [
            self.codex_binary, "exec", "--json", "--ephemeral",
            "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only", "-C", str(workspace),
            "-m", self.model, "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            "--output-schema", str(schema_path),
            "--output-last-message", str(final_path),
        ]
        for feature in DISABLED_FEATURES:
            command.extend(("--disable", feature))
        command.append("-")
        return tuple(command)

    def _dispatch_deadline(self) -> tuple[int, int | None]:
        """Resolve one dispatch timeout and retain its absolute boundary."""
        if self.deadline_provider is None:
            return self.timeout_seconds, None
        try:
            deadline_ns = self.deadline_provider()
        except Exception as exc:
            raise CodexProviderResourceError(
                "Codex game deadline provider failed") from exc
        if isinstance(deadline_ns, bool) or not isinstance(deadline_ns, int):
            raise CodexProviderResourceError("Codex game deadline drift")
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns <= 0:
            raise CodexProviderResourceError(
                "Codex game deadline exceeded before dispatch")
        # The contained runner accepts seconds.  Flooring keeps its timeout
        # within the absolute game boundary; a sub-second remainder is
        # represented by zero and is handled by the runner's immediate
        # timeout path.
        timeout_seconds = min(self.timeout_seconds,
                              remaining_ns // 1_000_000_000)
        return timeout_seconds, deadline_ns

    @staticmethod
    def _check_dispatch_deadline(deadline_ns: int | None) -> None:
        if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
            raise CodexProviderResourceError(
                "Codex game deadline exceeded after dispatch")

    def call(self, packet: DecisionPacket) -> PlannerResponse:
        if type(packet) is not DecisionPacket:
            raise CodexTurnTransportError("Codex decision packet drift")
        workspace = Path(tempfile.mkdtemp(
            prefix="pt-luna-turn-", dir=self.temp_root))
        try:
            workspace.chmod(0o700)
            schema = intent_output_schema(
                packet, allowed_kinds=self._allowed_kinds(packet))
            schema_path = workspace / "intent.schema.json"
            final_path = workspace / "final.json"
            schema_path.write_bytes(canonical_json_bytes(schema))
            prompt = planner_prompt(packet, policy_mode=self.policy_mode).encode("utf-8")
            command = self._command(workspace=workspace,
                                    schema_path=schema_path,
                                    final_path=final_path)
            dispatch_timeout, dispatch_deadline = self._dispatch_deadline()
            request_body = {
                "schema": "pt-luna-codex-request-v1",
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "policy_mode": self.policy_mode,
                "disabled_features": list(DISABLED_FEATURES),
                "packet_sha256": packet.sha256,
                "memory_sha256": packet.memory.sha256,
                "prompt_sha256": _sha_bytes(prompt),
                "output_schema_sha256": _sha(schema),
                "timeout_seconds": dispatch_timeout,
            }
            result = self.run_command(
                command, prompt, workspace, dispatch_timeout)
            if type(result) is not InvocationResult:
                raise CodexTurnTransportError("Codex runner result drift")
            final_raw = None
            if final_path.is_file() and not final_path.is_symlink():
                # Preserve exact provider bytes for a refusal even when they
                # exceed the accepted-response limits.  The response path
                # still rejects oversized output; the refusal record must not
                # silently turn those bytes into an absent response.
                final_raw = final_path.read_bytes()
            raw_usage, tool_count = _refusal_trace_facts(
                result.stdout, result.wall_ms)
            refusal_body = {
                "schema": PRIVATE_REFUSAL_EVIDENCE_SCHEMA,
                "request": request_body,
                "prompt_base64": _b64(prompt),
                "output_schema": schema,
                "returncode": result.returncode,
                "wall_ms": result.wall_ms,
                "final_base64": (None if final_raw is None
                                 else _b64(final_raw)),
                "trace_base64": _b64(result.stdout),
                "stderr_base64": _b64(result.stderr),
                "trace_sha256": _sha_bytes(result.stdout),
                "stderr_sha256": _sha_bytes(result.stderr),
                "final_sha256": (None if final_raw is None
                                 else _sha_bytes(final_raw)),
                "usage": raw_usage,
                "tool_event_count": tool_count,
            }
            refusal = {**refusal_body,
                       "evidence_sha256": _sha(refusal_body)}
            validate_private_refusal_evidence(refusal, packet=packet)
            if packet.sha256 in self._private_refusal_evidence:
                raise CodexTurnTransportError(
                    "Codex private refusal packet reused")
            self._private_refusal_evidence[packet.sha256] = refusal
            # Preserve parseable usage/tool telemetry for a late provider
            # result, then refuse before response validation can return to the
            # journal or any engine transition can commit.
            self._check_dispatch_deadline(dispatch_deadline)
            if result.returncode != 0:
                raise CodexProviderResourceError("Codex turn process failed")
            if result.stderr:
                raise CodexProviderResourceError("Codex turn stderr refused")
            if not final_path.is_file() or final_path.is_symlink():
                raise CodexProviderResourceError(
                    "Codex final response absent")
            assert final_raw is not None
            final_value = _strict_json(final_raw, "Codex final response")
            _, raw_usage, message = _events_and_usage(result.stdout)
            message_value = _strict_json(message.encode("utf-8"),
                                         "Codex agent message")
            if final_value != message_value:
                raise CodexTurnTransportError("Codex final response binding drift")
            intent = _provider_intent(
                final_value, packet,
                allowed_kinds=self._allowed_kinds(packet))
            if intent.kind == "play" and intent.candidate_index >= len(packet.candidates):
                raise CodexTurnTransportError("Codex intent refused: candidate outside ballot")
            if intent.kind == "rollout" and any(
                    index >= len(packet.candidates)
                    for index in intent.candidate_indices):
                raise CodexTurnTransportError("Codex intent refused: candidate outside ballot")
            usage = Usage(
                raw_usage["input_tokens"], raw_usage["output_tokens"],
                raw_usage["input_tokens"] + raw_usage["output_tokens"],
                result.wall_ms, raw_usage["cached_input_tokens"],
                raw_usage["cache_write_input_tokens"],
                raw_usage["reasoning_output_tokens"])
            response_body = {
                "schema": "pt-luna-codex-response-v1",
                "final": final_value,
                "usage": usage.payload(),
                "trace_sha256": _sha_bytes(result.stdout),
                "stderr_sha256": _sha_bytes(result.stderr),
                "returncode": result.returncode,
            }
            response = PlannerResponse(
                intent, usage, 0, packet.team, packet.sha256,
                packet.memory.sha256, _sha(request_body), _sha(response_body))
            private_body = {
                "schema": PRIVATE_EVIDENCE_SCHEMA,
                "request": request_body,
                "prompt_base64": _b64(prompt),
                "output_schema": schema,
                "response": response_body,
                "final_base64": _b64(final_raw),
                "trace_base64": _b64(result.stdout),
                "stderr_base64": _b64(result.stderr),
            }
            private = {**private_body, "evidence_sha256": _sha(private_body)}
            validate_private_evidence(private, packet=packet, response=response)
            assert response.provider_response_sha256 is not None
            if response.provider_response_sha256 in self._private_evidence:
                raise CodexTurnTransportError(
                    "Codex private response identity reused")
            self._private_evidence[response.provider_response_sha256] = private
            return response
        finally:
            shutil.rmtree(workspace)

    def take_private_evidence(
            self, packet: DecisionPacket,
            response: PlannerResponse) -> dict[str, object]:
        key = response.provider_response_sha256
        if key is None or key not in self._private_evidence:
            raise CodexTurnTransportError("Codex private evidence absent")
        payload = self._private_evidence.pop(key)
        # The raw invocation initially remains available as a refusal record
        # so an outer absolute-deadline guard can still charge its actual
        # parseable usage. A normal accepted response consumes both views here.
        self._private_refusal_evidence.pop(packet.sha256, None)
        return validate_private_evidence(
            payload, packet=packet, response=response)

    def take_private_refusal_evidence(
            self, packet: DecisionPacket) -> dict[str, object] | None:
        if type(packet) is not DecisionPacket:
            raise CodexTurnTransportError("Codex refusal packet drift")
        payload = self._private_refusal_evidence.pop(packet.sha256, None)
        return (None if payload is None else
                validate_private_refusal_evidence(payload, packet=packet))


__all__ = [
    "CODEX_USAGE_KEYS",
    "CODE_MODE_DISABLED_DIAGNOSTIC",
    "CodexExecPlannerTransport",
    "CodexToolEventError",
    "CodexTurnTransportError",
    "DISABLED_FEATURES",
    "InvocationResult",
    "PINNED_CODEX_VERSION",
    "PRIVATE_EVIDENCE_SCHEMA",
    "PRIVATE_REFUSAL_EVIDENCE_SCHEMA",
    "attest_codex_runtime",
    "classify_refusal_redispatch_eligibility",
    "intent_output_schema",
    "planner_prompt",
    "validate_private_evidence",
    "validate_private_refusal_evidence",
]
