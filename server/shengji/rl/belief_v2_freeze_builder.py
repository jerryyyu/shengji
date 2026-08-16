"""Receipt-driven construction of the BELIEF-V1 V2 execution freeze.

The execution freeze is intentionally host-specific, but it must not be
hand-assembled.  This module reopens the already-reviewed aggregate inputs,
derives their exact identities and population counts, binds the live source
and numerical runtime, and returns the one canonical freeze object that may
later receive an external execution review.  It does not initialize an
evidence namespace, open a test split, launch a worker, or grant authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .belief_b2_result import (
    NO_BEHAVIOR,
    NO_LIFT,
    PASS,
    REFUSE_INCOMPLETE,
    REFUSE_MECHANICS,
    RESOURCE_SCHEMA as V1_RESOURCE_SCHEMA,
)
from .belief_artifacts import stable_read_bytes
from .belief_b2_execution import (
    execution_design_from_bytes,
    pipeline_admission_from_bytes,
    validate_pipeline_consumption_tombstone,
)
from .belief_b2_terminal_controller import TERMINAL_REPORT_SCHEMA
from .belief_contract import canonical_json_bytes
from .belief_v2_accelerator import (
    build_training_device_profile,
    canonical_training_device,
    require_training_device,
)
from .belief_v2_device_qualification import qualification_protocol_sha256
from .belief_v2_execution_identity import (
    build_runtime_profile,
    build_source_bindings,
    source_manifest_sha256,
)
from .belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    CAP_SCHEMA,
    HUMAN_COHORT_ID,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_COHORT_ID,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2ResourceCapsV1,
    _canonical_remote_tip,
    _git,
    validate_execution_freeze,
)
from .belief_v2_human_inventory import group_split_bytes, inventory_bytes
from .belief_v2_preflight import preflight_result_bytes
from .belief_v2_seed_registry import seed_registry_bytes, seed_scan_bytes


FREEZE_INPUT_SCHEMA = "belief-v1-v2-execution-freeze-inputs-v1"
SCALE_COHORT_ID = "synthetic-scale-50"


class BeliefV2FreezeBuilderError(ValueError):
    """A reviewed receipt or freeze-construction input drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_number(value: str) -> None:
    raise BeliefV2FreezeBuilderError(
        f"V2 freeze input contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefV2FreezeBuilderError(
                "V2 freeze input has duplicate JSON key")
        result[key] = value
    return result


