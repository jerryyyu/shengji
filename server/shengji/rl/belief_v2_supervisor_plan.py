"""Closed task plan for the BELIEF-V1 V2/R4 offline supervisor.

The prior R2 operator failure came from constructing a Cartesian human
reference matrix outside the reviewed source.  This module makes the complete
task population a source-bound value.  It hashes private source files only to
classify their already-reviewed H0 group digests; it never parses source rows,
opens outcomes, starts a worker, or grants execution authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .belief_contract import canonical_json_bytes
from .belief_v2_freeze_builder import standard_cohort_plans
from .belief_v2_human_inventory import H0_GROUP_SCHEMA, H0_SPLIT_SCHEMA
from .belief_v2_protocol import V2_CAPTURE_LANES


SUPERVISOR_PLAN_SCHEMA = "belief-v1-v2-supervisor-plan-v3"
CALIBRATION_REPLICATES = (
    "calibration-replicate-0", "calibration-replicate-1")
TEST_REPLICATE = "test-primary"
EXPECTED_HUMAN_SOURCE_COUNT = 30
HUMAN_SPLITS = ("train", "calibration", "test")


class BeliefV2SupervisorPlanError(ValueError):
    """The source population, task matrix, or stage order drifted."""


@dataclass(frozen=True)
class V2SupervisorTaskV1:
    name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class V2SupervisorStageV1:
    name: str
    concurrency: int
    tasks: tuple[V2SupervisorTaskV1, ...]


@dataclass(frozen=True)
class V2SupervisorPlanV1:
    stages: tuple[V2SupervisorStageV1, ...]
    human_source_count: int
    human_split_counts: tuple[tuple[str, int], ...]
    human_reference_replicate_counts: tuple[tuple[str, int], ...]
    schema: str = SUPERVISOR_PLAN_SCHEMA

    def summary(self) -> dict[str, Any]:
        validate_supervisor_plan(self)
        return {
            "schema": self.schema,
            "stage_order": [stage.name for stage in self.stages],
            "stage_concurrency": [stage.concurrency for stage in self.stages],
            "stage_task_counts": [len(stage.tasks) for stage in self.stages],
            "task_count": sum(len(stage.tasks) for stage in self.stages),
            "human_source_count": self.human_source_count,
            "human_split_counts": dict(self.human_split_counts),
            "human_reference_replicate_counts": dict(
                self.human_reference_replicate_counts),
            "execution_plan_sha256": self.execution_sha256(),
            "human_source_bytes_hashed": True,
            "human_source_records_parsed": False,
            "outcome_fields_opened": False,
            "cache_stage_count": 1,
            "retry_authorized": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_summary_bytes(self) -> bytes:
        return canonical_json_bytes(self.summary())

    def execution_bytes(self) -> bytes:
        """Bind every internal task argument without publishing it in summary."""
        validate_supervisor_plan(self)
        return canonical_json_bytes({
            "schema": "belief-v1-v2-supervisor-execution-plan-v2",
            "stages": [{
                "name": stage.name,
                "concurrency": stage.concurrency,
                "tasks": [{
                    "name": task.name,
                    "arguments": list(task.arguments),
                } for task in stage.tasks],
            } for stage in self.stages],
            "retry_authorized": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        })

    def execution_sha256(self) -> str:
        return hashlib.sha256(self.execution_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _group_digest(raw: bytes) -> str:
    source_sha256 = hashlib.sha256(raw).hexdigest()
    return hashlib.sha256(
        f"{H0_GROUP_SCHEMA}|{source_sha256}".encode("ascii")).hexdigest()


def _split_population(group_split: dict[str, Any]) \
        -> dict[str, frozenset[str]]:
    if type(group_split) is not dict \
            or group_split.get("schema") != H0_SPLIT_SCHEMA \
            or type(group_split.get("splits")) is not dict \
            or set(group_split["splits"]) != set(HUMAN_SPLITS):
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor H0 split identity drift")
    result: dict[str, frozenset[str]] = {}
    population: set[str] = set()
    for split in HUMAN_SPLITS:
        row = group_split["splits"].get(split)
        values = row.get("group_digests") if type(row) is dict else None
        if type(values) is not list \
                or any(not _is_sha256(value) for value in values):
            raise BeliefV2SupervisorPlanError(
                "V2 supervisor H0 split population drift")
        members = frozenset(values)
        if not values or len(members) != len(values) \
                or row.get("group_count") != len(values) \
                or population.intersection(members):
            raise BeliefV2SupervisorPlanError(
                "V2 supervisor H0 split population drift")
        population.update(members)
        result[split] = members
    if len(population) != EXPECTED_HUMAN_SOURCE_COUNT:
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor H0 split union drift")
    return result


def _classify_sources(
        source_paths: Iterable[Path], group_split: dict[str, Any]) \
        -> tuple[tuple[Path, str, str], ...]:
    populations = _split_population(group_split)
    rows = []
    seen_paths: set[Path] = set()
    seen_groups: set[str] = set()
    for source in source_paths:
        path = Path(source).resolve()
        if path in seen_paths or path.is_symlink() or not path.is_file():
            raise BeliefV2SupervisorPlanError(
                "V2 supervisor human source shape drift")
        digest = _group_digest(path.read_bytes())
        matches = [split for split, values in populations.items()
                   if digest in values]
        if len(matches) != 1 or digest in seen_groups:
            raise BeliefV2SupervisorPlanError(
                "V2 supervisor human source classification drift")
        seen_paths.add(path)
        seen_groups.add(digest)
        rows.append((path, digest, matches[0]))
    expected_population = set().union(*populations.values())
    if seen_groups != expected_population:
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor human source population drift")
    return tuple(sorted(rows, key=lambda row: row[1]))


def _task(name: str, *arguments: str) -> V2SupervisorTaskV1:
    return V2SupervisorTaskV1(name=name, arguments=tuple(arguments))


def build_supervisor_plan(
        *, human_source_paths: Iterable[Path],
        group_split: dict[str, Any]) -> V2SupervisorPlanV1:
    """Build the exact ten-stage R4 task plan without opening row content."""
    sources = _classify_sources(human_source_paths, group_split)
    capture = tuple(_task(
        f"capture-lane-{lane:02d}", "capture-lane", "--lane", str(lane))
        for lane in range(V2_CAPTURE_LANES))
    human_capture = tuple(_task(
        f"human-capture-{index:02d}", "human-capture", "--source-path",
        str(path)) for index, (path, _digest, _split) in enumerate(sources))
    references = [
        _task(f"reference-lane-{lane:02d}", "reference-lane", "--lane",
              str(lane)) for lane in range(V2_CAPTURE_LANES)]
    replicate_counts = {
        CALIBRATION_REPLICATES[0]: 0,
        CALIBRATION_REPLICATES[1]: 0,
        TEST_REPLICATE: 0,
    }
    for index, (path, _digest, split) in enumerate(sources):
        replicates = (CALIBRATION_REPLICATES if split == "calibration"
                      else (TEST_REPLICATE,) if split == "test" else ())
        for replicate in replicates:
            references.append(_task(
                f"human-reference-{index:02d}-{replicate}",
                "human-reference", "--source-path", str(path),
                "--replicate", replicate))
            replicate_counts[replicate] += 1
    cohorts = tuple(plan.cohort_id for plan in standard_cohort_plans())
    stages = (
        V2SupervisorStageV1("synthetic-capture", V2_CAPTURE_LANES, capture),
        V2SupervisorStageV1(
            "human-capture", V2_CAPTURE_LANES, human_capture),
        V2SupervisorStageV1(
            "training-input-index", 1,
            (_task("build-training-index", "build-training-index"),)),
        V2SupervisorStageV1(
            "training-tensor-cache", 1,
            (_task("build-training-cache", "build-training-cache"),)),
        V2SupervisorStageV1(
            "device-qualification", 1,
            (_task("qualify-device", "qualify-device"),)),
        V2SupervisorStageV1("references", V2_CAPTURE_LANES,
                            tuple(references)),
        V2SupervisorStageV1(
            "training", len(cohorts), tuple(_task(
                f"train-{cohort}", "train-cohort", "--cohort-id", cohort)
                for cohort in cohorts)),
        V2SupervisorStageV1(
            "calibration", 1, (_task("calibrate", "calibrate"),)),
        V2SupervisorStageV1(
            "single-test-opening", 1,
            (_task("open-test", "open-test"),)),
        V2SupervisorStageV1(
            "terminal-verification", 1,
            (_task("verify-terminal", "verify-terminal"),)),
    )
    split_counts = {
        split: sum(row[2] == split for row in sources)
        for split in HUMAN_SPLITS}
    plan = V2SupervisorPlanV1(
        stages=stages, human_source_count=len(sources),
        human_split_counts=tuple(split_counts.items()),
        human_reference_replicate_counts=tuple(replicate_counts.items()))
    validate_supervisor_plan(plan)
    return plan


def validate_supervisor_plan(plan: V2SupervisorPlanV1) -> None:
    """Refuse any dropped/extra task, old Cartesian matrix, or stage drift."""
    expected_names = (
        "synthetic-capture", "human-capture", "training-input-index",
        "training-tensor-cache", "device-qualification", "references",
        "training", "calibration", "single-test-opening",
        "terminal-verification")
    expected_concurrency = (16, 16, 1, 1, 1, 16, 4, 1, 1, 1)
    try:
        split_counts = dict(plan.human_split_counts)
        replicate_counts = dict(plan.human_reference_replicate_counts)
    except (TypeError, ValueError) as exc:
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor plan identity drift") from exc
    if set(split_counts) != set(HUMAN_SPLITS) \
            or any(type(value) is not int or value <= 0
                   for value in split_counts.values()) \
            or sum(split_counts.values()) != EXPECTED_HUMAN_SOURCE_COUNT:
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor plan identity drift")
    expected_replicates = {
        CALIBRATION_REPLICATES[0]: split_counts["calibration"],
        CALIBRATION_REPLICATES[1]: split_counts["calibration"],
        TEST_REPLICATE: split_counts["test"],
    }
    expected_reference_count = (
        V2_CAPTURE_LANES + 2 * split_counts["calibration"]
        + split_counts["test"])
    expected_task_counts = (
        16, EXPECTED_HUMAN_SOURCE_COUNT, 1, 1, 1,
        expected_reference_count, 4, 1, 1, 1)
    if type(plan) is not V2SupervisorPlanV1 \
            or plan.schema != SUPERVISOR_PLAN_SCHEMA \
            or tuple(stage.name for stage in plan.stages) != expected_names \
            or tuple(stage.concurrency for stage in plan.stages) \
            != expected_concurrency \
            or tuple(len(stage.tasks) for stage in plan.stages) \
            != expected_task_counts \
            or plan.human_source_count != EXPECTED_HUMAN_SOURCE_COUNT \
            or replicate_counts != expected_replicates:
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor plan identity drift")
    all_tasks = tuple(task for stage in plan.stages for task in stage.tasks)
    if len(all_tasks) != sum(expected_task_counts) \
            or len({task.name for task in all_tasks}) != len(all_tasks) \
            or any(type(task) is not V2SupervisorTaskV1
                   or not task.name or not task.arguments
                   or any(type(value) is not str or not value
                          for value in task.arguments)
                   for task in all_tasks):
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor task population drift")
    reference_tasks = plan.stages[5].tasks[V2_CAPTURE_LANES:]
    observed_replicates = [task.arguments[-1] for task in reference_tasks]
    if len(reference_tasks) != expected_reference_count - V2_CAPTURE_LANES \
            or {value: observed_replicates.count(value)
                for value in set(observed_replicates)} != expected_replicates \
            or any(len(task.arguments) != 5
                   or task.arguments[0] != "human-reference"
                   or task.arguments[1] != "--source-path"
                   or task.arguments[3] != "--replicate"
                   for task in reference_tasks):
        raise BeliefV2SupervisorPlanError(
            "V2 supervisor human reference matrix drift")
