"""Typed, score-free provenance for the Value-Afterstate V2 terminal.

The records in this module are deliberately only receipts.  They bind the
already-produced hashes which a terminal verifier is given, but never open a
file, execute a worker, read a label, or grant authority to do any of those
things.  Ordered populations are used throughout so that a rehashed but
reordered (or truncated) receipt cannot look complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes


AUDIT_PROVENANCE_SCHEMA = "world-afterstate-v2-audit-provenance-v1"
RECONSTRUCTION_SCHEMA = (
    "world-afterstate-v2-independent-reconstruction-receipt-v1")

COHORT_LABELS = (
    "natural:block-1",
    "action-association-permutation:block-1",
    "label-permutation:block-1",
    "complete-world-shuffle:block-1",
    "natural:block-2",
    "complete-world-shuffle:block-2",
)
UPSTREAM_RECEIPT_LABELS = (
    "p0", "optimizer_canary", "precision_select", "model_selector_power")
COMPARISON_LABELS = (
    "association:b1", "label:b1", "world:b1", "world:b2")
DOSE_LABELS = ("association", "label", "world")

# This is intentionally a closed, all-false map.  A provenance record is not
# an admission, an execution lease, or a deployment decision.
AUTHORITY = {
    "data_opening_authorized": False,
    "label_opening_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "terminal_route_authorized": False,
    "reconstruction_authorized": False,
    "execution_authorized": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2TerminalProvenanceError(ValueError):
    """A V2 terminal provenance or reconstruction receipt drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2TerminalProvenanceError(f"{label} drift")
    return value


def _ordered_digests(value: object, expected: tuple[str, ...], label: str) \
        -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple or len(value) != len(expected):
        raise WorldAfterstateV2TerminalProvenanceError(
            f"{label} population drift")
    rows: list[tuple[str, str]] = []
    for row, wanted in zip(value, expected, strict=True):
        if type(row) is not tuple or len(row) != 2 or row[0] != wanted:
            raise WorldAfterstateV2TerminalProvenanceError(
                f"{label} order drift")
        _digest(row[1], f"{label} {wanted}")
        rows.append(row)
    return tuple(rows)


def _authority(value: object, label: str) -> None:
    if value != AUTHORITY or any(type(item) is not bool or item
                                 for item in AUTHORITY.values()):
        raise WorldAfterstateV2TerminalProvenanceError(
            f"{label} authority drift")


@dataclass(frozen=True)
class AuditProvenanceV2:
    """The complete, one-opening audit input population.

    Every ``*_sha256s`` member is an ordered ``(label, digest)`` tuple.  The
    labels are fixed by the V2 design and are checked independently for each
    population, which makes coordinated rehashing unable to hide a dropped,
    extra, or reordered artifact.
    """

    freeze_sha256: str
    admission_sha256: str
    audit_attempt_sha256: str
    audit_opened_count: int
    continuation_manifest_sha256: str
    prediction_manifest_sha256s: tuple[tuple[str, str], ...]
    checkpoint_manifest_sha256s: tuple[tuple[str, str], ...]
    cohort_manifest_sha256s: tuple[tuple[str, str], ...]
    evaluation_result_sha256s: tuple[tuple[str, str], ...]
    upstream_receipt_sha256s: tuple[tuple[str, str], ...]
    comparison_sha256s: tuple[tuple[str, str], ...]
    dose_sha256s: tuple[tuple[str, str], ...]
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    schema: str = AUDIT_PROVENANCE_SCHEMA

    def validate(self) -> None:
        if self.schema != AUDIT_PROVENANCE_SCHEMA:
            raise WorldAfterstateV2TerminalProvenanceError(
                "audit provenance schema drift")
        for value, label in (
                (self.freeze_sha256, "external freeze SHA-256"),
                (self.admission_sha256, "admission SHA-256"),
                (self.audit_attempt_sha256, "durable audit-attempt SHA-256"),
                (self.continuation_manifest_sha256,
                 "audit continuation-manifest SHA-256")):
            _digest(value, label)
        if (isinstance(self.audit_opened_count, bool)
                or not isinstance(self.audit_opened_count, int)
                or self.audit_opened_count != 1):
            raise WorldAfterstateV2TerminalProvenanceError(
                "audit opened count drift")
        _ordered_digests(self.prediction_manifest_sha256s, COHORT_LABELS,
                         "prediction manifest")
        _ordered_digests(self.checkpoint_manifest_sha256s, COHORT_LABELS,
                         "checkpoint manifest")
        _ordered_digests(self.cohort_manifest_sha256s, COHORT_LABELS,
                         "cohort manifest")
        _ordered_digests(self.evaluation_result_sha256s, COHORT_LABELS,
                         "evaluation result")
        _ordered_digests(self.upstream_receipt_sha256s,
                         UPSTREAM_RECEIPT_LABELS, "upstream receipt")
        _ordered_digests(self.comparison_sha256s, COMPARISON_LABELS,
                         "comparison")
        _ordered_digests(self.dose_sha256s, DOSE_LABELS, "dose")
        _authority(self.authority, "audit provenance")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "freeze_sha256": self.freeze_sha256,
            "admission_sha256": self.admission_sha256,
            "audit_attempt_sha256": self.audit_attempt_sha256,
            "audit_opened_count": self.audit_opened_count,
            "continuation_manifest_sha256": self.continuation_manifest_sha256,
            "prediction_manifest_sha256s": [list(row)
                                             for row in self.prediction_manifest_sha256s],
            "checkpoint_manifest_sha256s": [list(row)
                                             for row in self.checkpoint_manifest_sha256s],
            "cohort_manifest_sha256s": [list(row)
                                         for row in self.cohort_manifest_sha256s],
            "evaluation_result_sha256s": [list(row)
                                           for row in self.evaluation_result_sha256s],
            "upstream_receipt_sha256s": [list(row)
                                          for row in self.upstream_receipt_sha256s],
            "comparison_sha256s": [list(row) for row in self.comparison_sha256s],
            "dose_sha256s": [list(row) for row in self.dose_sha256s],
            "authority": dict(AUTHORITY),
        }

    def sha256(self) -> str:
        return _sha(self.payload())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())

    # Short descriptive aliases keep callers from having to infer whether a
    # digest is a manifest or a result while retaining one canonical payload.
    @property
    def prediction_digests(self) -> tuple[tuple[str, str], ...]:
        return self.prediction_manifest_sha256s

    @property
    def external_freeze_sha256(self) -> str:
        """Compatibility spelling for the externally supplied freeze hash."""
        return self.freeze_sha256

    @property
    def audit_continuation_manifest_sha256(self) -> str:
        return self.continuation_manifest_sha256

    @property
    def checkpoint_digests(self) -> tuple[tuple[str, str], ...]:
        return self.checkpoint_manifest_sha256s

    @property
    def cohort_digests(self) -> tuple[tuple[str, str], ...]:
        return self.cohort_manifest_sha256s

    @property
    def evaluation_digests(self) -> tuple[tuple[str, str], ...]:
        return self.evaluation_result_sha256s