def _canonical_object(raw: bytes, *, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise BeliefV2FreezeBuilderError(f"V2 {label} bytes are empty")
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefV2FreezeBuilderError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2FreezeBuilderError(
            f"V2 {label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefV2FreezeBuilderError(f"V2 {label} is not canonical")
    return value


def standard_cohort_plans() -> tuple[V2CohortPlanV1, ...]:
    """Return the single closed model comparison/data-scale population."""
    return (
        V2CohortPlanV1(
            cohort_id=PRIMARY_COHORT_ID, kind="synthetic-primary",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=None),
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=PRIMARY_COHORT_ID),
        V2CohortPlanV1(
            cohort_id=HUMAN_COHORT_ID, kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id=PRIMARY_COHORT_ID),
        V2CohortPlanV1(
            cohort_id=SCALE_COHORT_ID, kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id=PRIMARY_COHORT_ID),
    )


def resource_caps_from_bytes(raw: bytes) -> V2ResourceCapsV1:
    payload = _canonical_object(raw, label="resource caps")
    keys = {
        "schema", "capture_core_hours", "capture_wall_seconds",
        "capture_bytes", "reference_core_hours",
        "reference_wall_seconds", "reference_bytes",
        "training_device_hours", "training_wall_seconds",
        "training_bytes", "training_host_memory_bytes",
        "training_device_memory_bytes",
        "capture_next_unit_wall_estimate_nanoseconds",
        "reference_next_unit_wall_estimate_nanoseconds",
        "training_next_epoch_wall_estimate_nanoseconds",
        "deadline_safety_reserve_nanoseconds"}
    if set(payload) != keys or payload.get("schema") != CAP_SCHEMA:
        raise BeliefV2FreezeBuilderError("V2 resource cap field drift")
    try:
        result = V2ResourceCapsV1(**payload)
    except TypeError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 resource cap construction drift") from exc
    if any(type(value) is not int or value <= 0 for value in (
            result.capture_core_hours, result.capture_wall_seconds,
            result.capture_bytes, result.reference_core_hours,
            result.reference_wall_seconds, result.reference_bytes,
            result.training_device_hours, result.training_wall_seconds,
            result.training_bytes, result.training_host_memory_bytes,
            result.training_device_memory_bytes,
            result.capture_next_unit_wall_estimate_nanoseconds,
            result.reference_next_unit_wall_estimate_nanoseconds,
            result.training_next_epoch_wall_estimate_nanoseconds,
            result.deadline_safety_reserve_nanoseconds)):
        raise BeliefV2FreezeBuilderError("V2 resource cap value drift")
    return result


DEADLINE_ESTIMATE_SCHEMA = "belief-v1-v2-deadline-estimate-receipt-v1"


def _deadline_estimate_receipt(
        raw: bytes, *, expected_git: str,
        resource_caps: V2ResourceCapsV1) -> dict[str, Any]:
    payload = _canonical_object(raw, label="deadline estimate receipt")
    keys = {
        "schema", "execution_git", "runtime_profile_sha256",
        "capture_sample_count", "capture_p95_wall_nanoseconds",
        "reference_sample_count", "reference_p95_wall_nanoseconds",
        "training_epoch_sample_count", "training_epoch_p95_wall_nanoseconds",
        "safety_reserve_nanoseconds", "test_split_opened",
        "pipeline_execution_authorized", "retry_authorized",
        "strength_claim_authorized", "deployment_authorized"}
    if set(payload) != keys \
            or payload.get("schema") != DEADLINE_ESTIMATE_SCHEMA \
            or payload.get("execution_git") != expected_git \
            or any(type(payload.get(key)) is not int
                   or payload[key] <= 0 for key in (
                       "capture_sample_count",
                       "capture_p95_wall_nanoseconds",
                       "reference_sample_count",
                       "reference_p95_wall_nanoseconds",
                       "training_epoch_sample_count",
                       "training_epoch_p95_wall_nanoseconds",
                       "safety_reserve_nanoseconds")) \
            or payload["capture_sample_count"] < 32 \
            or payload["reference_sample_count"] < 32 \
            or payload["training_epoch_sample_count"] < 2 \
            or payload["capture_p95_wall_nanoseconds"] \
            != resource_caps.capture_next_unit_wall_estimate_nanoseconds \
            or payload["reference_p95_wall_nanoseconds"] \
            != resource_caps.reference_next_unit_wall_estimate_nanoseconds \
            or payload["training_epoch_p95_wall_nanoseconds"] \
            != resource_caps.training_next_epoch_wall_estimate_nanoseconds \
            or payload["safety_reserve_nanoseconds"] \
            != resource_caps.deadline_safety_reserve_nanoseconds \
            or type(payload.get("runtime_profile_sha256")) is not str \
            or len(payload["runtime_profile_sha256"]) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in payload["runtime_profile_sha256"]) \
            or any(payload.get(key) is not False for key in (
                "test_split_opened", "pipeline_execution_authorized",
                "retry_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2FreezeBuilderError(
            "V2 deadline estimate receipt drift")
    return payload


V1_RESOURCE_FAILURE_SCHEMA = (
    "belief-v1-b2-operator-stopped-resource-failure-v1")
V1_RESOURCE_REENTRY_ROUTE = (
    "RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW")


def _v1_resource_failure_receipt(raw: bytes) -> dict[str, Any]:
    receipt = _canonical_object(raw, label="V1 resource failure receipt")
    keys = {
        "schema", "v1_execution_git", "v1_design_sha256",
        "v1_admission_sha256", "v1_source_review_commit",
        "termination_review_commit", "closeout_ledger_commit",
        "closeout_ledger_sha256", "termination_route",
        "frozen_training_wall_seconds",
        "observed_training_wall_nanoseconds_at_stop",
        "candidate_exit_status", "control_exit_status",
        "supervisor_log_sha256",
        "training_partial_slots", "training_final_artifacts_absent",
        "calibration_artifacts_absent", "test_split_artifacts_absent",
        "terminal_artifacts_absent", "test_split_decision_open_count",
        "admission_spent", "retry_authorized", "model_result_exists",
        "calibration_result_exists", "strength_result_exists",
        "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    sha_keys = (
        "v1_design_sha256", "v1_admission_sha256",
        "closeout_ledger_sha256", "supervisor_log_sha256")
    git_keys = (
        "v1_execution_git", "v1_source_review_commit",
        "termination_review_commit", "closeout_ledger_commit")
    if set(receipt) != keys \
            or receipt.get("schema") != V1_RESOURCE_FAILURE_SCHEMA \
            or any(type(receipt.get(key)) is not str
                   or len(receipt[key]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in receipt[key]) for key in sha_keys) \
            or any(type(receipt.get(key)) is not str
                   or len(receipt[key]) != 40
                   or any(char not in "0123456789abcdef"
                          for char in receipt[key]) for key in git_keys) \
            or receipt.get("termination_route") \
            != "operator-stopped-after-frozen-cap" \
            or type(receipt.get("frozen_training_wall_seconds")) is not int \
            or receipt["frozen_training_wall_seconds"] <= 0 \
            or type(receipt.get(
                "observed_training_wall_nanoseconds_at_stop")) is not int \
            or receipt["observed_training_wall_nanoseconds_at_stop"] \
            <= receipt["frozen_training_wall_seconds"] * 1_000_000_000 \
            or receipt.get("candidate_exit_status") != 143 \
            or receipt.get("control_exit_status") != 143 \
            or receipt.get("training_partial_slots") != [
                "candidate.partial",
                "hard-geometry-label-permutation.partial"] \
            or receipt.get("test_split_decision_open_count") != 0 \
            or any(receipt.get(key) is not True for key in (
                "training_final_artifacts_absent",
                "calibration_artifacts_absent",
                "test_split_artifacts_absent",
                "terminal_artifacts_absent", "admission_spent")) \
            or any(receipt.get(key) is not False for key in (
                "retry_authorized", "model_result_exists",
                "calibration_result_exists", "strength_result_exists",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2FreezeBuilderError(
            "V2 V1 resource failure receipt drift")
    return receipt


def _authenticate_v1_resource_failure_receipt(
        repo: Path, receipt: dict[str, Any]) -> None:
    """Bind V1 termination and closeout facts to the real main ledger."""
    try:
        remote_tip = _canonical_remote_tip(repo)
        if _git(repo, "rev-parse", "origin/main") != remote_tip:
            raise BeliefV2FreezeBuilderError(
                "V2 V1 failure local canonical ref drift")
        commits = (
            receipt["v1_source_review_commit"],
            receipt["termination_review_commit"],
            receipt["closeout_ledger_commit"])
        if any(subprocess.run(
                ("git", "merge-base", "--is-ancestor", commit, remote_tip),
                cwd=repo, capture_output=True).returncode != 0
               for commit in commits):
            raise BeliefV2FreezeBuilderError(
                "V2 V1 failure receipt is not on canonical main")
        identity = tuple(str(_git(
            repo, "show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B",
            receipt["termination_review_commit"])).splitlines())
        if len(identity) < 5 or identity[:4] != (
                "Claude", "noreply@anthropic.com",
                "Claude", "noreply@anthropic.com") \
                or not any(line.startswith(
                    "Claude-Session: https://claude.ai/code/session_")
                           for line in identity[4:]):
            raise BeliefV2FreezeBuilderError(
                "V2 V1 termination review identity drift")
        closeout_parent = str(_git(
            repo, "show", "-s", "--format=%P",
            receipt["closeout_ledger_commit"])).split()
        if closeout_parent != [receipt["termination_review_commit"]]:
            raise BeliefV2FreezeBuilderError(
                "V2 V1 termination/closeout ancestry drift")
        termination_ledger = _git(
            repo, "show", receipt["termination_review_commit"]
            + ":HANDOFF_REVIEW.md", binary=True)
        closeout_ledger = _git(
            repo, "show", receipt["closeout_ledger_commit"]
            + ":HANDOFF_REVIEW.md", binary=True)
    except BeliefV2FreezeBuilderError:
        raise
    except (KeyError, ValueError) as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 failure receipt authentication failed") from exc
    if b"SAFE_TO_TERMINATE" not in termination_ledger \
            or receipt["v1_execution_git"].encode("ascii") \
            not in termination_ledger \
            or b"operator-stopped-after-frozen-cap" not in closeout_ledger \
            or _sha256(closeout_ledger) != receipt["closeout_ledger_sha256"]:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 failure canonical ledger binding drift")


def build_v1_resource_failure_receipt(
        *, repo: Path, design_path: Path, evidence_root: Path,
        supervisor_log_path: Path, termination_review_commit: str,
        closeout_ledger_commit: str) -> bytes:
    """Derive the narrow V1 closeout receipt without opening corpus/model bytes."""
    paths = (repo, design_path, evidence_root, supervisor_log_path)
    if any(not isinstance(path, Path) or not path.is_absolute()
           for path in paths) \
            or repo.is_symlink() or design_path.is_symlink() \
            or evidence_root.is_symlink() or supervisor_log_path.is_symlink() \
            or not repo.is_dir() or not design_path.is_file() \
            or not evidence_root.is_dir() or not supervisor_log_path.is_file():
        raise BeliefV2FreezeBuilderError(
            "V2 V1 closeout receipt path drift")
    design_raw = stable_read_bytes(design_path)
    admission_raw = stable_read_bytes(evidence_root / "admission.json")
    review_marker = stable_read_bytes(evidence_root / "review.md")
    tombstone_raw = stable_read_bytes(
        evidence_root.with_name(evidence_root.name + ".consumed.json"))
    try:
        design = execution_design_from_bytes(design_raw)
        admission = pipeline_admission_from_bytes(
            admission_raw, design=design, review_marker=review_marker)
        validate_pipeline_consumption_tombstone(
            tombstone_raw, admission=admission)
    except ValueError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 closeout design/admission refused") from exc
    if Path(design.evidence_root) != evidence_root \
            or admission.evidence_root != str(evidence_root):
        raise BeliefV2FreezeBuilderError(
            "V2 V1 closeout namespace binding drift")
    expected_root_entries = {
        "admission.json", "capture", "design.json", "reference",
        "review.md", "training"}
    if {path.name for path in evidence_root.iterdir()} \
            != expected_root_entries \
            or stable_read_bytes(evidence_root / "design.json") != design_raw:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 closeout evidence population drift")
    training = evidence_root / "training"
    partial_names = (
        "candidate.partial", "hard-geometry-label-permutation.partial")
    if training.is_symlink() or not training.is_dir() \
            or tuple(sorted(path.name for path in training.iterdir())) \
            != partial_names \
            or any((training / name).is_symlink()
                   or not (training / name).is_dir()
                   for name in partial_names) \
            or any((training / name).exists() for name in (
                "candidate", "hard-geometry-label-permutation")) \
            or any((evidence_root / name).exists() for name in (
                "calibration", "terminal", "terminal.partial")):
        raise BeliefV2FreezeBuilderError(
            "V2 V1 closeout partial/final population drift")
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(supervisor_log_path, flags)
        try:
            before = os.fstat(descriptor)
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                log_raw = handle.read()
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 supervisor log stable-read failed") from exc

    def file_identity(row):
        return (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
                row.st_size, row.st_mtime_ns)

    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
            or not log_raw or file_identity(before) != file_identity(after) \
            or len(log_raw) != before.st_size:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 supervisor log stable-read drift")
    try:
        log = log_raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 supervisor log encoding drift") from exc
    cohort_names = ("candidate", "hard-geometry-label-permutation")
    timestamps = {}
    for cohort in cohort_names:
        starts = [line for line in log.splitlines()
                  if f"stage=train item={cohort} " in line
                  and line.endswith("status=started")]
        exits = [line for line in log.splitlines()
                 if f"stage=train item={cohort} " in line
                 and line.endswith("status=exit-143")]
        if len(starts) != 1 or len(exits) != 1:
            raise BeliefV2FreezeBuilderError(
                "V2 V1 supervisor train lifecycle drift")
        timestamps[cohort] = (
            datetime.fromisoformat(starts[0].split()[0].replace("Z", "+00:00")),
            datetime.fromisoformat(exits[0].split()[0].replace("Z", "+00:00")))
    if any(token in log for token in (
            "stage=open-test", "stage=verify-terminal",
            "stage=supervisor item=exact-design status=complete")):
        raise BeliefV2FreezeBuilderError(
            "V2 V1 supervisor opened a forbidden later stage")
    observed = min(int((finished - started).total_seconds()
                       * 1_000_000_000)
                   for started, finished in timestamps.values())
    frozen_wall = design.to_dict()["resource_caps"]["training_wall_seconds"]
    closeout_ledger = _git(
        repo, "show", closeout_ledger_commit + ":HANDOFF_REVIEW.md",
        binary=True)
    receipt = {
        "schema": V1_RESOURCE_FAILURE_SCHEMA,
        "v1_execution_git": design.execution_git,
        "v1_design_sha256": _sha256(design_raw),
        "v1_admission_sha256": _sha256(admission_raw),
        "v1_source_review_commit": admission.review_commit,
        "termination_review_commit": termination_review_commit,
        "closeout_ledger_commit": closeout_ledger_commit,
        "closeout_ledger_sha256": _sha256(closeout_ledger),
        "termination_route": "operator-stopped-after-frozen-cap",
        "frozen_training_wall_seconds": frozen_wall,
        "observed_training_wall_nanoseconds_at_stop": observed,
        "candidate_exit_status": 143, "control_exit_status": 143,
        "supervisor_log_sha256": _sha256(log_raw),
        "training_partial_slots": list(partial_names),
        "training_final_artifacts_absent": True,
        "calibration_artifacts_absent": True,
        "test_split_artifacts_absent": True,
        "terminal_artifacts_absent": True,
        "test_split_decision_open_count": 0,
        "admission_spent": True, "retry_authorized": False,
        "model_result_exists": False, "calibration_result_exists": False,
        "strength_result_exists": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    raw = canonical_json_bytes(receipt)
    _v1_resource_failure_receipt(raw)
    _authenticate_v1_resource_failure_receipt(repo, receipt)
    return raw


def _v1_route(
        terminal_raw: bytes | None, *,
        resource_failure_raw: bytes | None,
        reentry_rationale_raw: bytes | None
        ) -> tuple[str, str | None, str | None, str | None, str | None]:
    if terminal_raw is None:
        if type(resource_failure_raw) is not bytes \
                or not resource_failure_raw \
                or type(reentry_rationale_raw) is not bytes \
                or not reentry_rationale_raw:
            raise BeliefV2FreezeBuilderError(
                "V2 resource-failure route lacks exact receipts")
        _v1_resource_failure_receipt(resource_failure_raw)
        return (
            V1_RESOURCE_REENTRY_ROUTE, None, None,
            _sha256(resource_failure_raw),
            _sha256(reentry_rationale_raw))
    if resource_failure_raw is not None:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 route contains competing receipts")
    report = _canonical_object(terminal_raw, label="V1 terminal report")
    expected_keys = {
        "schema", "protocol_sha256", "design_sha256",
        "admission_sha256", "evidence", "terminal",
        "test_split_open_count", "terminal_reproducibility_review_required",
        "b3_sampler_implementation_authorized", "sampler_run_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "promotion_authorized", "deployment_authorized"}
    if set(report) != expected_keys \
            or report.get("schema") != TERMINAL_REPORT_SCHEMA \
            or report.get("test_split_open_count") != 1 \
            or report.get("terminal_reproducibility_review_required") is not True \
            or any(report.get(key) is not False for key in (
                "b3_sampler_implementation_authorized",
                "sampler_run_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "promotion_authorized",
                "deployment_authorized")) \
            or type(report.get("terminal")) is not dict \
            or type(report.get("evidence")) is not dict \
            or type(report["evidence"].get("resources")) is not dict:
        raise BeliefV2FreezeBuilderError(
            "V2 V1 terminal report identity/authority drift")
    decision = report["terminal"].get("decision")
    resources = report["evidence"]["resources"]
    if resources.get("schema") != V1_RESOURCE_SCHEMA \
            or resources.get("within_frozen_caps") is not True:
        raise BeliefV2FreezeBuilderError("V2 V1 resource receipt drift")
    if decision == PASS:
        if reentry_rationale_raw is not None:
            raise BeliefV2FreezeBuilderError(
                "V2 V1 pass route contains reentry rationale")
        route = "v1-pass-to-b3"
        rationale_sha = None
    elif decision in (NO_LIFT, NO_BEHAVIOR):
        if type(reentry_rationale_raw) is not bytes \
                or not reentry_rationale_raw:
            raise BeliefV2FreezeBuilderError(
                "V2 SELECT_NONE route lacks reentry rationale")
        route = "v1-select-none-with-named-domain-shift-reentry"
        rationale_sha = _sha256(reentry_rationale_raw)
    elif decision in (REFUSE_MECHANICS, REFUSE_INCOMPLETE):
        raise BeliefV2FreezeBuilderError(
            "V2 cannot freeze after a V1 refusal route")
    else:
        raise BeliefV2FreezeBuilderError("V2 V1 terminal decision drift")
    return (
        route, _sha256(terminal_raw),
        _sha256(canonical_json_bytes(resources)), None, rationale_sha)


def build_execution_freeze_from_receipts(
        *, repo: Path, expected_git: str, source_review_commit: str,
        v1_terminal_report_raw: bytes | None,
        v1_resource_failure_receipt_raw: bytes | None,
        v2_reentry_rationale_raw: bytes | None,
        inventory_raw: bytes, group_split_raw: bytes,
        preflight_raw: bytes, seed_scan_raw: bytes,
        seed_registry_raw: bytes, training_candidate_device: str,
        deadline_estimate_raw: bytes,
        resource_caps: V2ResourceCapsV1,
        evidence_root: Path) -> V2ExecutionFreezeV1:
    """Reopen every receipt and build one host-specific canonical freeze."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not isinstance(evidence_root, Path) \
            or not evidence_root.is_absolute():
        raise BeliefV2FreezeBuilderError("V2 freeze path input drift")

    inventory = _canonical_object(inventory_raw, label="H0 inventory")
    group_split = _canonical_object(group_split_raw, label="H0 group split")
    if inventory_bytes(inventory) != inventory_raw \
            or group_split_bytes(group_split, inventory=inventory) \
            != group_split_raw:
        raise BeliefV2FreezeBuilderError(
            "V2 H0 inventory/group split reconstruction drift")

    preflight = _canonical_object(preflight_raw, label="preflight result")
    if preflight_result_bytes(preflight) != preflight_raw:
        raise BeliefV2FreezeBuilderError(
            "V2 preflight result reconstruction drift")
    deadline_estimate = _deadline_estimate_receipt(
        deadline_estimate_raw, expected_git=expected_git,
        resource_caps=resource_caps)

    scan = _canonical_object(seed_scan_raw, label="seed scan")
    registry = _canonical_object(seed_registry_raw, label="seed registry")
    if seed_scan_bytes(scan) != seed_scan_raw \
            or seed_registry_bytes(registry, scan=scan) \
            != seed_registry_raw \
            or scan.get("git_commit") != expected_git:
        raise BeliefV2FreezeBuilderError(
            "V2 seed registry/source-head reconstruction drift")

    route, terminal_sha, resource_sha, failure_sha, rationale_sha = _v1_route(
        v1_terminal_report_raw,
        resource_failure_raw=v1_resource_failure_receipt_raw,
        reentry_rationale_raw=v2_reentry_rationale_raw)
    if v1_resource_failure_receipt_raw is not None:
        _authenticate_v1_resource_failure_receipt(
            repo, _v1_resource_failure_receipt(
                v1_resource_failure_receipt_raw))
    try:
        candidate = canonical_training_device(training_candidate_device)
    except ValueError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 training candidate device drift") from exc
    if candidate == "cpu":
        raise BeliefV2FreezeBuilderError(
            "V2 qualification candidate cannot be CPU")
    try:
        require_training_device(candidate)
        device_profile = build_training_device_profile(candidate)
    except ValueError as exc:
        raise BeliefV2FreezeBuilderError(
            "V2 qualification candidate is unavailable at freeze time") \
            from exc

    splits = group_split["splits"]
    if set(splits) != {"train", "calibration", "test"}:
        raise BeliefV2FreezeBuilderError("V2 H0 split population drift")
    source_bindings = build_source_bindings(
        repo, expected_git=expected_git)
    runtime = build_runtime_profile()
    if deadline_estimate["runtime_profile_sha256"] \
            != _sha256(canonical_json_bytes(runtime.to_dict())):
        raise BeliefV2FreezeBuilderError(
            "V2 deadline estimate runtime binding drift")
    freeze = V2ExecutionFreezeV1(
        execution_git=expected_git,
        source_manifest_sha256=source_manifest_sha256(
            expected_git, source_bindings),
        source_bindings=source_bindings, runtime=runtime,
        source_review_commit=source_review_commit,
        v1_terminal_route=route,
        v1_terminal_result_sha256=terminal_sha,
        v1_resource_receipt_sha256=resource_sha,
        v1_resource_failure_receipt_sha256=failure_sha,
        v2_reentry_rationale_sha256=rationale_sha,
        h0_inventory_sha256=_sha256(inventory_raw),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=(
            inventory["source_digest_population_sha256"]),
        human_group_split_sha256=_sha256(group_split_raw),
        human_group_count=inventory["group_count"],
        human_train_group_count=splits["train"]["group_count"],
        human_calibration_group_count=(
            splits["calibration"]["group_count"]),
        human_test_group_count=splits["test"]["group_count"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=(
            splits["train"]["human_play_decisions"]),
        human_calibration_eligible_decision_count=(
            splits["calibration"]["human_play_decisions"]),
        human_test_eligible_decision_count=(
            splits["test"]["human_play_decisions"]),
        preflight_result_sha256=_sha256(preflight_raw),
        preflight_runtime_sha256=_sha256(canonical_json_bytes(
            preflight["runtime"])),
        deadline_estimate_receipt_sha256=_sha256(deadline_estimate_raw),
        seed_registry_sha256=_sha256(seed_registry_raw),
        seed_candidate_report_sha256=registry["candidate_report_sha256"],
        training_candidate_device=candidate,
        training_device_profile=device_profile,
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256(candidate)),
        cohorts=standard_cohort_plans(), resource_caps=resource_caps,
        evidence_root=str(evidence_root))
    validate_execution_freeze(freeze)
    return freeze
