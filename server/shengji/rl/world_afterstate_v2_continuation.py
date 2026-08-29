"""Materialize sealed V2 continuation outcomes from population material.

This is the narrow source bridge between the outcome-blind population and the
typed V2 label consumer.  The engine-owned continuation implementation remains
the only simulator; this module only supplies its domain-separated identity,
reopens its receipts, and binds the resulting category to a candidate row.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError,
    category_signed_level,
    reopen_afterstate_audit,
    validate_outcome,
)
from .world_afterstate_label import (
    continuation_identity,
    reopen_afterstate_continuation,
    run_afterstate_continuation,
    validate_continuation_identity,
)
from .world_afterstate_v2_label import ContinuationOutcomeV2
from .world_afterstate_v2_population import PopulationMaterialV2


SCHEMA = "world-afterstate-v2-continuation-bundle-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-raw-label-receipt-v1"
IDENTITY_EXPERIMENT = "world-afterstate-v2-continuation-v1"
REPLICATES = tuple(range(8))
AUTHORITY = {
    "dataset_opening_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
    "cli_authorized": False,
}


class WorldAfterstateV2ContinuationError(ValueError):
    """A V2 continuation receipt, row, or bundle binding drifted."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ContinuationError(f"{label} drift")
    return value


def _point_bucket(points: object) -> str:
    if isinstance(points, bool) or not isinstance(points, int) or points < 0:
        raise WorldAfterstateV2ContinuationError("points bucket source drift")
    if points < 40:
        return "0-39"
    if points < 80:
        return "40-79"
    if points < 120:
        return "80-119"
    if points < 160:
        return "120-159"
    return "160+"


