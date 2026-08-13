#!/usr/bin/env python3
"""Non-executable design for a checkpointed Pair whole-game successor.

This module deliberately has no gameplay or launch command.  It records the
smallest recovery boundary that would keep a fresh fixed population usable
after a worker, host, or supervisor interruption:

* capacity is measured at the intended concurrency, not extrapolated from one
  idle worker;
* the scored population is split into immutable 32-cluster microshards;
* a score-free manifest may expose only microshard identities and hashes;
* a reviewed resume may schedule only missing microshards after proving that
  no prior worker survives; and
* aggregate access remains closed until every microshard is present and an
  independent supervisor-final review passes.

The currently running ``pair-aware-whole-round-screen-v3`` is not changed by
this design.  Its packet expressly denies retry or extension.  If it times
out, its progress logs are operational capacity evidence only; no in-memory
outcome from that attempt is eligible for reuse.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass


SCHEMA = "pair-aware-rollout-checkpoint-successor-design-v1"
CAPACITY_SCHEMA = "pair-aware-rollout-concurrent-capacity-result-v1"
MANIFEST_SCHEMA = "pair-aware-rollout-microshard-manifest-v1"
MANIFEST_REVIEW_SCHEMA = "pair-aware-rollout-microshard-manifest-review-v1"

PARENT_GIT = "cd206707f56fbb576c6333b1ef7f86d8fc9c4451"
PARENT_RUN_ID = "pair-aware-whole-round-screen-v3"
PARENT_PACKET_SHA256 = (
    "4ece02b93ebb49020b9654bdc3d9bc2cd27d8f9db4bf9201b14443f479cdae47"
)
PARENT_SEED0 = 445_300_000_000

RUN_ID = "pair-aware-whole-round-checkpoint-screen-v1"
CAPACITY_RUN_ID = "pair-aware-whole-round-concurrent-capacity-v1"
CAPACITY_SEED0 = 499_000_000_000
SCREEN_SEED0 = 500_000_000_000
STREAM_STRIDE = 3_000_017
MAX_ROLE_OFFSET = 1_500_000

# Keep the powered scientific design unchanged.  Only its execution geometry
# changes from eight 896-cluster all-or-nothing shards to atomic microshards.
SCREEN_CLUSTERS = 7_168
MICROSHARD_CLUSTERS = 32
MICROSHARDS = SCREEN_CLUSTERS // MICROSHARD_CLUSTERS

# A capacity packet must saturate the exact intended runtime.  Eight clusters
# per lane turns a 4-seed/one-process spot check into at least 128 fresh
# clusters on a 16-worker host while remaining a bounded score-free preflight.
MIN_WORKERS = 16
CAPACITY_CLUSTERS_PER_WORKER = 8
CONCURRENT_CAPACITY_SAFETY_FACTOR = 1.5
MAX_PLANNED_WALL_HOURS = 48.0

RESERVED_POPULATIONS = (
    {
        "name": PARENT_RUN_ID,
        "seed0": PARENT_SEED0,
        "clusters": SCREEN_CLUSTERS,
        "stride": STREAM_STRIDE,
        "max_role_offset": MAX_ROLE_OFFSET,
    },
    {
        "name": "pair-cap-attacker-gate-capacity-v1",
        "seed0": 620_000_000_000,
        "clusters": 8,
        "stride": STREAM_STRIDE,
        "max_role_offset": MAX_ROLE_OFFSET,
    },
    {
        "name": "pair-cap-attacker-gate-evaluation-v1",
        "seed0": 621_000_000_000,
        "clusters": 4_608,
        "stride": STREAM_STRIDE,
        "max_role_offset": MAX_ROLE_OFFSET,
    },
)


class DesignRefused(RuntimeError):
    """A construction, capacity, checkpoint, or resume contract drifted."""


@dataclass(frozen=True)
class Population:
    seed0: int
    clusters: int
    stride: int = STREAM_STRIDE
    max_role_offset: int = MAX_ROLE_OFFSET

    @property
    def low(self) -> int:
        return self.seed0

    @property
    def high(self) -> int:
        return (
            self.seed0
            + self.stride * (self.clusters - 1)
            + self.max_role_offset
        )


def populations_overlap(left: Population, right: Population) -> bool:
    return not (left.high < right.low or right.high < left.low)


def _reserved_population(value: dict) -> Population:
    return Population(
        seed0=value["seed0"], clusters=value["clusters"],
        stride=value["stride"], max_role_offset=value["max_role_offset"],
    )


def pace_projection(*, elapsed_hours: float, clusters_complete: int,
                    clusters_total: int = 896,
                    timeout_hours: float = 64.0) -> dict[str, float]:
    """Return score-free pacing arithmetic; never reads a shard artifact."""
    if (not math.isfinite(elapsed_hours) or elapsed_hours <= 0
            or not isinstance(clusters_complete, int)
            or isinstance(clusters_complete, bool)
            or not 0 < clusters_complete < clusters_total
            or not math.isfinite(timeout_hours)
            or timeout_hours <= elapsed_hours):
        raise DesignRefused("live pace inputs are invalid")
    current_rate = clusters_complete / elapsed_hours
    remaining_hours = timeout_hours - elapsed_hours
    required_rate = (clusters_total - clusters_complete) / remaining_hours
    projected_total_hours = clusters_total / current_rate
    return {
        "current_clusters_per_hour": current_rate,
        "required_remaining_clusters_per_hour": required_rate,
        "required_throughput_acceleration_fraction": (
            required_rate / current_rate - 1.0),
        "projected_total_hours_at_current_rate": projected_total_hours,
    }


def design_record() -> dict:
    screen = Population(SCREEN_SEED0, SCREEN_CLUSTERS)
    capacity_clusters = MIN_WORKERS * CAPACITY_CLUSTERS_PER_WORKER
    capacity = Population(CAPACITY_SEED0, capacity_clusters)
    return {
        "schema": SCHEMA,
        "parent": {
            "git": PARENT_GIT,
            "run_id": PARENT_RUN_ID,
            "packet_sha256": PARENT_PACKET_SHA256,
            "current_run_unchanged": True,
            "current_namespace_retry_or_extension_authorized": False,
            "current_outcomes_or_shards_reusable": False,
            "if_timeout": "HOLD_INCOMPLETE_NO_AGGREGATE",
            "reusable_after_review": [
                "score-free progress counts",
                "process CPU and elapsed time",
                "runtime and scheduling profile",
            ],
        },
        "capacity": {
            "run_id": CAPACITY_RUN_ID,
            "seed0": CAPACITY_SEED0,
            "minimum_workers": MIN_WORKERS,
            "clusters_per_worker": CAPACITY_CLUSTERS_PER_WORKER,
            "minimum_clusters": capacity_clusters,
            "all_workers_start_concurrently": True,
            "same_source_runtime_and_worker_nice_as_screen": True,
            "outcomes_computed_in_memory_then_discarded": True,
            "outcomes_published": False,
            "planning_statistic": "maximum lane seconds per cluster",
            "safety_factor": CONCURRENT_CAPACITY_SAFETY_FACTOR,
            "max_planned_wall_hours": MAX_PLANNED_WALL_HOURS,
        },
        "screen": {
            "run_id": RUN_ID,
            "seed0": SCREEN_SEED0,
            "clusters": SCREEN_CLUSTERS,
            "stream_stride": STREAM_STRIDE,
            "microshard_clusters": MICROSHARD_CLUSTERS,
            "microshards": MICROSHARDS,
            "primary_metrics_and_decision_rule_unchanged": True,
            "fresh_population": True,
            "immutable_microshard_outputs": True,
            "outcome_files_closed_until_supervisor_review": True,
            "score_free_progress_fields": [
                "microshard_index", "clusters", "sha256",
                "elapsed_seconds", "worker_runtime_profile_sha256",
            ],
        },
        "resume": {
            "unit": "fixed campaign, not a new statistical population",
            "only_missing_microshards": True,
            "completed_microshards_never_overwritten_or_recomputed": True,
            "zero_surviving_prior_workers_required": True,
            "same_packet_population_source_and_runtime_required": True,
            "score_free_manifest_required": True,
            "independent_manifest_review_required": True,
            "outcome_access_before_resume": False,
            "aggregate_before_all_microshards": False,
            "host_migration": (
                "allowed only between packet-bound homogeneous runtime "
                "profiles with separately reviewed parity and concurrent "
                "capacity evidence"
            ),
        },
        "reserved_populations": [copy.deepcopy(value)
                                 for value in RESERVED_POPULATIONS],
        "authority": {
            "capacity_execution_authorized": False,
            "screen_execution_authorized": False,
            "resume_execution_authorized": False,
            "aggregate_execution_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }


def design_problems(value: object) -> list[str]:
    expected = design_record()
    if value != expected:
        return ["checkpoint successor design drift"]
    problems = []
    if SCREEN_CLUSTERS % MICROSHARD_CLUSTERS:
        problems.append("screen does not divide into complete microshards")
    screen = Population(SCREEN_SEED0, SCREEN_CLUSTERS)
    capacity = Population(
        CAPACITY_SEED0, MIN_WORKERS * CAPACITY_CLUSTERS_PER_WORKER)
    for reserved in map(_reserved_population, RESERVED_POPULATIONS):
        if populations_overlap(screen, reserved):
            problems.append("screen population overlaps a reserved population")
        if populations_overlap(capacity, reserved):
            problems.append("capacity population overlaps a reserved population")
    if populations_overlap(screen, capacity):
        problems.append("capacity and screen populations overlap")
    return sorted(set(problems))


def concurrent_capacity_problems(result: object, *, expected_workers: int,
                                 runtime_profile_sha256: str) -> list[str]:
    """Validate only score-free capacity facts used to size a later packet."""
    if not isinstance(result, dict):
        return ["capacity result is not an object"]
    lanes = result.get("lanes")
    problems = []
    expected_fields = {
        "schema", "run_id", "seed0", "workers", "clusters_per_worker",
        "runtime_profile_sha256", "score_free", "outcomes_published",
        "exact_work_complete", "concurrent_saturation_verified", "lanes",
    }
    if set(result) != expected_fields:
        problems.append("capacity field population drift")
    if (result.get("schema") != CAPACITY_SCHEMA
            or result.get("run_id") != CAPACITY_RUN_ID
            or result.get("seed0") != CAPACITY_SEED0
            or result.get("workers") != expected_workers
            or expected_workers < MIN_WORKERS
            or result.get("clusters_per_worker")
            != CAPACITY_CLUSTERS_PER_WORKER
            or result.get("outcomes_published") is not False
            or result.get("score_free") is not True
            or result.get("exact_work_complete") is not True
            or result.get("concurrent_saturation_verified") is not True
            or result.get("runtime_profile_sha256")
            != runtime_profile_sha256):
        problems.append("capacity identity/work/runtime drift")
    if not isinstance(lanes, list) or len(lanes) != expected_workers:
        problems.append("capacity lane population drift")
        return sorted(set(problems))
    expected_indices = list(range(expected_workers))
    if [lane.get("index") for lane in lanes if isinstance(lane, dict)] \
            != expected_indices:
        problems.append("capacity lane index drift")
    for lane in lanes:
        if (not isinstance(lane, dict)
                or set(lane) != {"index", "clusters", "elapsed_seconds"}
                or lane.get("clusters") != CAPACITY_CLUSTERS_PER_WORKER
                or isinstance(lane.get("elapsed_seconds"), bool)
                or not isinstance(lane.get("elapsed_seconds"), (int, float))
                or not math.isfinite(lane["elapsed_seconds"])
                or lane["elapsed_seconds"] <= 0):
            problems.append("capacity lane payload drift")
    forbidden = {"utility", "level_utility", "won", "winner", "points",
                 "outcomes", "records", "history", "actions"}
    if forbidden.intersection(result):
        problems.append("capacity result contains outcome-bearing fields")
    return sorted(set(problems))


def capacity_projection(result: dict, *, expected_workers: int,
                        runtime_profile_sha256: str) -> dict[str, float]:
    problems = concurrent_capacity_problems(
        result, expected_workers=expected_workers,
        runtime_profile_sha256=runtime_profile_sha256)
    if problems:
        raise DesignRefused("; ".join(problems))
    slowest = max(
        lane["elapsed_seconds"] / lane["clusters"]
        for lane in result["lanes"])
    planned = slowest * CONCURRENT_CAPACITY_SAFETY_FACTOR
    return {
        "measured_slowest_lane_seconds_per_cluster": slowest,
        "planning_seconds_per_cluster": planned,
        "projected_wall_hours": (
            SCREEN_CLUSTERS / expected_workers * planned / 3_600.0),
        "microshard_timeout_seconds": (
            MICROSHARD_CLUSTERS * planned + 300.0),
    }


def manifest_problems(value: object, *, packet_sha256: str,
                      runtime_profile_sha256s: set[str]) -> list[str]:
    """Validate a score-free checkpoint inventory without opening outcomes."""
    if not isinstance(value, dict):
        return ["microshard manifest is not an object"]
    rows = value.get("completed")
    problems = []
    if set(value) != {
            "schema", "run_id", "packet_sha256", "outcomes_opened",
            "statistics_published", "aggregate_execution_authorized",
            "completed"}:
        problems.append("microshard manifest field population drift")
    if (value.get("schema") != MANIFEST_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("packet_sha256") != packet_sha256
            or value.get("outcomes_opened") is not False
            or value.get("statistics_published") is not False
            or value.get("aggregate_execution_authorized") is not False):
        problems.append("microshard manifest identity/authority drift")
    if not isinstance(rows, list):
        problems.append("microshard manifest rows are missing")
        return sorted(set(problems))
    expected_fields = {
        "microshard_index", "clusters", "sha256", "elapsed_seconds",
        "worker_runtime_profile_sha256",
    }
    indices = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != expected_fields
                or isinstance(row.get("microshard_index"), bool)
                or not isinstance(row.get("microshard_index"), int)
                or not 0 <= row["microshard_index"] < MICROSHARDS
                or row.get("clusters") != MICROSHARD_CLUSTERS
                or not isinstance(row.get("sha256"), str)
                or len(row["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in row["sha256"])
                or isinstance(row.get("elapsed_seconds"), bool)
                or not isinstance(row.get("elapsed_seconds"), (int, float))
                or not math.isfinite(row["elapsed_seconds"])
                or row["elapsed_seconds"] <= 0
                or row.get("worker_runtime_profile_sha256")
                not in runtime_profile_sha256s):
            problems.append("microshard manifest row drift")
            continue
        indices.append(row["microshard_index"])
    if len(indices) != len(set(indices)) or indices != sorted(indices):
        problems.append("microshard manifest duplicate/order drift")
    return sorted(set(problems))


def missing_microshards(value: dict, *, packet_sha256: str,
                        runtime_profile_sha256s: set[str],
                        manifest_review: dict,
                        manifest_sha256: str,
                        surviving_prior_workers: int) -> list[int]:
    """Construct a resume set; this function cannot launch or read a shard."""
    problems = manifest_problems(
        value, packet_sha256=packet_sha256,
        runtime_profile_sha256s=runtime_profile_sha256s)
    if problems:
        raise DesignRefused("; ".join(problems))
    if surviving_prior_workers != 0:
        raise DesignRefused("prior microshard workers still survive")
    if (not isinstance(manifest_review, dict)
            or set(manifest_review) != {
                "schema", "run_id", "packet_sha256", "manifest_sha256",
                "manifest_verified", "independent_review", "outcomes_opened",
                "resume_missing_only_authorized", "verdict"}
            or manifest_review.get("schema") != MANIFEST_REVIEW_SCHEMA
            or manifest_review.get("run_id") != RUN_ID
            or manifest_review.get("packet_sha256") != packet_sha256
            or manifest_review.get("manifest_sha256") != manifest_sha256
            or manifest_review.get("manifest_verified") is not True
            or manifest_review.get("independent_review") is not True
            or manifest_review.get("outcomes_opened") is not False
            or manifest_review.get("resume_missing_only_authorized") is not True
            or manifest_review.get("verdict") != "PASS"):
        raise DesignRefused("independent manifest review is absent or drifted")
    complete = {row["microshard_index"] for row in value["completed"]}
    return [index for index in range(MICROSHARDS) if index not in complete]


DESIGN = design_record()
if design_problems(DESIGN):
    raise RuntimeError("invalid static Pair checkpoint successor design")
