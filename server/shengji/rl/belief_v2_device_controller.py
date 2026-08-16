"""Durable one-shot device qualification stage for BELIEF-V1 V2."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import _stage_gate
from .belief_v2_deadline import (
    BeliefV2DeadlineError,
    publish_deadline_refusal,
    stage_deadline,
)
from .belief_v2_device_qualification import (
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
    build_qualification_plan_from_primary,
    qualification_protocol_sha256,
    reopen_qualification_plan,
    reopen_qualification_result,
)
from .belief_v2_device_runner import (
    run_device_qualification_in_memory,
    run_device_qualification_streaming,
)
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_schedule import V2CohortRealizationV1
from .belief_v2_training import V2TrainingExampleV1


DEVICE_STAGE_SCHEMA = "belief-v1-v2-device-qualification-stage-result-v1"


class BeliefV2DeviceControllerError(ValueError):
    """A qualification slot, freeze binding, or raw artifact drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _expected_plan(
        freeze: V2ExecutionFreezeV1,
        primary: V2CohortRealizationV1) -> V2DeviceQualificationPlanV1:
    frozen = [row for row in freeze.cohorts
              if row.cohort_id == "synthetic-primary"]
    if len(frozen) != 1 \
            or primary.cohort_id != "synthetic-primary" \
            or primary.kind != "synthetic-primary" \
            or primary.cohort_plan_sha256 \
            != _sha256(canonical_json_bytes(frozen[0].to_dict())) \
            or primary.comparator_cohort_id is not None:
        raise BeliefV2DeviceControllerError(
            "V2 device stage primary/freeze binding drift")
    try:
        plan = build_qualification_plan_from_primary(
            execution_git=freeze.execution_git,
            candidate_device=freeze.training_candidate_device,
            primary=primary,
            host_memory_cap_bytes=(
                freeze.resource_caps.training_host_memory_bytes),
            device_memory_cap_bytes=(
                freeze.resource_caps.training_device_memory_bytes))
    except ValueError as exc:
        raise BeliefV2DeviceControllerError(
            "V2 device stage primary plan refused") from exc
    if freeze.device_qualification_protocol_sha256 \
            != qualification_protocol_sha256(
                freeze.training_candidate_device):
        raise BeliefV2DeviceControllerError(
            "V2 device stage protocol/freeze drift")
    return plan


