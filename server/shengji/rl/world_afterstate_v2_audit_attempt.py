"""Shared one-shot audit-attempt contract for Value-Afterstate V2.

The pipeline supervisor publishes this record before invoking the only stage
allowed to construct audit continuation labels.  Terminal derivation later
reopens the same bytes.  Keeping the contract in one module prevents a second
controller from inventing a different "attempt" and then claiming it preceded
labels that already existed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes


SCHEMA = "world-afterstate-v2-audit-attempt-v1"
AUTHORITY = {
    "label_opening_authorized": False,
    "retry_authorized": False,
    "replacement_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2AuditAttemptError(ValueError):
    """The durable one-shot audit marker was malformed or misbound."""


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2AuditAttemptError(f"{label} drift")
    return value


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_audit_attempt_bytes(*, freeze_sha256: str,
                              admission_sha256: str,
                              preflight: Mapping[str, Any]) -> bytes:
    """Build canonical marker bytes from already sealed target-free checks."""
    _digest(freeze_sha256, "audit freeze SHA-256")
    _digest(admission_sha256, "audit admission SHA-256")
    if type(preflight) is not dict or not preflight:
        raise WorldAfterstateV2AuditAttemptError("audit preflight drift")
    body = {
        "schema": SCHEMA,
        "freeze_sha256": freeze_sha256,
        "admission_sha256": admission_sha256,
        "audit_opened_once": True,
        "published_before_audit_labels": True,
        "preflight": dict(preflight),
        "authority": dict(AUTHORITY),
    }
    value = {**body, "attempt_sha256": _sha(body)}
    return canonical_json_bytes(value)


def reopen_audit_attempt_bytes(raw: bytes, *, expected_freeze_sha256: str,
                               expected_admission_sha256: str) -> dict[str, Any]:
    """Reopen the exact marker; no caller-owned boolean can satisfy it."""
    _digest(expected_freeze_sha256, "expected audit freeze SHA-256")
    _digest(expected_admission_sha256, "expected audit admission SHA-256")
    if type(raw) is not bytes:
        raise WorldAfterstateV2AuditAttemptError("audit attempt bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2AuditAttemptError(
            "audit attempt is not canonical JSON") from exc
    required = {
        "schema", "freeze_sha256", "admission_sha256",
        "audit_opened_once", "published_before_audit_labels", "preflight",
        "authority", "attempt_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or canonical_json_bytes(value) != raw or value["schema"] != SCHEMA \
            or value["freeze_sha256"] != expected_freeze_sha256 \
            or value["admission_sha256"] != expected_admission_sha256 \
            or value["audit_opened_once"] is not True \
            or value["published_before_audit_labels"] is not True \
            or type(value["preflight"]) is not dict or not value["preflight"] \
            or value["authority"] != AUTHORITY:
        raise WorldAfterstateV2AuditAttemptError("audit attempt contract drift")
    body = {key: item for key, item in value.items()
            if key != "attempt_sha256"}
    if value["attempt_sha256"] != _sha(body):
        raise WorldAfterstateV2AuditAttemptError("audit attempt hash drift")
    return value


__all__ = [
    "AUTHORITY", "SCHEMA", "WorldAfterstateV2AuditAttemptError",
    "build_audit_attempt_bytes", "reopen_audit_attempt_bytes",
]
