"""Targeted, score-free recovery for a late Value V2 capacity projection.

The recovery path consumes the exact Census-11 projection refusal, reruns only
fresh preflight plus a sustained width-two/width-four cohort benchmark, and
publishes one composite capacity artifact.  It never reruns the retained
19-stage representative DAG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, CAPACITY_HOST_LOGICAL_CPUS,
    CAPACITY_STAGE_TO_ARM, COMPOSED_STAGE_NAMES, COMPLETE_DAG_WALL_SECONDS_MAX,
    MEMORY_LIMIT_BYTES, MEMORY_PERCENT_MAX, MIN_CPU_UTILIZATION_PPM,
    MIN_WALL_SHARE_PPM, PINNED_TORCH_THREADS, SCIENTIFIC_SERVICE_SECONDS,
    ZERO_SWAP_BYTES, CapacityArmV2,
    CapacityFailureReceiptV2, CapacityTierReceiptV2, ComposedProjectionV2,
    ProgressRecoveryV2, TierProjectionV2,
    choose_capacity_tier, composed_critical_path_seconds,
    composed_dag_edges_for_cohort_workers,
    reopen_capacity_failure_receipt_v2,
)


RECOVERY_SCHEMA = "world-afterstate-v2-capacity-recovery-v1"
RECOVERY_SELECTION_SCHEMA = "world-afterstate-v2-capacity-selection-v1"
RECOVERY_FAILURE_SCHEMA = "world-afterstate-v2-capacity-recovery-failure-v1"
BASE_SOURCE_GIT = "8ff9c79cd294770b51127ec7a844694784b7d0bc"
BASE_FAILURE_EXTERNAL_SHA256 = (
    "06019851ec4a2aecdc8541d623a02e9d8355c3d68d69c9fe29572a3d0d5be14d")
BASE_FAILURE_RECEIPT_SHA256 = (
    "3a059e3de3c506117bac71611acf20ec3e2fbfdeb3c64e1baadd8d145db5a8b7")
BASE_FAILURE_SOURCE_SHA256 = (
    "53932edb01fabe8f9a3a93d962c34f589e2fe4dcfac1e90a6a6787fb155be6f7")
SUSTAINED_COHORT_EPOCHS = 8
RECOVERY_COHORT_VARIANTS = (2, 4)
RECOVERY_COMMAND_WALL_SECONDS = 60 * 60


class CapacityRecoveryError(ValueError):
    """A composite receipt or targeted recovery measurement was refused."""


@dataclass(frozen=True)
class CapacityRecoveryFailureV2:
    """One bounded refusal from the targeted recovery command."""

    reason: str
    detail_message: str
    elapsed_seconds: int
    source_sha256: str
    runtime_sha256: str
    base_failure_external_sha256: str
    deadline_seconds: int = RECOVERY_COMMAND_WALL_SECONDS
    schema: str = RECOVERY_FAILURE_SCHEMA

    def payload(self) -> dict[str, Any]:
        if (self.schema != RECOVERY_FAILURE_SCHEMA
                or type(self.reason) is not str or not self.reason
                or len(self.reason) > 64
                or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
                       for char in self.reason)
                or type(self.detail_message) is not str
                or not 1 <= len(self.detail_message) <= 512
                or self.base_failure_external_sha256
                != BASE_FAILURE_EXTERNAL_SHA256
                or self.deadline_seconds != RECOVERY_COMMAND_WALL_SECONDS):
            raise CapacityRecoveryError("capacity recovery failure identity drift")
        _integer(self.elapsed_seconds, "capacity recovery failure elapsed")
        if self.elapsed_seconds > self.deadline_seconds:
            raise CapacityRecoveryError("capacity recovery failure deadline drift")
        _digest(self.source_sha256, "capacity recovery failure source")
        _digest(self.runtime_sha256, "capacity recovery failure runtime")
        body = {
            "schema": self.schema, "status": "failure",
            "reason": self.reason, "detail_message": self.detail_message,
            "detail_sha256": _sha({"message": self.detail_message}),
            "elapsed_seconds": self.elapsed_seconds,
            "deadline_seconds": self.deadline_seconds,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "base_failure_external_sha256":
                self.base_failure_external_sha256,
            "authority": dict(AUTHORITY),
        }
        return {**body, "capacity_recovery_failure_sha256": _sha(body)}


def reopen_capacity_recovery_failure_v2(
        payload: Mapping[str, Any]) -> CapacityRecoveryFailureV2:
    required = {
        "schema", "status", "reason", "detail_message", "detail_sha256",
        "elapsed_seconds", "deadline_seconds", "source_sha256",
        "runtime_sha256", "base_failure_external_sha256", "authority",
        "capacity_recovery_failure_sha256",
    }
    if (type(payload) is not dict or set(payload) != required
            or payload["schema"] != RECOVERY_FAILURE_SCHEMA
            or payload["status"] != "failure" or payload["authority"] != AUTHORITY
            or payload["detail_sha256"]
            != _sha({"message": payload["detail_message"]})):
        raise CapacityRecoveryError("capacity recovery failure schema drift")
    body = {key: value for key, value in payload.items()
            if key != "capacity_recovery_failure_sha256"}
    if payload["capacity_recovery_failure_sha256"] != _sha(body):
        raise CapacityRecoveryError("capacity recovery failure reconstruction drift")
    value = CapacityRecoveryFailureV2(
        reason=payload["reason"], detail_message=payload["detail_message"],
        elapsed_seconds=payload["elapsed_seconds"],
        source_sha256=payload["source_sha256"],
        runtime_sha256=payload["runtime_sha256"],
        base_failure_external_sha256=payload["base_failure_external_sha256"],
        deadline_seconds=payload["deadline_seconds"], schema=payload["schema"])
    if value.payload() != payload:
        raise CapacityRecoveryError("capacity recovery failure canonical drift")
    return value


def reopen_capacity_recovery_failure_v2_bytes(
        raw: bytes) -> CapacityRecoveryFailureV2:
    if type(raw) is not bytes:
        raise CapacityRecoveryError("capacity recovery failure bytes drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityRecoveryError(
            "capacity recovery failure is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise CapacityRecoveryError(
            "capacity recovery failure is not canonical JSON")
    return reopen_capacity_recovery_failure_v2(payload)


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise CapacityRecoveryError(f"{label} drift")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CapacityRecoveryError(f"{label} drift")
    return value


@dataclass(frozen=True)
class CapacitySelectionV2:
    """One downstream-consumable selected variant and its evidence binding."""

    stage: str
    variant: int
    evidence_sha256: str
    schema: str = RECOVERY_SELECTION_SCHEMA

    def validate(self) -> None:
        if (self.schema != RECOVERY_SELECTION_SCHEMA
                or self.stage not in ARM_GRIDS
                or self.variant not in ARM_GRIDS[self.stage]):
            raise CapacityRecoveryError("capacity recovery selection drift")
        _digest(self.evidence_sha256, "capacity recovery selection evidence")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "stage": self.stage,
                "variant": self.variant,
                "evidence_sha256": self.evidence_sha256}

    @classmethod
    def reopen(cls, payload: Mapping[str, Any]) -> "CapacitySelectionV2":
        if (type(payload) is not dict
                or set(payload) != {"schema", "stage", "variant",
                                    "evidence_sha256"}):
            raise CapacityRecoveryError("capacity recovery selection schema drift")
        value = cls(**payload)
        value.validate()
        if value.payload() != payload:
            raise CapacityRecoveryError("capacity recovery selection canonical drift")
        return value


def _preflight_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "attempted", "accepted", "rejection_counts",
        "candidate_distribution", "stratum_distribution",
        "elapsed_wall_nanoseconds", "outcomes_opened",
        "accepted_fixture_sha256s",
    }
    if (type(value) is not dict or set(value) != required
            or value["schema"] != "world-afterstate-v2-score-free-preflight-v1"
            or value["accepted"] != 32 or value["outcomes_opened"] is not False
            or type(value["accepted_fixture_sha256s"]) is not list
            or len(value["accepted_fixture_sha256s"]) != 32
            or len(set(value["accepted_fixture_sha256s"])) != 32):
        raise CapacityRecoveryError("capacity recovery preflight drift")
    _integer(value["attempted"], "capacity recovery preflight attempted", minimum=32)
    _integer(value["elapsed_wall_nanoseconds"],
             "capacity recovery preflight wall", minimum=1)
    for digest in value["accepted_fixture_sha256s"]:
        _digest(digest, "capacity recovery fixture SHA-256")
    for name in ("rejection_counts", "candidate_distribution",
                 "stratum_distribution"):
        rows = value[name]
        if (type(rows) is not list
                or name != "rejection_counts" and not rows
                or any(type(row) is not list or len(row) != 2
                       or type(row[0]) not in (str, int)
                       or isinstance(row[1], bool) or not isinstance(row[1], int)
                       or row[1] < 1 for row in rows)):
            raise CapacityRecoveryError(f"capacity recovery {name} drift")
    if sum(row[1] for row in value["candidate_distribution"]) != 32 \
            or sum(row[1] for row in value["stratum_distribution"]) != 32 \
            or sum(row[1] for row in value["rejection_counts"]) \
            != value["attempted"] - value["accepted"]:
        raise CapacityRecoveryError("capacity recovery preflight distribution drift")
    return dict(value)


def _progress_recovery() -> ProgressRecoveryV2:
    return ProgressRecoveryV2(
        progress_interval_seconds=60,
        progress_interval_fraction_ppm=10_000,
        reports_stage_counts=True,
        reports_active_workers_and_cpu=True,
        reports_elapsed_eta_headroom=True,
        reports_current_peak_cgroup_memory=True,
        reports_immutable_shard_checkpoint_count=True,
        resumes_verified_shards_only=True,
        resume_same_admission=True,
        resume_cannot_regenerate_replace_select=True,
        checkpoints_each_common_epoch=True,
        deadline_truncation_keeps_complete_epoch=True,
        audit_requires_complete_upstream=True,
        audit_attempt_fsynced_before_open=True,
        one_audit_open=True,
        reconstruction_without_retraining=True,
        reconstruction_reuses_immutable_continuations=True,
    )


def _all_core_gate(base: CapacityFailureReceiptV2,
                   sustained_arms: Sequence[CapacityArmV2],
                   selected_width: int) -> bool:
    """Re-adjudicate exact retained counters plus the replaced cohort arm."""
    if any(row.violates_gate for row in base.assessments):
        return False
    diagnostic = base.projection_diagnostic
    if diagnostic is None:
        return False
    stage_walls = dict(diagnostic.stage_walls_seconds)
    total = sum(stage_walls.values())
    exact_wall = dict(diagnostic.measured_stage_wall_nanoseconds)
    exact_cpu = dict(diagnostic.measured_stage_cpu_nanoseconds)
    assessments = {row.category: row for row in base.assessments}
    by_width = {arm.variant: arm for arm in sustained_arms}
    selected = by_width.get(selected_width)
    if selected is None:
        return False
    for stage in COMPOSED_STAGE_NAMES:
        if stage_walls[stage] * 1_000_000 // total < MIN_WALL_SHARE_PPM:
            continue
        arm_stage = CAPACITY_STAGE_TO_ARM[stage]
        if arm_stage is None:
            utilization = exact_cpu[stage] * 1_000_000 // (
                exact_wall[stage] * CAPACITY_HOST_LOGICAL_CPUS)
            if utilization < MIN_CPU_UTILIZATION_PPM:
                return False
            continue
        if arm_stage == "cohort-concurrency":
            if selected.mean_cpu_utilization_ppm >= MIN_CPU_UTILIZATION_PPM:
                continue
            if selected_width != 2:
                return False
            next_arm = by_width.get(4)
            if (next_arm is None
                    or next_arm.byte_identity_sha256
                    != selected.byte_identity_sha256
                    or next_arm.peak_memory_bytes * 100
                    > MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX
                    or next_arm.wall_ns <= selected.wall_ns):
                return False
            continue
        assessment = assessments.get(arm_stage)
        if assessment is None or assessment.violates_gate:
            return False
    return True


@dataclass(frozen=True)
class CapacityRecoveryReceiptV2:
    """Composite capacity evidence retaining the old DAG and new topology."""

    base_failure: CapacityFailureReceiptV2
    base_failure_external_sha256: str
    source_sha256: str
    runtime_sha256: str
    preflight: Mapping[str, Any]
    sustained_arms: tuple[CapacityArmV2, ...]
    selections: tuple[CapacitySelectionV2, ...]
    composed: ComposedProjectionV2
    tiers: tuple[TierProjectionV2, ...]
    command_wall_seconds: int
    command_wall_nanoseconds: int
    fresh_free_disk_bytes: int
    task_count: int
    peak_task_count: int
    host_logical_cpus: int = CAPACITY_HOST_LOGICAL_CPUS
    memory_limit_bytes: int = MEMORY_LIMIT_BYTES
    swap_bytes: int = ZERO_SWAP_BYTES
    all_core_gate_passed: bool = True
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    progress_recovery: ProgressRecoveryV2 = field(default_factory=_progress_recovery)
    schema: str = RECOVERY_SCHEMA

    @property
    def selected_arms(self) -> tuple[CapacitySelectionV2, ...]:
        return self.selections

    @property
    def candidate_distribution(self) -> tuple[tuple[int, int], ...]:
        return tuple((int(row[0]), row[1])
                     for row in self.preflight["candidate_distribution"])

    @property
    def member_workers(self) -> int:
        return self._variant("member-concurrency")

    @property
    def continuation_workers(self) -> int:
        return self._variant("continuation-mechanics")

    @property
    def torch_threads(self) -> int:
        return PINNED_TORCH_THREADS

    @property
    def inference_batch(self) -> int:
        return self._variant("inference-batch")

    @property
    def reconstruction_workers(self) -> int:
        return self._variant("reconstruction")

    def _variant(self, stage: str) -> int:
        rows = tuple(row.variant for row in self.selections if row.stage == stage)
        if len(rows) != 1:
            raise CapacityRecoveryError("capacity recovery selection population drift")
        return rows[0]

    def validate(self) -> None:
        if (self.schema != RECOVERY_SCHEMA or self.authority != AUTHORITY
                or self.host_logical_cpus != CAPACITY_HOST_LOGICAL_CPUS
                or self.memory_limit_bytes != MEMORY_LIMIT_BYTES
                or self.swap_bytes != ZERO_SWAP_BYTES):
            raise CapacityRecoveryError("capacity recovery identity drift")
        _digest(self.source_sha256, "capacity recovery source")
        _digest(self.runtime_sha256, "capacity recovery runtime")
        self.base_failure.payload()
        base_raw = canonical_json_bytes(self.base_failure.payload())
        if (_sha_bytes(base_raw) != self.base_failure_external_sha256
                or self.base_failure_external_sha256
                != BASE_FAILURE_EXTERNAL_SHA256
                or self.base_failure.payload()["failure_receipt_sha256"]
                != BASE_FAILURE_RECEIPT_SHA256
                or self.base_failure.source_sha256 != BASE_FAILURE_SOURCE_SHA256
                or self.base_failure.stage != "full-dag"
                or self.base_failure.reason != "composed-projection-cap-drift"):
            raise CapacityRecoveryError("capacity recovery base failure drift")
        preflight = _preflight_payload(self.preflight)
        arms = tuple(self.sustained_arms)
        if ({(arm.stage, arm.variant) for arm in arms}
                != {("cohort-concurrency", 2), ("cohort-concurrency", 4)}
                or len(arms) != 2):
            raise CapacityRecoveryError("capacity recovery arm population drift")
        for arm in arms:
            arm.validate()
        if len({arm.byte_identity_sha256 for arm in arms}) != 1:
            raise CapacityRecoveryError("capacity recovery arm byte drift")
        eligible = tuple(arm for arm in arms if arm.peak_memory_bytes * 100
                         <= MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX)
        selected_arm = min(eligible, key=lambda arm: (arm.wall_ns, arm.variant),
                           default=None)
        if selected_arm is None:
            raise CapacityRecoveryError("capacity recovery has no eligible arm")
        if (tuple(row.stage for row in self.selections) != tuple(ARM_GRIDS)
                or len(self.selections) != len(ARM_GRIDS)):
            raise CapacityRecoveryError("capacity recovery selection grid drift")
        for row in self.selections:
            row.validate()
        if self._variant("cohort-concurrency") != selected_arm.variant:
            raise CapacityRecoveryError("capacity recovery fastest arm drift")
        base_assessments = {row.category: row for row in self.base_failure.assessments}
        if set(base_assessments) != set(ARM_GRIDS):
            raise CapacityRecoveryError("capacity recovery base assessment drift")
        sustained_evidence = _sha([arm.payload() for arm in sorted(
            arms, key=lambda value: value.variant)])
        for row in self.selections:
            expected = (sustained_evidence if row.stage == "cohort-concurrency"
                        else BASE_FAILURE_RECEIPT_SHA256)
            base_variant = base_assessments[row.stage].selected_variant
            if (row.evidence_sha256 != expected
                    or row.stage != "cohort-concurrency"
                    and row.variant != base_variant):
                raise CapacityRecoveryError("capacity recovery selection evidence drift")
        diagnostic = self.base_failure.projection_diagnostic
        if diagnostic is None:
            raise CapacityRecoveryError("capacity recovery projection missing")
        self.composed.validate()
        inherited = (
            self.composed.stage_walls_seconds == diagnostic.stage_walls_seconds
            and self.composed.stage_cpu_seconds == diagnostic.stage_cpu_seconds
            and self.composed.stage_unit_counts == diagnostic.stage_unit_counts
            and self.composed.measured_stage_wall_nanoseconds
            == diagnostic.measured_stage_wall_nanoseconds
            and self.composed.measured_stage_cpu_nanoseconds
            == diagnostic.measured_stage_cpu_nanoseconds
            and self.composed.composed_artifact_bytes
            == diagnostic.composed_artifact_bytes
            and self.composed.cohort_workers == selected_arm.variant
            and self.composed.dag_edges
            == composed_dag_edges_for_cohort_workers(selected_arm.variant)
            and self.composed.free_disk_bytes_before
            <= diagnostic.free_disk_bytes_before
            and self.composed.peak_memory_bytes == max(
                diagnostic.peak_memory_bytes,
                *(arm.peak_memory_bytes for arm in arms)))
        if not inherited:
            raise CapacityRecoveryError("capacity recovery inherited DAG drift")
        expected_wall = composed_critical_path_seconds(
            dict(self.composed.stage_walls_seconds), self.composed.dag_edges)
        if self.composed.composed_wall_seconds != expected_wall:
            raise CapacityRecoveryError("capacity recovery projection wall drift")
        if not _all_core_gate(self.base_failure, arms, selected_arm.variant) \
                or self.all_core_gate_passed is not True:
            raise CapacityRecoveryError("capacity recovery all-core gate drift")
        if type(self.tiers) is not tuple:
            raise CapacityRecoveryError("capacity recovery tier population drift")
        for tier in self.tiers:
            tier.validate()
        if {tier.tier for tier in self.tiers} != {"D256", "D512", "D1024"}:
            raise CapacityRecoveryError("capacity recovery tier grid drift")
        self.progress_recovery.validate()
        _integer(self.command_wall_seconds, "capacity recovery command wall", minimum=1)
        _integer(self.command_wall_nanoseconds,
                 "capacity recovery command wall nanoseconds", minimum=1)
        _integer(self.fresh_free_disk_bytes,
                 "capacity recovery fresh free disk", minimum=1)
        _integer(self.task_count, "capacity recovery task count", minimum=1)
        _integer(self.peak_task_count, "capacity recovery peak tasks", minimum=1)
        if (self.command_wall_seconds > RECOVERY_COMMAND_WALL_SECONDS
                or self.task_count > 4096 or self.peak_task_count > 4096):
            raise CapacityRecoveryError("capacity recovery command cap drift")
        charged_nanoseconds = preflight["elapsed_wall_nanoseconds"] \
            + sum(arm.wall_ns for arm in arms)
        if (self.command_wall_seconds
                != (self.command_wall_nanoseconds + 999_999_999)
                // 1_000_000_000
                or self.command_wall_nanoseconds < charged_nanoseconds
                or self.command_wall_nanoseconds
                > RECOVERY_COMMAND_WALL_SECONDS * 1_000_000_000
                or self.composed.free_disk_bytes_before != min(
                    diagnostic.free_disk_bytes_before,
                    self.fresh_free_disk_bytes)):
            raise CapacityRecoveryError("capacity recovery wall accounting drift")
        # A valid composite must actually unlock at least D256 under every
        # unchanged protocol gate.  Otherwise the command publishes refusal.
        self.choose_tier()

    def protocol_receipts(self) -> tuple[CapacityTierReceiptV2, ...]:
        return tuple(CapacityTierReceiptV2(
            tier=tier.tier, host_logical_cpus=self.host_logical_cpus,
            exact_source_supply=tier.exact_source_supply,
            byte_identical=tier.byte_identical,
            outcomes_opened=tier.outcomes_opened,
            all_core_gate_passed=self.all_core_gate_passed,
            label_wall_seconds=tier.label_wall_seconds,
            label_cpu_seconds=tier.label_cpu_seconds,
            complete_dag_wall_seconds=tier.complete_dag_wall_seconds,
            service_wall_seconds=SCIENTIFIC_SERVICE_SECONDS,
            peak_memory_bytes=tier.peak_memory_bytes,
            memory_limit_bytes=self.memory_limit_bytes,
            composed_artifact_bytes=tier.composed_artifact_bytes,
            free_disk_bytes_before=tier.free_disk_bytes_before)
                     for tier in sorted(self.tiers, key=lambda value: value.tier))

    def choose_tier(self):
        return choose_capacity_tier(self.protocol_receipts())

    def payload(self) -> dict[str, Any]:
        self.validate()
        body = {
            "schema": self.schema,
            "base_source_git": BASE_SOURCE_GIT,
            "base_failure": self.base_failure.payload(),
            "base_failure_external_sha256": self.base_failure_external_sha256,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "preflight": dict(self.preflight),
            "sustained_cohort_epochs": SUSTAINED_COHORT_EPOCHS,
            "sustained_arms": [arm.payload() for arm in sorted(
                self.sustained_arms, key=lambda value: value.variant)],
            "selections": [row.payload() for row in self.selections],
            "composed": self.composed.payload(),
            "tiers": [tier.__dict__ for tier in sorted(
                self.tiers, key=lambda value: value.tier)],
            "command_wall_seconds": self.command_wall_seconds,
            "command_wall_nanoseconds": self.command_wall_nanoseconds,
            "fresh_free_disk_bytes": self.fresh_free_disk_bytes,
            "task_count": self.task_count,
            "peak_task_count": self.peak_task_count,
            "host_logical_cpus": self.host_logical_cpus,
            "memory_limit_bytes": self.memory_limit_bytes,
            "swap_bytes": self.swap_bytes,
            "all_core_gate_passed": self.all_core_gate_passed,
            "progress_recovery": self.progress_recovery.payload(),
            "authority": dict(self.authority),
        }
        return {**body, "capacity_recovery_sha256": _sha(body)}


def reopen_capacity_recovery_receipt_v2(
        payload: Mapping[str, Any]) -> CapacityRecoveryReceiptV2:
    required = {
        "schema", "base_source_git", "base_failure",
        "base_failure_external_sha256", "source_sha256", "runtime_sha256",
        "preflight", "sustained_cohort_epochs", "sustained_arms",
        "selections", "composed", "tiers", "command_wall_seconds",
        "command_wall_nanoseconds", "fresh_free_disk_bytes",
        "task_count", "peak_task_count", "host_logical_cpus",
        "memory_limit_bytes", "swap_bytes", "all_core_gate_passed",
        "progress_recovery", "authority", "capacity_recovery_sha256",
    }
    if (type(payload) is not dict or set(payload) != required
            or payload["schema"] != RECOVERY_SCHEMA
            or payload["base_source_git"] != BASE_SOURCE_GIT
            or payload["sustained_cohort_epochs"] != SUSTAINED_COHORT_EPOCHS
            or payload["authority"] != AUTHORITY):
        raise CapacityRecoveryError("capacity recovery schema drift")
    body = {key: value for key, value in payload.items()
            if key != "capacity_recovery_sha256"}
    if payload["capacity_recovery_sha256"] != _sha(body):
        raise CapacityRecoveryError("capacity recovery reconstruction drift")
    from .world_afterstate_v2_capacity import ProgressRecoveryV2
    progress_fields = {key: value for key, value in payload["progress_recovery"].items()
                       if key != "schema"}
    composed_payload = dict(payload["composed"])
    for key in (
            "stage_walls_seconds", "stage_unit_counts",
            "arm_target_unit_counts", "measured_stage_walls_seconds",
            "stage_cpu_seconds", "measured_stage_cpu_seconds",
            "measured_stage_wall_nanoseconds",
            "measured_stage_cpu_nanoseconds", "scientific_dag_edges",
            "dag_edges", "capacity_stage_to_production_stage"):
        composed_payload[key] = tuple(
            tuple(row) for row in composed_payload.get(key, ()))
    receipt = CapacityRecoveryReceiptV2(
        base_failure=reopen_capacity_failure_receipt_v2(payload["base_failure"]),
        base_failure_external_sha256=payload["base_failure_external_sha256"],
        source_sha256=payload["source_sha256"],
        runtime_sha256=payload["runtime_sha256"], preflight=payload["preflight"],
        sustained_arms=tuple(CapacityArmV2(**row)
                             for row in payload["sustained_arms"]),
        selections=tuple(CapacitySelectionV2.reopen(row)
                         for row in payload["selections"]),
        composed=ComposedProjectionV2(**composed_payload),
        tiers=tuple(TierProjectionV2(**row) for row in payload["tiers"]),
        command_wall_seconds=payload["command_wall_seconds"],
        command_wall_nanoseconds=payload["command_wall_nanoseconds"],
        fresh_free_disk_bytes=payload["fresh_free_disk_bytes"],
        task_count=payload["task_count"],
        peak_task_count=payload["peak_task_count"],
        host_logical_cpus=payload["host_logical_cpus"],
        memory_limit_bytes=payload["memory_limit_bytes"],
        swap_bytes=payload["swap_bytes"],
        all_core_gate_passed=payload["all_core_gate_passed"],
        authority=payload["authority"],
        progress_recovery=ProgressRecoveryV2(**progress_fields))
    receipt.validate()
    if receipt.payload() != payload:
        raise CapacityRecoveryError("capacity recovery canonical drift")
    return receipt


def reopen_capacity_recovery_receipt_v2_bytes(raw: bytes) \
        -> CapacityRecoveryReceiptV2:
    if type(raw) is not bytes:
        raise CapacityRecoveryError("capacity recovery bytes drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityRecoveryError("capacity recovery is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise CapacityRecoveryError("capacity recovery is not canonical JSON")
    return reopen_capacity_recovery_receipt_v2(payload)


def reopen_capacity_evidence_v2_bytes(raw: bytes):
    """Reopen either a legacy complete receipt or a composite recovery."""
    if type(raw) is not bytes:
        raise CapacityRecoveryError("capacity evidence bytes drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityRecoveryError("capacity evidence is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise CapacityRecoveryError("capacity evidence is not canonical JSON")
    if payload.get("schema") == RECOVERY_SCHEMA:
        return reopen_capacity_recovery_receipt_v2(payload)
    from .world_afterstate_v2_capacity_runner import reopen_capacity_receipt_v2
    return reopen_capacity_receipt_v2(payload)


def _publish_exclusive(path: Path | str, raw: bytes) -> None:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise CapacityRecoveryError("capacity recovery output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.partial"
    if temporary.exists() or temporary.is_symlink():
        raise CapacityRecoveryError("capacity recovery partial already exists")
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        __import__("os").fsync(handle.fileno())
    temporary.chmod(0o400)
    temporary.replace(target)
    directory = __import__("os").open(target.parent, __import__("os").O_RDONLY)
    try:
        __import__("os").fsync(directory)
    finally:
        __import__("os").close(directory)


def publish_capacity_recovery_receipt_v2(
        path: Path | str, receipt: CapacityRecoveryReceiptV2) -> None:
    _publish_exclusive(path, canonical_json_bytes(receipt.payload()))


def publish_capacity_recovery_failure_v2(
        path: Path | str, receipt: CapacityRecoveryFailureV2) -> None:
    _publish_exclusive(path, canonical_json_bytes(receipt.payload()))


def build_capacity_recovery_receipt_v2(
        *, base_failure_raw: bytes, source_sha256: str, runtime_sha256: str,
        preflight: Any, sustained_arms: Sequence[CapacityArmV2], host: Any,
        elapsed_nanoseconds: int, fresh_free_disk_bytes: int
        ) -> CapacityRecoveryReceiptV2:
    """Build one composite from exact old DAG evidence and fresh arm evidence."""
    if _sha_bytes(base_failure_raw) != BASE_FAILURE_EXTERNAL_SHA256:
        raise CapacityRecoveryError("capacity recovery base bytes drift")
    try:
        base_payload = json.loads(base_failure_raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityRecoveryError("capacity recovery base is not JSON") from exc
    if canonical_json_bytes(base_payload) != base_failure_raw:
        raise CapacityRecoveryError("capacity recovery base is not canonical")
    base = reopen_capacity_failure_receipt_v2(base_payload)
    diagnostic = base.projection_diagnostic
    if diagnostic is None:
        raise CapacityRecoveryError("capacity recovery projection missing")
    preflight.validate()
    host.validate()
    _integer(elapsed_nanoseconds,
             "capacity recovery elapsed nanoseconds", minimum=1)
    _integer(fresh_free_disk_bytes,
             "capacity recovery fresh free disk", minimum=1)
    arms = tuple(sustained_arms)
    for arm in arms:
        arm.validate()
    eligible = tuple(arm for arm in arms if arm.peak_memory_bytes * 100
                     <= MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX)
    selected = min(eligible, key=lambda arm: (arm.wall_ns, arm.variant),
                   default=None)
    if selected is None:
        raise CapacityRecoveryError("capacity recovery has no eligible arm")
    dag_edges = composed_dag_edges_for_cohort_workers(selected.variant)
    composed = ComposedProjectionV2(
        stage_walls_seconds=diagnostic.stage_walls_seconds,
        composed_wall_seconds=composed_critical_path_seconds(
            dict(diagnostic.stage_walls_seconds), dag_edges),
        peak_memory_bytes=max(
            diagnostic.peak_memory_bytes,
            *(arm.peak_memory_bytes for arm in arms)),
        composed_artifact_bytes=diagnostic.composed_artifact_bytes,
        free_disk_bytes_before=min(
            diagnostic.free_disk_bytes_before, fresh_free_disk_bytes),
        stage_unit_counts=diagnostic.stage_unit_counts,
        measured_stage_walls_seconds=tuple(
            (name, max(1, (value + 999_999_999) // 1_000_000_000))
            for name, value in diagnostic.measured_stage_wall_nanoseconds),
        stage_cpu_seconds=diagnostic.stage_cpu_seconds,
        measured_stage_cpu_seconds=tuple(
            (name, max(1, (value + 999_999_999) // 1_000_000_000))
            for name, value in diagnostic.measured_stage_cpu_nanoseconds),
        measured_stage_wall_nanoseconds=
            diagnostic.measured_stage_wall_nanoseconds,
        measured_stage_cpu_nanoseconds=
            diagnostic.measured_stage_cpu_nanoseconds,
        cohort_workers=selected.variant, dag_edges=dag_edges)
    # Validates every unchanged cap before any composite can be serialized.
    composed.validate()
    from .world_afterstate_v2_capacity_runner import _tiers
    tiers = tuple(sorted(_tiers(
        composed,
        preflight_wall_nanoseconds=preflight.elapsed_wall_nanoseconds),
        key=lambda value: value.tier))
    base_assessments = {row.category: row for row in base.assessments}
    sustained_evidence = _sha([arm.payload() for arm in sorted(
        arms, key=lambda value: value.variant)])
    selections = tuple(CapacitySelectionV2(
        stage=stage,
        variant=(selected.variant if stage == "cohort-concurrency"
                 else base_assessments[stage].selected_variant),
        evidence_sha256=(sustained_evidence
                         if stage == "cohort-concurrency"
                         else BASE_FAILURE_RECEIPT_SHA256))
                       for stage in ARM_GRIDS)
    receipt = CapacityRecoveryReceiptV2(
        base_failure=base,
        base_failure_external_sha256=BASE_FAILURE_EXTERNAL_SHA256,
        source_sha256=source_sha256, runtime_sha256=runtime_sha256,
        preflight=preflight.payload(), sustained_arms=arms,
        selections=selections, composed=composed, tiers=tiers,
        command_wall_seconds=(elapsed_nanoseconds + 999_999_999)
            // 1_000_000_000,
        command_wall_nanoseconds=elapsed_nanoseconds,
        fresh_free_disk_bytes=fresh_free_disk_bytes,
        task_count=max(host.task_count,
                       *(arm.task_count for arm in arms)),
        peak_task_count=max(host.task_count,
                            *(arm.peak_task_count or arm.task_count
                              for arm in arms)))
    if elapsed_nanoseconds > RECOVERY_COMMAND_WALL_SECONDS * 1_000_000_000:
        raise CapacityRecoveryError("capacity recovery command wall expired")
    receipt.validate()
    return receipt


def run_capacity_recovery_v2(
        *, base_failure_raw: bytes, source_sha256: str, runtime_sha256: str,
        progress: Callable[[dict[str, Any]], None] | None = None
        ) -> CapacityRecoveryReceiptV2:
    """Run fresh preflight and only the sustained production cohort arms."""
    _digest(source_sha256, "capacity recovery source")
    _digest(runtime_sha256, "capacity recovery runtime")
    if _sha_bytes(base_failure_raw) != BASE_FAILURE_EXTERNAL_SHA256:
        raise CapacityRecoveryError("capacity recovery base bytes drift")
    from .world_afterstate_v2_capacity_runner import (
        RealMeasurementBackendV2, _arm_from_raw,
        _combine_capacity_repeats, _run_cohort_concurrency_benchmark,
        observe_host, run_score_free_preflight)
    started = time.perf_counter_ns()
    deadline = started + RECOVERY_COMMAND_WALL_SECONDS * 1_000_000_000
    preflight = run_score_free_preflight(
        deadline_ns=deadline, progress=progress, started_ns=started)
    host = observe_host()
    backend = RealMeasurementBackendV2(deadline_ns=deadline, progress=progress)
    fixtures = preflight.accepted_fixtures
    fixture = fixtures[0]
    warm: dict[int, Any] = {}
    warm_units: dict[int, int] = {}
    identity: str | None = None
    free_disk_samples = [host.free_disk_bytes]

    def operation(variant: int, units: dict[int, int]):
        def run() -> str:
            identity_value, unit_count = _run_cohort_concurrency_benchmark(
                fixtures, variant, max_epochs=SUSTAINED_COHORT_EPOCHS,
                report_units=True)
            units[variant] = unit_count
            return identity_value
        return run

    for position, variant in enumerate(RECOVERY_COHORT_VARIANTS, 1):
        measured_units: dict[int, int] = {}
        raw = backend.measure(
            "cohort-recovery-warm", variant, fixture,
            operation(variant, measured_units))
        raw.validate()
        if set(measured_units) != {variant}:
            raise CapacityRecoveryError("capacity recovery warm unit drift")
        warm[variant] = raw
        warm_units[variant] = measured_units[variant]
        free_disk_samples.extend(raw.sample_free_disk_bytes)
        if identity is None:
            identity = raw.byte_identity_sha256
        elif raw.byte_identity_sha256 != identity:
            raise CapacityRecoveryError("capacity recovery warm byte drift")
        if progress is not None:
            progress({
                "stage": "cohort-recovery-warm", "completed_units": position,
                "total_units": len(RECOVERY_COHORT_VARIANTS),
                "workers": variant,
                "utilization_ppm": raw.process_cpu_ns * 1_000_000
                // (raw.elapsed_ns * CAPACITY_HOST_LOGICAL_CPUS),
                "elapsed_seconds": (time.perf_counter_ns() - started)
                // 1_000_000_000,
                "eta_seconds": 0,
                "headroom_seconds": max(
                    0, RECOVERY_COMMAND_WALL_SECONDS
                    - (time.perf_counter_ns() - started) // 1_000_000_000),
                "memory_bytes": raw.peak_rss_bytes,
                "peak_memory_bytes": raw.peak_rss_bytes,
                "queue_depth": raw.queue_depth,
                "disk_free_bytes": min(
                    raw.sample_free_disk_bytes or (host.free_disk_bytes,)),
                "immutable_shards": 0, "checkpoint_count": 16,
            })
    if identity is None:
        raise CapacityRecoveryError("capacity recovery identity missing")
    arms = []
    for position, variant in enumerate(reversed(RECOVERY_COHORT_VARIANTS), 1):
        measured_units = {}
        measured = backend.measure(
            "cohort-recovery", variant, fixture,
            operation(variant, measured_units))
        if (set(measured_units) != {variant}
                or measured_units[variant] != warm_units[variant]):
            raise CapacityRecoveryError("capacity recovery measured unit drift")
        combined = _combine_capacity_repeats(warm[variant], measured)
        free_disk_samples.extend(measured.sample_free_disk_bytes)
        if combined.byte_identity_sha256 != identity:
            raise CapacityRecoveryError("capacity recovery measured byte drift")
        arm = _arm_from_raw(
            "cohort-concurrency", variant, combined, identity,
            combined.elapsed_ns,
            measured_unit_count=warm_units[variant] * 2)
        arms.append(arm)
        if progress is not None:
            progress({
                "stage": "cohort-recovery", "completed_units": position,
                "total_units": len(RECOVERY_COHORT_VARIANTS),
                "workers": variant,
                "utilization_ppm": arm.mean_cpu_utilization_ppm,
                "elapsed_seconds": (time.perf_counter_ns() - started)
                // 1_000_000_000,
                "eta_seconds": 0,
                "headroom_seconds": max(
                    0, RECOVERY_COMMAND_WALL_SECONDS
                    - (time.perf_counter_ns() - started) // 1_000_000_000),
                "memory_bytes": arm.peak_memory_bytes,
                "peak_memory_bytes": arm.peak_memory_bytes,
                "queue_depth": arm.queue_depth,
                "disk_free_bytes": host.free_disk_bytes,
                "immutable_shards": 0, "checkpoint_count": 16,
            })
    elapsed = time.perf_counter_ns() - started
    return build_capacity_recovery_receipt_v2(
        base_failure_raw=base_failure_raw, source_sha256=source_sha256,
        runtime_sha256=runtime_sha256, preflight=preflight,
        sustained_arms=tuple(arms), host=host,
        elapsed_nanoseconds=elapsed,
        fresh_free_disk_bytes=min(free_disk_samples))


__all__ = [
    "BASE_FAILURE_EXTERNAL_SHA256", "BASE_FAILURE_RECEIPT_SHA256",
    "BASE_SOURCE_GIT", "CapacityRecoveryError", "CapacityRecoveryFailureV2",
    "CapacityRecoveryReceiptV2",
    "CapacitySelectionV2", "RECOVERY_COMMAND_WALL_SECONDS",
    "RECOVERY_SCHEMA", "SUSTAINED_COHORT_EPOCHS",
    "publish_capacity_recovery_receipt_v2",
    "publish_capacity_recovery_failure_v2",
    "build_capacity_recovery_receipt_v2", "run_capacity_recovery_v2",
    "reopen_capacity_evidence_v2_bytes",
    "reopen_capacity_recovery_receipt_v2",
    "reopen_capacity_recovery_receipt_v2_bytes",
    "reopen_capacity_recovery_failure_v2",
    "reopen_capacity_recovery_failure_v2_bytes",
]
