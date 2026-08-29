from __future__ import annotations

import dataclasses
import hashlib

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_terminal_provenance import (
    AUTHORITY, COHORT_LABELS, COMPARISON_LABELS, DOSE_LABELS,
    UPSTREAM_RECEIPT_LABELS, AuditProvenanceV2,
    IndependentReconstructionReceiptV2,
    WorldAfterstateV2TerminalProvenanceError,
    validate_audit_provenance_v2, validate_independent_reconstruction_v2,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _rows(labels: tuple[str, ...], prefix: str) -> tuple[tuple[str, str], ...]:
    return tuple((label, _sha(f"{prefix}:{label}")) for label in labels)


def _audit(**changes) -> AuditProvenanceV2:
    body = dict(
        freeze_sha256=_sha("freeze"), admission_sha256=_sha("admission"),
        audit_attempt_sha256=_sha("attempt"), audit_opened_count=1,
        continuation_manifest_sha256=_sha("continuations"),
        prediction_manifest_sha256s=_rows(COHORT_LABELS, "prediction"),
        checkpoint_manifest_sha256s=_rows(COHORT_LABELS, "checkpoint"),
        cohort_manifest_sha256s=_rows(COHORT_LABELS, "cohort"),
        evaluation_result_sha256s=_rows(COHORT_LABELS, "evaluation"),
        upstream_receipt_sha256s=_rows(UPSTREAM_RECEIPT_LABELS, "upstream"),
        comparison_sha256s=_rows(COMPARISON_LABELS, "comparison"),
        dose_sha256s=_rows(DOSE_LABELS, "dose"),
    )
    body.update(changes)
    return AuditProvenanceV2(**body)


def _reconstruction(**changes) -> IndependentReconstructionReceiptV2:
    body = dict(
        provenance_sha256=_audit().sha256(),
        sealed_terminal_result_sha256=_sha("terminal"),
        independently_derived_terminal_result_sha256=_sha("terminal"),
        matched=True, verifier_sha256=_sha("verifier"),
        source_sha256=_sha("source"), runtime_sha256=_sha("runtime"),
    )
    body.update(changes)
    return IndependentReconstructionReceiptV2(**body)


def test_audit_payload_is_canonical_and_exactly_binds_all_populations():
    receipt = _audit()
    validate_audit_provenance_v2(receipt)
    raw = canonical_json_bytes(receipt.payload())
    assert raw.endswith(b"\n")
    assert raw == canonical_json_bytes(receipt.payload())
    assert receipt.sha256() == hashlib.sha256(raw).hexdigest()
    assert receipt.authority == AUTHORITY
    assert not any(AUTHORITY.values())


@pytest.mark.parametrize(("field", "kind"), (
    ("prediction_manifest_sha256s", "drop"),
    ("checkpoint_manifest_sha256s", "extra"),
    ("cohort_manifest_sha256s", "order"),
    ("evaluation_result_sha256s", "invalid"),
    ("upstream_receipt_sha256s", "order"),
    ("comparison_sha256s", "drop"),
    ("dose_sha256s", "extra"),
))
def test_rehashed_population_mutations_still_refuse(field, kind):
    original = _audit()
    rows = list(getattr(original, field))
    if kind == "drop":
        rows.pop()
    elif kind == "extra":
        rows.append(("unexpected", _sha("unexpected")))
    elif kind == "order":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0] = (rows[0][0], "A" * 64)
    forged = dataclasses.replace(original, **{field: tuple(rows)})
    # Recomputing the outer receipt hash is irrelevant: the exact expected
    # labels and digest population are rederived from the typed record.
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        forged.validate()


def test_audit_identity_and_authority_mutations_refuse():
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        _audit(audit_opened_count=2).validate()
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        _audit(freeze_sha256="A" * 64).validate()
    authority = dict(AUTHORITY)
    authority["audit_opening_authorized"] = True
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        _audit(authority=authority).validate()


def test_reconstruction_rederives_match_and_allows_only_negative_mismatch():
    matched = _reconstruction()
    validate_independent_reconstruction_v2(matched)
    assert matched.sha256() == hashlib.sha256(
        canonical_json_bytes(matched.payload())).hexdigest()

    negative = _reconstruction(
        independently_derived_terminal_result_sha256=_sha("foreign"),
        matched=False)
    negative.validate()
    forged_match = dataclasses.replace(negative, matched=True)
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError,
                       match="matched rederivation"):
        forged_match.validate()


def test_reconstruction_hashes_and_authority_are_strict():
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        _reconstruction(runtime_sha256="F" * 64).validate()
    authority = dict(AUTHORITY)
    authority["reconstruction_authorized"] = True
    with pytest.raises(WorldAfterstateV2TerminalProvenanceError):
        _reconstruction(authority=authority).validate()
