"""Durable three-state write-ahead journal for PT-Luna turn RPCs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from . import privileged_teacher_luna_selfplay as selfplay
from .privileged_teacher_luna_rpc_transport import (
    classify_refusal_redispatch_eligibility,
)
from .privileged_teacher_luna_rpc_io import (
    AtomicPublishError, partial_path, promote_partial,
    publish_exclusive_bytes,
    recover_linked_partial,
)
from .privileged_teacher_luna_turn_rpc import (
    AttemptRef,
    CallEvidence,
    DecisionPacket,
    Intent,
    JournalResume,
    PhaseContext,
    PlannerResponse,
    PlannerTransport,
    TeamMemory,
    TurnRPCError,
)
from .privileged_teacher_luna_canonical import canonical_json_bytes


SCHEMA = "pt-luna-turn-journal-record-v3"
_NAME = re.compile(r"^(\d{6})-(open|response|refusal|commit)\.json$")


class TurnJournalError(TurnRPCError):
    """Journal bytes, sequence, or replay semantics were refused."""


class SealedTurnRefusal(TurnJournalError):
    """A previously sealed provider refusal, preserving its original route."""

    def __init__(self, failure_kind: str, failure_class: str):
        super().__init__("provider call previously refused")
        self.failure_kind = failure_kind
        self.failure_class = failure_class


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed(body: Mapping[str, object]) -> dict[str, object]:
    result = dict(body)
    if "artifact_sha256" in result:
        raise TurnJournalError("journal body already sealed")
    result["artifact_sha256"] = _sha(result)
    return result


def _response_payload(
        response: PlannerResponse,
        private_evidence: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "intent": response.intent.payload(),
        "usage": response.usage.payload(),
        "tool_event_count": response.tool_event_count,
        "team": response.team,
        "packet_sha256": response.packet_sha256,
        "memory_sha256": response.memory_sha256,
        "provider_request_sha256": response.provider_request_sha256,
        "provider_response_sha256": response.provider_response_sha256,
        "provider_private_evidence": (None if private_evidence is None
                                      else dict(private_evidence)),
    }


def _publish(path: Path, body: Mapping[str, object]) -> None:
    raw = canonical_json_bytes(_sealed(body))
    try:
        publish_exclusive_bytes(path, raw)
    except AtomicPublishError as exc:
        raise TurnJournalError("journal atomic publication drift") from exc


def _read(path: Path) -> dict[str, object]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            if before.st_size > 64 << 20:
                raise TurnJournalError("journal file size drift")
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
        raise TurnJournalError("journal read failed") from exc
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o400
            or any(getattr(before, field) != getattr(after, field)
                   for field in fields)):
        raise TurnJournalError("journal file identity drift")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TurnJournalError("journal JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise TurnJournalError("journal canonical bytes drift")
    digest = value.pop("artifact_sha256", None)
    if type(digest) is not str or digest != _sha(value):
        raise TurnJournalError("journal seal drift")
    value["artifact_sha256"] = digest
    return value


def _closed_failure_disposition(
        exc: BaseException, *, stage: str) -> dict[str, object]:
    """Classify once, before a rejected provider result becomes durable."""
    from .privileged_teacher_luna_rpc_transport import (
        CodexProviderResourceError, CodexToolEventError,
        CodexTurnTransportError,
    )
    exception_type = type(exc).__name__
    message = str(exc) or exception_type
    lowered = message.lower()
    game_deadline = "game deadline" in lowered
    call_timeout = "turn deadline" in lowered or "call timeout" in lowered
    if game_deadline:
        kind = "game-deadline"
        if "before dispatch" in lowered or "admission" in lowered:
            stage = "dispatch"
        elif "after" in lowered:
            stage = "provider-response"
    elif call_timeout:
        stage, kind = "provider-response", "call-timeout"
    elif isinstance(exc, CodexToolEventError):
        stage, kind = "validation", "forbidden-tool"
    elif isinstance(exc, CodexProviderResourceError):
        kind = "provider-process"
    elif isinstance(exc, CodexTurnTransportError):
        stage, kind = "provider-response", "provider-schema"
    elif isinstance(exc, TurnJournalError):
        stage, kind = "journal-commit", "journal-io"
    elif isinstance(exc, TurnRPCError):
        stage, kind = "validation", "transport-validation"
    else:
        kind = "unknown"
    return {
        "stage": stage,
        "kind": kind,
        "game_deadline_fired": game_deadline,
        "call_timeout_fired": call_timeout,
        "exception_type": exception_type,
        "message_sha256": hashlib.sha256(message.encode(
            "utf-8", errors="replace")).hexdigest(),
    }


def _validate_closed_failure_disposition(value: object) -> dict[str, object]:
    keys = {"stage", "kind", "game_deadline_fired",
            "call_timeout_fired", "exception_type", "message_sha256"}
    if type(value) is not dict or set(value) != keys \
            or value["stage"] not in {
                "dispatch", "provider-response", "validation", "engine-apply",
                "journal-commit", "terminal-verification", "resource-meter"} \
            or value["kind"] not in {
                "game-deadline", "call-timeout", "provider-process",
                "provider-schema", "forbidden-tool", "transport-validation",
                "engine-validation", "journal-io", "resource-meter", "unknown"} \
            or type(value["game_deadline_fired"]) is not bool \
            or type(value["call_timeout_fired"]) is not bool \
            or type(value["exception_type"]) is not str \
            or not value["exception_type"] \
            or type(value["message_sha256"]) is not str \
            or len(value["message_sha256"]) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in value["message_sha256"]):
        raise TurnJournalError("journal failure disposition drift")
    return dict(value)


class FileTurnJournal:
    """One private append-only journal for a single game."""

    def __init__(self, root: Path):
        self.root = Path(root)
        created = not self.root.exists()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = self.root.stat(follow_symlinks=False)
        if self.root.is_symlink() or not stat.S_ISDIR(value.st_mode) \
                or value.st_uid != os.getuid() \
                or stat.S_IMODE(value.st_mode) != 0o700:
            raise TurnJournalError("journal root drift")
        if created:
            parent = os.open(
                self.root.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        self._groups = self._scan()

    def _scan(self) -> list[dict[str, dict[str, object]]]:
        # A death after the staged file was fsynced but before its hard-link
        # may leave one hidden partial.  Promote it only after the full journal
        # seal and canonical bytes validate.  A truncated partial refuses;
        # critically, it can never be mistaken for an absent provider call.
        for path in tuple(self.root.iterdir()):
            name = path.name
            if not (name.startswith(".") and name.endswith(".partial")):
                continue
            final_name = name[1:-len(".partial")]
            if _NAME.fullmatch(final_name) is None \
                    or partial_path(self.root / final_name) != path:
                raise TurnJournalError("journal file population drift")
            final_path = self.root / final_name
            try:
                if recover_linked_partial(final_path):
                    continue
            except AtomicPublishError as exc:
                raise TurnJournalError(
                    "journal linked recovery drift") from exc
            value = _read(path)
            try:
                promote_partial(
                    final_path, canonical_json_bytes(value))
            except AtomicPublishError as exc:
                raise TurnJournalError(
                    "journal partial recovery drift") from exc
        rows: dict[int, dict[str, dict[str, object]]] = {}
        order = {"open": 0, "refusal": 1, "response": 1, "commit": 2}
        seen_order: dict[int, int] = {}
        entries: list[tuple[int, int, str, str]] = []
        for path in self.root.iterdir():
            name = path.name
            match = _NAME.fullmatch(name)
            if match is None:
                raise TurnJournalError("journal file population drift")
            index = int(match.group(1))
            kind = match.group(2)
            entries.append((index, order[kind], kind, name))
        for index, _, kind, name in sorted(entries):
            if index not in rows:
                if index != len(rows):
                    raise TurnJournalError("journal call index drift")
                rows[index] = {}
                seen_order[index] = -1
            if kind in rows[index] or order[kind] != seen_order[index] + 1:
                raise TurnJournalError("journal stage sequence drift")
            value = _read(self.root / name)
            expected_kind = {"open": "decision-open",
                             "refusal": "model-call-refused",
                             "response": "model-response-sealed",
                             "commit": "transition-committed"}[kind]
            if value.get("schema") != SCHEMA \
                    or value.get("kind") != expected_kind \
                    or value.get("call_index") != index:
                raise TurnJournalError("journal record identity drift")
            rows[index][kind] = value
            seen_order[index] = order[kind]
        groups = [rows[index] for index in range(len(rows))]
        allowed = ({"open"}, {"open", "refusal"},
                   {"open", "response"},
                   {"open", "response", "commit"})
        if any(set(group) not in allowed for group in groups):
            raise TurnJournalError("journal stage population drift")
        for group in groups:
            attempt = self._attempt(group)
            for kind in ("refusal", "response", "commit"):
                if kind not in group:
                    continue
                try:
                    record_attempt = AttemptRef.from_mapping(
                        group[kind].get("attempt"))
                except Exception as exc:
                    raise TurnJournalError(
                        f"journal {kind} attempt drift") from exc
                if record_attempt != attempt:
                    raise TurnJournalError(
                        f"journal {kind} attempt binding drift")
        for index, group in enumerate(groups[:-1]):
            if set(group) not in ({"open", "response", "commit"},
                                  {"open", "refusal"}):
                raise TurnJournalError("nonterminal journal group incomplete")
            if set(group) == {"open", "refusal"}:
                if index + 1 >= len(groups):
                    raise TurnJournalError("refusal redispatch missing")
                previous = AttemptRef.from_mapping(group["open"].get("attempt"))
                following = AttemptRef.from_mapping(
                    groups[index + 1]["open"].get("attempt"))
                if (following.packet_sha256 != previous.packet_sha256
                        or following.ordinal != previous.ordinal + 1
                        or self._refusal_eligibility(group) is None):
                    raise TurnJournalError("refusal redispatch identity drift")
        for group in groups:
            if "refusal" in group:
                self._refusal(group)
        return groups

    @staticmethod
    def _open_body(packet: DecisionPacket, call_index: int,
                   attempt: AttemptRef) -> dict[str, object]:
        return {"schema": SCHEMA, "kind": "decision-open",
                "call_index": call_index, "packet_sha256": packet.sha256,
                "attempt": attempt.payload(),
                "packet": packet.payload(),
                "decision_sha256": packet.decision_sha256,
                "decision_index": packet.decision_index,
                "phase": packet.phase.phase, "team": packet.team,
                "memory_sha256": packet.memory.sha256,
                "agent_identity": packet.agent_identity}

    @staticmethod
    def _packet(group: Mapping[str, dict[str, object]]) -> DecisionPacket:
        try:
            packet = DecisionPacket.from_mapping(group["open"].get("packet"))
        except Exception as exc:
            raise TurnJournalError("journal open packet drift") from exc
        if packet.sha256 != group["open"].get("packet_sha256"):
            raise TurnJournalError("journal open packet binding drift")
        return packet

    @staticmethod
    def _attempt(group: Mapping[str, dict[str, object]]) -> AttemptRef:
        try:
            attempt = AttemptRef.from_mapping(group["open"].get("attempt"))
        except Exception as exc:
            raise TurnJournalError("journal attempt reference drift") from exc
        if attempt.packet_sha256 != group["open"].get("packet_sha256"):
            raise TurnJournalError("journal attempt packet binding drift")
        return attempt

    @staticmethod
    def _refusal_eligibility(
            group: Mapping[str, dict[str, object]]) -> str | None:
        refusal = group.get("refusal")
        if refusal is None:
            return None
        private = refusal.get("provider_private_evidence")
        if private is None:
            return None
        return classify_refusal_redispatch_eligibility(
            refusal.get("failure_disposition"), private)

    def _response(
            self, group: Mapping[str, dict[str, object]],
            packet: DecisionPacket | None = None) -> PlannerResponse:
        body = group["response"].get("response")
        if type(body) is not dict:
            raise TurnJournalError("journal response body drift")
        try:
            expected = {"intent", "usage", "tool_event_count", "team",
                        "packet_sha256", "memory_sha256",
                        "provider_request_sha256", "provider_response_sha256",
                        "provider_private_evidence"}
            if set(body) != expected:
                raise TurnJournalError("journal response field population drift")
            private = body["provider_private_evidence"]
            stored_packet = self._packet(group)
            if packet is not None and packet.payload() != stored_packet.payload():
                raise TurnJournalError("journal response packet drift")
            response = PlannerResponse.from_mapping({
                key: value for key, value in body.items()
                if key != "provider_private_evidence"})
            if private is not None:
                from .privileged_teacher_luna_rpc_transport import (
                    validate_private_evidence,
                )
                validate_private_evidence(
                    private, packet=stored_packet, response=response)
            return response
        except Exception as exc:
            raise TurnJournalError("journal response refused") from exc

    def _refusal(
            self, group: Mapping[str, dict[str, object]]) \
            -> dict[str, object]:
        body = group["refusal"]
        expected = {"schema", "kind", "call_index", "packet_sha256",
                    "attempt", "redispatch_eligibility",
                    "failure_kind", "failure_class", "failure_sha256",
                    "failure_disposition",
                    "usage", "tool_event_count",
                    "provider_private_evidence", "artifact_sha256"}
        if set(body) != expected \
                or type(body.get("failure_kind")) is not str \
                or body.get("failure_class") not in {
                    "mechanics-privacy", "resource-provider"} \
                or body.get("packet_sha256") \
                != group["open"].get("packet_sha256"):
            raise TurnJournalError("journal refusal body drift")
        attempt = self._attempt(group)
        try:
            stored_attempt = AttemptRef.from_mapping(body["attempt"])
        except Exception as exc:
            raise TurnJournalError("journal refusal attempt drift") from exc
        if stored_attempt != attempt:
            raise TurnJournalError("journal refusal attempt binding drift")
        disposition = _validate_closed_failure_disposition(
            body["failure_disposition"])
        private = body["provider_private_evidence"]
        if private is None:
            if body["usage"] is not None \
                    or body["tool_event_count"] is not None:
                raise TurnJournalError("journal refusal derivation drift")
            private_sha = None
        else:
            try:
                from .privileged_teacher_luna_rpc_transport import (
                    validate_private_refusal_evidence,
                )
                validated = validate_private_refusal_evidence(
                    private, packet=self._packet(group))
            except Exception as exc:
                raise TurnJournalError(
                    "journal refusal private evidence drift") from exc
            if body["usage"] != validated["usage"] \
                    or body["tool_event_count"] \
                    != validated["tool_event_count"]:
                raise TurnJournalError("journal refusal derivation drift")
            private_sha = validated["evidence_sha256"]
        fingerprint = {
            "packet_sha256": body["packet_sha256"],
            "failure_kind": body["failure_kind"],
            "failure_class": body["failure_class"],
            "failure_disposition": disposition,
            "private_evidence_sha256": private_sha,
            "attempt": attempt.payload(),
            "redispatch_eligibility": body["redispatch_eligibility"],
        }
        if body["failure_sha256"] != _sha(fingerprint):
            raise TurnJournalError("journal refusal fingerprint drift")
        expected_eligibility = classify_refusal_redispatch_eligibility(
            disposition, private)
        if body["redispatch_eligibility"] != expected_eligibility:
            raise TurnJournalError("journal refusal redispatch drift")
        return dict(body)

    @staticmethod
    def _failure_class(exc: Exception) -> str:
        from .privileged_teacher_luna_rpc_transport import (
            CodexProviderResourceError, CodexToolEventError,
            CodexTurnTransportError,
        )
        if isinstance(exc, CodexToolEventError):
            return "mechanics-privacy"
        if isinstance(exc, CodexProviderResourceError):
            return "resource-provider"
        if isinstance(exc, CodexTurnTransportError):
            return "mechanics-privacy"
        return ("mechanics-privacy" if isinstance(exc, TurnRPCError)
                else "resource-provider")

    def call(self, packet: DecisionPacket,
             transport: PlannerTransport, *,
             dispatch_reserver=None, attempt_reserver=None,
             refusal_settler=None, response_acceptor=None) -> PlannerResponse:
        self._groups = self._scan()
        if self._groups and set(self._groups[-1]) != {"open", "response", "commit"}:
            group = self._groups[-1]
            if self._packet(group).payload() != packet.payload():
                raise TurnJournalError("pending journal packet drift")
            if set(group) == {"open"}:
                raise TurnJournalError("provider call disposition unknown")
            if set(group) == {"open", "refusal"}:
                refusal = self._refusal(group)
                eligibility = self._refusal_eligibility(group)
                attempt = self._attempt(group)
                if eligibility is None or attempt.ordinal >= 2:
                    raise SealedTurnRefusal(
                        refusal["failure_kind"], refusal["failure_class"])
                if refusal_settler is not None:
                    refusal_settler(attempt, self.pending_refusal_disposition())
            elif set(group) == {"open", "response"}:
                response = self._response(group, packet)
                if response_acceptor is not None:
                    response_acceptor(self._attempt(group), response)
                return response
            else:
                raise TurnJournalError("pending journal stage drift")
        else:
            attempt = AttemptRef(packet.sha256, 0)

        call_index = len(self._groups)
        if attempt.packet_sha256 != packet.sha256:
            raise TurnJournalError("attempt packet drift")
        attempt = AttemptRef(packet.sha256, attempt.ordinal + 1
                             if self._groups and
                             set(self._groups[-1]) == {"open", "refusal"}
                             else attempt.ordinal)
        open_body = self._open_body(packet, call_index, attempt)
        _publish(self.root / f"{call_index:06d}-open.json", open_body)
        failure_stage = "dispatch"
        try:
            if attempt_reserver is not None:
                attempt_reserver(packet, attempt)
            elif dispatch_reserver is not None:
                dispatch_reserver(packet)
            failure_stage = "provider-response"
            raw = transport.call(packet)
            response = raw if type(raw) is PlannerResponse \
                else PlannerResponse.from_mapping(raw)
            take = getattr(transport, "take_private_evidence", None)
            private_evidence = (None if take is None
                                else take(packet, response))
        except Exception as exc:
            take_refusal = getattr(
                transport, "take_private_refusal_evidence", None)
            private_refusal = (None if take_refusal is None
                               else take_refusal(packet))
            failure_kind = type(exc).__name__
            failure_class = self._failure_class(exc)
            failure_disposition = _closed_failure_disposition(
                exc, stage=failure_stage)
            usage = (None if private_refusal is None
                     else private_refusal["usage"])
            tool_count = (None if private_refusal is None
                          else private_refusal["tool_event_count"])
            private_sha = (None if private_refusal is None
                           else private_refusal["evidence_sha256"])
            fingerprint = {
                "packet_sha256": packet.sha256,
                "failure_kind": failure_kind,
                "failure_class": failure_class,
                "failure_disposition": failure_disposition,
                "private_evidence_sha256": private_sha,
                "attempt": attempt.payload(),
            }
            failure = {
                "schema": SCHEMA, "kind": "model-call-refused",
                "call_index": call_index, "packet_sha256": packet.sha256,
                "attempt": attempt.payload(),
                "failure_kind": failure_kind,
                "failure_class": failure_class,
                "failure_disposition": failure_disposition,
                "failure_sha256": _sha(fingerprint),
                "usage": usage,
                "tool_event_count": tool_count,
                "provider_private_evidence": private_refusal,
            }
            eligibility = classify_refusal_redispatch_eligibility(
                failure_disposition, private_refusal)
            failure["redispatch_eligibility"] = eligibility
            # Re-seal after adding the public class to the durable body.
            fingerprint["redispatch_eligibility"] = eligibility
            failure["failure_sha256"] = _sha(fingerprint)
            _publish(self.root / f"{call_index:06d}-refusal.json", failure)
            self._groups = self._scan()
            if eligibility is not None and attempt.ordinal < 2:
                return self.call(packet, transport,
                                  dispatch_reserver=dispatch_reserver,
                                  attempt_reserver=attempt_reserver,
                                  refusal_settler=refusal_settler,
                                  response_acceptor=response_acceptor)
            if isinstance(exc, TurnRPCError):
                if refusal_settler is not None:
                    refusal_settler(attempt, self.pending_refusal_disposition())
                raise
            if refusal_settler is not None:
                refusal_settler(attempt, self.pending_refusal_disposition())
            raise TurnJournalError("planner transport exception") from exc
        response_body = {"schema": SCHEMA, "kind": "model-response-sealed",
                         "call_index": call_index,
                         "packet_sha256": packet.sha256,
                         "attempt": attempt.payload(),
                         "response": _response_payload(
                             response, private_evidence)}
        _publish(self.root / f"{call_index:06d}-response.json", response_body)
        self._groups = self._scan()
        if response_acceptor is not None:
            response_acceptor(attempt, response)
        return response

    def commit(self, evidence: CallEvidence) -> None:
        self._groups = self._scan()
        if not self._groups or set(self._groups[-1]) != {"open", "response"}:
            raise TurnJournalError("journal response is not pending commit")
        call_index = len(self._groups) - 1
        group = self._groups[-1]
        if group["open"].get("packet_sha256") != evidence.packet_sha256:
            raise TurnJournalError("journal commit packet drift")
        response = self._response(group)
        if (response.provider_request_sha256 != evidence.provider_request_sha256
                or response.provider_response_sha256
                != evidence.provider_response_sha256):
            raise TurnJournalError("journal commit provider binding drift")
        body = {"schema": SCHEMA, "kind": "transition-committed",
                "call_index": call_index,
                "packet_sha256": evidence.packet_sha256,
                "attempt": self._attempt(group).payload(),
                "evidence": evidence.payload()}
        _publish(self.root / f"{call_index:06d}-commit.json", body)
        self._groups = self._scan()

    def restore(self, game: selfplay.LunaSelfPlayGame) -> JournalResume:
        """Replay committed calls; never repeat a provider call."""
        self._groups = self._scan()
        memories = {team: TeamMemory.initial(
            team, selfplay._state_digest(game.rnd, team)) for team in (0, 1)}
        decision_index = 0
        phase = PhaseContext()
        rollouts: list[Mapping[str, object]] = []
        phase_planning_note = ""
        staged_memory: TeamMemory | None = None
        committed_evidence: list[CallEvidence] = []
        for group in self._groups:
            if "commit" not in group:
                if "refusal" in group:
                    continue
                break
            team = game.acting_team
            if team not in (0, 1):
                raise TurnJournalError("journal replay passed round end")
            observation = game.session(team).observe()
            stored_packet = self._packet(group)
            budget = dict(observation.get("budget", {}))
            if "model" in stored_packet.budget:
                budget["model"] = stored_packet.budget["model"]
            observation = dict(observation)
            observation["budget"] = budget
            packet = DecisionPacket.from_observation(
                observation, coordinate=game.coordinate, mirror=game.mirror,
                team=team, decision_index=decision_index,
                memory=memories[team], phase=phase,
                phase_planning_note=phase_planning_note,
                rollouts=tuple(rollouts))
            if stored_packet.payload() != packet.payload():
                raise TurnJournalError("journal replay packet drift")
            response = self._response(group, packet)
            evidence_raw = group["commit"].get("evidence")
            try:
                evidence = CallEvidence.from_mapping(evidence_raw)
            except Exception as exc:
                raise TurnJournalError("journal commit evidence drift") from exc
            if evidence.packet_sha256 != packet.sha256:
                raise TurnJournalError("journal replay evidence binding drift")
            committed_evidence.append(evidence)
            intent = response.intent
            session = game.session(team)
            if intent.kind == "rollout":
                rollout_before = selfplay._state_snapshot(game.rnd)
                result = session.rollout({
                    "op": "rollout",
                    "decision_sha256": packet.decision_sha256,
                    "candidate_indices": list(intent.candidate_indices),
                    "continuations": list(intent.continuations)})
                if selfplay._state_snapshot(game.rnd) != rollout_before \
                        or selfplay._state_digest(game.rnd, team) \
                        != packet.decision_sha256:
                    raise TurnJournalError("journal rollout mutated live engine")
                if evidence.rollout_result != result \
                        or evidence.before_state_sha256 != packet.decision_sha256 \
                        or evidence.after_state_sha256 != packet.decision_sha256:
                    raise TurnJournalError("journal rollout replay drift")
                rollouts.append(result)
                if intent.memory_update is not None:
                    staged_memory = intent.memory_update
                phase_planning_note = (
                    intent.memory_update.strategy_note
                    if intent.memory_update is not None
                    else intent.planning_note)
                phase = PhaseContext(phase.phase + 1)
                continue
            if intent.candidate_index >= len(packet.candidates):
                raise TurnJournalError("journal replay candidate drift")
            before = packet.decision_sha256
            session.play({"op": "play", "decision_sha256": before,
                          "candidate_index": intent.candidate_index,
                          "confidence": intent.confidence})
            after = selfplay._state_digest(game.rnd, team)
            if evidence.before_state_sha256 != before \
                    or evidence.after_state_sha256 != after:
                raise TurnJournalError("journal play replay drift")
            next_memory = intent.memory_update or staged_memory
            if next_memory is None:
                next_memory = TeamMemory(
                    team, memories[team].revision + 1, after,
                    intent.planning_note or phase_planning_note
                    or memories[team].strategy_note)
            if next_memory.team != team \
                    or next_memory.revision != memories[team].revision + 1 \
                    or next_memory.bound_after_state_sha256 != after:
                raise TurnJournalError("journal memory replay drift")
            memories[team] = next_memory
            session.memory = next_memory.payload()
            decision_index += 1
            phase = PhaseContext()
            rollouts = []
            phase_planning_note = ""
            staged_memory = None
        return JournalResume(
            decision_index, phase, tuple(rollouts), memories,
            phase_planning_note, staged_memory, tuple(committed_evidence))

    def pending_model_budget(self) -> dict[str, int] | None:
        """Return the exact dynamic budget of a sealed unfinished call."""
        self._groups = self._scan()
        if not self._groups \
                or set(self._groups[-1]) == {"open", "response", "commit"}:
            return None
        packet = self._packet(self._groups[-1])
        model = packet.budget.get("model")
        return None if model is None else dict(model)

    def pending_refusal_disposition(self) -> dict[str, object] | None:
        """Return a sealed rejected-call debit for global ledger replay."""
        self._groups = self._scan()
        if not self._groups or "refusal" not in self._groups[-1]:
            return None
        body = self._refusal(self._groups[-1])
        usage = body["usage"]
        return {
            "packet_sha256": body["packet_sha256"],
            "attempt": dict(body["attempt"]),
            "redispatch_eligibility": body["redispatch_eligibility"],
            "disposition_sha256": body["failure_sha256"],
            "failure_sha256": body["failure_sha256"],
            "failure_disposition": dict(body["failure_disposition"]),
            "total_tokens": (None if usage is None
                             else usage["total_tokens"]),
            "failure_kind": body["failure_kind"],
            "failure_class": body["failure_class"],
        }

    def pending_refusal_tool_event_count(self) -> int | None:
        """Return the exact sealed refusal tool count while bytes still exist."""
        self._groups = self._scan()
        if not self._groups or "refusal" not in self._groups[-1]:
            return None
        value = self._refusal(self._groups[-1])["tool_event_count"]
        return 0 if value is None else int(value)

    def pending_refusal_failure_disposition(self) \
            -> dict[str, object] | None:
        """Return the originally sealed closed failure classification."""
        self._groups = self._scan()
        if not self._groups or "refusal" not in self._groups[-1]:
            return None
        return _validate_closed_failure_disposition(
            self._refusal(self._groups[-1])["failure_disposition"])

    def pending_rejected_response_disposition(
            self, *, failure_kind: str, failure_class: str) \
            -> dict[str, object] | None:
        """Charge an exact sealed response rejected before engine commit."""
        self._groups = self._scan()
        if not self._groups \
                or set(self._groups[-1]) != {"open", "response"}:
            return None
        if type(failure_kind) is not str or failure_class not in {
                "mechanics-privacy", "resource-provider"}:
            raise TurnJournalError("rejected response disposition drift")
        group = self._groups[-1]
        response = self._response(group)
        packet_sha256 = group["open"]["packet_sha256"]
        body = {
            "schema": "pt-luna-rejected-response-disposition-v1",
            "packet_sha256": packet_sha256,
            "provider_response_sha256":
                response.provider_response_sha256,
            "total_tokens": response.usage.total_tokens,
            "failure_kind": failure_kind,
            "failure_class": failure_class,
        }
        return {
            "packet_sha256": packet_sha256,
            "attempt": self._attempt(group).payload(),
            "disposition_sha256": _sha(body),
            "total_tokens": response.usage.total_tokens,
            "failure_kind": failure_kind,
            "failure_class": failure_class,
        }

    def seal_unknown_disposition(self) -> dict[str, object] | None:
        """Turn an open-only provider call into a durable charged refusal."""
        self._groups = self._scan()
        if not self._groups or set(self._groups[-1]) != {"open"}:
            return self.pending_refusal_disposition()
        group = self._groups[-1]
        call_index = len(self._groups) - 1
        packet_sha256 = group["open"]["packet_sha256"]
        attempt = self._attempt(group)
        fingerprint = {
            "packet_sha256": packet_sha256,
            "failure_kind": "UnknownProviderDisposition",
            "failure_class": "resource-provider",
            "failure_disposition": {
                "stage": "provider-response",
                "kind": "provider-process",
                "game_deadline_fired": False,
                "call_timeout_fired": False,
                "exception_type": "UnknownProviderDisposition",
                "message_sha256": hashlib.sha256(
                    b"provider disposition unknown").hexdigest(),
            },
            "private_evidence_sha256": None,
            "attempt": attempt.payload(),
            "redispatch_eligibility": None,
        }
        body = {
            "schema": SCHEMA, "kind": "model-call-refused",
            "call_index": call_index, "packet_sha256": packet_sha256,
            "attempt": attempt.payload(), "redispatch_eligibility": None,
            "failure_kind": "UnknownProviderDisposition",
            "failure_class": "resource-provider",
            "failure_disposition": fingerprint["failure_disposition"],
            "failure_sha256": _sha(fingerprint), "usage": None,
            "tool_event_count": None, "provider_private_evidence": None,
        }
        _publish(self.root / f"{call_index:06d}-refusal.json", body)
        self._groups = self._scan()
        return self.pending_refusal_disposition()

    def summary(self) -> dict[str, object]:
        self._groups = self._scan()
        completed = sum(set(group) == {"open", "response", "commit"}
                        for group in self._groups)
        refused = sum(set(group) == {"open", "refusal"}
                      for group in self._groups)
        private = sum(
            group.get("response", {}).get("response", {}).get(
                "provider_private_evidence") is not None
            or group.get("refusal", {}).get(
                "provider_private_evidence") is not None
            for group in self._groups)
        pending = None
        if self._groups and set(self._groups[-1]) != {"open", "response", "commit"}:
            pending = sorted(self._groups[-1])
        committed_decisions = sum(
            group.get("commit", {}).get("evidence", {}).get(
                "intent", {}).get("kind") == "play"
            for group in self._groups)
        return {"schema": "pt-luna-turn-journal-summary-v1",
                "call_count": len(self._groups),
                "opened_rpc_count": len(self._groups),
                "committed_call_count": completed,
                "committed_decision_count": committed_decisions,
                "refused_call_count": refused,
                "private_evidence_count": private,
                "pending_stages": pending}

    def usage_totals(self) -> dict[str, int]:
        """Derive provider usage from accepted and known refused responses."""
        self._groups = self._scan()
        totals = {"input_tokens": 0, "cached_input_tokens": 0,
                  "cache_write_input_tokens": 0, "output_tokens": 0,
                  "reasoning_output_tokens": 0, "total_tokens": 0,
                  "wall_ms": 0, "response_count": 0}
        for group in self._groups:
            if "response" in group:
                usage = self._response(group).usage.payload()
            elif "refusal" in group:
                usage = self._refusal(group)["usage"]
                if usage is None:
                    continue
            else:
                continue
            for key in ("input_tokens", "cached_input_tokens",
                        "cache_write_input_tokens", "output_tokens",
                        "reasoning_output_tokens", "total_tokens", "wall_ms"):
                totals[key] += usage[key]
            totals["response_count"] += 1
        return totals


__all__ = ["FileTurnJournal", "SCHEMA", "SealedTurnRefusal",
           "TurnJournalError"]