@dataclass(frozen=True)
class IndependentReconstructionReceiptV2:
    """A sealed-vs-independent terminal result comparison.

    A disagreement is retained as a valid negative receipt when ``matched``
    is false.  Since validation rederives that boolean from the two result
    hashes, a mismatching pair can never masquerade as a match.
    """

    provenance_sha256: str
    sealed_terminal_result_sha256: str
    independently_derived_terminal_result_sha256: str
    matched: bool
    verifier_sha256: str
    source_sha256: str
    runtime_sha256: str
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    schema: str = RECONSTRUCTION_SCHEMA

    def validate(self) -> None:
        if self.schema != RECONSTRUCTION_SCHEMA:
            raise WorldAfterstateV2TerminalProvenanceError(
                "reconstruction schema drift")
        for value, label in (
                (self.provenance_sha256, "provenance SHA-256"),
                (self.sealed_terminal_result_sha256,
                 "sealed terminal result SHA-256"),
                (self.independently_derived_terminal_result_sha256,
                 "independent terminal result SHA-256"),
                (self.verifier_sha256, "verifier SHA-256"),
                (self.source_sha256, "source SHA-256"),
                (self.runtime_sha256, "runtime SHA-256")):
            _digest(value, label)
        if type(self.matched) is not bool:
            raise WorldAfterstateV2TerminalProvenanceError(
                "reconstruction matched flag drift")
        expected = (self.sealed_terminal_result_sha256
                    == self.independently_derived_terminal_result_sha256)
        if self.matched is not expected:
            raise WorldAfterstateV2TerminalProvenanceError(
                "reconstruction matched rederivation drift")
        _authority(self.authority, "reconstruction")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "provenance_sha256": self.provenance_sha256,
            "sealed_terminal_result_sha256": self.sealed_terminal_result_sha256,
            "independently_derived_terminal_result_sha256": (
                self.independently_derived_terminal_result_sha256),
            "matched": self.matched,
            "verifier_sha256": self.verifier_sha256,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "authority": dict(AUTHORITY),
        }

    def sha256(self) -> str:
        return _sha(self.payload())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


def validate_audit_provenance_v2(value: AuditProvenanceV2) -> None:
    if type(value) is not AuditProvenanceV2:
        raise WorldAfterstateV2TerminalProvenanceError(
            "audit provenance type drift")
    value.validate()


def validate_independent_reconstruction_v2(
        value: IndependentReconstructionReceiptV2) -> None:
    if type(value) is not IndependentReconstructionReceiptV2:
        raise WorldAfterstateV2TerminalProvenanceError(
            "reconstruction receipt type drift")
    value.validate()


validate_independent_reconstruction_receipt_v2 = \
    validate_independent_reconstruction_v2
WorldAfterstateV2ProvenanceError = WorldAfterstateV2TerminalProvenanceError


# Naming aliases used by nearby terminal modules.
TerminalProvenanceV2 = AuditProvenanceV2
IndependentReconstructionV2 = IndependentReconstructionReceiptV2


__all__ = [
    "AUDIT_PROVENANCE_SCHEMA", "AUTHORITY", "COHORT_LABELS",
    "COMPARISON_LABELS", "DOSE_LABELS", "IndependentReconstructionReceiptV2",
    "IndependentReconstructionV2", "RECONSTRUCTION_SCHEMA",
    "TerminalProvenanceV2", "UPSTREAM_RECEIPT_LABELS", "AuditProvenanceV2",
    "WorldAfterstateV2TerminalProvenanceError",
    "WorldAfterstateV2ProvenanceError", "validate_audit_provenance_v2",
    "validate_independent_reconstruction_receipt_v2",
    "validate_independent_reconstruction_v2",
]
