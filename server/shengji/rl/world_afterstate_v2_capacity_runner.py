"""Bounded, score-free post-implementation capacity measurement for V2.

The contract in :mod:`world_afterstate_v2_capacity` is intentionally only a
receipt.  This module is the executable boundary which obtains measurements,
derives projections, and then hands the result to that contract.  The
full-DAG supervisor it invokes keeps scientific labels/outcomes local and
never places them in the capacity receipt.

The synthetic backend is useful for unit tests only.  It is branded at the
type boundary and is rejected by ``build_receipt_v2`` and publication, so a
test seam cannot accidentally produce a production receipt.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import resource
import shutil
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import canonical_successor, replay_canonical_successor
from .world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, COMPOSED_STAGE_NAMES, MAX_COMMAND_WALL_SECONDS, MEMORY_LIMIT_BYTES,
    CAPACITY_PREFLIGHT_ACCEPTED,
    COHORT_MEMBER_WORKERS, COHORT_WORKERS, MEASUREMENT_SCOPE,
    MIN_CONTINUATION_WORK_UNITS,
    PINNED_TORCH_THREADS,
    MAX_TASKS, CapacityArmV2, CapacityCensusAssessmentV2, CapacityFailureReceiptV2, CapacityReceiptV2,
    ComposedProjectionV2,
    ProgressRecoveryV2, RejectedProjectionDiagnosticV2, TierProjectionV2,
    WorldAfterstateV2CapacityError,
    composed_critical_path_seconds, composed_dag_edges_for_cohort_workers,
    validate_capacity_receipt_v2,
    reopen_capacity_failure_receipt_v2,
    reopen_capacity_failure_receipt_v2_bytes,
    validate_capacity_failure_receipt_v2,
    derive_all_core_gate_passed, projected_arm_wall_shares_ppm,
    validate_capacity_arm_census_v2 as _validate_capacity_arm_census_contract,
)
from .world_afterstate_v2_protocol import (
    ATTEMPT_SCHEMA, MEMORY_PERCENT_MAX, P0_DEALS, TIER_SPECS,
)
from .world_afterstate_v2_schedule import (
    MAX_EPOCHS, ordered_root_ids_for_epoch, training_epoch_batches,
)
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_source_driver import drive_population_attempt_v2
from .world_afterstate_v2_execution import (
    bind_runtime_expectation, verified_process_pool_kwargs,
)
from .world_afterstate_v2_controls import (
    CONTROL_NAMES, action_association_permutation, complete_world_shuffle,
    control_training_examples, label_permutation, validate_control_evidence,
    WorldAfterstateV2ControlError,
)
from .world_afterstate_v2_inference import build_inference_root_v2
from .world_afterstate_v2_label import ContinuationOutcomeV2
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_training_controller import (
    controller_process_torch_scope, reopen_cohort_build, train_named_cohort,
)
from .world_afterstate_v2_artifacts import (
    publish_checkpoint_shard, reopen_checkpoint_shard,
)
from .world_afterstate_v2_capacity_supervisor import TRAINING_BATCH_EXAMPLE_CAP


HOST_CPUS = 16
ZERO_SWAP = 0
PREFLIGHT_ACCEPTED = 32
PREFLIGHT_ATTEMPT_CEILING = 384
PREFLIGHT_WORKERS = HOST_CPUS
PREFLIGHT_RESERVED_NATURAL_ROOTS = 16
PREFLIGHT_RESERVED_NATURAL_PAIRS = PREFLIGHT_RESERVED_NATURAL_ROOTS // 2
PREFLIGHT_MAX_NATURAL_ROOTS = 17
CONTINUATION_MIN_WORK_UNITS = MIN_CONTINUATION_WORK_UNITS
CAPACITY_TRAINING_EXAMPLES = 128
SYNTHETIC_BRAND = "SYNTHETIC_TEST_MEASUREMENT_ONLY"
RUNNER_SCHEMA = "world-afterstate-v2-capacity-runner-v1"
OPERATION_OUTPUT_SCHEMA = "world-afterstate-v2-capacity-operation-output-v1"
OPERATION_OUTPUT_DOMAIN = "world-afterstate-v2.capacity.operation-output"
_OPERATION_OUTPUT_SCHEMAS = {
    "state-successor": "world-afterstate-successor-v0",
    "continuation-mechanics": "world-afterstate-v2-continuation-probe-v1",
    "reconstruction": "world-afterstate-v2-capacity-reconstruction-output-v1",
}
_PRODUCTION_PROVENANCE = object()
_FULL_DAG_PROVENANCE = object()

if PREFLIGHT_ACCEPTED != CAPACITY_PREFLIGHT_ACCEPTED:
    raise RuntimeError("capacity preflight population constant drift")


class CapacityRunnerError(RuntimeError):
    """A capacity run was refused or could not be measured honestly."""

    def __init__(self, message: str, *, stage: str = "runner",
                 reason_code: str = "capacity-runner-refused",
                 assessments: Sequence[CapacityCensusAssessmentV2] = (),
                 projection_diagnostic: RejectedProjectionDiagnosticV2 | None = None
                 ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason_code = reason_code
        self.assessments = tuple(assessments)
        self.projection_diagnostic = projection_diagnostic


class FullDAGCapacityDependencyBlocked(CapacityRunnerError):
    """The repository lacks the supervisor needed for admissible DAG timing."""

    dependency = (
        "high-level score-free capacity supervisor for continuation-label, "
        "optimizer/epoch, cohort-control, audit, and reconstruction stages")


class MeasurementBackendV2(Protocol):
    synthetic: bool

    def measure(self, stage: str, variant: int, fixture: "FixtureV2",
                operation: Callable[[], None]) -> "RawMeasurementV2": ...


def _ordered_fixture_identity(fixtures: Sequence[FixtureV2]) -> str:
    """Identity of the ordered score-free outputs shared by every arm."""
    return _sha([fixture.fixture_sha256 for fixture in fixtures])


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ceil_seconds(nanoseconds: int) -> int:
    return max(1, (nanoseconds + 999_999_999) // 1_000_000_000)


def _proc_cpu_ns() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    process_ns = int((usage.ru_utime + usage.ru_stime + children.ru_utime
                      + children.ru_stime) * 1_000_000_000)
    # cgroup CPU accounting includes ProcessPool workers after they exit and
    # is the authoritative aggregate when available.
    try:
        stat = Path("/sys/fs/cgroup/cpu.stat").read_text(encoding="ascii")
        usage_usec = next(int(line.split()[1]) for line in stat.splitlines()
                          if line.startswith("usage_usec "))
        return max(process_ns, usage_usec * 1_000)
    except (OSError, StopIteration, ValueError, IndexError):
        return process_ns


def _rss_bytes() -> int:
    # Linux reports KiB.  ``ru_maxrss`` is bytes on macOS; the proc path is
    # preferred where available and the fallback is still real process RSS.
    try:
        raw = Path("/proc/self/status").read_text(encoding="ascii")
        for line in raw.splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if value > 1_000_000 else value * 1024


def _cgroup_memory_bytes() -> int:
    """Return current cgroup memory when the host exposes it."""
    for name in ("memory.current", "memory.usage_in_bytes"):
        try:
            value = Path("/sys/fs/cgroup", name).read_text(encoding="ascii").strip()
            if value != "max":
                return max(1, int(value))
        except (OSError, ValueError):
            continue
    return _rss_bytes()


def _cgroup_memory_limit_bytes() -> int | None:
    for name in ("memory.max", "memory.limit_in_bytes"):
        try:
            value = Path("/sys/fs/cgroup", name).read_text(encoding="ascii").strip()
            if value != "max":
                return int(value)
        except (OSError, ValueError):
            continue
    return None


def _task_count() -> int:
    values = []
    try:
        values.append(sum(1 for path in Path("/proc/self/task").iterdir()
                          if path.is_dir()))
    except OSError:
        pass
    for name in ("pids.current",):
        try:
            values.append(int(Path("/sys/fs/cgroup", name).read_text().strip()))
        except (OSError, ValueError):
            pass
    return max([1, *values])


def _swap_bytes() -> int:
    try:
        raw = Path("/proc/meminfo").read_text(encoding="ascii")
        values = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
                  for line in raw.splitlines() if ":" in line}
        return values.get("SwapTotal", 0) - values.get("SwapFree", 0)
    except (OSError, ValueError, IndexError):
        return 0


@dataclass(frozen=True)
class HostTelemetryV2:
    logical_cpus: int
    memory_limit_bytes: int = MEMORY_LIMIT_BYTES
    swap_bytes: int = ZERO_SWAP
    task_count: int = 1
    free_disk_bytes: int = 1
    observed_memory_max_bytes: int = 0

    def validate(self) -> None:
        if self.logical_cpus != HOST_CPUS:
            raise CapacityRunnerError("capacity host requires exactly 16 logical CPUs")
        if self.memory_limit_bytes != MEMORY_LIMIT_BYTES:
            raise CapacityRunnerError("capacity memory envelope drift")
        if self.observed_memory_max_bytes and self.observed_memory_max_bytes < MEMORY_LIMIT_BYTES:
            raise CapacityRunnerError("observed cgroup memory.max is below 30 GiB")
        if self.swap_bytes != ZERO_SWAP:
            raise CapacityRunnerError("capacity requires zero swap")
        if self.task_count < 1 or self.task_count > MAX_TASKS:
            raise CapacityRunnerError("capacity task cap exceeded")
        if self.free_disk_bytes < 1:
            raise CapacityRunnerError("capacity disk telemetry unavailable")


def observe_host(path: Path | str = ".") -> HostTelemetryV2:
    """Read the real host envelope used by production measurement."""
    usage = shutil.disk_usage(Path(path).resolve())
    result = HostTelemetryV2(
        logical_cpus=os.cpu_count() or 0, swap_bytes=_swap_bytes(),
        task_count=_task_count(), free_disk_bytes=usage.free,
        observed_memory_max_bytes=_cgroup_memory_limit_bytes() or 0)
    result.validate()
    return result


@dataclass(frozen=True)
class FixtureV2:
    """One immutable, outcome-free fixture shared by every arm of a stage."""

    snapshot: Mapping[str, Any]
    audit_raws: tuple[bytes, ...] = ()
    fixture_sha256: str = ""
    deal_sha256: str = ""
    # The complete material is retained privately so the full-DAG supervisor
    # can execute the reviewed primitives.  It is never part of a receipt.
    material: PopulationMaterialV2 | None = None

    def __post_init__(self) -> None:
        raw = canonical_json_bytes(self.snapshot)
        expected = _sha_bytes(raw)
        if self.fixture_sha256 and self.fixture_sha256 != expected:
            raise CapacityRunnerError("fixture byte identity drift")
        object.__setattr__(self, "fixture_sha256", expected)
        if any(type(raw_value) is not bytes for raw_value in self.audit_raws):
            raise CapacityRunnerError("fixture audit bytes drift")
        if self.deal_sha256 and (len(self.deal_sha256) != 64 or
                                 any(char not in "0123456789abcdef"
                                     for char in self.deal_sha256)):
            raise CapacityRunnerError("fixture deal identity drift")
        if self.material is not None:
            if type(self.material) is not PopulationMaterialV2:
                raise CapacityRunnerError("fixture material type drift")
            try:
                self.material.validate()
            except Exception as exc:
                raise CapacityRunnerError("fixture material validation drift") from exc
            if canonical_json_bytes(self.material.prestate) != raw:
                raise CapacityRunnerError("fixture material/prestate byte drift")
            if tuple(self.audit_raws) != tuple(self.material.audit_raws):
                raise CapacityRunnerError("fixture material/audit bytes drift")
            if self.material.deal_sha256 != self.deal_sha256:
                raise CapacityRunnerError("fixture material/deal identity drift")


@dataclass(frozen=True)
class PreflightResultV2:
    accepted_fixtures: tuple[FixtureV2, ...]
    attempted: int
    accepted: int
    rejection_counts: tuple[tuple[str, int], ...]
    candidate_distribution: tuple[tuple[int, int], ...]
    stratum_distribution: tuple[tuple[str, int], ...]
    elapsed_wall_nanoseconds: int
    outcomes_opened: bool = False

    def validate(self) -> None:
        if self.attempted < self.accepted or self.attempted > PREFLIGHT_ATTEMPT_CEILING:
            raise CapacityRunnerError("preflight attempt ceiling drift")
        if self.accepted != len(self.accepted_fixtures):
            raise CapacityRunnerError("preflight accepted fixture accounting drift")
        if self.accepted != PREFLIGHT_ACCEPTED:
            raise CapacityRunnerError("preflight requires exactly 32 accepted deals")
        if (type(self.elapsed_wall_nanoseconds) is not int
                or self.elapsed_wall_nanoseconds < 1):
            raise CapacityRunnerError("preflight wall timing drift")
        if (any(type(name) is not str or not name or type(count) is not int
                or count < 1 for name, count in self.rejection_counts)
                or sum(count for _, count in self.rejection_counts)
                != self.attempted - self.accepted):
            raise CapacityRunnerError("preflight rejection accounting drift")
        deal_ids = [fixture.deal_sha256 for fixture in self.accepted_fixtures
                    if fixture.deal_sha256]
        if deal_ids and len(deal_ids) != len(set(deal_ids)):
            raise CapacityRunnerError("preflight accepted deals are not independent")
        slot_ids = [getattr(getattr(fixture.material, "state", None),
                            "slot_sha256", None)
                    for fixture in self.accepted_fixtures]
        present_slot_ids = [value for value in slot_ids if value is not None]
        if present_slot_ids and (len(present_slot_ids) != len(slot_ids)
                                 or len(present_slot_ids)
                                 != len(set(present_slot_ids))):
            raise CapacityRunnerError(
                "preflight accepted population slots are not independent")
        if self.outcomes_opened:
            raise CapacityRunnerError("preflight outcomes were opened")
        if not self.candidate_distribution or not self.stratum_distribution:
            raise CapacityRunnerError("preflight candidate/stratum report missing")
        if (sum(count for _, count in self.candidate_distribution)
                != self.accepted
                or sum(count for _, count in self.stratum_distribution)
                != self.accepted):
            raise CapacityRunnerError("preflight accepted distribution drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "world-afterstate-v2-score-free-preflight-v1",
            "attempted": self.attempted, "accepted": self.accepted,
            "rejection_counts": [[key, value]
                                  for key, value in self.rejection_counts],
            "candidate_distribution": [[key, value]
                                        for key, value in self.candidate_distribution],
            "stratum_distribution": [[key, value]
                                      for key, value in self.stratum_distribution],
            "elapsed_wall_nanoseconds": self.elapsed_wall_nanoseconds,
            "outcomes_opened": self.outcomes_opened,
            "accepted_fixture_sha256s": [fixture.fixture_sha256
                                          for fixture in self.accepted_fixtures],
        }


def _namespace() -> str:
    return _sha({"namespace": "world-afterstate-v2-capacity-preflight-v2"})


def _attempt_identity(namespace: str, slot: Any, index: int) -> dict[str, Any]:
    body = {"schema": ATTEMPT_SCHEMA, "population_namespace_sha256": namespace,
            "slot_sha256": slot.slot_sha256, "attempt_index": index}
    deal = _sha(body)
    return {**body, "deal_sha256": deal,
            "engine_seed": int(deal[:16], 16) & ((1 << 63) - 1)}


def _preflight_executor_type(attempt: Callable[..., Any]):
    """Use processes for the real CPU-bound driver and threads for test seams."""
    return (ProcessPoolExecutor
            if attempt is drive_population_attempt_v2 else ThreadPoolExecutor)


def _population_category(value: Any) -> str | None:
    state = getattr(value, "state", value)
    split = getattr(state, "split", None)
    source = getattr(state, "source", None)
    subfold = getattr(state, "select_subfold", None)
    if split == "fit" and source in (None, "natural"):
        return "fit"
    if split == "select" and subfold in ("epoch-select", "precision-select"):
        return subfold
    return "audit" if split == "audit" else None


def _reserved_natural_pair_slots(slots: Sequence[Any]) -> tuple[Any, ...]:
    """Return the first eight canonical natural-fit slot pairs.

    Pair reservation uses only public slot metadata. Synthetic narrow test
    seams without canonical slot IDs retain their caller-supplied schedule.
    """
    from .world_afterstate_v2_protocol import fit_pair_id_from_slot_sha256

    groups: dict[str, list[Any]] = {}
    for slot in slots:
        if (getattr(slot, "split", None) != "fit"
                or getattr(slot, "source", None) != "natural"):
            continue
        try:
            pair = fit_pair_id_from_slot_sha256(slot.slot_sha256)
        except Exception:
            continue
        groups.setdefault(pair, []).append(slot)
    result: list[Any] = []
    for pair in sorted(groups):
        members = groups[pair]
        if len({member.slot_sha256 for member in members}) != 2:
            continue
        result.extend(sorted(members, key=lambda member: member.ordinal))
        if len(result) == PREFLIGHT_RESERVED_NATURAL_ROOTS:
            break
    return tuple(result)


def _preflight_slot(slots: Sequence[Any], attempt_index: int,
                    reserved_slots: Sequence[Any] = ()) -> Any:
    """Reserve eight natural slot pairs, then cover held-out cells."""
    values = tuple(slots)
    reserved = tuple(reserved_slots)
    if reserved and attempt_index < len(reserved):
        return reserved[attempt_index]
    if attempt_index < 96:
        return values[attempt_index % len(values)]
    first_wave_slot_ids = {
        values[index % len(values)].slot_sha256
        for index in range(96)
    }
    names = ("epoch-select", "precision-select", "audit", "fit")
    groups = tuple(tuple(
        slot for slot in values if _population_category(slot) == name)
                   for name in names)
    if any(not group for group in groups):
        # Narrow test seams retain their caller-supplied cyclic schedule.
        return values[attempt_index % len(values)]
    group_index = (attempt_index - 96) % len(groups)
    group = groups[group_index]
    held_out = tuple(slot for slot in group
                     if slot.slot_sha256 not in first_wave_slot_ids)
    if held_out:
        group = held_out
    return group[((attempt_index - 96) // len(groups)) % len(group)]


def _required_population_counts() -> dict[str, int]:
    return {
        "fit": max(1, min(PREFLIGHT_MAX_NATURAL_ROOTS,
                          PREFLIGHT_ACCEPTED - 3)),
        "epoch-select": 1, "precision-select": 1, "audit": 1,
    }


def _population_counts(fixtures: Sequence[Any]) -> Counter[str]:
    return Counter(
        category for fixture in fixtures
        if fixture.material is not None
        for category in (_population_category(fixture.material),)
        if category is not None)


def _population_coverage_complete(fixtures: Sequence[Any]) -> bool:
    counts = _population_counts(fixtures)
    return all(counts[name] >= minimum
               for name, minimum in _required_population_counts().items())


def run_score_free_preflight(*, attempt: Callable[..., Any] = drive_population_attempt_v2,
                             slots: Sequence[Any] | None = None,
                             deadline_ns: int | None = None,
                             progress: Callable[[dict[str, Any]], None] | None = None,
                             started_ns: int | None = None) -> PreflightResultV2:
    """Find 32 accepted natural/mechanics D256 deals, bounded at 384 attempts."""
    from .world_afterstate_v2_protocol import _raw_slot_ledger

    preflight_started_ns = time.perf_counter_ns()

    if slots is None:
        # Natural cells are the broadest honest source.  Mechanics slots are
        # included in the schedule so their acceptance is reported when an
        # eligible surface occurs, but no result is selected by an outcome.
        ledger = _raw_slot_ledger(TIER_SPECS[0])
        slots = tuple(row for row in ledger if row.source in ("natural", "mechanics"))
    slots = tuple(slots)
    if not slots:
        raise CapacityRunnerError("preflight slot population is empty")
    namespace = _namespace()
    accepted: list[FixtureV2] = []
    accepted_slots: set[str] = set()
    rejected: Counter[str] = Counter()
    candidates: Counter[int] = Counter()
    strata: Counter[str] = Counter()
    required_splits = set(_required_population_counts())
    coverage_required = (attempt is drive_population_attempt_v2
                         or required_splits <= {
                             _population_category(slot) for slot in slots})
    reserved_slots = _reserved_natural_pair_slots(slots)
    from .world_afterstate_v2_protocol import fit_pair_id_from_slot_sha256
    canonical_natural_slots = []
    for slot in slots:
        if (getattr(slot, "split", None) == "fit"
                and getattr(slot, "source", None) == "natural"):
            try:
                fit_pair_id_from_slot_sha256(slot.slot_sha256)
            except Exception:
                continue
            canonical_natural_slots.append(slot)
    reservation_required = len(canonical_natural_slots) >= PREFLIGHT_RESERVED_NATURAL_ROOTS
    if reservation_required and len(reserved_slots) != PREFLIGHT_RESERVED_NATURAL_ROOTS:
        raise CapacityRunnerError(
            "preflight natural-fit pair reservation is not predeclared")
    reserved_slot_ids = {slot.slot_sha256 for slot in reserved_slots}
    general_slots = tuple(slot for slot in slots
                          if slot.slot_sha256 not in reserved_slot_ids)
    if not general_slots:
        general_slots = slots
    reserved_target = min(PREFLIGHT_RESERVED_NATURAL_ROOTS,
                          PREFLIGHT_ACCEPTED, len(reserved_slots))
    reserved_accepted: set[str] = set()
    natural_fit_count = 0
    index = 0
    general_index = 0
    executor_type = _preflight_executor_type(attempt)
    peak_memory = _cgroup_memory_bytes()
    pool_kwargs = (verified_process_pool_kwargs()
                   if executor_type is ProcessPoolExecutor else {})
    with executor_type(max_workers=PREFLIGHT_WORKERS, **pool_kwargs) as pool:
        while index < PREFLIGHT_ATTEMPT_CEILING \
                and (len(accepted) < PREFLIGHT_ACCEPTED
                     or (coverage_required
                         and not _population_coverage_complete(accepted))
                     or len(reserved_accepted) < reserved_target):
            if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
                raise CapacityRunnerError(
                    "capacity deadline exceeded during preflight")
            if _cgroup_memory_bytes() * 100 > MEMORY_LIMIT_BYTES * 85:
                raise CapacityRunnerError(
                    "capacity memory headroom exhausted during preflight")
            if _swap_bytes() != ZERO_SWAP:
                raise CapacityRunnerError(
                    "capacity swap became non-zero during preflight")
            if _task_count() > MAX_TASKS:
                raise CapacityRunnerError(
                    "capacity task cap exceeded during preflight")
            # Never schedule more attempts than the number of fixtures still
            # needed.  Therefore a concurrent batch cannot produce an eligible
            # surplus that would require post-hoc selection or hidden accounting.
            pending_reserved = tuple(
                slot for slot in reserved_slots
                if slot.slot_sha256 not in reserved_accepted)
            batch_size = min(
                PREFLIGHT_WORKERS, max(1, PREFLIGHT_ACCEPTED - len(accepted)),
                len(pending_reserved) if pending_reserved else PREFLIGHT_WORKERS,
                PREFLIGHT_ATTEMPT_CEILING - index)
            batch_started = time.perf_counter_ns()
            batch_cpu_started = _proc_cpu_ns()
            jobs = []
            for offset in range(batch_size):
                attempt_index = index + offset
                if pending_reserved:
                    slot = pending_reserved[offset]
                else:
                    slot = _preflight_slot(general_slots,
                                           general_index + offset)
                jobs.append((attempt_index, slot, pool.submit(
                    attempt,
                    _attempt_identity(namespace, slot, attempt_index), slot)))
            try:
                results = tuple((attempt_index, slot, future.result())
                                for attempt_index, slot, future in jobs)
            except Exception as exc:
                # An infrastructure failure is not a scientific rejection and
                # must never be counted toward the fixed 384-attempt supply.
                raise CapacityRunnerError("capacity preflight worker failed") from exc
            if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
                # A batch that finishes after the command deadline is not
                # allowed to turn an expired capacity run into a success.
                raise CapacityRunnerError(
                    "capacity deadline exceeded during preflight")
            if _cgroup_memory_bytes() * 100 > MEMORY_LIMIT_BYTES * 85:
                raise CapacityRunnerError(
                    "capacity memory headroom exhausted during preflight")
            if _swap_bytes() != ZERO_SWAP:
                raise CapacityRunnerError(
                    "capacity swap became non-zero during preflight")
            if _task_count() > MAX_TASKS:
                raise CapacityRunnerError(
                    "capacity task cap exceeded during preflight")
            batch_elapsed = max(1, time.perf_counter_ns() - batch_started)
            batch_cpu = max(1, _proc_cpu_ns() - batch_cpu_started)
            utilization = min(
                1_000_000, batch_cpu * 1_000_000
                // max(1, batch_elapsed * HOST_CPUS))
            for attempt_index, slot, result in results:
                if not getattr(result, "accepted", False):
                    rejected[str(getattr(
                        result, "rejection_reason", "unknown"))] += 1
                    continue
                material = getattr(result, "material", None)
                if material is None:
                    rejected["missing-material"] += 1
                    continue
                slot_sha256 = slot.slot_sha256
                if slot_sha256 in accepted_slots:
                    rejected["duplicate-slot"] += 1
                    continue
                if coverage_required:
                    counts = _population_counts(accepted)
                    required_counts = _required_population_counts()
                    split = _population_category(material)
                    deficits = sum(max(0, required_counts[name] - counts[name])
                                   for name in required_counts)
                    remaining = PREFLIGHT_ACCEPTED - len(accepted)
                    # Keep the target at exactly 32 while reserving every
                    # still-missing production population, including the 17
                    # natural-fit deals needed by P0 plus later training.
                    if (len(accepted) >= PREFLIGHT_ACCEPTED
                            or split is None
                            or (counts[split] >= required_counts[split]
                                and remaining <= deficits)):
                        rejected["split-reservation"] += 1
                        continue
                category = _population_category(material)
                if category == "fit" and getattr(
                        getattr(material, "state", None), "source", None) == "natural":
                    if (slot_sha256 not in reserved_slot_ids
                            and natural_fit_count >= PREFLIGHT_MAX_NATURAL_ROOTS):
                        rejected["natural-fit-cap"] += 1
                        continue
                    natural_fit_count += 1
                # Only the score-free canonical state and private audit bytes
                # enter the in-memory fixture.  No continuation/result field is
                # copied.
                fixture = FixtureV2(
                    material.prestate, tuple(material.audit_raws),
                    deal_sha256=result.deal_sha256, material=material)
                accepted.append(fixture)
                accepted_slots.add(slot_sha256)
                if slot_sha256 in reserved_slot_ids:
                    reserved_accepted.add(slot_sha256)
                candidates[len(material.candidates)] += 1
                state = material.state
                strata[f"{state.phase}/{state.position}/{state.role}"] += 1
            index += batch_size
            if not pending_reserved:
                general_index += batch_size
            peak_memory = max(peak_memory, _cgroup_memory_bytes())
            if progress is not None:
                elapsed = max(
                    0, time.perf_counter_ns()
                    - (started_ns or time.perf_counter_ns()))
                projected_attempts = (index if not accepted else min(
                    PREFLIGHT_ATTEMPT_CEILING,
                    math.ceil(index * PREFLIGHT_ACCEPTED / len(accepted))))
                eta = (max(0, projected_attempts - index) * elapsed
                       // max(1, index))
                progress({
                    "stage": "preflight", "completed_units": index,
                    "total_units": PREFLIGHT_ATTEMPT_CEILING,
                    "workers": batch_size, "utilization_ppm": utilization,
                    "elapsed_seconds": elapsed // 1_000_000_000,
                    "eta_seconds": eta // 1_000_000_000,
                    "headroom_seconds": max(
                        0, MAX_COMMAND_WALL_SECONDS
                        - elapsed // 1_000_000_000),
                    "accepted": len(accepted),
                    "rejection_counts": dict(sorted(rejected.items())),
                    "memory_bytes": _cgroup_memory_bytes(),
                    "peak_memory_bytes": peak_memory,
                    "queue_depth": 0,
                    "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
                    "immutable_shards": 0, "checkpoint_count": 0,
                })
            if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
                raise CapacityRunnerError(
                    "capacity deadline exceeded during preflight")
            if _cgroup_memory_bytes() * 100 > MEMORY_LIMIT_BYTES * 85:
                raise CapacityRunnerError(
                    "capacity memory headroom exhausted during preflight")
            if _swap_bytes() != ZERO_SWAP:
                raise CapacityRunnerError(
                    "capacity swap became non-zero during preflight")
            if _task_count() > MAX_TASKS:
                raise CapacityRunnerError(
                    "capacity task cap exceeded during preflight")
    if (reserved_target and len(reserved_accepted) < reserved_target):
        raise CapacityRunnerError(
            "preflight natural-fit pair reservation is incomplete")
    if coverage_required and not _population_coverage_complete(accepted):
        raise CapacityRunnerError(
            "preflight retained split coverage is incomplete")
    result = PreflightResultV2(
        tuple(accepted), index, len(accepted), tuple(sorted(rejected.items())),
        tuple(sorted(candidates.items())), tuple(sorted(strata.items())),
        max(1, time.perf_counter_ns() - preflight_started_ns))
    result.validate()
    return result


@dataclass(frozen=True)
class RawMeasurementV2:
    elapsed_ns: int
    process_cpu_ns: int
    peak_rss_bytes: int
    task_count: int
    sample_utilization_ppm: tuple[int, ...] = ()
    sample_memory_bytes: tuple[int, ...] = ()
    sample_task_counts: tuple[int, ...] = ()
    sample_swap_bytes: tuple[int, ...] = ()
    sample_free_disk_bytes: tuple[int, ...] = ()
    queue_depth: int = 0
    disk_bytes_written: int = 1
    byte_identity_sha256: str = ""
    cpu_bound: bool = True

    def validate(self) -> None:
        if self.elapsed_ns < 1 or self.process_cpu_ns < 1:
            raise CapacityRunnerError("measurement timer is not positive")
        if self.peak_rss_bytes < 1 or self.task_count < 1:
            raise CapacityRunnerError("measurement telemetry is incomplete")
        if self.task_count > MAX_TASKS or self.disk_bytes_written < 0:
            raise CapacityRunnerError("measurement resource cap drift")
        if not self.byte_identity_sha256:
            raise CapacityRunnerError("measurement byte identity is missing")
        if any(value < 1 or value > 1_000_000
               for value in self.sample_utilization_ppm):
            raise CapacityRunnerError("measurement CPU sample drift")
        if any(value < 1 for value in self.sample_memory_bytes):
            raise CapacityRunnerError("measurement memory sample drift")
        if any(value < 0 for value in self.sample_task_counts):
            raise CapacityRunnerError("measurement task sample drift")
        if any(value != ZERO_SWAP for value in self.sample_swap_bytes):
            raise CapacityRunnerError("measurement swap sample drift")
        if any(value < 1 for value in self.sample_free_disk_bytes):
            raise CapacityRunnerError("measurement disk sample drift")


class RealMeasurementBackendV2:
    """Measure process wall/CPU/RSS/tasks while running real primitives."""

    synthetic = False

    def __init__(self, *, deadline_ns: int | None = None,
                 progress: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.deadline_ns = deadline_ns
        self.progress = progress

    def measure(self, stage: str, variant: int, fixture: FixtureV2,
                operation: Callable[[], None]) -> RawMeasurementV2:
        start = time.perf_counter_ns()
        cpu_start = _proc_cpu_ns()
        rss_before = max(_rss_bytes(), _cgroup_memory_bytes())
        tasks_before = _task_count()
        swap_before = _swap_bytes()
        disk_before = shutil.disk_usage(Path.cwd()).free
        samples: list[tuple[int, int, int, int]] = []
        cpu_samples: list[int] = []
        last_sample_ns = start
        last_sample_cpu = cpu_start
        stopped = threading.Event()
        failure: list[str] = []
        last_heartbeat = start
        def monitor() -> None:
            nonlocal last_sample_ns, last_sample_cpu, last_heartbeat
            while not stopped.is_set():
                now = time.perf_counter_ns()
                rss_now = max(_rss_bytes(), _cgroup_memory_bytes())
                task_now = _task_count()
                swap_now = _swap_bytes()
                disk_now = shutil.disk_usage(Path.cwd()).free
                samples.append((rss_now, task_now, swap_now, disk_now))
                now_cpu = _proc_cpu_ns()
                elapsed_sample = max(1, now - last_sample_ns)
                # CPU samples are aggregate host utilization, not a one-core
                # percentage.  Keep the same 16-core denominator used by the
                # receipt's busy-core binding.
                cpu_samples.append(min(
                    1_000_000, max(1, (now_cpu - last_sample_cpu)
                                    * 1_000_000
                                    // (elapsed_sample * HOST_CPUS))))
                last_sample_ns, last_sample_cpu = now, now_cpu
                if rss_now * 100 > MEMORY_LIMIT_BYTES * 85:
                    failure.append("capacity memory headroom exhausted")
                if task_now > MAX_TASKS:
                    failure.append("capacity task cap exceeded")
                if swap_now != ZERO_SWAP:
                    failure.append("capacity swap became non-zero")
                if self.deadline_ns is not None and now >= self.deadline_ns:
                    failure.append("capacity deadline exceeded during measurement")
                if self.progress is not None and now - last_heartbeat >= 1_000_000_000:
                    self.progress({
                        "stage": stage, "completed_units": 0,
                        "total_units": 1, "workers": variant,
                        "utilization_ppm": cpu_samples[-1] if cpu_samples else 0,
                        "elapsed_seconds": (now - start) // 1_000_000_000,
                        "eta_seconds": 0,
                        "headroom_seconds": max(0, MAX_COMMAND_WALL_SECONDS
                                                 - (now - start) // 1_000_000_000),
                        "memory_bytes": rss_now, "peak_memory_bytes": rss_now,
                        "queue_depth": max(0, task_now - variant),
                        "disk_free_bytes": disk_now,
                        "immutable_shards": 0, "checkpoint_count": 0,
                    })
                    last_heartbeat = now
                stopped.wait(.05)
        watcher = threading.Thread(target=monitor, name="capacity-telemetry",
                                   daemon=True)
        watcher.start()
        operation_result: Any = None
        operation_failure: list[BaseException] = []
        def invoke() -> None:
            try:
                nonlocal operation_result
                operation_result = operation()
            except BaseException as exc:  # re-raised in the parent below
                operation_failure.append(exc)
        worker = threading.Thread(target=invoke, name="capacity-operation",
                                  daemon=True)
        worker.start()
        while worker.is_alive():
            remaining = None if self.deadline_ns is None else max(
                0, self.deadline_ns - time.perf_counter_ns()) / 1_000_000_000
            worker.join(timeout=.05 if remaining is None else min(.05, remaining))
            if self.deadline_ns is not None and time.perf_counter_ns() >= self.deadline_ns:
                stopped.set()
                watcher.join()
                raise CapacityRunnerError(
                    "capacity deadline interrupted a running operation")
        try:
            worker.join()
            if operation_failure:
                raise operation_failure[0]
        finally:
            stopped.set()
            watcher.join()
        if failure:
            raise CapacityRunnerError(failure[0])
        elapsed = time.perf_counter_ns() - start
        cpu = _proc_cpu_ns() - cpu_start
        rss = max(rss_before, _rss_bytes(), _cgroup_memory_bytes())
        tasks = max(tasks_before, _task_count())
        swap_after = _swap_bytes()
        disk_after = shutil.disk_usage(Path.cwd()).free
        # Hashing the exact canonical fixture is a real, non-outcome sidecar
        # and supplies a non-zero disk-work unit without writing an artifact.
        digest = (operation_result if isinstance(operation_result, str)
                  else _sha_bytes(canonical_json_bytes(fixture.snapshot)))
        return RawMeasurementV2(
            elapsed_ns=elapsed, process_cpu_ns=max(1, cpu),
            peak_rss_bytes=max(1, rss), task_count=tasks,
            sample_utilization_ppm=tuple([min(
                1_000_000, max(1, cpu * 1_000_000
                               // max(1, elapsed * HOST_CPUS))),
                *cpu_samples]),
            sample_memory_bytes=tuple([rss_before, *[row[0] for row in samples], rss]),
            sample_task_counts=tuple([tasks_before, *[row[1] for row in samples], tasks]),
            sample_swap_bytes=tuple([swap_before, *[row[2] for row in samples], swap_after]),
            sample_free_disk_bytes=tuple([disk_before, *[row[3] for row in samples], disk_after]),
            queue_depth=max(0, tasks_before - 1),
            disk_bytes_written=max(0, disk_before - disk_after),
            byte_identity_sha256=digest, cpu_bound=True)


@dataclass(frozen=True)
class SyntheticMeasurementBackendV2:
    """Deterministic test seam; mechanically forbidden from publication."""

    measurements: Mapping[tuple[str, int], RawMeasurementV2]
    synthetic: bool = True
    brand: str = SYNTHETIC_BRAND

    def measure(self, stage: str, variant: int, fixture: FixtureV2,
                operation: Callable[[], None]) -> RawMeasurementV2:
        if self.brand != SYNTHETIC_BRAND:
            raise CapacityRunnerError("synthetic measurement brand drift")
        try:
            value = self.measurements[(stage, variant)]
        except KeyError as exc:
            raise CapacityRunnerError("synthetic measurement arm missing") from exc
        value.validate()
        return value


def _operation_output_identity(stage: str, output: Any) -> str:
    """Digest an operation's actual output in a variant-independent domain."""
    try:
        output_schema = _OPERATION_OUTPUT_SCHEMAS[stage]
    except KeyError as exc:
        raise CapacityRunnerError("unknown capacity operation output stage") from exc
    return _sha({
        "schema": OPERATION_OUTPUT_SCHEMA,
        "domain": OPERATION_OUTPUT_DOMAIN,
        "stage": stage,
        "output_schema": output_schema,
        "output": output,
    })


