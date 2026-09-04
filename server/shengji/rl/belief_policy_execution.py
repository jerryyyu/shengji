"""Two-review admission and compact execution freeze for the R4 diagnostic.

Source review authorizes only a score-free capacity census.  The resulting
receipt produces one immutable freeze.  A second exact-freeze marker admits
the scientific diagnostic.  Expensive source/runtime/model authentication is
performed once in the parent, never once per worker or again during terminal
reconstruction.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .belief_contract import canonical_json_bytes
from .belief_policy_controller import CAPACITY_SCHEMA, CAPACITY_WORKER_ARMS
from .belief_policy_models import R4PolicyModelsV1
from .belief_policy_protocol import (
    POLICY_PROTOCOL_SCHEMA,
    POLICY_RANKS,
    SELECTED_ROUNDS_PER_RANK,
    TARGET_ROUND_COUNT,
    policy_round_coordinates,
)
from .belief_v2_execution_identity import (
    build_runtime_profile,
    build_source_bindings,
    configure_numerical_runtime,
)


SOURCE_REVIEW_PREFIX = "BELIEF_R4_POLICY_CAPACITY_SOURCE_REVIEW "
FREEZE_REVIEW_PREFIX = "BELIEF_R4_POLICY_SCIENTIFIC_FREEZE_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
SOURCE_MANIFEST_SCHEMA = "belief-r4-policy-source-manifest-v1"
FREEZE_SCHEMA = "belief-r4-policy-scientific-freeze-v1"
ADMISSION_SCHEMA = "belief-r4-policy-scientific-admission-v1"
REQUIRED_EXACT_PATHS = (
    "BELIEF_R4_OPENED_DEV_POLICY_DIAGNOSTIC.md",
    "server/pyproject.toml",
    "server/setup.py",
    "server/uv.lock",
    "server/scripts/belief_r4_policy.py",
)
MAX_SCIENTIFIC_WALL_NANOSECONDS = 48 * 60 * 60 * 1_000_000_000
MIN_DEADLINE_RESERVE_NANOSECONDS = 30 * 60 * 1_000_000_000


class BeliefPolicyExecutionError(ValueError):
    """A source review, capacity receipt, freeze, or admission drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any, length: int = 64) -> bool:
    return type(value) is str and len(value) == length \
        and all(char in "0123456789abcdef" for char in value)


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    def object_hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BeliefPolicyExecutionError(
                    f"policy {label} contains duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=object_hook,
            parse_float=lambda _: (_ for _ in ()).throw(
                BeliefPolicyExecutionError(
                    f"policy {label} contains float")),
            parse_constant=lambda _: (_ for _ in ()).throw(
                BeliefPolicyExecutionError(
                    f"policy {label} contains nonfinite number")))
    except BeliefPolicyExecutionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefPolicyExecutionError(
            f"policy {label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefPolicyExecutionError(
            f"policy {label} is not canonical")
    return value


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ("git", *args), cwd=repo, check=True,
            capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefPolicyExecutionError(
            "policy Git authentication failed") from exc
    return result.stdout if binary else result.stdout.strip()


