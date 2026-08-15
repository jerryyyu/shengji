"""Exact execution-freeze schema for the BELIEF-V1 V2 offline pipeline.

This module closes the shape of the packet that will be populated after the
V1 terminal, H0 inventory, and multi-rank capacity receipts exist.  It has no
filesystem writer, corpus reader, worker launcher, training loop, test opener,
gameplay path, or deployment authority.
"""

from __future__ import annotations

import hashlib
import json
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


FREEZE_SCHEMA = "belief-v1-v2-offline-execution-freeze-v1"
COHORT_SCHEMA = "belief-v1-v2-training-cohort-plan-v1"
CAP_SCHEMA = "belief-v1-v2-resource-caps-v1"
REVIEW_SCHEMA = "belief-v1-v2-offline-execution-review-v1"
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
    optimizer_decisions_per_epoch: int
    synthetic_decisions_per_epoch: int
    human_decisions_per_epoch: int
    synthetic_decision_manifest_sha256: str
    human_decision_manifest_sha256: str | None
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
            "optimizer_decisions_per_epoch": (
                self.optimizer_decisions_per_epoch),
            "synthetic_decisions_per_epoch": (
                self.synthetic_decisions_per_epoch),
            "human_decisions_per_epoch": self.human_decisions_per_epoch,
            "synthetic_decision_manifest_sha256": (
                self.synthetic_decision_manifest_sha256),
            "human_decision_manifest_sha256": (
                self.human_decision_manifest_sha256),
            "comparator_cohort_id": self.comparator_cohort_id,
        }


def _validate_cohort(row: V2CohortPlanV1) -> None:
    if type(row) is not V2CohortPlanV1 or row.schema != COHORT_SCHEMA \
            or type(row.cohort_id) is not str or not row.cohort_id \
            or row.kind not in COHORT_KINDS \
            or row.member_seeds != COHORT_SEEDS \
            or any(type(value) is not int or value < 0 for value in (
                row.optimizer_decisions_per_epoch,
                row.synthetic_decisions_per_epoch,
                row.human_decisions_per_epoch)) \
            or row.optimizer_decisions_per_epoch <= 0 \
            or row.optimizer_decisions_per_epoch \
            != row.synthetic_decisions_per_epoch \
            + row.human_decisions_per_epoch \
            or not _is_sha256(row.synthetic_decision_manifest_sha256) \
            or not (row.human_decision_manifest_sha256 is None
                    or _is_sha256(row.human_decision_manifest_sha256)) \
            or not (row.comparator_cohort_id is None
                    or (type(row.comparator_cohort_id) is str
                        and bool(row.comparator_cohort_id))):
        raise BeliefV2FreezeError("V2 cohort plan identity drift")
    if row.kind in ("synthetic-primary", "synthetic-scale",
                    "hard-geometry-label-permutation"):
        if row.human_decisions_per_epoch != 0 \
                or row.human_decision_manifest_sha256 is not None:
            raise BeliefV2FreezeError("non-human V2 cohort contains human work")
    elif row.kind == "human-mixture":
        if row.human_decisions_per_epoch <= 0 \
                or row.synthetic_decisions_per_epoch <= 0 \
                or row.human_decision_manifest_sha256 is None \
                or row.human_decisions_per_epoch \
                * MAX_HUMAN_FRACTION_DENOMINATOR \
                > row.optimizer_decisions_per_epoch \
                * MAX_HUMAN_FRACTION_NUMERATOR:
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
        }


def _validate_caps(caps: V2ResourceCapsV1) -> None:
    if type(caps) is not V2ResourceCapsV1 or caps.schema != CAP_SCHEMA \
            or any(type(value) is not int or value <= 0 for value in (
                caps.capture_core_hours, caps.capture_wall_seconds,
                caps.capture_bytes, caps.reference_core_hours,
                caps.reference_wall_seconds, caps.reference_bytes,
                caps.training_device_hours, caps.training_wall_seconds,
                caps.training_bytes)):
        raise BeliefV2FreezeError("V2 resource cap identity drift")


