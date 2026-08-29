"""Authenticate the single external source+freeze review for Value V1 P1."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes


REVIEW_PREFIX = "WORLD_AFTERSTATE_V1_P1_SCIENTIFIC_REVIEW "
CAPACITY_REENTRY_PREFIX = (
    "WORLD_AFTERSTATE_V1_CAPACITY_OPERATOR_REENTRY_V1 ")
CAPACITY_REENTRY_V2_PREFIX = (
    "WORLD_AFTERSTATE_V1_CAPACITY_OPERATOR_REENTRY_V2 ")
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
CLAIM_SCHEMA = "world-afterstate-v1-p1-scientific-review-claim-v1"
ADMISSION_SCHEMA = "world-afterstate-v1-p1-scientific-admission-v1"
SCIENTIFIC_FREEZE_SCHEMA = "world-afterstate-advantage-p1-freeze-v1"
CAPACITY_REENTRY_AUTHENTICATION_SCHEMA = (
    "world-afterstate-v1-capacity-operator-reentry-authentication-v1")
CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA = (
    "world-afterstate-v1-capacity-operator-reentry-authentication-v2")
CAPACITY_REENTRY_CLAIM = {
    "authority": {
        "calibration_row_opening_authorized": False,
        "deployment_authorized": False,
        "gameplay_authorized": False,
        "merge_authorized": False,
        "p2_execution_authorized": False,
        "promotion_authorized": False,
        "provider_audit_row_opening_authorized": False,
        "r5_authorized": False,
        "report_row_opening_authorized": False,
        "retry_beyond_corrected_execution_authorized": False,
        "scientific_p1_training_authorized": False,
        "strength_claim_authorized": False,
        "train_only_corrected_capacity_execution_authorized": True,
    },
    "corrected_row_root": (
        "/opt/value-afterstate-v0-e3e4-d9ad99f-r1/artifacts/dataset"),
    "failed_invocation_id": "40a4c998a71e4b74befb46feddd2dd52",
    "failed_output_absent": True,
    "failed_service": "value-afterstate-v1-capacity-aa0595c-r1.service",
    "prior_review_commit": "cad30be4d0168f5ab0ec148e39e5de99b60c9852",
    "schema": "world-afterstate-v1-capacity-operator-reentry-v1",
    "source_git": "aa0595cce9b626941c9cc4fd64062b4e06d10cf1",
    "target_output": "/opt/value-afterstate-v1-capacity-aa0595c-r2",
    "train_row_bytes_opened": False,
    "wrong_row_root": (
        "/opt/value-afterstate-v0-e3e4-d9ad99f-r1/artifacts/dataset/rows"),
}
CAPACITY_REENTRY_V2_CLAIM = {
    "authority": {
        "calibration_row_opening_authorized": False,
        "deployment_authorized": False,
        "gameplay_authorized": False,
        "merge_authorized": False,
        "p2_execution_authorized": False,
        "promotion_authorized": False,
        "provider_audit_row_opening_authorized": False,
        "r5_authorized": False,
        "report_row_opening_authorized": False,
        "retry_beyond_second_corrected_execution_authorized": False,
        "scientific_p1_training_authorized": False,
        "strength_claim_authorized": False,
        "train_only_second_corrected_capacity_execution_authorized": True,
    },
    "canonical_remote_tip_at_failure": (
        "32cc41391a4c40c406161b14f6d91385123ba08c"),
    "corrected_row_root": (
        "/opt/value-afterstate-v0-e3e4-d9ad99f-r1/artifacts/dataset"),
    "failed_invocation_id": "638870aef3b44e84a2297b9a1cf1bbf7",
    "failed_output_absent": True,
    "failed_service": "value-afterstate-v1-capacity-aa0595c-r2.service",
    "failure_message": "capacity review local main differs from real remote",
    "local_origin_main_at_failure": (
        "cad30be4d0168f5ab0ec148e39e5de99b60c9852"),
    "prelaunch_canonical_ref_refresh_required": True,
    "prior_operator_reentry_commit": (
        "32cc41391a4c40c406161b14f6d91385123ba08c"),
    "prior_review_commit": "cad30be4d0168f5ab0ec148e39e5de99b60c9852",
    "progress_records_emitted": 0,
    "schema": "world-afterstate-v1-capacity-operator-reentry-v2",
    "source_git": "aa0595cce9b626941c9cc4fd64062b4e06d10cf1",
    "target_output": "/opt/value-afterstate-v1-capacity-aa0595c-r3",
    "train_row_bytes_opened": False,
}
ADMISSION_AUTHORITY = {
    "v0_train_row_reopening_authorized": True,
    "scientific_p1_training_authorized": True,
    "p1_calibration_audit_opening_authorized": True,
    "v0_calibration_label_opening_authorized": True,
    "immediate_independent_reconstruction_authorized": True,
    "report_row_opening_authorized": False,
    "provider_audit_row_opening_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1AdmissionError(ValueError):
    """The review actor, marker, canonical ancestry, or claim drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1AdmissionError(f"{label} drift")
    return value


def expected_review_claim(freeze: Mapping[str, Any]) -> dict[str, Any]:
    if type(freeze) is not dict \
            or freeze.get("schema") != SCIENTIFIC_FREEZE_SCHEMA:
        raise WorldAfterstateV1AdmissionError("review freeze identity drift")
    source_git = _digest(
        freeze.get("source_git"), "review source Git", length=40)
    freeze_sha = _digest(
        freeze.get("freeze_sha256"), "review freeze SHA-256")
    capacity = freeze.get("capacity")
    inputs = freeze.get("v0_inputs")
    resources = freeze.get("resources")
    if type(capacity) is not dict or type(inputs) is not dict \
            or type(resources) is not dict:
        raise WorldAfterstateV1AdmissionError("review input binding drift")
    claim = {
        "schema": CLAIM_SCHEMA,
        "source_git": source_git,
        "freeze_sha256": freeze_sha,
        "scientific_root": freeze.get("scientific_root"),
        "capacity_receipt_external_sha256": _digest(
            capacity.get("receipt_external_sha256"),
            "review capacity receipt external SHA-256"),
        "capacity_receipt_sha256": _digest(
            capacity.get("receipt_sha256"),
            "review capacity receipt SHA-256"),
        "v0_population_external_sha256": _digest(
            inputs.get("population_external_sha256"),
            "review V0 population external SHA-256"),
        "v0_dataset_external_sha256": _digest(
            inputs.get("dataset_external_sha256"),
            "review V0 dataset external SHA-256"),
        "v0_audit_manifest_external_sha256": _digest(
            inputs.get("audit_manifest_external_sha256"),
            "review V0 audit manifest external SHA-256"),
        "training_wall_cap_nanoseconds": resources.get(
            "training_wall_cap_nanoseconds"),
        "memory_limit_bytes": resources.get("memory_limit_bytes"),
        "authority": dict(ADMISSION_AUTHORITY),
    }
    for key in ("training_wall_cap_nanoseconds", "memory_limit_bytes"):
        if isinstance(claim[key], bool) or not isinstance(claim[key], int) \
                or claim[key] <= 0:
            raise WorldAfterstateV1AdmissionError(
                "review resource binding drift")
    scientific_root = claim["scientific_root"]
    if type(scientific_root) is not str or not scientific_root \
            or not Path(scientific_root).is_absolute() \
            or str(Path(scientific_root).resolve(strict=False)) \
            != scientific_root:
        raise WorldAfterstateV1AdmissionError(
            "review scientific root drift")
    return claim


def _git(repo: Path, *arguments: str, binary: bool = False):
    result = subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True,
        text=not binary)
    return result.stdout if binary else result.stdout.strip()