def build_source_identity(repo: Path, *, expected_git: str) -> dict[str, Any]:
    """Hash the complete tracked runtime surface and refuse dirty shadows."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_sha(expected_git, 40) \
            or _git(repo, "rev-parse", "HEAD") != expected_git \
            or _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise BeliefPolicyExecutionError(
            "policy source checkout is not exact and clean")
    # Reuse V2's reviewed full-package scanner, including its refusal of
    # ignored bytecode/native shadows, then add this diagnostic's script and
    # design.  Do not create a second, weaker source-boundary implementation.
    base = build_source_bindings(repo, expected_git=expected_git)
    rows_by_path = {row.path: {
        "path": row.path,
        "byte_count": row.byte_count,
        "sha256": row.sha256,
    } for row in base}
    for relative in REQUIRED_EXACT_PATHS:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise BeliefPolicyExecutionError(
                "policy source file shape drift")
        raw = path.read_bytes()
        if raw != _git(repo, "show", f"{expected_git}:{relative}",
                       binary=True):
            raise BeliefPolicyExecutionError(
                "policy source bytes differ from Git")
        rows_by_path[relative] = {
            "path": relative,
            "byte_count": len(raw),
            "sha256": _sha256(raw),
        }
    rows = [rows_by_path[path] for path in sorted(rows_by_path)]
    manifest = canonical_json_bytes({
        "schema": SOURCE_MANIFEST_SCHEMA,
        "execution_git": expected_git,
        "files": rows,
    })
    return {
        "execution_git": expected_git,
        "file_count": len(rows),
        "source_manifest_sha256": _sha256(manifest),
    }


def build_runtime_identity() -> dict[str, Any]:
    """Return exact runtime plus a reboot-tolerant compatibility digest."""
    configure_numerical_runtime()
    runtime = build_runtime_profile().to_dict()
    compatibility = dict(runtime)
    compatibility.pop("boot_identity", None)
    # Hostname may change across a legitimate same-hardware reboot/reprovision.
    compatibility.pop("hostname", None)
    return {
        "runtime": runtime,
        "compatibility_sha256": _sha256(
            canonical_json_bytes(compatibility)),
    }


def model_identity(models: R4PolicyModelsV1) -> dict[str, Any]:
    if type(models) is not R4PolicyModelsV1:
        raise BeliefPolicyExecutionError("policy model identity type drift")
    return {
        "r4_freeze_sha256": models.freeze_sha256,
        "r4_admission_sha256": models.admission_sha256,
        "r4_review_marker_sha256": models.review_marker_sha256,
        "common_calibration_sha256": models.common_calibration_sha256,
        "primary_trained_manifest_sha256": (
            models.primary_trained_manifest_sha256),
        "control_trained_manifest_sha256": (
            models.control_trained_manifest_sha256),
        "primary_model_sha256s": list(models.primary.model_sha256s),
        "control_model_sha256s": list(models.control.model_sha256s),
    }


def _validate_model_identity(value: Any) -> None:
    keys = {
        "r4_freeze_sha256", "r4_admission_sha256",
        "r4_review_marker_sha256", "common_calibration_sha256",
        "primary_trained_manifest_sha256",
        "control_trained_manifest_sha256", "primary_model_sha256s",
        "control_model_sha256s",
    }
    if type(value) is not dict or set(value) != keys \
            or any(not _is_sha(value[key]) for key in keys - {
                "primary_model_sha256s", "control_model_sha256s"}) \
            or any(type(value[key]) is not list or len(value[key]) != 8
                   or len(set(value[key])) != 8
                   or any(not _is_sha(digest) for digest in value[key])
                   for key in (
                       "primary_model_sha256s", "control_model_sha256s")) \
            or set(value["primary_model_sha256s"]) \
            & set(value["control_model_sha256s"]):
        raise BeliefPolicyExecutionError(
            "policy model identity reconstruction drift")


def expected_source_review_claim(
        *, source: dict[str, Any],
        models: R4PolicyModelsV1) -> dict[str, Any]:
    return expected_source_review_claim_from_identity(
        source=source, models=model_identity(models))


def expected_source_review_claim_from_identity(
        *, source: dict[str, Any], models: dict[str, Any]) -> dict[str, Any]:
    if type(source) is not dict or set(source) != {
            "execution_git", "file_count", "source_manifest_sha256"} \
            or not _is_sha(source["execution_git"], 40) \
            or type(source["file_count"]) is not int \
            or source["file_count"] <= 0 \
            or not _is_sha(source["source_manifest_sha256"]):
        raise BeliefPolicyExecutionError(
            "policy source review identity drift")
    _validate_model_identity(models)
    return {
        "schema": "belief-r4-policy-capacity-source-review-v1",
        "execution_git": source["execution_git"],
        "source_manifest_sha256": source["source_manifest_sha256"],
        "models": models,
        "one_score_free_capacity_census_authorized": True,
        "scientific_execution_authorized": False,
        "r4_test_opening_authorized": False,
        "retry_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def expected_freeze_review_claim(freeze: dict[str, Any]) -> dict[str, Any]:
    validate_freeze(freeze)
    return {
        "schema": "belief-r4-policy-scientific-freeze-review-v1",
        "freeze_sha256": _sha256(canonical_json_bytes(freeze)),
        "execution_git": freeze["execution_git"],
        "source_manifest_sha256": freeze["source_manifest_sha256"],
        "capacity_receipt_sha256": freeze["capacity_receipt_sha256"],
        "evidence_root": freeze["evidence_root"],
        "one_opened_dev_policy_diagnostic_authorized": True,
        "resume_missing_shards_before_deadline_authorized": True,
        "r4_test_opening_authorized": False,
        "retry_after_terminal_authorized": False,
        "r5_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def authenticate_review(
        *, repo: Path, review_commit: str, prefix: str,
        claim: dict[str, Any]) -> bytes:
    """Authenticate one exact marker introduced append-only on remote main."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_sha(review_commit, 40) \
            or type(prefix) is not str or not prefix:
        raise BeliefPolicyExecutionError("policy review input drift")
    try:
        probe = subprocess.run(
            ("git", "ls-remote", "--exit-code", CANONICAL_REMOTE_URL,
             CANONICAL_REMOTE_REF), cwd=repo, check=True,
            capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefPolicyExecutionError(
            "policy canonical remote probe failed") from exc
    remote_rows = probe.stdout.splitlines()
    if len(remote_rows) != 1 or len(remote_rows[0].split()) != 2:
        raise BeliefPolicyExecutionError("policy canonical remote drift")
    remote_tip = remote_rows[0].split()[0]
    if not _is_sha(remote_tip, 40) \
            or subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
        raise BeliefPolicyExecutionError(
            "policy review is not on canonical remote main")
    parents = str(_git(
        repo, "show", "-s", "--format=%P", review_commit)).split()
    identity = tuple(_git(
        repo, "show", "-s", f"--format={field}", review_commit)
                     for field in ("%an", "%ae", "%cn", "%ce"))
    message = str(_git(repo, "show", "-s", "--format=%B", review_commit))
    changed = str(_git(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
        review_commit)).splitlines()
    if len(parents) != 1 \
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL) \
            or REVIEWER_SESSION_TRAILER not in message \
            or changed != [REVIEW_LEDGER]:
        raise BeliefPolicyExecutionError("policy review provenance drift")
    current = _git(
        repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
    previous = _git(
        repo, "show", f"{parents[0]}:{REVIEW_LEDGER}", binary=True)
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise BeliefPolicyExecutionError(
            "policy review ledger is not append-only")
    marker = prefix.encode("ascii") + canonical_json_bytes(claim)
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix.encode("ascii"))]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix.encode("ascii"))]
    if current_matches != [*previous_matches, marker] \
            or marker in previous_matches:
        raise BeliefPolicyExecutionError(
            "policy exact review marker introduction drift")
    return marker


