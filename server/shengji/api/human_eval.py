"""Fail-closed identity primitives for a future human-vs-bot evaluation.

This module does not enable an experiment.  It defines the immutable fields a
reviewed room assignment must carry and a balanced, hidden two-session block
schedule.  Production room creation has no path to construct this context yet.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SCHEMA = "human-vs-bot-evaluation-v1"
RUNTIME_RECEIPT_SCHEMA = "human-evaluation-runtime-identity-receipt-v1"
ASSIGNMENT_RESERVATION_SCHEMA = "human-evaluation-assignment-reservation-v1"
CONSENT_ASSERTION_SCHEMA = "human-evaluation-consent-assertion-v1"
CONSENT_ASSERTION_AUDIENCE = "shengji-human-evaluation-ingress-v1"
MAX_CONSENT_ASSERTION_BYTES = 4096
MAX_CONSENT_ASSERTION_LIFETIME_SECONDS = 24 * 60 * 60
ARMS = ("candidate", "champion")
HUMAN_SEATS = (0, 2)
BOT_SEATS = (1, 3)
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$")
_PSEUDONYM = re.compile(r"^[0-9a-f]{16,64}$")
_GIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HumanEvaluationError(ValueError):
    """The proposed room identity is not evidence-grade."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()


def _json_object_without_duplicate_keys(raw: bytes) -> dict:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise HumanEvaluationError(
                    "duplicate consent assertion field")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except HumanEvaluationError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise HumanEvaluationError(
            "invalid consent assertion JSON") from exc
    if not isinstance(value, dict):
        raise HumanEvaluationError("consent assertion is not an object")
    return value