def _manifest(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        plan: V2DeviceQualificationPlanV1,
        result: V2DeviceQualificationResultV1) -> dict[str, Any]:
    plan_raw = plan.canonical_bytes()
    result_raw = result.canonical_bytes(plan)
    return {
        "schema": DEVICE_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "primary_realization_sha256": primary.sha256(),
        "qualification_protocol_sha256": (
            freeze.device_qualification_protocol_sha256),
        "plan_filename": "plan.json",
        "plan_byte_count": len(plan_raw),
        "plan_sha256": _sha256(plan_raw),
        "result_filename": "result.json",
        "result_byte_count": len(result_raw),
        "result_sha256": _sha256(result_raw),
        "selected_device": result.selected_device,
        "accelerator_retained": result.accelerator_retained,
        "arm_count": len(result.arms),
        "measured_arm_count": sum(not arm.warmup for arm in result.arms),
        "max_peak_host_memory_bytes": max(
            arm.peak_host_memory_bytes for arm in result.arms),
        "max_peak_device_memory_bytes": max(
            arm.peak_device_memory_bytes for arm in result.arms),
        "retry_count": 0,
        "fallback_arm_count": sum(arm.fallback_used for arm in result.arms),
        "training_authorized_by_this_artifact": False,
        "test_open_authorized_by_this_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_device_qualification(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes, primary: V2CohortRealizationV1,
        primary_examples: tuple[V2TrainingExampleV1, ...] | None,
        streaming_index=None, load_round=None) \
        -> dict[str, Any]:
    """Execute and atomically publish the exact frozen qualification."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    expected = _expected_plan(freeze, primary)
    parent = root / "device-qualification"
    if parent.is_symlink():
        raise BeliefV2DeviceControllerError(
            "V2 device qualification parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / "result"
    partial = parent / "result.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2DeviceControllerError(
            "V2 device qualification slot is occupied")
    partial.mkdir(mode=0o700)
    started = time.monotonic_ns()
    deadline = stage_deadline(
        freeze, admission, stage="device-qualification", slot="result",
        started_monotonic_nanoseconds=started)

    def deadline_check(phase: str, next_unit_index: int) -> None:
        try:
            deadline.check(
                phase=phase, next_unit_index=next_unit_index,
                observed_monotonic_nanoseconds=time.monotonic_ns())
        except BeliefV2DeadlineError as exc:
            publish_deadline_refusal(partial, exc.refusal)
            raise BeliefV2DeviceControllerError(
                "V2 device deadline exhausted and recorded") from exc

    streaming = streaming_index is not None or load_round is not None
    materialized = primary_examples is not None
    if streaming != (streaming_index is not None and callable(load_round)) \
            or streaming == materialized:
        raise BeliefV2DeviceControllerError(
            "V2 device qualification input mode drift")
    common = {
        "execution_git": freeze.execution_git,
        "candidate_device": freeze.training_candidate_device,
        "primary": primary,
        "host_memory_cap_bytes": (
            freeze.resource_caps.training_host_memory_bytes),
        "device_memory_cap_bytes": (
            freeze.resource_caps.training_device_memory_bytes),
        "deadline_check": deadline_check,
    }
    try:
        if streaming:
            plan, result = run_device_qualification_streaming(
                **common, streaming_index=streaming_index,
                load_round=load_round)
        else:
            plan, result = run_device_qualification_in_memory(
                **common, primary_examples=primary_examples)
    except ValueError as exc:
        raise BeliefV2DeviceControllerError(
            "V2 device qualification execution refused") from exc
    if plan.canonical_bytes() != expected.canonical_bytes():
        raise BeliefV2DeviceControllerError(
            "V2 device qualification executed plan drift")
    deadline_check("before-seal", len(result.arms))
    plan_raw = plan.canonical_bytes()
    result_raw = result.canonical_bytes(plan)
    publish_exclusive_bytes(partial / "plan.json", plan_raw)
    publish_exclusive_bytes(partial / "result.json", result_raw)
    manifest = _manifest(freeze, admission, primary, plan, result)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened, _, _ = reopen_device_qualification(
        final, freeze=freeze, admission=admission, primary=primary)
    if reopened != manifest:
        raise BeliefV2DeviceControllerError(
            "V2 device qualification post-publish drift")
    return reopened


def reopen_device_qualification(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1) \
        -> tuple[dict[str, Any], V2DeviceQualificationPlanV1,
                 V2DeviceQualificationResultV1]:
    """Reopen all raw bytes and independently reproduce device selection."""
    expected_plan = _expected_plan(freeze, primary)
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != "result" \
            or {path.name for path in directory.iterdir()} \
            != {"manifest.json", "plan.json", "result.json"}:
        raise BeliefV2DeviceControllerError(
            "V2 device qualification directory drift")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    plan_raw = stable_read_bytes(directory / "plan.json")
    result_raw = stable_read_bytes(directory / "result.json")
    try:
        payload = json.loads(manifest_raw)
        plan = reopen_qualification_plan(plan_raw)
        result = reopen_qualification_result(plan, result_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BeliefV2DeviceControllerError(
            "V2 device qualification raw reopen refused") from exc
    if plan.canonical_bytes() != expected_plan.canonical_bytes():
        raise BeliefV2DeviceControllerError(
            "V2 device qualification plan/primary drift")
    expected = _manifest(freeze, admission, primary, plan, result)
    if type(payload) is not dict \
            or canonical_json_bytes(payload) != manifest_raw \
            or payload != expected \
            or payload["retry_count"] != 0 \
            or payload["fallback_arm_count"] != 0 \
            or any(payload[key] is not False for key in (
                "training_authorized_by_this_artifact",
                "test_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2DeviceControllerError(
            "V2 device qualification manifest reconstruction drift")
    return payload, plan, result