def authenticate_capacity_envelope_source(
        *, repo: Path, envelope: dict[str, Any]) -> bytes:
    """Re-authenticate source review at the freeze-construction boundary."""
    if type(envelope) is not dict:
        raise BeliefPolicyExecutionError(
            "policy capacity envelope authentication drift")
    source = envelope.get("source")
    models = envelope.get("models")
    if type(source) is not dict:
        raise BeliefPolicyExecutionError(
            "policy capacity envelope source drift")
    live_source = build_source_identity(
        repo, expected_git=source.get("execution_git"))
    if live_source != source:
        raise BeliefPolicyExecutionError(
            "policy capacity envelope live source drift")
    marker = authenticate_review(
        repo=repo,
        review_commit=envelope.get("source_review_commit"),
        prefix=SOURCE_REVIEW_PREFIX,
        claim=expected_source_review_claim_from_identity(
            source=live_source, models=models),
    )
    if _sha256(marker) != envelope.get("source_review_marker_sha256"):
        raise BeliefPolicyExecutionError(
            "policy capacity envelope source review drift")
    return marker


def authenticate_scientific_freeze_review(
        *, repo: Path, freeze: dict[str, Any],
        admission: dict[str, Any], marker: bytes) -> None:
    """Re-authenticate exact-freeze provenance whenever science starts."""
    validate_freeze(freeze)
    if type(admission) is not dict or type(marker) is not bytes:
        raise BeliefPolicyExecutionError(
            "policy scientific review authentication drift")
    authenticated = authenticate_review(
        repo=repo, review_commit=admission.get("review_commit"),
        prefix=FREEZE_REVIEW_PREFIX,
        claim=expected_freeze_review_claim(freeze))
    if authenticated != marker:
        raise BeliefPolicyExecutionError(
            "policy scientific freeze review provenance drift")


