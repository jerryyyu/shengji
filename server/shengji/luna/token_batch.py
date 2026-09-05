"""Bounded, play-only batching for independent PT-Luna decisions.

This module is intentionally an opt-in transport.  It shares the contained
Codex runner and strict event parsing with :mod:`transport`, but never changes
the single-decision transport or the live Luna engine.
"""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import tempfile
from typing import Mapping, Sequence

from .canonical import canonical_json_bytes
from .transport import (
    DISABLED_FEATURES,
    CodexExecPlannerTransport,
    CodexProviderResourceError,
    CodexTurnTransportError,
    InvocationResult,
    _b64,
    _events_and_usage,
    _provider_intent,
    _refusal_trace_facts,
    _sha,
    _sha_bytes,
    _strict_json,
)
from .turn import (
    CONFIDENCE_LEVELS,
    DecisionPacket,
    Intent,
    PlannerResponse,
    TurnValidationError,
    Usage,
)


MAX_BATCH = 4
BATCH_SCHEMA = "pt-luna-provider-batch-v1"

# This schema deliberately does not depend on the number of packets or any
# packet's ballot length.  The supervisor performs those packet-bound checks.
BATCH_OUTPUT_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array", "minItems": 1, "maxItems": MAX_BATCH,
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "minimum": 0, "maximum": 3},
                    "candidate_index": {"type": "integer", "minimum": 0},
                    "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                    "planning_note": {"type": "string", "maxLength": 2048},
                },
                "required": ["slot", "candidate_index", "confidence", "planning_note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def batch_output_schema() -> dict[str, object]:
    """Return a fresh copy of the size-independent provider schema."""
    return copy.deepcopy(BATCH_OUTPUT_SCHEMA)


def _safe_b64(raw: object) -> str | None:
    return _b64(raw) if type(raw) is bytes else None

_PREFIX = """You are PT-Luna, a full-information Shengji teacher choosing play actions.
Maximize final signed-level utility for the specified team, not raw attacker
points. Candidate index 0 is the production prior. You have no tools.
Return exactly the supplied closed JSON batch schema, with one play decision
per slot. Keep each team's concise private plan attached to its own slot.
Never invent a card, candidate, state transition, or planning result; you must
play now.
These are independent unrelated games: never share information, cards, plans,
or deductions between slots. State decoder legend: state is a complete,
lossless verbatim engine snapshot; retain every field and value as supplied,
including hands, trick history, current and last trick records, and cards.

BATCH_CONTEXT_JSON
"""

COMPACT_PROMPT_PREFIX = _PREFIX


def _packets(value: object, *, label: str = "packets") -> tuple[DecisionPacket, ...]:
    if type(value) not in (list, tuple):
        raise CodexTurnTransportError(f"{label} must be a list")
    result = tuple(value)
    if not 1 <= len(result) <= MAX_BATCH:
        raise CodexTurnTransportError("batch size must be between 1 and 4")
    if any(type(packet) is not DecisionPacket for packet in result):
        raise CodexTurnTransportError("Codex decision packet drift")
    coordinates = [packet.coordinate for packet in result]
    if len(set(coordinates)) != len(coordinates):
        raise CodexTurnTransportError("batched packet coordinate reused")
    hashes = [packet.decision_sha256 for packet in result]
    if len(set(hashes)) != len(hashes):
        raise CodexTurnTransportError("batched decision hash reused")
    # Validate the play-only boundary during preflight, before any workspace
    # or provider dispatch is created.  compact_packet is defined below and
    # resolved at call time.
    for slot, packet in enumerate(result):
        compact_packet(packet, slot)
    return result


def compact_packet(packet: DecisionPacket, slot: int) -> dict[str, object]:
    """Return the model-facing, identity-free view of one play decision."""
    if type(packet) is not DecisionPacket:
        raise CodexTurnTransportError("Codex decision packet drift")
    if isinstance(slot, bool) or type(slot) is not int or not 0 <= slot < MAX_BATCH:
        raise CodexTurnTransportError("batch slot drift")
    if packet.phase.phase != 1:
        raise CodexTurnTransportError("compact batch requires phase 1")
    if packet.rollouts:
        raise CodexTurnTransportError("compact batch forbids rollout results")
    if packet.phase_planning_note:
        raise CodexTurnTransportError("compact batch forbids phase planning note")
    # Do not reinterpret or summarize state.  A deep copy prevents the prompt
    # assembly from becoming an accidental mutation path while retaining every
    # field and value exactly.
    return {
        "slot": slot,
        "team": packet.team,
        "acting_seat": packet.acting_seat,
        "state": copy.deepcopy(dict(packet.state)),
        "candidates": [list(cards) for cards in packet.candidates],
        "production_prior_index": packet.production_prior_index,
        "team_plan": packet.memory.strategy_note,
    }


def compact_prompt(packets: Sequence[DecisionPacket]) -> str:
    """Build a deterministic prompt with all variable context at its end."""
    checked = _packets(packets)
    context = [compact_packet(packet, slot) for slot, packet in enumerate(checked)]
    return _PREFIX + canonical_json_bytes(context).decode("utf-8")


def decode_batch(value: object,
                 packets: Sequence[DecisionPacket]) -> tuple[Intent, ...]:
    """Strictly decode a provider batch into packet-bound play intents."""
    checked = _packets(packets)
    if type(value) is not dict or set(value) != {"decisions"}:
        raise CodexTurnTransportError("batch response shape drift")
    decisions = value["decisions"]
    if type(decisions) is not list or len(decisions) != len(checked):
        raise CodexTurnTransportError("batch decision count drift")
    by_slot: dict[int, dict[str, object]] = {}
    expected_keys = {"slot", "candidate_index", "confidence", "planning_note"}
    for decision in decisions:
        if type(decision) is not dict or set(decision) != expected_keys:
            raise CodexTurnTransportError("batch decision shape drift")
        slot = decision["slot"]
        if isinstance(slot, bool) or type(slot) is not int or not 0 <= slot < len(checked):
            raise CodexTurnTransportError("batch slot drift")
        if slot in by_slot:
            raise CodexTurnTransportError("duplicate batch slot")
        by_slot[slot] = decision
    if set(by_slot) != set(range(len(checked))):
        raise CodexTurnTransportError("missing batch slot")
    intents: list[Intent] = []
    for slot, packet in enumerate(checked):
        decision = by_slot[slot]
        index = decision["candidate_index"]
        if isinstance(index, bool) or type(index) is not int or index < 0:
            raise CodexTurnTransportError("batch candidate index drift")
        if index >= len(packet.candidates):
            raise CodexTurnTransportError("batch candidate outside ballot")
        confidence = decision["confidence"]
        note = decision["planning_note"]
        if confidence not in CONFIDENCE_LEVELS or type(note) is not str:
            raise CodexTurnTransportError("batch play fields drift")
        if len(note.encode("utf-8")) > 2048:
            raise CodexTurnTransportError("batch planning note drift")
        final = {
            "schema": "pt-luna-provider-intent-v2",
            "decision_sha256": packet.decision_sha256,
            "action": {"kind": "play", "candidate_index": index,
                        "confidence": confidence, "planning_note": note},
        }
        intents.append(_provider_intent(final, packet, allowed_kinds=("play",)))
    return tuple(intents)


def _split(value: int, count: int, slot: int) -> int:
    return value // count + (1 if slot < value % count else 0)


def _usage(raw: Mapping[str, int], wall_ms: int, count: int, slot: int) -> Usage:
    input_tokens = _split(raw["input_tokens"], count, slot)
    cached = _split(raw["cached_input_tokens"], count, slot)
    output_tokens = _split(raw["output_tokens"], count, slot)
    reasoning = _split(raw["reasoning_output_tokens"], count, slot)
    return Usage(input_tokens, output_tokens, input_tokens + output_tokens,
                 _split(wall_ms, count, slot), cached,
                 _split(raw["cache_write_input_tokens"], count, slot), reasoning)


def _once_usage(raw: Mapping[str, int] | None,
                wall_ms: int | None) -> dict[str, object] | None:
    if raw is None or type(wall_ms) is not int or wall_ms < 0:
        return None
    try:
        return Usage(raw["input_tokens"], raw["output_tokens"],
                     raw["input_tokens"] + raw["output_tokens"], wall_ms,
                     raw["cached_input_tokens"], raw["cache_write_input_tokens"],
                     raw["reasoning_output_tokens"]).payload()
    except (KeyError, TypeError, TurnValidationError):
        # Keep the raw trace even if its usage cannot be safely charged.
        return None


class CompactBatchTransport(CodexExecPlannerTransport):
    """Opt-in one-process transport for 1–4 independent phase-one plays."""

    def __init__(self, **kwargs):
        # Force the only policy supported by this class.  The base constructor
        # still enforces the pinned model, medium reasoning, runtime attestation
        # and all normal timeout/runner invariants.
        requested = kwargs.pop("policy_mode", "play-only")
        if requested != "play-only":
            raise CodexTurnTransportError("compact batch is play-only")
        super().__init__(policy_mode="play-only", **kwargs)
        self.last_evidence: dict[str, object] | None = None

    def _record(self, **fields: object) -> None:
        self.last_evidence = fields

    def call_many(self, packets: Sequence[DecisionPacket]) -> tuple[PlannerResponse, ...]:
        # Every invocation, including local validation failures, must replace
        # the previous witness rather than leave stale accepted evidence.
        self.last_evidence = None
        try:
            checked = _packets(packets)
        except Exception as exc:
            # Preflight failures have no provider bytes, but still leave a
            # truthful refusal witness instead of retaining an older call.
            raw_packets = list(packets) if type(packets) in (list, tuple) else []
            self._record(schema=BATCH_SCHEMA,
                         packets=[(packet.payload() if type(packet) is DecisionPacket
                                   else None) for packet in raw_packets],
                         prompt_base64=None, schema_base64=None,
                         output_schema=None, final_base64=None,
                         stdout_base64=None, stderr_base64=None, raw_usage=None,
                         usage=None, wall_ms=0, accepted=False,
                         error=f"{type(exc).__name__}: {exc}")
            raise
        prompt = compact_prompt(checked).encode("utf-8")
        workspace = Path(tempfile.mkdtemp(prefix="pt-luna-batch-", dir=self.temp_root))
        schema = batch_output_schema()
        schema_path = workspace / "batch.schema.json"
        final_path = workspace / "final.json"
        result: InvocationResult | None = None
        final_raw: bytes | None = None
        raw_usage: dict[str, int] | None = None
        request_body: dict[str, object] | None = None
        try:
            workspace.chmod(0o700)
            schema_path.write_bytes(canonical_json_bytes(schema))
            dispatch_timeout, dispatch_deadline = self._dispatch_deadline()
            request_body = {
                "schema": "pt-luna-codex-batch-request-v1",
                "model": self.model, "reasoning_effort": self.reasoning_effort,
                "policy_mode": "play-only", "prompt_profile": self.prompt_profile,
                "disabled_features": list(DISABLED_FEATURES),
                "packet_sha256": [packet.sha256 for packet in checked],
                "memory_sha256": [packet.memory.sha256 for packet in checked],
                "prompt_sha256": _sha_bytes(prompt),
                "output_schema_sha256": _sha(schema),
                "timeout_seconds": dispatch_timeout,
            }
            command = self._command(workspace=workspace, schema_path=schema_path,
                                    final_path=final_path)
            result = self.run_command(command, prompt, workspace, dispatch_timeout)
            if type(result) is not InvocationResult:
                raise CodexTurnTransportError("Codex runner result drift")
            if type(result.stderr) is not bytes or len(result.stderr) > (1 << 20):
                raise CodexProviderResourceError("Codex stderr size drift")
            if final_path.is_file() and not final_path.is_symlink():
                final_raw = final_path.read_bytes()
            raw_usage, _tool_count = _refusal_trace_facts(result.stdout,
                                                          result.wall_ms)
            self._check_dispatch_deadline(dispatch_deadline)
            if result.returncode != 0:
                raise CodexProviderResourceError("Codex turn process failed")
            if final_raw is None:
                raise CodexProviderResourceError("Codex final response absent")
            final = _strict_json(final_raw, "Codex final response")
            _events, parsed_usage, message = _events_and_usage(result.stdout)
            raw_usage = parsed_usage
            if _strict_json(message.encode("utf-8"), "Codex agent message") != final:
                raise CodexTurnTransportError("Codex final response binding drift")
            intents = decode_batch(final, checked)
            provider_request_hash = _sha_bytes(canonical_json_bytes(request_body))
            response_body = {
                "schema": "pt-luna-codex-batch-response-v1",
                "final": final,
                "usage": raw_usage,
                "trace_sha256": _sha_bytes(result.stdout),
                "stderr_sha256": _sha_bytes(result.stderr),
                "returncode": result.returncode,
            }
            provider_response_hash = _sha_bytes(canonical_json_bytes(response_body))
            responses = tuple(
                PlannerResponse(intent, _usage(raw_usage, result.wall_ms,
                                               len(checked), slot), 0,
                                packet.team, packet.sha256, packet.memory.sha256,
                                provider_request_hash, provider_response_hash)
                for slot, (packet, intent) in enumerate(zip(checked, intents)))
            self._record(schema=BATCH_SCHEMA, packets=[packet.payload() for packet in checked],
                         prompt_base64=_b64(prompt),
                         schema_base64=_b64(canonical_json_bytes(schema)),
                         output_schema=schema,
                         final_base64=_b64(final_raw), stdout_base64=_safe_b64(result.stdout),
                         stderr_base64=_safe_b64(result.stderr), raw_usage=dict(raw_usage),
                         usage=_once_usage(raw_usage, result.wall_ms),
                         wall_ms=result.wall_ms, accepted=True, error=None,
                         request=request_body, provider_request_sha256=provider_request_hash,
                         provider_response_sha256=provider_response_hash,
                         usage_allocation="equal per measured component; integer remainders to lowest slots; not measured per-decision usage")
            return responses
        except Exception as exc:
            stderr = b"" if result is None else result.stderr
            stdout = b"" if result is None else result.stdout
            self._record(schema=BATCH_SCHEMA, packets=[packet.payload() for packet in checked],
                         prompt_base64=_b64(prompt),
                         schema_base64=_b64(canonical_json_bytes(schema)),
                         output_schema=schema,
                         final_base64=None if final_raw is None else _safe_b64(final_raw),
                         stdout_base64=_safe_b64(stdout), stderr_base64=_safe_b64(stderr),
                         raw_usage=raw_usage, wall_ms=0 if result is None else result.wall_ms,
                         usage=_once_usage(raw_usage, None if result is None else result.wall_ms),
                         accepted=False, error=f"{type(exc).__name__}: {exc}",
                         request=request_body)
            raise
        finally:
            shutil.rmtree(workspace)

    def call(self, packet: DecisionPacket) -> PlannerResponse:
        responses = self.call_many((packet,))
        return responses[0]


__all__ = ["BATCH_OUTPUT_SCHEMA", "BATCH_SCHEMA", "COMPACT_PROMPT_PREFIX",
           "CompactBatchTransport", "batch_output_schema", "compact_packet",
           "compact_prompt", "decode_batch"]
