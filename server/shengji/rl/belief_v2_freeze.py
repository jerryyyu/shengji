"""Exact execution-freeze schema for the BELIEF-V1 V2 offline pipeline.

This module closes the shape of the packet that will be populated after the
V1 terminal, H0 inventory, and multi-rank capacity receipts exist.  It has no
filesystem writer, corpus reader, worker launcher, training loop, test opener,
gameplay path, or deployment authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_protocol import (
    V2_CAPTURE_LANES,
    V2_RANKS,
    V2_ROUND_COUNT,
    V2_SPLIT_COUNTS,
    protocol_sha256,
    schedule_sha256,
)
from .belief_v2_execution_identity import (
    PACKAGE_SCHEMA,
    RUNTIME_SCHEMA,
    SOURCE_SCHEMA,
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
    validate_runtime_profile,
    validate_source_bindings,
)
from .belief_v2_accelerator import (
    V2TrainingDeviceProfileV1,
    canonical_training_device,
    validate_training_device_profile,
)
from .belief_v2_device_qualification import (
    qualification_protocol_sha256,
)


FREEZE_SCHEMA = "belief-v1-v2-offline-execution-freeze-v1"
COHORT_SCHEMA = "belief-v1-v2-training-cohort-plan-v1"
CAP_SCHEMA = "belief-v1-v2-resource-caps-v1"
REVIEW_SCHEMA = "belief-v1-v2-offline-execution-review-v1"
ADMISSION_SCHEMA = "belief-v1-v2-offline-pipeline-admission-v1"
CONSUMPTION_SCHEMA = "belief-v1-v2-offline-consumption-tombstone-v1"
REVIEW_PREFIX = "BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
RUN_ID = "belief-v1-v2-all-ranks-human-offline-v1"
V1_ROUTES = (
    "v1-pass-to-b3",
    "v1-select-none-with-named-domain-shift-reentry",
)
COHORT_KINDS = (
    "synthetic-primary",
    "hard-geometry-label-permutation",
    "human-mixture",
    "synthetic-scale",
)
PRIMARY_COHORT_ID = "synthetic-primary"
CONTROL_COHORT_ID = "hard-geometry-label-permutation"
HUMAN_COHORT_ID = "human-mixture"
RANK_MATERIAL_REGRESSION_TOLERANCE_PPB = 5_000_000
RANK_CALIBRATION_MINIMUM_ROUNDS = 100
RANK_MULTIPLICITY_RULE = (
    "paired-round-bootstrap-max-statistic-one-sided-familywise-95-v1")
MAX_HUMAN_FRACTION_NUMERATOR = 1
MAX_HUMAN_FRACTION_DENOMINATOR = 5
MIN_PLAY_DECISIONS_PER_COMPLETE_ROUND = 4
V2_TRAIN_ROUND_COUNT = dict(V2_SPLIT_COUNTS)["train"]
ALL_SYNTHETIC_TRAIN_DECISIONS = (
    "all-realized-synthetic-train-decisions-v1")
MIXED_SYNTHETIC_TRAIN_DECISIONS = (
    "all-realized-synthetic-train-decisions-minus-human-count-by-digest-v1")
SCALE_SYNTHETIC_TRAIN_DECISIONS = (
    "digest-ranked-prefix-of-realized-synthetic-train-decisions-v1")
NO_HUMAN_DECISIONS = "none"
ALL_HUMAN_TRAIN_DECISIONS = (
    "all-h0-train-decisions-once-in-group-and-decision-digest-order-v1")
PRIMARY_WORK_RULE = "all-realized-synthetic-train-decisions-per-epoch-v1"
MIXED_WORK_RULE = (
    "replace-one-synthetic-per-human-at-primary-realized-total-v1")
SCALE_WORK_RULE = "floor-primary-realized-work-times-frozen-fraction-v1"


class BeliefV2FreezeError(ValueError):
    """The V2 execution-freeze identity or scientific contract drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _is_git_sha(value: Any) -> bool:
    return (type(value) is str and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_number(value: str) -> None:
    raise BeliefV2FreezeError(
        f"V2 freeze contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefV2FreezeError("V2 freeze has duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class V2CohortPlanV1:
    cohort_id: str
    kind: str
    synthetic_selection_rule: str
    synthetic_fraction_numerator: int
    synthetic_fraction_denominator: int
    human_selection_rule: str
    work_match_rule: str
    comparator_cohort_id: str | None
    member_seeds: tuple[int, ...] = COHORT_SEEDS
    schema: str = COHORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cohort_id": self.cohort_id,
            "kind": self.kind,
            "member_seeds": list(self.member_seeds),
            "member_count": len(self.member_seeds),
            "synthetic_selection_rule": self.synthetic_selection_rule,
            "synthetic_fraction": {
                "numerator": self.synthetic_fraction_numerator,
                "denominator": self.synthetic_fraction_denominator,
            },
            "human_selection_rule": self.human_selection_rule,
            "work_match_rule": self.work_match_rule,
            "comparator_cohort_id": self.comparator_cohort_id,
        }


def _validate_cohort(row: V2CohortPlanV1) -> None:
    if type(row) is not V2CohortPlanV1 or row.schema != COHORT_SCHEMA \
            or type(row.cohort_id) is not str or not row.cohort_id \
            or row.kind not in COHORT_KINDS \
            or row.member_seeds != COHORT_SEEDS \
            or type(row.synthetic_selection_rule) is not str \
            or not row.synthetic_selection_rule \
            or type(row.synthetic_fraction_numerator) is not int \
            or type(row.synthetic_fraction_denominator) is not int \
            or not 0 < row.synthetic_fraction_numerator \
            <= row.synthetic_fraction_denominator \
            or math.gcd(row.synthetic_fraction_numerator,
                        row.synthetic_fraction_denominator) != 1 \
            or type(row.human_selection_rule) is not str \
            or not row.human_selection_rule \
            or type(row.work_match_rule) is not str \
            or not row.work_match_rule \
            or not (row.comparator_cohort_id is None
                    or (type(row.comparator_cohort_id) is str
                        and bool(row.comparator_cohort_id))):
        raise BeliefV2FreezeError("V2 cohort plan identity drift")
    if row.kind in ("synthetic-primary", "synthetic-scale",
                    "hard-geometry-label-permutation"):
        if row.human_selection_rule != NO_HUMAN_DECISIONS:
            raise BeliefV2FreezeError("non-human V2 cohort contains human work")
    elif row.kind == "human-mixture":
        if row.human_selection_rule != ALL_HUMAN_TRAIN_DECISIONS:
            raise BeliefV2FreezeError("V2 human mixture fraction drift")


@dataclass(frozen=True)
class V2ResourceCapsV1:
    capture_core_hours: int
    capture_wall_seconds: int
    capture_bytes: int
    reference_core_hours: int
    reference_wall_seconds: int
    reference_bytes: int
    training_device_hours: int
    training_wall_seconds: int
    training_bytes: int
    training_host_memory_bytes: int
    training_device_memory_bytes: int
    schema: str = CAP_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capture_core_hours": self.capture_core_hours,
            "capture_wall_seconds": self.capture_wall_seconds,
            "capture_bytes": self.capture_bytes,
            "reference_core_hours": self.reference_core_hours,
            "reference_wall_seconds": self.reference_wall_seconds,
            "reference_bytes": self.reference_bytes,
            "training_device_hours": self.training_device_hours,
            "training_wall_seconds": self.training_wall_seconds,
            "training_bytes": self.training_bytes,
            "training_host_memory_bytes": self.training_host_memory_bytes,
            "training_device_memory_bytes": self.training_device_memory_bytes,
        }


