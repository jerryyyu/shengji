"""Durable per-game execution for supervisor-owned PT-Luna collection.

This module owns no population choice and no scientific authority.  It turns
one already-admitted schedule item into either a fully reopenable private game
artifact or one terminal, non-retryable refusal artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Callable, Mapping, Sequence

from . import privileged_teacher_luna_selfplay as selfplay
from .privileged_teacher_luna_rpc_capacity import (
    FAILURE_KINDS,
    FAILURE_STAGES,
    NO_FAILURE_MESSAGE_SHA256,
    RPCConcurrency,
    source_identity,
)
from .privileged_teacher_luna_rpc_io import (
    AtomicPublishError, partial_path, promote_partial,
    publish_exclusive_bytes, recover_linked_partial,
)
from .privileged_teacher_luna_rpc_journal import (
    FileTurnJournal,
    SealedTurnRefusal,
    TurnJournalError,
)
from .privileged_teacher_luna_rpc_transport import (
    CodexExecPlannerTransport,
    CodexProviderResourceError,
    CodexToolEventError,
    CodexTurnTransportError,
    _default_run,
)
from .privileged_teacher_luna_turn_rpc import (
    CallEvidence,
    DecisionPacket,
    PlannerTransport,
    PlannerResponse,
    TurnDriver,
    TurnRPCError,
    TurnValidationError,
)
from .privileged_teacher_pt0 import canonical_json_bytes


ATTEMPT_SCHEMA = "pt-luna-turn-rpc-game-attempt-v1"
EVIDENCE_SCHEMA = "pt-luna-turn-rpc-game-evidence-v1"
FAILURE_SCHEMA = "pt-luna-turn-rpc-game-failure-v2"
MANIFEST_SCHEMA = "pt-luna-turn-rpc-game-manifest-v2"
SCIENTIFIC_BINDING_SCHEMA = "pt-luna-turn-rpc-scientific-attempt-binding-v1"


@dataclass(frozen=True)
class FailureDisposition:
    stage: str
    kind: str
    game_deadline_fired: bool
    call_timeout_fired: bool
    exception_type: str
    message_sha256: str
    last_opened_rpc_count: int
    last_committed_decision_count: int

    def __post_init__(self) -> None:
        if self.stage not in FAILURE_STAGES or self.stage == "none" \
                or self.kind not in FAILURE_KINDS or self.kind == "none" \
                or type(self.game_deadline_fired) is not bool \
                or type(self.call_timeout_fired) is not bool \
                or type(self.exception_type) is not str \
                or not self.exception_type \
                or type(self.message_sha256) is not str \
                or len(self.message_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in self.message_sha256) \
                or self.message_sha256 == NO_FAILURE_MESSAGE_SHA256:
            raise RPCCollectionError("game failure disposition drift")
        for value in (self.last_opened_rpc_count,
                      self.last_committed_decision_count):
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value < 0:
                raise RPCCollectionError("game failure progress drift")
        if self.last_committed_decision_count > self.last_opened_rpc_count:
            raise RPCCollectionError("game failure progress drift")

    def payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: object) -> "FailureDisposition":
        fields = set(cls.__dataclass_fields__)
        if type(value) is not dict or set(value) != fields:
            raise RPCCollectionError("game failure disposition schema drift")
        return cls(**{name: value[name] for name in fields})


class RPCCollectionError(ValueError):
    """A game attempt, resource boundary, or durable artifact was refused."""


class ResourceBoundaryError(CodexProviderResourceError):
    """A frozen resource boundary refused before an engine transition."""


class SettledResourceBoundaryError(ResourceBoundaryError):
    """A sealed provider response was charged once and refused by the ledger."""


def _failure_disposition(exc: BaseException, *, stage: str,
                         journal: FileTurnJournal) -> FailureDisposition:
    message = str(exc) or type(exc).__name__
    lowered = message.lower()
    summary = journal.summary()
    game_deadline = "game deadline" in lowered
    call_timeout = ("turn deadline" in lowered or "call timeout" in lowered)
    if game_deadline:
        kind = "game-deadline"
        if "after" in lowered:
            stage = "provider-response"
    elif call_timeout:
        kind = "call-timeout"
        stage = "provider-response"
    elif isinstance(exc, CodexToolEventError):
        stage, kind = "validation", "forbidden-tool"
    elif isinstance(exc, ResourceBoundaryError):
        stage, kind = "provider-response", "provider-process"
    elif isinstance(exc, CodexProviderResourceError):
        stage, kind = "provider-response", "provider-process"
    elif isinstance(exc, TurnJournalError):
        stage, kind = "journal-commit", "journal-io"
    elif isinstance(exc, TurnValidationError):
        engine = "engine" in lowered or "candidate" in lowered
        stage, kind = (("engine-apply", "engine-validation") if engine
                       else ("validation", "transport-validation"))
    elif isinstance(exc, CodexTurnTransportError):
        stage, kind = "provider-response", "provider-schema"
    elif isinstance(exc, TurnRPCError):
        stage, kind = "validation", "transport-validation"
    elif isinstance(exc, RPCCollectionError):
        kind = "engine-validation"
    else:
        kind = "unknown"
    return FailureDisposition(
        stage, kind, game_deadline, call_timeout, type(exc).__name__,
        hashlib.sha256(message.encode(
            "utf-8", errors="replace")).hexdigest(),
        int(summary["opened_rpc_count"]),
        int(summary["committed_decision_count"]))


class ScientificBudgetLedger:
    """Durable atomic reservations plus replay-stable provider debits."""

    def __init__(self, *, root: Path,
                 started_monotonic_nanoseconds: int,
                 wall_nanoseconds: int, token_cap: int,
                 per_call_token_reserve: int,
                 boot_identity_sha256: str,
                 runtime_sha256: str,
                 capacity_receipt_sha256: str,
                 namespace: str,
                 per_call_wall_reserve_milliseconds: int = 91_000):
        values = (started_monotonic_nanoseconds, wall_nanoseconds, token_cap,
                  per_call_token_reserve,
                  per_call_wall_reserve_milliseconds)
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value <= 0 for value in values) \
                or per_call_token_reserve > token_cap \
                or per_call_wall_reserve_milliseconds * 1_000_000 \
                > wall_nanoseconds:
            raise RPCCollectionError("scientific budget ledger drift")
        for value, label in (
                (boot_identity_sha256, "budget boot identity"),
                (runtime_sha256, "budget runtime"),
                (capacity_receipt_sha256, "budget capacity receipt")):
            _strict_sha(value, label)
        if type(namespace) is not str or not namespace \
                or len(namespace) > 256:
            raise RPCCollectionError("scientific budget namespace drift")
        self.started_ns = started_monotonic_nanoseconds
        self.wall_ns = wall_nanoseconds
        self.token_cap = token_cap
        self.reserve_tokens = per_call_token_reserve
        self.reserve_wall_ms = per_call_wall_reserve_milliseconds
        self.boot_identity_sha256 = boot_identity_sha256
        self.runtime_sha256 = runtime_sha256
        self.capacity_receipt_sha256 = capacity_receipt_sha256
        self.namespace = namespace
        self._lock = threading.Lock()
        self._reservations: set[str] = set()
        self._responses: dict[str, tuple[str, int, bool]] = {}
        self._cancelled: set[str] = set()
        self._spent_tokens = 0
        self._crossed = False
        self._events: list[dict[str, object]] = []
        self._terminal_accept: dict[str, object] | None = None
        self.root = Path(root)
        created = not self.root.exists()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_private_dir(self.root, "scientific budget ledger root")
        if created:
            _fsync_dir(self.root.parent)
        self._genesis = self._open_or_publish_genesis()
        self._last_elapsed = -1
        self._load()

    @classmethod
    def open_or_create(cls, *, root: Path, wall_nanoseconds: int,
                       token_cap: int, per_call_token_reserve: int,
                       boot_identity_sha256: str, runtime_sha256: str,
                       capacity_receipt_sha256: str, namespace: str,
                       per_call_wall_reserve_milliseconds: int) \
            -> "ScientificBudgetLedger":
        genesis_path = Path(root) / "genesis.json"
        try:
            recover_linked_partial(genesis_path)
            staged = partial_path(genesis_path)
            if not genesis_path.exists() and staged.exists():
                value = _read(staged)
                promote_partial(genesis_path, canonical_json_bytes(value))
        except (AtomicPublishError, RPCCollectionError) as exc:
            raise RPCCollectionError(
                "scientific budget genesis recovery drift") from exc
        started = (time.monotonic_ns() if not genesis_path.exists()
                   else _read(genesis_path).get(
                       "started_monotonic_nanoseconds"))
        return cls(
            root=root, started_monotonic_nanoseconds=started,
            wall_nanoseconds=wall_nanoseconds, token_cap=token_cap,
            per_call_token_reserve=per_call_token_reserve,
            per_call_wall_reserve_milliseconds=
                per_call_wall_reserve_milliseconds,
            boot_identity_sha256=boot_identity_sha256,
            runtime_sha256=runtime_sha256,
            capacity_receipt_sha256=capacity_receipt_sha256,
            namespace=namespace)

    def _genesis_body(self) -> dict[str, object]:
        return {
            "schema": "pt-luna-budget-genesis-v1",
            "started_monotonic_nanoseconds": self.started_ns,
            "wall_nanoseconds": self.wall_ns,
            "token_cap": self.token_cap,
            "per_call_token_reserve": self.reserve_tokens,
            "per_call_wall_reserve_milliseconds": self.reserve_wall_ms,
            "boot_identity_sha256": self.boot_identity_sha256,
            "runtime_sha256": self.runtime_sha256,
            "capacity_receipt_sha256": self.capacity_receipt_sha256,
            "namespace": self.namespace,
        }

    def _open_or_publish_genesis(self) -> dict[str, object]:
        body = self._genesis_body()
        expected = {**body, "genesis_sha256": _sha(body)}
        path = self.root / "genesis.json"
        if not path.exists():
            _publish(path, expected)
        value = _read(path)
        if value != expected:
            raise RPCCollectionError("scientific budget genesis drift")
        return value

    def _load(self) -> None:
        # Recover only canonical, complete immutable events.  A death before
        # link leaves one complete partial; a death after link leaves the same
        # inode under both names.  Invalid or truncated partials still refuse.
        for staged in tuple(self.root.iterdir()):
            name = staged.name
            if not (name.startswith(".") and name.endswith(".partial")):
                continue
            final_name = name[1:-len(".partial")]
            final_path = self.root / final_name
            valid_name = (final_name == "terminal-accept.json"
                          or (len(final_name) == 17
                              and final_name.endswith(".json")
                              and final_name[:-5].isdigit()))
            if not valid_name or partial_path(final_path) != staged:
                raise RPCCollectionError(
                    "scientific budget file population drift")
            try:
                if recover_linked_partial(final_path):
                    continue
                value = _read(staged)
                promote_partial(final_path, canonical_json_bytes(value))
            except (AtomicPublishError, RPCCollectionError) as exc:
                raise RPCCollectionError(
                    "scientific budget partial recovery drift") from exc
        population = {item.name for item in self.root.iterdir()}
        allowed_special = {"genesis.json", "terminal-accept.json"}
        names = sorted(name for name in population
                       if name not in allowed_special)
        expected_population = {"genesis.json", *names}
        if "terminal-accept.json" in population:
            expected_population.add("terminal-accept.json")
        if population != expected_population:
            raise RPCCollectionError("scientific budget file population drift")
        expected_names = [f"{index:012d}.json"
                          for index in range(len(names))]
        if names != expected_names:
            raise RPCCollectionError("scientific budget event population drift")
        for index, name in enumerate(names):
            event = _read(self.root / name)
            body = {key: value for key, value in event.items()
                    if key != "event_sha256"}
            keys = {"schema", "sequence", "event", "packet_sha256",
                    "provider_response_sha256", "tokens",
                    "elapsed_nanoseconds", "accepted",
                    "spent_tokens_after", "reserved_call_count_after",
                    "event_sha256"}
            if set(event) != keys \
                    or event.get("schema") != "pt-luna-budget-event-v1" \
                    or event.get("sequence") != index \
                    or event.get("event_sha256") != _sha(body):
                raise RPCCollectionError("scientific budget event drift")
            self._apply(event, reopening=True)
            self._events.append(event)
        terminal_path = self.root / "terminal-accept.json"
        if terminal_path.exists():
            terminal = _read(terminal_path)
            body = {key: value for key, value in terminal.items()
                    if key != "terminal_accept_sha256"}
            expected = {
                "schema", "elapsed_nanoseconds", "spent_tokens",
                "reserved_call_count", "crossed", "genesis_sha256",
                "event_count", "events_sha256", "terminal_accept_sha256",
            }
            if (set(terminal) != expected
                    or terminal.get("schema")
                    != "pt-luna-budget-terminal-accept-v1"
                    or terminal.get("terminal_accept_sha256") != _sha(body)
                    or terminal.get("spent_tokens") != self._spent_tokens
                    or terminal.get("reserved_call_count")
                    != len(self._reservations)
                    or terminal.get("crossed") is not self._crossed
                    or terminal.get("genesis_sha256")
                    != self._genesis["genesis_sha256"]
                    or terminal.get("event_count") != len(self._events)
                    or terminal.get("events_sha256") != _sha([
                        event["event_sha256"] for event in self._events])
                    or isinstance(terminal.get("elapsed_nanoseconds"), bool)
                    or not isinstance(terminal.get("elapsed_nanoseconds"), int)
                    or terminal["elapsed_nanoseconds"] < 0
                    or terminal["elapsed_nanoseconds"] > self.wall_ns
                    or self._reservations or self._crossed
                    or self._spent_tokens > self.token_cap):
                raise RPCCollectionError(
                    "scientific budget terminal acceptance drift")
            self._terminal_accept = terminal

    def _apply(self, event: Mapping[str, object], *, reopening: bool) -> None:
        packet = _strict_sha(event["packet_sha256"], "budget packet SHA")
        elapsed = event["elapsed_nanoseconds"]
        tokens = event["tokens"]
        if isinstance(elapsed, bool) or not isinstance(elapsed, int) \
                or elapsed < 0 or isinstance(tokens, bool) \
                or not isinstance(tokens, int) or tokens < 0:
            raise RPCCollectionError("scientific budget scalar drift")
        if elapsed < self._last_elapsed:
            raise RPCCollectionError("scientific budget clock drift")
        kind = event["event"]
        if kind == "reserve":
            projected = (self._spent_tokens
                         + (len(self._reservations) + 1)
                         * self.reserve_tokens)
            if packet in self._reservations or packet in self._responses \
                    or packet in self._cancelled \
                    or event["provider_response_sha256"] is not None \
                    or tokens != self.reserve_tokens \
                    or event["accepted"] is not True \
                    or self._crossed or projected > self.token_cap \
                    or elapsed + self.reserve_wall_ms * 1_000_000 \
                    > self.wall_ns:
                raise RPCCollectionError("scientific budget reserve drift")
            self._reservations.add(packet)
        elif kind == "settle":
            provider = _strict_sha(
                event["provider_response_sha256"], "budget response SHA")
            if packet not in self._reservations or packet in self._responses:
                raise RPCCollectionError("scientific budget settle drift")
            expected_accepted = (not self._crossed
                                 and tokens <= self.reserve_tokens
                                 and self._spent_tokens + tokens
                                 + (len(self._reservations) - 1)
                                 * self.reserve_tokens <= self.token_cap
                                 and elapsed <= self.wall_ns)
            if event["accepted"] is not expected_accepted:
                raise RPCCollectionError("scientific budget disposition drift")
            self._reservations.remove(packet)
            self._spent_tokens += tokens
            self._responses[packet] = (provider, tokens, expected_accepted)
            if not expected_accepted:
                self._crossed = True
        elif kind == "refuse":
            disposition = _strict_sha(
                event["provider_response_sha256"],
                "budget refusal disposition SHA")
            if packet not in self._reservations or packet in self._responses \
                    or event["accepted"] is not False:
                raise RPCCollectionError("scientific budget refusal drift")
            self._reservations.remove(packet)
            self._spent_tokens += tokens
            self._responses[packet] = (disposition, tokens, False)
            self._crossed = True
        elif kind == "cancel":
            if packet in self._responses \
                    or packet in self._cancelled \
                    or event["provider_response_sha256"] is not None \
                    or tokens != 0 or event["accepted"] is not False:
                raise RPCCollectionError("scientific budget cancel drift")
            self._reservations.discard(packet)
            self._cancelled.add(packet)
        else:
            raise RPCCollectionError("scientific budget event kind drift")
        if event["spent_tokens_after"] != self._spent_tokens \
                or event["reserved_call_count_after"] \
                != len(self._reservations):
            raise RPCCollectionError("scientific budget accounting drift")
        self._last_elapsed = elapsed

    def _append(self, body: Mapping[str, object]) -> None:
        sequence = len(self._events)
        event_body = {"schema": "pt-luna-budget-event-v1",
                      "sequence": sequence, **dict(body)}
        event = {**event_body, "event_sha256": _sha(event_body)}
        _publish(self.root / f"{sequence:012d}.json", event)
        self._apply(event, reopening=False)
        self._events.append(event)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            held = len(self._reservations) * self.reserve_tokens
            return {
                "remaining_scientific_wall_ms": max(
                    0, (self.wall_ns - elapsed) // 1_000_000),
                "remaining_scientific_tokens": max(
                    0, self.token_cap - self._spent_tokens - held),
            }

    def reserve(self, packet: DecisionPacket) -> None:
        if type(packet) is not DecisionPacket:
            raise ResourceBoundaryError("scientific dispatch packet drift")
        key = packet.sha256
        with self._lock:
            if self._terminal_accept is not None:
                raise ResourceBoundaryError(
                    "scientific budget already terminal")
            if key in self._responses:
                if not self._responses[key][2]:
                    raise ResourceBoundaryError("scientific budget crossed")
                return
            if key in self._cancelled:
                raise ResourceBoundaryError(
                    "scientific dispatch was already cancelled")
            if key in self._reservations:
                return
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            projected = (self._spent_tokens
                         + (len(self._reservations) + 1)
                         * self.reserve_tokens)
            if self._crossed or projected > self.token_cap \
                    or elapsed + self.reserve_wall_ms * 1_000_000 \
                    > self.wall_ns:
                raise ResourceBoundaryError(
                    "scientific dispatch reservation refused")
            self._append({
                "event": "reserve", "packet_sha256": key,
                "provider_response_sha256": None,
                "tokens": self.reserve_tokens,
                "elapsed_nanoseconds": elapsed, "accepted": True,
                "spent_tokens_after": self._spent_tokens,
                "reserved_call_count_after": len(self._reservations) + 1})

    def accept(self, response: PlannerResponse) -> None:
        if type(response) is not PlannerResponse \
                or response.packet_sha256 is None \
                or response.provider_response_sha256 is None:
            raise ResourceBoundaryError("scientific response identity drift")
        key = response.packet_sha256
        provider = response.provider_response_sha256
        tokens = response.usage.total_tokens
        with self._lock:
            prior = self._responses.get(key)
            if prior is not None:
                if prior[:2] != (provider, tokens):
                    raise ResourceBoundaryError(
                        "scientific response replay drift")
                if not prior[2]:
                    raise SettledResourceBoundaryError(
                        "scientific budget crossed")
                return
            if key not in self._reservations:
                raise ResourceBoundaryError(
                    "scientific response lacks dispatch reservation")
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            accepted = (not self._crossed and tokens <= self.reserve_tokens
                        and self._spent_tokens + tokens
                        + (len(self._reservations) - 1)
                        * self.reserve_tokens <= self.token_cap
                        and elapsed <= self.wall_ns)
            self._append({
                "event": "settle", "packet_sha256": key,
                "provider_response_sha256": provider, "tokens": tokens,
                "elapsed_nanoseconds": elapsed, "accepted": accepted,
                "spent_tokens_after": self._spent_tokens + tokens,
                "reserved_call_count_after": len(self._reservations) - 1})
            if not accepted:
                raise SettledResourceBoundaryError(
                    "scientific budget crossed")

    def refuse(self, disposition: Mapping[str, object]) -> None:
        expected = {"packet_sha256", "disposition_sha256", "total_tokens",
                    "failure_kind", "failure_class"}
        if type(disposition) is not dict or set(disposition) != expected \
                or type(disposition.get("failure_kind")) is not str \
                or disposition.get("failure_class") not in {
                    "mechanics-privacy", "resource-provider"}:
            raise ResourceBoundaryError(
                "scientific refusal disposition drift")
        packet = _strict_sha(
            disposition["packet_sha256"], "scientific refusal packet")
        evidence = _strict_sha(
            disposition["disposition_sha256"],
            "scientific refusal evidence")
        actual = disposition["total_tokens"]
        if actual is not None and (isinstance(actual, bool)
                                   or not isinstance(actual, int)
                                   or actual < 0):
            raise ResourceBoundaryError("scientific refusal usage drift")
        tokens = self.reserve_tokens if actual is None else actual
        with self._lock:
            prior = self._responses.get(packet)
            if prior is not None:
                if prior != (evidence, tokens, False):
                    raise ResourceBoundaryError(
                        "scientific refusal replay drift")
                return
            if packet not in self._reservations:
                raise ResourceBoundaryError(
                    "scientific refusal lacks dispatch reservation")
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            self._append({
                "event": "refuse", "packet_sha256": packet,
                "provider_response_sha256": evidence, "tokens": tokens,
                "elapsed_nanoseconds": elapsed, "accepted": False,
                "spent_tokens_after": self._spent_tokens + tokens,
                "reserved_call_count_after": len(self._reservations) - 1})

    def cancel(self, packet: DecisionPacket) -> None:
        """Release a reservation proven not to have launched a provider."""
        if type(packet) is not DecisionPacket:
            raise ResourceBoundaryError("scientific cancel packet drift")
        key = packet.sha256
        with self._lock:
            if key in self._cancelled:
                return
            if key in self._responses:
                raise ResourceBoundaryError(
                    "scientific settled call cannot be cancelled")
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            remaining = len(self._reservations) - int(
                key in self._reservations)
            self._append({
                "event": "cancel", "packet_sha256": key,
                "provider_response_sha256": None, "tokens": 0,
                "elapsed_nanoseconds": elapsed, "accepted": False,
                "spent_tokens_after": self._spent_tokens,
                "reserved_call_count_after": remaining})

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {"spent_tokens": self._spent_tokens,
                    "reserved_call_count": len(self._reservations),
                    "accepted_response_count": sum(
                        accepted for _, _, accepted
                        in self._responses.values()),
                    "refused_response_count": sum(
                        not accepted for _, _, accepted
                        in self._responses.values()),
                    "cancelled_dispatch_count": len(self._cancelled),
                    "crossed": self._crossed,
                    "genesis_sha256": self._genesis["genesis_sha256"],
                    "event_count": len(self._events),
                    "events_sha256": _sha([
                        event["event_sha256"] for event in self._events])}

    def is_settled(self, packet_sha256: str) -> bool:
        packet = _strict_sha(packet_sha256, "scientific settlement packet")
        with self._lock:
            return packet in self._responses

    def packet_state(self, packet_sha256: str) -> str:
        packet = _strict_sha(packet_sha256, "scientific packet state")
        with self._lock:
            if packet in self._responses:
                return "settled"
            if packet in self._reservations:
                return "reserved"
            if packet in self._cancelled:
                return "cancelled"
            return "absent"

    def reconcile_attempt_journals(self, attempts: Sequence[Path]) -> None:
        """Require a one-to-one durable journal/ledger disposition mapping."""
        expected_responses: dict[
            str, tuple[set[str], int, set[bool]]] = {}
        expected_reservations: set[str] = set()
        cancelable_refusals: set[str] = set()
        for attempt in attempts:
            journal_root = Path(attempt) / "journal"
            if not journal_root.is_dir() or journal_root.is_symlink():
                continue
            journal = FileTurnJournal(journal_root)
            groups = journal._scan()
            manifest = None
            manifest_path = Path(attempt) / "manifest.json"
            if manifest_path.is_file() and not manifest_path.is_symlink():
                manifest = _read(manifest_path)
            for group in groups:
                packet = _strict_sha(
                    group["open"]["packet_sha256"],
                    "journal ledger packet")
                if packet in expected_responses \
                        or packet in expected_reservations:
                    raise RPCCollectionError(
                        "journal ledger packet duplication")
                stages = set(group)
                if stages == {"open", "response", "commit"}:
                    response = journal._response(group)
                    expected_responses[packet] = ({
                        response.provider_response_sha256},
                        response.usage.total_tokens, {True})
                elif stages == {"open", "refusal"}:
                    refusal = journal._refusal(group)
                    tokens = (self.reserve_tokens
                              if refusal["usage"] is None
                              else refusal["usage"]["total_tokens"])
                    expected_responses[packet] = ({
                        refusal["failure_sha256"]}, tokens, {False})
                    if refusal["usage"] is None:
                        cancelable_refusals.add(packet)
                elif stages == {"open", "response"}:
                    response = journal._response(group)
                    identities = {response.provider_response_sha256}
                    if type(manifest) is dict \
                            and type(manifest.get("failure_kind")) is str \
                            and manifest.get("failure_class") in {
                                "mechanics-privacy", "resource-provider"}:
                        rejected = journal.pending_rejected_response_disposition(
                            failure_kind=manifest["failure_kind"],
                            failure_class=manifest["failure_class"])
                        if rejected is not None:
                            identities.add(rejected["disposition_sha256"])
                    expected_responses[packet] = (
                        identities, response.usage.total_tokens,
                        {True, False})
                elif stages == {"open"}:
                    expected_reservations.add(packet)
                else:
                    raise RPCCollectionError(
                        "journal ledger stage population drift")
        with self._lock:
            if self._reservations != expected_reservations \
                    or not self._cancelled.issubset(cancelable_refusals) \
                    or set(self._responses) \
                    != set(expected_responses) - self._cancelled:
                raise RPCCollectionError(
                    "journal ledger population drift")
            for packet, (identities, tokens, accepted) \
                    in expected_responses.items():
                if packet in self._cancelled:
                    continue
                actual_identity, actual_tokens, actual_accepted = \
                    self._responses[packet]
                if actual_identity not in identities \
                        or actual_tokens != tokens \
                        or actual_accepted not in accepted:
                    raise RPCCollectionError(
                        "journal ledger disposition drift")

    def assert_within_limits(self) -> None:
        """Refuse terminal publication after either scientific cap crossed."""
        with self._lock:
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            if self._crossed or self._spent_tokens > self.token_cap \
                    or elapsed > self.wall_ns:
                raise ResourceBoundaryError(
                    "scientific terminal budget crossed")

    def seal_terminal_acceptance(self) -> str:
        """Durably prove the global budget was live before terminal sealing."""
        with self._lock:
            if self._terminal_accept is not None:
                return str(self._terminal_accept["terminal_accept_sha256"])
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            if self._crossed or self._spent_tokens > self.token_cap \
                    or elapsed > self.wall_ns or self._reservations:
                raise ResourceBoundaryError(
                    "scientific terminal budget crossed")
            body = {
                "schema": "pt-luna-budget-terminal-accept-v1",
                "elapsed_nanoseconds": elapsed,
                "spent_tokens": self._spent_tokens,
                "reserved_call_count": len(self._reservations),
                "crossed": self._crossed,
                "genesis_sha256": self._genesis["genesis_sha256"],
                "event_count": len(self._events),
                "events_sha256": _sha([
                    event["event_sha256"] for event in self._events]),
            }
            terminal = {**body, "terminal_accept_sha256": _sha(body)}
            _publish(self.root / "terminal-accept.json", terminal)
            self._terminal_accept = terminal
            return terminal["terminal_accept_sha256"]

    def terminal_acceptance_sha256(self) -> str | None:
        with self._lock:
            return (None if self._terminal_accept is None else
                    str(self._terminal_accept["terminal_accept_sha256"]))


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _strict_sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RPCCollectionError(f"{label} drift")
    return value


def _publish(path: Path, payload: object, *, repair_partial: bool = False) -> None:
    raw = canonical_json_bytes(payload)
    try:
        publish_exclusive_bytes(
            path, raw, repair_incomplete_partial=repair_partial)
    except AtomicPublishError as exc:
        raise RPCCollectionError("game atomic publication drift") from exc


def _validate_private_dir(path: Path, label: str) -> None:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RPCCollectionError(f"{label} drift") from exc
    if not stat.S_ISDIR(value.st_mode) or path.is_symlink() \
            or value.st_uid != os.getuid() \
            or stat.S_IMODE(value.st_mode) != 0o700:
        raise RPCCollectionError(f"{label} drift")


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_or_verify(path: Path, payload: object) -> None:
    """Resume a deterministic post-game publish without overwriting bytes."""
    raw = canonical_json_bytes(payload)
    if path.exists():
        if canonical_json_bytes(_read(path)) != raw:
            raise RPCCollectionError("resumed game publication drift")
        return
    _publish(path, payload, repair_partial=True)


def _read(path: Path) -> dict[str, object]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            if before.st_size > 64 << 20:
                raise RPCCollectionError("game artifact size drift")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RPCCollectionError("game artifact read failed") from exc
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
            or before.st_uid != os.getuid() \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or any(getattr(before, key) != getattr(after, key)
                   for key in identity):
        raise RPCCollectionError("game artifact identity drift")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RPCCollectionError("game artifact JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RPCCollectionError("game artifact canonical bytes drift")
    return value


def _attempt_name(coordinate: tuple[str, int, int], mirror: int) -> str:
    selfplay.LunaCoordinate(*coordinate)
    if mirror not in (0, 1):
        raise RPCCollectionError("game mirror drift")
    return f"{coordinate[0]}-{coordinate[1]}-{coordinate[2]}-mirror-{mirror}"


def _terminal(payload: Mapping[str, object]) -> selfplay.TerminalReceipt:
    if type(payload) is not dict or payload.get("schema") \
            != selfplay.TERMINAL_RECEIPT_SCHEMA:
        raise RPCCollectionError("terminal receipt schema drift")
    return selfplay.TerminalReceipt(
        tuple(payload["coordinate"]), payload["mirror"],
        payload["root_sha256"], payload["trajectory_sha256"],
        payload["final_attacker_points"], payload["signed_level_utility"],
        payload["completion"], payload["receipt_sha256"],
        payload["authority"])


def _journal_hashes(root: Path) -> dict[str, str]:
    try:
        root_stat = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise RPCCollectionError("journal directory drift") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink() \
            or root_stat.st_uid != os.getuid() \
            or stat.S_IMODE(root_stat.st_mode) != 0o700:
        raise RPCCollectionError("journal directory drift")
    rows: dict[str, str] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        item = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(item.st_mode) or path.is_symlink() \
                or item.st_uid != os.getuid() or item.st_nlink != 1 \
                or stat.S_IMODE(item.st_mode) != 0o400:
            raise RPCCollectionError("journal file population drift")
        rows[path.name] = _sha_bytes(canonical_json_bytes(_read(path)))
    return rows


@dataclass(frozen=True)
class AttemptReopen:
    status: str
    manifest_sha256: str
    artifacts: selfplay.CompletedGameArtifacts | None
    failure_kind: str | None
    failure_class: str | None
    usage: Mapping[str, int]
    failure_disposition: FailureDisposition | None = None


class _Never:
    def call(self, packet):
        del packet
        raise AssertionError("reopen invoked a provider")


def reopen_attempt(
        path: Path, *, seed_secret: bytes,
        expected_runtime_sha256: str | None = None,
        expected_scientific_binding_sha256: str | None = None,
        expected_coordinate: tuple[str, int, int] | None = None,
        expected_mirror: int | None = None) \
        -> AttemptReopen:
    """Reopen one complete/refused game without a provider call."""
    path = Path(path)
    _validate_private_dir(path, "game attempt directory")
    attempt = _read(path / "attempt.json")
    manifest = _read(path / "manifest.json")
    if set(attempt) != {"schema", "coordinate", "mirror", "root_sha256",
                       "seed_commitment_sha256", "runtime_sha256",
                       "boot_identity_sha256",
                       "scientific_binding_sha256",
                       "started_monotonic_nanoseconds",
                       "per_game_deadline_nanoseconds", "per_game_token_cap",
                       "per_call_token_reserve",
                       "per_call_wall_reserve_milliseconds",
                       "authority", "attempt_sha256"} \
            or attempt["schema"] != ATTEMPT_SCHEMA:
        raise RPCCollectionError("game attempt schema drift")
    attempt_body = {key: value for key, value in attempt.items()
                    if key != "attempt_sha256"}
    if attempt["attempt_sha256"] != _sha(attempt_body) \
            or hashlib.sha256(seed_secret).hexdigest() \
            != attempt["seed_commitment_sha256"]:
        raise RPCCollectionError("game attempt seal drift")
    _strict_sha(attempt["boot_identity_sha256"], "game boot identity")
    if isinstance(attempt["started_monotonic_nanoseconds"], bool) \
            or not isinstance(attempt["started_monotonic_nanoseconds"], int) \
            or attempt["started_monotonic_nanoseconds"] <= 0:
        raise RPCCollectionError("game start clock drift")
    coordinate = tuple(attempt["coordinate"])
    mirror = attempt["mirror"]
    selfplay.LunaCoordinate(*coordinate)
    if (expected_coordinate is None) != (expected_mirror is None):
        raise RPCCollectionError("game expected identity population drift")
    if expected_coordinate is not None:
        if type(expected_coordinate) is not tuple \
                or tuple(expected_coordinate) != coordinate \
                or type(expected_mirror) is not int \
                or expected_mirror != mirror:
            raise RPCCollectionError("game scheduled identity drift")
    if expected_runtime_sha256 is not None \
            and attempt["runtime_sha256"] != expected_runtime_sha256:
        raise RPCCollectionError("game runtime binding drift")
    if attempt["scientific_binding_sha256"] \
            != expected_scientific_binding_sha256:
        raise RPCCollectionError("game scientific binding drift")
    root = selfplay.build_root(seed_secret, coordinate, mirror=mirror)
    if selfplay.root_identity(root) != attempt["root_sha256"]:
        raise RPCCollectionError("game root binding drift")
    manifest_keys = {"schema", "status", "coordinate", "mirror",
                     "attempt_sha256", "runtime_sha256", "files",
                     "journal_files", "journal_summary", "usage",
                     "failure_kind", "failure_class",
                     "failure_disposition", "authority",
                     "manifest_sha256"}
    if set(manifest) != manifest_keys or manifest["schema"] != MANIFEST_SCHEMA:
        raise RPCCollectionError("game manifest schema drift")
    manifest_body = {key: value for key, value in manifest.items()
                     if key != "manifest_sha256"}
    if manifest["manifest_sha256"] != _sha(manifest_body) \
            or manifest["coordinate"] != list(coordinate) \
            or manifest["mirror"] != mirror \
            or manifest["attempt_sha256"] != attempt["attempt_sha256"] \
            or manifest["runtime_sha256"] != attempt["runtime_sha256"] \
            or manifest["authority"] != selfplay.AUTHORITY:
        raise RPCCollectionError("game manifest binding drift")
    files = manifest["files"]
    if type(files) is not dict:
        raise RPCCollectionError("game file manifest drift")
    expected_entries = {"attempt.json", "journal", "manifest.json", *files}
    if {item.name for item in path.iterdir()} != expected_entries:
        raise RPCCollectionError("game artifact population drift")
    opened_files: dict[str, dict[str, object]] = {}
    for name, digest in files.items():
        _strict_sha(digest, "game file SHA")
        opened = _read(path / name)
        opened_files[name] = opened
        if _sha_bytes(canonical_json_bytes(opened)) != digest:
            raise RPCCollectionError("game file hash drift")
    journal = FileTurnJournal(path / "journal")
    if _journal_hashes(path / "journal") != manifest["journal_files"] \
            or journal.summary() != manifest["journal_summary"] \
            or journal.usage_totals() != manifest["usage"]:
        raise RPCCollectionError("game journal manifest drift")
    game = selfplay.LunaSelfPlayGame(
        root, coordinate=coordinate, mirror=mirror, seed_secret=seed_secret)
    driver = TurnDriver(game, _Never(), journal=journal)
    if manifest["status"] == "complete":
        if set(files) != {"attempt.json", "evidence.json", "trajectory.json",
                         "terminal.json"} \
                or manifest["failure_kind"] is not None \
                or manifest["failure_class"] is not None \
                or manifest["failure_disposition"] is not None \
                or not game.complete or game.failed is not None:
            raise RPCCollectionError("complete game manifest drift")
        evidence = opened_files["evidence.json"]
        if set(evidence) != {"schema", "rows", "evidence_sha256"} \
                or evidence["schema"] != EVIDENCE_SCHEMA \
                or evidence["evidence_sha256"] != _sha({
                    "schema": EVIDENCE_SCHEMA, "rows": evidence["rows"]}) \
                or evidence["rows"] != [row.payload()
                                         for row in driver.evidence]:
            raise RPCCollectionError("game evidence derivation drift")
        trajectory = selfplay.SealedTrajectory.reopen(
            canonical_json_bytes(opened_files["trajectory.json"]))
        terminal = _terminal(opened_files["terminal.json"])
        artifacts = selfplay.CompletedGameArtifacts(trajectory, terminal)
        if artifacts.trajectory.body["coordinate"] != list(coordinate) \
                or artifacts.trajectory.body["mirror"] != mirror:
            raise RPCCollectionError("game artifact coordinate drift")
        return AttemptReopen(
            "complete", manifest["manifest_sha256"], artifacts, None, None,
            dict(manifest["usage"]))
    if manifest["status"] != "incomplete" \
            or not {"attempt.json", "failure.json"}.issubset(files) \
            or set(files) - {"attempt.json", "failure.json", "evidence.json",
                             "trajectory.json", "terminal.json"} \
            or type(manifest["failure_kind"]) is not str \
            or manifest["failure_class"] not in {
                "mechanics-privacy", "resource-provider"} \
            or type(manifest["failure_disposition"]) is not dict:
        raise RPCCollectionError("incomplete game manifest drift")
    disposition = FailureDisposition.from_mapping(
        manifest["failure_disposition"])
    failure = opened_files["failure.json"]
    if set(failure) != {"schema", "coordinate", "mirror", "failure_kind",
                       "failure_class", "failure_fingerprint_sha256",
                       "failure_disposition",
                       "journal_summary_sha256",
                       "authority", "artifact_sha256"} \
            or failure["schema"] != FAILURE_SCHEMA \
            or failure["coordinate"] != list(coordinate) \
            or failure["mirror"] != mirror \
            or failure["failure_kind"] != manifest["failure_kind"] \
            or failure["failure_class"] != manifest["failure_class"] \
            or failure["failure_disposition"] != disposition.payload() \
            or failure["failure_fingerprint_sha256"] != _sha({
                "failure_kind": failure["failure_kind"],
                "failure_class": failure["failure_class"],
                "failure_disposition": disposition.payload()}) \
            or failure["journal_summary_sha256"] \
            != _sha(manifest["journal_summary"]) \
            or failure["authority"] != selfplay.AUTHORITY:
        raise RPCCollectionError("game failure binding drift")
    failure_body = {key: value for key, value in failure.items()
                    if key != "artifact_sha256"}
    if failure["artifact_sha256"] != _sha(failure_body):
        raise RPCCollectionError("game failure seal drift")
    return AttemptReopen(
        "incomplete", manifest["manifest_sha256"], None,
        manifest["failure_kind"], manifest["failure_class"],
        dict(manifest["usage"]), disposition)


class _CountingRun:
    def __init__(self, concurrency: RPCConcurrency):
        self.concurrency = concurrency
        from .privileged_teacher_luna_rpc_transport import ActiveCallManager
        self.active_calls = ActiveCallManager()

    def __call__(self, command, prompt, workspace, timeout_seconds):
        self.concurrency.enter()
        try:
            return _default_run(
                command, prompt, workspace, timeout_seconds,
                _active_call_manager=self.active_calls)
        finally:
            self.concurrency.leave()


TransportFactory = Callable[[Path], PlannerTransport]


class _DeadlineTransport:
    """Game-owned absolute boundary around both real and injected transports."""

    def __init__(self, inner: PlannerTransport,
                 deadline_provider: Callable[[], int],
                 event_callback: Callable[[str], object] | None = None,
                 configure_inner_deadline: bool = True):
        self.inner = inner
        self.deadline_provider = deadline_provider
        self.event_callback = event_callback
        if configure_inner_deadline and hasattr(inner, "deadline_provider"):
            setattr(inner, "deadline_provider", deadline_provider)

    def call(self, packet: DecisionPacket):
        deadline = self.deadline_provider()
        if time.monotonic_ns() >= deadline:
            raise ResourceBoundaryError(
                "game deadline exceeded before dispatch")
        if self.event_callback is not None:
            self.event_callback("rpc-start")
        try:
            response = self.inner.call(packet)
        finally:
            if self.event_callback is not None:
                self.event_callback("rpc-end")
        if time.monotonic_ns() >= deadline:
            raise ResourceBoundaryError(
                "game deadline exceeded after provider response")
        return response

    def take_private_evidence(self, packet, response):
        take = getattr(self.inner, "take_private_evidence", None)
        return None if take is None else take(packet, response)

    def take_private_refusal_evidence(self, packet):
        take = getattr(self.inner, "take_private_refusal_evidence", None)
        return None if take is None else take(packet)


class RPCGameAttemptRunner:
    """Run/resume one schedule item and seal it exactly once."""

    def __init__(
            self, *, seed_secret: bytes, attempts_root: Path,
            codex_binary: Path | None, runtime: Mapping[str, object],
            per_game_deadline_seconds: int, per_game_token_cap: int,
            concurrency: RPCConcurrency | None = None,
            stop_event: threading.Event | None = None,
            scientific_budget_provider: Callable[[], Mapping[str, int]] | None = None,
            scientific_response_acceptor: Callable[[object], object] | None = None,
            scientific_dispatch_reserver: Callable[[DecisionPacket], object] | None = None,
            scientific_refusal_acceptor: Callable[[Mapping[str, object]], object] | None = None,
            scientific_terminal_acceptor: Callable[[], object] | None = None,
            per_call_token_reserve: int = 1,
            per_call_wall_reserve_milliseconds: int = 91_000,
            scientific_binding: Mapping[str, object] | None = None,
            transport_factory: TransportFactory | None = None,
            progress_callback: Callable[[Mapping[str, object]], object]
            | None = None):
        if type(seed_secret) is not bytes or len(seed_secret) != 32:
            raise RPCCollectionError("collection seed secret drift")
        if isinstance(per_game_deadline_seconds, bool) \
                or not isinstance(per_game_deadline_seconds, int) \
                or per_game_deadline_seconds <= 90 \
                or isinstance(per_game_token_cap, bool) \
                or not isinstance(per_game_token_cap, int) \
                or per_game_token_cap <= 0 \
                or isinstance(per_call_token_reserve, bool) \
                or not isinstance(per_call_token_reserve, int) \
                or not 0 < per_call_token_reserve <= per_game_token_cap \
                or isinstance(per_call_wall_reserve_milliseconds, bool) \
                or not isinstance(per_call_wall_reserve_milliseconds, int) \
                or not 1_000 <= per_call_wall_reserve_milliseconds \
                <= 1_200_999 \
                or per_call_wall_reserve_milliseconds * 1_000_000 \
                >= per_game_deadline_seconds * 1_000_000_000:
            raise RPCCollectionError("collection game budget drift")
        if type(runtime) is not dict \
                or runtime.get("schema") != "pt-luna-turn-rpc-runtime-v1" \
                or _strict_sha(runtime.get("boot_identity_sha256"),
                               "collection boot identity") \
                != runtime.get("boot_identity_sha256"):
            raise RPCCollectionError("collection runtime drift")
        self.seed_secret = seed_secret
        self.attempts_root = Path(attempts_root)
        self.attempts_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_private_dir(self.attempts_root, "collection attempt root")
        self.runtime = dict(runtime)
        self.runtime_sha256 = _sha(runtime)
        if scientific_binding is None:
            self.scientific_binding = None
            self.scientific_binding_sha256 = None
        else:
            expected_binding_keys = {
                "schema", "freeze_sha256", "admission_sha256",
                "capacity_receipt_sha256", "runtime_sha256",
                "ledger_genesis_sha256", "namespace"}
            if type(scientific_binding) is not dict \
                    or set(scientific_binding) != expected_binding_keys \
                    or scientific_binding.get("schema") \
                    != SCIENTIFIC_BINDING_SCHEMA \
                    or type(scientific_binding.get("namespace")) is not str \
                    or not scientific_binding["namespace"]:
                raise RPCCollectionError("scientific attempt binding drift")
            for name in expected_binding_keys - {"schema", "namespace"}:
                _strict_sha(scientific_binding[name],
                            "scientific attempt binding")
            self.scientific_binding = dict(scientific_binding)
            self.scientific_binding_sha256 = _sha(scientific_binding)
        self.per_game_deadline_ns = per_game_deadline_seconds * 1_000_000_000
        self.per_game_token_cap = per_game_token_cap
        self.per_call_token_reserve = per_call_token_reserve
        self.per_call_wall_reserve_milliseconds = \
            per_call_wall_reserve_milliseconds
        self.per_call_timeout_seconds = (
            per_call_wall_reserve_milliseconds // 1_000)
        self.concurrency = concurrency or RPCConcurrency()
        self.stop_event = stop_event or threading.Event()
        if progress_callback is not None and not callable(progress_callback):
            raise RPCCollectionError("collection progress callback drift")
        self.progress_callback = progress_callback
        self.scientific_budget_provider = scientific_budget_provider
        if scientific_response_acceptor is not None \
                and not callable(scientific_response_acceptor):
            raise RPCCollectionError("scientific response acceptor drift")
        if scientific_dispatch_reserver is not None \
                and not callable(scientific_dispatch_reserver):
            raise RPCCollectionError("scientific dispatch reserver drift")
        if scientific_refusal_acceptor is not None \
                and not callable(scientific_refusal_acceptor):
            raise RPCCollectionError("scientific refusal acceptor drift")
        if scientific_terminal_acceptor is not None \
                and not callable(scientific_terminal_acceptor):
            raise RPCCollectionError("scientific terminal acceptor drift")
        supplied = (scientific_budget_provider is not None,
                    scientific_response_acceptor is not None,
                    scientific_dispatch_reserver is not None,
                    scientific_refusal_acceptor is not None,
                    scientific_terminal_acceptor is not None)
        if any(supplied) and not all(supplied):
            raise RPCCollectionError("scientific budget callback population drift")
        self.scientific_response_acceptor = scientific_response_acceptor
        self.scientific_dispatch_reserver = scientific_dispatch_reserver
        self.scientific_refusal_acceptor = scientific_refusal_acceptor
        self.scientific_terminal_acceptor = scientific_terminal_acceptor
        self.codex_binary: Path | None = None
        self.active_call_manager = None
        if transport_factory is None:
            if codex_binary is None \
                    or source_identity(Path(codex_binary)) != dict(runtime):
                raise RPCCollectionError("collection live runtime drift")
            self.codex_binary = Path(codex_binary).resolve()
            catalog = dict(runtime["codex_tool_catalog"])
            counted = _CountingRun(self.concurrency)
            self.active_call_manager = counted.active_calls
            self.transport_factory = lambda temp: CodexExecPlannerTransport(
                codex_binary=Path(codex_binary), temp_root=temp,
                timeout_seconds=self.per_call_timeout_seconds,
                run_command=counted, runtime_attestor=lambda _: dict(catalog))
        else:
            self.transport_factory = transport_factory

    def terminate_active_calls(self) -> None:
        if self.active_call_manager is not None:
            self.active_call_manager.terminate()

    def _emit_progress(self, event: str, journal: FileTurnJournal,
                       absolute_deadline_ns: int) -> None:
        if self.progress_callback is None:
            return
        summary = journal.summary()
        self.progress_callback({
            "event": event,
            "opened_rpc_count": summary["opened_rpc_count"],
            "committed_decision_count": summary[
                "committed_decision_count"],
            "remaining_game_deadline_seconds": max(
                0, absolute_deadline_ns - time.monotonic_ns())
                // 1_000_000_000,
        })

    def _attempt_body(self, coordinate, mirror, root_sha, started):
        body = {"schema": ATTEMPT_SCHEMA, "coordinate": list(coordinate),
                "mirror": mirror, "root_sha256": root_sha,
                "seed_commitment_sha256": hashlib.sha256(
                    self.seed_secret).hexdigest(),
                "runtime_sha256": self.runtime_sha256,
                "boot_identity_sha256": self.runtime["boot_identity_sha256"],
                "scientific_binding_sha256":
                    self.scientific_binding_sha256,
                "started_monotonic_nanoseconds": started,
                "per_game_deadline_nanoseconds": self.per_game_deadline_ns,
                "per_game_token_cap": self.per_game_token_cap,
                "per_call_token_reserve": self.per_call_token_reserve,
                "per_call_wall_reserve_milliseconds":
                    self.per_call_wall_reserve_milliseconds,
                "authority": dict(selfplay.AUTHORITY)}
        return {**body, "attempt_sha256": _sha(body)}

    def _model_budget(self, journal: FileTurnJournal,
                      started: int) -> dict[str, int]:
        usage = journal.usage_totals()
        elapsed = max(0, time.monotonic_ns() - started)
        scientific = (self.scientific_budget_provider()
                      if self.scientific_budget_provider is not None else {
                          "remaining_scientific_wall_ms": max(
                              0, (self.per_game_deadline_ns - elapsed)
                              // 1_000_000),
                          "remaining_scientific_tokens": max(
                              0, self.per_game_token_cap
                              - usage["total_tokens"])})
        return {
            "remaining_game_wall_ms": max(
                0, (self.per_game_deadline_ns - elapsed) // 1_000_000),
            "remaining_game_tokens": max(
                0, self.per_game_token_cap - usage["total_tokens"]),
            "remaining_scientific_wall_ms": int(
                scientific["remaining_scientific_wall_ms"]),
            "remaining_scientific_tokens": int(
                scientific["remaining_scientific_tokens"]),
        }

    def _manifest(self, path: Path, *, status: str,
                  failure_kind: str | None,
                  failure_class: str | None,
                  failure_disposition: FailureDisposition | None = None) \
            -> dict[str, object]:
        attempt = _read(path / "attempt.json")
        files = {
            item.name: _sha_bytes(canonical_json_bytes(_read(item)))
            for item in path.iterdir()
            if item.name != "manifest.json" and not item.is_dir()}
        journal = FileTurnJournal(path / "journal")
        body = {"schema": MANIFEST_SCHEMA, "status": status,
                "coordinate": attempt["coordinate"],
                "mirror": attempt["mirror"],
                "attempt_sha256": attempt["attempt_sha256"],
                "runtime_sha256": attempt["runtime_sha256"],
                "files": files,
                "journal_files": _journal_hashes(path / "journal"),
                "journal_summary": journal.summary(),
                "usage": journal.usage_totals(),
                "failure_kind": failure_kind,
                "failure_class": failure_class,
                "failure_disposition": (None if failure_disposition is None
                                        else failure_disposition.payload()),
                "authority": dict(selfplay.AUTHORITY)}
        return {**body, "manifest_sha256": _sha(body)}

    def _seal_failure(self, path: Path, coordinate, mirror,
                      exc: Exception, *, stage: str) -> None:
        if (path / "manifest.json").exists():
            return
        journal = FileTurnJournal(path / "journal")
        refusal = journal.pending_refusal_disposition()
        persisted_disposition = \
            journal.pending_refusal_failure_disposition()
        if persisted_disposition is None:
            disposition = _failure_disposition(
                exc, stage=stage, journal=journal)
        else:
            progress = journal.summary()
            disposition = FailureDisposition.from_mapping({
                **persisted_disposition,
                "last_opened_rpc_count": int(
                    progress["opened_rpc_count"]),
                "last_committed_decision_count": int(
                    progress["committed_decision_count"]),
            })
        if refusal is not None:
            kind = refusal["failure_kind"]
            failure_class = refusal["failure_class"]
        elif isinstance(exc, SealedTurnRefusal):
            kind = exc.failure_kind
            failure_class = exc.failure_class
        else:
            kind = type(exc).__name__
            failure_class = ("resource-provider"
                             if isinstance(exc, ResourceBoundaryError)
                             or isinstance(exc, CodexProviderResourceError)
                             else "mechanics-privacy")
        if refusal is None:
            refusal = journal.pending_rejected_response_disposition(
                failure_kind=kind, failure_class=failure_class)
        if refusal is None:
            refusal = journal.seal_unknown_disposition()
            if refusal is not None:
                kind = refusal["failure_kind"]
                failure_class = refusal["failure_class"]
        response_acceptor_owner = getattr(
            self.scientific_response_acceptor, "__self__", None)
        ledger_state = None
        if refusal is not None and isinstance(
                response_acceptor_owner, ScientificBudgetLedger):
            ledger_state = response_acceptor_owner.packet_state(
                refusal["packet_sha256"])
        already_settled = (
            isinstance(exc, SettledResourceBoundaryError)
            or (ledger_state is not None and ledger_state != "reserved"))
        if refusal is not None and self.scientific_refusal_acceptor is not None \
                and not already_settled:
            self.scientific_refusal_acceptor(refusal)
        body = {"schema": FAILURE_SCHEMA, "coordinate": list(coordinate),
                "mirror": mirror, "failure_kind": kind,
                "failure_class": failure_class,
                "failure_disposition": disposition.payload(),
                "failure_fingerprint_sha256": _sha({
                    "failure_kind": kind, "failure_class": failure_class,
                    "failure_disposition": disposition.payload()}),
                "journal_summary_sha256": _sha(journal.summary()),
                "authority": dict(selfplay.AUTHORITY)}
        _publish_or_verify(path / "failure.json",
                           {**body, "artifact_sha256": _sha(body)})
        _publish_or_verify(path / "manifest.json", self._manifest(
            path, status="incomplete", failure_kind=kind,
            failure_class=failure_class,
            failure_disposition=disposition))

    def _finish_interrupted_failure(self, path: Path, coordinate, mirror) \
            -> None:
        """Finish only the manifest half of an already sealed failure."""
        failure = _read(path / "failure.json")
        keys = {"schema", "coordinate", "mirror", "failure_kind",
                "failure_class", "failure_fingerprint_sha256",
                "failure_disposition",
                "journal_summary_sha256", "authority", "artifact_sha256"}
        body = {key: value for key, value in failure.items()
                if key != "artifact_sha256"}
        if set(failure) != keys or failure.get("schema") != FAILURE_SCHEMA \
                or failure.get("coordinate") != list(coordinate) \
                or failure.get("mirror") != mirror \
                or failure.get("authority") != selfplay.AUTHORITY \
                or failure.get("failure_class") not in {
                    "mechanics-privacy", "resource-provider"} \
                or FailureDisposition.from_mapping(
                    failure.get("failure_disposition")).payload() \
                    != failure.get("failure_disposition") \
                or failure.get("failure_fingerprint_sha256") != _sha({
                    "failure_kind": failure.get("failure_kind"),
                    "failure_class": failure.get("failure_class"),
                    "failure_disposition": failure.get(
                        "failure_disposition")}) \
                or failure.get("artifact_sha256") != _sha(body) \
                or failure.get("journal_summary_sha256") != _sha(
                    FileTurnJournal(path / "journal").summary()):
            raise RPCCollectionError("interrupted game failure drift")
        _publish_or_verify(path / "manifest.json", self._manifest(
            path, status="incomplete",
            failure_kind=failure["failure_kind"],
            failure_class=failure["failure_class"],
            failure_disposition=FailureDisposition.from_mapping(
                failure["failure_disposition"])))

    def __call__(self, coordinate: tuple[str, int, int], mirror: int) \
            -> selfplay.CompletedGameArtifacts:
        try:
            return self._run_game(coordinate, mirror)
        except BaseException:
            self.stop_event.set()
            raise

    def _run_game(self, coordinate: tuple[str, int, int], mirror: int) \
            -> selfplay.CompletedGameArtifacts:
        name = _attempt_name(coordinate, mirror)
        path = self.attempts_root / name
        if path.exists() or path.is_symlink():
            _validate_private_dir(path, "game attempt directory")
        if (path / "manifest.json").is_file():
            result = reopen_attempt(
                path, seed_secret=self.seed_secret,
                expected_runtime_sha256=self.runtime_sha256,
                expected_scientific_binding_sha256=
                    self.scientific_binding_sha256,
                expected_coordinate=coordinate, expected_mirror=mirror)
            if result.artifacts is None:
                self.stop_event.set()
                raise RPCCollectionError("sealed game attempt is incomplete")
            return result.artifacts
        if self.stop_event.is_set() and not path.exists():
            raise RPCCollectionError("collection stopped before game attempt")
        root = selfplay.build_root(self.seed_secret, coordinate, mirror=mirror)
        root_sha = selfplay.root_identity(root)
        if not path.exists():
            path.mkdir(mode=0o700)
            _fsync_dir(self.attempts_root)
            started = time.monotonic_ns()
            _publish(path / "attempt.json", self._attempt_body(
                coordinate, mirror, root_sha, started))
        else:
            attempt = _read(path / "attempt.json")
            started = attempt.get("started_monotonic_nanoseconds")
            if attempt != self._attempt_body(
                    coordinate, mirror, root_sha, started):
                raise RPCCollectionError("resumed game attempt drift")
        if self.runtime.get("boot_identity_sha256") \
                != _read(path / "attempt.json")["boot_identity_sha256"]:
            raise RPCCollectionError("resumed game boot identity drift")
        journal = FileTurnJournal(path / "journal")
        if (path / "failure.json").is_file():
            self._finish_interrupted_failure(path, coordinate, mirror)
            self.stop_event.set()
            raise RPCCollectionError("sealed game attempt is incomplete")
        pending_refusal = journal.pending_refusal_disposition()
        if pending_refusal is not None:
            refusal = SealedTurnRefusal(
                pending_refusal["failure_kind"],
                pending_refusal["failure_class"])
            self._seal_failure(
                path, coordinate, mirror, refusal, stage="provider-response")
            self.stop_event.set()
            raise RPCCollectionError("sealed game attempt is incomplete") \
                from refusal
        game = selfplay.LunaSelfPlayGame(
            root, coordinate=coordinate, mirror=mirror,
            seed_secret=self.seed_secret)
        absolute_deadline_ns = started + self.per_game_deadline_ns
        stage = "dispatch"
        try:
            if self.codex_binary is not None \
                    and source_identity(self.codex_binary) != self.runtime:
                raise RPCCollectionError("collection live runtime drift")
            transport = _DeadlineTransport(
                self.transport_factory(path),
                lambda: absolute_deadline_ns,
                lambda event: self._emit_progress(
                    event, journal, absolute_deadline_ns),
                configure_inner_deadline=self.codex_binary is not None)
        except Exception as exc:
            game.fail(type(exc).__name__)
            self._seal_failure(
                path, coordinate, mirror, exc, stage="dispatch")
            raise RPCCollectionError("game attempt refused") from exc
        budget = lambda: (journal.pending_model_budget()
                          or self._model_budget(journal, started))
        def accept_usage(_usage) -> None:
            current = journal.usage_totals()
            if current["total_tokens"] > self.per_game_token_cap:
                raise ResourceBoundaryError("game token cap crossed")
            if time.monotonic_ns() - started > self.per_game_deadline_ns:
                raise ResourceBoundaryError("game deadline crossed")
            remaining = self._model_budget(journal, started)
            if remaining["remaining_scientific_tokens"] < 0 \
                    or remaining["remaining_scientific_wall_ms"] < 0:
                raise ResourceBoundaryError("scientific budget crossed")
        def reserve_dispatch(packet: DecisionPacket) -> None:
            owner = getattr(
                self.scientific_dispatch_reserver, "__self__", None)
            try:
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped before provider dispatch")
                if self.scientific_dispatch_reserver is not None:
                    self.scientific_dispatch_reserver(packet)
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped during provider admission")
            except Exception:
                if isinstance(owner, ScientificBudgetLedger):
                    owner.cancel(packet)
                raise
        try:
            driver = TurnDriver(
                game, transport, journal=journal,
                budget_provider=budget, usage_acceptor=accept_usage,
                response_acceptor=self.scientific_response_acceptor,
                dispatch_reserver=(reserve_dispatch
                                   if self.scientific_dispatch_reserver
                                   is not None else None))
            while not game.complete and game.failed is None:
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped after peer failure")
                remaining = self.per_game_deadline_ns - (
                    time.monotonic_ns() - started)
                if remaining <= \
                        self.per_call_wall_reserve_milliseconds * 1_000_000:
                    raise ResourceBoundaryError(
                        "game deadline admission refused")
                if journal.pending_model_budget() is None \
                        and journal.usage_totals()["total_tokens"] \
                        + self.per_call_token_reserve > self.per_game_token_cap:
                    raise ResourceBoundaryError("game token admission refused")
                stage = "dispatch"
                driver.step()
                stage = "journal-commit"
                self._emit_progress(
                    "transition-commit", journal, absolute_deadline_ns)
                if time.monotonic_ns() >= absolute_deadline_ns:
                    raise ResourceBoundaryError(
                        "game terminal deadline crossed")
                if self.scientific_terminal_acceptor is not None:
                    self.scientific_terminal_acceptor()
            if not game.complete or game.failed is not None:
                raise RPCCollectionError("game did not complete")
            stage = "terminal-verification"
            if time.monotonic_ns() >= absolute_deadline_ns:
                raise ResourceBoundaryError("game terminal deadline crossed")
            if self.scientific_terminal_acceptor is not None:
                self.scientific_terminal_acceptor()
            artifacts = game.completed_artifacts()
            summary = journal.summary()
            if summary["private_evidence_count"] != summary["call_count"] \
                    or summary["committed_call_count"] != summary["call_count"]:
                raise RPCCollectionError("game provider evidence incomplete")
            evidence_body = {"schema": EVIDENCE_SCHEMA,
                             "rows": [row.payload()
                                      for row in driver.evidence]}
            _publish_or_verify(path / "evidence.json", {**evidence_body,
                               "evidence_sha256": _sha(evidence_body)})
            _publish_or_verify(path / "trajectory.json",
                               json.loads(artifacts.trajectory.private_bytes()))
            _publish_or_verify(path / "terminal.json",
                               artifacts.terminal_receipt.payload())
            if self.codex_binary is not None \
                    and source_identity(self.codex_binary) != self.runtime:
                raise RPCCollectionError("collection terminal runtime drift")
            _publish(path / "manifest.json", self._manifest(
                path, status="complete", failure_kind=None,
                failure_class=None))
            self._emit_progress(
                "game-complete", journal, absolute_deadline_ns)
            reopened = reopen_attempt(
                path, seed_secret=self.seed_secret,
                expected_runtime_sha256=self.runtime_sha256,
                expected_scientific_binding_sha256=
                    self.scientific_binding_sha256,
                expected_coordinate=coordinate, expected_mirror=mirror)
            if reopened.artifacts is None:
                raise RPCCollectionError("completed game failed reopen")
            return reopened.artifacts
        except Exception as exc:
            game.fail(type(exc).__name__)
            self._seal_failure(
                path, coordinate, mirror, exc, stage=stage)
            self._emit_progress(
                "game-failure", journal, absolute_deadline_ns)
            self.stop_event.set()
            raise RPCCollectionError("game attempt refused") from exc


__all__ = ["ATTEMPT_SCHEMA", "AttemptReopen", "EVIDENCE_SCHEMA",
           "FAILURE_SCHEMA", "MANIFEST_SCHEMA", "RPCCollectionError",
           "RPCGameAttemptRunner", "ResourceBoundaryError",
           "SCIENTIFIC_BINDING_SCHEMA",
           "SettledResourceBoundaryError",
           "ScientificBudgetLedger", "reopen_attempt"]