def build_capacity_envelope(
        receipt: dict[str, Any], *, source: dict[str, Any],
        runtime: dict[str, Any], models: R4PolicyModelsV1,
        source_review_commit: str, source_review_marker: bytes) \
        -> dict[str, Any]:
    validate_capacity_receipt(receipt)
    if receipt.get("schema") != CAPACITY_SCHEMA \
            or receipt.get("execution_git") != source["execution_git"] \
            or receipt.get("source_manifest_sha256") \
            != source["source_manifest_sha256"]:
        raise BeliefPolicyExecutionError("policy capacity receipt drift")
    return {
        "schema": "belief-r4-policy-capacity-envelope-v1",
        "source": source,
        "runtime": runtime,
        "models": model_identity(models),
        "source_review_commit": source_review_commit,
        "source_review_marker_sha256": _sha256(source_review_marker),
        "receipt": receipt,
        "scientific_execution_authorized": False,
        "r4_test_opened": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def validate_capacity_receipt(receipt: dict[str, Any]) -> None:
    keys = {
        "schema", "execution_git", "source_manifest_sha256", "cpu_count",
        "arms", "selected_workers", "headroom_workers",
        "selected_max_root_wall_nanoseconds",
        "scientific_wall_estimate_nanoseconds", "contains_actions",
        "contains_outcomes", "r4_test_opened",
        "scientific_execution_authorized", "gameplay_authorized",
        "strength_claim_authorized", "deployment_authorized",
    }
    if type(receipt) is not dict or set(receipt) != keys \
            or receipt["schema"] != CAPACITY_SCHEMA \
            or not _is_sha(receipt["execution_git"], 40) \
            or not _is_sha(receipt["source_manifest_sha256"]) \
            or type(receipt["cpu_count"]) is not int \
            or receipt["cpu_count"] < 16 \
            or type(receipt["arms"]) is not list \
            or [row.get("workers") for row in receipt["arms"]] \
            != list(CAPACITY_WORKER_ARMS) \
            or receipt["selected_workers"] not in CAPACITY_WORKER_ARMS \
            or receipt["headroom_workers"] not in CAPACITY_WORKER_ARMS \
            or receipt["headroom_workers"] <= receipt["selected_workers"] \
            or type(receipt["selected_max_root_wall_nanoseconds"]) is not int \
            or receipt["selected_max_root_wall_nanoseconds"] <= 0 \
            or receipt["scientific_wall_estimate_nanoseconds"] \
            != receipt["selected_max_root_wall_nanoseconds"] \
            * SELECTED_ROUNDS_PER_RANK * max(
                2, (len(POLICY_RANKS)
                    + receipt["selected_workers"] - 1)
                // receipt["selected_workers"]) \
            or any(receipt[key] is not False for key in (
                "contains_actions", "contains_outcomes", "r4_test_opened",
                "scientific_execution_authorized", "gameplay_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefPolicyExecutionError(
            "policy capacity receipt reconstruction drift")
    for arm, expected_workers in zip(
            receipt["arms"], CAPACITY_WORKER_ARMS, strict=True):
        arm_keys = {
            "workers", "task_count", "tasks", "wall_nanoseconds",
            "cpu_nanoseconds", "aggregate_cpu_utilization_ppb",
            "max_child_rss_bytes", "projected_process_rss_bytes",
            "host_memory_bytes", "swap_used_bytes_before",
            "swap_used_bytes_after", "passed",
        }
        if type(arm) is not dict or set(arm) != arm_keys \
                or arm["workers"] != expected_workers \
                or arm["task_count"] != expected_workers \
                or type(arm["tasks"]) is not list \
                or len(arm["tasks"]) != expected_workers \
                or type(arm["wall_nanoseconds"]) is not int \
                or arm["wall_nanoseconds"] <= 0 \
                or type(arm["cpu_nanoseconds"]) is not int \
                or arm["cpu_nanoseconds"] < 0 \
                or arm["aggregate_cpu_utilization_ppb"] \
                != arm["cpu_nanoseconds"] * 1_000_000_000 \
                // arm["wall_nanoseconds"] \
                or any(type(arm[key]) is not int or arm[key] < 0 for key in (
                    "max_child_rss_bytes", "projected_process_rss_bytes",
                    "host_memory_bytes", "swap_used_bytes_before",
                    "swap_used_bytes_after")):
            raise BeliefPolicyExecutionError(
                "policy capacity arm reconstruction drift")
        task_keys = {
            "coordinate_index", "qualified", "wall_nanoseconds",
            "cpu_nanoseconds", "max_rss_bytes", "reference_worlds",
            "selection_physical_rollouts", "report_physical_rollouts",
        }
        for index, task in enumerate(arm["tasks"]):
            if type(task) is not dict or set(task) != task_keys \
                    or task["coordinate_index"] != index \
                    or type(task["qualified"]) is not bool \
                    or any(type(task[key]) is not int or task[key] < 0
                           for key in task_keys - {
                               "coordinate_index", "qualified"}):
                raise BeliefPolicyExecutionError(
                    "policy capacity task reconstruction drift")
        expected_pass = (
            all(task["qualified"] for task in arm["tasks"])
            and arm["swap_used_bytes_after"]
            <= arm["swap_used_bytes_before"]
            and arm["projected_process_rss_bytes"] * 1_000_000_000
            <= arm["host_memory_bytes"] * 750_000_000)
        if arm["passed"] is not expected_pass:
            raise BeliefPolicyExecutionError(
                "policy capacity arm pass derivation drift")
    passing = tuple(row["workers"] for row in receipt["arms"]
                    if row.get("passed") is True)
    eligible = tuple(workers for workers in passing
                     if workers <= len(POLICY_RANKS)
                     and any(larger > workers for larger in passing))
    if not eligible or receipt["selected_workers"] != max(eligible) \
            or receipt["headroom_workers"] \
            != min(workers for workers in passing
                   if workers > receipt["selected_workers"]):
        raise BeliefPolicyExecutionError(
            "policy capacity selection reconstruction drift")


def build_freeze(
        envelope_raw: bytes, *, evidence_root: Path,
        model_root: Path) -> dict[str, Any]:
    envelope = _strict_json(envelope_raw, label="capacity envelope")
    receipt = envelope.get("receipt")
    source = envelope.get("source")
    runtime = envelope.get("runtime")
    if set(envelope) != {
            "schema", "source", "runtime", "models",
            "source_review_commit", "source_review_marker_sha256",
            "receipt", "scientific_execution_authorized",
            "r4_test_opened", "strength_claim_authorized",
            "deployment_authorized"} \
            or envelope["schema"] \
            != "belief-r4-policy-capacity-envelope-v1" \
            or type(receipt) is not dict or receipt.get("schema") != CAPACITY_SCHEMA \
            or type(source) is not dict or type(runtime) is not dict \
            or not isinstance(evidence_root, Path) \
            or not evidence_root.is_absolute() \
            or not isinstance(model_root, Path) or not model_root.is_absolute():
        raise BeliefPolicyExecutionError("policy freeze input drift")
    validate_capacity_receipt(receipt)
    _validate_model_identity(envelope["models"])
    if set(source) != {
            "execution_git", "file_count", "source_manifest_sha256"} \
            or receipt["execution_git"] != source["execution_git"] \
            or receipt["source_manifest_sha256"] \
            != source["source_manifest_sha256"] \
            or type(source["file_count"]) is not int \
            or source["file_count"] <= 0 \
            or not _is_sha(runtime.get("compatibility_sha256")) \
            or envelope["scientific_execution_authorized"] is not False \
            or envelope["r4_test_opened"] is not False \
            or envelope["strength_claim_authorized"] is not False \
            or envelope["deployment_authorized"] is not False:
        raise BeliefPolicyExecutionError(
            "policy capacity envelope reconstruction drift")
    estimate = receipt["scientific_wall_estimate_nanoseconds"]
    if type(estimate) is not int or estimate <= 0:
        raise BeliefPolicyExecutionError("policy capacity estimate drift")
    wall_cap = min(
        MAX_SCIENTIFIC_WALL_NANOSECONDS,
        estimate + max(estimate // 2, MIN_DEADLINE_RESERVE_NANOSECONDS))
    if wall_cap < estimate:
        raise BeliefPolicyExecutionError(
            "policy measured estimate exceeds fixed scientific cap")
    coordinates = policy_round_coordinates()
    freeze = {
        "schema": FREEZE_SCHEMA,
        "execution_git": source["execution_git"],
        "source_manifest_sha256": source["source_manifest_sha256"],
        "runtime_compatibility_sha256": runtime["compatibility_sha256"],
        "capacity_receipt_sha256": _sha256(envelope_raw),
        "model_root": str(model_root),
        "models": envelope["models"],
        "evidence_root": str(evidence_root),
        "protocol_schema": POLICY_PROTOCOL_SCHEMA,
        "coordinate_sha256": _sha256(canonical_json_bytes({
            "coordinates": [row.__dict__ for row in coordinates]})),
        "target_round_count": TARGET_ROUND_COUNT,
        "workers": receipt["selected_workers"],
        "headroom_workers": receipt["headroom_workers"],
        "scientific_wall_estimate_nanoseconds": estimate,
        "next_unit_reserve_nanoseconds": (
            receipt["selected_max_root_wall_nanoseconds"]),
        "scientific_wall_cap_nanoseconds": wall_cap,
        "authority": {
            "freeze_review_authorized": True,
            "scientific_execution_authorized": False,
            "r4_test_opening_authorized": False,
            "retry_after_terminal_authorized": False,
            "r5_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
    validate_freeze(freeze)
    return freeze


def validate_freeze(freeze: dict[str, Any]) -> None:
    keys = {
        "schema", "execution_git", "source_manifest_sha256",
        "runtime_compatibility_sha256", "capacity_receipt_sha256",
        "model_root", "models", "evidence_root", "protocol_schema",
        "coordinate_sha256", "target_round_count", "workers",
        "headroom_workers", "scientific_wall_estimate_nanoseconds",
        "next_unit_reserve_nanoseconds", "scientific_wall_cap_nanoseconds",
        "authority",
    }
    coordinates = policy_round_coordinates()
    expected_coordinate_sha = _sha256(canonical_json_bytes({
        "coordinates": [row.__dict__ for row in coordinates]}))
    if type(freeze) is not dict or set(freeze) != keys \
            or freeze["schema"] != FREEZE_SCHEMA \
            or not _is_sha(freeze["execution_git"], 40) \
            or any(not _is_sha(freeze[key]) for key in (
                "source_manifest_sha256", "runtime_compatibility_sha256",
                "capacity_receipt_sha256", "coordinate_sha256")) \
            or freeze["coordinate_sha256"] != expected_coordinate_sha \
            or freeze["target_round_count"] != TARGET_ROUND_COUNT \
            or freeze["workers"] not in CAPACITY_WORKER_ARMS \
            or freeze["headroom_workers"] not in CAPACITY_WORKER_ARMS \
            or freeze["headroom_workers"] <= freeze["workers"] \
            or freeze["scientific_wall_estimate_nanoseconds"] <= 0 \
            or type(freeze["next_unit_reserve_nanoseconds"]) is not int \
            or freeze["next_unit_reserve_nanoseconds"] <= 0 \
            or not freeze["scientific_wall_estimate_nanoseconds"] \
            <= freeze["scientific_wall_cap_nanoseconds"] \
            <= MAX_SCIENTIFIC_WALL_NANOSECONDS \
            or type(freeze["model_root"]) is not str \
            or not Path(freeze["model_root"]).is_absolute() \
            or type(freeze["evidence_root"]) is not str \
            or not Path(freeze["evidence_root"]).is_absolute() \
            or freeze["protocol_schema"] != POLICY_PROTOCOL_SCHEMA \
            or freeze["authority"] != {
                "freeze_review_authorized": True,
                "scientific_execution_authorized": False,
                "r4_test_opening_authorized": False,
                "retry_after_terminal_authorized": False,
                "r5_authorized": False,
                "gameplay_authorized": False,
                "strength_claim_authorized": False,
                "deployment_authorized": False,
            }:
        raise BeliefPolicyExecutionError("policy freeze reconstruction drift")
    _validate_model_identity(freeze["models"])


def build_admission(
        freeze: dict[str, Any], *, review_commit: str,
        review_marker: bytes) -> dict[str, Any]:
    claim = expected_freeze_review_claim(freeze)
    expected_marker = FREEZE_REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
    if review_marker != expected_marker or not _is_sha(review_commit, 40):
        raise BeliefPolicyExecutionError(
            "policy admission review binding drift")
    return {
        "schema": ADMISSION_SCHEMA,
        "freeze_sha256": _sha256(canonical_json_bytes(freeze)),
        "review_commit": review_commit,
        "review_marker_sha256": _sha256(review_marker),
        "created_unix_nanoseconds": time.time_ns(),
        "authority": {
            "one_scientific_execution_authorized": True,
            "resume_missing_shards_before_deadline_authorized": True,
            "r4_test_opening_authorized": False,
            "retry_after_terminal_authorized": False,
            "r5_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
