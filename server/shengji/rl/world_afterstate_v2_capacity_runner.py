"""Bounded, score-free post-implementation capacity measurement for V2.

The contract in :mod:`world_afterstate_v2_capacity` is intentionally only a
receipt.  This module is the executable boundary which obtains measurements,
derives projections, and then hands the result to that contract.  In
particular, this file never opens a continuation outcome or a label.

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
import os
from pathlib import Path
import resource
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import canonical_successor, replay_canonical_successor
from .world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, MAX_COMMAND_WALL_SECONDS, MEMORY_LIMIT_BYTES,
    MAX_TASKS, CapacityArmV2, CapacityReceiptV2, ComposedProjectionV2,
    ProgressRecoveryV2, TierProjectionV2, WorldAfterstateV2CapacityError,
    validate_capacity_receipt_v2,
)
from .world_afterstate_v2_protocol import ATTEMPT_SCHEMA, TIER_SPECS
from .world_afterstate_v2_source_driver import drive_population_attempt_v2


HOST_CPUS = 16
ZERO_SWAP = 0
PREFLIGHT_ACCEPTED = 32
PREFLIGHT_ATTEMPT_CEILING = 96
SYNTHETIC_BRAND = "SYNTHETIC_TEST_MEASUREMENT_ONLY"
RUNNER_SCHEMA = "world-afterstate-v2-capacity-runner-v1"
_PRODUCTION_PROVENANCE = object()


class CapacityRunnerError(RuntimeError):
    """A capacity run was refused or could not be measured honestly."""


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


@dataclass(frozen=True)
class PreflightResultV2:
    accepted_fixtures: tuple[FixtureV2, ...]
    attempted: int
    accepted: int
    rejection_counts: tuple[tuple[str, int], ...]
    candidate_distribution: tuple[tuple[int, int], ...]
    stratum_distribution: tuple[tuple[str, int], ...]
    outcomes_opened: bool = False

    def validate(self) -> None:
        if self.attempted < self.accepted or self.attempted > PREFLIGHT_ATTEMPT_CEILING:
            raise CapacityRunnerError("preflight attempt ceiling drift")
        if self.accepted != len(self.accepted_fixtures):
            raise CapacityRunnerError("preflight accepted fixture accounting drift")
        if self.accepted != PREFLIGHT_ACCEPTED:
            raise CapacityRunnerError("preflight requires exactly 32 accepted deals")
        deal_ids = [fixture.deal_sha256 for fixture in self.accepted_fixtures
                    if fixture.deal_sha256]
        if deal_ids and len(deal_ids) != len(set(deal_ids)):
            raise CapacityRunnerError("preflight accepted deals are not independent")
        if self.outcomes_opened:
            raise CapacityRunnerError("preflight outcomes were opened")
        if not self.candidate_distribution or not self.stratum_distribution:
            raise CapacityRunnerError("preflight candidate/stratum report missing")

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
            "outcomes_opened": self.outcomes_opened,
            "accepted_fixture_sha256s": [fixture.fixture_sha256
                                          for fixture in self.accepted_fixtures],
        }


def _namespace() -> str:
    return _sha({"namespace": "world-afterstate-v2-capacity-preflight-v1"})


def _attempt_identity(namespace: str, slot: Any, index: int) -> dict[str, Any]:
    body = {"schema": ATTEMPT_SCHEMA, "population_namespace_sha256": namespace,
            "slot_sha256": slot.slot_sha256, "attempt_index": index}
    deal = _sha(body)
    return {**body, "deal_sha256": deal,
            "engine_seed": int(deal[:16], 16) & ((1 << 63) - 1)}


def run_score_free_preflight(*, attempt: Callable[..., Any] = drive_population_attempt_v2,
                             slots: Sequence[Any] | None = None,
                             deadline_ns: int | None = None,
                             progress: Callable[[dict[str, Any]], None] | None = None,
                             started_ns: int | None = None) -> PreflightResultV2:
    """Find 32 accepted natural/mechanics D256 deals, bounded at 96 attempts."""
    from .world_afterstate_v2_protocol import _raw_slot_ledger

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
    rejected: Counter[str] = Counter()
    candidates: Counter[int] = Counter()
    strata: Counter[str] = Counter()
    for index in range(PREFLIGHT_ATTEMPT_CEILING):
        if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
            raise CapacityRunnerError("capacity deadline exceeded during preflight")
        if _rss_bytes() * 100 > MEMORY_LIMIT_BYTES * 85:
            raise CapacityRunnerError("capacity memory headroom exhausted during preflight")
        if _swap_bytes() != ZERO_SWAP:
            raise CapacityRunnerError("capacity swap became non-zero during preflight")
        if _task_count() > MAX_TASKS:
            raise CapacityRunnerError("capacity task cap exceeded during preflight")
        slot = slots[index % len(slots)]
        result = attempt(_attempt_identity(namespace, slot, index), slot)
        if progress is not None:
            elapsed = max(0, time.perf_counter_ns() - (started_ns or time.perf_counter_ns()))
            progress({
                "stage": "preflight", "completed_units": index + 1,
                "total_units": PREFLIGHT_ATTEMPT_CEILING, "workers": 1,
                "utilization_ppm": 0, "elapsed_seconds": elapsed // 1_000_000_000,
                "eta_seconds": 0, "headroom_seconds": max(
                    0, MAX_COMMAND_WALL_SECONDS - elapsed // 1_000_000_000),
                "accepted": len(accepted),
                "memory_bytes": _cgroup_memory_bytes(),
                "peak_memory_bytes": _cgroup_memory_bytes(),
                "queue_depth": 0,
                "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
                "immutable_shards": 0, "checkpoint_count": 0,
            })
        if not getattr(result, "accepted", False):
            rejected[str(getattr(result, "rejection_reason", "unknown"))] += 1
            continue
        material = getattr(result, "material", None)
        if material is None:
            rejected["missing-material"] += 1
            continue
        # Only the score-free canonical state and private audit bytes enter
        # the in-memory fixture.  No continuation/result field is copied.
        fixture = FixtureV2(
            material.prestate, tuple(material.audit_raws),
            deal_sha256=result.deal_sha256)
        accepted.append(fixture)
        candidates[len(material.candidates)] += 1
        state = material.state
        strata[f"{state.phase}/{state.position}/{state.role}"] += 1
        if len(accepted) == PREFLIGHT_ACCEPTED:
            break
    result = PreflightResultV2(
        tuple(accepted), index + 1, len(accepted), tuple(sorted(rejected.items())),
        tuple(sorted(candidates.items())), tuple(sorted(strata.items())))
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
                cpu_samples.append(min(
                    1_000_000, max(1, (now_cpu - last_sample_cpu)
                                    * 1_000_000 // elapsed_sample)))
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
                1_000_000, max(1, cpu * 1_000_000 // max(1, elapsed))),
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


def _operation(stage: str, variant: int, fixture: FixtureV2) -> Callable[[], None]:
    """Construct a score-free operation from the current V2 primitives."""
    def run() -> None:
        if stage == "state-successor":
            value = replay_canonical_successor(dict(fixture.snapshot))
            canonical_successor(value, 0)
        elif stage == "continuation-mechanics":
            # Replaying and applying legal afterstate transitions exercises the
            # continuation mechanics; points/outcomes are never serialized.
            value = replay_canonical_successor(dict(fixture.snapshot))
            if value.phase == "play" and value.trick is not None:
                actor = value.turn
                from .actions import enumerate_actions
                actions = enumerate_actions(value, actor)
                if actions:
                    value.play(actor, list(actions[0]))
        elif stage in {"member-concurrency", "torch-threads-per-member", "inference-batch"}:
            # These three arms exercise the actual target-free model input and
            # forward path.  No training target, optimizer, or label is ever
            # constructed.  Imports stay local because the server itself does
            # not require the optional RL dependency.
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
                    def member(_: int) -> None:
                        new_world_afterstate_v2_model(variant)(batch)
                    with ThreadPoolExecutor(max_workers=min(4, variant)) as pool:
                        tuple(pool.map(member, range(4)))
                else:
                    model = new_world_afterstate_v2_model(variant)
                    for _ in range(1 if stage == "inference-batch" else variant):
                        model(batch)
        elif stage == "reconstruction":
            from .world_afterstate import reopen_afterstate_audit
            for raw in fixture.audit_raws or (canonical_json_bytes(fixture.snapshot),):
                hashlib.sha256(raw).digest()
                try:
                    value = json.loads(raw.decode("ascii"))
                    if isinstance(value, dict) and "successor" in value:
                        reopened = reopen_afterstate_audit(value)
                        canonical_successor(reopened, value["root_seat"])
                except (UnicodeDecodeError, ValueError):
                    pass
        else:
            raise CapacityRunnerError("unknown capacity stage")
    return run


def _process_fixture(payload: tuple[str, int, FixtureV2]) -> str:
    """Process worker entry point; only score-free ordered fixture identity returns."""
    stage, variant, fixture = payload
    _operation(stage, variant, fixture)()
    return fixture.fixture_sha256


def _parallel_operation(stage: str, variant: int,
                        fixtures: Sequence[FixtureV2]) -> Callable[[], str]:
    """Run one independent process task per fixture at the requested arm width."""
    values = tuple(fixtures)

    def run() -> str:
        with ProcessPoolExecutor(max_workers=variant) as pool:
            outputs = tuple(pool.map(
                _process_fixture,
                ((stage, variant, fixture) for fixture in values)))
        return _sha(outputs)
    return run


def _model_operation(stage: str, variant: int,
                     fixtures: Sequence[FixtureV2]) -> Callable[[], str]:
    """Run target-free model work with the requested member/batch shape."""
    values = tuple(fixtures)

    def run() -> str:
        import torch
        from .world_afterstate import build_afterstate_tensors
        from .world_afterstate_v2_model import (
            collate_world_afterstate_tensors, new_world_afterstate_v2_model)
        tensors = tuple(
            build_afterstate_tensors(json.loads(raw.decode("ascii")))
            for fixture in values for raw in fixture.audit_raws)
        if not tensors:
            raise CapacityRunnerError("model fixture has no score-free audit bytes")
        with torch.inference_mode():
            if stage == "member-concurrency":
                model_count = variant
                def member(_: int) -> None:
                    model = new_world_afterstate_v2_model(0)
                    model(collate_world_afterstate_tensors(tensors))
                with ThreadPoolExecutor(max_workers=model_count) as pool:
                    tuple(pool.map(member, range(model_count)))
            else:
                model = new_world_afterstate_v2_model(0)
                for start in range(0, len(tensors), variant):
                    chunk = tensors[start:start + variant]
                    if len(chunk) < variant:
                        chunk = chunk + tensors[:variant - len(chunk)]
                    model(collate_world_afterstate_tensors(chunk))
        return _sha([fixture.fixture_sha256 for fixture in values])
    return run


def _arm_from_raw(stage: str, variant: int, raw: RawMeasurementV2,
                  fixture_sha: str, stage_wall: int,
                  *, synthetic: bool = False) -> CapacityArmV2:
    raw.validate()
    if raw.byte_identity_sha256 != fixture_sha:
        raise CapacityRunnerError("stage arms are not byte-identical")
    wall = _ceil_seconds(raw.elapsed_ns)
    busy = max(1, (raw.process_cpu_ns + 999_999_999) // 1_000_000_000)
    busy = min(busy, wall * HOST_CPUS)
    mean = busy * 1_000_000 // (wall * HOST_CPUS)
    samples = raw.sample_utilization_ppm or (mean,)
    p50 = sorted(samples)[len(samples) // 2]
    p95 = sorted(samples)[min(len(samples) - 1, math.ceil(len(samples) * .95) - 1)]
    scaling = min(1_000_000, max(1, mean * max(1, variant) // max(1, HOST_CPUS)))
    # The receipt's wall-share gate is a projected-DAG share, not a timer
    # unit.  A conservative 10% share keeps the CPU-bound guard active even
    # for a one-fixture benchmark; the next-arm rule then remains binding.
    share = 100_000
    arm = CapacityArmV2(
        stage=stage, variant=variant, wall_seconds=wall,
        busy_core_seconds=busy, mean_cpu_utilization_ppm=mean,
        p50_cpu_utilization_ppm=p50, p95_cpu_utilization_ppm=p95,
        scaling_efficiency_ppm=scaling, queue_depth=raw.queue_depth,
        wall_share_ppm=share, peak_memory_bytes=raw.peak_rss_bytes,
        swap_bytes=ZERO_SWAP, task_count=raw.task_count,
        byte_identity_sha256=fixture_sha, cpu_bound=raw.cpu_bound,
        wall_nanoseconds=raw.elapsed_ns,
        peak_task_count=max((raw.task_count, *raw.sample_task_counts)))
    # CapacityArmV2 intentionally remains the existing public wire type.  A
    # private in-memory provenance bit prevents a test seam from being
    # relabelled into a production receipt before validation.
    if synthetic:
        object.__setattr__(arm, "_synthetic_measurement", True)
    return arm


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


def _representative_dag(fixtures: Sequence[FixtureV2],
                        backend: RealMeasurementBackendV2) -> RepresentativeDAGV2:
    values = tuple(fixtures)
    def timed(kind: str, fn: Callable[[], None]) -> int:
        raw = backend.measure(kind, 1, values[0], fn)
        raw.validate()
        return _ceil_seconds(raw.elapsed_ns)
    def hashes(prefix: str) -> None:
        for fixture in values:
            hashlib.sha256(prefix.encode("ascii") +
                           canonical_json_bytes(fixture.snapshot)).digest()
    def label_work() -> None:
        payload = b"".join(canonical_json_bytes(fixture.snapshot)
                            for fixture in values)
        with tempfile.TemporaryDirectory(prefix="shengji-v2-capacity-") as root:
            path = Path(root) / "label-shard.bin"
            with path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if path.stat().st_size != len(payload):
                raise CapacityRunnerError("temporary artifact write drift")
    p0 = timed("p0", lambda: hashes("p0"))
    label = timed("label", label_work)
    epoch = timed("epoch", lambda: _model_operation(
        "member-concurrency", 4, values)())
    controls = timed("controls", lambda: hashes("control"))
    inference = timed("inference", lambda: _model_operation(
        "inference-batch", 64, values)())
    audit = timed("audit", lambda: hashes("audit"))
    reconstruction = timed("reconstruction", lambda: _parallel_operation(
        "reconstruction", 1, values)())
    artifact_bytes = sum(len(canonical_json_bytes(fixture.snapshot))
                         + sum(len(raw) for raw in fixture.audit_raws)
                         for fixture in values)
    return RepresentativeDAGV2(
        p0, label, epoch, controls, inference, audit, reconstruction,
        max(1, artifact_bytes), admissible=False)


def _progress_event(stage: str, completed: int, total: int, workers: int,
                    started_ns: int, stage_wall: int,
                    utilization_ppm: int,
                    callback: Callable[[dict[str, Any]], None] | None) -> None:
    if callback is None:
        return
    elapsed = max(0, time.perf_counter_ns() - started_ns) / 1_000_000_000
    fraction = completed / max(1, total)
    eta = 0 if completed == 0 else max(0, int(elapsed * (1 - fraction) / fraction))
    callback({
        "stage": stage, "completed_units": completed, "total_units": total,
        "workers": workers, "utilization_ppm": utilization_ppm,
        "elapsed_seconds": int(elapsed), "eta_seconds": eta,
        "headroom_seconds": max(0, MAX_COMMAND_WALL_SECONDS - int(elapsed)),
        "memory_bytes": _cgroup_memory_bytes(),
        "peak_memory_bytes": _cgroup_memory_bytes(),
        "queue_depth": max(0, _task_count() - workers),
        "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
        "immutable_shards": 0, "checkpoint_count": 0,
    })


def _composed_projection(selected: Mapping[str, CapacityArmV2],
                         fixture_count: int, free_disk_bytes: int,
                         dag: RepresentativeDAGV2 | None = None) -> ComposedProjectionV2:
    def wall(stage: str, multiplier: int = 1) -> int:
        return max(1, selected[stage].wall_seconds * max(1, multiplier))
    base = wall("state-successor", fixture_count)
    continuation = wall("continuation-mechanics", fixture_count)
    label = max(1, dag.label_wall_seconds if dag else base + continuation * 8)
    inference = max(1, dag.inference_wall_seconds if dag
                    else wall("inference-batch", fixture_count))
    reconstruction = max(1, dag.reconstruction_wall_seconds if dag
                        else wall("reconstruction", fixture_count))
    p0 = max(1, dag.p0_wall_seconds if dag else label)
    epoch = max(1, dag.epoch_wall_seconds if dag else label)
    controls = max(1, dag.control_wall_seconds if dag else label)
    audit = max(1, dag.audit_wall_seconds if dag else label)
    values = (
        ("optimizer-canary", wall("state-successor")),
        ("nested-curve-25", max(1, base // 4)),
        ("nested-curve-50", max(1, base // 2)),
        ("nested-curve-100", base), ("p0", p0), ("label", label),
        ("block-1-natural", epoch),
        ("block-1-action-association-permutation", controls),
        ("block-1-label-permutation", controls),
        ("block-1-complete-world-shuffle", controls),
        ("block-2-natural", epoch),
        ("block-2-complete-world-shuffle", controls),
        ("precision-select-inference", inference),
        ("precision-select", inference), ("audit", audit),
        ("reconstruction", reconstruction),)
    total = sum(value for _, value in values)
    artifact = max(1, dag.artifact_bytes if dag else fixture_count * 1024)
    return ComposedProjectionV2(
        stage_walls_seconds=values, composed_wall_seconds=total,
        peak_memory_bytes=max(1, max(arm.peak_memory_bytes for arm in selected.values())),
        composed_artifact_bytes=artifact, free_disk_bytes_before=free_disk_bytes)


def _tiers(composed: ComposedProjectionV2) -> tuple[TierProjectionV2, ...]:
    result = []
    for spec in TIER_SPECS:
        factor = spec.total / TIER_SPECS[0].total
        result.append(TierProjectionV2(
            tier=spec.name, exact_source_supply=True,
            label_wall_seconds=max(1, int(composed.composed_wall_seconds * factor / 3)),
            label_cpu_seconds=max(1, int(composed.composed_wall_seconds * factor * 16)),
            complete_dag_wall_seconds=max(1, int(composed.composed_wall_seconds * factor)),
            peak_memory_bytes=composed.peak_memory_bytes,
            composed_artifact_bytes=max(1, int(composed.composed_artifact_bytes * factor)),
            free_disk_bytes_before=composed.free_disk_bytes_before))
    return tuple(result)


def build_receipt_v2(arms: Sequence[CapacityArmV2], *, host: HostTelemetryV2,
                     preflight: PreflightResultV2,
                     synthetic: bool = False,
                     representative_dag: RepresentativeDAGV2 | None = None,
                     _provenance: object | None = None) -> CapacityReceiptV2:
    """Derive and validate one receipt from measured arms only."""
    if synthetic or _provenance is not _PRODUCTION_PROVENANCE:
        raise CapacityRunnerError("synthetic measurement cannot build production receipt")
    if representative_dag is not None and not representative_dag.admissible:
        raise FullDAGCapacityDependencyBlocked(
            "non-admissible representative DAG cannot issue a receipt")
    preflight.validate()
    host.validate()
    arms = tuple(arms)
    for arm in arms:
        if getattr(arm, "_synthetic_measurement", False):
            raise CapacityRunnerError("synthetic measurement cannot build production receipt")
        arm.validate()
    selected: dict[str, CapacityArmV2] = {}
    for stage in ARM_GRIDS:
        eligible = [arm for arm in arms if arm.stage == stage and
                    arm.peak_memory_bytes * 100 <= MEMORY_LIMIT_BYTES * 85]
        if not eligible:
            raise CapacityRunnerError("no memory-eligible arm")
        selected[stage] = min(
            eligible, key=lambda arm: (arm.wall_nanoseconds or
                                       arm.wall_seconds * 1_000_000_000,
                                       arm.variant))
    composed = _composed_projection(
        selected, len(preflight.accepted_fixtures), host.free_disk_bytes,
        representative_dag)
    try:
        from .world_afterstate_v2_model import (
            count_trainable_parameters, new_world_afterstate_v2_model)
        parameter_count = int(count_trainable_parameters(
            new_world_afterstate_v2_model(0)))
    except Exception as exc:
        raise CapacityRunnerError("model parameter measurement unavailable") from exc
    progress = ProgressRecoveryV2(
        progress_interval_seconds=60, progress_interval_fraction_ppm=10_000,
        reports_stage_counts=True, reports_active_workers_and_cpu=True,
        reports_elapsed_eta_headroom=True, reports_current_peak_cgroup_memory=True,
        reports_immutable_shard_checkpoint_count=True,
        resumes_verified_shards_only=False, resume_same_admission=False,
        resume_cannot_regenerate_replace_select=False,
        checkpoints_each_common_epoch=False,
        deadline_truncation_keeps_complete_epoch=False,
        audit_requires_complete_upstream=False,
        audit_attempt_fsynced_before_open=False, one_audit_open=False,
        reconstruction_without_retraining=True,
        reconstruction_reuses_immutable_continuations=False)
    receipt = CapacityReceiptV2(
        host_logical_cpus=host.logical_cpus,
        command_wall_seconds=max(sum(arm.wall_seconds for arm in arms), composed.composed_wall_seconds),
        memory_limit_bytes=host.memory_limit_bytes, swap_bytes=host.swap_bytes,
        task_count=sum(arm.task_count for arm in arms), arms=arms,
        selected_arms=tuple(selected.values()), composed=composed,
        tiers=_tiers(composed), progress_recovery=progress,
        authority=dict(AUTHORITY), model_parameter_count=parameter_count,
        candidate_distribution=preflight.candidate_distribution,
        per_epoch_wall_seconds=(representative_dag.epoch_wall_seconds
                                if representative_dag else
                                selected["member-concurrency"].wall_seconds),
        peak_task_count=max((arm.peak_task_count or arm.task_count)
                            for arm in arms))
    try:
        validate_capacity_receipt_v2(receipt)
    except WorldAfterstateV2CapacityError as exc:
        raise CapacityRunnerError(str(exc)) from exc
    return receipt


def measure_capacity_v2(*, preflight: PreflightResultV2 | None = None,
                        backend: MeasurementBackendV2 | None = None,
                        host: HostTelemetryV2 | None = None,
                        progress: Callable[[dict[str, Any]], None] | None = None,
                        production: bool = True) -> CapacityRunResultV2:
    started = time.perf_counter_ns()
    deadline_ns = started + MAX_COMMAND_WALL_SECONDS * 1_000_000_000
    if production and any(value is not None for value in (preflight, backend, host)):
        raise CapacityRunnerError(
            "production capacity refuses caller-fabricated inputs")
    backend = backend or RealMeasurementBackendV2(
        deadline_ns=deadline_ns, progress=progress)
    if getattr(backend, "synthetic", False) and production:
        raise CapacityRunnerError("synthetic measurement backend refused in production")
    preflight = preflight or run_score_free_preflight(
        deadline_ns=deadline_ns, progress=progress, started_ns=started)
    preflight.validate()
    host = host or observe_host()
    if production:
        host.validate()
    fixtures = preflight.accepted_fixtures
    if time.perf_counter_ns() >= deadline_ns:
        raise CapacityRunnerError("capacity deadline exceeded before measurement")
    arms: list[CapacityArmV2] = []
    for stage, variants in ARM_GRIDS.items():
        fixture_sha = fixtures[0].fixture_sha256
        for position, variant in enumerate(variants, 1):
            # Same bytes are supplied to all arms; a backend changing that
            # identity is refused before it can influence selection.
            fixture = fixtures[0]
            operation = (_parallel_operation(stage, variant, fixtures)
                         if stage in {"state-successor", "continuation-mechanics",
                                       "reconstruction"}
                         else _model_operation(stage, variant, fixtures))
            if stage == "torch-threads-per-member":
                import torch
                prior_threads = torch.get_num_threads()
                torch.set_num_threads(variant)
                operation_to_run = operation
                def operation_with_threads() -> None:
                    try:
                        operation_to_run()
                    finally:
                        torch.set_num_threads(prior_threads)
                operation = operation_with_threads
            raw = backend.measure(stage, variant, fixture,
                                  operation)
            if time.perf_counter_ns() >= deadline_ns:
                raise CapacityRunnerError("capacity deadline exceeded during measurement")
            if production:
                live = observe_host()
                if _rss_bytes() * 100 > MEMORY_LIMIT_BYTES * 85:
                    raise CapacityRunnerError("capacity memory headroom exhausted")
                if live.swap_bytes != ZERO_SWAP:
                    raise CapacityRunnerError("capacity swap became non-zero")
            raw.validate()
            expected_identity = (fixture_sha if getattr(backend, "synthetic", False)
                                 else _ordered_fixture_identity(fixtures))
            if raw.byte_identity_sha256 != expected_identity:
                raise CapacityRunnerError("byte-identical fixture refusal")
            arm = _arm_from_raw(
                stage, variant, raw, expected_identity, raw.elapsed_ns,
                synthetic=bool(getattr(backend, "synthetic", False)))
            arms.append(arm)
            _progress_event(stage, position, len(variants),
                            variant, started, raw.elapsed_ns,
                            arm.mean_cpu_utilization_ppm, progress)
    if production and time.perf_counter_ns() - started > MAX_COMMAND_WALL_SECONDS * 1_000_000_000:
        raise CapacityRunnerError("capacity command wall cap exceeded")
    if getattr(backend, "synthetic", False):
        return CapacityRunResultV2(None, tuple(arms), preflight, True,
                                   getattr(backend, "brand", SYNTHETIC_BRAND))
    dag = (_representative_dag(fixtures, backend)
           if isinstance(backend, RealMeasurementBackendV2) and not production
           else None)
    if production and time.perf_counter_ns() >= deadline_ns:
        raise CapacityRunnerError("capacity command wall cap exceeded")
    if production:
        # The local primitives can benchmark mechanics and target-free model
        # forwards, but cannot honestly run the complete label/training/control
        # supervisor.  The representative helper is therefore diagnostics
        # only and is never admissible for a production receipt.
        raise FullDAGCapacityDependencyBlocked(
            "blocked dependency: " + FullDAGCapacityDependencyBlocked.dependency)
    receipt = build_receipt_v2(
        tuple(arms), host=host, preflight=preflight,
        representative_dag=dag, _provenance=_PRODUCTION_PROVENANCE)
    return CapacityRunResultV2(receipt, tuple(arms), preflight, False, None)


class CapacityRunnerV2:
    """Small object wrapper for supervisors that need an explicit runner."""

    def __init__(self, *, preflight: PreflightResultV2 | None = None,
                 backend: MeasurementBackendV2 | None = None,
                 host: HostTelemetryV2 | None = None,
                 progress: Callable[[dict[str, Any]], None] | None = None,
                 production: bool = True) -> None:
        self.preflight = preflight
        self.backend = backend
        self.host = host
        self.progress = progress
        self.production = production

    def measure(self) -> CapacityRunResultV2:
        return measure_capacity_v2(
            preflight=self.preflight, backend=self.backend, host=self.host,
            progress=self.progress, production=self.production)

    def run(self) -> CapacityReceiptV2:
        if not self.production:
            raise CapacityRunnerError("non-production runner cannot publish receipt")
        return self.measure().production_receipt()


def run_capacity_v2(*, progress: Callable[[dict[str, Any]], None] | None = None
                    ) -> CapacityReceiptV2:
    """Run the real bounded command with no caller-fabricated inputs."""
    result = measure_capacity_v2(progress=progress, production=True)
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
                "peak_task_count"}
    if set(payload) != required:
        raise CapacityRunnerError("capacity payload field population drift")
    try:
        arms = tuple(CapacityArmV2(**row) for row in payload["arms"])
        selected = tuple(CapacityArmV2(**row) for row in payload["selected_arms"])
        composed_payload = dict(payload["composed"])
        composed_payload["stage_walls_seconds"] = tuple(
            tuple(row) for row in composed_payload["stage_walls_seconds"])
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
            authority=payload["authority"],
            model_parameter_count=payload["model_parameter_count"],
            candidate_distribution=candidate_distribution,
            per_epoch_wall_seconds=payload["per_epoch_wall_seconds"],
            peak_task_count=payload["peak_task_count"])
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


def publish_capacity_receipt_v2(path: Path | str, receipt: CapacityReceiptV2) -> None:
    """Publish exact canonical bytes once; never overwrite an occupied path."""
    validate_capacity_receipt_v2(receipt)
    target = Path(path).resolve()
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
    "run_capacity_v2", "run_score_free_preflight", "run_capacity",
    "measure_capacity", "reopen_capacity_receipt", "publish_capacity_receipt",
    "PREFLIGHT_ACCEPTED", "PREFLIGHT_ATTEMPT_CEILING", "SYNTHETIC_BRAND",
    "run_preflight_v2", "preflight_v2",
]


# Public descriptive aliases used by lightweight callers and tests.
HostEnvelopeV2 = HostTelemetryV2
MeasurementV2 = RawMeasurementV2
run_preflight_v2 = run_score_free_preflight
preflight_v2 = run_score_free_preflight
