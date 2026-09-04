"""Strict, supervisor-owned structured turns for PT-Luna self play.

This module is deliberately transport-neutral.  A transport receives one
immutable :class:`DecisionPacket` and returns a validated structured response;
only the supervisor calls the existing Luna game/session methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import threading
from typing import Callable, Mapping, Protocol

from . import game as selfplay
from .canonical import canonical_json_bytes


SCHEMA = "privileged-teacher-luna-turn-rpc-v1"
MEMORY_SCHEMA = "pt-luna-team-memory-v1"
INTENT_SCHEMA = "pt-luna-intent-v1"
USAGE_SCHEMA = "pt-luna-usage-v1"
EVIDENCE_SCHEMA = "pt-luna-call-evidence-v1"
CONTINUATIONS = tuple(selfplay.CONTINUATIONS)
CONFIDENCE_LEVELS = tuple(selfplay.CONFIDENCE_LEVELS)


class TurnRPCError(ValueError):
    """A structured turn was refused without changing the live game."""


class TurnValidationError(TurnRPCError):
    """A planner response or supervisor input failed strict validation."""


ATTEMPT_REF_SCHEMA = "pt-luna-attempt-ref-v1"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _index(value: object, label: str = "candidate index") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TurnValidationError(f"{label} must be a non-negative integer")
    return value


def _team(value: object) -> int:
    if isinstance(value, bool) or type(value) is not int or value not in (0, 1):
        raise TurnValidationError("team must be 0 or 1")
    return int(value)


def _sha_value(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise TurnValidationError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class AttemptRef:
    """Stable identity for one provider attempt of an immutable packet."""

    logical_packet_sha256: str
    attempt_ordinal: int
    attempt_sha256: str | None = None

    def __post_init__(self) -> None:
        _sha_value(self.logical_packet_sha256, "attempt packet hash")
        if (isinstance(self.attempt_ordinal, bool)
                or not isinstance(self.attempt_ordinal, int)
                or not 0 <= self.attempt_ordinal <= 2):
            raise TurnValidationError("attempt ordinal drift")
        expected = _sha({"schema": ATTEMPT_REF_SCHEMA,
                         "logical_packet_sha256": self.logical_packet_sha256,
                         "attempt_ordinal": self.attempt_ordinal})
        if self.attempt_sha256 is None:
            object.__setattr__(self, "attempt_sha256", expected)
        elif self.attempt_sha256 != expected:
            raise TurnValidationError("attempt identity drift")

    def payload(self) -> dict[str, object]:
        return {"schema": ATTEMPT_REF_SCHEMA,
                "logical_packet_sha256": self.logical_packet_sha256,
                "attempt_ordinal": self.attempt_ordinal,
                "attempt_sha256": self.attempt_sha256}

    # These read-only aliases keep the callback surface source-compatible for
    # existing callers while the durable schema is unambiguously new.
    @property
    def packet_sha256(self) -> str:
        return self.logical_packet_sha256

    @property
    def ordinal(self) -> int:
        return self.attempt_ordinal

    @classmethod
    def from_mapping(cls, value: object) -> "AttemptRef":
        if type(value) is not dict or set(value) != {
                "schema", "logical_packet_sha256", "attempt_ordinal",
                "attempt_sha256"} \
                or value.get("schema") != ATTEMPT_REF_SCHEMA:
            raise TurnValidationError("attempt reference schema drift")
        result = cls(value["logical_packet_sha256"], value["attempt_ordinal"],
                     value["attempt_sha256"])
        if result.payload() != value:
            raise TurnValidationError("attempt reference derivation drift")
        return result


def _note(value: object, label: str = "strategy note") -> str:
    if type(value) is not str:
        raise TurnValidationError(f"{label} must be a string")
    if len(value.encode("utf-8")) > 2048:
        raise TurnValidationError(f"{label} exceeds 2048 UTF-8 bytes")
    return value


def _evidence_intent(intent: "Intent") -> dict[str, object]:
    """Keep evidence hash-bound without copying planner prose or memory text."""
    body = intent.payload(include_note=False)
    update = body.pop("memory_update", None)
    if update is not None:
        body["memory_update_sha256"] = _sha(update)
    return body


@dataclass(frozen=True)
class TeamMemory:
    team: int
    revision: int
    bound_after_state_sha256: str
    strategy_note: str = ""

    def __post_init__(self) -> None:
        _team(self.team)
        _index(self.revision, "memory revision")
        _sha_value(self.bound_after_state_sha256, "memory state hash")
        _note(self.strategy_note)

    @classmethod
    def initial(cls, team: int, state_sha256: str) -> "TeamMemory":
        return cls(_team(team), 0, _sha_value(state_sha256, "memory state hash"))

    @classmethod
    def from_mapping(cls, value: object) -> "TeamMemory":
        if type(value) is not dict or set(value) != {
                "schema", "team", "revision", "bound_after_state_sha256",
                "strategy_note"} or value.get("schema") != MEMORY_SCHEMA:
            raise TurnValidationError("team memory schema drift")
        return cls(value["team"], value["revision"],
                   value["bound_after_state_sha256"], value["strategy_note"])

    def payload(self) -> dict[str, object]:
        return {"schema": MEMORY_SCHEMA, "team": self.team,
                "revision": self.revision,
                "bound_after_state_sha256": self.bound_after_state_sha256,
                "strategy_note": self.strategy_note}

    @property
    def sha256(self) -> str:
        return _sha(self.payload())

@dataclass(frozen=True)
class PhaseContext:
    """The only legal RPC phases for one contested decision."""

    phase: int = 1
    rollout_batches: int | None = None

    def __post_init__(self) -> None:
        if type(self.phase) is not int or self.phase not in (1, 2, 3):
            raise TurnValidationError("phase must be 1, 2, or 3")
        if self.rollout_batches is None:
            object.__setattr__(self, "rollout_batches", self.phase - 1)
        elif type(self.rollout_batches) is not int \
                or self.rollout_batches != self.phase - 1:
            raise TurnValidationError("phase rollout count drift")

    @property
    def label(self) -> str:
        return f"phase{self.phase}"

    def payload(self) -> dict[str, int]:
        return {"phase": self.phase, "rollout_batches": self.rollout_batches}


@dataclass(frozen=True)
class DecisionPacket:
    coordinate: tuple[str, int, int]
    mirror: int
    team: int
    acting_seat: int
    decision_index: int
    decision_sha256: str
    state: Mapping[str, object]
    candidates: tuple[tuple[str, ...], ...]
    production_prior_index: int
    memory: TeamMemory
    phase: PhaseContext
    phase_planning_note: str = ""
    rollouts: tuple[Mapping[str, object], ...] = ()
    budget: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.coordinate) != 3:
            raise TurnValidationError("coordinate drift")
        selfplay.LunaCoordinate(*self.coordinate)
        if isinstance(self.mirror, bool) or self.mirror not in (0, 1):
            raise TurnValidationError("mirror drift")
        _team(self.team)
        if isinstance(self.acting_seat, bool) or self.acting_seat not in range(4):
            raise TurnValidationError("acting seat drift")
        _index(self.decision_index, "decision index")
        _sha_value(self.decision_sha256, "decision hash")
        try:
            selfplay._validate_snapshot(self.state)
        except Exception as exc:
            raise TurnValidationError("decision state snapshot drift") from exc
        if self.state.get("turn") != self.acting_seat \
                or self.decision_sha256 != _sha({"team": self.team,
                                                 "snapshot": self.state}):
            raise TurnValidationError("decision state binding drift")
        if self.memory.team != self.team:
            raise TurnValidationError("memory team mismatch")
        _note(self.phase_planning_note, "phase planning note")
        if type(self.state) is not dict:
            raise TurnValidationError("state must be a mapping")
        if (type(self.candidates) is not tuple or not self.candidates
                or any(type(cards) is not tuple or not cards
                       or any(type(card) is not str for card in cards)
                       for cards in self.candidates)):
            raise TurnValidationError("candidate ballot drift")
        _index(self.production_prior_index, "production prior index")
        if self.production_prior_index >= len(self.candidates):
            raise TurnValidationError("production prior outside ballot")
        if type(self.rollouts) is not tuple:
            raise TurnValidationError("rollout result shape drift")
        if (len(self.rollouts) > 2
                or len(self.rollouts) != self.phase.rollout_batches
                or any(type(row) is not dict for row in self.rollouts)):
            raise TurnValidationError("rollout result shape drift")
        engine_budget = {"rollout_calls", "rollout_calls_limit", "used",
                         "round_used", "decision_limit", "round_limit"}
        allowed_budget = engine_budget | {"model"}
        if type(self.budget) is not dict \
                or not engine_budget.issubset(self.budget) \
                or set(self.budget) - allowed_budget:
            raise TurnValidationError("decision budget schema drift")
        if any(isinstance(self.budget[key], bool)
               or not isinstance(self.budget[key], int)
               or self.budget[key] < 0 for key in engine_budget):
            raise TurnValidationError("decision engine budget drift")
        model_budget = self.budget.get("model")
        if model_budget is not None:
            model_keys = {"remaining_game_wall_ms", "remaining_game_tokens",
                          "remaining_scientific_wall_ms",
                          "remaining_scientific_tokens"}
            if type(model_budget) is not dict or set(model_budget) != model_keys \
                    or any(isinstance(model_budget[key], bool)
                           or not isinstance(model_budget[key], int)
                           or model_budget[key] < 0 for key in model_keys):
                raise TurnValidationError("decision model budget drift")

    @classmethod
    def from_observation(cls, observation: Mapping[str, object], *, coordinate,
                         mirror: int, team: int, decision_index: int,
                         memory: TeamMemory, phase: PhaseContext,
                         phase_planning_note: str = "",
                         rollouts: tuple[Mapping[str, object], ...] = ()) \
            -> "DecisionPacket":
        if type(observation) is not dict or observation.get("status") != "decision":
            raise TurnValidationError("observation is not a decision")
        candidates = observation.get("candidates")
        if (type(candidates) is not list or not candidates
                or any(type(cards) is not list for cards in candidates)):
            raise TurnValidationError("observation ballot drift")
        return cls(tuple(coordinate), mirror, team,
                   observation["acting_seat"], decision_index,
                   _sha_value(observation["decision_sha256"], "decision hash"),
                   observation["current_state"],
                   tuple(tuple(cards) for cards in candidates),
                   0, memory, phase, phase_planning_note, rollouts,
                   observation.get("budget", {}))

    @classmethod
    def from_mapping(cls, value: object) -> "DecisionPacket":
        expected = {"schema", "coordinate", "mirror", "team",
                    "agent_identity", "acting_seat", "decision_index",
                    "decision_sha256", "state", "candidates",
                    "production_prior_index", "memory", "phase",
                    "phase_planning_note", "rollouts", "budget"}
        if type(value) is not dict or set(value) != expected \
                or value.get("schema") != SCHEMA:
            raise TurnValidationError("decision packet schema drift")
        phase = value["phase"]
        if type(phase) is not dict or set(phase) != {"phase", "rollout_batches"}:
            raise TurnValidationError("decision packet phase drift")
        candidates = value["candidates"]
        rollouts = value["rollouts"]
        if type(candidates) is not list or type(rollouts) is not list:
            raise TurnValidationError("decision packet collection drift")
        packet = cls(
            tuple(value["coordinate"]), value["mirror"], value["team"],
            value["acting_seat"], value["decision_index"],
            value["decision_sha256"], value["state"],
            tuple(tuple(cards) for cards in candidates),
            value["production_prior_index"],
            TeamMemory.from_mapping(value["memory"]),
            PhaseContext(phase["phase"], phase["rollout_batches"]),
            value["phase_planning_note"], tuple(rollouts), value["budget"])
        if packet.payload() != value:
            raise TurnValidationError("decision packet derivation drift")
        return packet

    def payload(self) -> dict[str, object]:
        return {"schema": SCHEMA, "coordinate": list(self.coordinate),
                "mirror": self.mirror, "team": self.team,
                "agent_identity": self.agent_identity,
                "acting_seat": self.acting_seat,
                "decision_index": self.decision_index,
                "decision_sha256": self.decision_sha256,
                "state": self.state,
                "candidates": [list(cards) for cards in self.candidates],
                "production_prior_index": self.production_prior_index,
                "memory": self.memory.payload(), "phase": self.phase.payload(),
                "phase_planning_note": self.phase_planning_note,
                "rollouts": [dict(row) for row in self.rollouts],
                "budget": dict(self.budget)}

    @property
    def sha256(self) -> str:
        return _sha(self.payload())

    @property
    def agent_identity(self) -> int:
        return selfplay.agent_for_team(self.mirror, self.team)


@dataclass(frozen=True)
class Intent:
    kind: str
    decision_sha256: str
    candidate_index: int | None = None
    confidence: str | None = None
    candidate_indices: tuple[int, ...] = ()
    continuations: tuple[str, ...] = ()
    planning_note: str = ""
    memory_update: TeamMemory | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in ("play", "rollout"):
            raise TurnValidationError("intent kind drift")
        _sha_value(self.decision_sha256, "intent decision hash")
        _note(self.planning_note, "planning note")
        if self.kind == "play":
            _index(self.candidate_index, "candidate index")
            if self.confidence not in CONFIDENCE_LEVELS:
                raise TurnValidationError("confidence drift")
            if self.candidate_indices or self.continuations:
                raise TurnValidationError("play intent contains rollout fields")
        else:
            if self.candidate_index is not None or self.confidence is not None:
                raise TurnValidationError("rollout intent contains play fields")
            if (type(self.candidate_indices) is not tuple
                    or type(self.continuations) is not tuple
                    or not self.candidate_indices or not self.continuations
                    or any(_index(i) != i for i in self.candidate_indices)
                    or len(set(self.candidate_indices)) != len(self.candidate_indices)
                    or any(type(c) is not str or c not in CONTINUATIONS
                           for c in self.continuations)
                    or len(set(self.continuations)) != len(self.continuations)
                    or len(self.candidate_indices) * len(self.continuations) > 16):
                raise TurnValidationError("rollout batch drift")
        if self.memory_update is not None and type(self.memory_update) is not TeamMemory:
            raise TurnValidationError("memory update drift")

    @classmethod
    def from_mapping(cls, value: object) -> "Intent":
        if type(value) is not dict:
            raise TurnValidationError("intent must be an object")
        schema = value.get("schema")
        if schema != INTENT_SCHEMA:
            raise TurnValidationError("intent schema drift")
        common = {"schema", "decision_sha256", "kind", "planning_note"}
        if "planning_note" not in value:
            raise TurnValidationError("intent planning note is required")
        kind = value.get("kind")
        if kind == "play":
            allowed = common | {"candidate_index", "confidence", "memory_update"}
            if set(value) - allowed or not {"candidate_index", "confidence"} <= set(value):
                raise TurnValidationError("play intent shape drift")
            update = value.get("memory_update")
            return cls("play", value["decision_sha256"], value["candidate_index"],
                       value["confidence"], planning_note=value.get("planning_note", ""),
                       memory_update=(None if update is None else TeamMemory.from_mapping(update)))
        if kind == "rollout":
            allowed = common | {"candidate_indices", "continuations", "memory_update"}
            if set(value) - allowed or not {"candidate_indices", "continuations"} <= set(value):
                raise TurnValidationError("rollout intent shape drift")
            if (type(value["candidate_indices"]) not in (list, tuple)
                    or type(value["continuations"]) not in (list, tuple)):
                raise TurnValidationError("rollout intent shape drift")
            update = value.get("memory_update")
            return cls("rollout", value["decision_sha256"],
                       candidate_indices=tuple(value["candidate_indices"]),
                       continuations=tuple(value["continuations"]),
                       planning_note=value.get("planning_note", ""),
                       memory_update=(None if update is None else TeamMemory.from_mapping(update)))
        raise TurnValidationError("intent kind drift")

    def payload(self, *, include_note: bool = True) -> dict[str, object]:
        body: dict[str, object] = {"schema": INTENT_SCHEMA,
            "decision_sha256": self.decision_sha256, "kind": self.kind}
        if self.kind == "play":
            body.update({"candidate_index": self.candidate_index,
                         "confidence": self.confidence})
        else:
            body.update({"candidate_indices": list(self.candidate_indices),
                         "continuations": list(self.continuations)})
        if include_note:
            body["planning_note"] = self.planning_note
        if self.memory_update is not None:
            body["memory_update"] = self.memory_update.payload()
        return body


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    wall_ms: int
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    reasoning_output_tokens: int = 0

    def __post_init__(self) -> None:
        for value, label in ((self.input_tokens, "input tokens"),
                             (self.output_tokens, "output tokens"),
                             (self.total_tokens, "total tokens"),
                             (self.wall_ms, "wall milliseconds"),
                             (self.cached_input_tokens, "cached input tokens"),
                             (self.cache_write_input_tokens,
                              "cache-write input tokens"),
                             (self.reasoning_output_tokens,
                              "reasoning output tokens")):
            _index(value, label)
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise TurnValidationError("usage total mismatch")
        if self.cached_input_tokens > self.input_tokens:
            raise TurnValidationError("cached input exceeds input tokens")
        if self.reasoning_output_tokens > self.output_tokens:
            raise TurnValidationError("reasoning output exceeds output tokens")

    @classmethod
    def from_mapping(cls, value: object) -> "Usage":
        if type(value) is not dict or set(value) != {
                "schema", "input_tokens", "cached_input_tokens",
                "cache_write_input_tokens", "output_tokens",
                "reasoning_output_tokens", "total_tokens", "wall_ms"} \
                or value.get("schema") != USAGE_SCHEMA:
            raise TurnValidationError("usage is missing or malformed")
        return cls(value["input_tokens"], value["output_tokens"],
                   value["total_tokens"], value["wall_ms"],
                   value["cached_input_tokens"],
                   value["cache_write_input_tokens"],
                   value["reasoning_output_tokens"])

    def payload(self) -> dict[str, object]:
        return {"schema": USAGE_SCHEMA, "input_tokens": self.input_tokens,
                "cached_input_tokens": self.cached_input_tokens,
                "cache_write_input_tokens": self.cache_write_input_tokens,
                "output_tokens": self.output_tokens,
                "reasoning_output_tokens": self.reasoning_output_tokens,
                "total_tokens": self.total_tokens, "wall_ms": self.wall_ms}


@dataclass(frozen=True)
class PlannerResponse:
    intent: Intent
    usage: Usage
    tool_event_count: int = 0
    team: int | None = None
    packet_sha256: str | None = None
    memory_sha256: str | None = None
    provider_request_sha256: str | None = None
    provider_response_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.intent) is not Intent or type(self.usage) is not Usage:
            raise TurnValidationError("planner response types drift")
        if isinstance(self.tool_event_count, bool) or not isinstance(self.tool_event_count, int) \
                or self.tool_event_count < 0:
            raise TurnValidationError("tool-event count drift")
        if self.team is not None:
            _team(self.team)
        if self.packet_sha256 is not None:
            _sha_value(self.packet_sha256, "packet hash")
        if self.memory_sha256 is not None:
            _sha_value(self.memory_sha256, "memory hash")
        if self.provider_request_sha256 is not None:
            _sha_value(self.provider_request_sha256, "provider request hash")
        if self.provider_response_sha256 is not None:
            _sha_value(self.provider_response_sha256, "provider response hash")

    @classmethod
    def from_mapping(cls, value: object) -> "PlannerResponse":
        if type(value) is not dict or "intent" not in value or "usage" not in value:
            raise TurnValidationError("planner response missing intent or usage")
        allowed = {"intent", "usage", "tool_event_count", "team",
                   "packet_sha256", "memory_sha256",
                   "provider_request_sha256", "provider_response_sha256"}
        if set(value) - allowed:
            raise TurnValidationError("planner response shape drift")
        intent = value["intent"] if type(value["intent"]) is Intent \
            else Intent.from_mapping(value["intent"])
        usage = value["usage"] if type(value["usage"]) is Usage \
            else Usage.from_mapping(value["usage"])
        return cls(intent, usage, value.get("tool_event_count", 0),
                   value.get("team"), value.get("packet_sha256"),
                   value.get("memory_sha256"),
                   value.get("provider_request_sha256"),
                   value.get("provider_response_sha256"))


@dataclass(frozen=True)
class CallEvidence:
    team: int
    decision_index: int
    phase: int
    packet_sha256: str
    intent: Mapping[str, object]
    rollout_result: Mapping[str, object] | None
    usage: Usage
    tool_event_count: int
    before_state_sha256: str
    after_state_sha256: str
    provider_request_sha256: str
    provider_response_sha256: str

    def __post_init__(self) -> None:
        _team(self.team)
        _index(self.decision_index, "decision index")
        if type(self.phase) is not int or self.phase not in (1, 2, 3):
            raise TurnValidationError("evidence phase drift")
        _sha_value(self.packet_sha256, "packet hash")
        if type(self.intent) is not dict:
            raise TurnValidationError("evidence intent drift")
        if self.rollout_result is not None and type(self.rollout_result) is not dict:
            raise TurnValidationError("evidence rollout result drift")
        if type(self.usage) is not Usage:
            raise TurnValidationError("evidence usage drift")
        if isinstance(self.tool_event_count, bool) \
                or not isinstance(self.tool_event_count, int) \
                or self.tool_event_count < 0:
            raise TurnValidationError("evidence tool-event count drift")
        _sha_value(self.before_state_sha256, "before state hash")
        _sha_value(self.after_state_sha256, "after state hash")
        _sha_value(self.provider_request_sha256, "provider request hash")
        _sha_value(self.provider_response_sha256, "provider response hash")

    @classmethod
    def from_mapping(cls, value: object) -> "CallEvidence":
        if type(value) is not dict or set(value) != {
                "schema", "team", "decision_index", "phase", "packet_sha256",
                "prompt_sha256", "intent", "rollout_result", "usage",
                "tool_event_count", "before_state_sha256",
                "after_state_sha256", "provider_request_sha256",
                "provider_response_sha256"} or value.get("schema") != EVIDENCE_SCHEMA:
            raise TurnValidationError("evidence schema drift")
        if value["prompt_sha256"] != value["packet_sha256"]:
            raise TurnValidationError("evidence prompt binding drift")
        usage = value["usage"] if type(value["usage"]) is Usage \
            else Usage.from_mapping(value["usage"])
        return cls(value["team"], value["decision_index"], value["phase"],
                   value["packet_sha256"], value["intent"],
                   value["rollout_result"], usage,
                   value["tool_event_count"],
                   value["before_state_sha256"], value["after_state_sha256"],
                   value["provider_request_sha256"],
                   value["provider_response_sha256"])

    def payload(self) -> dict[str, object]:
        return {"schema": EVIDENCE_SCHEMA, "team": self.team,
                "decision_index": self.decision_index, "phase": self.phase,
                "packet_sha256": self.packet_sha256,
                "prompt_sha256": self.packet_sha256,
                "intent": dict(self.intent),
                "rollout_result": (None if self.rollout_result is None
                                    else dict(self.rollout_result)),
                "usage": self.usage.payload(),
                "tool_event_count": self.tool_event_count,
                "before_state_sha256": self.before_state_sha256,
                "after_state_sha256": self.after_state_sha256,
                "provider_request_sha256": self.provider_request_sha256,
                "provider_response_sha256": self.provider_response_sha256}

    @property
    def sha256(self) -> str:
        return _sha(self.payload())


class PlannerTransport(Protocol):
    def call(self, packet: DecisionPacket) -> PlannerResponse | Mapping[str, object]:
        """Return exactly one structured planner response."""


@dataclass(frozen=True)
class JournalResume:
    decision_index: int
    phase: PhaseContext
    rollouts: tuple[Mapping[str, object], ...]
    memories: Mapping[int, TeamMemory]
    phase_planning_note: str = ""
    staged_memory: TeamMemory | None = None
    evidence: tuple[CallEvidence, ...] = ()


class TurnJournal(Protocol):
    def restore(self, game: selfplay.LunaSelfPlayGame) -> JournalResume:
        """Reapply committed calls to a fresh game and return driver state."""

    def call(self, packet: DecisionPacket,
             transport: PlannerTransport, *,
             dispatch_reserver: Callable[[DecisionPacket], object] | None = None,
             attempt_reserver: Callable[[DecisionPacket, AttemptRef], object]
             | None = None,
             refusal_settler: Callable[[AttemptRef, Mapping[str, object]], object]
             | None = None,
             response_acceptor: Callable[[AttemptRef, PlannerResponse], object]
             | None = None,
             ) -> PlannerResponse | Mapping[str, object]:
        """Open/seal one provider call or replay its sealed response."""

    def commit(self, evidence: CallEvidence) -> None:
        """Durably bind the engine/rollout transition after validation."""


class TurnDriver:
    """Drive one game while keeping transport, memory, and phases supervised."""

    def __init__(self, game: selfplay.LunaSelfPlayGame,
                 transports: Mapping[int, PlannerTransport] | PlannerTransport,
                 *, journal: TurnJournal | None = None,
                 budget_provider: Callable[[], Mapping[str, object]] | None = None,
                 usage_acceptor: Callable[[Usage], object] | None = None,
                 response_acceptor: Callable[[PlannerResponse], object] | None = None,
                 dispatch_reserver: Callable[[DecisionPacket], object] | None = None,
                 attempt_reserver: Callable[[DecisionPacket, AttemptRef], object]
                 | None = None,
                 refusal_settler: Callable[[AttemptRef, Mapping[str, object]], object]
                 | None = None,
                 journal_response_acceptor: Callable[[AttemptRef, PlannerResponse], object]
                 | None = None):
        if type(game) is not selfplay.LunaSelfPlayGame:
            raise TurnRPCError("driver requires LunaSelfPlayGame")
        if isinstance(transports, Mapping):
            if set(transports) != {0, 1}:
                raise TurnRPCError("both team transports are required")
            self._transports = dict(transports)
        else:
            self._transports = {0: transports, 1: transports}
        self.game = game
        self._lock = threading.RLock()
        self._decision_index = 0
        self._phase = PhaseContext()
        self._rollouts: list[Mapping[str, object]] = []
        self._phase_planning_note = ""
        self._staged_memory: TeamMemory | None = None
        self._journal = journal
        if budget_provider is not None and not callable(budget_provider):
            raise TurnRPCError("model budget provider is not callable")
        if usage_acceptor is not None and not callable(usage_acceptor):
            raise TurnRPCError("usage acceptor is not callable")
        if response_acceptor is not None and not callable(response_acceptor):
            raise TurnRPCError("response acceptor is not callable")
        if dispatch_reserver is not None and not callable(dispatch_reserver):
            raise TurnRPCError("dispatch reserver is not callable")
        if attempt_reserver is not None and not callable(attempt_reserver):
            raise TurnRPCError("attempt reserver is not callable")
        if refusal_settler is not None and not callable(refusal_settler):
            raise TurnRPCError("refusal settler is not callable")
        if journal_response_acceptor is not None \
                and not callable(journal_response_acceptor):
            raise TurnRPCError("journal response acceptor is not callable")
        self._budget_provider = budget_provider
        self._usage_acceptor = usage_acceptor
        self._response_acceptor = response_acceptor
        self._dispatch_reserver = dispatch_reserver
        self._attempt_reserver = attempt_reserver
        self._refusal_settler = refusal_settler
        self._journal_response_acceptor = journal_response_acceptor
        self._memories: dict[int, TeamMemory] = {}
        for team in (0, 1):
            state_sha = selfplay._state_digest(game.rnd, team)
            self._memories[team] = TeamMemory.initial(team, state_sha)
        self.evidence: list[CallEvidence] = []
        if journal is not None:
            resume = journal.restore(game)
            if type(resume) is not JournalResume or set(resume.memories) != {0, 1}:
                raise TurnRPCError("journal resume state drift")
            self._decision_index = resume.decision_index
            self._phase = resume.phase
            self._rollouts = list(resume.rollouts)
            self._memories = dict(resume.memories)
            self._phase_planning_note = resume.phase_planning_note
            self._staged_memory = resume.staged_memory
            self.evidence = list(resume.evidence)

    @property
    def memories(self) -> Mapping[int, TeamMemory]:
        return dict(self._memories)

    @property
    def decision_index(self) -> int:
        """Number of validated live-engine decisions committed by this driver."""
        return self._decision_index

    def _response(self, transport: object, packet: DecisionPacket) -> PlannerResponse:
        try:
            if hasattr(transport, "call"):
                raw = transport.call(packet)  # type: ignore[attr-defined]
            elif callable(transport):
                raw = transport(packet)
            else:
                raise TurnValidationError("transport has no call seam")
        except TurnRPCError:
            raise
        except Exception as exc:
            raise TurnRPCError("planner transport exception") from exc
        return self._validate_response(raw, packet)

    @staticmethod
    def _validate_response(raw: object,
                           packet: DecisionPacket) -> PlannerResponse:
        response = raw if type(raw) is PlannerResponse else PlannerResponse.from_mapping(raw)
        if response.tool_event_count != 0:
            raise TurnValidationError("planner tool events are forbidden")
        if response.team != packet.team:
            raise TurnValidationError("planner team binding drift")
        if response.packet_sha256 != packet.sha256:
            raise TurnValidationError("packet hash binding drift")
        if response.memory_sha256 != packet.memory.sha256:
            raise TurnValidationError("memory hash binding drift")
        if response.provider_request_sha256 is None \
                or response.provider_response_sha256 is None:
            raise TurnValidationError("provider evidence binding absent")
        if response.intent.decision_sha256 != packet.decision_sha256:
            raise TurnValidationError("stale decision response")
        return response

    def step(self) -> CallEvidence | None:
        with self._lock:
            if self.game.complete or self.game.failed is not None:
                return None
            team = self.game.acting_team
            if team not in (0, 1):
                raise TurnRPCError("acting team absent")
            session = self.game.session(team)
            observed = session.observe()
            if observed.get("status") == "round_end":
                return None
            if observed.get("status") != "decision":
                raise TurnRPCError("acting session did not produce a decision")
            if self._budget_provider is not None:
                supplied = self._budget_provider()
                if type(supplied) is not dict:
                    raise TurnRPCError("model budget provider drift")
                observed = dict(observed)
                budget = dict(observed.get("budget", {}))
                budget["model"] = dict(supplied)
                observed["budget"] = budget
            memory = self._memories[team]
            packet = DecisionPacket.from_observation(
                observed, coordinate=self.game.coordinate, mirror=self.game.mirror,
                team=team, decision_index=self._decision_index,
                memory=memory, phase=self._phase,
                phase_planning_note=self._phase_planning_note,
                rollouts=tuple(self._rollouts))
            try:
                journal_settled = False
                if self._journal is None:
                    if self._dispatch_reserver is not None:
                        self._dispatch_reserver(packet)
                    response = self._response(self._transports[team], packet)
                else:
                    raw = self._journal.call(
                        packet, self._transports[team],
                        dispatch_reserver=self._dispatch_reserver,
                        attempt_reserver=self._attempt_reserver,
                        refusal_settler=self._refusal_settler,
                        response_acceptor=self._journal_response_acceptor)
                    journal_settled = self._journal_response_acceptor is not None
                    response = self._validate_response(raw, packet)
            except TurnRPCError as exc:
                self.game.fail(str(exc))
                raise
            if self._response_acceptor is not None and not journal_settled:
                try:
                    self._response_acceptor(response)
                except TurnRPCError as exc:
                    self.game.fail(str(exc))
                    raise
                except Exception as exc:
                    self.game.fail("response acceptance failed")
                    raise TurnRPCError("response acceptance failed") from exc
            if self._usage_acceptor is not None:
                try:
                    self._usage_acceptor(response.usage)
                except TurnRPCError as exc:
                    self.game.fail(str(exc))
                    raise
                except Exception as exc:
                    self.game.fail("usage acceptance failed")
                    raise TurnRPCError("usage acceptance failed") from exc
            intent = response.intent
            if intent.kind == "rollout":
                if packet.phase.phase >= 3:
                    raise TurnValidationError("third rollout batch is forbidden")
                # Validate all requested indices against this exact ballot before
                # invoking the existing session; no engine mutation occurs here.
                if any(index >= len(packet.candidates) for index in intent.candidate_indices):
                    raise TurnValidationError("candidate outside ballot")
                if intent.memory_update is not None and (
                        intent.memory_update.team != team
                        or intent.memory_update.revision != memory.revision + 1):
                    raise TurnValidationError("staged memory binding drift")
                rollout_before = selfplay._state_snapshot(self.game.rnd)
                result = session.rollout({
                    "op": "rollout", "decision_sha256": packet.decision_sha256,
                    "candidate_indices": list(intent.candidate_indices),
                    "continuations": list(intent.continuations)})
                if selfplay._state_snapshot(self.game.rnd) != rollout_before \
                        or selfplay._state_digest(self.game.rnd, team) \
                        != packet.decision_sha256:
                    raise TurnValidationError("rollout mutated live engine")
                evidence = CallEvidence(team, packet.decision_index,
                    packet.phase.phase, packet.sha256,
                    _evidence_intent(intent), result, response.usage,
                    response.tool_event_count,
                    packet.decision_sha256, packet.decision_sha256,
                    response.provider_request_sha256,
                    response.provider_response_sha256)
                self.evidence.append(evidence)
                if self._journal is not None:
                    self._journal.commit(evidence)
                self._rollouts.append(result)
                if intent.memory_update is not None:
                    self._staged_memory = intent.memory_update
                self._phase_planning_note = (
                    intent.memory_update.strategy_note
                    if intent.memory_update is not None
                    else intent.planning_note)
                self._phase = PhaseContext(self._phase.phase + 1,
                                           self._phase.rollout_batches + 1)
                return evidence
            if intent.candidate_index >= len(packet.candidates):
                raise TurnValidationError("candidate outside ballot")
            before = packet.decision_sha256
            request = {"op": "play", "decision_sha256": before,
                       "candidate_index": intent.candidate_index,
                       "confidence": intent.confidence}
            staged = intent.memory_update or self._staged_memory
            if staged is not None:
                if staged.team != team or staged.revision != memory.revision + 1:
                    raise TurnValidationError("staged memory binding drift")
                # Validate the post-play binding on a detached Round before
                # touching the live engine.  Forced opponents are part of the
                # same transition and therefore included in this preview.
                import copy
                preview = copy.deepcopy(self.game.rnd)
                preview.play(packet.acting_seat,
                             list(packet.candidates[intent.candidate_index]))
                while preview.phase == "play":
                    seat = preview.turn
                    if seat is None:
                        break
                    forced = self.game._ballots[seat]._candidates(preview, seat)
                    if len(forced) != 1:
                        break
                    preview.play(seat, list(forced[0]))
                expected_after = selfplay._state_digest(preview, team)
                if staged.bound_after_state_sha256 != expected_after:
                    raise TurnValidationError("staged memory state binding drift")
                next_memory = staged
            session.play(request)
            after = selfplay._state_digest(self.game.rnd, team)
            if staged is not None and staged.bound_after_state_sha256 != after:
                # Defensive check: a changed engine implementation must not
                # silently commit a memory bound to another transition.
                raise TurnRPCError("staged memory transition drift")
            if staged is None:
                next_memory = TeamMemory(team, memory.revision + 1, after,
                                         intent.planning_note
                                         or self._phase_planning_note
                                         or memory.strategy_note)
            # This is deliberately after session.play: invalid requests and
            # transport failures cannot alter committed team memory.
            self._memories[team] = next_memory
            session.memory = next_memory.payload()
            evidence = CallEvidence(team, packet.decision_index, packet.phase.phase,
                packet.sha256, _evidence_intent(intent), None,
                response.usage, response.tool_event_count, before, after,
                response.provider_request_sha256,
                response.provider_response_sha256)
            self.evidence.append(evidence)
            if self._journal is not None:
                self._journal.commit(evidence)
            self._decision_index += 1
            self._phase = PhaseContext()
            self._rollouts = []
            self._phase_planning_note = ""
            self._staged_memory = None
            return evidence

    def run(self, *, max_decisions: int | None = None) -> tuple[CallEvidence, ...]:
        if max_decisions is not None and (isinstance(max_decisions, bool)
                                          or not isinstance(max_decisions, int)
                                          or max_decisions < 0):
            raise TurnValidationError("max decisions drift")
        start = len(self.evidence)
        while not self.game.complete and self.game.failed is None:
            if max_decisions is not None and self._decision_index >= max_decisions:
                break
            try:
                previous = self.step()
            except (TurnRPCError, selfplay.PrivilegedTeacherLunaSelfPlayError) as exc:
                # Failure is supervisor metadata; the live Round and committed
                # team memory have not been touched by validation failures.
                self.game.fail(str(exc))
                raise
            if previous is None:
                break
        return tuple(self.evidence[start:])

    def drive(self, *, max_decisions: int | None = None) -> tuple[CallEvidence, ...]:
        """Compatibility spelling for callers treating the driver as a runner."""
        return self.run(max_decisions=max_decisions)


__all__ = ["ATTEMPT_REF_SCHEMA", "AttemptRef", "CallEvidence", "DecisionPacket", "Intent", "JournalResume",
           "MEMORY_SCHEMA",
           "PhaseContext", "PlannerResponse", "PlannerTransport", "SCHEMA",
           "TeamMemory", "TurnDriver", "TurnJournal", "TurnRPCError",
           "TurnValidationError",
           "Usage"]
