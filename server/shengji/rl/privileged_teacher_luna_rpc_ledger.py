"""Durable shared token/wall ledger for PT-Luna collection.

The ledger holds one atomic reservation per provider dispatch, settles the
exact provider debit once, isolates a local refusal to its own packet, and
marks the shared budget crossed only when the population-wide token cap or
wall is actually exhausted.  Its terminal acceptance is sealed before the
public terminal receipt so a complete population cannot be published after
either cap was crossed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Mapping, Sequence

from .privileged_teacher_luna_rpc_io import (
    AtomicPublishError, partial_path, promote_partial,
    publish_exclusive_bytes, recover_linked_partial,
)
from .privileged_teacher_luna_rpc_journal import FileTurnJournal
from .privileged_teacher_luna_rpc_transport import CodexProviderResourceError
from .privileged_teacher_luna_turn_rpc import (
    AttemptRef,
    DecisionPacket,
    PlannerResponse,
)
from .privileged_teacher_pt0 import canonical_json_bytes


REDISPATCH_ELIGIBILITIES = frozenset({
    "stderr-nonempty", "completion-telemetry-drift",
})


class RPCCollectionError(ValueError):
    """A game attempt, resource boundary, or durable artifact was refused."""


class ResourceBoundaryError(CodexProviderResourceError):
    """A frozen resource boundary refused before an engine transition."""


class SettledResourceBoundaryError(ResourceBoundaryError):
    """A sealed provider response was charged once and refused by the ledger."""


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


class ScientificBudgetLedger:
    """Durable atomic reservations plus replay-stable provider debits."""

    def __init__(self, *, root: Path,
                 started_monotonic_nanoseconds: int,
                 wall_nanoseconds: int, token_cap: int,
                 per_call_token_reserve: int,
                 boot_identity_sha256: str,
                 runtime_sha256: str,
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
                (runtime_sha256, "budget runtime")):
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
        self.namespace = namespace
        self._lock = threading.Lock()
        self._reservations: set[str] = set()
        self._responses: dict[str, tuple[str, int, bool, str, str | None]] = {}
        self._cancelled: set[str] = set()
        self._attempts: dict[str, AttemptRef] = {}
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
                       namespace: str,
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
            namespace=namespace)

    def _genesis_body(self) -> dict[str, object]:
        return {
            "schema": "pt-luna-budget-genesis-v4",
            "started_monotonic_nanoseconds": self.started_ns,
            "wall_nanoseconds": self.wall_ns,
            "token_cap": self.token_cap,
            "per_call_token_reserve": self.reserve_tokens,
            "per_call_wall_reserve_milliseconds": self.reserve_wall_ms,
            "boot_identity_sha256": self.boot_identity_sha256,
            "runtime_sha256": self.runtime_sha256,
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
                    "attempt", "redispatch_eligibility",
                    "provider_response_sha256", "tokens",
                    "elapsed_nanoseconds", "accepted",
                    "spent_tokens_after", "reserved_call_count_after",
                    "event_sha256"}
            if set(event) != keys \
                    or event.get("schema") != "pt-luna-budget-event-v3" \
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
                    != "pt-luna-budget-terminal-accept-v3"
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
                    or self._spent_tokens > self.token_cap
                    or self._has_terminal_refusal()):
                raise RPCCollectionError(
                    "scientific budget terminal acceptance drift")
            self._terminal_accept = terminal

    def _apply(self, event: Mapping[str, object], *, reopening: bool) -> None:
        packet = _strict_sha(event["packet_sha256"], "budget packet SHA")
        try:
            attempt = AttemptRef.from_mapping(event["attempt"])
        except Exception as exc:
            raise RPCCollectionError("scientific budget attempt drift") from exc
        if attempt.logical_packet_sha256 != packet:
            raise RPCCollectionError("scientific budget attempt packet drift")
        attempt_key = str(attempt.attempt_sha256)
        eligibility = event.get("redispatch_eligibility")
        if eligibility is not None and type(eligibility) is not str:
            raise RPCCollectionError("scientific budget redispatch drift")
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
            if attempt_key in self._reservations \
                    or attempt_key in self._responses \
                    or attempt_key in self._cancelled \
                    or event["provider_response_sha256"] is not None \
                    or eligibility is not None \
                    or tokens != self.reserve_tokens \
                    or event["accepted"] is not True \
                    or self._crossed or projected > self.token_cap \
                    or elapsed + self.reserve_wall_ms * 1_000_000 \
                    > self.wall_ns \
                    or (attempt.attempt_ordinal > 0 and not any(
                        ref.logical_packet_sha256 == packet
                        and ref.attempt_ordinal == attempt.attempt_ordinal - 1
                        and key in self._responses
                        and not self._responses[key][2]
                        and self._responses[key][4] in REDISPATCH_ELIGIBILITIES
                        for key, ref in self._attempts.items())) \
                    or (attempt.attempt_ordinal == 0 and any(
                        ref.logical_packet_sha256 == packet
                        for ref in self._attempts.values())):
                raise RPCCollectionError("scientific budget reserve drift")
            self._reservations.add(attempt_key)
            self._attempts[attempt_key] = attempt
        elif kind == "settle":
            provider = _strict_sha(
                event["provider_response_sha256"], "budget response SHA")
            if attempt_key not in self._reservations \
                    or attempt_key in self._responses \
                    or eligibility is not None:
                raise RPCCollectionError("scientific budget settle drift")
            expected_accepted = (not self._crossed
                                 and tokens <= self.reserve_tokens
                                 and self._spent_tokens + tokens
                                 + (len(self._reservations) - 1)
                                 * self.reserve_tokens <= self.token_cap
                                 and elapsed <= self.wall_ns)
            if event["accepted"] is not expected_accepted:
                raise RPCCollectionError("scientific budget disposition drift")
            self._reservations.remove(attempt_key)
            self._spent_tokens += tokens
            self._responses[attempt_key] = (
                provider, tokens, expected_accepted, packet, None)
            self._attempts[attempt_key] = attempt
            # A response can refuse its own game without exhausting the
            # population-wide budget (for example, by exceeding the
            # per-call reserve while the global token cap still has room).
            # Only an actual shared wall/token crossing stops peer games.
            if (self._spent_tokens
                    + len(self._reservations) * self.reserve_tokens
                    > self.token_cap or elapsed > self.wall_ns):
                self._crossed = True
        elif kind == "refuse":
            disposition = _strict_sha(
                event["provider_response_sha256"],
                "budget refusal disposition SHA")
            if attempt_key not in self._reservations \
                    or attempt_key in self._responses \
                    or event["accepted"] is not False \
                    or (eligibility is not None
                        and eligibility not in REDISPATCH_ELIGIBILITIES):
                raise RPCCollectionError("scientific budget refusal drift")
            self._reservations.remove(attempt_key)
            self._spent_tokens += tokens
            self._responses[attempt_key] = (
                disposition, tokens, False, packet, eligibility)
            self._attempts[attempt_key] = attempt
            # Retry eligibility remains packet-local: reserve() admits only
            # the exact next reviewed ordinal and never admits a fourth
            # attempt.  It must not be overloaded onto the population-wide
            # shared-budget bit.
            if (self._spent_tokens
                    + len(self._reservations) * self.reserve_tokens
                    > self.token_cap or elapsed > self.wall_ns):
                self._crossed = True
        elif kind == "cancel":
            if attempt_key in self._responses \
                    or attempt_key in self._cancelled \
                    or event["provider_response_sha256"] is not None \
                    or eligibility is not None \
                    or tokens != 0 or event["accepted"] is not False:
                raise RPCCollectionError("scientific budget cancel drift")
            self._reservations.discard(attempt_key)
            self._cancelled.add(attempt_key)
            self._attempts[attempt_key] = attempt
        else:
            raise RPCCollectionError("scientific budget event kind drift")
        if event["spent_tokens_after"] != self._spent_tokens \
                or event["reserved_call_count_after"] \
                != len(self._reservations):
            raise RPCCollectionError("scientific budget accounting drift")
        self._last_elapsed = elapsed

    def _append(self, body: Mapping[str, object]) -> None:
        sequence = len(self._events)
        event_body = {"schema": "pt-luna-budget-event-v3",
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

    @staticmethod
    def _attempt_for(packet: DecisionPacket, attempt: AttemptRef | None) \
            -> AttemptRef:
        if type(packet) is not DecisionPacket:
            raise ResourceBoundaryError("scientific dispatch packet drift")
        result = (AttemptRef(packet.sha256, 0) if attempt is None else attempt)
        if type(result) is not AttemptRef \
                or result.logical_packet_sha256 != packet.sha256:
            raise ResourceBoundaryError("scientific attempt binding drift")
        return result

    def reserve(self, packet: DecisionPacket,
                attempt: AttemptRef | None = None) -> None:
        if type(packet) is not DecisionPacket:
            raise ResourceBoundaryError("scientific dispatch packet drift")
        attempt = self._attempt_for(packet, attempt)
        key = packet.sha256
        attempt_key = str(attempt.attempt_sha256)
        with self._lock:
            if self._terminal_accept is not None:
                raise ResourceBoundaryError(
                    "scientific budget already terminal")
            if attempt_key in self._responses:
                if not self._responses[attempt_key][2]:
                    raise ResourceBoundaryError("scientific budget crossed")
                return
            if attempt_key in self._cancelled:
                raise ResourceBoundaryError(
                    "scientific dispatch was already cancelled")
            if attempt_key in self._reservations:
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
                "attempt": attempt.payload(),
                "redispatch_eligibility": None,
                "provider_response_sha256": None,
                "tokens": self.reserve_tokens,
                "elapsed_nanoseconds": elapsed, "accepted": True,
                "spent_tokens_after": self._spent_tokens,
                "reserved_call_count_after": len(self._reservations) + 1})

    def accept(self, response: PlannerResponse,
               attempt: AttemptRef | None = None) -> None:
        if type(response) is not PlannerResponse \
                or response.packet_sha256 is None \
                or response.provider_response_sha256 is None:
            raise ResourceBoundaryError("scientific response identity drift")
        key = response.packet_sha256
        if attempt is None:
            attempt = AttemptRef(key, 0)
        if type(attempt) is not AttemptRef \
                or attempt.logical_packet_sha256 != key:
            raise ResourceBoundaryError("scientific attempt binding drift")
        attempt_key = str(attempt.attempt_sha256)
        provider = response.provider_response_sha256
        tokens = response.usage.total_tokens
        with self._lock:
            prior = self._responses.get(attempt_key)
            if prior is not None:
                if prior[:2] != (provider, tokens):
                    raise ResourceBoundaryError(
                        "scientific response replay drift")
                if not prior[2]:
                    raise SettledResourceBoundaryError(
                        "scientific budget crossed")
                return
            if attempt_key not in self._reservations:
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
                "attempt": attempt.payload(),
                "redispatch_eligibility": None,
                "provider_response_sha256": provider, "tokens": tokens,
                "elapsed_nanoseconds": elapsed, "accepted": accepted,
                "spent_tokens_after": self._spent_tokens + tokens,
                "reserved_call_count_after": len(self._reservations) - 1})
            if not accepted:
                raise SettledResourceBoundaryError(
                    "scientific budget crossed")

    def accept_attempt(self, attempt: AttemptRef,
                       response: PlannerResponse) -> None:
        """Settle the exact journal response, including its physical ordinal."""
        self.accept(response, attempt)

    def refuse(self, disposition: Mapping[str, object]) -> None:
        expected = {"packet_sha256", "disposition_sha256", "total_tokens",
                    "failure_kind", "failure_class"}
        if type(disposition) is not dict or not expected.issubset(disposition) \
                or type(disposition.get("failure_kind")) is not str \
                or disposition.get("failure_class") not in {
                    "mechanics-privacy", "resource-provider"}:
            raise ResourceBoundaryError(
                "scientific refusal disposition drift")
        packet = _strict_sha(
            disposition["packet_sha256"], "scientific refusal packet")
        attempt_value = disposition.get("attempt")
        if attempt_value is None:
            attempt = AttemptRef(packet, 0)
        else:
            try:
                attempt = AttemptRef.from_mapping(attempt_value)
            except Exception as exc:
                raise ResourceBoundaryError(
                    "scientific refusal attempt drift") from exc
        if attempt.logical_packet_sha256 != packet:
            raise ResourceBoundaryError("scientific refusal attempt binding drift")
        attempt_key = str(attempt.attempt_sha256)
        evidence = _strict_sha(
            disposition["disposition_sha256"],
            "scientific refusal evidence")
        actual = disposition["total_tokens"]
        if actual is not None and (isinstance(actual, bool)
                                   or not isinstance(actual, int)
                                   or actual < 0):
            raise ResourceBoundaryError("scientific refusal usage drift")
        tokens = self.reserve_tokens if actual is None else actual
        eligibility = disposition.get("redispatch_eligibility")
        if eligibility is not None \
                and eligibility not in REDISPATCH_ELIGIBILITIES:
            raise ResourceBoundaryError("scientific refusal redispatch drift")
        with self._lock:
            prior = self._responses.get(attempt_key)
            if prior is not None:
                if prior[:3] != (evidence, tokens, False) \
                        or prior[4] != eligibility:
                    raise ResourceBoundaryError(
                        "scientific refusal replay drift")
                return
            if attempt_key not in self._reservations:
                raise ResourceBoundaryError(
                    "scientific refusal lacks dispatch reservation")
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            self._append({
                "event": "refuse", "packet_sha256": packet,
                "attempt": attempt.payload(),
                "redispatch_eligibility": disposition.get(
                    "redispatch_eligibility"),
                "provider_response_sha256": evidence, "tokens": tokens,
                "elapsed_nanoseconds": elapsed, "accepted": False,
                "spent_tokens_after": self._spent_tokens + tokens,
                "reserved_call_count_after": len(self._reservations) - 1})

    def cancel(self, packet: DecisionPacket,
               attempt: AttemptRef | None = None) -> None:
        """Release a reservation proven not to have launched a provider."""
        if type(packet) is not DecisionPacket:
            raise ResourceBoundaryError("scientific cancel packet drift")
        key = packet.sha256
        attempt = self._attempt_for(packet, attempt)
        attempt_key = str(attempt.attempt_sha256)
        with self._lock:
            if attempt_key in self._cancelled:
                return
            if attempt_key in self._responses:
                raise ResourceBoundaryError(
                    "scientific settled call cannot be cancelled")
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            remaining = len(self._reservations) - int(
                attempt_key in self._reservations)
            self._append({
                "event": "cancel", "packet_sha256": key,
                "attempt": attempt.payload(),
                "redispatch_eligibility": None,
                "provider_response_sha256": None, "tokens": 0,
                "elapsed_nanoseconds": elapsed, "accepted": False,
                "spent_tokens_after": self._spent_tokens,
                "reserved_call_count_after": remaining})

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {"spent_tokens": self._spent_tokens,
                    "reserved_call_count": len(self._reservations),
                    "accepted_response_count": sum(
                        accepted for _, _, accepted, _, _
                        in self._responses.values()),
                    "refused_response_count": sum(
                        not accepted for _, _, accepted, _, _
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
            return any(row[3] == packet for row in self._responses.values())

    def packet_state(self, packet_sha256: str) -> str:
        packet = _strict_sha(packet_sha256, "scientific packet state")
        with self._lock:
            if any(row[3] == packet for row in self._responses.values()):
                return "settled"
            if any(ref.logical_packet_sha256 == packet
                   for key, ref in self._attempts.items()
                   if key in self._reservations):
                return "reserved"
            if any(ref.logical_packet_sha256 == packet
                   for key, ref in self._attempts.items()
                   if key in self._cancelled):
                return "cancelled"
            return "absent"

    def attempt_state(self, attempt: AttemptRef) -> str:
        """Return state for one physical attempt, never another retry."""
        if type(attempt) is not AttemptRef:
            raise ResourceBoundaryError("scientific attempt state drift")
        key = str(attempt.attempt_sha256)
        with self._lock:
            if key in self._responses:
                return "settled"
            if key in self._reservations:
                return "reserved"
            if key in self._cancelled:
                return "cancelled"
            return "absent"

    def _has_terminal_refusal(self) -> bool:
        """Return whether a refusal lacks a later accepted redispatch."""
        for key, (_, _, accepted, logical, eligibility) \
                in self._responses.items():
            if accepted:
                continue
            current = self._attempts[key]
            recovered = eligibility in REDISPATCH_ELIGIBILITIES and any(
                later_accepted
                and later_logical == logical
                and self._attempts[later_key].attempt_ordinal
                > current.attempt_ordinal
                for later_key, (_, _, later_accepted, later_logical, _)
                in self._responses.items())
            if not recovered:
                return True
        return False

    def reconcile_attempt_journals(self, attempts: Sequence[Path]) -> None:
        """Require a one-to-one durable journal/ledger disposition mapping."""
        expected_responses: dict[
            str, tuple[set[str], int, set[bool], str, str | None]] = {}
        expected_reservations: set[str] = set()
        cancelable_refusals: set[str] = set()
        for attempt_path in attempts:
            journal_root = Path(attempt_path) / "journal"
            if not journal_root.is_dir() or journal_root.is_symlink():
                continue
            journal = FileTurnJournal(journal_root)
            groups = journal._scan()
            manifest = None
            manifest_path = Path(attempt_path) / "manifest.json"
            if manifest_path.is_file() and not manifest_path.is_symlink():
                manifest = _read(manifest_path)
            for group in groups:
                packet = _strict_sha(
                    group["open"]["packet_sha256"],
                    "journal ledger packet")
                attempt_ref = FileTurnJournal._attempt(group)
                attempt_key = str(attempt_ref.attempt_sha256)
                if attempt_key in expected_responses \
                        or attempt_key in expected_reservations:
                    raise RPCCollectionError(
                        "journal ledger attempt duplication")
                stages = set(group)
                if stages == {"open", "response", "commit"}:
                    response = journal._response(group)
                    expected_responses[attempt_key] = ({
                        response.provider_response_sha256},
                        response.usage.total_tokens, {True}, packet, None)
                elif stages == {"open", "refusal"}:
                    refusal = journal._refusal(group)
                    tokens = (self.reserve_tokens
                              if refusal["usage"] is None
                              else refusal["usage"]["total_tokens"])
                    expected_responses[attempt_key] = (
                        {refusal["failure_sha256"]}, tokens, {False}, packet,
                        refusal["redispatch_eligibility"])
                    if refusal["usage"] is None:
                        cancelable_refusals.add(attempt_key)
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
                    expected_responses[attempt_key] = (
                        identities, response.usage.total_tokens,
                        {True, False}, packet, None)
                elif stages == {"open"}:
                    expected_reservations.add(attempt_key)
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
            for attempt_key, (identities, tokens, accepted, logical, eligibility) \
                    in expected_responses.items():
                if attempt_key in self._cancelled:
                    continue
                actual_identity, actual_tokens, actual_accepted = \
                    self._responses[attempt_key][:3]
                if actual_identity not in identities \
                        or actual_tokens != tokens \
                        or actual_accepted not in accepted \
                        or self._responses[attempt_key][3] != logical \
                        or self._responses[attempt_key][4] != eligibility:
                    raise RPCCollectionError(
                        "journal ledger disposition drift")

    def assert_within_limits(self) -> None:
        """Refuse terminal publication after either scientific cap crossed."""
        with self._lock:
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            if self._crossed or self._spent_tokens > self.token_cap \
                    or elapsed > self.wall_ns \
                    or self._has_terminal_refusal():
                raise ResourceBoundaryError(
                    "scientific terminal budget crossed")

    def seal_terminal_acceptance(self) -> str:
        """Durably prove the global budget was live before terminal sealing."""
        with self._lock:
            if self._terminal_accept is not None:
                return str(self._terminal_accept["terminal_accept_sha256"])
            elapsed = max(0, time.monotonic_ns() - self.started_ns)
            if self._crossed or self._spent_tokens > self.token_cap \
                    or elapsed > self.wall_ns or self._reservations \
                    or self._has_terminal_refusal():
                raise ResourceBoundaryError(
                    "scientific terminal budget crossed")
            body = {
                "schema": "pt-luna-budget-terminal-accept-v3",
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


__all__ = ["REDISPATCH_ELIGIBILITIES", "RPCCollectionError",
           "ResourceBoundaryError", "ScientificBudgetLedger",
           "SettledResourceBoundaryError"]
