"""Score-free post-implementation capacity contract for Value-Afterstate V2.

This module is a typed receipt/validator only.  It performs no measurement,
filesystem work, process execution, label opening, or tier selection from
outcomes.  Tier selection is delegated to the existing protocol function
after the richer receipt has been authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
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


SCHEMA = "world-afterstate-v2-post-implementation-capacity-v3"
FAILURE_SCHEMA = "world-afterstate-v2-post-implementation-capacity-failure-v1"
ARM_SCHEMA = "world-afterstate-v2-capacity-arm-v2"
PROJECTION_SCHEMA = "world-afterstate-v2-composed-projection-v2"
PROGRESS_SCHEMA = "world-afterstate-v2-progress-recovery-v1"
MEASUREMENT_SCOPE = "retained-32-material-sample-projection-v1"
MAX_COMMAND_WALL_SECONDS = 2 * 60 * 60
MEMORY_LIMIT_BYTES = 30 * 1024**3
MAX_TASKS = 4_096
ZERO_SWAP_BYTES = 0
MIN_FREE_DISK_HEADROOM_PPM = DISK_RETAIN_PERCENT_MIN * 10_000
MIN_CPU_UTILIZATION_PPM = 850_000
MIN_WALL_SHARE_PPM = 50_000
PINNED_TORCH_THREADS = 1

ARM_GRIDS: dict[str, tuple[int, ...]] = {
    "state-successor": (1, 2, 4, 8, 16),
    "continuation-mechanics": (1, 2, 4, 8, 12, 16),
    "member-concurrency": (1, 2, 4),
    "inference-batch": (32, 64, 128, 256),
    "reconstruction": (1, 4, 8, 16),
}
ARM_DIMENSIONS = {
    "state-successor": "workers",
    "continuation-mechanics": "workers",
    "member-concurrency": "members",
    "inference-batch": "batch_size",
    "reconstruction": "workers",
}
COMPOSED_STAGE_NAMES = (
    "label-p0", "p0", "optimizer-canary", "label-fit",
    "nested-curve-25", "nested-curve-50", "block-1-natural",
    "nested-curve-100",
    "block-1-action-association-permutation",
    "block-1-label-permutation", "block-1-complete-world-shuffle",
    "block-2-natural", "block-2-complete-world-shuffle",
    "precision-select-inference", "label-precision-select", "precision-select",
    "label-audit", "audit",
    "reconstruction",
)
FAILURE_STAGES = frozenset((*COMPOSED_STAGE_NAMES, "capacity-cli",
                            "preflight", "measurement", "publication",
                            "runner", "full-dag"))
# The executable production supervisor has coarser boundaries than the
# capacity witness.  Keep this relation closed and explicit so every measured
# substage remains attributable when boundaries collapse (notably terminal).
PRODUCTION_STAGE_NAMES = (
    "population", "p0-labels-gates", "optimizer-canary", "fit-select-labels",
    "block-1-natural", "nested-curve", "block-1-controls", "block-2-natural",
    "block-2-controls", "precision-select-power", "audit-attempt", "terminal",
    "reconstruction",
)
CAPACITY_STAGE_TO_PRODUCTION_STAGE = {
    "label-p0": "p0-labels-gates", "p0": "p0-labels-gates",
    "optimizer-canary": "optimizer-canary", "label-fit": "fit-select-labels",
    "nested-curve-25": "nested-curve", "nested-curve-50": "nested-curve",
    "block-1-natural": "block-1-natural", "nested-curve-100": "nested-curve",
    "block-1-action-association-permutation": "block-1-controls",
    "block-1-label-permutation": "block-1-controls",
    "block-1-complete-world-shuffle": "block-1-controls",
    "block-2-natural": "block-2-natural",
    "block-2-complete-world-shuffle": "block-2-controls",
    "precision-select-inference": "precision-select-power",
    "label-precision-select": "precision-select-power",
    "precision-select": "precision-select-power",
    "label-audit": "audit-attempt", "audit": "terminal",
    "reconstruction": "reconstruction",
}
# Population construction is intentionally not charged to a composed DAG
# substage: the dedicated state/successor arms provide that measurement.
CAPACITY_ARM_TO_PRODUCTION_STAGE = {
    "state-successor": "population",
    "continuation-mechanics": "population",
}
CAPACITY_PRODUCTION_STAGE_COVERAGE = frozenset(
    (*CAPACITY_STAGE_TO_PRODUCTION_STAGE.values(),
     *CAPACITY_ARM_TO_PRODUCTION_STAGE.values()))
# Descriptive aliases used by callers that distinguish a capacity substage
# from its production stage.
CAPACITY_SUBSTAGE_TO_PRODUCTION_STAGE = CAPACITY_STAGE_TO_PRODUCTION_STAGE
# Scientific dependencies are recorded explicitly.  Edges are
# (predecessor, successor); their order is wire-stable.
SCIENTIFIC_DAG_EDGES = (
    ("label-p0", "p0"),
    ("p0", "optimizer-canary"),
    ("optimizer-canary", "label-fit"),
    ("label-fit", "block-1-natural"),
    ("label-fit", "block-1-action-association-permutation"),
    ("label-fit", "block-1-label-permutation"),
    ("label-fit", "block-1-complete-world-shuffle"),
    ("label-fit", "block-2-natural"),
    ("label-fit", "block-2-complete-world-shuffle"),
    ("optimizer-canary", "block-1-natural"),
    ("block-1-natural", "nested-curve-100"),
    ("optimizer-canary", "nested-curve-25"),
    ("optimizer-canary", "nested-curve-50"),
    ("optimizer-canary", "block-1-action-association-permutation"),
    ("optimizer-canary", "block-1-label-permutation"),
    ("optimizer-canary", "block-1-complete-world-shuffle"),
    ("optimizer-canary", "block-2-natural"),
    ("optimizer-canary", "block-2-complete-world-shuffle"),
    ("block-1-natural", "precision-select-inference"),
    ("block-1-action-association-permutation", "precision-select-inference"),
    ("block-1-label-permutation", "precision-select-inference"),
    ("block-1-complete-world-shuffle", "precision-select-inference"),
    ("block-2-natural", "precision-select-inference"),
    ("block-2-complete-world-shuffle", "precision-select-inference"),
    ("nested-curve-25", "precision-select-inference"),
    ("nested-curve-50", "precision-select-inference"),
    ("nested-curve-100", "precision-select-inference"),
    ("precision-select-inference", "label-precision-select"),
    ("label-precision-select", "precision-select"),
    ("precision-select", "label-audit"),
    ("label-audit", "audit"),
    ("audit", "reconstruction"),
)
# Separate member-concurrency and torch-thread arms do not prove a joint
# co-scheduled multi-cohort layout.  Until such an arm exists, these resource
# edges conservatively serialize the otherwise independent training cohorts.
TRAINING_RESOURCE_SERIALIZATION_EDGES = (
    ("block-1-natural", "nested-curve-25"),
    ("nested-curve-25", "nested-curve-50"),
    ("nested-curve-50", "nested-curve-100"),
    ("nested-curve-100", "block-1-action-association-permutation"),
    ("block-1-action-association-permutation", "block-1-label-permutation"),
    ("block-1-label-permutation", "block-1-complete-world-shuffle"),
    ("block-1-complete-world-shuffle", "block-2-natural"),
    ("block-2-natural", "block-2-complete-world-shuffle"),
)
COMPOSED_DAG_EDGES = SCIENTIFIC_DAG_EDGES + TRAINING_RESOURCE_SERIALIZATION_EDGES
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


@dataclass(frozen=True)
class CapacityFailureReceiptV2:
    """Bounded, immutable metadata for one refused CLI capacity attempt."""

    stage: str
    reason: str
    elapsed_seconds: int
    source_sha256: str
    input_sha256: str
    namespace_sha256: str
    detail_sha256: str
    deadline_seconds: int = MAX_COMMAND_WALL_SECONDS
    status: str = "failure"
    schema: str = FAILURE_SCHEMA

    def payload(self) -> dict[str, Any]:
        if self.schema != FAILURE_SCHEMA or self.status != "failure":
            raise WorldAfterstateV2CapacityError(
                "capacity failure identity drift")
        digests = (self.source_sha256, self.input_sha256,
                   self.namespace_sha256, self.detail_sha256)
        if (type(self.stage) is not str or self.stage not in FAILURE_STAGES
                or type(self.reason) is not str
                or not 1 <= len(self.reason) <= 64
                or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
                       for char in self.reason)
                or any(type(value) is not str or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value)
                       for value in digests)):
                raise WorldAfterstateV2CapacityError(
                    "capacity failure evidence drift")
        if self.namespace_sha256 != _sha({
                "source_sha256": self.source_sha256,
                "input_sha256": self.input_sha256}):
            raise WorldAfterstateV2CapacityError(
                "capacity failure namespace binding drift")
        if (isinstance(self.elapsed_seconds, bool)
                or not isinstance(self.elapsed_seconds, int)
                or self.elapsed_seconds < 0
                or self.elapsed_seconds > MAX_COMMAND_WALL_SECONDS
                or self.deadline_seconds != MAX_COMMAND_WALL_SECONDS):
            raise WorldAfterstateV2CapacityError(
                "capacity failure deadline drift")
        body = {
            "schema": self.schema, "status": self.status,
            "stage": self.stage, "reason": self.reason,
            "source_sha256": self.source_sha256,
            "input_sha256": self.input_sha256,
            "namespace_sha256": self.namespace_sha256,
            "detail_sha256": self.detail_sha256,
            "elapsed_seconds": self.elapsed_seconds,
            "deadline_seconds": self.deadline_seconds,
            "authority": dict(AUTHORITY),
        }
        return {**body, "failure_receipt_sha256": _sha(body)}


def reopen_capacity_failure_receipt_v2(
        payload: Mapping[str, Any]) -> CapacityFailureReceiptV2:
    """Strictly reconstruct one canonical refusal artifact."""
    required = {"schema", "status", "stage", "reason", "source_sha256",
                "input_sha256", "namespace_sha256", "detail_sha256",
                "elapsed_seconds",
                "deadline_seconds", "authority", "failure_receipt_sha256"}
    if type(payload) is not dict or set(payload) != required \
            or payload.get("authority") != AUTHORITY:
        raise WorldAfterstateV2CapacityError("capacity failure schema drift")
    body = {key: value for key, value in payload.items()
            if key != "failure_receipt_sha256"}
    if payload["failure_receipt_sha256"] != _sha(body):
        raise WorldAfterstateV2CapacityError(
            "capacity failure reconstruction drift")
    receipt = CapacityFailureReceiptV2(
        stage=payload["stage"], reason=payload["reason"],
        elapsed_seconds=payload["elapsed_seconds"],
        source_sha256=payload["source_sha256"],
        input_sha256=payload["input_sha256"],
        namespace_sha256=payload["namespace_sha256"],
        detail_sha256=payload["detail_sha256"],
        deadline_seconds=payload["deadline_seconds"],
        status=payload["status"], schema=payload["schema"])
    if receipt.payload() != payload:
        raise WorldAfterstateV2CapacityError("capacity failure canonical drift")
    return receipt


def validate_capacity_failure_receipt_v2(
        value: CapacityFailureReceiptV2) -> None:
    if type(value) is not CapacityFailureReceiptV2:
        raise WorldAfterstateV2CapacityError(
            "capacity failure receipt type drift")
    value.payload()


def reopen_capacity_failure_receipt_v2_bytes(raw: bytes) -> CapacityFailureReceiptV2:
    if type(raw) is not bytes:
        raise WorldAfterstateV2CapacityError("capacity failure bytes type drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2CapacityError(
            "capacity failure is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise WorldAfterstateV2CapacityError(
            "capacity failure is not canonical JSON")
    return reopen_capacity_failure_receipt_v2(payload)


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


def composed_critical_path_seconds(
        stage_walls_seconds: Mapping[str, int],
        dag_edges: Sequence[tuple[str, str]] = COMPOSED_DAG_EDGES) -> int:
    """Return the longest permitted dependency path through stage walls.

    This deliberately validates the closed DAG rather than silently accepting
    an omitted stage or an accidental cycle.  It is used for both the D256
    projection and every scaled tier projection.
    """
    if set(stage_walls_seconds) != set(COMPOSED_STAGE_NAMES):
        raise WorldAfterstateV2CapacityError("composed stage grid drift")
    if any(type(name) is not str or type(value) is not int or value < 1
           for name, value in stage_walls_seconds.items()):
        raise WorldAfterstateV2CapacityError("composed stage wall drift")
    edges = tuple(dag_edges)
    if edges != COMPOSED_DAG_EDGES:
        raise WorldAfterstateV2CapacityError("composed DAG contract drift")
    children: dict[str, list[str]] = {name: [] for name in COMPOSED_STAGE_NAMES}
    indegree = {name: 0 for name in COMPOSED_STAGE_NAMES}
    for edge in edges:
        if type(edge) is not tuple or len(edge) != 2:
            raise WorldAfterstateV2CapacityError("composed DAG edge drift")
        parent, child = edge
        if parent not in children or child not in children or parent == child:
            raise WorldAfterstateV2CapacityError("composed DAG edge drift")
        children[parent].append(child)
        indegree[child] += 1
    distance = {name: stage_walls_seconds[name] for name in COMPOSED_STAGE_NAMES}
    ready = [name for name in COMPOSED_STAGE_NAMES if indegree[name] == 0]
    visited = 0
    while ready:
        node = ready.pop(0)
        visited += 1
        for child in children[node]:
            distance[child] = max(distance[child],
                                   distance[node] + stage_walls_seconds[child])
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(COMPOSED_STAGE_NAMES):
        raise WorldAfterstateV2CapacityError("composed DAG cycle drift")
    return max(distance.values())


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
    # Retain measured and projected units per stage; fixed-cost and split
    # workloads therefore do not inherit one universal fit/32 multiplier.
    stage_unit_counts: tuple[tuple[str, int, int], ...] = ()
    measured_stage_walls_seconds: tuple[tuple[str, int], ...] = ()
    # CPU is retained independently from wall.  A projected label budget must
    # never be inferred by multiplying wall by host width.
    stage_cpu_seconds: tuple[tuple[str, int], ...] = ()
    measured_stage_cpu_seconds: tuple[tuple[str, int], ...] = ()
    scientific_dag_edges: tuple[tuple[str, str], ...] = SCIENTIFIC_DAG_EDGES
    dag_edges: tuple[tuple[str, str], ...] = COMPOSED_DAG_EDGES
    capacity_stage_to_production_stage: tuple[tuple[str, str], ...] = tuple(
        CAPACITY_STAGE_TO_PRODUCTION_STAGE.items())
    schema: str = PROJECTION_SCHEMA

    def validate(self) -> None:
        if self.schema != PROJECTION_SCHEMA or type(self.stage_walls_seconds) is not tuple:
            raise WorldAfterstateV2CapacityError("composed projection schema drift")
        names = [name for name, _ in self.stage_walls_seconds]
        if tuple(names) != COMPOSED_STAGE_NAMES or len(set(names)) != len(names):
            raise WorldAfterstateV2CapacityError("composed stage grid drift")
        if type(self.stage_unit_counts) is not tuple:
            raise WorldAfterstateV2CapacityError("composed stage unit population drift")
        if self.stage_unit_counts:
            if any(type(row) is not tuple or len(row) != 3
                   for row in self.stage_unit_counts):
                raise WorldAfterstateV2CapacityError("composed stage unit counts drift")
        if type(self.measured_stage_walls_seconds) is not tuple:
            raise WorldAfterstateV2CapacityError("measured stage wall population drift")
        if self.measured_stage_walls_seconds:
            if tuple(row[0] for row in self.measured_stage_walls_seconds) \
                    != COMPOSED_STAGE_NAMES \
                    or any(type(row) is not tuple or len(row) != 2
                           or type(row[1]) is not int or row[1] < 1
                           for row in self.measured_stage_walls_seconds):
                raise WorldAfterstateV2CapacityError("measured stage wall grid drift")
        if self.stage_unit_counts and not self.measured_stage_walls_seconds:
            raise WorldAfterstateV2CapacityError("measured stage walls missing")
        if self.stage_unit_counts and not self.measured_stage_cpu_seconds:
            raise WorldAfterstateV2CapacityError("measured stage CPU missing")
        if self.stage_unit_counts:
            if tuple(row[0] for row in self.stage_unit_counts) != COMPOSED_STAGE_NAMES:
                raise WorldAfterstateV2CapacityError("composed stage unit grid drift")
            if any(type(row) is not tuple or len(row) != 3
                   or type(row[1]) is not int or type(row[2]) is not int
                   or row[1] < 1 or row[2] < 1 for row in self.stage_unit_counts):
                raise WorldAfterstateV2CapacityError("composed stage unit counts drift")
        for rows, label in ((self.stage_cpu_seconds, "composed stage CPU"),
                            (self.measured_stage_cpu_seconds,
                             "measured stage CPU")):
            if type(rows) is not tuple:
                raise WorldAfterstateV2CapacityError(f"{label} population drift")
            if rows and (tuple(row[0] for row in rows) != COMPOSED_STAGE_NAMES
                         or any(type(row) is not tuple or len(row) != 2
                                or type(row[1]) is not int or row[1] < 1
                                for row in rows)):
                raise WorldAfterstateV2CapacityError(f"{label} grid drift")
        if self.stage_unit_counts and (
                tuple(row[0] for row in self.stage_cpu_seconds)
                != COMPOSED_STAGE_NAMES):
            raise WorldAfterstateV2CapacityError("composed stage CPU grid drift")
        if self.scientific_dag_edges != SCIENTIFIC_DAG_EDGES:
            raise WorldAfterstateV2CapacityError("scientific DAG contract drift")
        if (tuple(name for name, _ in self.capacity_stage_to_production_stage)
                != COMPOSED_STAGE_NAMES
                or tuple(stage for _, stage in
                         self.capacity_stage_to_production_stage)
                != tuple(CAPACITY_STAGE_TO_PRODUCTION_STAGE[name]
                         for name in COMPOSED_STAGE_NAMES)
                or set(stage for _, stage in
                       self.capacity_stage_to_production_stage)
                != (set(PRODUCTION_STAGE_NAMES) - {"population"})):
            raise WorldAfterstateV2CapacityError(
                "capacity/production stage mapping drift")
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
        expected_critical_path = composed_critical_path_seconds(
            dict(self.stage_walls_seconds), self.dag_edges)
        if self.composed_wall_seconds != expected_critical_path \
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
            "stage_unit_counts": [list(row) for row in self.stage_unit_counts],
            "measured_stage_walls_seconds": [
                list(row) for row in self.measured_stage_walls_seconds],
            "stage_cpu_seconds": [list(row) for row in self.stage_cpu_seconds],
            "measured_stage_cpu_seconds": [
                list(row) for row in self.measured_stage_cpu_seconds],
            "scientific_dag_edges": [list(row) for row in self.scientific_dag_edges],
            "dag_edges": [list(row) for row in self.dag_edges],
            "capacity_stage_to_production_stage": [
                list(row) for row in self.capacity_stage_to_production_stage],
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
        if not all(flags):
            raise WorldAfterstateV2CapacityError(
                "progress/recovery capabilities are not all proven")

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
    measurement_scope: str = MEASUREMENT_SCOPE
    # Exact production layout selected from the measured byte-identical arms.
    # Zero defaults preserve construction of legacy typed fixtures; production
    # receipts are required to populate and bind these fields.
    member_workers: int = 0
    torch_threads: int = 0
    inference_batch: int = 0

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY \
                or self.host_logical_cpus != CAPACITY_HOST_LOGICAL_CPUS \
                or self.memory_limit_bytes != MEMORY_LIMIT_BYTES \
                or self.swap_bytes != ZERO_SWAP_BYTES:
            raise WorldAfterstateV2CapacityError("capacity receipt identity drift")
        if self.measurement_scope != MEASUREMENT_SCOPE:
            raise WorldAfterstateV2CapacityError("capacity measurement scope drift")
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
        arm_peak_tasks = max((arm.peak_task_count or arm.task_count)
                             for arm in self.arms)
        # New receipts bind command task_count to simultaneous peak telemetry.
        # The zero-valued field remains accepted for old typed fixtures, whose
        # legacy accounting was the sum of sequential arm samples.
        task_accounting_ok = (
            self.task_count == self.peak_task_count == arm_peak_tasks
            if self.peak_task_count else
            self.task_count == sum(arm.task_count for arm in self.arms))
        # A production command executes the arm grid sequentially and then
        # runs the retained-sample DAG.  The six-hour scientific projection
        # is separate and must not be mistaken for measured command wall.
        if self.peak_task_count and not self.composed.measured_stage_walls_seconds:
            raise WorldAfterstateV2CapacityError(
                "capacity command/arm accounting drift")
        arm_wall = sum(arm.wall_seconds for arm in self.arms)
        required_command_wall = arm_wall + (
            sum(value for _, value in self.composed.measured_stage_walls_seconds)
            if self.peak_task_count else 0)
        command_wall_ok = (
            self.command_wall_seconds == required_command_wall
            if self.peak_task_count else
            self.command_wall_seconds >= arm_wall)
        if not command_wall_ok \
                or not task_accounting_ok:
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
            fastest = min(eligible, key=lambda arm: (
                arm.wall_nanoseconds or arm.wall_seconds * 1_000_000_000,
                arm.variant))
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
        if any((self.member_workers, self.torch_threads, self.inference_batch)):
            if (self.member_workers not in ARM_GRIDS["member-concurrency"]
                    or type(self.torch_threads) is not int
                    or self.torch_threads != PINNED_TORCH_THREADS
                    or self.inference_batch not in ARM_GRIDS["inference-batch"]):
                raise WorldAfterstateV2CapacityError("capacity resource layout drift")
            selected_by_stage = {arm.stage: arm for arm in self.selected_arms}
            if (selected_by_stage["member-concurrency"].variant != self.member_workers
                    or selected_by_stage["inference-batch"].variant
                    != self.inference_batch):
                raise WorldAfterstateV2CapacityError("capacity resource layout mismatch")
        elif self.peak_task_count:
            raise WorldAfterstateV2CapacityError("capacity resource layout missing")
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
            "measurement_scope": self.measurement_scope,
            "member_workers": self.member_workers,
            "torch_threads": self.torch_threads,
            "inference_batch": self.inference_batch,
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
    "ARM_GRIDS", "AUTHORITY", "CapacityArmV2", "CapacityFailureReceiptV2",
    "CapacityReceiptV2",
    "CAPACITY_ARM_TO_PRODUCTION_STAGE", "CAPACITY_PRODUCTION_STAGE_COVERAGE",
    "CAPACITY_STAGE_TO_PRODUCTION_STAGE",
    "CAPACITY_SUBSTAGE_TO_PRODUCTION_STAGE",
    "COMPOSED_DAG_EDGES", "COMPOSED_STAGE_NAMES", "PRODUCTION_STAGE_NAMES",
    "SCIENTIFIC_DAG_EDGES",
    "TRAINING_RESOURCE_SERIALIZATION_EDGES", "ComposedProjectionV2",
    "MAX_COMMAND_WALL_SECONDS", "MAX_TASKS",
    "MEMORY_LIMIT_BYTES", "ProgressRecoveryV2", "TierProjectionV2",
    "MEASUREMENT_SCOPE", "PINNED_TORCH_THREADS",
    "WorldAfterstateV2CapacityError", "choose_capacity_tier_v2",
    "capacity_receipt_sha256", "composed_critical_path_seconds",
    "reopen_capacity_failure_receipt_v2",
    "reopen_capacity_failure_receipt_v2_bytes",
    "validate_capacity_failure_receipt_v2",
    "validate_capacity_receipt_v2",
]