def _operation(stage: str, variant: int, fixture: FixtureV2) -> Callable[[], Any]:
    """Construct a score-free operation from the current V2 primitives."""
    if stage in {"member-concurrency", "cohort-concurrency"}:
        # Keep the low-level operation seam honest for callers that exercise
        # an arm directly; the runner uses _model_operation for the full
        # retained fixture population.
        return _model_operation(stage, variant, (fixture,))

    def run() -> Any:
        if stage == "state-successor":
            value = replay_canonical_successor(dict(fixture.snapshot))
            return canonical_successor(value, 0)
        elif stage == "continuation-mechanics":
            # One real engine continuation per retained material is enough to
            # measure independent-worker scaling without paying the complete
            # 8xN label bundle in every arm. The resulting outcome is hashed
            # in-process and discarded; the full-DAG stage below measures the
            # production bundle/controller at the selected worker width.
            if fixture.material is None:
                raise CapacityRunnerError(
                    "continuation capacity material is missing")
            from .world_afterstate_v2_continuation import (
                run_continuation_capacity_probe_v2)
            return run_continuation_capacity_probe_v2(fixture.material)
        elif stage == "inference-batch":
            # The inference arm exercises the actual target-free model input
            # and forward path.  No training target, optimizer, or label is
            # ever constructed.  Imports stay local because the server itself
            # does not require the optional RL dependency.
            import json as _json
            import torch
            from .world_afterstate import build_afterstate_tensors
            from .world_afterstate_v2_model import (
                collate_world_afterstate_tensors, new_world_afterstate_v2_model)
            raws = fixture.audit_raws
            if not raws:
                raise CapacityRunnerError("model fixture has no score-free audit bytes")
            tensors = tuple(build_afterstate_tensors(_json.loads(raw.decode("ascii")))
                            for raw in raws)
            batch = collate_world_afterstate_tensors(tensors)
            with torch.inference_mode():
                if stage == "member-concurrency":
                    output: list[str] = [""] * 4
                    def member(index: int) -> None:
                        result = new_world_afterstate_v2_model(0)(batch)
                        output[index] = _tensor_identity(result)
                    with ThreadPoolExecutor(max_workers=min(4, variant)) as pool:
                        tuple(pool.map(member, range(4)))
                else:
                    model = new_world_afterstate_v2_model(0)
                    # Thread arms alter torch's execution width only.  They
                    # must never multiply the measured work population.
                    output = [_tensor_identity(model(batch))]
            return _sha(output)
        elif stage == "reconstruction":
            from .world_afterstate import reopen_afterstate_audit
            outputs: list[Any] = []
            for raw in fixture.audit_raws or (canonical_json_bytes(fixture.snapshot),):
                hashlib.sha256(raw).digest()
                try:
                    value = json.loads(raw.decode("ascii"))
                    if isinstance(value, dict) and "successor" in value:
                        reopened = reopen_afterstate_audit(value)
                        outputs.append(canonical_successor(
                            reopened, value["root_seat"]))
                    else:
                        outputs.append({
                            "schema": "world-afterstate-v2-capacity-raw-audit-output-v1",
                            "sha256": _sha_bytes(raw),
                        })
                except (UnicodeDecodeError, ValueError):
                    outputs.append({
                        "schema": "world-afterstate-v2-capacity-raw-audit-output-v1",
                        "sha256": _sha_bytes(raw),
                    })
            return outputs
        else:
            raise CapacityRunnerError("unknown capacity stage")
    return run


