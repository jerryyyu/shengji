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
        "training_device_memory_bytes"}
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
            result.training_device_memory_bytes)):
        raise BeliefV2FreezeBuilderError("V2 resource cap value drift")
    return result


def _v1_route(
        terminal_raw: bytes, *, reentry_rationale_raw: bytes | None
        ) -> tuple[str, str, str, str | None]:
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
        _sha256(canonical_json_bytes(resources)), rationale_sha)


def build_execution_freeze_from_receipts(
        *, repo: Path, expected_git: str, source_review_commit: str,
        v1_terminal_report_raw: bytes,
        v2_reentry_rationale_raw: bytes | None,
        inventory_raw: bytes, group_split_raw: bytes,
        preflight_raw: bytes, seed_scan_raw: bytes,
        seed_registry_raw: bytes, training_candidate_device: str,
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

    scan = _canonical_object(seed_scan_raw, label="seed scan")
    registry = _canonical_object(seed_registry_raw, label="seed registry")
    if seed_scan_bytes(scan) != seed_scan_raw \
            or seed_registry_bytes(registry, scan=scan) \
            != seed_registry_raw \
            or scan.get("git_commit") != expected_git:
        raise BeliefV2FreezeBuilderError(
            "V2 seed registry/source-head reconstruction drift")

    route, terminal_sha, resource_sha, rationale_sha = _v1_route(
        v1_terminal_report_raw,
        reentry_rationale_raw=v2_reentry_rationale_raw)
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
    freeze = V2ExecutionFreezeV1(
        execution_git=expected_git,
        source_manifest_sha256=source_manifest_sha256(
            expected_git, source_bindings),
        source_bindings=source_bindings, runtime=runtime,
        source_review_commit=source_review_commit,
        v1_terminal_route=route,
        v1_terminal_result_sha256=terminal_sha,
        v1_resource_receipt_sha256=resource_sha,
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
