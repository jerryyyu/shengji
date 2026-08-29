"""Score-free post-implementation capacity contract for Value-Afterstate V2.

This module is a typed receipt/validator only.  It performs no measurement,
filesystem work, process execution, label opening, or tier selection from
outcomes.  Tier selection is delegated to the existing protocol function
after the richer receipt has been authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_protocol import (
    CAPACITY_HOST_LOGICAL_CPUS,
    CapacityTierReceiptV2,
    COMPLETE_DAG_WALL_SECONDS_MAX,
    DISK_RETAIN_PERCENT_MIN,
    MEMORY_PERCENT_MAX,
    SCIENTIFIC_SERVICE_SECONDS,
    TIER_SPECS,
    WorldAfterstateV2ProtocolError,
    choose_capacity_tier,
)


SCHEMA = "world-afterstate-v2-post-implementation-capacity-v1"
ARM_SCHEMA = "world-afterstate-v2-capacity-arm-v1"
PROJECTION_SCHEMA = "world-afterstate-v2-composed-projection-v1"
PROGRESS_SCHEMA = "world-afterstate-v2-progress-recovery-v1"
MAX_COMMAND_WALL_SECONDS = 2 * 60 * 60
MEMORY_LIMIT_BYTES = 30 * 1024**3
MAX_TASKS = 4_096
ZERO_SWAP_BYTES = 0
MIN_FREE_DISK_HEADROOM_PPM = DISK_RETAIN_PERCENT_MIN * 10_000
MIN_CPU_UTILIZATION_PPM = 850_000
MIN_WALL_SHARE_PPM = 50_000

ARM_GRIDS: dict[str, tuple[int, ...]] = {
    "state-successor": (1, 2, 4, 8, 16),
    "continuation-mechanics": (1, 2, 4, 8, 12, 16),
    "member-concurrency": (1, 2, 4),
    "torch-threads-per-member": (1, 2, 4),
    "inference-batch": (32, 64, 128, 256),
    "reconstruction": (1, 4, 8, 16),
}
ARM_DIMENSIONS = {
    "state-successor": "workers",
    "continuation-mechanics": "workers",
    "member-concurrency": "members",
    "torch-threads-per-member": "torch_threads",
    "inference-batch": "batch_size",
    "reconstruction": "workers",
}
COMPOSED_STAGE_NAMES = (
    "optimizer-canary", "nested-curve-25", "nested-curve-50",
    "nested-curve-100", "p0", "label",
    "block-1-natural", "block-1-action-association-permutation",
    "block-1-label-permutation", "block-1-complete-world-shuffle",
    "block-2-natural", "block-2-complete-world-shuffle",
    "precision-select-inference", "precision-select", "audit",
    "reconstruction",
)
AUTHORITY = {
    "capacity_execution_authorized": False,
    "data_collection_authorized": False,
    "dataset_opening_authorized": False,
    "label_opening_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "outcomes_opened": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2CapacityError(ValueError):
    """A post-implementation capacity receipt violated its frozen contract."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2CapacityError(f"{label} drift")
    return value


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2CapacityError(f"{label} drift")
    return value


def _ppm(value: object, label: str, *, maximum: int = 1_000_000) -> int:
    _int(value, label)
    if value > maximum:
        raise WorldAfterstateV2CapacityError(f"{label} drift")
    return value