def registered_policy_ballot_id(policy: str) -> str:
    """Reconstruct the registered policy's executable ballot identity.

    The digest includes every named ballot stage and its derived source/config
    identity.  Git and image identity bind the rest of the executable policy;
    this field prevents a reviewed room from silently widening or swapping the
    action generator inside that artifact.
    """
    _require(_ID, policy, "policy")
    try:
        from ..engine.ballot import policy_ballots
        stages = policy_ballots(policy)
    except Exception as exc:
        raise HumanEvaluationError(
            f"cannot reopen registered policy ballot: {policy}") from exc
    payload = {
        stage: asdict(spec)
        for stage, spec in sorted(stages.items())
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()
    return "policy-ballots-v1-" + hashlib.sha256(raw).hexdigest()


def _require(pattern: re.Pattern[str], value: str, field: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise HumanEvaluationError(f"invalid {field}")


def derive_participant_pair_id(participant_ids: tuple[str, str]) -> str:
    """Derive the stable clustering key from two pseudonymous identities."""
    if (not isinstance(participant_ids, tuple) or len(participant_ids) != 2
            or len(set(participant_ids)) != 2):
        raise HumanEvaluationError("two distinct participant IDs are required")
    for value in participant_ids:
        _require(_PSEUDONYM, value, "participant_id")
    raw = (SCHEMA + "\0" + "\0".join(sorted(participant_ids))).encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def blocked_arm(*, assignment_secret: bytes, participant_pair_id: str,
                block_id: str, block_slot: int,
                assignment_domain: str | None = None
                ) -> Literal["candidate", "champion"]:
    """Return one complementary arm per slot in a hidden two-session block."""
    if not isinstance(assignment_secret, bytes) or len(assignment_secret) < 32:
        raise HumanEvaluationError("assignment secret must contain >=32 bytes")
    _require(_PSEUDONYM, participant_pair_id, "participant_pair_id")
    _require(_ID, block_id, "block_id")
    if block_slot not in (0, 1) or isinstance(block_slot, bool):
        raise HumanEvaluationError("block_slot must be 0 or 1")
    if assignment_domain is not None:
        _require(_ID, assignment_domain, "assignment_domain")
    domain = "" if assignment_domain is None else f"{assignment_domain}\0"
    message = (
        f"{SCHEMA}\0{domain}{participant_pair_id}\0{block_id}"
    ).encode()
    first = hmac.new(assignment_secret, message, hashlib.sha256).digest()[0] & 1
    candidate_slot = first
    return "candidate" if block_slot == candidate_slot else "champion"


def _session_id(*, assignment_secret: bytes, participant_pair_id: str,
                block_id: str, block_slot: int,
                assignment_domain: str) -> str:
    """Derive one opaque, idempotent session ID without revealing the arm."""
    if not isinstance(assignment_secret, bytes) or len(assignment_secret) < 32:
        raise HumanEvaluationError("assignment secret must contain >=32 bytes")
    _require(_PSEUDONYM, participant_pair_id, "participant_pair_id")
    _require(_ID, block_id, "block_id")
    _require(_ID, assignment_domain, "assignment_domain")
    if block_slot not in (0, 1) or isinstance(block_slot, bool):
        raise HumanEvaluationError("block_slot must be 0 or 1")
    message = (
        f"{SCHEMA}\0session\0{assignment_domain}\0{participant_pair_id}"
        f"\0{block_id}\0{block_slot}"
    ).encode()
    digest = hmac.new(assignment_secret, message, hashlib.sha256).hexdigest()
    return f"session-{digest[:32]}"


@dataclass(frozen=True)
class PolicyIdentity:
    """One reviewed policy artifact named by an evaluation design."""

    policy: str
    git: str
    image_sha256: str
    ballot_id: str

    def __post_init__(self) -> None:
        _require(_ID, self.policy, "policy")
        _require(_GIT, self.git, "git")
        _require(_SHA256, self.image_sha256, "image_sha256")
        _require(_ID, self.ballot_id, "ballot_id")


@dataclass(frozen=True)
class HumanEvaluationDesign:
    """Reviewed, score-free identity from which assignments may be built."""

    experiment_id: str
    assignment_design_sha256: str
    cohort_id: str
    consent_version: str
    candidate: PolicyIdentity
    champion: PolicyIdentity

    def __post_init__(self) -> None:
        for field in ("experiment_id", "cohort_id", "consent_version"):
            _require(_ID, getattr(self, field), field)
        _require(_SHA256, self.assignment_design_sha256,
                 "assignment_design_sha256")
        if not isinstance(self.candidate, PolicyIdentity):
            raise HumanEvaluationError("invalid candidate identity")
        if not isinstance(self.champion, PolicyIdentity):
            raise HumanEvaluationError("invalid champion identity")
        if self.candidate.policy == self.champion.policy:
            raise HumanEvaluationError(
                "candidate and champion policy names must differ")


@dataclass(frozen=True)
class ConsentedParticipant:
    """Server-verified consent facts."""

    participant_id: str
    cohort_id: str
    consent_version: str
    opted_in: bool

    def __post_init__(self) -> None:
        _require(_PSEUDONYM, self.participant_id, "participant_id")
        _require(_ID, self.cohort_id, "cohort_id")
        _require(_ID, self.consent_version, "consent_version")
        if self.opted_in is not True:
            raise HumanEvaluationError("participant has not opted in")


def verify_consent_assertion(
        token: str, *, design: HumanEvaluationDesign,
        consent_secret: bytes, now_unix_s: int) -> ConsentedParticipant:
    """Authenticate one short-lived opt-in assertion for an exact design.

    Assertions are issued outside this module by a separately reviewed,
    authenticated consent flow.  This verifier accepts only canonical JSON in
    ``base64url(payload).hex_hmac`` form.  It deliberately grants neither an
    assignment nor human-traffic authority; the two distinct verified facts
    still have to pass :func:`construct_reviewed_assignment` and the durable
    one-use reservation boundary.
    """
    if not isinstance(design, HumanEvaluationDesign):
        raise HumanEvaluationError("invalid evaluation design")
    if not isinstance(consent_secret, bytes) or len(consent_secret) < 32:
        raise HumanEvaluationError("consent secret must contain >=32 bytes")
    if (not isinstance(now_unix_s, int) or isinstance(now_unix_s, bool)
            or now_unix_s < 0):
        raise HumanEvaluationError("invalid consent verification time")
    if (not isinstance(token, str) or not token.isascii()
            or not 0 < len(token.encode("ascii"))
            <= MAX_CONSENT_ASSERTION_BYTES
            or token.count(".") != 1):
        raise HumanEvaluationError("invalid consent assertion encoding")
    payload_text, signature = token.split(".", 1)
    if (not payload_text
            or re.fullmatch(r"[A-Za-z0-9_-]+", payload_text) is None
            or _SHA256.fullmatch(signature) is None):
        raise HumanEvaluationError("invalid consent assertion encoding")
    payload_segment = payload_text.encode("ascii")
    padding = b"=" * ((4 - len(payload_segment) % 4) % 4)
    try:
        raw = base64.b64decode(
            payload_segment + padding, altchars=b"-_", validate=True)
    except ValueError as exc:
        raise HumanEvaluationError(
            "invalid consent assertion encoding") from exc
    if base64.urlsafe_b64encode(raw).rstrip(b"=") != payload_segment:
        raise HumanEvaluationError("non-canonical consent assertion encoding")
    expected_signature = hmac.new(
        consent_secret,
        CONSENT_ASSERTION_SCHEMA.encode() + b"\0" + payload_segment,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HumanEvaluationError("consent assertion signature mismatch")

    claims = _json_object_without_duplicate_keys(raw)
    expected_fields = {
        "schema", "audience", "experiment_id",
        "assignment_design_sha256", "participant_id", "cohort_id",
        "consent_version", "opted_in", "issued_at_unix_s",
        "expires_at_unix_s",
    }
    if set(claims) != expected_fields or _canonical_json(claims) != raw:
        raise HumanEvaluationError("invalid consent assertion fields")
    if (claims.get("schema") != CONSENT_ASSERTION_SCHEMA
            or claims.get("audience") != CONSENT_ASSERTION_AUDIENCE
            or claims.get("experiment_id") != design.experiment_id
            or claims.get("assignment_design_sha256")
            != design.assignment_design_sha256
            or claims.get("cohort_id") != design.cohort_id
            or claims.get("consent_version") != design.consent_version):
        raise HumanEvaluationError(
            "consent assertion does not match evaluation design")
    issued_at = claims.get("issued_at_unix_s")
    expires_at = claims.get("expires_at_unix_s")
    if (not isinstance(issued_at, int) or isinstance(issued_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or issued_at < 0 or expires_at <= issued_at
            or expires_at - issued_at
            > MAX_CONSENT_ASSERTION_LIFETIME_SECONDS):
        raise HumanEvaluationError("invalid consent assertion lifetime")
    if issued_at > now_unix_s:
        raise HumanEvaluationError("consent assertion is not yet valid")
    if expires_at <= now_unix_s:
        raise HumanEvaluationError("consent assertion has expired")
    return ConsentedParticipant(
        participant_id=claims.get("participant_id"),
        cohort_id=claims.get("cohort_id"),
        consent_version=claims.get("consent_version"),
        opted_in=claims.get("opted_in"),
    )


@dataclass(frozen=True)
class HumanEvaluationContext:
    """Immutable assignment/log identity; never serialized to client state."""

    experiment_id: str
    assignment_design_sha256: str
    session_id: str
    participant_pair_id: str
    participant_ids_by_human_seat: tuple[str, str]
    cohort_id: str
    consent_version: str
    block_id: str
    block_slot: int
    arm: Literal["candidate", "champion"]
    candidate_policy: str
    candidate_git: str
    candidate_image_sha256: str
    champion_policy: str
    champion_git: str
    champion_image_sha256: str
    candidate_ballot_id: str
    champion_ballot_id: str

    def __post_init__(self) -> None:
        for field in ("experiment_id", "session_id", "cohort_id",
                      "consent_version", "block_id", "candidate_policy",
                      "champion_policy", "candidate_ballot_id",
                      "champion_ballot_id"):
            _require(_ID, getattr(self, field), field)
        _require(_SHA256, self.assignment_design_sha256,
                 "assignment_design_sha256")
        _require(_PSEUDONYM, self.participant_pair_id, "participant_pair_id")
        if (not isinstance(self.participant_ids_by_human_seat, tuple)
                or len(self.participant_ids_by_human_seat) != 2
                or len(set(self.participant_ids_by_human_seat)) != 2):
            raise HumanEvaluationError(
                "two distinct participant IDs are required for seats 0 and 2")
        for value in self.participant_ids_by_human_seat:
            _require(_PSEUDONYM, value, "participant_id")
        if self.participant_pair_id != derive_participant_pair_id(
                self.participant_ids_by_human_seat):
            raise HumanEvaluationError(
                "participant_pair_id does not match participant IDs")
        if self.arm not in ARMS:
            raise HumanEvaluationError("arm must be candidate or champion")
        if self.block_slot not in (0, 1) or isinstance(self.block_slot, bool):
            raise HumanEvaluationError("block_slot must be 0 or 1")
        _require(_GIT, self.candidate_git, "candidate_git")
        _require(_GIT, self.champion_git, "champion_git")
        _require(_SHA256, self.candidate_image_sha256,
                 "candidate_image_sha256")
        _require(_SHA256, self.champion_image_sha256,
                 "champion_image_sha256")
        if self.candidate_policy == self.champion_policy:
            raise HumanEvaluationError(
                "candidate and champion policy names must differ")

    @property
    def active_policy(self) -> str:
        return (self.candidate_policy if self.arm == "candidate"
                else self.champion_policy)

    @property
    def active_policy_identity(self) -> PolicyIdentity:
        if self.arm == "candidate":
            return PolicyIdentity(
                policy=self.candidate_policy,
                git=self.candidate_git,
                image_sha256=self.candidate_image_sha256,
                ballot_id=self.candidate_ballot_id,
            )
        return PolicyIdentity(
            policy=self.champion_policy,
            git=self.champion_git,
            image_sha256=self.champion_image_sha256,
            ballot_id=self.champion_ballot_id,
        )

    def log_payload(self) -> dict:
        """Return the complete server-only identity attached to every event."""
        return {
            "schema": SCHEMA,
            "experiment_id": self.experiment_id,
            "assignment_design_sha256": self.assignment_design_sha256,
            "session_id": self.session_id,
            "participant_pair_id": self.participant_pair_id,
            "participants": [
                {"seat": seat, "participant_id": participant}
                for seat, participant in zip(
                    HUMAN_SEATS, self.participant_ids_by_human_seat,
                    strict=True)
            ],
            "human_seats": list(HUMAN_SEATS),
            "bot_seats": list(BOT_SEATS),
            "cohort_id": self.cohort_id,
            "consent_version": self.consent_version,
            "block_id": self.block_id,
            "block_slot": self.block_slot,
            "arm": self.arm,
            "assignment_probability": 0.5,
            "candidate": {
                "policy": self.candidate_policy,
                "git": self.candidate_git,
                "image_sha256": self.candidate_image_sha256,
                "ballot_id": self.candidate_ballot_id,
            },
            "champion": {
                "policy": self.champion_policy,
                "git": self.champion_git,
                "image_sha256": self.champion_image_sha256,
                "ballot_id": self.champion_ballot_id,
            },
            "active_policy": self.active_policy,
            "training_excluded": True,
            "candidate_selection_excluded": True,
            "production_promotion_gate": True,
            "policy_hidden_from_players": True,
        }


def construct_reviewed_assignment(
        *, design: HumanEvaluationDesign,
        participants_by_human_seat: tuple[ConsentedParticipant,
                                          ConsentedParticipant],
        block_id: str, block_slot: int,
        assignment_secret: bytes) -> HumanEvaluationContext:
    """Construct an immutable hidden assignment from a reviewed design.

    This is deliberately a pure, server-only constructor.  It derives the arm
    and session ID rather than accepting either from a client.  A future
    ingress must still authenticate consent tokens and durably enforce that a
    reviewed block slot is issued and completed at most once.
    """
    if not isinstance(design, HumanEvaluationDesign):
        raise HumanEvaluationError("invalid evaluation design")
    if (not isinstance(participants_by_human_seat, tuple)
            or len(participants_by_human_seat) != 2
            or not all(isinstance(value, ConsentedParticipant)
                       for value in participants_by_human_seat)):
        raise HumanEvaluationError(
            "two consented participants are required for seats 0 and 2")
    participant_ids = tuple(
        participant.participant_id
        for participant in participants_by_human_seat)
    pair_id = derive_participant_pair_id(participant_ids)
    for participant in participants_by_human_seat:
        if participant.cohort_id != design.cohort_id:
            raise HumanEvaluationError("participant cohort does not match design")
        if participant.consent_version != design.consent_version:
            raise HumanEvaluationError(
                "participant consent version does not match design")
    arm = blocked_arm(
        assignment_secret=assignment_secret,
        participant_pair_id=pair_id,
        block_id=block_id,
        block_slot=block_slot,
        assignment_domain=design.assignment_design_sha256,
    )
    session_id = _session_id(
        assignment_secret=assignment_secret,
        participant_pair_id=pair_id,
        block_id=block_id,
        block_slot=block_slot,
        assignment_domain=design.assignment_design_sha256,
    )
    return HumanEvaluationContext(
        experiment_id=design.experiment_id,
        assignment_design_sha256=design.assignment_design_sha256,
        session_id=session_id,
        participant_pair_id=pair_id,
        participant_ids_by_human_seat=participant_ids,
        cohort_id=design.cohort_id,
        consent_version=design.consent_version,
        block_id=block_id,
        block_slot=block_slot,
        arm=arm,
        candidate_policy=design.candidate.policy,
        candidate_git=design.candidate.git,
        candidate_image_sha256=design.candidate.image_sha256,
        champion_policy=design.champion.policy,
        champion_git=design.champion.git,
        champion_image_sha256=design.champion.image_sha256,
        candidate_ballot_id=design.candidate.ballot_id,
        champion_ballot_id=design.champion.ballot_id,
    )


def construct_reviewed_assignment_from_consent_assertions(
        *, design: HumanEvaluationDesign,
        consent_assertions_by_human_seat: tuple[str, str],
        block_id: str, block_slot: int, assignment_secret: bytes,
        consent_secret: bytes, now_unix_s: int) -> HumanEvaluationContext:
    """Authenticate two opt-ins before constructing a score-free assignment.

    No token may provide the arm, session, block or policy.  Those values come
    exclusively from the reviewed design and the server-side assignment
    secret.  This helper remains unreachable from production room ingress.
    """
    if (not isinstance(consent_assertions_by_human_seat, tuple)
            or len(consent_assertions_by_human_seat) != 2
            or not all(isinstance(value, str)
                       for value in consent_assertions_by_human_seat)):
        raise HumanEvaluationError(
            "two consent assertions are required for seats 0 and 2")
    participants = tuple(
        verify_consent_assertion(
            token, design=design, consent_secret=consent_secret,
            now_unix_s=now_unix_s)
        for token in consent_assertions_by_human_seat
    )
    return construct_reviewed_assignment(
        design=design,
        participants_by_human_seat=participants,
        block_id=block_id,
        block_slot=block_slot,
        assignment_secret=assignment_secret,
    )


def reopen_assigned_policy(
        context: HumanEvaluationContext, *, runtime_git: str,
        runtime_image_sha256: str):
    """Reconstruct and authenticate the policy an assigned room will run.

    A future ingress must obtain the runtime Git/image values from its reviewed
    immutable deployment receipt.  No caller-supplied bot is accepted here:
    the exact registered policy is rebuilt and its executable ballot is
    independently derived before a room may receive it.
    """
    if not isinstance(context, HumanEvaluationContext):
        raise HumanEvaluationError("invalid evaluation context")
    _require(_GIT, runtime_git, "runtime_git")
    _require(_SHA256, runtime_image_sha256, "runtime_image_sha256")
    expected = context.active_policy_identity
    if runtime_git != expected.git:
        raise HumanEvaluationError(
            "assigned policy Git does not match evaluation runtime")
    if runtime_image_sha256 != expected.image_sha256:
        raise HumanEvaluationError(
            "assigned policy image does not match evaluation runtime")
    actual_ballot_id = registered_policy_ballot_id(expected.policy)
    if actual_ballot_id != expected.ballot_id:
        raise HumanEvaluationError(
            "assigned policy ballot does not match evaluation runtime")
    try:
        from ..ai.registry import make_bot
        bot = make_bot(expected.policy)
    except Exception as exc:
        raise HumanEvaluationError(
            f"cannot reopen registered policy: {expected.policy}") from exc
    if getattr(bot, "policy_name", None) != expected.policy:
        raise HumanEvaluationError(
            "reopened policy name does not match evaluation assignment")
    return bot


def _read_regular_unlinked(path: Path) -> bytes:
    """Read stable bytes while refusing symlinks and shared hard links."""
    try:
        listed = path.lstat()
    except OSError as exc:
        raise HumanEvaluationError("cannot open runtime identity receipt") from exc
    if not stat.S_ISREG(listed.st_mode) or listed.st_nlink != 1:
        raise HumanEvaluationError(
            "runtime identity receipt must be a regular unlinked file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HumanEvaluationError("cannot open runtime identity receipt") from exc
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            before = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino) != (listed.st_dev, listed.st_ino):
                raise HumanEvaluationError(
                    "runtime identity receipt changed before open")
            raw = handle.read()
            after = os.fstat(handle.fileno())
    finally:
        os.close(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if (before.st_nlink != 1 or after.st_nlink != 1
            or not stat.S_ISREG(after.st_mode)
            or any(getattr(before, field) != getattr(after, field)
                   for field in stable_fields)
            or len(raw) != after.st_size):
        raise HumanEvaluationError(
            "runtime identity receipt changed while reading")
    return raw


def reopen_assigned_policy_from_receipt(
        context: HumanEvaluationContext, *, receipt_path: str | Path,
        expected_receipt_sha256: str):
    """Reopen an assigned policy from an exact identity-only receipt.

    The receipt deliberately grants no room or traffic authority.  A later
    reviewed ingress/admission must pin its digest and separately authorize a
    bounded evaluation launch.
    """
    _require(_SHA256, expected_receipt_sha256, "expected_receipt_sha256")
    raw = _read_regular_unlinked(Path(receipt_path))
    if hashlib.sha256(raw).hexdigest() != expected_receipt_sha256:
        raise HumanEvaluationError("runtime identity receipt digest mismatch")
    try:
        receipt = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HumanEvaluationError("invalid runtime identity receipt JSON") from exc
    expected_keys = {
        "schema", "assignment_design_sha256", "policy",
        "identity_only", "human_traffic_authorized",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_keys:
        raise HumanEvaluationError("invalid runtime identity receipt fields")
    if (receipt.get("schema") != RUNTIME_RECEIPT_SCHEMA
            or receipt.get("identity_only") is not True
            or receipt.get("human_traffic_authorized") is not False):
        raise HumanEvaluationError("invalid runtime identity receipt authority")
    if receipt.get("assignment_design_sha256") != \
            context.assignment_design_sha256:
        raise HumanEvaluationError(
            "runtime identity receipt design does not match assignment")
    policy = receipt.get("policy")
    if not isinstance(policy, dict) or set(policy) != {
            "policy", "git", "image_sha256", "ballot_id"}:
        raise HumanEvaluationError("invalid runtime policy identity fields")
    expected = asdict(context.active_policy_identity)
    if policy != expected:
        raise HumanEvaluationError(
            "runtime policy identity does not match assignment")
    return reopen_assigned_policy(
        context, runtime_git=policy["git"],
        runtime_image_sha256=policy["image_sha256"])


def assignment_slot_id(context: HumanEvaluationContext) -> str:
    """Public, secret-independent identity for one pair/block slot."""
    if not isinstance(context, HumanEvaluationContext):
        raise HumanEvaluationError("invalid evaluation context")
    raw = "\0".join((
        SCHEMA,
        context.assignment_design_sha256,
        context.participant_pair_id,
        context.block_id,
        str(context.block_slot),
    )).encode()
    return hashlib.sha256(raw).hexdigest()


def reserve_assignment_once(
        context: HumanEvaluationContext, *, ledger_root: str | Path) -> dict:
    """Durably consume one reviewed pair/block slot without traffic authority.

    The slot identity excludes the assignment secret and derived session ID,
    so rotating the secret cannot reissue the same reviewed block slot.  An
    interrupted write remains consumed in place; callers may never delete or
    retry it into apparently complete evidence.
    """
    slot_id = assignment_slot_id(context)
    root = Path(ledger_root)
    try:
        listed = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise HumanEvaluationError("assignment ledger root is unavailable") from exc
    if (not stat.S_ISDIR(listed.st_mode)
            or resolved != root.absolute()):
        raise HumanEvaluationError(
            "assignment ledger root must be a real existing directory")
    receipt = {
        "schema": ASSIGNMENT_RESERVATION_SCHEMA,
        "assignment_design_sha256": context.assignment_design_sha256,
        "assignment_slot_id": slot_id,
        "session_id": context.session_id,
        "participant_pair_id": context.participant_pair_id,
        "block_id": context.block_id,
        "block_slot": context.block_slot,
        "arm": context.arm,
        "active_policy": asdict(context.active_policy_identity),
        "identity_only": True,
        "human_traffic_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    raw = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"),
    ).encode() + b"\n"
    name = f"slot-{slot_id}.json"
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise HumanEvaluationError("cannot open assignment ledger root") from exc
    descriptor = None
    try:
        opened_root = os.fstat(root_descriptor)
        if (not stat.S_ISDIR(opened_root.st_mode)
                or (opened_root.st_dev, opened_root.st_ino)
                != (listed.st_dev, listed.st_ino)):
            raise HumanEvaluationError(
                "assignment ledger root changed before open")
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(
                name, file_flags, 0o600, dir_fd=root_descriptor)
        except FileExistsError as exc:
            raise HumanEvaluationError(
                "assignment block slot was already reserved") from exc
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short assignment reservation write")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size != len(raw)):
            raise HumanEvaluationError(
                "assignment reservation publication is not stable")
        os.fsync(root_descriptor)
    except HumanEvaluationError:
        raise
    except OSError as exc:
        raise HumanEvaluationError(
            "cannot publish assignment reservation") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(root_descriptor)
    return {
        "path": str(root / name),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "assignment_slot_id": slot_id,
    }
