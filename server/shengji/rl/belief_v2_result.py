"""Closed terminal routing for the BELIEF-V1 V2 offline pipeline.

This module consumes already-derived, independently reopenable statistics and
measured resource/population counters.  It contains no artifact reader, model,
sampler, gameplay path, subprocess, clock, or execution authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_device_qualification import (
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
    validate_qualification_plan,
    validate_qualification_result,
)
from .belief_v2_freeze import (
    HUMAN_COHORT_ID,
    PRIMARY_COHORT_ID,
    V2ExecutionFreezeV1,
    validate_execution_freeze,
)
from .belief_v2_protocol import V2_RANKS, V2_ROUND_COUNT, V2_SPLIT_COUNTS
from .belief_v2_statistics import (
    V2HumanSelectionResultV1,
    V2HumanTransferResultV1,
    V2LabelControlTestResultV1,
    V2PrimaryTestResultV1,
    V2ScaleCurveResultV1,
)


INTEGRITY_SCHEMA = "belief-v1-v2-integrity-resource-receipt-v1"
TERMINAL_SCHEMA = "belief-v1-v2-offline-terminal-result-v1"
REFUSE_INTEGRITY = "REFUSE_INCOMPLETE_OR_INTEGRITY"
REFUSE_CONTROL = "REFUSE_NEGATIVE_CONTROL"
PASS_B3 = "PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW"
SELECT_REENTRY = "SELECT_NONE_WITH_PREREGISTERED_REENTRY"
SELECT_NONE = "SELECT_NONE_NO_CALIBRATION_LIFT"
TERMINAL_ROUTES = (
    REFUSE_INTEGRITY,
    REFUSE_CONTROL,
    PASS_B3,
    SELECT_REENTRY,
    SELECT_NONE,
)
REENTRY_SIGNALS = ("data-scale", "rank-stratified")
NS_PER_SECOND = 1_000_000_000
NS_PER_HOUR = 3_600 * NS_PER_SECOND


class BeliefV2ResultError(ValueError):
    """A terminal input, measured receipt, or derived route drifted."""


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class V2IntegrityResourceReceiptV1:
    freeze_sha256: str
    device_qualification_plan_sha256: str
    device_qualification_result_sha256: str
    training_device: str
    capture_expected_round_count: int
    capture_reopened_round_count: int
    reference_expected_round_count: int
    reference_reopened_round_count: int
    training_expected_cohort_count: int
    training_reopened_cohort_count: int
    training_expected_checkpoint_count: int
    training_reopened_checkpoint_count: int
    synthetic_test_expected_round_count: int
    synthetic_test_reopened_round_count: int
    human_test_expected_decision_count: int
    human_test_reopened_decision_count: int
    capture_cpu_nanoseconds: int
    capture_wall_nanoseconds: int
    capture_artifact_bytes: int
    reference_cpu_nanoseconds: int
    reference_wall_nanoseconds: int
    reference_artifact_bytes: int
    training_device_nanoseconds: int
    training_wall_nanoseconds: int
    training_artifact_bytes: int
    training_peak_host_memory_bytes: int
    training_peak_device_memory_bytes: int
    capture_failure_count: int
    reference_failure_count: int
    training_failure_count: int
    mechanics_failure_count: int
    resource_cap_violation_count: int
    retry_count: int
    drop_count: int
    test_split_decision_open_count: int
    schema: str = INTEGRITY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "freeze_sha256": self.freeze_sha256,
            "device_qualification": {
                "plan_sha256": self.device_qualification_plan_sha256,
                "result_sha256": self.device_qualification_result_sha256,
                "training_device": self.training_device,
            },
            "populations": {
                "capture": {
                    "expected_round_count": self.capture_expected_round_count,
                    "reopened_round_count": self.capture_reopened_round_count,
                },
                "reference": {
                    "expected_round_count": self.reference_expected_round_count,
                    "reopened_round_count": self.reference_reopened_round_count,
                },
                "training": {
                    "expected_cohort_count": self.training_expected_cohort_count,
                    "reopened_cohort_count": self.training_reopened_cohort_count,
                    "expected_checkpoint_count": (
                        self.training_expected_checkpoint_count),
                    "reopened_checkpoint_count": (
                        self.training_reopened_checkpoint_count),
                },
                "synthetic_test": {
                    "expected_round_count": (
                        self.synthetic_test_expected_round_count),
                    "reopened_round_count": (
                        self.synthetic_test_reopened_round_count),
                },
                "human_test": {
                    "expected_decision_count": (
                        self.human_test_expected_decision_count),
                    "reopened_decision_count": (
                        self.human_test_reopened_decision_count),
                },
            },
            "resources": {
                "capture": {
                    "cpu_nanoseconds": self.capture_cpu_nanoseconds,
                    "wall_nanoseconds": self.capture_wall_nanoseconds,
                    "artifact_bytes": self.capture_artifact_bytes,
                },
                "reference": {
                    "cpu_nanoseconds": self.reference_cpu_nanoseconds,
                    "wall_nanoseconds": self.reference_wall_nanoseconds,
                    "artifact_bytes": self.reference_artifact_bytes,
                },
                "training": {
                    "device_nanoseconds": self.training_device_nanoseconds,
                    "wall_nanoseconds": self.training_wall_nanoseconds,
                    "artifact_bytes": self.training_artifact_bytes,
                    "peak_host_memory_bytes": (
                        self.training_peak_host_memory_bytes),
                    "peak_device_memory_bytes": (
                        self.training_peak_device_memory_bytes),
                },
            },
            "measured_failures": {
                "capture": self.capture_failure_count,
                "reference": self.reference_failure_count,
                "training": self.training_failure_count,
                "mechanics": self.mechanics_failure_count,
                "resource_cap": self.resource_cap_violation_count,
                "retry": self.retry_count,
                "drop": self.drop_count,
                "test_split_decision_open_count": (
                    self.test_split_decision_open_count),
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _validate_receipt_identity(
        freeze: V2ExecutionFreezeV1,
        plan: V2DeviceQualificationPlanV1,
        qualification: V2DeviceQualificationResultV1,
        receipt: V2IntegrityResourceReceiptV1) -> None:
    if type(receipt) is not V2IntegrityResourceReceiptV1:
        raise BeliefV2ResultError("V2 terminal integrity receipt drift")
    try:
        validate_execution_freeze(freeze)
        validate_qualification_plan(plan)
        validate_qualification_result(plan, qualification)
    except ValueError as exc:
        raise BeliefV2ResultError("V2 terminal source identity drift") from exc
    result_sha = _sha256(qualification.canonical_bytes(plan))
    integer_values = tuple(
        value for name, value in receipt.__dict__.items()
        if name not in {
            "schema", "freeze_sha256",
            "device_qualification_plan_sha256",
            "device_qualification_result_sha256", "training_device"})
    if receipt.schema != INTEGRITY_SCHEMA \
            or receipt.freeze_sha256 != freeze.sha256() \
            or receipt.device_qualification_plan_sha256 != plan.sha256() \
            or receipt.device_qualification_result_sha256 != result_sha \
            or receipt.training_device != qualification.selected_device \
            or plan.execution_git != freeze.execution_git \
            or plan.candidate_device != freeze.training_candidate_device \
            or plan.host_memory_cap_bytes \
            != freeze.resource_caps.training_host_memory_bytes \
            or plan.device_memory_cap_bytes \
            != freeze.resource_caps.training_device_memory_bytes \
            or any(type(value) is not int or value < 0
                   for value in integer_values):
        raise BeliefV2ResultError("V2 terminal integrity receipt drift")


def integrity_failure_reasons(
        freeze: V2ExecutionFreezeV1,
        plan: V2DeviceQualificationPlanV1,
        qualification: V2DeviceQualificationResultV1,
        receipt: V2IntegrityResourceReceiptV1) -> tuple[str, ...]:
    """Return measured failures; identity/derivation drift raises instead."""
    _validate_receipt_identity(freeze, plan, qualification, receipt)
    reasons: list[str] = []
    expected_populations = (
        (receipt.capture_expected_round_count, V2_ROUND_COUNT),
        (receipt.reference_expected_round_count, 2 * V2_ROUND_COUNT),
        (receipt.training_expected_cohort_count, len(freeze.cohorts)),
        (receipt.training_expected_checkpoint_count,
         len(freeze.cohorts) * len(COHORT_SEEDS)),
        (receipt.synthetic_test_expected_round_count,
         dict(V2_SPLIT_COUNTS)["test"]),
        (receipt.human_test_expected_decision_count,
         freeze.human_test_eligible_decision_count),
    )
    if any(measured != expected for measured, expected
           in expected_populations):
        reasons.append("expected-population-drift")
    reopened_populations = (
        (receipt.capture_reopened_round_count,
         receipt.capture_expected_round_count),
        (receipt.reference_reopened_round_count,
         receipt.reference_expected_round_count),
        (receipt.training_reopened_cohort_count,
         receipt.training_expected_cohort_count),
        (receipt.training_reopened_checkpoint_count,
         receipt.training_expected_checkpoint_count),
        (receipt.synthetic_test_reopened_round_count,
         receipt.synthetic_test_expected_round_count),
        (receipt.human_test_reopened_decision_count,
         receipt.human_test_expected_decision_count),
    )
    if any(reopened != expected for reopened, expected
           in reopened_populations):
        reasons.append("reopened-population-incomplete")
    caps = freeze.resource_caps
    if receipt.capture_cpu_nanoseconds > caps.capture_core_hours * NS_PER_HOUR \
            or receipt.capture_wall_nanoseconds \
            > caps.capture_wall_seconds * NS_PER_SECOND \
            or receipt.capture_artifact_bytes > caps.capture_bytes \
            or receipt.reference_cpu_nanoseconds \
            > caps.reference_core_hours * NS_PER_HOUR \
            or receipt.reference_wall_nanoseconds \
            > caps.reference_wall_seconds * NS_PER_SECOND \
            or receipt.reference_artifact_bytes > caps.reference_bytes \
            or receipt.training_device_nanoseconds \
            > caps.training_device_hours * NS_PER_HOUR \
            or receipt.training_wall_nanoseconds \
            > caps.training_wall_seconds * NS_PER_SECOND \
            or receipt.training_artifact_bytes > caps.training_bytes \
            or receipt.training_peak_host_memory_bytes \
            > caps.training_host_memory_bytes \
            or receipt.training_peak_device_memory_bytes \
            > caps.training_device_memory_bytes:
        reasons.append("recomputed-resource-cap-exceeded")
    if min(
            receipt.capture_cpu_nanoseconds,
            receipt.capture_wall_nanoseconds,
            receipt.capture_artifact_bytes,
            receipt.reference_cpu_nanoseconds,
            receipt.reference_wall_nanoseconds,
            receipt.reference_artifact_bytes,
            receipt.training_device_nanoseconds,
            receipt.training_wall_nanoseconds,
            receipt.training_artifact_bytes) <= 0:
        reasons.append("resource-measurement-empty")
    if any(value != 0 for value in (
            receipt.capture_failure_count,
            receipt.reference_failure_count,
            receipt.training_failure_count,
            receipt.mechanics_failure_count,
            receipt.resource_cap_violation_count)):
        reasons.append("measured-stage-or-mechanics-failure")
    if receipt.retry_count != 0 or receipt.drop_count != 0:
        reasons.append("retry-or-drop-observed")
    if receipt.test_split_decision_open_count != 1:
        reasons.append("test-split-decision-open-count-drift")
    return tuple(reasons)


@dataclass(frozen=True)
class V2TerminalResultV1:
    freeze_sha256: str
    integrity_receipt_sha256: str
    device_qualification_result_sha256: str
    human_selection_sha256: str
    scale_curve_sha256: str
    primary_test_sha256: str
    label_control_test_sha256: str
    human_transfer_sha256: str
    selected_cohort_id: str
    terminal_route: str
    integrity_failure_reasons: tuple[str, ...]
    reentry_signals: tuple[str, ...]
    schema: str = TERMINAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "freeze_sha256": self.freeze_sha256,
            "integrity_receipt_sha256": self.integrity_receipt_sha256,
            "device_qualification_result_sha256": (
                self.device_qualification_result_sha256),
            "statistics": {
                "human_selection_sha256": self.human_selection_sha256,
                "scale_curve_sha256": self.scale_curve_sha256,
                "primary_test_sha256": self.primary_test_sha256,
                "label_control_test_sha256": (
                    self.label_control_test_sha256),
                "human_transfer_sha256": self.human_transfer_sha256,
            },
            "selected_cohort_id": self.selected_cohort_id,
            "terminal_route": self.terminal_route,
            "integrity_failure_reasons": list(
                self.integrity_failure_reasons),
            "reentry_signals": list(self.reentry_signals),
            "claim_scope": "offline-belief-calibration-only",
            "sampler_implementation_authorized": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _terminal_inputs(
        freeze: V2ExecutionFreezeV1,
        plan: V2DeviceQualificationPlanV1,
        qualification: V2DeviceQualificationResultV1,
        receipt: V2IntegrityResourceReceiptV1,
        human_selection: V2HumanSelectionResultV1,
        scale_curve: V2ScaleCurveResultV1,
        primary: V2PrimaryTestResultV1,
        control: V2LabelControlTestResultV1,
        human_transfer: V2HumanTransferResultV1) \
        -> tuple[str, tuple[str, ...], tuple[str, ...], dict[str, str]]:
    exact_types = (
        (human_selection, V2HumanSelectionResultV1),
        (scale_curve, V2ScaleCurveResultV1),
        (primary, V2PrimaryTestResultV1),
        (control, V2LabelControlTestResultV1),
        (human_transfer, V2HumanTransferResultV1),
    )
    if any(type(value) is not expected for value, expected in exact_types):
        raise BeliefV2ResultError("V2 terminal statistic type drift")
    selected = HUMAN_COHORT_ID if human_selection.retained \
        else PRIMARY_COHORT_ID
    expected_rank_keys = tuple(V2_RANKS)
    if type(human_selection.retained) is not bool \
            or type(human_selection.refusal_reasons) is not tuple \
            or human_selection.retained \
            is not (not human_selection.refusal_reasons) \
            or tuple(rank for rank, _ in human_selection.rank_round_counts) \
            != expected_rank_keys \
            or tuple(rank for rank, _
                     in human_selection.rank_mean_regression_ppb) \
            != expected_rank_keys \
            or tuple(rank for rank, _
                     in human_selection.rank_familywise_upper_regression_ppb) \
            != expected_rank_keys \
            or type(primary.passed) is not bool \
            or type(primary.refusal_reasons) is not tuple \
            or primary.passed is not (not primary.refusal_reasons) \
            or tuple(rank for rank, _ in primary.rank_round_counts) \
            != expected_rank_keys \
            or tuple(rank for rank, _ in primary.rank_mean_regression_ppb) \
            != expected_rank_keys \
            or tuple(rank for rank, _
                     in primary.rank_familywise_upper_regression_ppb) \
            != expected_rank_keys \
            or type(control.passed) is not bool \
            or type(control.unexpectedly_positive_lower_bound) is not bool \
            or type(scale_curve.any_positive_data_scaling_signal) is not bool \
            or type(scale_curve.rows) is not tuple \
            or not scale_curve.rows \
            or any(type(row.positive_lower_bound) is not bool
                   or row.positive_lower_bound
                   is not (row.bootstrap_lower_improvement_ppb > 0)
                   for row in scale_curve.rows) \
            or tuple(row.cohort_id for row in human_transfer.cohorts) \
            != (PRIMARY_COHORT_ID, HUMAN_COHORT_ID) \
            or primary.selected_cohort_id != selected \
            or human_transfer.selected_cohort_id != selected \
            or primary.round_count != dict(V2_SPLIT_COUNTS)["test"] \
            or control.round_count != dict(V2_SPLIT_COUNTS)["test"] \
            or human_transfer.decision_count \
            != freeze.human_test_eligible_decision_count \
            or primary.positive_member_count \
            != sum(value > 0 for value
                   in primary.member_mean_improvement_ppb) \
            or len(primary.member_mean_improvement_ppb) != len(COHORT_SEEDS) \
            or control.passed is control.unexpectedly_positive_lower_bound \
            or scale_curve.any_positive_data_scaling_signal \
            is not any(row.positive_lower_bound for row in scale_curve.rows):
        raise BeliefV2ResultError("V2 terminal statistic coherence drift")
    integrity = integrity_failure_reasons(
        freeze, plan, qualification, receipt)
    candidate_signals = []
    if scale_curve.any_positive_data_scaling_signal:
        candidate_signals.append("data-scale")
    if any(upper < 0 for _, upper
           in primary.rank_familywise_upper_regression_ppb):
        candidate_signals.append("rank-stratified")
    if integrity:
        route = REFUSE_INTEGRITY
    elif not control.passed:
        route = REFUSE_CONTROL
    elif primary.passed:
        route = PASS_B3
    elif candidate_signals:
        route = SELECT_REENTRY
    else:
        route = SELECT_NONE
    signals = tuple(candidate_signals) if route == SELECT_REENTRY else ()
    digests = {
        "freeze": freeze.sha256(),
        "receipt": _sha256(receipt.canonical_bytes()),
        "qualification": _sha256(qualification.canonical_bytes(plan)),
        "human_selection": _sha256(human_selection.canonical_bytes()),
        "scale_curve": _sha256(scale_curve.canonical_bytes()),
        "primary": _sha256(primary.canonical_bytes()),
        "control": _sha256(control.canonical_bytes()),
        "human_transfer": _sha256(human_transfer.canonical_bytes()),
    }
    return route, integrity, signals, digests


def derive_terminal_result(
        freeze: V2ExecutionFreezeV1,
        plan: V2DeviceQualificationPlanV1,
        qualification: V2DeviceQualificationResultV1,
        receipt: V2IntegrityResourceReceiptV1,
        human_selection: V2HumanSelectionResultV1,
        scale_curve: V2ScaleCurveResultV1,
        primary: V2PrimaryTestResultV1,
        control: V2LabelControlTestResultV1,
        human_transfer: V2HumanTransferResultV1) -> V2TerminalResultV1:
    route, integrity, signals, digests = _terminal_inputs(
        freeze, plan, qualification, receipt, human_selection, scale_curve,
        primary, control, human_transfer)
    result = V2TerminalResultV1(
        freeze_sha256=digests["freeze"],
        integrity_receipt_sha256=digests["receipt"],
        device_qualification_result_sha256=digests["qualification"],
        human_selection_sha256=digests["human_selection"],
        scale_curve_sha256=digests["scale_curve"],
        primary_test_sha256=digests["primary"],
        label_control_test_sha256=digests["control"],
        human_transfer_sha256=digests["human_transfer"],
        selected_cohort_id=primary.selected_cohort_id,
        terminal_route=route,
        integrity_failure_reasons=integrity,
        reentry_signals=signals)
    validate_terminal_result(
        freeze, plan, qualification, receipt, human_selection, scale_curve,
        primary, control, human_transfer, result)
    return result


def validate_terminal_result(
        freeze: V2ExecutionFreezeV1,
        plan: V2DeviceQualificationPlanV1,
        qualification: V2DeviceQualificationResultV1,
        receipt: V2IntegrityResourceReceiptV1,
        human_selection: V2HumanSelectionResultV1,
        scale_curve: V2ScaleCurveResultV1,
        primary: V2PrimaryTestResultV1,
        control: V2LabelControlTestResultV1,
        human_transfer: V2HumanTransferResultV1,
        result: V2TerminalResultV1) -> None:
    route, integrity, signals, digests = _terminal_inputs(
        freeze, plan, qualification, receipt, human_selection, scale_curve,
        primary, control, human_transfer)
    expected = V2TerminalResultV1(
        freeze_sha256=digests["freeze"],
        integrity_receipt_sha256=digests["receipt"],
        device_qualification_result_sha256=digests["qualification"],
        human_selection_sha256=digests["human_selection"],
        scale_curve_sha256=digests["scale_curve"],
        primary_test_sha256=digests["primary"],
        label_control_test_sha256=digests["control"],
        human_transfer_sha256=digests["human_transfer"],
        selected_cohort_id=primary.selected_cohort_id,
        terminal_route=route,
        integrity_failure_reasons=integrity,
        reentry_signals=signals)
    if type(result) is not V2TerminalResultV1 \
            or result.schema != TERMINAL_SCHEMA \
            or result.terminal_route not in TERMINAL_ROUTES \
            or any(signal not in REENTRY_SIGNALS
                   for signal in result.reentry_signals) \
            or result != expected:
        raise BeliefV2ResultError("V2 terminal result derivation drift")