@dataclass(frozen=True)
class CapacityArmV2:
    """One measured member of a frozen stage arm grid."""

    stage: str
    variant: int
    wall_seconds: int
    busy_core_seconds: int
    mean_cpu_utilization_ppm: int
    p50_cpu_utilization_ppm: int
    p95_cpu_utilization_ppm: int
    scaling_efficiency_ppm: int
    queue_depth: int
    wall_share_ppm: int
    peak_memory_bytes: int
    swap_bytes: int
    task_count: int
    byte_identity_sha256: str
    cpu_bound: bool
    schema: str = ARM_SCHEMA
    # Nanoseconds are retained for arm selection; wall_seconds is the frozen
    # receipt display unit and therefore must not decide subsecond ties.
    wall_nanoseconds: int = 0
    peak_task_count: int = 0

    def validate(self) -> None:
        if self.schema != ARM_SCHEMA or self.stage not in ARM_GRIDS \
                or self.variant not in ARM_GRIDS[self.stage] \
                or type(self.cpu_bound) is not bool:
            raise WorldAfterstateV2CapacityError("capacity arm identity drift")
        for value, label in (
                (self.wall_seconds, "arm wall"),
                (self.busy_core_seconds, "arm busy core seconds"),
                (self.queue_depth, "arm queue depth"),
                (self.peak_memory_bytes, "arm peak memory"),
                (self.task_count, "arm task count")):
            _int(value, label)
        _int(self.wall_nanoseconds, "arm wall nanoseconds")
        _int(self.peak_task_count, "arm peak task count")
        for value, label in (
                (self.mean_cpu_utilization_ppm, "arm mean utilization"),
                (self.p50_cpu_utilization_ppm, "arm p50 utilization"),
                (self.p95_cpu_utilization_ppm, "arm p95 utilization"),
                (self.scaling_efficiency_ppm, "arm scaling efficiency"),
                (self.wall_share_ppm, "arm wall share")):
            _ppm(value, label)
        _int(self.swap_bytes, "arm swap bytes")
        if self.wall_seconds < 1 or self.wall_seconds > MAX_COMMAND_WALL_SECONDS \
                or self.busy_core_seconds < 1 \
                or self.peak_memory_bytes < 1 \
                or self.task_count < 1 or self.task_count > MAX_TASKS \
                or self.swap_bytes != ZERO_SWAP_BYTES \
                or self.peak_memory_bytes > MEMORY_LIMIT_BYTES:
            raise WorldAfterstateV2CapacityError("capacity arm resource cap drift")
        _digest(self.byte_identity_sha256, "arm byte identity SHA-256")
        if self.p50_cpu_utilization_ppm > self.p95_cpu_utilization_ppm:
            raise WorldAfterstateV2CapacityError("arm utilization quantile drift")
        if self.busy_core_seconds > self.wall_seconds * CAPACITY_HOST_LOGICAL_CPUS:
            raise WorldAfterstateV2CapacityError("arm busy-core bound drift")
        implied = self.busy_core_seconds * 1_000_000 \
            // (self.wall_seconds * CAPACITY_HOST_LOGICAL_CPUS)
        tolerance = 1_000_000 \
            // (self.wall_seconds * CAPACITY_HOST_LOGICAL_CPUS) + 1
        if abs(self.mean_cpu_utilization_ppm - implied) > tolerance:
            raise WorldAfterstateV2CapacityError(
                "arm busy-core/utilization binding drift")
        if self.wall_nanoseconds and self.wall_nanoseconds < 1_000_000:
            raise WorldAfterstateV2CapacityError("arm wall nanoseconds drift")
        if self.peak_task_count and self.peak_task_count < self.task_count:
            raise WorldAfterstateV2CapacityError("arm peak task count drift")

    @property
    def dimension(self) -> str:
        self.validate()
        return ARM_DIMENSIONS[self.stage]

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema, "stage": self.stage,
            "variant": self.variant, "wall_seconds": self.wall_seconds,
            "busy_core_seconds": self.busy_core_seconds,
            "mean_cpu_utilization_ppm": self.mean_cpu_utilization_ppm,
            "p50_cpu_utilization_ppm": self.p50_cpu_utilization_ppm,
            "p95_cpu_utilization_ppm": self.p95_cpu_utilization_ppm,
            "scaling_efficiency_ppm": self.scaling_efficiency_ppm,
            "queue_depth": self.queue_depth,
            "wall_share_ppm": self.wall_share_ppm,
            "peak_memory_bytes": self.peak_memory_bytes,
            "swap_bytes": self.swap_bytes, "task_count": self.task_count,
            "byte_identity_sha256": self.byte_identity_sha256,
            "cpu_bound": self.cpu_bound,
            "wall_nanoseconds": self.wall_nanoseconds,
            "peak_task_count": self.peak_task_count,
        }


