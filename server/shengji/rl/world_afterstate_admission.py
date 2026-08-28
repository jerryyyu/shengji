"""Authenticate one external review for the immutable Value V0 run."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes


REVIEW_PREFIX = "WORLD_AFTERSTATE_E3_E4_V0_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
ADMISSION_SCHEMA = "world-afterstate-e3-e4-admission-v0"
ADMISSION_AUTHORITY = {
    "continuation_dataset_generation_authorized": True,
    "scientific_training_authorized": True,
    "one_report_decision_opening_authorized": True,
    "terminal_reconstruction_authorized": True,
    "retry_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateAdmissionError(ValueError):
    """The review commit, marker, remote, or admission drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateAdmissionError(f"{label} drift")
    return value


def expected_review_claim(freeze: Mapping[str, Any]) -> dict[str, Any]:
    if type(freeze) is not dict:
        raise WorldAfterstateAdmissionError("review freeze type drift")
    source_git = _digest(
        freeze.get("source_git"), "review source Git", length=40)
    freeze_sha = _digest(
        freeze.get("freeze_sha256"), "review freeze SHA-256")
    capacity = freeze.get("capacity")
    population = freeze.get("population_packet")
    if type(capacity) is not dict or type(population) is not dict:
        raise WorldAfterstateAdmissionError("review input binding drift")
    claim = {
        "schema": "world-afterstate-e3-e4-review-claim-v0",
        "source_git": source_git,
        "freeze_sha256": freeze_sha,
        "capacity_external_sha256": _digest(
            capacity.get("external_sha256"),
            "review capacity external SHA-256"),
        "population_packet_external_sha256": _digest(
            population.get("external_sha256"),
            "review population packet external SHA-256"),
        "population_manifest_sha256": _digest(
            population.get("population_manifest_sha256"),
            "review population manifest SHA-256"),
        "authority": dict(ADMISSION_AUTHORITY),
    }
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
        raise WorldAfterstateAdmissionError(
            "review canonical remote lookup failed") from exc
    fields = output.split()
    if len(fields) != 2 or fields[1] != CANONICAL_REMOTE_REF:
        raise WorldAfterstateAdmissionError(
            "review canonical remote identity drift")
    return _digest(fields[0], "review canonical remote tip", length=40)


def authenticate_review_commit(
        freeze: Mapping[str, Any], *, repo: Path,
        review_commit: str) -> tuple[bytes, str]:
    claim = expected_review_claim(freeze)
    if not isinstance(repo, Path) or not repo.is_absolute():
        raise WorldAfterstateAdmissionError("review repository drift")
    _digest(review_commit, "review commit", length=40)
    remote_tip = _canonical_remote_tip(repo)
    try:
        local_tip = _git(repo, "rev-parse", "origin/main")
        if local_tip != remote_tip:
            raise WorldAfterstateAdmissionError(
                "review local canonical ref differs from real remote")
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
            raise WorldAfterstateAdmissionError(
                "review commit is not on canonical remote main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        if len(parents) != 1:
            raise WorldAfterstateAdmissionError("review commit parent drift")
        parent = parents[0]
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                        REVIEWER_NAME, REVIEWER_EMAIL):
            raise WorldAfterstateAdmissionError("review actor drift")
        message = str(_git(repo, "show", "-s", "--format=%B",
                           review_commit))
        if REVIEWER_SESSION_TRAILER not in message:
            raise WorldAfterstateAdmissionError("review session drift")
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise WorldAfterstateAdmissionError("review file scope drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parent}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateAdmissionError("review Git lookup failed") \
            from exc
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise WorldAfterstateAdmissionError(
            "review ledger is not append-only")
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(claim)
    prefix = REVIEW_PREFIX.encode("ascii")
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [marker] or previous_matches:
        raise WorldAfterstateAdmissionError(
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
        # This is an admission-time anti-rollback anchor, not a promise that
        # canonical main will remain frozen throughout a multi-stage run.
        "canonical_remote_tip_at_admission": remote_tip,
        "review_marker_sha256": _sha_bytes(marker),
        "authority": dict(ADMISSION_AUTHORITY),
    }
    return {**body, "admission_sha256": _sha(body)}


def validate_admission(
        value: Mapping[str, Any], *, freeze: Mapping[str, Any],
        review_marker: bytes) -> None:
    claim = expected_review_claim(freeze)
    required = {
        "schema", "source_git", "freeze_sha256", "review_commit",
        "canonical_remote_tip_at_admission", "review_marker_sha256",
        "authority", "admission_sha256",
    }
    expected_marker = REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != ADMISSION_SCHEMA \
            or value.get("source_git") != claim["source_git"] \
            or value.get("freeze_sha256") != claim["freeze_sha256"] \
            or value.get("authority") != ADMISSION_AUTHORITY \
            or type(review_marker) is not bytes \
            or review_marker != expected_marker \
            or value.get("review_marker_sha256") \
            != _sha_bytes(review_marker):
        raise WorldAfterstateAdmissionError("admission identity drift")
    _digest(value.get("review_commit"), "admission review commit", length=40)
    _digest(value.get("canonical_remote_tip_at_admission"),
            "admission canonical remote tip at admission", length=40)
    _digest(value.get("admission_sha256"), "admission SHA-256")
    body = {key: item for key, item in value.items()
            if key != "admission_sha256"}
    if value["admission_sha256"] != _sha(body):
        raise WorldAfterstateAdmissionError(
            "admission reconstruction drift")


def reauthenticate_admission(
        value: Mapping[str, Any], *, freeze: Mapping[str, Any],
        repo: Path) -> bytes:
    marker, remote_tip = authenticate_review_commit(
        freeze, repo=repo, review_commit=value.get("review_commit"))
    validate_admission(value, freeze=freeze, review_marker=marker)
    # Canonical main may advance while a reviewed multi-stage experiment is
    # running.  It may not roll back or fork away from the tip authenticated
    # when admission was minted.
    try:
        retained = subprocess.run(
            ("git", "merge-base", "--is-ancestor",
             value["canonical_remote_tip_at_admission"], remote_tip),
            cwd=repo, capture_output=True).returncode == 0
    except OSError as exc:
        raise WorldAfterstateAdmissionError(
            "admission canonical ancestry lookup failed") from exc
    if not retained:
        raise WorldAfterstateAdmissionError("admission remote rollback drift")
    return marker


__all__ = [
    "ADMISSION_AUTHORITY", "ADMISSION_SCHEMA", "REVIEW_PREFIX",
    "WorldAfterstateAdmissionError", "authenticate_review_commit",
    "build_admission", "expected_review_claim", "reauthenticate_admission",
    "validate_admission",
]
