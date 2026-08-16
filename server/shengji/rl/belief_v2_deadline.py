"""Fail-closed, monotonic in-loop deadline mechanics for BELIEF-V1 V2.

The freeze supplies measured next-unit wall estimates and one reserve.  Long
stages call the guard before starting each indivisible unit and again before
publishing a final artifact.  Expiry is data: the controller must persist the
canonical refusal in its already-created partial slot, which remains occupied
and therefore cannot be retried under the same admission.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes


DEADLINE_REFUSAL_SCHEMA = "belief-v1-v2-stage-deadline-refusal-v1"
DEADLINE_REFUSAL_FILENAME = "deadline-refusal.json"
NS_PER_SECOND = 1_000_000_000


class BeliefV2DeadlineError(ValueError):
    """The next indivisible unit or final seal cannot fit before the cap."""

    def __init__(self, refusal: "V2DeadlineRefusalV1") -> None:
        super().__init__("V2 stage deadline exhausted")
        self.refusal = refusal


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class V2DeadlineRefusalV1:
    freeze_sha256: str
    admission_sha256: str
    stage: str
    slot: str
    phase: str
    next_unit_index: int
    started_monotonic_nanoseconds: int
    observed_monotonic_nanoseconds: int
    hard_deadline_monotonic_nanoseconds: int
    wall_cap_nanoseconds: int
    next_unit_wall_estimate_nanoseconds: int
    safety_reserve_nanoseconds: int
    required_remaining_nanoseconds: int
    observed_remaining_nanoseconds: int
    schema: str = DEADLINE_REFUSAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "freeze_sha256": self.freeze_sha256,
            "admission_sha256": self.admission_sha256,
            "stage": self.stage,
            "slot": self.slot,
            "phase": self.phase,
            "next_unit_index": self.next_unit_index,
            "started_monotonic_nanoseconds": (
                self.started_monotonic_nanoseconds),
            "observed_monotonic_nanoseconds": (
                self.observed_monotonic_nanoseconds),
            "hard_deadline_monotonic_nanoseconds": (
                self.hard_deadline_monotonic_nanoseconds),
            "wall_cap_nanoseconds": self.wall_cap_nanoseconds,
            "next_unit_wall_estimate_nanoseconds": (
                self.next_unit_wall_estimate_nanoseconds),
            "safety_reserve_nanoseconds": self.safety_reserve_nanoseconds,
            "required_remaining_nanoseconds": (
                self.required_remaining_nanoseconds),
            "observed_remaining_nanoseconds": (
                self.observed_remaining_nanoseconds),
            "reason": "next-unit-or-seal-cannot-fit-before-frozen-wall-cap",
            "stage_advanced_after_expiry": False,
            "final_artifact_sealed": False,
            "calibration_open_authorized": False,
            "test_split_open_authorized": False,
            "retry_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        _validate_refusal(self)
        return canonical_json_bytes(self.to_dict())


def _validate_refusal(row: V2DeadlineRefusalV1) -> None:
    if type(row) is not V2DeadlineRefusalV1 \
            or row.schema != DEADLINE_REFUSAL_SCHEMA \
            or not _is_sha256(row.freeze_sha256) \
            or not _is_sha256(row.admission_sha256) \
            or type(row.stage) is not str or not row.stage \
            or type(row.slot) is not str or not row.slot \
            or row.phase not in {"before-unit", "after-unit", "before-seal"} \
            or type(row.next_unit_index) is not int \
            or row.next_unit_index < 0 \
            or any(type(value) is not int or value <= 0 for value in (
                row.started_monotonic_nanoseconds,
                row.observed_monotonic_nanoseconds,
                row.hard_deadline_monotonic_nanoseconds,
                row.wall_cap_nanoseconds,
                row.next_unit_wall_estimate_nanoseconds,
                row.safety_reserve_nanoseconds,
                row.required_remaining_nanoseconds)) \
            or type(row.observed_remaining_nanoseconds) is not int \
            or row.hard_deadline_monotonic_nanoseconds \
            != row.started_monotonic_nanoseconds + row.wall_cap_nanoseconds \
            or row.observed_monotonic_nanoseconds \
            < row.started_monotonic_nanoseconds \
            or row.observed_remaining_nanoseconds \
            != row.hard_deadline_monotonic_nanoseconds \
            - row.observed_monotonic_nanoseconds \
            or row.observed_remaining_nanoseconds \
            >= row.required_remaining_nanoseconds:
        raise ValueError("V2 deadline refusal identity drift")


@dataclass(frozen=True)
class V2StageDeadlineV1:
    freeze_sha256: str
    admission_sha256: str
    stage: str
    slot: str
    started_monotonic_nanoseconds: int
    wall_cap_nanoseconds: int
    next_unit_wall_estimate_nanoseconds: int
    safety_reserve_nanoseconds: int

    def __post_init__(self) -> None:
        if not _is_sha256(self.freeze_sha256) \
                or not _is_sha256(self.admission_sha256) \
                or type(self.stage) is not str or not self.stage \
                or type(self.slot) is not str or not self.slot \
                or any(type(value) is not int or value <= 0 for value in (
                    self.started_monotonic_nanoseconds,
                    self.wall_cap_nanoseconds,
                    self.next_unit_wall_estimate_nanoseconds,
                    self.safety_reserve_nanoseconds)) \
                or self.next_unit_wall_estimate_nanoseconds \
                + self.safety_reserve_nanoseconds \
                >= self.wall_cap_nanoseconds:
            raise ValueError("V2 stage deadline identity drift")

    def check(self, *, phase: str, next_unit_index: int,
              observed_monotonic_nanoseconds: int) -> None:
        if phase == "before-unit":
            required = (self.next_unit_wall_estimate_nanoseconds
                        + self.safety_reserve_nanoseconds)
        elif phase in {"after-unit", "before-seal"}:
            required = self.safety_reserve_nanoseconds
        else:
            raise ValueError("V2 stage deadline phase drift")
        if type(next_unit_index) is not int or next_unit_index < 0 \
                or type(observed_monotonic_nanoseconds) is not int \
                or observed_monotonic_nanoseconds \
                < self.started_monotonic_nanoseconds:
            raise ValueError("V2 stage deadline observation drift")
        hard = (self.started_monotonic_nanoseconds
                + self.wall_cap_nanoseconds)
        remaining = hard - observed_monotonic_nanoseconds
        if remaining < required:
            raise BeliefV2DeadlineError(V2DeadlineRefusalV1(
                freeze_sha256=self.freeze_sha256,
                admission_sha256=self.admission_sha256,
                stage=self.stage, slot=self.slot, phase=phase,
                next_unit_index=next_unit_index,
                started_monotonic_nanoseconds=(
                    self.started_monotonic_nanoseconds),
                observed_monotonic_nanoseconds=(
                    observed_monotonic_nanoseconds),
                hard_deadline_monotonic_nanoseconds=hard,
                wall_cap_nanoseconds=self.wall_cap_nanoseconds,
                next_unit_wall_estimate_nanoseconds=(
                    self.next_unit_wall_estimate_nanoseconds),
                safety_reserve_nanoseconds=self.safety_reserve_nanoseconds,
                required_remaining_nanoseconds=required,
                observed_remaining_nanoseconds=remaining))


def publish_deadline_refusal(
        partial: Path, refusal: V2DeadlineRefusalV1) -> bytes:
    """Persist one exact refusal in the occupied, never-renamed stage slot."""
    if not isinstance(partial, Path) or partial.is_symlink() \
            or not partial.is_dir():
        raise ValueError("V2 deadline refusal partial slot drift")
    raw = refusal.canonical_bytes()
    publish_exclusive_bytes(partial / DEADLINE_REFUSAL_FILENAME, raw)
    return raw


def reopen_deadline_refusal(
        path: Path, *, freeze_sha256: str,
        admission_sha256: str) -> V2DeadlineRefusalV1:
    raw = stable_read_bytes(path)
    try:
        payload = json.loads(raw)
        row = V2DeadlineRefusalV1(
            freeze_sha256=payload["freeze_sha256"],
            admission_sha256=payload["admission_sha256"],
            stage=payload["stage"], slot=payload["slot"],
            phase=payload["phase"],
            next_unit_index=payload["next_unit_index"],
            started_monotonic_nanoseconds=(
                payload["started_monotonic_nanoseconds"]),
            observed_monotonic_nanoseconds=(
                payload["observed_monotonic_nanoseconds"]),
            hard_deadline_monotonic_nanoseconds=(
                payload["hard_deadline_monotonic_nanoseconds"]),
            wall_cap_nanoseconds=payload["wall_cap_nanoseconds"],
            next_unit_wall_estimate_nanoseconds=(
                payload["next_unit_wall_estimate_nanoseconds"]),
            safety_reserve_nanoseconds=(
                payload["safety_reserve_nanoseconds"]),
            required_remaining_nanoseconds=(
                payload["required_remaining_nanoseconds"]),
            observed_remaining_nanoseconds=(
                payload["observed_remaining_nanoseconds"]),
            schema=payload["schema"])
    except (KeyError, TypeError, json.JSONDecodeError,
            UnicodeDecodeError) as exc:
        raise ValueError("V2 deadline refusal is not canonical JSON") from exc
    _validate_refusal(row)
    if set(payload) != set(row.to_dict()) \
            or canonical_json_bytes(payload) != raw \
            or payload != row.to_dict() \
            or row.freeze_sha256 != freeze_sha256 \
            or row.admission_sha256 != admission_sha256:
        raise ValueError("V2 deadline refusal reconstruction drift")
    return row


def deadline_refusal_paths(root: Path) -> tuple[Path, ...]:
    """Return refusal files without following symlinked directories."""
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise ValueError("V2 deadline refusal root drift")
    result = []
    for parent, directories, files in os.walk(
            root, topdown=True, followlinks=False):
        base = Path(parent)
        directories[:] = sorted(name for name in directories
                                 if not (base / name).is_symlink())
        if DEADLINE_REFUSAL_FILENAME in files:
            result.append(base / DEADLINE_REFUSAL_FILENAME)
    return tuple(sorted(result))


def stage_deadline(
        freeze, admission, *, stage: str, slot: str,
        started_monotonic_nanoseconds: int) -> V2StageDeadlineV1:
    """Build the only deadline parameters permitted by the exact freeze."""
    caps = freeze.resource_caps
    if stage == "capture":
        wall_seconds = caps.capture_wall_seconds
        estimate = caps.capture_next_unit_wall_estimate_nanoseconds
    elif stage == "reference":
        wall_seconds = caps.reference_wall_seconds
        estimate = caps.reference_next_unit_wall_estimate_nanoseconds
    elif stage in {"device-qualification", "training"}:
        wall_seconds = caps.training_wall_seconds
        estimate = caps.training_next_epoch_wall_estimate_nanoseconds
    else:
        raise ValueError("V2 stage has no frozen deadline contract")
    return V2StageDeadlineV1(
        freeze_sha256=freeze.sha256(), admission_sha256=admission.sha256(),
        stage=stage, slot=slot,
        started_monotonic_nanoseconds=started_monotonic_nanoseconds,
        wall_cap_nanoseconds=wall_seconds * NS_PER_SECOND,
        next_unit_wall_estimate_nanoseconds=estimate,
        safety_reserve_nanoseconds=caps.deadline_safety_reserve_nanoseconds)