def _capacity_training_population_identity(
        fixtures: Sequence[FixtureV2]) -> str:
    """Bind every retained material into the score-free training workload."""
    values = tuple(fixtures)
    if not values or any(type(item.material) is not PopulationMaterialV2
                         for item in values):
        raise CapacityRunnerError("capacity training material is missing")
    rows = []
    for fixture in values:
        material = fixture.material
        assert material is not None
        material.validate()
        rows.append({
            "fixture_sha256": fixture.fixture_sha256,
            "deal_sha256": material.state.deal_sha256,
            "slot_sha256": material.state.slot_sha256,
            "state_sha256": material.state.state_sha256,
            "candidate_set_sha256": material.candidate_set_sha256,
            "candidates": [{
                "candidate_index": candidate.candidate_index,
                "audit_sha256": candidate.audit_sha256,
                "successor_sha256": candidate.successor_sha256,
            } for candidate in material.candidates],
        })
    return _sha({
        "schema": "world-afterstate-v2-capacity-training-population-v1",
        "materials": rows,
    })


def _capacity_training_examples(
        fixtures: Sequence[FixtureV2]) -> tuple[Any, ...]:
    """Build complete score-free candidate x replica roots from all fixtures.

    Capacity labels are deterministic workload targets only.  They are kept in
    memory and are deliberately derived from sealed candidate/audit identity;
    no scientific continuation or outcome is opened or persisted here.
    """
    import json as _json
    from .world_afterstate import build_afterstate_tensors
    from .world_afterstate_v2_training import (
        WorldAfterstateV2TrainingExample)
    from .world_afterstate import OUTCOME_CLASSES
    values = tuple(fixtures)
    if not values or any(type(item.material) is not PopulationMaterialV2
                         for item in values):
        raise CapacityRunnerError("capacity training material is missing")
    population_identity = _capacity_training_population_identity(values)
    rows = []
    from .world_afterstate_v2_protocol import prior_points_bucket
    for fixture in values:
        material = fixture.material
        assert material is not None
        # Select/audit and mechanics fixtures serve other capacity stages and
        # remain bound into ``population_identity`` above.  They are not fit
        # examples and must never be relabelled into the optimizer population.
        if (material.state.split != "fit"
                or material.state.source != "natural"):
            continue
        points = material.prestate.get("public", {}).get("attacker_points")
        points_bucket = prior_points_bucket(points)
        for candidate, raw in zip(
                material.candidates, material.audit_raws, strict=True):
            audit = _json.loads(raw.decode("ascii"))
            tensors = build_afterstate_tensors(audit)
            for replica in range(8):
                # The CRN identity stays common across candidates at one
                # state/replica, matching production training semantics.
                continuation_identity = _sha({
                    "namespace": "world-afterstate-v2-capacity-label-v2",
                    "population_sha256": population_identity,
                    "state_sha256": material.state.state_sha256,
                    "replica": replica})
                target_identity = _sha({
                    "namespace": "world-afterstate-v2-capacity-target-v2",
                    "population_sha256": population_identity,
                    "state_sha256": material.state.state_sha256,
                    "candidate_set_sha256": material.candidate_set_sha256,
                    "candidate_index": candidate.candidate_index,
                    "audit_sha256": candidate.audit_sha256,
                    "successor_sha256": candidate.successor_sha256,
                    "replica": replica,
                })
                target = int(target_identity[:8], 16) % OUTCOME_CLASSES
                rows.append(WorldAfterstateV2TrainingExample(
                    deal_sha256=material.state.deal_sha256,
                    slot_sha256=material.state.slot_sha256,
                    state_sha256=material.state.state_sha256,
                    candidate_set_sha256=material.candidate_set_sha256,
                    candidate_index=candidate.candidate_index,
                    protected_incumbent=candidate.protected_incumbent,
                    successor_sha256=candidate.successor_sha256,
                    continuation_sha256=continuation_identity,
                    replica=replica, source=material.state.source, split="fit",
                    role=material.state.role, phase=material.state.phase,
                    position=material.state.position,
                    trump_rank=material.state.trump_rank,
                    trump_mode=material.state.trump_mode,
                    points_bucket=points_bucket, tensors=tensors,
                    signed_level_category=target))
    return tuple(rows)


