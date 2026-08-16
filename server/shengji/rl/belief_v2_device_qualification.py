"""Closed CPU-versus-accelerator qualification for BELIEF-V1 V2.

The protocol deterministically selects a bounded representative batch subset
from the realized training schedule, fixes warmup and alternating measured-arm
order, and derives the sole permitted device decision.  It does not open a
corpus, train a model, measure a clock, write an artifact, or authorize a run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_accelerator import (
    CPU_MEMBER_WORKERS,
    canonical_training_device,
)

if TYPE_CHECKING:
    from .belief_v2_schedule import V2CohortRealizationV1


QUALIFICATION_PLAN_SCHEMA = "belief-v1-v2-device-qualification-plan-v2"
QUALIFICATION_ARM_SCHEMA = "belief-v1-v2-device-qualification-arm-v1"
QUALIFICATION_RESULT_SCHEMA = "belief-v1-v2-device-qualification-result-v1"
QUALIFICATION_NAMESPACE = "belief-v1-v2-device-qualification-v1"
MEASURED_BATCH_COUNT = 32
MEASURED_PAIR_COUNT = 3
MIN_WALL_REDUCTION_PERCENT = 15


class BeliefV2DeviceQualificationError(ValueError):
    """A qualification plan, arm, integrity gate, or verdict drifted."""


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _sha(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _batch_schedule_sha256(
        batch_decision_keys: tuple[tuple[str, ...], ...]) -> str:
    return _sha({
        "schema": "belief-v1-v2-realized-training-batch-schedule-v1",
        "batch_count": len(batch_decision_keys),
        "batch_decision_keys": [list(batch) for batch in batch_decision_keys],
    })


def _selected_indices(
        batch_decision_keys: tuple[tuple[str, ...], ...],
        batch_active_label_counts: tuple[int, ...]) -> tuple[int, ...]:
    if type(batch_decision_keys) is not tuple \
            or len(batch_decision_keys) < MEASURED_BATCH_COUNT \
            or any(type(batch) is not tuple or not batch
                   or any(type(key) is not str or not _is_sha256(key)
                          for key in batch)
                   for batch in batch_decision_keys) \
            or len({key for batch in batch_decision_keys for key in batch}) \
            != sum(len(batch) for batch in batch_decision_keys) \
            or type(batch_active_label_counts) is not tuple \
            or len(batch_active_label_counts) != len(batch_decision_keys) \
            or any(type(value) is not int or value <= 0
                   for value in batch_active_label_counts):
        raise BeliefV2DeviceQualificationError(
            "device qualification training schedule drift")
    schedule_sha = _batch_schedule_sha256(batch_decision_keys)
    ranked = sorted(range(len(batch_decision_keys)), key=lambda index: (
        hashlib.sha256(
            f"{QUALIFICATION_NAMESPACE}|{schedule_sha}|{index}".encode(
                "ascii")).digest(), index))
    maximum_batch = max(
        range(len(batch_decision_keys)),
        key=lambda index: (len(batch_decision_keys[index]), -index))
    minimum_density = min(
        range(len(batch_decision_keys)),
        key=lambda index: (
            Fraction(batch_active_label_counts[index],
                     len(batch_decision_keys[index])), index))
    maximum_density = max(
        range(len(batch_decision_keys)),
        key=lambda index: (
            Fraction(batch_active_label_counts[index],
                     len(batch_decision_keys[index])), -index))
    selected = {maximum_batch, minimum_density, maximum_density}
    for index in ranked:
        selected.add(index)
        if len(selected) == MEASURED_BATCH_COUNT:
            break
    if len(selected) != MEASURED_BATCH_COUNT:
        raise BeliefV2DeviceQualificationError(
            "device qualification selected batch population drift")
    return tuple(sorted(selected))


def expected_arm_order(candidate_device: str) \
        -> tuple[tuple[str, bool, int], ...]:
    candidate = canonical_training_device(candidate_device)
    if candidate == "cpu":
        return (
            ("cpu", True, -1),
            ("cpu", False, 0),
            ("cpu", False, 1),
            ("cpu", False, 2),
        )
    return (
        ("cpu", True, -1),
        (candidate, True, -1),
        ("cpu", False, 0),
        (candidate, False, 0),
        (candidate, False, 1),
        ("cpu", False, 1),
        ("cpu", False, 2),
        (candidate, False, 2),
    )


def qualification_protocol_sha256(candidate_device: str) -> str:
    """Bind every choice that may affect the post-capture device decision."""
    candidate = canonical_training_device(candidate_device)
    return _sha({
        "schema": "belief-v1-v2-device-qualification-protocol-v4",
        "candidate_device": candidate,
        "selection_namespace": QUALIFICATION_NAMESPACE,
        "measured_batch_count": MEASURED_BATCH_COUNT,
        "selection_includes_maximum_batch_size": True,
        "selection_includes_active_label_density_extremes": True,
        "warmup_uses_same_batch_population": True,
        "measured_pair_count": MEASURED_PAIR_COUNT,
        "arm_order": [
            {"device": device, "warmup": warmup, "pair_index": pair}
            for device, warmup, pair in expected_arm_order(candidate)
        ],
        "cpu_only_no_accelerator_candidate": candidate == "cpu",
        "minimum_wall_reduction_percent": (
            0 if candidate == "cpu" else MIN_WALL_REDUCTION_PERCENT),
        "all_paired_reductions_must_be_positive": True,
        "within_device_checkpoint_loss_and_receipt_repeatability": True,
        "fallback_authorized": False,
        "cross_device_checkpoint_equality_required": False,
        "cpu_member_workers": CPU_MEMBER_WORKERS,
        "accelerator_member_workers": 1,
        "cpu_training_process_count_bound_to_frozen_cohort_count": True,
        "accelerator_training_process_count": 1,
        "aggregate_training_host_memory_upper_bound_required": True,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    })


def training_host_memory_upper_bound(
        peak_host_memory_bytes: int, *, selected_device: str,
        cpu_cohort_process_count: int) -> tuple[int, int]:
    """Return the conservative concurrent-process host-memory bound."""
    device = canonical_training_device(selected_device)
    if type(peak_host_memory_bytes) is not int \
            or peak_host_memory_bytes <= 0 \
            or type(cpu_cohort_process_count) is not int \
            or cpu_cohort_process_count <= 0:
        raise BeliefV2DeviceQualificationError(
            "device qualification host memory population drift")
    process_count = cpu_cohort_process_count if device == "cpu" else 1
    return process_count, peak_host_memory_bytes * process_count


@dataclass(frozen=True)
class V2DeviceQualificationPlanV1:
    execution_git: str
    candidate_device: str
    full_schedule_sha256: str
    selected_batch_indices: tuple[int, ...]
    selected_population_sha256: str
    selected_schedule_sha256: str
    decision_count: int
    active_label_count: int
    host_memory_cap_bytes: int
    device_memory_cap_bytes: int
    arm_order: tuple[tuple[str, bool, int], ...]
    model_seeds: tuple[int, ...] = COHORT_SEEDS
    schema: str = QUALIFICATION_PLAN_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "execution_git": self.execution_git,
            "candidate_device": self.candidate_device,
            "full_schedule_sha256": self.full_schedule_sha256,
            "selected_batch_indices": list(self.selected_batch_indices),
            "selected_population_sha256": self.selected_population_sha256,
            "selected_schedule_sha256": self.selected_schedule_sha256,
            "measured_batch_count": MEASURED_BATCH_COUNT,
            "warmup_uses_same_batch_population": True,
            "decision_count": self.decision_count,
            "active_label_count": self.active_label_count,
            "host_memory_cap_bytes": self.host_memory_cap_bytes,
            "device_memory_cap_bytes": self.device_memory_cap_bytes,
            "model_seeds": list(self.model_seeds),
            "arm_order": [
                {"device": device, "warmup": warmup, "pair_index": pair}
                for device, warmup, pair in self.arm_order
            ],
            "minimum_wall_reduction_percent": (
                0 if self.candidate_device == "cpu"
                else MIN_WALL_REDUCTION_PERCENT),
            "cpu_only_no_accelerator_candidate": (
                self.candidate_device == "cpu"),
            "training_authorized": False,
            "test_open_authorized": False,
            "strength_claim_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        validate_qualification_plan(self)
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_qualification_plan(
        *, execution_git: str, candidate_device: str,
        batch_decision_keys: tuple[tuple[str, ...], ...],
        batch_active_label_counts: tuple[int, ...],
        host_memory_cap_bytes: int,
        device_memory_cap_bytes: int) -> V2DeviceQualificationPlanV1:
    """Derive the only plan allowed for one realized training schedule."""
    indices = _selected_indices(
        batch_decision_keys, batch_active_label_counts)
    selected = tuple(batch_decision_keys[index] for index in indices)
    flattened = tuple(key for batch in selected for key in batch)
    plan = V2DeviceQualificationPlanV1(
        execution_git=execution_git,
        candidate_device=canonical_training_device(candidate_device),
        full_schedule_sha256=_batch_schedule_sha256(batch_decision_keys),
        selected_batch_indices=indices,
        selected_population_sha256=_sha({
            "schema": "belief-v1-v2-device-population-v1",
            "decision_keys": sorted(flattened),
        }),
        selected_schedule_sha256=_batch_schedule_sha256(selected),
        decision_count=len(flattened),
        active_label_count=sum(
            batch_active_label_counts[index] for index in indices),
        host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes,
        arm_order=expected_arm_order(candidate_device),
    )
    validate_qualification_plan(plan)
    return plan


def build_qualification_plan_from_primary(
        *, execution_git: str, candidate_device: str,
        primary: V2CohortRealizationV1,
        host_memory_cap_bytes: int,
        device_memory_cap_bytes: int) -> V2DeviceQualificationPlanV1:
    """Bind qualification directly to the reopened primary realization."""
    from .belief_v2_schedule import V2CohortRealizationV1

    if type(primary) is not V2CohortRealizationV1 \
            or primary.kind != "synthetic-primary" \
            or primary.cohort_id != "synthetic-primary":
        raise BeliefV2DeviceQualificationError(
            "device qualification primary realization drift")
    try:
        primary.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2DeviceQualificationError(
            "device qualification primary realization drift") from exc
    active_by_key = {
        row.decision_key: row.active_label_count for row in primary.rows}
    if len(active_by_key) != len(primary.rows):
        raise BeliefV2DeviceQualificationError(
            "device qualification primary population drift")
    try:
        active_counts = tuple(sum(active_by_key[key] for key in batch)
                              for batch in primary.batches)
    except KeyError as exc:
        raise BeliefV2DeviceQualificationError(
            "device qualification primary schedule drift") from exc
    return build_qualification_plan(
        execution_git=execution_git, candidate_device=candidate_device,
        batch_decision_keys=primary.batches,
        batch_active_label_counts=active_counts,
        host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes)


def validate_qualification_plan(value: V2DeviceQualificationPlanV1) -> None:
    if type(value) is not V2DeviceQualificationPlanV1 \
            or value.schema != QUALIFICATION_PLAN_SCHEMA \
            or type(value.execution_git) is not str \
            or len(value.execution_git) != 40 \
            or any(char not in "0123456789abcdef"
                   for char in value.execution_git) \
            or canonical_training_device(value.candidate_device) \
            != value.candidate_device \
            or not _is_sha256(value.full_schedule_sha256) \
            or not _is_sha256(value.selected_population_sha256) \
            or not _is_sha256(value.selected_schedule_sha256) \
            or type(value.selected_batch_indices) is not tuple \
            or len(value.selected_batch_indices) != MEASURED_BATCH_COUNT \
            or tuple(sorted(value.selected_batch_indices)) \
            != value.selected_batch_indices \
            or len(set(value.selected_batch_indices)) \
            != MEASURED_BATCH_COUNT \
            or any(type(index) is not int or index < 0
                   for index in value.selected_batch_indices) \
            or type(value.decision_count) is not int \
            or value.decision_count < MEASURED_BATCH_COUNT \
            or type(value.active_label_count) is not int \
            or value.active_label_count <= 0 \
            or type(value.host_memory_cap_bytes) is not int \
            or value.host_memory_cap_bytes <= 0 \
            or type(value.device_memory_cap_bytes) is not int \
            or value.device_memory_cap_bytes < 0 \
            or value.model_seeds != COHORT_SEEDS \
            or value.arm_order != expected_arm_order(value.candidate_device):
        raise BeliefV2DeviceQualificationError(
            "device qualification plan drift")


@dataclass(frozen=True)
class V2DeviceQualificationArmV1:
    arm_index: int
    device: str
    warmup: bool
    pair_index: int
    plan_sha256: str
    batch_population_sha256: str
    batch_schedule_sha256: str
    decision_count: int
    active_label_count: int
    member_checkpoint_sha256s: tuple[str, ...]
    member_loss_nanonats: tuple[int, ...]
    member_epoch_receipt_sha256s: tuple[str, ...]
    wall_nanoseconds: int
    peak_host_memory_bytes: int
    peak_device_memory_bytes: int
    actual_device: str
    fallback_used: bool = False
    completed: bool = True
    schema: str = QUALIFICATION_ARM_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "arm_index": self.arm_index,
            "device": self.device,
            "warmup": self.warmup,
            "pair_index": self.pair_index,
            "plan_sha256": self.plan_sha256,
            "batch_population_sha256": self.batch_population_sha256,
            "batch_schedule_sha256": self.batch_schedule_sha256,
            "decision_count": self.decision_count,
            "active_label_count": self.active_label_count,
            "member_checkpoint_sha256s": list(
                self.member_checkpoint_sha256s),
            "member_loss_nanonats": list(self.member_loss_nanonats),
            "member_epoch_receipt_sha256s": list(
                self.member_epoch_receipt_sha256s),
            "wall_nanoseconds": self.wall_nanoseconds,
            "peak_host_memory_bytes": self.peak_host_memory_bytes,
            "peak_device_memory_bytes": self.peak_device_memory_bytes,
            "actual_device": self.actual_device,
            "fallback_used": self.fallback_used,
            "completed": self.completed,
        }


def _validate_arm(
        plan: V2DeviceQualificationPlanV1,
        arm: V2DeviceQualificationArmV1) -> None:
    if type(arm) is not V2DeviceQualificationArmV1:
        raise BeliefV2DeviceQualificationError(
            "device qualification arm drift")
    expected_device, expected_warmup, expected_pair = plan.arm_order[
        arm.arm_index] if type(arm.arm_index) is int \
        and 0 <= arm.arm_index < len(plan.arm_order) else (None, None, None)
    if arm.schema != QUALIFICATION_ARM_SCHEMA \
            or (arm.device, arm.warmup, arm.pair_index) \
            != (expected_device, expected_warmup, expected_pair) \
            or arm.actual_device != arm.device \
            or arm.plan_sha256 != plan.sha256() \
            or arm.batch_population_sha256 \
            != plan.selected_population_sha256 \
            or arm.batch_schedule_sha256 != plan.selected_schedule_sha256 \
            or arm.decision_count != plan.decision_count \
            or arm.active_label_count != plan.active_label_count \
            or type(arm.member_checkpoint_sha256s) is not tuple \
            or len(arm.member_checkpoint_sha256s) != len(COHORT_SEEDS) \
            or any(not _is_sha256(value)
                   for value in arm.member_checkpoint_sha256s) \
            or type(arm.member_loss_nanonats) is not tuple \
            or len(arm.member_loss_nanonats) != len(COHORT_SEEDS) \
            or any(type(value) is not int or value < 0
                   for value in arm.member_loss_nanonats) \
            or type(arm.member_epoch_receipt_sha256s) is not tuple \
            or len(arm.member_epoch_receipt_sha256s) != len(COHORT_SEEDS) \
            or any(not _is_sha256(value)
                   for value in arm.member_epoch_receipt_sha256s) \
            or type(arm.wall_nanoseconds) is not int \
            or arm.wall_nanoseconds <= 0 \
            or type(arm.peak_host_memory_bytes) is not int \
            or not 0 <= arm.peak_host_memory_bytes \
            <= plan.host_memory_cap_bytes \
            or type(arm.peak_device_memory_bytes) is not int \
            or not 0 <= arm.peak_device_memory_bytes \
            <= plan.device_memory_cap_bytes \
            or arm.fallback_used is not False \
            or arm.completed is not True:
        raise BeliefV2DeviceQualificationError(
            "device qualification arm drift")


@dataclass(frozen=True)
class V2DeviceQualificationResultV1:
    plan_sha256: str
    arms: tuple[V2DeviceQualificationArmV1, ...]
    selected_device: str
    accelerator_retained: bool
    aggregate_cpu_wall_nanoseconds: int
    aggregate_candidate_wall_nanoseconds: int
    wall_reduction_ppb: int
    schema: str = QUALIFICATION_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "plan_sha256": self.plan_sha256,
            "arms": [arm.to_dict() for arm in self.arms],
            "selected_device": self.selected_device,
            "accelerator_retained": self.accelerator_retained,
            "aggregate_cpu_wall_nanoseconds": (
                self.aggregate_cpu_wall_nanoseconds),
            "aggregate_candidate_wall_nanoseconds": (
                self.aggregate_candidate_wall_nanoseconds),
            "wall_reduction_ppb": self.wall_reduction_ppb,
            "training_authorized": False,
            "test_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self, plan: V2DeviceQualificationPlanV1) -> bytes:
        validate_qualification_result(plan, self)
        return canonical_json_bytes(self.to_dict())


def derive_qualification_result(
        plan: V2DeviceQualificationPlanV1,
        arms: tuple[V2DeviceQualificationArmV1, ...]) \
        -> V2DeviceQualificationResultV1:
    metrics = _qualification_metrics(plan, arms)
    cpu_wall, candidate_wall, reduction, retained = metrics
    result = V2DeviceQualificationResultV1(
        plan_sha256=plan.sha256(), arms=arms,
        selected_device=plan.candidate_device if retained else "cpu",
        accelerator_retained=retained,
        aggregate_cpu_wall_nanoseconds=cpu_wall,
        aggregate_candidate_wall_nanoseconds=candidate_wall,
        wall_reduction_ppb=reduction,
    )
    validate_qualification_result(plan, result)
    return result


def _qualification_metrics(
        plan: V2DeviceQualificationPlanV1,
        arms: tuple[V2DeviceQualificationArmV1, ...]) \
        -> tuple[int, int, int, bool]:
    validate_qualification_plan(plan)
    if type(arms) is not tuple or len(arms) != len(plan.arm_order):
        raise BeliefV2DeviceQualificationError(
            "device qualification arm population drift")
    for arm in arms:
        _validate_arm(plan, arm)
    if tuple(arm.arm_index for arm in arms) != tuple(range(len(arms))):
        raise BeliefV2DeviceQualificationError(
            "device qualification arm order drift")
    measured = tuple(arm for arm in arms if not arm.warmup)
    if plan.candidate_device == "cpu":
        if len(measured) != MEASURED_PAIR_COUNT \
                or tuple(arm.pair_index for arm in measured) \
                != tuple(range(MEASURED_PAIR_COUNT)) \
                or len({arm.member_checkpoint_sha256s
                        for arm in measured}) != 1 \
                or len({arm.member_loss_nanonats for arm in measured}) != 1 \
                or len({arm.member_epoch_receipt_sha256s
                        for arm in measured}) != 1:
            raise BeliefV2DeviceQualificationError(
                "device qualification CPU determinism drift")
        return (sum(arm.wall_nanoseconds for arm in measured), 0, 0, False)
    for device in ("cpu", plan.candidate_device):
        rows = tuple(arm for arm in measured if arm.device == device)
        if len(rows) != MEASURED_PAIR_COUNT \
                or len({arm.member_checkpoint_sha256s for arm in rows}) != 1 \
                or len({arm.member_loss_nanonats for arm in rows}) != 1 \
                or len({arm.member_epoch_receipt_sha256s
                        for arm in rows}) != 1:
            raise BeliefV2DeviceQualificationError(
                "device qualification determinism drift")
    cpu_by_pair = {arm.pair_index: arm for arm in measured
                   if arm.device == "cpu"}
    candidate_by_pair = {arm.pair_index: arm for arm in measured
                         if arm.device == plan.candidate_device}
    cpu_wall = sum(arm.wall_nanoseconds for arm in cpu_by_pair.values())
    candidate_wall = sum(
        arm.wall_nanoseconds for arm in candidate_by_pair.values())
    positive = all(candidate_by_pair[index].wall_nanoseconds
                   < cpu_by_pair[index].wall_nanoseconds
                   for index in range(MEASURED_PAIR_COUNT))
    retained = positive and candidate_wall * 100 \
        <= cpu_wall * (100 - MIN_WALL_REDUCTION_PERCENT)
    reduction = (cpu_wall - candidate_wall) * 1_000_000_000 // cpu_wall
    return cpu_wall, candidate_wall, reduction, retained


def validate_qualification_result(
        plan: V2DeviceQualificationPlanV1,
        result: V2DeviceQualificationResultV1) -> None:
    if type(result) is not V2DeviceQualificationResultV1 \
            or result.schema != QUALIFICATION_RESULT_SCHEMA \
            or result.plan_sha256 != plan.sha256():
        raise BeliefV2DeviceQualificationError(
            "device qualification result identity drift")
    cpu_wall, candidate_wall, reduction, retained = _qualification_metrics(
        plan, result.arms)
    if result.selected_device \
            != (plan.candidate_device if retained else "cpu") \
            or result.accelerator_retained is not retained \
            or result.aggregate_cpu_wall_nanoseconds != cpu_wall \
            or result.aggregate_candidate_wall_nanoseconds != candidate_wall \
            or result.wall_reduction_ppb != reduction:
        raise BeliefV2DeviceQualificationError(
            "device qualification result derivation drift")


def reopen_qualification_plan(raw: bytes) -> V2DeviceQualificationPlanV1:
    """Strictly reconstruct a persisted qualification plan."""
    if type(raw) is not bytes or not raw:
        raise BeliefV2DeviceQualificationError(
            "device qualification plan artifact is empty")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2DeviceQualificationError(
            "device qualification plan artifact is not JSON") from exc
    expected_keys = {
        "schema", "execution_git", "candidate_device",
        "full_schedule_sha256", "selected_batch_indices",
        "selected_population_sha256", "selected_schedule_sha256",
        "measured_batch_count", "warmup_uses_same_batch_population",
        "decision_count", "active_label_count", "host_memory_cap_bytes",
        "device_memory_cap_bytes", "model_seeds", "arm_order",
        "minimum_wall_reduction_percent",
        "cpu_only_no_accelerator_candidate", "training_authorized",
        "test_open_authorized", "strength_claim_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != QUALIFICATION_PLAN_SCHEMA \
            or payload["measured_batch_count"] != MEASURED_BATCH_COUNT \
            or payload["warmup_uses_same_batch_population"] is not True \
            or payload["model_seeds"] != list(COHORT_SEEDS) \
            or payload["minimum_wall_reduction_percent"] \
            != (0 if payload["candidate_device"] == "cpu"
                else MIN_WALL_REDUCTION_PERCENT) \
            or payload["cpu_only_no_accelerator_candidate"] \
            is not (payload["candidate_device"] == "cpu") \
            or any(payload[key] is not False for key in (
                "training_authorized", "test_open_authorized",
                "strength_claim_authorized")) \
            or type(payload["selected_batch_indices"]) is not list \
            or type(payload["arm_order"]) is not list \
            or any(type(row) is not dict or set(row) != {
                "device", "warmup", "pair_index"}
                   for row in payload["arm_order"]):
        raise BeliefV2DeviceQualificationError(
            "device qualification plan artifact identity drift")
    result = V2DeviceQualificationPlanV1(
        execution_git=payload["execution_git"],
        candidate_device=payload["candidate_device"],
        full_schedule_sha256=payload["full_schedule_sha256"],
        selected_batch_indices=tuple(payload["selected_batch_indices"]),
        selected_population_sha256=payload["selected_population_sha256"],
        selected_schedule_sha256=payload["selected_schedule_sha256"],
        decision_count=payload["decision_count"],
        active_label_count=payload["active_label_count"],
        host_memory_cap_bytes=payload["host_memory_cap_bytes"],
        device_memory_cap_bytes=payload["device_memory_cap_bytes"],
        arm_order=tuple((row["device"], row["warmup"], row["pair_index"])
                        for row in payload["arm_order"]))
    validate_qualification_plan(result)
    if result.canonical_bytes() != raw:
        raise BeliefV2DeviceQualificationError(
            "device qualification plan artifact reconstruction drift")
    return result


def reopen_qualification_result(
        plan: V2DeviceQualificationPlanV1,
        raw: bytes) -> V2DeviceQualificationResultV1:
    """Strictly reconstruct every arm and the selected-device verdict."""
    if type(raw) is not bytes or not raw:
        raise BeliefV2DeviceQualificationError(
            "device qualification result artifact is empty")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2DeviceQualificationError(
            "device qualification result artifact is not JSON") from exc
    expected_keys = {
        "schema", "plan_sha256", "arms", "selected_device",
        "accelerator_retained", "aggregate_cpu_wall_nanoseconds",
        "aggregate_candidate_wall_nanoseconds", "wall_reduction_ppb",
        "training_authorized", "test_open_authorized",
        "strength_claim_authorized", "deployment_authorized",
    }
    arm_keys = {
        "schema", "arm_index", "device", "warmup", "pair_index",
        "plan_sha256", "batch_population_sha256",
        "batch_schedule_sha256", "decision_count", "active_label_count",
        "member_checkpoint_sha256s", "member_loss_nanonats",
        "member_epoch_receipt_sha256s", "wall_nanoseconds",
        "peak_host_memory_bytes", "peak_device_memory_bytes",
        "actual_device", "fallback_used", "completed",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != QUALIFICATION_RESULT_SCHEMA \
            or type(payload["arms"]) is not list \
            or any(type(row) is not dict or set(row) != arm_keys
                   for row in payload["arms"]) \
            or any(payload[key] is not False for key in (
                "training_authorized", "test_open_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2DeviceQualificationError(
            "device qualification result artifact identity drift")
    arms = tuple(V2DeviceQualificationArmV1(
        arm_index=row["arm_index"], device=row["device"],
        warmup=row["warmup"], pair_index=row["pair_index"],
        plan_sha256=row["plan_sha256"],
        batch_population_sha256=row["batch_population_sha256"],
        batch_schedule_sha256=row["batch_schedule_sha256"],
        decision_count=row["decision_count"],
        active_label_count=row["active_label_count"],
        member_checkpoint_sha256s=tuple(
            row["member_checkpoint_sha256s"]),
        member_loss_nanonats=tuple(row["member_loss_nanonats"]),
        member_epoch_receipt_sha256s=tuple(
            row["member_epoch_receipt_sha256s"]),
        wall_nanoseconds=row["wall_nanoseconds"],
        peak_host_memory_bytes=row["peak_host_memory_bytes"],
        peak_device_memory_bytes=row["peak_device_memory_bytes"],
        actual_device=row["actual_device"],
        fallback_used=row["fallback_used"], completed=row["completed"])
                 for row in payload["arms"])
    result = V2DeviceQualificationResultV1(
        plan_sha256=payload["plan_sha256"], arms=arms,
        selected_device=payload["selected_device"],
        accelerator_retained=payload["accelerator_retained"],
        aggregate_cpu_wall_nanoseconds=payload[
            "aggregate_cpu_wall_nanoseconds"],
        aggregate_candidate_wall_nanoseconds=payload[
            "aggregate_candidate_wall_nanoseconds"],
        wall_reduction_ppb=payload["wall_reduction_ppb"])
    validate_qualification_result(plan, result)
    if result.canonical_bytes(plan) != raw:
        raise BeliefV2DeviceQualificationError(
            "device qualification result artifact reconstruction drift")
    return result