def _canonical_remote_tip(repo: Path) -> str:
    try:
        output = subprocess.run(
            ("git", "ls-remote", "--exit-code", CANONICAL_REMOTE_URL,
             CANONICAL_REMOTE_REF), cwd=repo, check=True,
            capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1AdmissionError(
            "review canonical remote lookup failed") from exc
    fields = output.split()
    if len(fields) != 2 or fields[1] != CANONICAL_REMOTE_REF:
        raise WorldAfterstateV1AdmissionError(
            "review canonical remote identity drift")
    return _digest(fields[0], "review canonical remote tip", length=40)


def _refresh_canonical_remote_ref(repo: Path) -> None:
    try:
        subprocess.run(
            ("git", "fetch", "--quiet", CANONICAL_REMOTE_URL,
             f"{CANONICAL_REMOTE_REF}:refs/remotes/origin/main"),
            cwd=repo, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1AdmissionError(
            "review canonical ref refresh failed") from exc


def expected_capacity_operator_reentry_claim() -> dict[str, Any]:
    """Return the one exact operator re-entry authorized after the path miss."""
    return {
        **CAPACITY_REENTRY_CLAIM,
        "authority": dict(CAPACITY_REENTRY_CLAIM["authority"]),
    }


def expected_capacity_operator_reentry_v2_claim() -> dict[str, Any]:
    """Return the exact re-entry after the stale canonical-ref refusal."""
    return {
        **CAPACITY_REENTRY_V2_CLAIM,
        "authority": dict(CAPACITY_REENTRY_V2_CLAIM["authority"]),
    }


def _validate_capacity_operator_reentry(
        value: Mapping[str, Any], *, claim: Mapping[str, Any],
        authentication_schema: str, label: str) -> None:
    required = {
        "schema", "review_commit", "canonical_remote_tip_at_freeze",
        "claim", "review_marker_sha256", "review_claim_sha256",
        "authentication_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") \
            != authentication_schema \
            or value.get("claim") != claim \
            or value.get("review_claim_sha256") != _sha(claim):
        raise WorldAfterstateV1AdmissionError(
            f"{label} identity drift")
    for key, length in (
            ("review_commit", 40),
            ("canonical_remote_tip_at_freeze", 40),
            ("review_marker_sha256", 64),
            ("review_claim_sha256", 64),
            ("authentication_sha256", 64)):
        _digest(value.get(key), f"{label} {key}", length=length)
    body = {key: item for key, item in value.items()
            if key != "authentication_sha256"}
    if value["authentication_sha256"] != _sha(body):
        raise WorldAfterstateV1AdmissionError(
            f"{label} reconstruction drift")


def validate_capacity_operator_reentry(
        value: Mapping[str, Any]) -> None:
    _validate_capacity_operator_reentry(
        value, claim=expected_capacity_operator_reentry_claim(),
        authentication_schema=CAPACITY_REENTRY_AUTHENTICATION_SCHEMA,
        label="capacity operator reentry")


def validate_capacity_operator_reentry_v2(
        value: Mapping[str, Any]) -> None:
    _validate_capacity_operator_reentry(
        value, claim=expected_capacity_operator_reentry_v2_claim(),
        authentication_schema=CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA,
        label="capacity operator reentry V2")


def _authenticate_capacity_operator_reentry(
        *, repo: Path, review_commit: str, claim: Mapping[str, Any],
        prefix_text: str, authentication_schema: str,
        label: str) -> dict[str, Any]:
    if not isinstance(repo, Path) or not repo.is_absolute():
        raise WorldAfterstateV1AdmissionError(
            f"{label} repository drift")
    _digest(review_commit, f"{label} commit", length=40)
    _refresh_canonical_remote_ref(repo)
    remote_tip = _canonical_remote_tip(repo)
    try:
        if _git(repo, "rev-parse", "origin/main") != remote_tip:
            raise WorldAfterstateV1AdmissionError(
                f"{label} local main differs from remote")
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
            raise WorldAfterstateV1AdmissionError(
                f"{label} is not on canonical main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        message = str(_git(
            repo, "show", "-s", "--format=%B", review_commit))
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if len(parents) != 1 or identity != (
                REVIEWER_NAME, REVIEWER_EMAIL,
                REVIEWER_NAME, REVIEWER_EMAIL) \
                or REVIEWER_SESSION_TRAILER not in message \
                or changed != [REVIEW_LEDGER]:
            raise WorldAfterstateV1AdmissionError(
                f"{label} provenance drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parents[0]}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1AdmissionError(
            f"{label} Git lookup failed") from exc
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise WorldAfterstateV1AdmissionError(
            f"{label} ledger is not append-only")
    marker = prefix_text.encode("ascii") + canonical_json_bytes(claim)
    prefix = prefix_text.encode("ascii")
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [*previous_matches, marker] \
            or marker in previous_matches:
        raise WorldAfterstateV1AdmissionError(
            f"{label} marker introduction drift")
    body = {
        "schema": authentication_schema,
        "review_commit": review_commit,
        "canonical_remote_tip_at_freeze": remote_tip,
        "claim": dict(claim),
        "review_marker_sha256": _sha_bytes(marker),
        "review_claim_sha256": _sha(claim),
    }
    value = {**body, "authentication_sha256": _sha(body)}
    return value


def authenticate_capacity_operator_reentry(
        *, repo: Path, review_commit: str) -> dict[str, Any]:
    """Authenticate the exact first command-only re-entry."""
    value = _authenticate_capacity_operator_reentry(
        repo=repo, review_commit=review_commit,
        claim=expected_capacity_operator_reentry_claim(),
        prefix_text=CAPACITY_REENTRY_PREFIX,
        authentication_schema=CAPACITY_REENTRY_AUTHENTICATION_SCHEMA,
        label="capacity operator reentry")
    validate_capacity_operator_reentry(value)
    return value


def authenticate_capacity_operator_reentry_v2(
        *, repo: Path, review_commit: str) -> dict[str, Any]:
    """Authenticate the stale-canonical-ref command-only re-entry."""
    value = _authenticate_capacity_operator_reentry(
        repo=repo, review_commit=review_commit,
        claim=expected_capacity_operator_reentry_v2_claim(),
        prefix_text=CAPACITY_REENTRY_V2_PREFIX,
        authentication_schema=CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA,
        label="capacity operator reentry V2")
    validate_capacity_operator_reentry_v2(value)
    return value


def authenticate_review_commit(
        freeze: Mapping[str, Any], *, repo: Path,
        review_commit: str) -> tuple[bytes, str]:
    claim = expected_review_claim(freeze)
    if not isinstance(repo, Path) or not repo.is_absolute():
        raise WorldAfterstateV1AdmissionError("review repository drift")
    _digest(review_commit, "review commit", length=40)
    _refresh_canonical_remote_ref(repo)
    remote_tip = _canonical_remote_tip(repo)
    try:
        if _git(repo, "rev-parse", "origin/main") != remote_tip:
            raise WorldAfterstateV1AdmissionError(
                "review local canonical ref differs from real remote")
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
            raise WorldAfterstateV1AdmissionError(
                "review commit is not on canonical remote main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        if len(parents) != 1:
            raise WorldAfterstateV1AdmissionError(
                "review commit parent drift")
        parent = parents[0]
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                        REVIEWER_NAME, REVIEWER_EMAIL):
            raise WorldAfterstateV1AdmissionError("review actor drift")
        message = str(_git(repo, "show", "-s", "--format=%B",
                           review_commit))
        if REVIEWER_SESSION_TRAILER not in message:
            raise WorldAfterstateV1AdmissionError("review session drift")
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise WorldAfterstateV1AdmissionError("review file scope drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parent}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1AdmissionError(
            "review Git lookup failed") from exc
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise WorldAfterstateV1AdmissionError(
            "review ledger is not append-only")
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(claim)
    prefix = REVIEW_PREFIX.encode("ascii")
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [*previous_matches, marker] \
            or marker in previous_matches:
        raise WorldAfterstateV1AdmissionError(
            "review marker introduction drift")
    return marker, remote_tip


def build_admission(
        freeze: Mapping[str, Any], *, repo: Path,
        review_commit: str) -> dict[str, Any]:
    marker, remote_tip = authenticate_review_commit(
        freeze, repo=repo, review_commit=review_commit)
    claim = expected_review_claim(freeze)
    body = {
        "schema": ADMISSION_SCHEMA,
        "source_git": claim["source_git"],
        "freeze_sha256": claim["freeze_sha256"],
        "review_commit": review_commit,
        "canonical_remote_tip_at_admission": remote_tip,
        "review_marker_sha256": _sha_bytes(marker),
        "review_claim_sha256": _sha(claim),
        "authority": dict(ADMISSION_AUTHORITY),
    }
    return {**body, "admission_sha256": _sha(body)}


def validate_admission(
        value: Mapping[str, Any], *, freeze: Mapping[str, Any],
        review_marker: bytes) -> None:
    claim = expected_review_claim(freeze)
    expected_marker = REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
    required = {
        "schema", "source_git", "freeze_sha256", "review_commit",
        "canonical_remote_tip_at_admission", "review_marker_sha256",
        "review_claim_sha256", "authority", "admission_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != ADMISSION_SCHEMA \
            or value.get("source_git") != claim["source_git"] \
            or value.get("freeze_sha256") != claim["freeze_sha256"] \
            or value.get("authority") != ADMISSION_AUTHORITY \
            or type(review_marker) is not bytes \
            or review_marker != expected_marker \
            or value.get("review_marker_sha256") \
            != _sha_bytes(review_marker) \
            or value.get("review_claim_sha256") != _sha(claim):
        raise WorldAfterstateV1AdmissionError("admission identity drift")
    _digest(value.get("review_commit"), "admission review commit", length=40)
    _digest(value.get("canonical_remote_tip_at_admission"),
            "admission canonical remote tip", length=40)
    _digest(value.get("admission_sha256"), "admission SHA-256")
    body = {key: item for key, item in value.items()
            if key != "admission_sha256"}
    if value["admission_sha256"] != _sha(body):
        raise WorldAfterstateV1AdmissionError(
            "admission reconstruction drift")


def reauthenticate_admission(
        value: Mapping[str, Any], *, freeze: Mapping[str, Any],
        repo: Path) -> bytes:
    marker, remote_tip = authenticate_review_commit(
        freeze, repo=repo, review_commit=value.get("review_commit"))
    validate_admission(value, freeze=freeze, review_marker=marker)
    try:
        retained = subprocess.run(
            ("git", "merge-base", "--is-ancestor",
             value["canonical_remote_tip_at_admission"], remote_tip),
            cwd=repo, capture_output=True).returncode == 0
    except OSError as exc:
        raise WorldAfterstateV1AdmissionError(
            "admission canonical ancestry lookup failed") from exc
    if not retained:
        raise WorldAfterstateV1AdmissionError(
            "admission remote rollback drift")
    return marker


__all__ = [
    "ADMISSION_AUTHORITY", "ADMISSION_SCHEMA",
    "CAPACITY_REENTRY_AUTHENTICATION_SCHEMA", "CAPACITY_REENTRY_PREFIX",
    "CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA",
    "CAPACITY_REENTRY_V2_PREFIX",
    "REVIEW_PREFIX", "WorldAfterstateV1AdmissionError",
    "authenticate_capacity_operator_reentry",
    "authenticate_capacity_operator_reentry_v2", "authenticate_review_commit",
    "build_admission", "expected_capacity_operator_reentry_claim",
    "expected_capacity_operator_reentry_v2_claim",
    "expected_review_claim", "reauthenticate_admission",
    "validate_admission", "validate_capacity_operator_reentry",
    "validate_capacity_operator_reentry_v2",
]