@dataclass(frozen=True)
class ComposedProjectionV2:
    """The complete pre-freeze scientific DAG wall/resource projection."""

    stage_walls_seconds: tuple[tuple[str, int], ...]
    composed_wall_seconds: int
    peak_memory_bytes: int
    composed_artifact_bytes: int
    free_disk_bytes_before: int
    schema: str = PROJECTION_SCHEMA

    def validate(self) -> None:
        if self.schema != PROJECTION_SCHEMA or type(self.stage_walls_seconds) is not tuple:
            raise WorldAfterstateV2CapacityError("composed projection schema drift")
        names = [name for name, _ in self.stage_walls_seconds]
        if tuple(names) != COMPOSED_STAGE_NAMES or len(set(names)) != len(names):
            raise WorldAfterstateV2CapacityError("composed stage grid drift")
        for name, value in self.stage_walls_seconds:
            if type(name) is not str:
                raise WorldAfterstateV2CapacityError("composed stage name drift")
            _int(value, f"{name} wall", minimum=1)
        for value, label in (
                (self.composed_wall_seconds, "composed wall"),
                (self.peak_memory_bytes, "composed peak memory"),
                (self.composed_artifact_bytes, "composed artifact bytes"),
                (self.free_disk_bytes_before, "composed free disk")):
            _int(value, label, minimum=1)
        if self.composed_wall_seconds != sum(value for _, value in self.stage_walls_seconds) \
                or self.composed_wall_seconds > COMPLETE_DAG_WALL_SECONDS_MAX \
                or self.composed_wall_seconds * 2 > SCIENTIFIC_SERVICE_SECONDS \
                or self.peak_memory_bytes * 100 > MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX \
                or self.composed_artifact_bytes * 100 \
                > self.free_disk_bytes_before * (100 - DISK_RETAIN_PERCENT_MIN):
            raise WorldAfterstateV2CapacityError("composed projection cap drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "stage_walls_seconds": [[name, value]
                                     for name, value in self.stage_walls_seconds],
            "composed_wall_seconds": self.composed_wall_seconds,
            "peak_memory_bytes": self.peak_memory_bytes,
            "composed_artifact_bytes": self.composed_artifact_bytes,
            "free_disk_bytes_before": self.free_disk_bytes_before,
        }


@dataclass(frozen=True)
class ProgressRecoveryV2:
    """Declared progress cadence and safe shard/checkpoint recovery behavior."""

    progress_interval_seconds: int
    progress_interval_fraction_ppm: int
    reports_stage_counts: bool
    reports_active_workers_and_cpu: bool
    reports_elapsed_eta_headroom: bool
    reports_current_peak_cgroup_memory: bool
    reports_immutable_shard_checkpoint_count: bool
    resumes_verified_shards_only: bool
    resume_same_admission: bool
    resume_cannot_regenerate_replace_select: bool
    checkpoints_each_common_epoch: bool
    deadline_truncation_keeps_complete_epoch: bool
    audit_requires_complete_upstream: bool
    audit_attempt_fsynced_before_open: bool
    one_audit_open: bool
    reconstruction_without_retraining: bool
    reconstruction_reuses_immutable_continuations: bool
    schema: str = PROGRESS_SCHEMA

    def validate(self) -> None:
        if self.schema != PROGRESS_SCHEMA:
            raise WorldAfterstateV2CapacityError("progress schema drift")
        _int(self.progress_interval_seconds, "progress interval", minimum=1)
        _ppm(self.progress_interval_fraction_ppm, "progress fraction")
        if self.progress_interval_seconds > 60 \
                or self.progress_interval_fraction_ppm > 10_000:
            raise WorldAfterstateV2CapacityError("progress cadence drift")
        flags = (
            self.reports_stage_counts, self.reports_active_workers_and_cpu,
            self.reports_elapsed_eta_headroom,
            self.reports_current_peak_cgroup_memory,
            self.reports_immutable_shard_checkpoint_count,
            self.resumes_verified_shards_only, self.resume_same_admission,
            self.resume_cannot_regenerate_replace_select,
            self.checkpoints_each_common_epoch,
            self.deadline_truncation_keeps_complete_epoch,
            self.audit_requires_complete_upstream,
            self.audit_attempt_fsynced_before_open,
            self.one_audit_open,
            self.reconstruction_without_retraining,
            self.reconstruction_reuses_immutable_continuations)
        if any(type(value) is not bool for value in flags):
            raise WorldAfterstateV2CapacityError("progress/recovery capability drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {key: value for key, value in self.__dict__.items()
                if key != "schema"} | {"schema": self.schema}


