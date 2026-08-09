"""Fail-closed identity primitives for a future human-vs-bot evaluation.

This module does not enable an experiment.  It defines the immutable fields a
reviewed room assignment must carry and a balanced, hidden two-session block
schedule.  Production room creation has no path to construct this context yet.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Literal


SCHEMA = "human-vs-bot-evaluation-v1"
ARMS = ("candidate", "champion")
HUMAN_SEATS = (0, 2)
BOT_SEATS = (1, 3)
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$")
_PSEUDONYM = re.compile(r"^[0-9a-f]{16,64}$")
_GIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HumanEvaluationError(ValueError):
    """The proposed room identity is not evidence-grade."""


def _require(pattern: re.Pattern[str], value: str, field: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise HumanEvaluationError(f"invalid {field}")


def blocked_arm(*, assignment_secret: bytes, participant_pair_id: str,
                block_id: str, block_slot: int) -> Literal["candidate", "champion"]:
    """Return one complementary arm per slot in a hidden two-session block."""
    if not isinstance(assignment_secret, bytes) or len(assignment_secret) < 32:
        raise HumanEvaluationError("assignment secret must contain >=32 bytes")
    _require(_PSEUDONYM, participant_pair_id, "participant_pair_id")
    _require(_ID, block_id, "block_id")
    if block_slot not in (0, 1) or isinstance(block_slot, bool):
        raise HumanEvaluationError("block_slot must be 0 or 1")
    message = f"{SCHEMA}\0{participant_pair_id}\0{block_id}".encode()
    first = hmac.new(assignment_secret, message, hashlib.sha256).digest()[0] & 1
    candidate_slot = first
    return "candidate" if block_slot == candidate_slot else "champion"


@dataclass(frozen=True)
class HumanEvaluationContext:
    """Immutable assignment/log identity; never serialized to client state."""

    experiment_id: str
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
    ballot_id: str

    def __post_init__(self) -> None:
        for field in ("experiment_id", "session_id", "cohort_id",
                      "consent_version", "block_id", "candidate_policy",
                      "champion_policy", "ballot_id"):
            _require(_ID, getattr(self, field), field)
        _require(_PSEUDONYM, self.participant_pair_id, "participant_pair_id")
        if (not isinstance(self.participant_ids_by_human_seat, tuple)
                or len(self.participant_ids_by_human_seat) != 2
                or len(set(self.participant_ids_by_human_seat)) != 2):
            raise HumanEvaluationError(
                "two distinct participant IDs are required for seats 0 and 2")
        for value in self.participant_ids_by_human_seat:
            _require(_PSEUDONYM, value, "participant_id")
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

    @property
    def active_policy(self) -> str:
        return (self.candidate_policy if self.arm == "candidate"
                else self.champion_policy)

    def log_payload(self) -> dict:
        """Return the complete server-only identity attached to every event."""
        return {
            "schema": SCHEMA,
            "experiment_id": self.experiment_id,
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
            },
            "champion": {
                "policy": self.champion_policy,
                "git": self.champion_git,
                "image_sha256": self.champion_image_sha256,
            },
            "active_policy": self.active_policy,
            "ballot_id": self.ballot_id,
            "training_excluded": True,
            "candidate_selection_excluded": True,
            "production_promotion_gate": True,
            "policy_hidden_from_players": True,
        }