@dataclass(frozen=True)
class V2ExecutionFreezeV1:
    execution_git: str
    source_manifest_sha256: str
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
    preflight_result_sha256: str
    preflight_runtime_sha256: str
    seed_registry_sha256: str
    seed_candidate_report_sha256: str
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
                freeze.seed_candidate_report_sha256)) \
            or freeze.v1_terminal_route not in V1_ROUTES \
            or type(freeze.cohorts) is not tuple or not freeze.cohorts \
            or type(freeze.evidence_root) is not str \
            or not Path(freeze.evidence_root).is_absolute() \
            or any(type(value) is not int or value < 0 for value in (
                freeze.human_group_count, freeze.human_train_group_count,
                freeze.human_calibration_group_count,
                freeze.human_test_group_count,
                freeze.human_complete_round_count,
                freeze.human_eligible_decision_count)) \
            or min(freeze.human_group_count,
                   freeze.human_complete_round_count,
                   freeze.human_eligible_decision_count) <= 0 \
            or freeze.human_group_count != (
                freeze.human_train_group_count
                + freeze.human_calibration_group_count
                + freeze.human_test_group_count) \
            or min(freeze.human_train_group_count,
                   freeze.human_calibration_group_count,
                   freeze.human_test_group_count) <= 0:
        raise BeliefV2FreezeError("V2 execution freeze identity drift")
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
            or control.cohort_id != CONTROL_COHORT_ID \
            or control.comparator_cohort_id != PRIMARY_COHORT_ID \
            or control.optimizer_decisions_per_epoch \
            != primary.optimizer_decisions_per_epoch \
            or control.synthetic_decision_manifest_sha256 \
            != primary.synthetic_decision_manifest_sha256 \
            or human.cohort_id != HUMAN_COHORT_ID \
            or human.comparator_cohort_id != PRIMARY_COHORT_ID \
            or human.optimizer_decisions_per_epoch \
            != primary.optimizer_decisions_per_epoch \
            or human.synthetic_decision_manifest_sha256 \
            == primary.synthetic_decision_manifest_sha256:
        raise BeliefV2FreezeError("V2 cohort comparison/work binding drift")
    for scale in by_kind["synthetic-scale"]:
        if scale.comparator_cohort_id != PRIMARY_COHORT_ID \
                or scale.optimizer_decisions_per_epoch \
                >= primary.optimizer_decisions_per_epoch \
                or scale.synthetic_decision_manifest_sha256 \
                == primary.synthetic_decision_manifest_sha256:
            raise BeliefV2FreezeError("V2 scale cohort binding drift")
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
            or type(payload.get("seed_registry")) is not dict:
        raise BeliefV2FreezeError("V2 freeze field/canonical drift")
    cohorts = []
    for row in payload["cohorts"]:
        if type(row) is not dict or set(row) != {
                "schema", "cohort_id", "kind", "member_seeds",
                "member_count", "optimizer_decisions_per_epoch",
                "synthetic_decisions_per_epoch", "human_decisions_per_epoch",
                "synthetic_decision_manifest_sha256",
                "human_decision_manifest_sha256", "comparator_cohort_id"} \
                or type(row["member_seeds"]) is not list \
                or row["member_count"] != len(row["member_seeds"]):
            raise BeliefV2FreezeError("V2 cohort row field drift")
        cohorts.append(V2CohortPlanV1(
            schema=row["schema"], cohort_id=row["cohort_id"],
            kind=row["kind"], member_seeds=tuple(row["member_seeds"]),
            optimizer_decisions_per_epoch=(
                row["optimizer_decisions_per_epoch"]),
            synthetic_decisions_per_epoch=(
                row["synthetic_decisions_per_epoch"]),
            human_decisions_per_epoch=row["human_decisions_per_epoch"],
            synthetic_decision_manifest_sha256=(
                row["synthetic_decision_manifest_sha256"]),
            human_decision_manifest_sha256=(
                row["human_decision_manifest_sha256"]),
            comparator_cohort_id=row["comparator_cohort_id"]))
    caps = payload["resource_caps"]
    if set(caps) != {
            "schema", "capture_core_hours", "capture_wall_seconds",
            "capture_bytes", "reference_core_hours",
            "reference_wall_seconds", "reference_bytes",
            "training_device_hours", "training_wall_seconds",
            "training_bytes"}:
        raise BeliefV2FreezeError("V2 resource cap field drift")
    route = payload["v1_route"]
    human = payload["human_inventory"]
    capacity = payload["capacity"]
    registry = payload["seed_registry"]
    try:
        freeze = V2ExecutionFreezeV1(
            schema=payload["schema"], execution_git=payload["execution_git"],
            source_manifest_sha256=payload["source_manifest_sha256"],
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
            preflight_result_sha256=capacity["preflight_result_sha256"],
            preflight_runtime_sha256=capacity["preflight_runtime_sha256"],
            seed_registry_sha256=registry["registry_sha256"],
            seed_candidate_report_sha256=(
                registry["candidate_report_sha256"]),
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
        "seed_registry_sha256": freeze.seed_registry_sha256,
        "evidence_root": freeze.evidence_root,
        "bounded_capture_reference_training_and_one_test_open_authorized": True,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }

