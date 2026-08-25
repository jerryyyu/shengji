"""Score-redacted PT1 capacity capture and evaluation.

This lane is deliberately separate from the scientific population.  It
captures exactly sixteen out-of-population states, runs the real PT1 batch
evaluator, and retains only identity digests, work counters and resource
projections.  Actions, utilities, points, hidden worlds, raw seeds and the
capture secret never cross the report boundary.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .privileged_teacher_pt0 import PrivilegedTeacherPT0Error, canonical_json_bytes
from .privileged_teacher_pt1 import (
    AUTHORITY as PT1_AUTHORITY, PT1Record, PrivilegedTeacherPT1Error,
    evaluate_state_batch, verify_record,
)
from .privileged_teacher_pt1_natural import (
    NATURAL_PT1_SCHEMA, NaturalPT1Design, NaturalPT1Error, NaturalPT1State,
    TARGET_STATE_COUNT, _capture_round, _first_eligible, _state_from_round,
)


CAPACITY_SCHEMA = "privileged-teacher-pt1-capacity-v1"
CAPACITY_REPORT_SCHEMA = "privileged-teacher-pt1-capacity-report-v1"
CAPACITY_MANIFEST_SCHEMA = "privileged-teacher-pt1-capacity-manifest-v1"
CAPACITY_SEED_NAMESPACE = "privileged-teacher-pt1-capacity-out-of-population-v1"
CAPACITY_STATE_COUNT = 16
CAPACITY_POLICY_SEEDS = (0, 1, 2, 3)
CAPACITY_RESERVE_NUMERATOR = 1
CAPACITY_RESERVE_DENOMINATOR = 4
CAPACITY_AUTHORITIES = {
    "scientific_authorized": False,
    "gameplay_authorized": False,
    "training_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "merge_authorized": False,
}


class PT1CapacityError(PrivilegedTeacherPT1Error):
    """A capacity identity, resource, privacy, or write boundary drifted."""


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise PT1CapacityError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class CapacityDesign:
    capture_secret_sha256: str
    capture_attempts: int = 64
    reserve_numerator: int = CAPACITY_RESERVE_NUMERATOR
    reserve_denominator: int = CAPACITY_RESERVE_DENOMINATOR
    production_policy: str = "mc-s0-report-lcb"
    authorities: Mapping[str, bool] = field(
        default_factory=lambda: dict(CAPACITY_AUTHORITIES))

    def __post_init__(self) -> None:
        _sha(self.capture_secret_sha256, "capacity capture secret commitment")
        if self.capture_attempts <= 0 or isinstance(self.capture_attempts, bool):
            raise PT1CapacityError("capacity capture attempts must be positive")
        if (self.reserve_numerator <= 0 or self.reserve_denominator <= 0
                or isinstance(self.reserve_numerator, bool)
                or isinstance(self.reserve_denominator, bool)
                or self.reserve_numerator >= self.reserve_denominator):
            raise PT1CapacityError("capacity reserve must be a proper fraction")
        if self.production_policy != "mc-s0-report-lcb":
            raise PT1CapacityError("capacity production policy drift")
        if dict(self.authorities) != CAPACITY_AUTHORITIES:
            raise PT1CapacityError("capacity authorities must remain false")

    def payload(self) -> dict[str, object]:
        return {"schema": CAPACITY_SCHEMA,
                "capture_secret_sha256": self.capture_secret_sha256,
                "capture_attempts": self.capture_attempts,
                "reserve": {"numerator": self.reserve_numerator,
                             "denominator": self.reserve_denominator},
                "production_policy": self.production_policy,
                "selector_namespace": CAPACITY_SEED_NAMESPACE,
                "policy_seed_count": len(CAPACITY_POLICY_SEEDS),
                "state_count": CAPACITY_STATE_COUNT,
                "authority": dict(self.authorities)}


@dataclass(frozen=True)
class CapacityCoordinate:
    index: int
    rank: str
    banker: int
    role: str
    threshold: int

    def payload(self) -> dict[str, object]:
        return {"index": self.index, "trump_rank": self.rank,
                "banker": self.banker, "role": self.role,
                "remaining_hand_threshold": self.threshold}


@dataclass(frozen=True)
class CapacityReport:
    payload_value: Mapping[str, object]

    def payload(self) -> dict[str, object]:
        return copy.deepcopy(dict(self.payload_value))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


def capacity_coordinates() -> tuple[CapacityCoordinate, ...]:
    from ..engine.cards import RANKS
    rows = tuple(CapacityCoordinate(
        index, RANKS[index % len(RANKS)], index % 2,
        "banker-team" if index % 2 == 0 else "attacker-team",
        3 if index % 2 == 0 else 4) for index in range(CAPACITY_STATE_COUNT))
    if len(rows) != CAPACITY_STATE_COUNT \
            or {row.rank for row in rows} != set(RANKS) \
            or {row.banker for row in rows} != {0, 1} \
            or {row.role for row in rows} != {"banker-team", "attacker-team"} \
            or {row.threshold for row in rows} != {3, 4}:
        raise PT1CapacityError("capacity marginal coverage drift")
    return rows


def capacity_schedule_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes({
        "schema": CAPACITY_SCHEMA,
        "selector_namespace": CAPACITY_SEED_NAMESPACE,
        "coordinates": [row.payload() for row in capacity_coordinates()],
    })).hexdigest()


def _seed(secret: bytes, coordinate: CapacityCoordinate, attempt: int) -> int:
    return int.from_bytes(hmac.new(
        secret, canonical_json_bytes([
            CAPACITY_SCHEMA, CAPACITY_SEED_NAMESPACE,
            coordinate.payload(), attempt]), hashlib.sha256).digest()[:8], "big")


def _secret(design: CapacityDesign, secret: bytes) -> bytes:
    if type(secret) is not bytes or len(secret) != 32 \
            or hashlib.sha256(secret).hexdigest() != design.capture_secret_sha256:
        raise PT1CapacityError("capacity secret commitment drift")
    return secret


def capture_capacity_states(
        design: CapacityDesign, *, capture_secret: bytes,
        state_capture: Callable[..., object] | None = None) \
        -> tuple[tuple[CapacityCoordinate, NaturalPT1State], ...]:
    """Capture the fixed sixteen states through the real production route."""
    secret = _secret(design, capture_secret)
    natural_design = NaturalPT1Design(
        capture_secret_sha256=hashlib.sha256(secret).hexdigest())
    used_seeds = set()
    states = []
    for coordinate in capacity_coordinates():
        found = None
        for attempt in range(design.capture_attempts):
            round_seed = _seed(secret, coordinate, attempt)
            if round_seed in used_seeds:
                raise PT1CapacityError("capacity round seed collision")
            used_seeds.add(round_seed)
            candidate = (state_capture(design, coordinate, round_seed, attempt)
                         if state_capture is not None else
                         _capture_round(natural_design, round_seed,
                                       coordinate.rank, coordinate.banker).get(
                                           (coordinate.role, coordinate.threshold)))
            if isinstance(candidate, Mapping):
                candidate = candidate.get((coordinate.role, coordinate.threshold))
            if candidate is None:
                continue
            eligible = _first_eligible(
                candidate, role=coordinate.role, threshold=coordinate.threshold)
            if eligible is None:
                continue
            state = _state_from_round(
                natural_design, eligible, rank=coordinate.rank,
                banker=coordinate.banker, role=coordinate.role,
                threshold=coordinate.threshold, replicate=0,
                round_seed=round_seed)
            found = state
            break
        if found is None:
            raise PT1CapacityError(
                f"capacity state cell incomplete: {coordinate.payload()}")
        states.append((coordinate, found))
    if len(states) != CAPACITY_STATE_COUNT \
            or len({state.round_seed for _, state in states}) != CAPACITY_STATE_COUNT \
            or len({state.capture_round_cluster_sha256 for _, state in states}) != CAPACITY_STATE_COUNT:
        raise PT1CapacityError("capacity state population drift")
    return tuple(states)


def _runtime_identity() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root,
            text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PT1CapacityError("capacity source identity unavailable") from exc
    files = []
    for relative in (
            "server/shengji/rl/privileged_teacher_pt1.py",
            "server/shengji/rl/privileged_teacher_pt1_natural.py",
            "server/shengji/rl/privileged_teacher_pt1_statistics.py",
            "server/shengji/rl/privileged_teacher_pt1_capacity.py",
            "server/scripts/privileged_teacher_pt1_capacity.py"):
        path = root / relative
        if not path.is_file():
            raise PT1CapacityError("capacity source population incomplete")
        files.append({"path": relative,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    try:
        from ..engine import fast
        native = Path(getattr(getattr(fast, "_fast", None), "__file__", ""))
    except (ImportError, AttributeError, TypeError):
        native = Path()
    if not native.is_file():
        raise PT1CapacityError("capacity native identity unavailable")
    executable = Path(sys.executable).resolve()
    if not executable.is_file():
        raise PT1CapacityError("capacity Python identity unavailable")
    boot_source = Path("/proc/sys/kernel/random/boot_id")
    try:
        if boot_source.is_file():
            boot_identity = boot_source.read_bytes().strip()
        elif sys.platform == "darwin":
            boot_identity = subprocess.check_output(
                ["sysctl", "-n", "kern.boottime"],
                stderr=subprocess.DEVNULL).strip()
        else:
            raise PT1CapacityError("capacity boot identity unavailable")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PT1CapacityError("capacity boot identity unavailable") from exc
    if not boot_identity:
        raise PT1CapacityError("capacity boot identity unavailable")
    return {"git_head": head, "source_tree_dirty": dirty,
            "source_population_sha256": hashlib.sha256(
                canonical_json_bytes(files)).hexdigest(),
            "source_file_count": len(files),
            "host_name": platform.node(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "boot_identity_sha256": hashlib.sha256(boot_identity).hexdigest(),
            "python_version": platform.python_version(),
            "python_executable_sha256": hashlib.sha256(
                executable.read_bytes()).hexdigest(),
            "native_extension_sha256": hashlib.sha256(
                native.read_bytes()).hexdigest(),
            "compiled_engine": True, "strict_voids": True}


def _work(record: PT1Record, arm_name: str) -> dict[str, int]:
    arm = next(arm for arm in record.arms if arm.arm == arm_name)
    return {"n_determinizations": arm.work.n_determinizations,
            "report_worlds": arm.work.report_worlds,
            "selection_attempts": arm.work.selection_attempts,
            "selection_worlds": arm.work.selection_worlds,
            "report_attempts": arm.work.report_attempts,
            "report_worlds_accepted": arm.work.report_worlds_accepted,
            "searches": arm.work.searches,
            "attempted_rollouts": arm.work.attempted_rollouts,
            "completed_rollouts": arm.work.completed_rollouts,
            "exact_nodes": arm.work.exact_nodes,
            "exact_cache_hits": arm.work.exact_cache_hits}


def _redacted_row(coordinate: CapacityCoordinate, state: NaturalPT1State,
                  records: Sequence[PT1Record], *, wall_ns: int, cpu_ns: int,
                  rss_raw: int, rss_unit: str) -> dict[str, object]:
    if len(records) != len(CAPACITY_POLICY_SEEDS):
        raise PT1CapacityError("capacity evaluator seed count drift")
    for record, seed in zip(records, CAPACITY_POLICY_SEEDS):
        verify_record(record)
        if (record.public_state_sha256 != state.public_state_sha256
                or record.true_world_sha256 != state.true_world_sha256
                or any(arm.seed != seed for arm in record.arms)):
            raise PT1CapacityError("capacity record state/seed binding drift")
    # A and B genuinely execute once per policy seed. C is computed once and
    # copied into the four paired records, so counting all four C receipts
    # would inflate the measured exact work by 4x.
    work = {arm: {
        metric: sum(_work(record, arm)[metric] for record in records)
        for metric in _work(records[0], arm)} for arm in ("A", "B")}
    c_work = tuple(_work(record, "C") for record in records)
    if any(row != c_work[0] for row in c_work[1:]):
        raise PT1CapacityError("capacity shared C work drift")
    work["C"] = c_work[0]
    row = {"schema": CAPACITY_REPORT_SCHEMA,
           "index": coordinate.index, "trump_rank": coordinate.rank,
           "banker": coordinate.banker, "role": coordinate.role,
           "remaining_hand_threshold": coordinate.threshold,
           "public_state_sha256": state.public_state_sha256,
           "true_world_sha256": state.true_world_sha256,
           "capture_id_sha256": state.capture_id_sha256,
           "evaluator_identity_sha256": hashlib.sha256(canonical_json_bytes(
               sorted(record.evaluator_identity for record in records))).hexdigest(),
           "policy_seed_count": len(records), "work": work,
           "wall_nanoseconds": wall_ns, "cpu_nanoseconds": cpu_ns,
           "peak_rss_raw": rss_raw, "peak_rss_unit": rss_unit,
           # Measure the real four-record scientific payload without
           # retaining any action, utility, point, world or seed bytes.
           "artifact_projection_bytes": sum(
               len(record.canonical_bytes()) for record in records)}
    return row


def _cap(value: int, numerator: int, denominator: int) -> int:
    return (value * (denominator + numerator) + denominator - 1) // denominator


def _caps(rows: Sequence[Mapping[str, object]], design: CapacityDesign,
          *, capture_wall_ns: int = 0, capture_cpu_ns: int = 0) -> dict[str, int]:
    if type(capture_wall_ns) is not int or type(capture_cpu_ns) is not int \
            or capture_wall_ns < 0 or capture_cpu_ns < 0:
        raise PT1CapacityError("capacity capture resource drift")
    if not rows:
        return {}
    capture_scale = (TARGET_STATE_COUNT + CAPACITY_STATE_COUNT - 1) \
        // CAPACITY_STATE_COUNT
    max_wall = max(int(row["wall_nanoseconds"]) for row in rows)
    max_cpu = max(int(row["cpu_nanoseconds"]) for row in rows)
    max_artifact = max(int(row["artifact_projection_bytes"]) for row in rows)
    max_nodes = max(int(row["work"]["C"]["exact_nodes"]) for row in rows)
    max_rss_bytes = max(
        int(row["peak_rss_raw"]) *
        (1024 if row["peak_rss_unit"] == "kibibytes" else 1)
        for row in rows)
    return {
        "scientific_wall_nanoseconds": _cap(
            capture_wall_ns * capture_scale + max_wall * TARGET_STATE_COUNT,
            design.reserve_numerator, design.reserve_denominator),
        "scientific_cpu_nanoseconds": _cap(
            capture_cpu_ns * capture_scale + max_cpu * TARGET_STATE_COUNT,
            design.reserve_numerator, design.reserve_denominator),
        "peak_rss_bytes": _cap(
            max_rss_bytes, design.reserve_numerator, design.reserve_denominator),
        "scientific_artifact_bytes": _cap(
            max_artifact * TARGET_STATE_COUNT,
            design.reserve_numerator, design.reserve_denominator),
        "exact_nodes_per_state": _cap(
            max_nodes, design.reserve_numerator, design.reserve_denominator),
        "scientific_exact_nodes": _cap(
            max_nodes * TARGET_STATE_COUNT,
            design.reserve_numerator, design.reserve_denominator),
    }


def run_capacity(
        design: CapacityDesign, *, capture_secret: bytes,
        state_capture: Callable[..., object] | None = None,
        deadline: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        progress_sink: Callable[[dict[str, object]], object] | None = None,
        evaluator: Callable[..., Sequence[PT1Record]] = evaluate_state_batch) \
        -> CapacityReport:
    if deadline is not None and not isinstance(deadline, (int, float)):
        raise PT1CapacityError("capacity deadline must be numeric")
    if not callable(monotonic) or (progress_sink is not None
                                   and not callable(progress_sink)):
        raise PT1CapacityError("capacity callback drift")
    capture_started = time.perf_counter_ns()
    capture_cpu_started = time.process_time_ns()
    states = capture_capacity_states(
        design, capture_secret=capture_secret, state_capture=state_capture)
    capture_wall_ns = time.perf_counter_ns() - capture_started
    capture_cpu_ns = time.process_time_ns() - capture_cpu_started
    runtime = _runtime_identity()
    if runtime["source_tree_dirty"] is not False:
        raise PT1CapacityError("capacity source tree must be clean")
    rows = []
    for coordinate, state in states:
        if deadline is not None and monotonic() >= deadline:
            break
        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        records = tuple(evaluator(
            state.public_round, state.true_world,
            seeds=CAPACITY_POLICY_SEEDS))
        row = _redacted_row(
            coordinate, state, records,
            wall_ns=time.perf_counter_ns() - started,
            cpu_ns=time.process_time_ns() - cpu_started,
            rss_raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            rss_unit="bytes" if sys.platform == "darwin" else "kibibytes")
        rows.append(row)
        if progress_sink is not None:
            progress_sink({"completed_units": len(rows),
                           "total_units": CAPACITY_STATE_COUNT,
                           "percent_basis_points": len(rows) * 10_000
                           // CAPACITY_STATE_COUNT,
                           "status": "TRUNCATED"})
    complete = len(rows) == CAPACITY_STATE_COUNT
    body = {"schema": CAPACITY_REPORT_SCHEMA,
            "design_sha256": hashlib.sha256(
                canonical_json_bytes(design.payload())).hexdigest(),
            "capture_secret_sha256": design.capture_secret_sha256,
            "selector_namespace": CAPACITY_SEED_NAMESPACE,
            "schedule_sha256": capacity_schedule_sha256(),
            "runtime": runtime,
            "capture_wall_nanoseconds": capture_wall_ns,
            "capture_cpu_nanoseconds": capture_cpu_ns,
            "records": rows, "record_count": len(rows),
            "total_record_count": CAPACITY_STATE_COUNT,
            "status": "COMPLETE" if complete else "TRUNCATED",
            "truncated_by_deadline": not complete,
            "progress": {"completed_units": len(rows),
                         "total_units": CAPACITY_STATE_COUNT,
                         "percent_basis_points": len(rows) * 10_000
                         // CAPACITY_STATE_COUNT},
            "reserve": {"numerator": design.reserve_numerator,
                        "denominator": design.reserve_denominator},
            "caps": _caps(rows, design, capture_wall_ns=capture_wall_ns,
                          capture_cpu_ns=capture_cpu_ns),
            "authority": dict(CAPACITY_AUTHORITIES)}
    body["population_digest_sha256"] = hashlib.sha256(
        canonical_json_bytes([[row["index"], row["public_state_sha256"],
                               row["true_world_sha256"],
                               row["capture_id_sha256"]] for row in rows])).hexdigest()
    body["report_sha256"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    report = CapacityReport(body)
    verify_capacity_report(report, design=design)
    return report


def verify_capacity_report(
        report: CapacityReport | Mapping[str, object] | bytes,
        *, design: CapacityDesign | None = None) -> CapacityReport:
    if isinstance(report, bytes):
        try:
            payload = json.loads(report.decode("ascii"))
        except Exception as exc:
            raise PT1CapacityError("capacity report is not canonical") from exc
        if canonical_json_bytes(payload) != report:
            raise PT1CapacityError("capacity report is not canonical")
    elif isinstance(report, CapacityReport):
        payload = report.payload()
    elif isinstance(report, Mapping):
        payload = copy.deepcopy(dict(report))
    else:
        raise PT1CapacityError("capacity report type refused")
    required = {"schema", "design_sha256", "capture_secret_sha256",
                "selector_namespace", "schedule_sha256", "runtime", "records",
                "capture_wall_nanoseconds", "capture_cpu_nanoseconds",
                "record_count", "total_record_count", "status",
                "truncated_by_deadline", "progress", "reserve", "caps",
                "authority", "population_digest_sha256", "report_sha256"}
    if set(payload) != required or payload["schema"] != CAPACITY_REPORT_SCHEMA:
        raise PT1CapacityError("capacity report field/schema drift")
    _sha(payload["design_sha256"], "capacity design identity")
    _sha(payload["capture_secret_sha256"], "capacity secret commitment")
    _sha(payload["schedule_sha256"], "capacity schedule identity")
    _sha(payload["population_digest_sha256"], "capacity population identity")
    _sha(payload["report_sha256"], "capacity report identity")
    body = {key: payload[key] for key in required if key != "report_sha256"}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != payload["report_sha256"]:
        raise PT1CapacityError("capacity report hash drift")
    if design is not None:
        if payload["design_sha256"] != hashlib.sha256(
                canonical_json_bytes(design.payload())).hexdigest() \
                or payload["capture_secret_sha256"] != design.capture_secret_sha256:
            raise PT1CapacityError("capacity design/secret identity drift")
    if payload["selector_namespace"] != CAPACITY_SEED_NAMESPACE \
            or payload["schedule_sha256"] != capacity_schedule_sha256():
        raise PT1CapacityError("capacity selector/schedule drift")
    if payload["authority"] != CAPACITY_AUTHORITIES:
        raise PT1CapacityError("capacity authority drift")
    runtime = payload["runtime"]
    runtime_keys = {"git_head", "source_tree_dirty", "source_population_sha256",
                    "source_file_count", "host_name", "machine",
                    "logical_cpu_count", "boot_identity_sha256", "python_version",
                    "python_executable_sha256", "native_extension_sha256",
                    "compiled_engine", "strict_voids"}
    if type(runtime) is not dict or set(runtime) != runtime_keys \
            or type(runtime["git_head"]) is not str \
            or len(runtime["git_head"]) != 40 \
            or any(char not in "0123456789abcdef" for char in runtime["git_head"]) \
            or runtime["source_tree_dirty"] is not False \
            or type(runtime["source_file_count"]) is not int \
            or runtime["source_file_count"] != 5 \
            or type(runtime["host_name"]) is not str or not runtime["host_name"] \
            or type(runtime["machine"]) is not str or not runtime["machine"] \
            or type(runtime["logical_cpu_count"]) is not int \
            or runtime["logical_cpu_count"] <= 0 \
            or type(runtime["python_version"]) is not str \
            or any(_sha(runtime[key], f"capacity runtime {key}") is None for key in (
                "source_population_sha256", "python_executable_sha256",
                "native_extension_sha256", "boot_identity_sha256")) \
            or runtime["compiled_engine"] is not True \
            or runtime["strict_voids"] is not True:
        raise PT1CapacityError("capacity runtime identity drift")
    for key in ("capture_wall_nanoseconds", "capture_cpu_nanoseconds"):
        if type(payload[key]) is not int or payload[key] < 0:
            raise PT1CapacityError("capacity capture resource drift")
    records = payload["records"]
    if not isinstance(records, list) or len(records) != payload["record_count"] \
            or payload["total_record_count"] != CAPACITY_STATE_COUNT \
            or payload["record_count"] > CAPACITY_STATE_COUNT:
        raise PT1CapacityError("capacity record population drift")
    if payload["truncated_by_deadline"] is not (payload["record_count"] < CAPACITY_STATE_COUNT) \
            or payload["status"] != ("COMPLETE" if payload["record_count"] == CAPACITY_STATE_COUNT
                                       else "TRUNCATED"):
        raise PT1CapacityError("capacity completion drift")
    progress = payload["progress"]
    expected_progress = {
        "completed_units": payload["record_count"],
        "total_units": CAPACITY_STATE_COUNT,
        "percent_basis_points": payload["record_count"] * 10_000
        // CAPACITY_STATE_COUNT}
    if progress != expected_progress:
        raise PT1CapacityError("capacity progress drift")
    expected = capacity_coordinates()
    observed = []
    row_keys = {"schema", "index", "trump_rank", "banker", "role",
                "remaining_hand_threshold", "public_state_sha256",
                "true_world_sha256", "capture_id_sha256",
                "evaluator_identity_sha256", "policy_seed_count", "work",
                "wall_nanoseconds", "cpu_nanoseconds", "peak_rss_raw",
                "peak_rss_unit", "artifact_projection_bytes"}
    for coordinate, row in zip(expected, records):
        if type(row) is not dict or set(row) != row_keys \
                or row.get("schema") != CAPACITY_REPORT_SCHEMA \
                or row.get("index") != coordinate.index \
                or row.get("trump_rank") != coordinate.rank \
                or row.get("banker") != coordinate.banker \
                or row.get("role") != coordinate.role \
                or row.get("remaining_hand_threshold") != coordinate.threshold:
            raise PT1CapacityError("capacity selector/coverage drift")
        forbidden = {"selected_action", "selected_utilities", "selected_points",
                     "legal_ballot", "arms", "hidden_state", "true_world",
                     "round_seed", "policy_seeds", "capture_secret"}
        if forbidden & set(row):
            raise PT1CapacityError("capacity report redaction drift")
        for key in ("public_state_sha256", "true_world_sha256",
                    "capture_id_sha256", "evaluator_identity_sha256"):
            _sha(row[key], f"capacity row {key}")
        for key in ("wall_nanoseconds", "cpu_nanoseconds", "peak_rss_raw",
                    "artifact_projection_bytes"):
            if type(row[key]) is not int or row[key] < 0:
                raise PT1CapacityError("capacity resource receipt drift")
        if row["peak_rss_unit"] not in {"bytes", "kibibytes"}:
            raise PT1CapacityError("capacity RSS unit drift")
        if row["policy_seed_count"] != len(CAPACITY_POLICY_SEEDS):
            raise PT1CapacityError("capacity policy seed count drift")
        work = row["work"]
        work_keys = {"A", "B", "C"}
        metric_keys = {
            "n_determinizations", "report_worlds", "selection_attempts",
            "selection_worlds", "report_attempts", "report_worlds_accepted",
            "searches", "attempted_rollouts", "completed_rollouts",
            "exact_nodes", "exact_cache_hits"}
        if type(work) is not dict or set(work) != work_keys or any(
                type(arm_work) is not dict or set(arm_work) != metric_keys
                or any(type(value) is not int or value < 0
                       for value in arm_work.values())
                for arm_work in work.values()):
            raise PT1CapacityError("capacity work receipt drift")
        observed.append(row)
    if payload["population_digest_sha256"] != hashlib.sha256(
            canonical_json_bytes([[row["index"], row["public_state_sha256"],
                                   row["true_world_sha256"],
                                   row["capture_id_sha256"]] for row in observed])).hexdigest():
        raise PT1CapacityError("capacity population digest drift")
    reserve = payload["reserve"]
    if reserve != {"numerator": CAPACITY_RESERVE_NUMERATOR,
                   "denominator": CAPACITY_RESERVE_DENOMINATOR}:
        raise PT1CapacityError("capacity reserve drift")
    expected_caps = _caps(observed, CapacityDesign(
        payload["capture_secret_sha256"], reserve_numerator=reserve["numerator"],
        reserve_denominator=reserve["denominator"]),
        capture_wall_ns=payload["capture_wall_nanoseconds"],
        capture_cpu_ns=payload["capture_cpu_nanoseconds"]) if observed else {}
    if payload["caps"] != expected_caps:
        raise PT1CapacityError("capacity derived caps drift")
    if design is not None and payload["runtime"] != _runtime_identity():
        raise PT1CapacityError("capacity source/runtime/native identity drift")
    return CapacityReport(payload)


def manifest_for(report: CapacityReport | Mapping[str, object]) -> dict[str, object]:
    payload = report.payload() if isinstance(report, CapacityReport) else dict(report)
    return {"schema": CAPACITY_MANIFEST_SCHEMA,
            "report_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
            "authority": dict(CAPACITY_AUTHORITIES)}


def verify_manifest(manifest: Mapping[str, object], report: CapacityReport | Mapping[str, object]) -> None:
    if not isinstance(manifest, Mapping) or set(manifest) != {
            "schema", "report_sha256", "authority"}:
        raise PT1CapacityError("capacity manifest drift")
    expected = manifest_for(report)
    if dict(manifest) != expected:
        raise PT1CapacityError("capacity manifest mismatch")


__all__ = [
    "CAPACITY_AUTHORITIES", "CAPACITY_MANIFEST_SCHEMA", "CAPACITY_POLICY_SEEDS",
    "CAPACITY_REPORT_SCHEMA", "CAPACITY_RESERVE_DENOMINATOR",
    "CAPACITY_RESERVE_NUMERATOR", "CAPACITY_SCHEMA", "CAPACITY_SEED_NAMESPACE",
    "CAPACITY_STATE_COUNT", "CapacityCoordinate", "CapacityDesign",
    "CapacityReport", "PT1CapacityError", "capacity_coordinates",
    "capacity_schedule_sha256", "capture_capacity_states", "manifest_for",
    "run_capacity", "verify_capacity_report", "verify_manifest",
]