def _validate_caps(caps: V2ResourceCapsV1) -> None:
    if type(caps) is not V2ResourceCapsV1 or caps.schema != CAP_SCHEMA \
            or any(type(value) is not int or value <= 0 for value in (
                caps.capture_core_hours, caps.capture_wall_seconds,
                caps.capture_bytes, caps.reference_core_hours,
                caps.reference_wall_seconds, caps.reference_bytes,
                caps.training_device_hours, caps.training_wall_seconds,
                caps.training_bytes, caps.training_host_memory_bytes,
                caps.training_device_memory_bytes)):
        raise BeliefV2FreezeError("V2 resource cap identity drift")


@dataclass(frozen=True)
class V2ExecutionFreezeV1:
    execution_git: str
    source_manifest_sha256: str
    source_bindings: tuple[V2SourceBindingV1, ...]
    runtime: V2RuntimeProfileV1
    source_review_commit: str
    v1_terminal_route: str
    v1_terminal_result_sha256: str
    v1_resource_receipt_sha256: str
    v2_reentry_rationale_sha256: str | None
    h0_inventory_sha256: str
    h0_source_manifest_sha256: str
    h0_source_digest_population_sha256: str
    human_group_split_sha256: str
    human_group_count: int
    human_train_group_count: int
    human_calibration_group_count: int
    human_test_group_count: int
    human_complete_round_count: int
    human_eligible_decision_count: int
    human_train_eligible_decision_count: int
    human_calibration_eligible_decision_count: int
    human_test_eligible_decision_count: int
    preflight_result_sha256: str
    preflight_runtime_sha256: str
    seed_registry_sha256: str
    seed_candidate_report_sha256: str
    training_candidate_device: str
    training_device_profile: V2TrainingDeviceProfileV1
    device_qualification_protocol_sha256: str
    cohorts: tuple[V2CohortPlanV1, ...]
    resource_caps: V2ResourceCapsV1
    evidence_root: str
    schema: str = FREEZE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": RUN_ID,
            "protocol_sha256": protocol_sha256(),
            "schedule_sha256": schedule_sha256(),
            "execution_git": self.execution_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_bindings": [
                row.to_dict() for row in self.source_bindings],
            "runtime": self.runtime.to_dict(),
            "source_review_commit": self.source_review_commit,
            "v1_route": {
                "terminal_route": self.v1_terminal_route,
                "terminal_result_sha256": self.v1_terminal_result_sha256,
                "resource_receipt_sha256": self.v1_resource_receipt_sha256,
                "v2_reentry_rationale_sha256": (
                    self.v2_reentry_rationale_sha256),
            },
            "human_inventory": {
                "inventory_sha256": self.h0_inventory_sha256,
                "source_manifest_sha256": self.h0_source_manifest_sha256,
                "source_digest_population_sha256": (
                    self.h0_source_digest_population_sha256),
                "group_split_sha256": self.human_group_split_sha256,
                "group_count": self.human_group_count,
                "train_group_count": self.human_train_group_count,
                "calibration_group_count": (
                    self.human_calibration_group_count),
                "test_group_count": self.human_test_group_count,
                "complete_round_count": self.human_complete_round_count,
                "eligible_decision_count": (
                    self.human_eligible_decision_count),
                "train_eligible_decision_count": (
                    self.human_train_eligible_decision_count),
                "calibration_eligible_decision_count": (
                    self.human_calibration_eligible_decision_count),
                "test_eligible_decision_count": (
                    self.human_test_eligible_decision_count),
                "group_split_unit": "source-log-session-digest",
                "raw_identity_model_input": False,
                "source_path_model_input": False,
                "world_generating_key_model_input": False,
            },
            "capacity": {
                "preflight_result_sha256": self.preflight_result_sha256,
                "preflight_runtime_sha256": self.preflight_runtime_sha256,
            },
            "seed_registry": {
                "registry_sha256": self.seed_registry_sha256,
                "candidate_report_sha256": (
                    self.seed_candidate_report_sha256),
                "v2_collision_count": 0,
            },
            "training_device_qualification": {
                "candidate_device": self.training_candidate_device,
                "device_profile": self.training_device_profile.to_dict(),
                "protocol_sha256": (
                    self.device_qualification_protocol_sha256),
                "cpu_fallback_on_performance_miss": True,
                "fallback_on_integrity_failure": False,
            },
            "population": {
                "round_count": V2_ROUND_COUNT,
                "capture_lanes": V2_CAPTURE_LANES,
                "trump_ranks": list(V2_RANKS),
                "split_counts": dict(V2_SPLIT_COUNTS),
                "retry_count": 0,
                "drop_count": 0,
            },
            "cohorts": [row.to_dict() for row in self.cohorts],
            "gates": {
                "human_work_match": (
                    "replace-synthetic-decisions-at-fixed-total-work-v1"),
                "maximum_human_fraction": {
                    "numerator": MAX_HUMAN_FRACTION_NUMERATOR,
                    "denominator": MAX_HUMAN_FRACTION_DENOMINATOR,
                },
                "rank_material_regression_tolerance_ppb": (
                    RANK_MATERIAL_REGRESSION_TOLERANCE_PPB),
                "rank_calibration_minimum_rounds": (
                    RANK_CALIBRATION_MINIMUM_ROUNDS),
                "rank_multiplicity_rule": RANK_MULTIPLICITY_RULE,
                "rank_attribution_source": (
                    "balanced-synthetic-rank-contrasts-only"),
                "human_transfer_is_rank_evidence": False,
            },
            "resource_caps": self.resource_caps.to_dict(),
            "evidence_root": self.evidence_root,
            "review": {
                "exact_external_execution_review_required": True,
                "review_schema": REVIEW_SCHEMA,
            },
            "authority": {
                "design_freeze_authorized": True,
                "offline_pipeline_execution_authorized": False,
                "test_split_open_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False,
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def validate_execution_freeze(freeze: V2ExecutionFreezeV1) -> None:
    if type(freeze) is not V2ExecutionFreezeV1 \
            or freeze.schema != FREEZE_SCHEMA \
            or not _is_git_sha(freeze.execution_git) \
            or not _is_git_sha(freeze.source_review_commit) \
            or any(not _is_sha256(value) for value in (
                freeze.source_manifest_sha256,
                freeze.v1_terminal_result_sha256,
                freeze.v1_resource_receipt_sha256,
                freeze.h0_inventory_sha256,
                freeze.h0_source_manifest_sha256,
                freeze.h0_source_digest_population_sha256,
                freeze.human_group_split_sha256,
                freeze.preflight_result_sha256,
                freeze.preflight_runtime_sha256,
                freeze.seed_registry_sha256,
                freeze.seed_candidate_report_sha256,
                freeze.device_qualification_protocol_sha256)) \
            or freeze.v1_terminal_route not in V1_ROUTES \
            or type(freeze.cohorts) is not tuple or not freeze.cohorts \
            or type(freeze.evidence_root) is not str \
            or not Path(freeze.evidence_root).is_absolute() \
            or any(type(value) is not int or value < 0 for value in (
                freeze.human_group_count, freeze.human_train_group_count,
                freeze.human_calibration_group_count,
                freeze.human_test_group_count,
                freeze.human_complete_round_count,
                freeze.human_eligible_decision_count,
                freeze.human_train_eligible_decision_count,
                freeze.human_calibration_eligible_decision_count,
                freeze.human_test_eligible_decision_count)) \
            or min(freeze.human_group_count,
                   freeze.human_complete_round_count,
                   freeze.human_eligible_decision_count) <= 0 \
            or freeze.human_group_count != (
                freeze.human_train_group_count
                + freeze.human_calibration_group_count
                + freeze.human_test_group_count) \
            or freeze.human_eligible_decision_count != (
                freeze.human_train_eligible_decision_count
                + freeze.human_calibration_eligible_decision_count
                + freeze.human_test_eligible_decision_count) \
            or min(freeze.human_train_group_count,
                   freeze.human_calibration_group_count,
                   freeze.human_test_group_count,
                   freeze.human_train_eligible_decision_count,
                   freeze.human_calibration_eligible_decision_count,
                   freeze.human_test_eligible_decision_count) <= 0:
        raise BeliefV2FreezeError("V2 execution freeze identity drift")
    try:
        candidate_device = canonical_training_device(
            freeze.training_candidate_device)
    except ValueError as exc:
        raise BeliefV2FreezeError(
            "V2 training candidate device drift") from exc
    if candidate_device == "cpu" \
            or freeze.training_device_profile.requested_device \
            != candidate_device \
            or freeze.device_qualification_protocol_sha256 \
            != qualification_protocol_sha256(candidate_device):
        raise BeliefV2FreezeError(
            "V2 device qualification protocol drift")
    try:
        validate_training_device_profile(freeze.training_device_profile)
    except ValueError as exc:
        raise BeliefV2FreezeError(
            "V2 training device profile drift") from exc
    # The exact synthetic decision count is deliberately not guessed before
    # capture.  Every complete play-phase round has at least one four-seat
    # trick, so this lower bound proves that consuming every H0 training
    # decision once can never exceed the frozen 20% ceiling.  The capture
    # controller later publishes the exact realized population and fraction.
    if freeze.human_train_eligible_decision_count \
            * MAX_HUMAN_FRACTION_DENOMINATOR \
            > V2_TRAIN_ROUND_COUNT \
            * MIN_PLAY_DECISIONS_PER_COMPLETE_ROUND \
            * MAX_HUMAN_FRACTION_NUMERATOR:
        raise BeliefV2FreezeError("V2 human mixture fraction drift")
    try:
        validate_source_bindings(freeze.source_bindings)
        validate_runtime_profile(freeze.runtime)
    except ValueError as exc:
        raise BeliefV2FreezeError(
            "V2 execution source/runtime identity drift") from exc
    if freeze.source_manifest_sha256 != source_manifest_sha256(
            freeze.execution_git, freeze.source_bindings):
        raise BeliefV2FreezeError("V2 source manifest digest drift")
    if freeze.v1_terminal_route == "v1-pass-to-b3":
        if freeze.v2_reentry_rationale_sha256 is not None:
            raise BeliefV2FreezeError("V2 V1-pass route has reentry drift")
    elif not _is_sha256(freeze.v2_reentry_rationale_sha256):
        raise BeliefV2FreezeError(
            "V2 SELECT_NONE route lacks named reentry evidence")
    _validate_caps(freeze.resource_caps)

    ids = [row.cohort_id for row in freeze.cohorts]
    if len(ids) != len(set(ids)):
        raise BeliefV2FreezeError("V2 cohort identifier population drift")
    for row in freeze.cohorts:
        _validate_cohort(row)
    by_kind = {kind: [row for row in freeze.cohorts if row.kind == kind]
               for kind in COHORT_KINDS}
    if len(by_kind["synthetic-primary"]) != 1 \
            or len(by_kind["hard-geometry-label-permutation"]) != 1 \
            or len(by_kind["human-mixture"]) != 1 \
            or not by_kind["synthetic-scale"]:
        raise BeliefV2FreezeError("V2 cohort kind population drift")
    primary = by_kind["synthetic-primary"][0]
    control = by_kind["hard-geometry-label-permutation"][0]
    human = by_kind["human-mixture"][0]
    if primary.cohort_id != PRIMARY_COHORT_ID \
            or primary.comparator_cohort_id is not None \
            or primary.synthetic_selection_rule \
            != ALL_SYNTHETIC_TRAIN_DECISIONS \
            or (primary.synthetic_fraction_numerator,
                primary.synthetic_fraction_denominator) != (1, 1) \
            or primary.human_selection_rule != NO_HUMAN_DECISIONS \
            or primary.work_match_rule != PRIMARY_WORK_RULE \
            or control.cohort_id != CONTROL_COHORT_ID \
            or control.comparator_cohort_id != PRIMARY_COHORT_ID \
            or control.synthetic_selection_rule \
            != primary.synthetic_selection_rule \
            or (control.synthetic_fraction_numerator,
                control.synthetic_fraction_denominator) != (1, 1) \
            or control.work_match_rule != PRIMARY_WORK_RULE \
            or human.cohort_id != HUMAN_COHORT_ID \
            or human.comparator_cohort_id != PRIMARY_COHORT_ID \
            or human.synthetic_selection_rule \
            != MIXED_SYNTHETIC_TRAIN_DECISIONS \
            or (human.synthetic_fraction_numerator,
                human.synthetic_fraction_denominator) != (1, 1) \
            or human.human_selection_rule \
            != ALL_HUMAN_TRAIN_DECISIONS \
            or human.work_match_rule != MIXED_WORK_RULE:
        raise BeliefV2FreezeError("V2 cohort comparison/work binding drift")
    fractions = set()
    for scale in by_kind["synthetic-scale"]:
        if scale.comparator_cohort_id != PRIMARY_COHORT_ID \
                or scale.synthetic_selection_rule \
                != SCALE_SYNTHETIC_TRAIN_DECISIONS \
                or scale.human_selection_rule != NO_HUMAN_DECISIONS \
                or scale.work_match_rule != SCALE_WORK_RULE \
                or scale.synthetic_fraction_numerator \
                >= scale.synthetic_fraction_denominator \
                or (scale.synthetic_fraction_numerator,
                    scale.synthetic_fraction_denominator) in fractions:
            raise BeliefV2FreezeError("V2 scale cohort binding drift")
        fractions.add((scale.synthetic_fraction_numerator,
                       scale.synthetic_fraction_denominator))
    if canonical_json_bytes(freeze.to_dict()) != freeze.canonical_bytes() \
            or not _is_sha256(freeze.sha256()):
        raise BeliefV2FreezeError("V2 freeze canonical digest drift")


def execution_freeze_from_bytes(raw: bytes) -> V2ExecutionFreezeV1:
    if type(raw) is not bytes or not raw:
        raise BeliefV2FreezeError("V2 freeze bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefV2FreezeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2FreezeError("V2 freeze is not strict JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw \
            or type(payload.get("cohorts")) is not list \
            or type(payload.get("resource_caps")) is not dict \
            or type(payload.get("v1_route")) is not dict \
            or type(payload.get("human_inventory")) is not dict \
            or type(payload.get("capacity")) is not dict \
            or type(payload.get("seed_registry")) is not dict \
            or type(payload.get("source_bindings")) is not list \
            or type(payload.get("runtime")) is not dict:
        raise BeliefV2FreezeError("V2 freeze field/canonical drift")
    bindings = []
    for row in payload["source_bindings"]:
        if type(row) is not dict or set(row) != {
                "schema", "path", "byte_count", "sha256"}:
            raise BeliefV2FreezeError("V2 source binding field drift")
        bindings.append(V2SourceBindingV1(
            schema=row["schema"], path=row["path"],
            byte_count=row["byte_count"], sha256=row["sha256"]))
    runtime = payload["runtime"]
    if type(runtime) is not dict or set(runtime) != {
            "schema", "hostname", "operating_system", "machine",
            "cpu_count", "memory_bytes", "boot_identity", "python",
            "torch", "numpy", "native", "required_environment"} \
            or type(runtime["python"]) is not dict \
            or type(runtime["torch"]) is not dict \
            or type(runtime["numpy"]) is not dict \
            or type(runtime["native"]) is not dict \
            or type(runtime["required_environment"]) is not dict:
        raise BeliefV2FreezeError("V2 runtime profile field drift")
    python_row = runtime["python"]
    torch_row = runtime["torch"]
    numpy_row = runtime["numpy"]
    native_row = runtime["native"]
    distribution_keys = {
        "schema", "name", "version", "root", "file_count",
        "payload_sha256"}
    if set(python_row) != {"executable", "executable_sha256", "version"} \
            or set(torch_row) != {
                "distribution", "config_sha256", "num_threads",
                "deterministic_algorithms", "device"} \
            or type(torch_row["distribution"]) is not dict \
            or set(torch_row["distribution"]) != distribution_keys \
            or set(numpy_row) != distribution_keys \
            or set(native_row) != {"path", "sha256"}:
        raise BeliefV2FreezeError("V2 runtime nested field drift")

    def distribution(row: dict[str, Any]) -> V2InstalledDistributionV1:
        return V2InstalledDistributionV1(
            schema=row["schema"], name=row["name"],
            version=row["version"], root=row["root"],
            file_count=row["file_count"],
            payload_sha256=row["payload_sha256"])

    profile = V2RuntimeProfileV1(
        schema=runtime["schema"], hostname=runtime["hostname"],
        operating_system=runtime["operating_system"],
        machine=runtime["machine"], cpu_count=runtime["cpu_count"],
        memory_bytes=runtime["memory_bytes"],
        boot_identity=runtime["boot_identity"],
        python_executable=python_row["executable"],
        python_executable_sha256=python_row["executable_sha256"],
        python_version=python_row["version"],
        torch=distribution(torch_row["distribution"]),
        torch_config_sha256=torch_row["config_sha256"],
        numpy=distribution(numpy_row), native_path=native_row["path"],
        native_sha256=native_row["sha256"],
        required_environment=tuple(runtime["required_environment"].items()),
        torch_num_threads=torch_row["num_threads"],
        torch_deterministic_algorithms=torch_row[
            "deterministic_algorithms"], device=torch_row["device"])
    cohorts = []
    for row in payload["cohorts"]:
        if type(row) is not dict or set(row) != {
                "schema", "cohort_id", "kind", "member_seeds",
                "member_count", "synthetic_selection_rule",
                "synthetic_fraction", "human_selection_rule",
                "work_match_rule", "comparator_cohort_id"} \
                or type(row["member_seeds"]) is not list \
                or row["member_count"] != len(row["member_seeds"]) \
                or type(row["synthetic_fraction"]) is not dict \
                or set(row["synthetic_fraction"]) != {
                    "numerator", "denominator"}:
            raise BeliefV2FreezeError("V2 cohort row field drift")
        cohorts.append(V2CohortPlanV1(
            schema=row["schema"], cohort_id=row["cohort_id"],
            kind=row["kind"], member_seeds=tuple(row["member_seeds"]),
            synthetic_selection_rule=row["synthetic_selection_rule"],
            synthetic_fraction_numerator=(
                row["synthetic_fraction"]["numerator"]),
            synthetic_fraction_denominator=(
                row["synthetic_fraction"]["denominator"]),
            human_selection_rule=row["human_selection_rule"],
            work_match_rule=row["work_match_rule"],
            comparator_cohort_id=row["comparator_cohort_id"]))
    caps = payload["resource_caps"]
    if set(caps) != {
            "schema", "capture_core_hours", "capture_wall_seconds",
            "capture_bytes", "reference_core_hours",
            "reference_wall_seconds", "reference_bytes",
            "training_device_hours", "training_wall_seconds",
            "training_bytes", "training_host_memory_bytes",
            "training_device_memory_bytes"}:
        raise BeliefV2FreezeError("V2 resource cap field drift")
    route = payload["v1_route"]
    human = payload["human_inventory"]
    capacity = payload["capacity"]
    registry = payload["seed_registry"]
    device = payload.get("training_device_qualification")
    if type(device) is not dict or set(device) != {
            "candidate_device", "device_profile", "protocol_sha256",
            "cpu_fallback_on_performance_miss",
            "fallback_on_integrity_failure"} \
            or type(device["device_profile"]) is not dict \
            or set(device["device_profile"]) != {
                "schema", "requested_device", "device_type",
                "device_index", "hardware_name", "total_memory_bytes",
                "runtime_version", "compute_capability_major",
                "compute_capability_minor", "backend_built",
                "backend_available"} \
            or device["cpu_fallback_on_performance_miss"] is not True \
            or device["fallback_on_integrity_failure"] is not False:
        raise BeliefV2FreezeError(
            "V2 device qualification field drift")
    try:
        freeze = V2ExecutionFreezeV1(
            schema=payload["schema"], execution_git=payload["execution_git"],
            source_manifest_sha256=payload["source_manifest_sha256"],
            source_bindings=tuple(bindings), runtime=profile,
            source_review_commit=payload["source_review_commit"],
            v1_terminal_route=route["terminal_route"],
            v1_terminal_result_sha256=route["terminal_result_sha256"],
            v1_resource_receipt_sha256=route["resource_receipt_sha256"],
            v2_reentry_rationale_sha256=(
                route["v2_reentry_rationale_sha256"]),
            h0_inventory_sha256=human["inventory_sha256"],
            h0_source_manifest_sha256=human["source_manifest_sha256"],
            h0_source_digest_population_sha256=(
                human["source_digest_population_sha256"]),
            human_group_split_sha256=human["group_split_sha256"],
            human_group_count=human["group_count"],
            human_train_group_count=human["train_group_count"],
            human_calibration_group_count=human["calibration_group_count"],
            human_test_group_count=human["test_group_count"],
            human_complete_round_count=human["complete_round_count"],
            human_eligible_decision_count=human["eligible_decision_count"],
            human_train_eligible_decision_count=(
                human["train_eligible_decision_count"]),
            human_calibration_eligible_decision_count=(
                human["calibration_eligible_decision_count"]),
            human_test_eligible_decision_count=(
                human["test_eligible_decision_count"]),
            preflight_result_sha256=capacity["preflight_result_sha256"],
            preflight_runtime_sha256=capacity["preflight_runtime_sha256"],
            seed_registry_sha256=registry["registry_sha256"],
            seed_candidate_report_sha256=(
                registry["candidate_report_sha256"]),
            training_candidate_device=device["candidate_device"],
            training_device_profile=V2TrainingDeviceProfileV1(
                schema=device["device_profile"]["schema"],
                requested_device=device["device_profile"][
                    "requested_device"],
                device_type=device["device_profile"]["device_type"],
                device_index=device["device_profile"]["device_index"],
                hardware_name=device["device_profile"]["hardware_name"],
                total_memory_bytes=device["device_profile"][
                    "total_memory_bytes"],
                runtime_version=device["device_profile"][
                    "runtime_version"],
                compute_capability_major=device["device_profile"][
                    "compute_capability_major"],
                compute_capability_minor=device["device_profile"][
                    "compute_capability_minor"],
                backend_built=device["device_profile"]["backend_built"],
                backend_available=device["device_profile"][
                    "backend_available"]),
            device_qualification_protocol_sha256=(
                device["protocol_sha256"]),
            cohorts=tuple(cohorts),
            resource_caps=V2ResourceCapsV1(**caps),
            evidence_root=payload["evidence_root"])
    except (KeyError, TypeError) as exc:
        raise BeliefV2FreezeError("V2 freeze nested field drift") from exc
    validate_execution_freeze(freeze)
    if freeze.canonical_bytes() != raw:
        raise BeliefV2FreezeError("V2 freeze reconstruction drift")
    return freeze


def expected_execution_review_claim(
        freeze: V2ExecutionFreezeV1) -> dict[str, Any]:
    validate_execution_freeze(freeze)
    return {
        "schema": REVIEW_SCHEMA,
        "run_id": RUN_ID,
        "freeze_sha256": freeze.sha256(),
        "execution_git": freeze.execution_git,
        "protocol_sha256": protocol_sha256(),
        "schedule_sha256": schedule_sha256(),
        "source_manifest_sha256": freeze.source_manifest_sha256,
        "runtime_profile_sha256": _sha256(canonical_json_bytes(
            freeze.runtime.to_dict())),
        "seed_registry_sha256": freeze.seed_registry_sha256,
        "device_qualification_protocol_sha256": (
            freeze.device_qualification_protocol_sha256),
        "training_device_profile_sha256": (
            freeze.training_device_profile.sha256()),
        "training_candidate_device": freeze.training_candidate_device,
        "evidence_root": freeze.evidence_root,
        "bounded_capture_reference_training_and_one_test_open_authorized": True,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }


@dataclass(frozen=True)
class V2PipelineAdmissionV1:
    freeze_sha256: str
    execution_git: str
    source_manifest_sha256: str
    seed_registry_sha256: str
    review_commit: str
    canonical_remote_tip: str
    review_marker_sha256: str
    evidence_root: str
    schema: str = ADMISSION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": RUN_ID,
            "protocol_sha256": protocol_sha256(),
            "schedule_sha256": schedule_sha256(),
            "freeze_sha256": self.freeze_sha256,
            "execution_git": self.execution_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "seed_registry_sha256": self.seed_registry_sha256,
            "review_commit": self.review_commit,
            "canonical_remote_tip": self.canonical_remote_tip,
            "review_marker_sha256": self.review_marker_sha256,
            "evidence_root": self.evidence_root,
            "authority": {
                "capture_authorized": True,
                "reference_generation_authorized": True,
                "training_authorized": True,
                "one_test_split_open_authorized": True,
                "terminal_reconstruction_authorized": True,
                "retry_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False,
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ("git", *arguments), cwd=repo, check=True,
            capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2FreezeError("V2 review Git authentication failed") \
            from exc
    return result.stdout if binary else result.stdout.strip()


def _canonical_remote_tip(repo: Path) -> str:
    try:
        probe = subprocess.run(
            ("git", "ls-remote", "--exit-code", CANONICAL_REMOTE_URL,
             CANONICAL_REMOTE_REF), cwd=repo, check=True,
            capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2FreezeError("V2 canonical remote probe failed") \
            from exc
    rows = probe.stdout.splitlines()
    if len(rows) != 1:
        raise BeliefV2FreezeError("V2 canonical remote population drift")
    fields = rows[0].split()
    if len(fields) != 2 or fields[1] != CANONICAL_REMOTE_REF \
            or not _is_git_sha(fields[0]):
        raise BeliefV2FreezeError("V2 canonical remote identity drift")
    return fields[0]


def authenticate_execution_review(
        freeze: V2ExecutionFreezeV1, *, repo: Path,
        review_commit: str) -> tuple[bytes, str]:
    """Authenticate the exact marker against the real canonical remote tip."""
    validate_execution_freeze(freeze)
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(review_commit):
        raise BeliefV2FreezeError("V2 execution review input drift")
    remote_tip = _canonical_remote_tip(repo)
    local_tip = _git(repo, "rev-parse", "origin/main")
    if local_tip != remote_tip:
        raise BeliefV2FreezeError(
            "V2 local canonical ref differs from real remote")
    try:
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
            raise BeliefV2FreezeError(
                "V2 execution review is not on canonical remote main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        if len(parents) != 1:
            raise BeliefV2FreezeError("V2 execution review parent drift")
        parent = parents[0]
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (
                REVIEWER_NAME, REVIEWER_EMAIL,
                REVIEWER_NAME, REVIEWER_EMAIL):
            raise BeliefV2FreezeError("V2 execution review actor drift")
        message = str(_git(
            repo, "show", "-s", "--format=%B", review_commit))
        if REVIEWER_SESSION_TRAILER not in message:
            raise BeliefV2FreezeError("V2 execution review session drift")
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise BeliefV2FreezeError("V2 execution review file scope drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parent}:{REVIEW_LEDGER}", binary=True)
    except subprocess.CalledProcessError as exc:
        raise BeliefV2FreezeError("V2 execution review lookup failed") \
            from exc
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise BeliefV2FreezeError(
            "V2 execution review ledger is not append-only")
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_execution_review_claim(freeze))
    prefix = REVIEW_PREFIX.encode("ascii")
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [marker] or previous_matches:
        raise BeliefV2FreezeError(
            "V2 execution review marker introduction drift")
    return marker, remote_tip


def build_pipeline_admission(
        freeze: V2ExecutionFreezeV1, *, repo: Path,
        review_commit: str) -> tuple[V2PipelineAdmissionV1, bytes]:
    marker, remote_tip = authenticate_execution_review(
        freeze, repo=repo, review_commit=review_commit)
    admission = V2PipelineAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        review_commit=review_commit, canonical_remote_tip=remote_tip,
        review_marker_sha256=_sha256(marker),
        evidence_root=freeze.evidence_root)
    validate_pipeline_admission(freeze, admission, review_marker=marker)
    return admission, marker


def validate_pipeline_admission(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1, *,
        review_marker: bytes) -> None:
    validate_execution_freeze(freeze)
    expected_marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_execution_review_claim(freeze))
    if type(admission) is not V2PipelineAdmissionV1 \
            or admission.schema != ADMISSION_SCHEMA \
            or admission.freeze_sha256 != freeze.sha256() \
            or admission.execution_git != freeze.execution_git \
            or admission.source_manifest_sha256 \
            != freeze.source_manifest_sha256 \
            or admission.seed_registry_sha256 != freeze.seed_registry_sha256 \
            or not _is_git_sha(admission.review_commit) \
            or not _is_git_sha(admission.canonical_remote_tip) \
            or type(review_marker) is not bytes \
            or review_marker != expected_marker \
            or admission.review_marker_sha256 != _sha256(review_marker) \
            or admission.evidence_root != freeze.evidence_root:
        raise BeliefV2FreezeError("V2 pipeline admission identity drift")


def pipeline_admission_from_bytes(
        raw: bytes, *, freeze: V2ExecutionFreezeV1,
        review_marker: bytes) -> V2PipelineAdmissionV1:
    """Strictly reopen the durable admission consumed by every stage."""
    if type(raw) is not bytes or not raw:
        raise BeliefV2FreezeError("V2 admission bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefV2FreezeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2FreezeError("V2 admission is not strict JSON") from exc
    expected_keys = {
        "schema", "run_id", "protocol_sha256", "schedule_sha256",
        "freeze_sha256", "execution_git", "source_manifest_sha256",
        "seed_registry_sha256", "review_commit", "canonical_remote_tip",
        "review_marker_sha256", "evidence_root", "authority",
    }
    authority = payload.get("authority") if type(payload) is dict else None
    if type(payload) is not dict or set(payload) != expected_keys \
            or type(authority) is not dict \
            or set(authority) != {
                "capture_authorized", "reference_generation_authorized",
                "training_authorized", "one_test_split_open_authorized",
                "terminal_reconstruction_authorized", "retry_authorized",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "promotion_authorized",
                "deployment_authorized"}:
        raise BeliefV2FreezeError("V2 admission field drift")
    try:
        admission = V2PipelineAdmissionV1(
            schema=payload["schema"],
            freeze_sha256=payload["freeze_sha256"],
            execution_git=payload["execution_git"],
            source_manifest_sha256=payload["source_manifest_sha256"],
            seed_registry_sha256=payload["seed_registry_sha256"],
            review_commit=payload["review_commit"],
            canonical_remote_tip=payload["canonical_remote_tip"],
            review_marker_sha256=payload["review_marker_sha256"],
            evidence_root=payload["evidence_root"])
    except (KeyError, TypeError) as exc:
        raise BeliefV2FreezeError("V2 admission field drift") from exc
    validate_pipeline_admission(
        freeze, admission, review_marker=review_marker)
    if admission.canonical_bytes() != raw:
        raise BeliefV2FreezeError("V2 admission reconstruction drift")
    return admission


def reauthenticate_pipeline_admission(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1, *,
        repo: Path, review_marker: bytes) -> None:
    """The mandatory gate called by every future stage entry point."""
    validate_pipeline_admission(
        freeze, admission, review_marker=review_marker)
    authentic_marker, remote_tip = authenticate_execution_review(
        freeze, repo=repo, review_commit=admission.review_commit)
    if authentic_marker != review_marker \
            or remote_tip != admission.canonical_remote_tip:
        raise BeliefV2FreezeError("V2 pipeline admission remote drift")


def pipeline_consumption_tombstone_bytes(
        admission: V2PipelineAdmissionV1) -> bytes:
    if type(admission) is not V2PipelineAdmissionV1:
        raise BeliefV2FreezeError("V2 tombstone admission drift")
    return canonical_json_bytes({
        "schema": CONSUMPTION_SCHEMA,
        "run_id": RUN_ID,
        "admission_sha256": admission.sha256(),
        "freeze_sha256": admission.freeze_sha256,
        "review_commit": admission.review_commit,
        "canonical_remote_tip": admission.canonical_remote_tip,
        "evidence_root": admission.evidence_root,
        "initialization_consumed": True,
        "retry_authorized": False,
    })


def validate_pipeline_consumption_tombstone(
        raw: bytes, *, admission: V2PipelineAdmissionV1) -> None:
    """Require the undeletable sibling receipt for this exact admission."""
    if type(admission) is not V2PipelineAdmissionV1:
        raise BeliefV2FreezeError("V2 tombstone admission drift")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefV2FreezeError:
        raise
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2FreezeError("V2 tombstone is not strict JSON") from exc
    if type(payload) is not dict \
            or canonical_json_bytes(payload) != raw \
            or raw != pipeline_consumption_tombstone_bytes(admission):
        raise BeliefV2FreezeError("V2 consumption tombstone drift")