def _audit(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV2ContinuationError("audit bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "audit is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2ContinuationError("audit canonical bytes drift")
    try:
        reopen_afterstate_audit(value)
    except WorldAfterstateError as exc:
        raise WorldAfterstateV2ContinuationError(
            "audit reconstruction drift") from exc
    return value


def _identity(material: PopulationMaterialV2, replica: int) -> dict[str, Any]:
    # ``state_sha256`` is the state group identity.  No candidate, attempted
    # action, successor, or candidate-set value enters this identity.
    return continuation_identity(
        experiment_id=IDENTITY_EXPERIMENT,
        state_group_id=material.state_sha256,
        fold=material.state.split,
        world_occurrence=0,
        replicate=replica,
    )


@dataclass(frozen=True)
class RawLabelReceiptV2:
    """Private canonical engine label bytes and their immutable identity."""

    candidate_index: int
    replica: int
    continuation_sha256: str
    raw: bytes
    raw_sha256: str
    schema: str = RECEIPT_SCHEMA

    def validate(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise WorldAfterstateV2ContinuationError("label receipt schema drift")
        if isinstance(self.candidate_index, bool) or not isinstance(
                self.candidate_index, int) or self.candidate_index < 0:
            raise WorldAfterstateV2ContinuationError("label candidate index drift")
        if isinstance(self.replica, bool) or self.replica not in REPLICATES:
            raise WorldAfterstateV2ContinuationError("label replica drift")
        _digest(self.continuation_sha256, "label continuation SHA-256")
        if type(self.raw) is not bytes or _sha_bytes(self.raw) != self.raw_sha256:
            raise WorldAfterstateV2ContinuationError("label raw byte binding drift")
        _digest(self.raw_sha256, "label raw SHA-256")
        try:
            value = json.loads(self.raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "label raw bytes are not canonical JSON") from exc
        if type(value) is not dict or canonical_json_bytes(value) != self.raw:
            raise WorldAfterstateV2ContinuationError("label raw canonical bytes drift")
        try:
            identity = value["continuation_identity"]
            validate_continuation_identity(identity)
        except (KeyError, TypeError, WorldAfterstateError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "label identity reconstruction drift") from exc
        if _sha(identity) != self.continuation_sha256:
            raise WorldAfterstateV2ContinuationError(
                "label continuation identity/hash drift")
        if identity["replicate"] != self.replica:
            raise WorldAfterstateV2ContinuationError(
                "label replica/identity binding drift")

    @property
    def raw_bytes(self) -> bytes:
        return self.raw

    @property
    def raw_label(self) -> bytes:
        return self.raw

    @property
    def continuation_identity(self) -> dict[str, Any]:
        value = json.loads(self.raw.decode("ascii"))
        return copy.deepcopy(value["continuation_identity"])


@dataclass(frozen=True)
class ContinuationBundleV2:
    """One state, complete candidate set, and all 8xN sealed label rows."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    candidates: tuple[ContinuationOutcomeV2, ...]
    labels: tuple[RawLabelReceiptV2, ...]
    canonical_bytes: bytes
    bundle_sha256: str
    schema: str = SCHEMA
    authority: Mapping[str, bool] = field(
        default_factory=lambda: dict(AUTHORITY))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "candidates": [row.__dict__ for row in self.candidates],
            "labels": [
                {
                    "schema": receipt.schema,
                    "candidate_index": receipt.candidate_index,
                    "replica": receipt.replica,
                    "continuation_sha256": receipt.continuation_sha256,
                    "raw": json.loads(receipt.raw.decode("ascii")),
                    "raw_sha256": receipt.raw_sha256,
                }
                for receipt in self.labels
            ],
            "authority": dict(self.authority),
        }

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise WorldAfterstateV2ContinuationError("bundle schema/authority drift")
        for label, value in (("bundle deal SHA-256", self.deal_sha256),
                             ("bundle slot SHA-256", self.slot_sha256),
                             ("bundle state SHA-256", self.state_sha256),
                             ("bundle candidate-set SHA-256",
                              self.candidate_set_sha256),
                             ("bundle SHA-256", self.bundle_sha256)):
            _digest(value, label)
        if type(self.canonical_bytes) is not bytes:
            raise WorldAfterstateV2ContinuationError("bundle canonical bytes drift")
        try:
            encoded = json.loads(self.canonical_bytes.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "bundle canonical JSON drift") from exc
        if canonical_json_bytes(encoded) != self.canonical_bytes \
                or encoded != self._payload():
            raise WorldAfterstateV2ContinuationError(
                "bundle canonical reconstruction drift")
        if _sha_bytes(self.canonical_bytes) != self.bundle_sha256:
            raise WorldAfterstateV2ContinuationError("bundle hash drift")
        if type(self.candidates) is not tuple or not self.candidates \
                or type(self.labels) is not tuple:
            raise WorldAfterstateV2ContinuationError("bundle population drift")
        if len(self.candidates) < 2 * len(REPLICATES) \
                or len(self.labels) != len(self.candidates):
            raise WorldAfterstateV2ContinuationError("bundle label population drift")
        indexes = sorted({row.candidate_index for row in self.candidates})
        count = len(indexes)
        if indexes != list(range(count)) \
                or len(self.candidates) != count * len(REPLICATES):
            raise WorldAfterstateV2ContinuationError("bundle candidate index drift")
        successors = []
        rows_by_key: dict[tuple[int, int], ContinuationOutcomeV2] = {}
        for row in self.candidates:
            if type(row) is not ContinuationOutcomeV2:
                raise WorldAfterstateV2ContinuationError("bundle outcome type drift")
            try:
                row.validate()
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "bundle outcome validation drift") from exc
            if (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256) != (
                        self.deal_sha256, self.slot_sha256, self.state_sha256,
                        self.candidate_set_sha256):
                raise WorldAfterstateV2ContinuationError(
                    "bundle outcome state binding drift")
            if row.protected_incumbent != (row.candidate_index == 0):
                raise WorldAfterstateV2ContinuationError(
                    "bundle incumbent/index drift")
            if row.replica not in REPLICATES:
                raise WorldAfterstateV2ContinuationError(
                    "bundle replica population drift")
            key = (row.candidate_index, row.replica)
            if key in rows_by_key:
                raise WorldAfterstateV2ContinuationError("bundle outcome duplicate")
            rows_by_key[key] = row
        for index in indexes:
            candidate_successors = {
                rows_by_key[(index, replica)].successor_sha256
                for replica in REPLICATES}
            if len(candidate_successors) != 1:
                raise WorldAfterstateV2ContinuationError(
                    "bundle successor identity drift")
            successors.append(next(iter(candidate_successors)))
        # Reuse the exact digest recipe consumed by the typed label consumer.
        expected_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": self.state_sha256,
            "successor_sha256s": successors,
        })
        if expected_set != self.candidate_set_sha256:
            raise WorldAfterstateV2ContinuationError("bundle candidate-set drift")
        by_key: dict[tuple[int, int], RawLabelReceiptV2] = {}
        for receipt in self.labels:
            if type(receipt) is not RawLabelReceiptV2:
                raise WorldAfterstateV2ContinuationError("bundle label type drift")
            receipt.validate()
            key = (receipt.candidate_index, receipt.replica)
            if key in by_key or receipt.candidate_index not in range(count):
                raise WorldAfterstateV2ContinuationError(
                    "bundle label candidate/replica drop or duplicate")
            by_key[key] = receipt
            identity = receipt.continuation_identity
            expected = _identity_from_fields(self.state_sha256,
                                             rows_by_key[(0, 0)].split,
                                             receipt.replica)
            if identity != expected:
                raise WorldAfterstateV2ContinuationError(
                    "bundle continuation identity drift")
            if receipt.continuation_sha256 != _sha(identity):
                raise WorldAfterstateV2ContinuationError(
                    "bundle continuation hash drift")
            label = json.loads(receipt.raw.decode("ascii"))
            candidate = rows_by_key[(receipt.candidate_index, receipt.replica)]
            if label.get("successor_sha256") != candidate.successor_sha256:
                raise WorldAfterstateV2ContinuationError(
                    "bundle label successor binding drift")
            try:
                validate_outcome(label["outcome"])
            except (KeyError, WorldAfterstateError) as exc:
                raise WorldAfterstateV2ContinuationError(
                    "bundle raw outcome mechanics drift") from exc
            if label["outcome"]["signed_level_category"] != \
                    candidate.signed_level_category:
                raise WorldAfterstateV2ContinuationError(
                    "bundle category binding drift")
            if label["outcome"]["root_is_attacker"] != (
                    candidate.role == "attacker"):
                raise WorldAfterstateV2ContinuationError(
                    "bundle perspective binding drift")
        expected_keys = {(index, replica) for index in range(count)
                         for replica in REPLICATES}
        if set(by_key) != expected_keys:
            raise WorldAfterstateV2ContinuationError("bundle label population drift")
        for key, row in rows_by_key.items():
            index, replica = key
            receipt = by_key[(index, replica)]
            if receipt.continuation_sha256 != row.continuation_sha256:
                raise WorldAfterstateV2ContinuationError(
                    "bundle sibling continuation binding drift")
        for index in indexes:
            for replica in REPLICATES:
                receipt = by_key[(index, replica)]
                if receipt.continuation_sha256 != rows_by_key[(index, replica)].continuation_sha256:
                    raise WorldAfterstateV2ContinuationError(
                        "bundle sibling continuation binding drift")

    @property
    def raw_label_receipts(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def raw_labels(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def outcomes(self) -> tuple[ContinuationOutcomeV2, ...]:
        return self.candidates

    @property
    def outcome_rows(self) -> tuple[ContinuationOutcomeV2, ...]:
        return self.candidates

    @property
    def label_receipts(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def sealed_bytes(self) -> bytes:
        return self.canonical_bytes

    @property
    def sha256(self) -> str:
        return self.bundle_sha256

    def reopen(self, material: PopulationMaterialV2) -> "ContinuationBundleV2":
        """Reconstruct this seal from the retained private population material."""
        return reopen_continuation_bundle_v2(self, material)


def _identity_from_fields(state_sha256: str, fold: str,
                          replica: int) -> dict[str, Any]:
    return continuation_identity(
        experiment_id=IDENTITY_EXPERIMENT, state_group_id=state_sha256,
        fold=fold, world_occurrence=0, replicate=replica)


def build_continuation_bundle_v2(
        material: PopulationMaterialV2) -> ContinuationBundleV2:
    """Run/reopen all eight CRN labels for every validated candidate."""
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2ContinuationError("population material type drift")
    try:
        material.validate()
    except Exception as exc:
        raise WorldAfterstateV2ContinuationError(
            "population material validation drift") from exc
    state = material.state
    points = material.prestate.get("public", {}).get("attacker_points")
    points_bucket = _point_bucket(points)
    identities = {replica: _identity(material, replica) for replica in REPLICATES}
    continuation_hashes = {replica: _sha(identity)
                           for replica, identity in identities.items()}
    rows: list[ContinuationOutcomeV2] = []
    receipts: list[RawLabelReceiptV2] = []
    for candidate_index, raw_audit in enumerate(material.private_audit_raws):
        audit = _audit(raw_audit)
        if audit.get("successor_sha256") != material.candidates[candidate_index].successor_sha256:
            raise WorldAfterstateV2ContinuationError(
                "audit/candidate successor binding drift")
        for replica in REPLICATES:
            identity = identities[replica]
            try:
                label = run_afterstate_continuation(audit, identity)
                raw_label = canonical_json_bytes(label)
                reopened = reopen_afterstate_continuation(audit, label)
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "engine continuation run/reopen failed") from exc
            if canonical_json_bytes(reopened) != raw_label:
                raise WorldAfterstateV2ContinuationError(
                    "engine continuation reopen drift")
            if reopened.get("successor_sha256") != audit["successor_sha256"]:
                raise WorldAfterstateV2ContinuationError(
                    "continuation successor binding drift")
            outcome = reopened.get("outcome")
            if type(outcome) is not dict:
                raise WorldAfterstateV2ContinuationError("continuation outcome drift")
            try:
                validate_outcome(outcome)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2ContinuationError(
                    "continuation outcome mechanics drift") from exc
            category = outcome.get("signed_level_category")
            try:
                category_signed_level(category)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2ContinuationError(
                    "continuation category drift") from exc
            if outcome.get("root_is_attacker") != (
                    audit.get("root_seat") is not None and
                    reopen_afterstate_audit(audit).is_attacker(audit["root_seat"])):
                raise WorldAfterstateV2ContinuationError(
                    "continuation perspective mismatch")
            receipt = RawLabelReceiptV2(
                candidate_index=candidate_index, replica=replica,
                continuation_sha256=continuation_hashes[replica],
                raw=raw_label, raw_sha256=_sha_bytes(raw_label))
            receipt.validate()
            receipts.append(receipt)
            rows.append(ContinuationOutcomeV2(
                deal_sha256=state.deal_sha256, slot_sha256=state.slot_sha256,
                state_sha256=state.state_sha256,
                candidate_set_sha256=material.candidate_set_sha256,
                source=state.source, split=state.split, role=state.role,
                phase=state.phase, position=state.position,
                trump_rank=state.trump_rank, trump_mode=state.trump_mode,
                points_bucket=points_bucket, candidate_index=candidate_index,
                protected_incumbent=candidate_index == 0,
                successor_sha256=material.candidates[candidate_index].successor_sha256,
                continuation_sha256=continuation_hashes[replica],
                replica=replica, signed_level_category=int(category)))
    candidate_rows = tuple(rows)
    label_rows = tuple(receipts)
    body = {
        "schema": SCHEMA,
        "deal_sha256": state.deal_sha256,
        "slot_sha256": state.slot_sha256,
        "state_sha256": state.state_sha256,
        "candidate_set_sha256": material.candidate_set_sha256,
        "candidates": [row.__dict__ for row in candidate_rows],
        "labels": [
            {"schema": receipt.schema, "candidate_index": receipt.candidate_index,
             "replica": receipt.replica,
             "continuation_sha256": receipt.continuation_sha256,
             "raw": json.loads(receipt.raw.decode("ascii")),
             "raw_sha256": receipt.raw_sha256}
            for receipt in label_rows
        ],
        "authority": dict(AUTHORITY),
    }
    canonical = canonical_json_bytes(body)
    bundle = ContinuationBundleV2(
        deal_sha256=state.deal_sha256, slot_sha256=state.slot_sha256,
        state_sha256=state.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        candidates=candidate_rows, labels=label_rows,
        canonical_bytes=canonical, bundle_sha256=_sha_bytes(canonical))
    bundle.validate()
    return bundle


def validate_continuation_bundle_v2(value: ContinuationBundleV2) -> None:
    if type(value) is not ContinuationBundleV2:
        raise WorldAfterstateV2ContinuationError("bundle type drift")
    value.validate()


def reopen_continuation_bundle_v2(
        value: ContinuationBundleV2 | bytes, material: PopulationMaterialV2) \
        -> ContinuationBundleV2:
    """Reopen immutable rows without repeating expensive continuations."""
    raw = value.canonical_bytes if isinstance(value, ContinuationBundleV2) \
        else value
    if type(raw) is not bytes:
        raise WorldAfterstateV2ContinuationError("bundle raw bytes drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "bundle raw JSON drift") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw \
            or set(payload) != {"schema", "deal_sha256", "slot_sha256",
                                "state_sha256", "candidate_set_sha256",
                                "candidates", "labels", "authority"}:
        raise WorldAfterstateV2ContinuationError("bundle raw schema drift")
    try:
        candidates = tuple(ContinuationOutcomeV2(**row)
                           for row in payload["candidates"])
        labels = tuple(RawLabelReceiptV2(
            schema=row["schema"], candidate_index=row["candidate_index"],
            replica=row["replica"],
            continuation_sha256=row["continuation_sha256"],
            raw=canonical_json_bytes(row["raw"]),
            raw_sha256=row["raw_sha256"])
                       for row in payload["labels"])
        reopened = ContinuationBundleV2(
            deal_sha256=payload["deal_sha256"],
            slot_sha256=payload["slot_sha256"],
            state_sha256=payload["state_sha256"],
            candidate_set_sha256=payload["candidate_set_sha256"],
            candidates=candidates, labels=labels, canonical_bytes=raw,
            bundle_sha256=_sha_bytes(raw), schema=payload["schema"],
            authority=payload["authority"])
        reopened.validate()
        material.validate()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "bundle typed reconstruction drift") from exc
    state = material.state
    if (reopened.deal_sha256, reopened.slot_sha256,
            reopened.state_sha256, reopened.candidate_set_sha256) != (
                state.deal_sha256, state.slot_sha256, state.state_sha256,
                material.candidate_set_sha256):
        raise WorldAfterstateV2ContinuationError(
            "bundle population material binding drift")
    candidate_count = len(material.candidates)
    if len(reopened.candidates) != candidate_count * len(REPLICATES):
        raise WorldAfterstateV2ContinuationError(
            "bundle material candidate population drift")
    by_label = {(row.candidate_index, row.replica): row
                for row in reopened.labels}
    by_outcome = {(row.candidate_index, row.replica): row
                  for row in reopened.candidates}
    for candidate_index, (candidate, audit_raw) in enumerate(zip(
            material.candidates, material.private_audit_raws, strict=True)):
        audit = _audit(audit_raw)
        for replica in REPLICATES:
            receipt = by_label[(candidate_index, replica)]
            outcome_row = by_outcome[(candidate_index, replica)]
            label = json.loads(receipt.raw.decode("ascii"))
            try:
                reconstructed = reopen_afterstate_continuation(audit, label)
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "sealed continuation reconstruction drift") from exc
            if (canonical_json_bytes(reconstructed) != receipt.raw
                    or label.get("successor_sha256") !=
                    candidate.successor_sha256
                    or outcome_row.successor_sha256 !=
                    candidate.successor_sha256):
                raise WorldAfterstateV2ContinuationError(
                    "sealed continuation material binding drift")
    return reopened


# Descriptive aliases keep the source layer discoverable to pipeline callers.
build_continuation_outcomes_v2 = build_continuation_bundle_v2
materialize_continuation_v2 = build_continuation_bundle_v2
reopen_continuation_v2 = reopen_continuation_bundle_v2
validate_continuation_v2 = validate_continuation_bundle_v2


__all__ = [
    "AUTHORITY", "IDENTITY_EXPERIMENT", "RECEIPT_SCHEMA", "REPLICATES",
    "SCHEMA", "ContinuationBundleV2", "RawLabelReceiptV2",
    "WorldAfterstateV2ContinuationError", "build_continuation_bundle_v2",
    "build_continuation_outcomes_v2", "materialize_continuation_v2",
    "reopen_continuation_bundle_v2", "reopen_continuation_v2",
    "validate_continuation_bundle_v2", "validate_continuation_v2",
]