def _capacity_training_example_population(
        fixtures: Sequence[FixtureV2]) -> tuple[Any, ...]:
    """Select an exact paired-fit 128-example capacity population.

    The preflight retains select/audit roots for later DAG stages as well as
    eight complete natural-fit slot pairs for P0 and the world-shuffle
    control.  Capacity pseudo rows must preserve that split boundary: treating
    a select slot as fit makes the control correctly refuse it as absent from
    the canonical fit ledger.  Roots remain complete, both members of every
    chosen fit pair stay together, and their production epoch order is kept.
    All retained fixtures still enter the pseudo-target population identity.
    """
    examples = _capacity_training_examples(fixtures)
    roots: dict[str, list[Any]] = {}
    for example in examples:
        roots.setdefault(example.root_key, []).append(example)
    ordered_roots = ordered_root_ids_for_epoch(tuple(roots), epoch=1)
    root_position = {root: index for index, root in enumerate(ordered_roots)}

    from .world_afterstate_v2_protocol import fit_pair_id_from_slot_sha256
    pair_roots: dict[str, list[str]] = {}
    for root in ordered_roots:
        rows = roots[root]
        first = rows[0]
        if first.source != "natural" or first.split != "fit":
            continue
        try:
            pair = fit_pair_id_from_slot_sha256(first.slot_sha256)
        except Exception:
            continue
        pair_roots.setdefault(pair, []).append(root)
    paired_groups = []
    for pair, members in pair_roots.items():
        if (len(members) != 2
                or len({roots[root][0].slot_sha256 for root in members}) != 2
                or len({roots[root][0].deal_sha256 for root in members}) != 2):
            continue
        ordered_members = tuple(sorted(
            members, key=lambda root: root_position[root]))
        paired_groups.append((
            min(root_position[root] for root in ordered_members),
            pair, ordered_members))
    paired_groups.sort()

    selections: dict[int, tuple[tuple[str, ...], ...]] = {0: ()}
    for _position, _pair, members in paired_groups:
        count = sum(len(roots[root]) for root in members)
        for prior_count, prior_roots in tuple(
                sorted(selections.items(), reverse=True)):
            combined = prior_count + count
            if (combined <= CAPACITY_TRAINING_EXAMPLES
                    and combined not in selections):
                selections[combined] = (*prior_roots, members)
    selected_groups = selections.get(CAPACITY_TRAINING_EXAMPLES)
    if selected_groups is None:
        raise CapacityRunnerError(
            "capacity training cannot form one complete 128-example "
            "paired-fit batch")
    selected_set = {root for group in selected_groups for root in group}
    selected_roots = tuple(root for root in ordered_roots
                           if root in selected_set)
    selected = tuple(example for root in selected_roots
                     for example in roots[root])
    schedule, batches = training_epoch_batches(
        selected, epoch=1, batch_example_cap=CAPACITY_TRAINING_EXAMPLES)
    if (len(batches) != 1
            or batches[0].size != CAPACITY_TRAINING_EXAMPLES
            or tuple(schedule.ordered_root_ids) != selected_roots):
        raise CapacityRunnerError("capacity training batch schedule drift")
    return selected


def _capacity_training_batch(fixtures: Sequence[FixtureV2]) -> Any:
    """Collate the frozen exact 128-example capacity population."""
    selected = _capacity_training_example_population(fixtures)
    _schedule, batches = training_epoch_batches(
        selected, epoch=1, batch_example_cap=CAPACITY_TRAINING_EXAMPLES)
    return batches[0]


def _capacity_cohort_select_population(
        fixtures: Sequence[FixtureV2]) -> EpochSelectPopulationV2:
    """Build a deterministic, target-free epoch-select population.

    The retained select roots are already sealed in the fixture materials.
    Their synthetic category values are capacity workload inputs derived only
    from public identities; no scientific continuation or outcome is opened.
    """
    values = tuple(sorted(
        (fixture.material for fixture in fixtures
         if fixture.material is not None
         and fixture.material.state.split == "select"
         and fixture.material.state.select_subfold == "epoch-select"),
        key=lambda material: material.state.deal_sha256))
    if not values:
        raise CapacityRunnerError("capacity cohort select population missing")
    roots = tuple(build_inference_root_v2(material) for material in values)
    from .world_afterstate import OUTCOME_CLASSES
    outcomes = []
    for root in roots:
        for candidate, successor in enumerate(root.successor_sha256s):
            for replica in range(8):
                continuation = _sha({
                    "namespace": "world-afterstate-v2-capacity-cohort-continuation-v1",
                    "root_sha256": root.root_sha256, "replica": replica})
                category = int(_sha({
                    "namespace": "world-afterstate-v2-capacity-cohort-category-v1",
                    "root_sha256": root.root_sha256,
                    "candidate_index": candidate, "replica": replica,
                })[:8], 16) % OUTCOME_CLASSES
                outcomes.append(ContinuationOutcomeV2(
                    deal_sha256=root.deal_sha256,
                    slot_sha256=root.slot_sha256,
                    state_sha256=root.state_sha256,
                    candidate_set_sha256=root.candidate_set_sha256,
                    source=root.source, split="select", role=root.role,
                    phase=root.phase, position=root.position,
                    trump_rank=root.trump_rank, trump_mode=root.trump_mode,
                    points_bucket=root.points_bucket,
                    candidate_index=candidate,
                    protected_incumbent=candidate == 0,
                    successor_sha256=successor,
                    continuation_sha256=continuation, replica=replica,
                    signed_level_category=category))
    result = EpochSelectPopulationV2(roots, tuple(outcomes))
    result.validate()
    return result


def _capacity_cohort_populations(
        fixtures: Sequence[FixtureV2]) -> tuple[
            tuple[Any, ...], tuple[
                tuple[str, int, tuple[Any, ...], tuple[Any, ...] | None], ...],
            EpochSelectPopulationV2]:
    """Prepare the exact concurrent-wave cohorts for one benchmark pass.

    The scientific wave pairs the three block-1 controls with the independent
    block-2 natural cohort.  Keeping the seed block in the task identity avoids
    benchmarking four superficially named block-1 cohorts instead.
    """
    try:
        # The design freezes one identical complete-root 128-example workload
        # for every cohort arm.  The unpermuted cohort is called ``natural``
        # because it is the control baseline; capacity pseudo-targets remain
        # score-free and bind all 32 retained materials through their identity.
        natural = _capacity_training_example_population(fixtures)
        transforms = {
            CONTROL_NAMES[0]: action_association_permutation,
            CONTROL_NAMES[1]: label_permutation,
            CONTROL_NAMES[2]: complete_world_shuffle,
        }
        tasks: list[tuple[
            str, int, tuple[Any, ...], tuple[Any, ...] | None]] = [
                ("natural", 2, natural, None)]
        for name in CONTROL_NAMES:
            controlled, evidence = transforms[name](natural)
            validate_control_evidence(
                evidence, natural=natural, controlled=controlled)
            rows = control_training_examples(controlled)
            tasks.append((name, 1, rows, natural))
        selection = _capacity_cohort_select_population(fixtures)
    except CapacityRunnerError:
        raise
    except WorldAfterstateV2ControlError as exc:
        raise CapacityRunnerError(
            f"capacity cohort control population refused: {exc}") from exc
    except Exception as exc:
        raise CapacityRunnerError(
            "capacity cohort populations could not be built: "
            f"{type(exc).__name__}") from exc
    return natural, tuple(tasks), selection


def _cohort_checkpoint_rows(payload: tuple[
        str, int, tuple[Any, ...], tuple[Any, ...] | None,
        EpochSelectPopulationV2, str, Any]) -> dict[str, Any]:
    """Train one cohort and return only sealed checkpoint identity rows.

    This is a process entry point on purpose.  The production stage isolates
    controller processes because the reviewed controller temporarily changes
    Torch's process-global thread setting.  Returning only digest rows keeps
    the model/build objects inside the child and out of the parent IPC path.
    """
    name, seed_block, rows, natural, selection, freeze_sha256, config = payload
    if seed_block not in (1, 2) \
            or (name == "natural") is not (seed_block == 2):
        raise CapacityRunnerError("capacity cohort seed-block drift")
    import tempfile
    build = train_named_cohort(
        cohort_name=name, values=rows, natural_values=natural,
        freeze_sha256=freeze_sha256, config=config,
        selection_population=selection, seed_block=seed_block,
        member_workers=COHORT_MEMBER_WORKERS,
        torch_threads=PINNED_TORCH_THREADS,
        batch_example_cap=TRAINING_BATCH_EXAMPLE_CAP,
        wall_budget_nanoseconds=2 * 60 * 60 * 1_000_000_000)
    models, manifest = reopen_cohort_build(build)
    if (len(models) != COHORT_MEMBER_WORKERS
            or manifest.get("cohort_name") != name
            or manifest.get("seed_block") != seed_block
            or len(build.selected_checkpoint_raws) != COHORT_MEMBER_WORKERS):
        raise CapacityRunnerError("capacity cohort reopen drift")
    with tempfile.TemporaryDirectory(
            prefix="shengji-v2-capacity-cohort-ephemeral-") as raw_root:
        ephemeral_root = Path(raw_root)
        if tuple(ephemeral_root.iterdir()):
            raise CapacityRunnerError("capacity cohort ephemeral root contaminated")
        checkpoints = []
        for member, raw in enumerate(build.selected_checkpoint_raws):
            publish_checkpoint_shard(
                ephemeral_root, raw, cohort=name, seed_block=seed_block,
                member_index=member, epoch=1)
            _model, metadata = reopen_checkpoint_shard(
                ephemeral_root, name, seed_block, member, 1)
            checkpoints.append({
                "task": name, "seed_block": seed_block, "member": member,
                "sha256": _sha_bytes(raw),
                "checkpoint_sha256": metadata["checkpoint_sha256"],
            })
        if len(checkpoints) != COHORT_MEMBER_WORKERS:
            raise CapacityRunnerError("capacity cohort checkpoint count drift")
    return {"task": name, "seed_block": seed_block,
            "checkpoints": tuple(checkpoints)}


def _cohort_controller_group(payload: tuple[
        str, tuple[
            tuple[str, int, tuple[Any, ...], tuple[Any, ...] | None], ...],
        EpochSelectPopulationV2, str, Any, int]) -> tuple[dict[str, Any], ...]:
    """Run one production controller group inside its isolated process."""
    group, tasks, selection, freeze_sha256, config, variant = payload
    prepared = tuple((name, block, rows, natural, selection,
                      freeze_sha256, config)
                    for name, block, rows, natural in tasks)
    with controller_process_torch_scope(PINNED_TORCH_THREADS):
        if group == "controls":
            workers = 1 if variant == 1 else variant - 1
            with ThreadPoolExecutor(max_workers=workers) as pool:
                return tuple(pool.map(_cohort_checkpoint_rows, prepared))
        if group == "natural":
            if len(prepared) != 1:
                raise CapacityRunnerError("capacity natural controller group drift")
            return (_cohort_checkpoint_rows(prepared[0]),)
        raise CapacityRunnerError("capacity controller group drift")


def _run_cohort_concurrency_benchmark(
        fixtures: Sequence[FixtureV2], variant: int) -> str:
    """Run four real cohorts at production member width and seal outputs."""
    if variant not in (1, 2, 4):
        raise CapacityRunnerError("cohort concurrency width drift")
    _natural, tasks, selection = _capacity_cohort_populations(fixtures)
    from .world_afterstate_v2_training import WorldAfterstateV2TrainingConfig

    config = WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=10_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=1.0)
    freeze_sha256 = _sha({
        "namespace": "world-afterstate-v2-capacity-cohort-freeze-v1",
        "fixtures": [fixture.fixture_sha256 for fixture in fixtures]})

    controls = tuple(tasks[1:])
    groups = (
        ("controls", controls),
        ("natural", (tasks[0],)),
    )
    payloads = tuple((group, group_tasks, selection, freeze_sha256,
                      config, variant)
                    for group, group_tasks in groups)
    pool_kwargs = {
        **verified_process_pool_kwargs(),
        "mp_context": multiprocessing.get_context("spawn"),
    }
    if variant == 1:
        # Width one is a serial prefix, with a fresh isolated controller
        # process for each production group.
        grouped = []
        for payload in payloads:
            with ProcessPoolExecutor(max_workers=1, **pool_kwargs) as pool:
                group_result, = tuple(
                    pool.map(_cohort_controller_group, (payload,)))
                grouped.append(group_result)
        rows = tuple(item for result in grouped for item in result)
    else:
        # Width two/four retain the production two-controller wave.  The
        # controls process schedules one or three controls internally.
        with ProcessPoolExecutor(max_workers=2, **pool_kwargs) as pool:
            grouped = tuple(pool.map(_cohort_controller_group, payloads))
        rows = tuple(item for result in grouped for item in result)
    by_name = {row["task"]: row for row in rows}
    if set(by_name) != {"natural", *CONTROL_NAMES}:
        raise CapacityRunnerError("capacity cohort task population drift")
    if (by_name["natural"]["seed_block"] != 2
            or any(by_name[name]["seed_block"] != 1
                   for name in CONTROL_NAMES)):
        raise CapacityRunnerError("capacity cohort seed-block drift")
    checkpoint_hashes = [
        checkpoint
        for name in ("natural", *CONTROL_NAMES)
        for checkpoint in by_name[name]["checkpoints"]]
    if len(checkpoint_hashes) != 4 * COHORT_MEMBER_WORKERS:
        raise CapacityRunnerError("capacity cohort checkpoint count drift")
    output = _sha({
        "schema": "world-afterstate-v2-capacity-cohort-output-v1",
        "checkpoints": checkpoint_hashes,
    })
    fixture_identity = _ordered_fixture_identity(fixtures)
    if output == fixture_identity:
        raise CapacityRunnerError("capacity cohort output identity did not mutate")
    return output


def _tensor_identity(value: Any) -> str:
    """Digest actual model output bytes, including shape and dtype."""
    array = value.detach().cpu().contiguous().numpy()
    return _sha({"shape": list(array.shape), "dtype": str(array.dtype),
                 "bytes": array.tobytes().hex()})


def _batched_prediction_identity(values: Sequence[Any]) -> str:
    """Bind the ordered sealed prediction values across batch partitions.

    Raw float32 logits are not a public V2 artifact and may differ by a few
    ulps when an otherwise identical matrix operation uses another batch
    shape.  Production inference already resolves that permitted numerical
    freedom through its reviewed probability canonicalization and exact PPB
    encoding.  Capacity must compare that same semantic output rather than a
    stricter, non-production intermediate.
    """
    import torch
    from .world_afterstate_v2_inference import _quantize_probability_row
    if not values:
        raise CapacityRunnerError("capacity inference output population missing")
    logits = torch.cat(tuple(values), dim=0)
    probabilities = torch.softmax(logits, dim=1)
    return _sha([list(_quantize_probability_row(row))
                 for row in probabilities])


def _run_with_torch_threads(operation: Callable[[], str], variant: int) -> str:
    """Run identical model work at the reviewed, reproducible width."""
    import torch
    if type(variant) is not int or variant != PINNED_TORCH_THREADS:
        raise CapacityRunnerError("Torch intra-model threads are pinned to 1")
    prior_threads = torch.get_num_threads()
    torch.set_num_threads(PINNED_TORCH_THREADS)
    try:
        return operation()
    finally:
        torch.set_num_threads(prior_threads)


def _process_fixture(payload: tuple[str, int, FixtureV2]) -> str:
    """Process one fixture and digest its actual score-free operation output."""
    stage, variant, fixture = payload
    output = _operation(stage, variant, fixture)()
    # Check before domain separation so a producer returning the fixture's
    # input identity cannot be hidden by the output-identity envelope.
    if isinstance(output, str) and output == fixture.fixture_sha256:
        raise CapacityRunnerError(
            "capacity operation returned fixture input identity")
    return _operation_output_identity(stage, output)