@dataclass(frozen=True)
class TierProjectionV2:
    tier: str
    exact_source_supply: bool
    label_wall_seconds: int
    label_cpu_seconds: int
    complete_dag_wall_seconds: int
    peak_memory_bytes: int
    composed_artifact_bytes: int
    free_disk_bytes_before: int
    byte_identical: bool = True
    outcomes_opened: bool = False

    def validate(self) -> None:
        if self.tier not in {tier.name for tier in TIER_SPECS} \
                or type(self.exact_source_supply) is not bool \
                or type(self.byte_identical) is not bool \
                or type(self.outcomes_opened) is not bool:
            raise WorldAfterstateV2CapacityError("tier projection identity drift")
        for value, label in (
                (self.label_wall_seconds, "tier label wall"),
                (self.label_cpu_seconds, "tier label CPU"),
                (self.complete_dag_wall_seconds, "tier DAG wall"),
                (self.peak_memory_bytes, "tier peak memory"),
                (self.composed_artifact_bytes, "tier artifact bytes"),
                (self.free_disk_bytes_before, "tier free disk")):
            _int(value, label, minimum=1)


@dataclass(frozen=True)
class CapacityReceiptV2:
    """Complete score-free capacity receipt, including every measured arm."""

    host_logical_cpus: int
    command_wall_seconds: int
    memory_limit_bytes: int
    swap_bytes: int
    task_count: int
    arms: tuple[CapacityArmV2, ...]
    selected_arms: tuple[CapacityArmV2, ...]
    composed: ComposedProjectionV2
    tiers: tuple[TierProjectionV2, ...]
    progress_recovery: ProgressRecoveryV2
    schema: str = SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    # These fields are populated by the post-implementation runner.  Defaults
    # preserve reopening of older typed test fixtures while production runner
    # validation rejects an unpopulated receipt.
    model_parameter_count: int = 0
    candidate_distribution: tuple[tuple[int, int], ...] = ()
    per_epoch_wall_seconds: int = 0
    peak_task_count: int = 0

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY \
                or self.host_logical_cpus != CAPACITY_HOST_LOGICAL_CPUS \
                or self.memory_limit_bytes != MEMORY_LIMIT_BYTES \
                or self.swap_bytes != ZERO_SWAP_BYTES:
            raise WorldAfterstateV2CapacityError("capacity receipt identity drift")
        _int(self.command_wall_seconds, "command wall", minimum=1)
        _int(self.task_count, "command task count", minimum=1)
        if self.command_wall_seconds > MAX_COMMAND_WALL_SECONDS \
                or self.task_count > MAX_TASKS:
            raise WorldAfterstateV2CapacityError("capacity command cap drift")
        if type(self.arms) is not tuple or type(self.selected_arms) is not tuple \
                or type(self.tiers) is not tuple \
                or len(self.tiers) != len(TIER_SPECS) \
                or type(self.progress_recovery) is not ProgressRecoveryV2:
            raise WorldAfterstateV2CapacityError("capacity receipt population drift")
        for arm in self.arms:
            arm.validate()
        expected_grid = {(stage, variant) for stage, variants in ARM_GRIDS.items()
                         for variant in variants}
        actual_grid = {(arm.stage, arm.variant) for arm in self.arms}
        if actual_grid != expected_grid or len(actual_grid) != len(self.arms):
            raise WorldAfterstateV2CapacityError("capacity arm grid drift")
        if self.command_wall_seconds < sum(arm.wall_seconds for arm in self.arms) \
                or self.task_count != sum(arm.task_count for arm in self.arms):
            raise WorldAfterstateV2CapacityError(
                "capacity command/arm accounting drift")
        _int(self.model_parameter_count, "model parameter count")
        _int(self.per_epoch_wall_seconds, "per-epoch wall seconds")
        _int(self.peak_task_count, "peak task count")
        if self.peak_task_count and self.peak_task_count > MAX_TASKS:
            raise WorldAfterstateV2CapacityError("peak task cap drift")
        if type(self.candidate_distribution) is not tuple:
            raise WorldAfterstateV2CapacityError("candidate distribution drift")
        for row in self.candidate_distribution:
            if type(row) is not tuple or len(row) != 2:
                raise WorldAfterstateV2CapacityError("candidate distribution drift")
            _int(row[0], "candidate count", minimum=2)
            _int(row[1], "candidate frequency", minimum=1)
        for stage in ARM_GRIDS:
            stage_arms = [arm for arm in self.arms if arm.stage == stage]
            if len({arm.byte_identity_sha256 for arm in stage_arms}) != 1:
                raise WorldAfterstateV2CapacityError(
                    "stage arms are not byte-identical")
            eligible = [arm for arm in stage_arms
                        if arm.peak_memory_bytes * 100
                        <= MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX]
            if not eligible:
                raise WorldAfterstateV2CapacityError("no memory-eligible arm")
            fastest = min(eligible, key=lambda arm: (arm.wall_seconds, arm.variant))
            chosen = [arm for arm in self.selected_arms if arm.stage == stage]
            if len(chosen) != 1 or chosen[0] != fastest:
                raise WorldAfterstateV2CapacityError(
                    "selected arm is not fastest eligible byte-identical arm")
            if fastest.cpu_bound and fastest.wall_share_ppm >= MIN_WALL_SHARE_PPM \
                    and fastest.mean_cpu_utilization_ppm < MIN_CPU_UTILIZATION_PPM:
                next_arms = [arm for arm in stage_arms if arm.variant > fastest.variant]
                if not next_arms or not any(
                        arm.byte_identity_sha256 == fastest.byte_identity_sha256
                        and arm.wall_seconds > fastest.wall_seconds
                        for arm in next_arms):
                    raise WorldAfterstateV2CapacityError(
                        "CPU-bound stage utilization/next-arm gate drift")
        if len(self.selected_arms) != len(ARM_GRIDS):
            raise WorldAfterstateV2CapacityError("selected arm population drift")
        self.composed.validate()
        self.progress_recovery.validate()
        for tier in self.tiers:
            tier.validate()
        if {tier.tier for tier in self.tiers} != {tier.name for tier in TIER_SPECS}:
            raise WorldAfterstateV2CapacityError("tier projection population drift")
        if any(tier.outcomes_opened for tier in self.tiers):
            raise WorldAfterstateV2CapacityError("capacity outcomes opened")

    def protocol_receipts(self) -> tuple[CapacityTierReceiptV2, ...]:
        self.validate()
        return tuple(CapacityTierReceiptV2(
            tier=tier.tier, host_logical_cpus=self.host_logical_cpus,
            exact_source_supply=tier.exact_source_supply,
            byte_identical=tier.byte_identical,
            outcomes_opened=tier.outcomes_opened,
            all_core_gate_passed=True,
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
        """Select the largest eligible tier through the frozen protocol gate."""
        return choose_capacity_tier(self.protocol_receipts())

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "host_logical_cpus": self.host_logical_cpus,
            "command_wall_seconds": self.command_wall_seconds,
            "memory_limit_bytes": self.memory_limit_bytes,
            "swap_bytes": self.swap_bytes, "task_count": self.task_count,
            "arms": [arm.payload() for arm in sorted(
                self.arms, key=lambda value: (value.stage, value.variant))],
            "selected_arms": [arm.payload() for arm in sorted(
                self.selected_arms, key=lambda value: value.stage)],
            "composed": self.composed.payload(),
            "tiers": [tier.__dict__ for tier in sorted(
                self.tiers, key=lambda value: value.tier)],
            "progress_recovery": self.progress_recovery.payload(),
            "model_parameter_count": self.model_parameter_count,
            "candidate_distribution": [list(row)
                                        for row in self.candidate_distribution],
            "per_epoch_wall_seconds": self.per_epoch_wall_seconds,
            "peak_task_count": self.peak_task_count,
            "authority": dict(self.authority),
        }

    def sha256(self) -> str:
        return _sha(self.payload())


def choose_capacity_tier_v2(receipt: CapacityReceiptV2):
    if type(receipt) is not CapacityReceiptV2:
        raise WorldAfterstateV2CapacityError("capacity receipt type drift")
    try:
        return receipt.choose_tier()
    except WorldAfterstateV2ProtocolError as exc:
        raise WorldAfterstateV2CapacityError("protocol capacity selection refused") from exc


def validate_capacity_receipt_v2(value: CapacityReceiptV2) -> None:
    if type(value) is not CapacityReceiptV2:
        raise WorldAfterstateV2CapacityError("capacity receipt type drift")
    value.validate()


def capacity_receipt_sha256(value: CapacityReceiptV2) -> str:
    validate_capacity_receipt_v2(value)
    return value.sha256()


__all__ = [
    "ARM_GRIDS", "AUTHORITY", "CapacityArmV2", "CapacityReceiptV2",
    "ComposedProjectionV2", "MAX_COMMAND_WALL_SECONDS", "MAX_TASKS",
    "MEMORY_LIMIT_BYTES", "ProgressRecoveryV2", "TierProjectionV2",
    "WorldAfterstateV2CapacityError", "choose_capacity_tier_v2",
    "capacity_receipt_sha256", "validate_capacity_receipt_v2",
]