def _parallel_operation(stage: str, variant: int,
                        fixtures: Sequence[FixtureV2]) -> Callable[[], str]:
    """Run one independent process task per fixture at the requested arm width."""
    values = tuple(fixtures)

    # Continuation arms must expose at least two waves at the immediate 64
    # comparison.  Repeating the immutable source fixtures is deterministic
    # and keeps the measured output population independent of arm width.
    measured_units = (CONTINUATION_MIN_WORK_UNITS
                      if stage == "continuation-mechanics" else len(values))
    if measured_units < 1:
        raise CapacityRunnerError("capacity operation fixture population missing")
    if (stage == "continuation-mechanics" and variant >= 64
            and measured_units < variant * 2):
        raise CapacityRunnerError(
            "continuation capacity arm lacks two deterministic work waves")
    work = tuple(values[index % len(values)] for index in range(measured_units))

    def run() -> str:
        with ProcessPoolExecutor(
                max_workers=variant, **verified_process_pool_kwargs()) as pool:
            outputs = tuple(pool.map(
                _process_fixture,
                ((stage, variant, fixture) for fixture in work)))
        return _sha(outputs)
    run.measured_unit_count = measured_units  # type: ignore[attr-defined]
    return run


def _model_operation(stage: str, variant: int,
                     fixtures: Sequence[FixtureV2]) -> Callable[[], str]:
    """Run fixed model work with the requested member/batch shape.

    The member arm captures a typed batch at factory time, outside the
    backend's timed callback.  Cohort-concurrency builds its complete
    production population in isolated controller children. Inference-batch
    remains target-free and inference-only.
    """
    values = tuple(fixtures)
    training_batch = (_capacity_training_batch(values)
                      if stage == "member-concurrency" else None)

    if stage == "member-concurrency":
        measured_units = 4
    elif stage == "cohort-concurrency":
        measured_units = 16
    elif stage == "inference-batch":
        measured_units = sum(len(fixture.audit_raws) for fixture in values)
    else:
        measured_units = len(values)
    if measured_units < 1:
        raise CapacityRunnerError("capacity model fixture population missing")

    def run() -> str:
        import torch
        from .world_afterstate_v2_model import new_world_afterstate_v2_model
        with torch.random.fork_rng(devices=[]):
            # Model initialization is part of the fixed score-free fixture;
            # reset it for every arm so output identity compares work, not
            # process-global RNG state.
            torch.manual_seed(0)
            if stage == "cohort-concurrency":
                # This arm is the production-altitude cohort boundary: four
                # named cohorts, each with the real four-member controller,
                # run in one outer wave.  All preparation and checkpoint
                # reopening stay score-free and deterministic.
                output = [_run_cohort_concurrency_benchmark(values, variant)]
            elif stage == "member-concurrency":
                # Every arm executes the same fixed model population and the
                # same production-formatted 128-row optimizer batch; only
                # executor width varies. State digests bind post-step model
                # bytes rather than inference outputs.
                from .world_afterstate_v2_training import (
                    WorldAfterstateV2TrainingConfig, model_state_sha256,
                    new_optimizer, train_epoch)
                config = WorldAfterstateV2TrainingConfig(
                    learning_rate_ppb=10_000_000, weight_decay_ppb=0,
                    gradient_norm_milli=1_000, max_epochs=1,
                    sigma_pair_squared=1.0)
                model_count = COHORT_MEMBER_WORKERS
                output: list[str] = [""] * model_count
                models = tuple(new_world_afterstate_v2_model(0)
                               for _ in range(model_count))
                def member(index: int) -> None:
                    optimizer = new_optimizer(models[index], config)
                    train_epoch(models[index], optimizer, (training_batch,),
                                epoch=1, config=config)
                    output[index] = model_state_sha256(models[index])
                with ThreadPoolExecutor(max_workers=variant) as pool:
                    # Executor width is the only member-concurrency arm
                    # dimension; fixed population and order are retained.
                    tuple(pool.map(member, range(model_count)))
            else:
                from .world_afterstate import build_afterstate_tensors
                from .world_afterstate_v2_model import collate_world_afterstate_tensors
                tensors = tuple(
                    build_afterstate_tensors(json.loads(raw.decode("ascii")))
                    for fixture in values for raw in fixture.audit_raws)
                if not tensors:
                    raise CapacityRunnerError(
                        "model fixture has no score-free audit bytes")
                model = new_world_afterstate_v2_model(0)
                batches = []
                for start in range(0, len(tensors), variant):
                    chunk = tensors[start:start + variant]
                    batches.append(model(collate_world_afterstate_tensors(chunk)))
                # Batch-size arms bind the exact ordered prediction values
                # that scientific inference seals, not raw-logit ulps or the
                # arbitrary chunk boundaries used to produce them.
                output = [_batched_prediction_identity(batches)]
        return _sha(output)
    run.measured_unit_count = measured_units  # type: ignore[attr-defined]
    return run


def _arm_from_raw(stage: str, variant: int, raw: RawMeasurementV2,
                  fixture_sha: str, stage_wall: int,
                  *, synthetic: bool = False,
                  measured_unit_count: int = 1) -> CapacityArmV2:
    raw.validate()
    if (stage == "continuation-mechanics"
            and (measured_unit_count < CONTINUATION_MIN_WORK_UNITS
                 or (variant >= 64 and measured_unit_count < variant * 2))):
        raise CapacityRunnerError(
            "continuation capacity arm lacks required deterministic work population")
    if raw.byte_identity_sha256 != fixture_sha:
        raise CapacityRunnerError("stage arms are not byte-identical")
    wall_ns = raw.elapsed_ns
    busy_ns = max(1, raw.process_cpu_ns)
    if busy_ns > wall_ns * HOST_CPUS:
        raise CapacityRunnerError("measurement CPU exceeds wall/core envelope")
    wall = _ceil_seconds(wall_ns)
    busy = _ceil_seconds(busy_ns)
    mean = busy_ns * 1_000_000 // (wall_ns * HOST_CPUS)
    samples = raw.sample_utilization_ppm or (mean,)
    p50 = sorted(samples)[len(samples) // 2]
    p95 = sorted(samples)[min(len(samples) - 1, math.ceil(len(samples) * .95) - 1)]
    scaling = min(1_000_000, max(1, mean * HOST_CPUS // max(1, variant)))
    # Shares are bound after all arms are measured, once the projected D256
    # stage categories are available.  Zero is an honest pre-census value,
    # never a fabricated constant.
    share = 0
    arm = CapacityArmV2(
        stage=stage, variant=variant, wall_seconds=wall,
        busy_core_seconds=busy, mean_cpu_utilization_ppm=mean,
        p50_cpu_utilization_ppm=p50, p95_cpu_utilization_ppm=p95,
        scaling_efficiency_ppm=scaling, queue_depth=raw.queue_depth,
        wall_share_ppm=share, peak_memory_bytes=raw.peak_rss_bytes,
        swap_bytes=ZERO_SWAP, task_count=raw.task_count,
        byte_identity_sha256=fixture_sha, cpu_bound=raw.cpu_bound,
        wall_ns=wall_ns, busy_core_ns=busy_ns,
        measured_unit_count=measured_unit_count,
        peak_task_count=max((raw.task_count, *raw.sample_task_counts)))
    # CapacityArmV2 intentionally remains the existing public wire type.  A
    # private in-memory provenance bit prevents a test seam from being
    # relabelled into a production receipt before validation.
    if synthetic:
        object.__setattr__(arm, "_synthetic_measurement", True)
    return arm


def _arm_target_units(
        fixtures: Sequence[FixtureV2],
        measured_counts: Mapping[str, int] | None = None,
        continuation_target_units: int | None = None,
        ) -> dict[str, tuple[int, int]]:
    """Return (measured, target) unit populations for every arm category."""
    source = len(fixtures)
    if source < 1:
        raise CapacityRunnerError("capacity fixture population missing")
    continuation_target = 0
    missing_material = False
    for fixture in fixtures:
        if fixture.material is None:
            # Synthetic seams do not carry production material; their real
            # operation is not executed, but retain the 128-unit shape.
            missing_material = True
        else:
            continuation_target += len(fixture.material.candidates) * 8
    if missing_material:
        continuation_target = max(CONTINUATION_MIN_WORK_UNITS, source)
    if continuation_target_units is not None:
        if type(continuation_target_units) is not int or continuation_target_units < 1:
            raise CapacityRunnerError("capacity continuation target population drift")
        continuation_target = continuation_target_units
    if continuation_target < 1:
        raise CapacityRunnerError("capacity continuation target population missing")
    measured_counts = measured_counts or {}
    return {
        "state-successor": (measured_counts.get("state-successor", source), source),
        "continuation-mechanics": (
            measured_counts.get("continuation-mechanics", CONTINUATION_MIN_WORK_UNITS),
            continuation_target),
        "member-concurrency": (measured_counts.get("member-concurrency", 4), 4),
        "cohort-concurrency": (
            measured_counts.get("cohort-concurrency", 16), 16),
        "inference-batch": (
            measured_counts.get("inference-batch", max(1, sum(
                len(fixture.audit_raws) for fixture in fixtures))),
            max(1, sum(len(fixture.audit_raws) for fixture in fixtures))),
        "reconstruction": (measured_counts.get("reconstruction", source), source),
    }


def _capacity_arm_operation(
        stage: str, variant: int, fixtures: Sequence[FixtureV2],
        fixture_sha256: str, arm_targets: Mapping[str, tuple[int, int]],
        *, synthetic: bool) -> tuple[Callable[[], str], int]:
    """Build one fixed arm operation and retain its measured population."""
    if synthetic:
        def operation() -> str:
            return fixture_sha256
        return operation, arm_targets[stage][0]
    raw_operation = (
        _parallel_operation(stage, variant, fixtures)
        if stage in {"state-successor", "continuation-mechanics",
                     "reconstruction"}
        else _model_operation(stage, variant, fixtures))
    measured = getattr(raw_operation, "measured_unit_count",
                       arm_targets[stage][0])
    if stage in {"member-concurrency", "cohort-concurrency"}:
        def operation() -> str:
            return _run_with_torch_threads(
                raw_operation, PINNED_TORCH_THREADS)
        return operation, measured
    return raw_operation, measured


def _combine_capacity_repeats(
        warm: RawMeasurementV2, measured: RawMeasurementV2) -> RawMeasurementV2:
    """Combine two identical-work observations without hiding their cost."""
    warm.validate()
    measured.validate()
    if (warm.byte_identity_sha256 != measured.byte_identity_sha256
            or warm.cpu_bound is not measured.cpu_bound):
        raise CapacityRunnerError("capacity repeat identity drift")
    return RawMeasurementV2(
        elapsed_ns=warm.elapsed_ns + measured.elapsed_ns,
        process_cpu_ns=warm.process_cpu_ns + measured.process_cpu_ns,
        peak_rss_bytes=max(warm.peak_rss_bytes, measured.peak_rss_bytes),
        task_count=max(warm.task_count, measured.task_count),
        sample_utilization_ppm=(
            *warm.sample_utilization_ppm,
            *measured.sample_utilization_ppm),
        sample_memory_bytes=(
            *warm.sample_memory_bytes, *measured.sample_memory_bytes),
        sample_task_counts=(
            *warm.sample_task_counts, *measured.sample_task_counts),
        sample_swap_bytes=(
            *warm.sample_swap_bytes, *measured.sample_swap_bytes),
        sample_free_disk_bytes=(
            *warm.sample_free_disk_bytes, *measured.sample_free_disk_bytes),
        queue_depth=max(warm.queue_depth, measured.queue_depth),
        disk_bytes_written=(
            warm.disk_bytes_written + measured.disk_bytes_written),
        byte_identity_sha256=warm.byte_identity_sha256,
        cpu_bound=warm.cpu_bound)


def _select_arms(arms: Sequence[CapacityArmV2]) -> dict[str, CapacityArmV2]:
    """Select fastest memory-eligible byte-identical arm per dimension."""
    selected: dict[str, CapacityArmV2] = {}
    for stage in ARM_GRIDS:
        stage_arms = [arm for arm in arms if arm.stage == stage]
        if len({arm.byte_identity_sha256 for arm in stage_arms}) != 1:
            raise CapacityRunnerError("stage arms are not byte-identical")
        eligible = [arm for arm in stage_arms
                    if arm.peak_memory_bytes * 100
                    <= MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX]
        if not eligible:
            raise CapacityRunnerError("no memory-eligible arm")
        selected[stage] = min(
            eligible, key=lambda arm: (arm.wall_ns, arm.variant))
    return selected


def _bind_projected_arm_shares(
        arms: Sequence[CapacityArmV2],
        stage_walls_seconds: Mapping[str, int]) -> tuple[CapacityArmV2, ...]:
    """Bind each measured arm to its disjoint projected D256 category share."""
    shares = projected_arm_wall_shares_ppm(stage_walls_seconds)
    return tuple(__import__("dataclasses").replace(
        arm, wall_share_ppm=shares[arm.stage]) for arm in arms)


def validate_capacity_arm_census_v2(
        arms: Sequence[CapacityArmV2], selected: Mapping[str, CapacityArmV2],
        stage_walls_seconds: Mapping[str, int]) -> tuple[CapacityCensusAssessmentV2, ...]:
    """Fail closed on material low-utilization arms before the full DAG call."""
    try:
        return _validate_capacity_arm_census_contract(
            arms, selected, stage_walls_seconds)
    except WorldAfterstateV2CapacityError as exc:
        raise CapacityRunnerError(
            "capacity arm census refused low-utilization material arm",
            stage="measurement",
            reason_code="arm-census-low-utilization",
            assessments=getattr(exc, "assessments", ())) from exc


@dataclass(frozen=True)
class CapacityRunResultV2:
    receipt: CapacityReceiptV2 | None
    arms: tuple[CapacityArmV2, ...]
    preflight: PreflightResultV2
    synthetic: bool
    brand: str | None

    def production_receipt(self) -> CapacityReceiptV2:
        if self.synthetic or self.receipt is None:
            raise CapacityRunnerError("synthetic measurement cannot publish production receipt")
        return self.receipt


@dataclass(frozen=True)
class RepresentativeDAGV2:
    """Real measured representatives used to project the complete DAG."""

    p0_wall_seconds: int
    label_wall_seconds: int
    epoch_wall_seconds: int
    control_wall_seconds: int
    inference_wall_seconds: int
    audit_wall_seconds: int
    reconstruction_wall_seconds: int
    artifact_bytes: int
    admissible: bool = False
    source_fixture_count: int = PREFLIGHT_ACCEPTED
    stage_walls_seconds: tuple[tuple[str, int], ...] = ()
    stage_wall_nanoseconds: tuple[tuple[str, int], ...] = ()
    # Only the executable full-DAG supervisor may populate this witness.
    progress_recovery: Mapping[str, bool] | None = None
    provenance_token: object | None = None
    attestation_sha256: str | None = None
    stage_source_unit_counts: tuple[tuple[str, int], ...] = ()
    stage_process_cpu_nanoseconds: tuple[tuple[str, int], ...] = ()
    member_workers: int = 0
    continuation_workers: int = 0
    torch_threads: int = 0
    inference_batch: int = 0
    reconstruction_workers: int = 0

    @property
    def stage_cpu_nanoseconds(self) -> tuple[tuple[str, int], ...]:
        """Compatibility spelling for the process-CPU witness."""
        return self.stage_process_cpu_nanoseconds


def _dag_attestation(value: RepresentativeDAGV2) -> str:
    return _sha({
        "p0": value.p0_wall_seconds, "label": value.label_wall_seconds,
        "epoch": value.epoch_wall_seconds, "control": value.control_wall_seconds,
        "inference": value.inference_wall_seconds, "audit": value.audit_wall_seconds,
        "reconstruction": value.reconstruction_wall_seconds,
        "artifact_bytes": value.artifact_bytes,
        "admissible": value.admissible,
        "source_fixture_count": value.source_fixture_count,
        "stage_walls_seconds": list(value.stage_walls_seconds),
        "stage_wall_nanoseconds": list(value.stage_wall_nanoseconds),
        "stage_source_unit_counts": list(value.stage_source_unit_counts),
        "stage_process_cpu_nanoseconds": list(value.stage_process_cpu_nanoseconds),
        "member_workers": value.member_workers,
        "continuation_workers": value.continuation_workers,
        "torch_threads": value.torch_threads,
        "inference_batch": value.inference_batch,
        "reconstruction_workers": value.reconstruction_workers,
        "progress_recovery": value.progress_recovery,
    })


def _progress_event(stage: str, completed: int, total: int, workers: int,
                    started_ns: int, stage_wall: int,
                    utilization_ppm: int,
                    callback: Callable[[dict[str, Any]], None] | None,
                    *, now_ns: int | None = None) -> None:
    observed_ns = time.perf_counter_ns() if now_ns is None else now_ns
    elapsed_ns = observed_ns - started_ns
    if elapsed_ns < 0:
        raise CapacityRunnerError("capacity progress clock moved backwards")
    if elapsed_ns >= MAX_COMMAND_WALL_SECONDS * 1_000_000_000:
        raise CapacityRunnerError("capacity command wall cap expired")
    if callback is None:
        return
    elapsed_seconds = elapsed_ns // 1_000_000_000
    elapsed = elapsed_ns / 1_000_000_000
    fraction = completed / max(1, total)
    eta = 0 if completed == 0 else max(0, int(elapsed * (1 - fraction) / fraction))
    callback({
        "stage": stage, "completed_units": completed, "total_units": total,
        "workers": workers, "utilization_ppm": utilization_ppm,
        "elapsed_seconds": elapsed_seconds, "eta_seconds": eta,
        "headroom_seconds": MAX_COMMAND_WALL_SECONDS - elapsed_seconds,
        "memory_bytes": _cgroup_memory_bytes(),
        "peak_memory_bytes": _cgroup_memory_bytes(),
        "queue_depth": max(0, _task_count() - workers),
        "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
        "immutable_shards": 0, "checkpoint_count": 0,
    })


def _scientific_stage_units(spec: Any) -> dict[str, int]:
    """Return the frozen scientific work units for one capacity tier."""
    fit = spec.fit
    return {
        "optimizer-canary": 16 * 500,
        # Nested 25/50 each train a prefix for all epochs and then perform the
        # fit/select epoch-selection evaluation.  Nested-100 reuses the
        # already-fitted member and therefore pays evaluation only.
        "nested-curve-25": max(1, fit * 25 // 100) * MAX_EPOCHS + spec.select,
        "nested-curve-50": max(1, fit * 50 // 100) * MAX_EPOCHS + spec.select,
        "nested-curve-100": fit + spec.select,
        "p0": P0_DEALS,
        # P0 labels are a strict pre-P0 spend.  The remaining fit labels and
        # epoch-select half are opened after P0+optimizer; precision-select
        # and audit labels each wait for their respective durable boundary.
        "label-p0": P0_DEALS,
        "label-fit": fit - P0_DEALS + spec.select // 2,
        "label-precision-select": spec.select // 2,
        "label-audit": spec.audit,
        "block-1-natural": fit * MAX_EPOCHS,
        "block-1-action-association-permutation": fit * MAX_EPOCHS,
        "block-1-label-permutation": fit * MAX_EPOCHS,
        "block-1-complete-world-shuffle": fit * MAX_EPOCHS,
        "block-2-natural": fit * MAX_EPOCHS,
        "block-2-complete-world-shuffle": fit * MAX_EPOCHS,
        "precision-select-inference": spec.select,
        "precision-select": spec.select,
        "audit": spec.audit,
        "reconstruction": spec.total,
    }


def _composed_projection(selected: Mapping[str, CapacityArmV2],
                         fixture_count: int, free_disk_bytes: int,
                         dag: RepresentativeDAGV2 | None = None,
                         arm_target_units: Mapping[str, tuple[int, int]] | None = None
                         ) -> ComposedProjectionV2:
    if arm_target_units is None:
        arm_target_units = {
            stage: (selected[stage].measured_unit_count, fixture_count)
            for stage in ARM_GRIDS}
    if set(arm_target_units) != set(ARM_GRIDS):
        raise CapacityRunnerError("capacity arm target unit mapping drift")
    for stage, (measured, target) in arm_target_units.items():
        if (type(measured) is not int or measured < 1
                or type(target) is not int or target < 1):
            raise CapacityRunnerError("capacity arm target unit mapping drift")

    def wall(stage: str, multiplier: int = 1) -> int:
        if stage in arm_target_units:
            measured, target = arm_target_units[stage]
            projected_ns = (selected[stage].wall_ns * target + measured - 1) // measured
            return _ceil_seconds(projected_ns)
        return max(1, selected[stage].wall_seconds * max(1, multiplier))
    base = wall("state-successor")
    continuation = wall("continuation-mechanics")
    measured = dict(dag.stage_walls_seconds) if dag else {}
    measured_cpu = (dict(dag.stage_process_cpu_nanoseconds)
                    if dag else {})
    if dag:
        source = max(1, dag.source_fixture_count)
        # These are the reviewed D256 populations, expressed per measured
        # retained-sample stage.  Fixed canary work remains 16 roots/500
        # optimizer steps; split/cohort stages have distinct populations.
        projected_units = _scientific_stage_units(TIER_SPECS[0])
        source_units = dict(dag.stage_source_unit_counts)
        fit_source = max(1, source // 2)
        units = {
            "optimizer-canary": (16 * 500, projected_units["optimizer-canary"]),
            "nested-curve-25": (max(1, fit_source * 25 // 100) + fit_source,
                                 projected_units["nested-curve-25"]),
            "nested-curve-50": (max(1, fit_source * 50 // 100) + fit_source,
                                 projected_units["nested-curve-50"]),
            "nested-curve-100": (fit_source, projected_units["nested-curve-100"]),
            "label-p0": (source, projected_units["label-p0"]),
            "p0": (source, projected_units["p0"]),
            "label-fit": (source, projected_units["label-fit"]),
            "block-1-natural": (source, projected_units["block-1-natural"]),
            "block-2-natural": (source, projected_units["block-2-natural"]),
            "block-1-action-association-permutation": (source,
                projected_units["block-1-action-association-permutation"]),
            "block-1-label-permutation": (source,
                projected_units["block-1-label-permutation"]),
            "block-1-complete-world-shuffle": (source,
                projected_units["block-1-complete-world-shuffle"]),
            "block-2-complete-world-shuffle": (source,
                projected_units["block-2-complete-world-shuffle"]),
            "precision-select-inference": (source, TIER_SPECS[0].select),
            "label-precision-select": (source,
                projected_units["label-precision-select"]),
            "precision-select": (source, TIER_SPECS[0].select),
            "audit": (source, TIER_SPECS[0].audit),
            "label-audit": (source, projected_units["label-audit"]),
            "reconstruction": (source, TIER_SPECS[0].total),
        }
        if source_units:
            units = {name: (source_units.get(name, source), projected)
                     for name, (_sample, projected) in units.items()}
        stage_units = tuple((name, *units[name]) for name in COMPOSED_STAGE_NAMES)
        def measured_wall(name: str, fallback: int) -> int:
            sample, projected = units[name]
            seconds = measured.get(name, fallback)
            return max(1, (seconds * projected + sample - 1) // sample)
        measured_cpu_seconds = {
            name: max(1, (value + 999_999_999) // 1_000_000_000)
            for name, value in measured_cpu.items()}
        def projected_cpu(name: str, fallback: int) -> int:
            sample, projected = units[name]
            seconds = measured_cpu_seconds.get(name, fallback)
            return max(1, (seconds * projected + sample - 1) // sample)
        def projected_parallel_wall(name: str, fallback: int,
                                    arm_name: str) -> int:
            """Project parallel work without scaling an underfilled makespan.

            The representative label buckets may contain fewer deals than the
            selected worker width.  Multiplying that stage wall by
            target/source therefore counts the representative's idle cores in
            every projected unit.  Scale the exact measured CPU work instead
            and translate it back to wall with the independently measured,
            saturated arm for the same operation class.  Retain the measured
            stage wall as a fixed-cost/largest-task floor.
            """
            sample, projected = units[name]
            cpu_ns = measured_cpu.get(name)
            if cpu_ns is None:
                return measured_wall(name, fallback)
            arm = selected[arm_name]
            utilization_ppm = arm.mean_cpu_utilization_ppm
            if utilization_ppm < 1:
                raise CapacityRunnerError(
                    "parallel projection utilization drift")
            projected_cpu_ns = (
                cpu_ns * projected + sample - 1) // sample
            projected_wall_ns = (
                projected_cpu_ns * 1_000_000
                + HOST_CPUS * utilization_ppm - 1
            ) // (HOST_CPUS * utilization_ppm)
            return max(measured.get(name, fallback),
                       _ceil_seconds(projected_wall_ns))
    else:
        stage_units = ()
        def measured_wall(name: str, fallback: int) -> int:
            return fallback
        measured_cpu_seconds = {}
        def projected_cpu(name: str, fallback: int) -> int:
            return fallback
        def projected_parallel_wall(name: str, fallback: int,
                                    arm_name: str) -> int:
            del arm_name
            return measured_wall(name, fallback)
    # Continuation target units already equal the complete candidate*8 label
    # workload; multiplying its wall by eight would count the population twice.
    label = max(1, base + continuation)
    inference = measured_wall("precision-select-inference", dag.inference_wall_seconds
                              if dag else wall("inference-batch", fixture_count))
    reconstruction = measured_wall("reconstruction", dag.reconstruction_wall_seconds
                                   if dag else wall("reconstruction", fixture_count))
    p0 = measured_wall("p0", dag.p0_wall_seconds if dag else label)
    epoch = measured_wall("block-1-natural", dag.epoch_wall_seconds if dag else label)
    controls = measured_wall("block-1-complete-world-shuffle",
                             dag.control_wall_seconds if dag else label)
    audit = measured_wall("audit", dag.audit_wall_seconds if dag else label)
    values = (
        ("label-p0", projected_parallel_wall(
            "label-p0", p0, "continuation-mechanics")),
        ("p0", p0),
        ("optimizer-canary", measured_wall("optimizer-canary", wall("state-successor"))),
        ("label-fit", projected_parallel_wall(
            "label-fit", label, "continuation-mechanics")),
        ("nested-curve-25", measured_wall("nested-curve-25", max(1, base // 4))),
        ("nested-curve-50", measured_wall("nested-curve-50", max(1, base // 2))),
        ("block-1-natural", epoch),
        ("nested-curve-100", measured_wall("nested-curve-100", base)),
        ("block-1-action-association-permutation",
         measured_wall("block-1-action-association-permutation", controls)),
        ("block-1-label-permutation",
         measured_wall("block-1-label-permutation", controls)),
        ("block-1-complete-world-shuffle", controls),
        ("block-2-natural", measured_wall("block-2-natural", epoch)),
        ("block-2-complete-world-shuffle",
         measured_wall("block-2-complete-world-shuffle", controls)),
        ("precision-select-inference", inference),
        ("label-precision-select", projected_parallel_wall(
            "label-precision-select", inference, "continuation-mechanics")),
        ("precision-select", measured_wall("precision-select", inference)),
        ("label-audit", projected_parallel_wall(
            "label-audit", audit, "continuation-mechanics")),
        ("audit", audit),
        ("reconstruction", reconstruction),)
    cpu_values = tuple((name, projected_cpu(name,
        max(1, values[index][1] * HOST_CPUS)))
        for index, (name, _value) in enumerate(values))
    cohort_workers = selected["cohort-concurrency"].variant
    dag_edges = composed_dag_edges_for_cohort_workers(cohort_workers)
    total = composed_critical_path_seconds(dict(values), dag_edges)
    artifact = (max(1, (dag.artifact_bytes * TIER_SPECS[0].total
                        + max(1, dag.source_fixture_count) - 1)
                     // max(1, dag.source_fixture_count))
                if dag else fixture_count * 1024)
    return ComposedProjectionV2(
        stage_walls_seconds=values, composed_wall_seconds=total,
        peak_memory_bytes=max(1, max(arm.peak_memory_bytes for arm in selected.values())),
        composed_artifact_bytes=artifact, free_disk_bytes_before=free_disk_bytes,
        stage_unit_counts=stage_units,
        measured_stage_walls_seconds=(
            tuple(dag.stage_walls_seconds) if dag else ()),
        measured_stage_wall_nanoseconds=(
            tuple(dag.stage_wall_nanoseconds) if dag else ()),
        measured_stage_cpu_nanoseconds=(
            tuple(dag.stage_process_cpu_nanoseconds) if dag else ()),
        stage_cpu_seconds=cpu_values,
        measured_stage_cpu_seconds=(
            tuple((name, max(1, (value + 999_999_999) // 1_000_000_000))
                  for name, value in dag.stage_process_cpu_nanoseconds)
            if dag else ()),
        cohort_workers=cohort_workers,
        dag_edges=dag_edges,
        arm_target_unit_counts=tuple(
            (stage, *arm_target_units[stage]) for stage in arm_target_units))


def _tiers(composed: ComposedProjectionV2, *,
           preflight_wall_nanoseconds: int) -> tuple[TierProjectionV2, ...]:
    if (type(preflight_wall_nanoseconds) is not int
            or preflight_wall_nanoseconds < 1):
        raise CapacityRunnerError("preflight wall projection drift")
    stage = dict(composed.stage_walls_seconds)
    base_units = {name: projected for name, _measured, projected
                  in composed.stage_unit_counts}
    base_cpu = dict(composed.stage_cpu_seconds)
    if not base_units:
        base_units = {name: 1 for name in stage}
    if not base_cpu:
        base_cpu = {name: max(1, seconds * HOST_CPUS)
                    for name, seconds in stage.items()}
    result = []
    for spec in TIER_SPECS:
        target_units = _scientific_stage_units(spec)
        projected_stage = {
            name: max(1, (seconds * target_units[name]
                          + base_units[name] - 1) // base_units[name])
            for name, seconds in stage.items()
        }
        projected_cpu = {
            name: max(1, (base_cpu[name] * target_units[name]
                          + base_units[name] - 1) // base_units[name])
            for name in stage}
        population_wall_seconds = _ceil_seconds(
            (preflight_wall_nanoseconds * spec.total
             + PREFLIGHT_ACCEPTED - 1) // PREFLIGHT_ACCEPTED)
        post_population_wall_seconds = composed_critical_path_seconds(
            projected_stage, composed.dag_edges)
        result.append(TierProjectionV2(
            tier=spec.name,
            # The first reviewed scientific implementation composes only the
            # exact D256 population.  Keep larger projections visible for a
            # future source amendment, but never let host speed alone freeze a
            # tier whose population/adapters cannot actually be produced.
            exact_source_supply=spec.name == "D256",
            # Label cost is the sum of the four measured label buckets, not an
            # arbitrary share of the composed total.  CPU is the same exact
            # work category in the projected tier.
            label_wall_seconds=sum(projected_stage[name] for name in (
                "label-p0", "label-fit", "label-precision-select", "label-audit")),
            label_cpu_seconds=sum(projected_cpu[name] for name in (
                "label-p0", "label-fit", "label-precision-select", "label-audit")),
            population_wall_seconds=population_wall_seconds,
            complete_dag_wall_seconds=(population_wall_seconds
                                       + post_population_wall_seconds),
            peak_memory_bytes=composed.peak_memory_bytes,
            composed_artifact_bytes=max(
                1, composed.composed_artifact_bytes * spec.total
                // TIER_SPECS[0].total),
            free_disk_bytes_before=composed.free_disk_bytes_before))
    return tuple(result)


def build_receipt_v2(arms: Sequence[CapacityArmV2], *, host: HostTelemetryV2,
                     preflight: PreflightResultV2,
                     source_sha256: str,
                     runtime_sha256: str,
                     synthetic: bool = False,
                     representative_dag: RepresentativeDAGV2 | None = None,
                     capacity_assessments: Sequence[
                         CapacityCensusAssessmentV2] = (),
                     _provenance: object | None = None) -> CapacityReceiptV2:
    """Derive and validate one receipt from measured arms only."""
    if synthetic or _provenance is not _PRODUCTION_PROVENANCE:
        raise CapacityRunnerError("synthetic measurement cannot build production receipt")
    if representative_dag is None:
        raise FullDAGCapacityDependencyBlocked(
            "complete admissible full-DAG measurement is required")
    if not representative_dag.admissible:
        raise FullDAGCapacityDependencyBlocked(
            "non-admissible representative DAG cannot issue a receipt")
    if representative_dag.provenance_token is not _FULL_DAG_PROVENANCE:
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG witness provenance is not executable")
    if representative_dag.attestation_sha256 != _dag_attestation(representative_dag):
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG witness attestation drift")
    stage_rows = representative_dag.stage_walls_seconds
    if (type(stage_rows) is not tuple
            or tuple(name for name, _ in stage_rows) != COMPOSED_STAGE_NAMES
            or any(type(seconds) is not int or seconds < 1
                   for _, seconds in stage_rows)):
        raise FullDAGCapacityDependencyBlocked(
            "complete full-DAG stage timing witness is missing")
    stage_ns_rows = representative_dag.stage_wall_nanoseconds
    if (type(stage_ns_rows) is not tuple
            or tuple(name for name, _ in stage_ns_rows) != COMPOSED_STAGE_NAMES
            or any(type(value) is not int or value < 1
                   for _, value in stage_ns_rows)
            or any(seconds != _ceil_seconds(ns)
                   for (_, seconds), (_, ns) in zip(stage_rows, stage_ns_rows))):
        raise FullDAGCapacityDependencyBlocked(
            "complete full-DAG exact wall timing witness is missing")
    unit_rows = representative_dag.stage_source_unit_counts
    if (type(unit_rows) is not tuple
            or tuple(name for name, _ in unit_rows) != COMPOSED_STAGE_NAMES
            or any(type(value) is not int or value < 1 for _, value in unit_rows)):
        raise FullDAGCapacityDependencyBlocked(
            "complete full-DAG representative unit witness is missing")
    cpu_rows = representative_dag.stage_process_cpu_nanoseconds
    if (type(cpu_rows) is not tuple
            or tuple(name for name, _ in cpu_rows) != COMPOSED_STAGE_NAMES
            or any(type(value) is not int or value < 1 for _, value in cpu_rows)):
        raise FullDAGCapacityDependencyBlocked(
            "complete full-DAG process CPU witness is missing")
    required_recovery = (
        "reports_stage_counts", "reports_active_workers_and_cpu",
        "reports_elapsed_eta_headroom", "reports_current_peak_cgroup_memory",
        "reports_immutable_shard_checkpoint_count", "resumes_verified_shards_only",
        "resume_same_admission", "resume_cannot_regenerate_replace_select",
        "checkpoints_each_common_epoch", "deadline_truncation_keeps_complete_epoch",
        "audit_requires_complete_upstream", "audit_attempt_fsynced_before_open",
        "one_audit_open", "reconstruction_without_retraining",
        "reconstruction_reuses_immutable_continuations")
    capabilities = representative_dag.progress_recovery
    if type(capabilities) is not dict or any(
            capabilities.get(name) is not True for name in required_recovery):
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG progress/recovery capabilities are not proven")
    preflight.validate()
    host.validate()
    arms = tuple(arms)
    for arm in arms:
        if getattr(arm, "_synthetic_measurement", False):
            raise CapacityRunnerError("synthetic measurement cannot build production receipt")
        arm.validate()
    selected = _select_arms(arms)
    layout = (selected["member-concurrency"].variant,
               selected["continuation-mechanics"].variant,
               PINNED_TORCH_THREADS,
               selected["inference-batch"].variant,
               selected["reconstruction"].variant)
    dag_layout = (representative_dag.member_workers,
                  representative_dag.continuation_workers,
                  representative_dag.torch_threads,
                  representative_dag.inference_batch,
                  representative_dag.reconstruction_workers)
    if dag_layout != layout:
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG resource layout mismatch")
    composed = _composed_projection(
        selected, len(preflight.accepted_fixtures), host.free_disk_bytes,
            representative_dag,
            arm_target_units=_arm_target_units(
                preflight.accepted_fixtures,
                {stage: selected[stage].measured_unit_count for stage in ARM_GRIDS},
                continuation_target_units=sum(
                    candidate * count * 8
                    for candidate, count in preflight.candidate_distribution)))
    arms = _bind_projected_arm_shares(arms, dict(composed.stage_walls_seconds))
    selected = {stage: next(arm for arm in arms if arm.stage == stage
                            and arm.variant == selected[stage].variant)
                for stage in ARM_GRIDS}
    all_core_gate_passed = derive_all_core_gate_passed(
        arms, dict(composed.stage_walls_seconds),
        dict(representative_dag.stage_wall_nanoseconds),
        dict(representative_dag.stage_process_cpu_nanoseconds))
    if (tuple(row[0] for row in composed.stage_unit_counts)
            != COMPOSED_STAGE_NAMES):
        raise FullDAGCapacityDependencyBlocked(
            "full-DAG measured/projected stage units are missing")
    try:
        from .world_afterstate_v2_model import (
            count_trainable_parameters, new_world_afterstate_v2_model)
        parameter_count = int(count_trainable_parameters(
            new_world_afterstate_v2_model(0)))
    except Exception as exc:
        raise CapacityRunnerError("model parameter measurement unavailable") from exc
    capabilities = dict(representative_dag.progress_recovery)
    progress = ProgressRecoveryV2(
        progress_interval_seconds=60, progress_interval_fraction_ppm=10_000,
        **{name: capabilities[name] for name in (
            "reports_stage_counts", "reports_active_workers_and_cpu",
            "reports_elapsed_eta_headroom", "reports_current_peak_cgroup_memory",
            "reports_immutable_shard_checkpoint_count",
            "resumes_verified_shards_only", "resume_same_admission",
            "resume_cannot_regenerate_replace_select",
            "checkpoints_each_common_epoch",
            "deadline_truncation_keeps_complete_epoch",
            "audit_requires_complete_upstream", "audit_attempt_fsynced_before_open",
            "one_audit_open", "reconstruction_without_retraining",
            "reconstruction_reuses_immutable_continuations")})
    receipt = CapacityReceiptV2(
        host_logical_cpus=host.logical_cpus,
        # Arms run sequentially and the complete DAG follows them.  Taking
        # max(arms, DAG) silently under-counts command wall time.
        command_wall_seconds=sum(arm.wall_seconds for arm in arms)
        + _ceil_seconds(preflight.elapsed_wall_nanoseconds)
        + sum(value for _, value in composed.measured_stage_walls_seconds),
        memory_limit_bytes=host.memory_limit_bytes, swap_bytes=host.swap_bytes,
        task_count=max((arm.peak_task_count or arm.task_count)
                        for arm in arms), arms=arms,
        selected_arms=tuple(selected.values()), composed=composed,
        tiers=_tiers(
            composed,
            preflight_wall_nanoseconds=preflight.elapsed_wall_nanoseconds),
        progress_recovery=progress,
        source_sha256=source_sha256,
        runtime_sha256=runtime_sha256,
        preflight_wall_nanoseconds=preflight.elapsed_wall_nanoseconds,
        authority=dict(AUTHORITY), model_parameter_count=parameter_count,
        candidate_distribution=preflight.candidate_distribution,
        per_epoch_wall_seconds=(representative_dag.epoch_wall_seconds
                                if representative_dag else
                            selected["member-concurrency"].wall_seconds),
        peak_task_count=max((arm.peak_task_count or arm.task_count)
                        for arm in arms), measurement_scope=MEASUREMENT_SCOPE)
    receipt = __import__("dataclasses").replace(
        receipt, member_workers=layout[0], continuation_workers=layout[1],
        torch_threads=layout[2], inference_batch=layout[3],
        reconstruction_workers=layout[4],
        all_core_gate_passed=all_core_gate_passed)
    try:
        validate_capacity_receipt_v2(receipt)
    except WorldAfterstateV2CapacityError as exc:
        if str(exc) == "composed projection cap drift":
            raise CapacityRunnerError(
                str(exc), stage="full-dag",
                reason_code="composed-projection-cap-drift",
                assessments=capacity_assessments,
                projection_diagnostic=(
                    RejectedProjectionDiagnosticV2.from_projection(composed))) \
                from exc
        raise CapacityRunnerError(str(exc)) from exc
    return receipt


def measure_capacity_v2(*, preflight: PreflightResultV2 | None = None,
                        backend: MeasurementBackendV2 | None = None,
                        host: HostTelemetryV2 | None = None,
                        progress: Callable[[dict[str, Any]], None] | None = None,
                        output_root: Path | None = None,
                        source_sha256: str | None = None,
                        runtime_sha256: str | None = None,
                        production: bool = True) -> CapacityRunResultV2:
    started = time.perf_counter_ns()
    deadline_ns = started + MAX_COMMAND_WALL_SECONDS * 1_000_000_000
    if production and any(value is not None for value in (preflight, backend, host)):
        raise CapacityRunnerError(
            "production capacity refuses caller-fabricated inputs")
    if production and (type(source_sha256) is not str
                       or len(source_sha256) != 64
                       or any(char not in "0123456789abcdef"
                              for char in source_sha256)):
        raise CapacityRunnerError("production capacity source binding drift")
    if production and (type(runtime_sha256) is not str
                       or len(runtime_sha256) != 64
                       or any(char not in "0123456789abcdef"
                              for char in runtime_sha256)):
        raise CapacityRunnerError("production capacity runtime binding drift")
    backend = backend or RealMeasurementBackendV2(
        deadline_ns=deadline_ns, progress=progress)
    if getattr(backend, "synthetic", False) and production:
        raise CapacityRunnerError("synthetic measurement backend refused in production")
    preflight = preflight or run_score_free_preflight(
        deadline_ns=deadline_ns, progress=progress, started_ns=started)
    preflight.validate()
    host = host or observe_host()
    capacity_assessments: tuple[CapacityCensusAssessmentV2, ...] = ()
    if production:
        host.validate()
    fixtures = preflight.accepted_fixtures
    if time.perf_counter_ns() >= deadline_ns:
        raise CapacityRunnerError("capacity deadline exceeded before measurement")
    arms: list[CapacityArmV2] = []
    arm_targets = _arm_target_units(fixtures)
    for stage, variants in ARM_GRIDS.items():
        fixture_sha = fixtures[0].fixture_sha256
        measured_output_identity: str | None = None
        synthetic = bool(getattr(backend, "synthetic", False))
        warm_raws: dict[int, RawMeasurementV2] = {}

        # Cohort topology is selected from a substantially more expensive
        # process/controller workload than the raw model arms.  Warm every
        # width once in ascending order, then measure in reverse order.  This
        # balances import/page-cache/startup order without turning a cold
        # first observation into the production topology.  Each width's two
        # observations are combined into one receipt arm so no executed work
        # disappears from command-wall or resource accounting.
        if stage == "cohort-concurrency" and not synthetic:
            for warm_position, warm_variant in enumerate(variants, 1):
                warm_operation, _warm_count = _capacity_arm_operation(
                    stage, warm_variant, fixtures, fixture_sha, arm_targets,
                    synthetic=False)
                warm_raw = backend.measure(
                    f"{stage}-warm", warm_variant, fixtures[0],
                    warm_operation)
                warm_raw.validate()
                warm_raws[warm_variant] = warm_raw
                if time.perf_counter_ns() >= deadline_ns:
                    raise CapacityRunnerError(
                        "capacity deadline exceeded during measurement")
                if production:
                    live = observe_host()
                    if (_cgroup_memory_bytes() * 100
                            > MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX):
                        raise CapacityRunnerError(
                            "capacity memory headroom exhausted")
                    if live.swap_bytes != ZERO_SWAP:
                        raise CapacityRunnerError(
                            "capacity swap became non-zero")
                if measured_output_identity is None:
                    measured_output_identity = warm_raw.byte_identity_sha256
                    if measured_output_identity in {
                            _ordered_fixture_identity(fixtures),
                            *(item.fixture_sha256 for item in fixtures)}:
                        raise CapacityRunnerError(
                            "capacity arm returned input identity instead of operation output")
                elif warm_raw.byte_identity_sha256 != measured_output_identity:
                    raise CapacityRunnerError(
                        "byte-identical fixture refusal")
                _progress_event(
                    f"{stage}-warm", warm_position, len(variants),
                    warm_variant, started, warm_raw.elapsed_ns,
                    min(1_000_000, max(
                        1, warm_raw.process_cpu_ns * 1_000_000
                        // max(1, warm_raw.elapsed_ns * HOST_CPUS))),
                    progress)
            measured_variants = tuple(reversed(variants))
        else:
            measured_variants = variants

        for position, variant in enumerate(measured_variants, 1):
            # Same bytes are supplied to all arms; a backend changing that
            # identity is refused before it can influence selection.
            fixture = fixtures[0]
            operation, measured_count = _capacity_arm_operation(
                stage, variant, fixtures, fixture_sha, arm_targets,
                synthetic=synthetic)
            raw = backend.measure(stage, variant, fixture,
                                  operation)
            if time.perf_counter_ns() >= deadline_ns:
                raise CapacityRunnerError("capacity deadline exceeded during measurement")
            if production:
                live = observe_host()
                if (_cgroup_memory_bytes() * 100
                        > MEMORY_LIMIT_BYTES * MEMORY_PERCENT_MAX):
                    raise CapacityRunnerError("capacity memory headroom exhausted")
                if live.swap_bytes != ZERO_SWAP:
                    raise CapacityRunnerError("capacity swap became non-zero")
            raw.validate()
            if stage == "cohort-concurrency" and not synthetic:
                warm = warm_raws.get(variant)
                if warm is None:
                    raise CapacityRunnerError(
                        "capacity cohort warm measurement missing")
                raw = _combine_capacity_repeats(warm, raw)
                measured_count *= 2
            if synthetic:
                expected_identity = fixture_sha
            elif measured_output_identity is None:
                # The first real arm establishes the ordered population of
                # actual operation outputs.  Every later arm must produce
                # those same bytes; fixture-input hashes are insufficient.
                measured_output_identity = raw.byte_identity_sha256
                expected_identity = measured_output_identity
                if expected_identity in {
                        _ordered_fixture_identity(fixtures),
                        *(item.fixture_sha256 for item in fixtures)}:
                    raise CapacityRunnerError(
                        "capacity arm returned input identity instead of operation output")
            else:
                expected_identity = measured_output_identity
                if raw.byte_identity_sha256 in {
                        _ordered_fixture_identity(fixtures),
                        *(item.fixture_sha256 for item in fixtures)}:
                    raise CapacityRunnerError(
                        "capacity arm returned input identity instead of operation output")
            if raw.byte_identity_sha256 != expected_identity:
                raise CapacityRunnerError("byte-identical fixture refusal")
            arm = _arm_from_raw(
                stage, variant, raw, expected_identity, raw.elapsed_ns,
                synthetic=synthetic, measured_unit_count=measured_count)
            arms.append(arm)
            _progress_event(stage, position, len(variants),
                            variant, started, raw.elapsed_ns,
                            arm.mean_cpu_utilization_ppm, progress)
    if production and time.perf_counter_ns() - started > MAX_COMMAND_WALL_SECONDS * 1_000_000_000:
        raise CapacityRunnerError("capacity command wall cap exceeded")
    selected = _select_arms(arms)
    if production:
        # The census is deliberately before importing/calling the full-DAG
        # supervisor.  Its projected D256 category shares are deterministic
        # from the selected arm timings and frozen stage mapping.
        provisional = _composed_projection(
            selected, len(fixtures), host.free_disk_bytes,
            arm_target_units=arm_targets)
        capacity_assessments = validate_capacity_arm_census_v2(
            arms, selected, dict(provisional.stage_walls_seconds))
    # Freeze the exact layout before any representative DAG work starts.
    member_workers = selected["member-concurrency"].variant
    torch_threads = PINNED_TORCH_THREADS
    inference_batch = selected["inference-batch"].variant
    reconstruction_workers = selected["reconstruction"].variant
    if getattr(backend, "synthetic", False):
        return CapacityRunResultV2(None, tuple(arms), preflight, True,
                                   getattr(backend, "brand", SYNTHETIC_BRAND))
    if production and time.perf_counter_ns() >= deadline_ns:
        raise CapacityRunnerError("capacity command wall cap exceeded")
    if production:
        from .world_afterstate_v2_capacity_supervisor import (
            FullDAGCapacityDependencyBlocked as SupervisorBlocked,
            run_full_dag_supervisor,
        )
        try:
            measured = run_full_dag_supervisor(
                fixtures, backend=backend, progress=progress,
                output_root=output_root,
                deadline_ns=deadline_ns, _provenance=_FULL_DAG_PROVENANCE,
                member_workers=member_workers, torch_threads=torch_threads,
                continuation_workers=selected["continuation-mechanics"].variant,
                inference_batch=inference_batch,
                reconstruction_workers=reconstruction_workers)
            measured.validate()
            stage = dict(measured.stage_wall_nanoseconds)
            required_staged_labels = {
                "label-p0", "label-fit", "label-precision-select", "label-audit"}
            if not required_staged_labels.issubset(stage):
                raise FullDAGCapacityDependencyBlocked(
                    "full-DAG staged label timing witness is missing")
            label_wall = sum(stage[name] for name in required_staged_labels)
            dag = RepresentativeDAGV2(
                _ceil_seconds(stage["p0"]), _ceil_seconds(label_wall),
                *(_ceil_seconds(stage[name]) for name in (
                    "block-1-natural",
                    "block-1-complete-world-shuffle",
                    "precision-select-inference", "audit",
                    "reconstruction")),
                measured.artifact_bytes, admissible=True,
                stage_walls_seconds=tuple(
                    (name, _ceil_seconds(value))
                    for name, value in measured.stage_wall_nanoseconds),
                stage_wall_nanoseconds=tuple(measured.stage_wall_nanoseconds),
                stage_source_unit_counts=measured.stage_source_unit_counts,
                stage_process_cpu_nanoseconds=measured.stage_process_cpu_nanoseconds,
                member_workers=measured.member_workers,
                continuation_workers=getattr(measured, "continuation_workers", 0),
                torch_threads=measured.torch_threads,
                inference_batch=measured.inference_batch,
                reconstruction_workers=measured.reconstruction_workers,
                progress_recovery=dict(measured.progress_recovery),
                provenance_token=measured.provenance_token)
            object.__setattr__(dag, "attestation_sha256", _dag_attestation(dag))
        except SupervisorBlocked as exc:
            raise FullDAGCapacityDependencyBlocked(
                str(exc), stage=getattr(exc, "stage", "full-dag"),
                reason_code=getattr(exc, "reason_code",
                                    "full-dag-dependency-failed"),
                assessments=capacity_assessments) from exc
    else:
        dag = None
    receipt = build_receipt_v2(
        tuple(arms), host=host, preflight=preflight,
        source_sha256=source_sha256,
        runtime_sha256=runtime_sha256,
        representative_dag=dag,
        capacity_assessments=capacity_assessments,
        _provenance=_PRODUCTION_PROVENANCE)
    return CapacityRunResultV2(receipt, tuple(arms), preflight, False, None)


class CapacityRunnerV2:
    """Small object wrapper for supervisors that need an explicit runner."""

    def __init__(self, *, preflight: PreflightResultV2 | None = None,
                 backend: MeasurementBackendV2 | None = None,
                 host: HostTelemetryV2 | None = None,
                 progress: Callable[[dict[str, Any]], None] | None = None,
                 output_root: Path | None = None,
                 source_sha256: str | None = None,
                 runtime_sha256: str | None = None,
                 production: bool = True) -> None:
        self.preflight = preflight
        self.backend = backend
        self.host = host
        self.progress = progress
        self.output_root = output_root
        self.source_sha256 = source_sha256
        self.runtime_sha256 = runtime_sha256
        self.production = production

    def measure(self) -> CapacityRunResultV2:
        return measure_capacity_v2(
            preflight=self.preflight, backend=self.backend, host=self.host,
            progress=self.progress, output_root=self.output_root,
            source_sha256=self.source_sha256,
            runtime_sha256=self.runtime_sha256,
            production=self.production)

    def run(self) -> CapacityReceiptV2:
        if not self.production:
            raise CapacityRunnerError("non-production runner cannot publish receipt")
        return self.measure().production_receipt()


def run_capacity_v2(*, source_sha256: str, runtime_sha256: str,
                    progress: Callable[[dict[str, Any]], None] | None = None,
                    output_root: Path | None = None
                    ) -> CapacityReceiptV2:
    """Run the real bounded command with no caller-fabricated inputs."""
    bind_runtime_expectation(runtime_sha256)
    result = measure_capacity_v2(
        progress=progress, output_root=output_root,
        source_sha256=source_sha256, runtime_sha256=runtime_sha256,
        production=True)
    return result.production_receipt()


def reopen_capacity_receipt_v2(payload: Mapping[str, Any]) -> CapacityReceiptV2:
    """Reconstruct a receipt from canonical JSON and validate independently."""
    if type(payload) is not dict:
        raise CapacityRunnerError("capacity payload type drift")
    required = {"schema", "host_logical_cpus", "command_wall_seconds",
                "memory_limit_bytes", "swap_bytes", "task_count", "arms",
                "selected_arms", "composed", "tiers", "progress_recovery",
                "authority", "model_parameter_count",
                "candidate_distribution", "per_epoch_wall_seconds",
                "peak_task_count", "measurement_scope", "member_workers",
                "continuation_workers", "torch_threads", "inference_batch", "source_sha256",
                "runtime_sha256", "reconstruction_workers",
                "all_core_gate_passed", "preflight_wall_nanoseconds"}
    if set(payload) != required:
        raise CapacityRunnerError("capacity payload field population drift")
    try:
        arm_fields = set(CapacityArmV2(
            stage="state-successor", variant=1, wall_seconds=1,
            busy_core_seconds=1, mean_cpu_utilization_ppm=62_500,
            p50_cpu_utilization_ppm=1, p95_cpu_utilization_ppm=1,
            scaling_efficiency_ppm=1, queue_depth=0, wall_share_ppm=0,
            peak_memory_bytes=1, swap_bytes=0, task_count=1,
            byte_identity_sha256="0" * 64, cpu_bound=False,
            wall_ns=1_000_000_000, busy_core_ns=1_000_000_000).payload())
        for row in (*payload["arms"], *payload["selected_arms"]):
            if type(row) is not dict or set(row) != arm_fields:
                raise CapacityRunnerError("capacity arm payload field population drift")
        arms = tuple(CapacityArmV2(**row) for row in payload["arms"])
        selected = tuple(CapacityArmV2(**row) for row in payload["selected_arms"])
        composed_payload = dict(payload["composed"])
        composed_payload["stage_walls_seconds"] = tuple(
            tuple(row) for row in composed_payload["stage_walls_seconds"])
        composed_payload["stage_unit_counts"] = tuple(
            tuple(row) for row in composed_payload.get("stage_unit_counts", ()))
        composed_payload["arm_target_unit_counts"] = tuple(
            tuple(row) for row in composed_payload.get("arm_target_unit_counts", ()))
        composed_payload["measured_stage_walls_seconds"] = tuple(
            tuple(row) for row in composed_payload.get(
                "measured_stage_walls_seconds", ()))
        composed_payload["stage_cpu_seconds"] = tuple(
            tuple(row) for row in composed_payload.get("stage_cpu_seconds", ()))
        composed_payload["measured_stage_cpu_seconds"] = tuple(
            tuple(row) for row in composed_payload.get(
                "measured_stage_cpu_seconds", ()))
        composed_payload["measured_stage_wall_nanoseconds"] = tuple(
            tuple(row) for row in composed_payload.get(
                "measured_stage_wall_nanoseconds", ()))
        composed_payload["measured_stage_cpu_nanoseconds"] = tuple(
            tuple(row) for row in composed_payload.get(
                "measured_stage_cpu_nanoseconds", ()))
        composed_payload["scientific_dag_edges"] = tuple(
            tuple(row) for row in composed_payload.get("scientific_dag_edges", ()))
        composed_payload["dag_edges"] = tuple(
            tuple(row) for row in composed_payload.get("dag_edges", ()))
        composed_payload["capacity_stage_to_production_stage"] = tuple(
            tuple(row) for row in composed_payload.get(
                "capacity_stage_to_production_stage", ()))
        composed = ComposedProjectionV2(**composed_payload)
        tiers = tuple(TierProjectionV2(**row) for row in payload["tiers"])
        progress = ProgressRecoveryV2(**payload["progress_recovery"])
        candidate_distribution = tuple(
            (row[0], row[1]) for row in payload["candidate_distribution"])
        result = CapacityReceiptV2(
            host_logical_cpus=payload["host_logical_cpus"],
            command_wall_seconds=payload["command_wall_seconds"],
            memory_limit_bytes=payload["memory_limit_bytes"],
            swap_bytes=payload["swap_bytes"], task_count=payload["task_count"],
            arms=arms, selected_arms=selected, composed=composed, tiers=tiers,
            progress_recovery=progress, schema=payload["schema"],
            source_sha256=payload["source_sha256"],
            runtime_sha256=payload["runtime_sha256"],
            preflight_wall_nanoseconds=payload["preflight_wall_nanoseconds"],
            authority=payload["authority"],
            model_parameter_count=payload["model_parameter_count"],
            candidate_distribution=candidate_distribution,
            per_epoch_wall_seconds=payload["per_epoch_wall_seconds"],
            peak_task_count=payload["peak_task_count"],
            measurement_scope=payload["measurement_scope"],
            member_workers=payload["member_workers"],
            continuation_workers=payload["continuation_workers"],
            torch_threads=payload["torch_threads"],
            inference_batch=payload["inference_batch"],
            reconstruction_workers=payload["reconstruction_workers"],
            all_core_gate_passed=payload["all_core_gate_passed"])
        validate_capacity_receipt_v2(result)
    except Exception as exc:
        raise CapacityRunnerError("capacity payload reconstruction refused") from exc
    if result.payload() != payload:
        raise CapacityRunnerError("capacity payload reconstruction drift")
    return result


def reopen_capacity_receipt_v2_bytes(raw: bytes) -> CapacityReceiptV2:
    """Strictly reopen canonical receipt bytes as an independent reader."""
    if type(raw) is not bytes:
        raise CapacityRunnerError("capacity receipt bytes type drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityRunnerError("capacity receipt is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise CapacityRunnerError("capacity receipt is not canonical JSON")
    return reopen_capacity_receipt_v2(payload)


def _publication_target(path: Path | str) -> Path:
    target = Path(os.path.abspath(os.fspath(path)))
    current = target
    while current != current.parent:
        if current.is_symlink():
            raise CapacityRunnerError(
                "capacity output namespace is occupied or aliased")
        current = current.parent
    if current.is_symlink():
        raise CapacityRunnerError(
            "capacity output namespace is occupied or aliased")
    return target


def publish_capacity_receipt_v2(path: Path | str, receipt: CapacityReceiptV2) -> None:
    """Publish exact canonical bytes once; never overwrite an occupied path."""
    validate_capacity_receipt_v2(receipt)
    target = _publication_target(path)
    partial = target.with_name(f".{target.name}.partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink() or partial.exists() or partial.is_symlink():
        raise CapacityRunnerError("capacity output namespace is occupied")
    raw = canonical_json_bytes(receipt.payload())
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(partial, 0o400)
    os.link(partial, target)
    partial.unlink()
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_capacity_failure_receipt_v2(
        path: Path | str, receipt: CapacityFailureReceiptV2) -> None:
    """Publish one canonical refusal artifact without overwrite."""
    validate_capacity_failure_receipt_v2(receipt)
    raw = canonical_json_bytes(receipt.payload())
    target = _publication_target(path)
    partial = target.with_name(f".{target.name}.partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink() or partial.exists() \
            or partial.is_symlink():
        raise CapacityRunnerError("capacity output namespace is occupied")
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(partial, 0o400)
    os.link(partial, target)
    partial.unlink()
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Compact compatibility names for callers following the V0 runner naming.
run_capacity = run_capacity_v2
measure_capacity = measure_capacity_v2
reopen_capacity_receipt = reopen_capacity_receipt_v2
publish_capacity_receipt = publish_capacity_receipt_v2


__all__ = [
    "CapacityRunResultV2", "CapacityRunnerError",
    "FullDAGCapacityDependencyBlocked", "FixtureV2",
    "CapacityRunnerV2", "HostEnvelopeV2", "HostTelemetryV2",
    "PreflightResultV2", "RawMeasurementV2", "MeasurementV2",
    "RepresentativeDAGV2",
    "RealMeasurementBackendV2", "SyntheticMeasurementBackendV2",
    "build_receipt_v2", "measure_capacity_v2", "observe_host",
    "publish_capacity_receipt_v2", "reopen_capacity_receipt_v2",
    "reopen_capacity_receipt_v2_bytes",
    "publish_capacity_failure_receipt_v2", "reopen_capacity_failure_receipt_v2",
    "reopen_capacity_failure_receipt_v2_bytes",
    "validate_capacity_failure_receipt_v2",
    "run_capacity_v2", "run_score_free_preflight", "run_capacity",
    "measure_capacity", "reopen_capacity_receipt", "publish_capacity_receipt",
    "PREFLIGHT_ACCEPTED", "PREFLIGHT_ATTEMPT_CEILING",
    "PREFLIGHT_MAX_NATURAL_ROOTS", "PREFLIGHT_RESERVED_NATURAL_PAIRS",
    "PREFLIGHT_RESERVED_NATURAL_ROOTS", "SYNTHETIC_BRAND",
    "run_preflight_v2", "preflight_v2",
]


# Public descriptive aliases used by lightweight callers and tests.
HostEnvelopeV2 = HostTelemetryV2
MeasurementV2 = RawMeasurementV2
run_preflight_v2 = run_score_free_preflight
preflight_v2 = run_score_free_preflight
