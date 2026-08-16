"""Exact score-free capacity preflight for the BELIEF-V1 V2 capture.

The preflight uses a dedicated seed namespace, runs two rounds at every trump
rank in every one of sixteen lanes, discards all captured rows after measuring
their canonical bundle size, and publishes only resource/coverage receipts.
It cannot capture a production V2 seed or authorize the later population.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import math
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ai.registry import make_bot
from ..engine import fast
from .belief_artifacts import capture_bundle_bytes
from .belief_capture import (
    CHAMPION_POLICY,
    CapturedBeliefRoundV1,
    _capture_with_policies,
    captured_round_artifacts,
)
from .belief_contract import canonical_json_bytes
from .belief_v2_protocol import (
    MAX_SEED,
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    V2_CAPTURE_LANES,
    V2_RANKS,
    v2_round_coordinates,
)


PREFLIGHT_SCHEMA = "belief-v1-v2-capture-capacity-preflight-v1"
PREFLIGHT_RESULT_SCHEMA = "belief-v1-v2-capture-capacity-result-v2"
PREFLIGHT_SEED_NAMESPACE = "belief-v1-v2-capacity-out-of-population-v1"
PREFLIGHT_REPLICATES_PER_LANE_RANK = 2
PREFLIGHT_ROUND_COUNT = (
    V2_CAPTURE_LANES * len(V2_RANKS) * PREFLIGHT_REPLICATES_PER_LANE_RANK)


class BeliefV2PreflightError(ValueError):
    """A preflight identity, resource receipt, or execution boundary drifted."""


@dataclass(frozen=True)
class V2PreflightCoordinate:
    lane: int
    trump_rank: str
    rank_index: int
    replicate: int
    round_seed: int
    policy_seeds: tuple[int, int, int, int]


def _derive_seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefV2PreflightError("preflight seed label is invalid")
    return int.from_bytes(hashlib.sha256(
        f"{PREFLIGHT_SCHEMA}|{PREFLIGHT_SEED_NAMESPACE}|{label}".encode(
            "ascii")).digest()[:8], "big") & MAX_SEED


def preflight_coordinates() -> tuple[V2PreflightCoordinate, ...]:
    production_seeds = {row.round_seed for row in v2_round_coordinates()}
    seen: set[int] = set()
    rows: list[V2PreflightCoordinate] = []
    for lane in range(V2_CAPTURE_LANES):
        for rank_index, trump_rank in enumerate(V2_RANKS):
            for replicate in range(PREFLIGHT_REPLICATES_PER_LANE_RANK):
                seed = _derive_seed(
                    f"round|lane-{lane}|rank-{trump_rank}|replicate-{replicate}")
                policy_seeds = tuple(_derive_seed(
                    f"policy|round-{seed}|seat-{seat}") for seat in range(4))
                if seed in seen or seed in production_seeds \
                        or V1_B2_SEED_START <= seed <= V1_B2_SEED_END \
                        or len(set(policy_seeds)) != 4 \
                        or seed in policy_seeds:
                    raise BeliefV2PreflightError(
                        "preflight seed population collision")
                seen.add(seed)
                rows.append(V2PreflightCoordinate(
                    lane=lane, trump_rank=trump_rank,
                    rank_index=rank_index, replicate=replicate,
                    round_seed=seed,
                    policy_seeds=policy_seeds))  # type: ignore[arg-type]
    result = tuple(rows)
    if len(result) != PREFLIGHT_ROUND_COUNT:
        raise BeliefV2PreflightError("preflight population drift")
    return result


def preflight_schedule_bytes() -> bytes:
    return canonical_json_bytes({
        "schema": PREFLIGHT_SCHEMA,
        "coordinates": [{
            "lane": row.lane,
            "policy_seeds": list(row.policy_seeds),
            "rank_index": row.rank_index,
            "replicate": row.replicate,
            "round_seed": row.round_seed,
            "trump_rank": row.trump_rank,
        } for row in preflight_coordinates()],
    })


def preflight_schedule_sha256() -> str:
    return hashlib.sha256(preflight_schedule_bytes()).hexdigest()


def _rss_unit() -> str:
    return "bytes" if sys.platform == "darwin" else "kibibytes"


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        try:
            return int(subprocess.run(
                ("sysctl", "-n", "hw.memsize"), check=True,
                capture_output=True, text=True).stdout.strip())
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            raise BeliefV2PreflightError(
                "preflight memory identity probe failed") from exc
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) \
            * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError) as exc:
        raise BeliefV2PreflightError(
            "preflight memory identity probe failed") from exc


def _boot_identity() -> str:
    linux = Path("/proc/sys/kernel/random/boot_id")
    if linux.is_file():
        value = linux.read_text(encoding="ascii").strip()
    else:
        try:
            value = subprocess.run(
                ("sysctl", "-n", "kern.boottime"), check=True,
                capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BeliefV2PreflightError(
                "preflight boot identity probe failed") from exc
    if not value:
        raise BeliefV2PreflightError(
            "preflight boot identity probe failed")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _validate_live_run_environment() -> None:
    if not sys.flags.safe_path or not sys.dont_write_bytecode \
            or os.environ.get("PYTHONPATH"):
        raise BeliefV2PreflightError(
            "preflight requires isolated -P -B Python and no PYTHONPATH")
    if os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1" \
            or not fast.activate():
        raise BeliefV2PreflightError(
            "preflight requires compiled engine and strict voids")


def _capture_lane(lane: int) -> dict[str, Any]:
    if type(lane) is not int or not 0 <= lane < V2_CAPTURE_LANES:
        raise BeliefV2PreflightError("preflight lane is invalid")
    _validate_live_run_environment()
    runtime_before = _runtime_identity()
    rows = [row for row in preflight_coordinates() if row.lane == lane]
    lane_started = time.monotonic_ns()
    lane_cpu_started = time.process_time_ns()
    receipts = []
    for coordinate in rows:
        policies = [make_bot(CHAMPION_POLICY, seed=seed)
                    for seed in coordinate.policy_seeds]
        started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        captured = _capture_with_policies(
            coordinate.round_seed, CHAMPION_POLICY,
            coordinate.policy_seeds, policies,
            trump_rank=coordinate.trump_rank)
        if type(captured) is not CapturedBeliefRoundV1:
            raise BeliefV2PreflightError("preflight capture type drift")
        bundle = capture_bundle_bytes(captured_round_artifacts(captured))
        finished = time.perf_counter_ns()
        cpu_finished = time.process_time_ns()
        receipts.append({
            "artifact_bytes": len(bundle),
            "cpu_nanoseconds": cpu_finished - cpu_started,
            "decision_count": len(captured.pairs),
            "engine_adjusted_play_count": captured.manifest_dict()[
                "engine_adjusted_play_count"],
            "lane": coordinate.lane,
            "rank_index": coordinate.rank_index,
            "replicate": coordinate.replicate,
            "round_seed": coordinate.round_seed,
            "trump_rank": coordinate.trump_rank,
            "wall_nanoseconds": finished - started,
        })
    lane_finished = time.monotonic_ns()
    lane_cpu_finished = time.process_time_ns()
    runtime_after = _runtime_identity()
    if runtime_after != runtime_before:
        raise BeliefV2PreflightError(
            "preflight lane runtime changed during capture")
    return {
        "lane": lane,
        "started_monotonic_nanoseconds": lane_started,
        "finished_monotonic_nanoseconds": lane_finished,
        "cpu_nanoseconds": lane_cpu_finished - lane_cpu_started,
        "max_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "max_rss_unit": _rss_unit(),
        "runtime_identity_sha256": hashlib.sha256(
            canonical_json_bytes(runtime_before)).hexdigest(),
        "rounds": receipts,
    }


def _percentile95(values: list[int]) -> int:
    if not values or any(type(value) is not int or value <= 0
                         for value in values):
        raise BeliefV2PreflightError("preflight percentile population invalid")
    ordered = sorted(values)
    return ordered[math.ceil(95 * len(ordered) / 100) - 1]


def _derive_summary(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    rounds = [row for lane in lanes for row in lane["rounds"]]
    wall = [row["wall_nanoseconds"] for row in rounds]
    cpu = [row["cpu_nanoseconds"] for row in rounds]
    artifact = [row["artifact_bytes"] for row in rounds]
    decisions = [row["decision_count"] for row in rounds]
    return {
        "aggregate_parallel_wall_nanoseconds": max(
            lane["finished_monotonic_nanoseconds"] for lane in lanes) - min(
                lane["started_monotonic_nanoseconds"] for lane in lanes),
        "aggregate_cpu_nanoseconds": sum(
            lane["cpu_nanoseconds"] for lane in lanes),
        "aggregate_artifact_bytes": sum(artifact),
        "concurrent_lane_overlap_nanoseconds": min(
            lane["finished_monotonic_nanoseconds"] for lane in lanes) - max(
                lane["started_monotonic_nanoseconds"] for lane in lanes),
        "maximum_lane_rss_raw": max(lane["max_rss_raw"] for lane in lanes),
        "max_rss_unit": lanes[0]["max_rss_unit"],
        "mean_round_wall_nanoseconds": sum(wall) // len(wall),
        "p95_round_wall_nanoseconds": _percentile95(wall),
        "mean_round_cpu_nanoseconds": sum(cpu) // len(cpu),
        "p95_round_cpu_nanoseconds": _percentile95(cpu),
        "mean_round_artifact_bytes": sum(artifact) // len(artifact),
        "p95_round_artifact_bytes": _percentile95(artifact),
        "mean_decisions_per_round": sum(decisions) // len(decisions),
        "minimum_decisions_per_round": min(decisions),
        "maximum_decisions_per_round": max(decisions),
        "engine_adjusted_round_count": sum(
            row["engine_adjusted_play_count"] > 0 for row in rounds),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_identity() -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[3]
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo, text=True, stderr=subprocess.DEVNULL)
        tracked = subprocess.check_output(
            ["git", "ls-files", "server/shengji",
             "server/scripts/belief_v2_preflight.py", "server/setup.py",
             "server/pyproject.toml", "server/uv.lock"],
            cwd=repo, text=True, stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2PreflightError(
            "preflight Git/source identity cannot be resolved") from exc
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head) \
            or status or not tracked:
        raise BeliefV2PreflightError(
            "preflight requires an exact clean source checkout")
    source_rows = []
    for name in tracked:
        path = repo / name
        if not path.is_file():
            raise BeliefV2PreflightError(
                "preflight tracked source population is incomplete")
        source_rows.append({"path": name, "sha256": _file_sha256(path)})
    source_population_sha = hashlib.sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-preflight-source-population-v1",
        "files": source_rows,
    })).hexdigest()
    python_path = Path(sys.executable).resolve()
    native_value = getattr(fast, "_fast", None)
    native_file = getattr(native_value, "__file__", None)
    if not python_path.is_file() or not isinstance(native_file, str):
        raise BeliefV2PreflightError(
            "preflight Python/native identity is incomplete")
    native_path = Path(native_file).resolve()
    if not native_path.is_file():
        raise BeliefV2PreflightError(
            "preflight native extension is missing")
    return {
        "git_head": head,
        "source_tree_dirty": False,
        "source_file_count": len(source_rows),
        "source_population_sha256": source_population_sha,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_sha256": _file_sha256(python_path),
        "native_extension_sha256": _file_sha256(native_path),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "boot_identity": _boot_identity(),
        "compiled_engine": True,
        "strict_voids": True,
    }


def run_capture_preflight() -> dict[str, Any]:
    """Run the exact 16-lane preflight; never retain captured row bytes."""
    _validate_live_run_environment()
    runtime_before = _runtime_identity()
    with concurrent.futures.ProcessPoolExecutor(
            max_workers=V2_CAPTURE_LANES) as executor:
        lanes = list(executor.map(_capture_lane, range(V2_CAPTURE_LANES)))
    lanes.sort(key=lambda row: row["lane"])
    runtime_after = _runtime_identity()
    if runtime_after != runtime_before:
        raise BeliefV2PreflightError(
            "preflight parent runtime changed during capture")
    result = {
        "schema": PREFLIGHT_RESULT_SCHEMA,
        "schedule_sha256": preflight_schedule_sha256(),
        "runtime": runtime_before,
        "lanes": lanes,
        "summary": _derive_summary(lanes),
        "preflight_only": True,
        "captured_rows_retained": False,
        "production_seed_opened": False,
        "population_capture_authorized": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }
    verify_preflight_result(result)
    return result


def verify_preflight_result(result: dict[str, Any]) -> None:
    if type(result) is not dict or set(result) != {
            "schema", "schedule_sha256", "runtime", "lanes", "summary",
            "preflight_only", "captured_rows_retained",
            "production_seed_opened", "population_capture_authorized",
            "training_authorized", "test_open_authorized",
            "strength_claim_authorized"}:
        raise BeliefV2PreflightError("preflight result field population drift")
    if result["schema"] != PREFLIGHT_RESULT_SCHEMA \
            or result["schedule_sha256"] != preflight_schedule_sha256() \
            or any(result[key] is not False for key in (
                "captured_rows_retained", "production_seed_opened",
                "population_capture_authorized", "training_authorized",
                "test_open_authorized", "strength_claim_authorized")) \
            or result["preflight_only"] is not True:
        raise BeliefV2PreflightError("preflight identity/authority drift")
    runtime = result["runtime"]
    if type(runtime) is not dict or set(runtime) != {
            "git_head", "source_tree_dirty", "source_file_count",
            "source_population_sha256", "python_implementation",
            "python_version", "python_executable_sha256",
            "native_extension_sha256", "hostname", "platform", "machine",
            "logical_cpu_count", "memory_bytes", "boot_identity",
            "compiled_engine", "strict_voids"} \
            or type(runtime["git_head"]) is not str \
            or len(runtime["git_head"]) != 40 \
            or any(char not in "0123456789abcdef"
                   for char in runtime["git_head"]) \
            or runtime["source_tree_dirty"] is not False \
            or type(runtime["source_file_count"]) is not int \
            or runtime["source_file_count"] <= 0 \
            or any(type(runtime[key]) is not str or len(runtime[key]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in runtime[key])
                   for key in ("source_population_sha256",
                               "python_executable_sha256",
                               "native_extension_sha256")) \
            or any(type(runtime[key]) is not str or not runtime[key]
                   for key in ("python_implementation", "python_version",
                               "hostname", "platform", "machine")) \
            or type(runtime["logical_cpu_count"]) is not int \
            or runtime["logical_cpu_count"] < V2_CAPTURE_LANES \
            or type(runtime["memory_bytes"]) is not int \
            or runtime["memory_bytes"] <= 0 \
            or type(runtime["boot_identity"]) is not str \
            or len(runtime["boot_identity"]) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in runtime["boot_identity"]) \
            or runtime["compiled_engine"] is not True \
            or runtime["strict_voids"] is not True:
        raise BeliefV2PreflightError("preflight runtime drift")
    lanes = result["lanes"]
    if type(lanes) is not list or len(lanes) != V2_CAPTURE_LANES \
            or [lane.get("lane") for lane in lanes] \
            != list(range(V2_CAPTURE_LANES)):
        raise BeliefV2PreflightError("preflight lane population drift")
    runtime_sha256 = hashlib.sha256(canonical_json_bytes(runtime)).hexdigest()
    expected = {(row.lane, row.trump_rank, row.replicate): row
                for row in preflight_coordinates()}
    observed = {}
    rss_units = set()
    for lane in lanes:
        if type(lane) is not dict or set(lane) != {
                "lane", "started_monotonic_nanoseconds",
                "finished_monotonic_nanoseconds", "cpu_nanoseconds",
                "max_rss_raw", "max_rss_unit", "runtime_identity_sha256",
                "rounds"}:
            raise BeliefV2PreflightError("preflight lane field drift")
        rss_units.add(lane["max_rss_unit"])
        if any(type(lane[key]) is not int or lane[key] <= 0 for key in (
                "started_monotonic_nanoseconds",
                "finished_monotonic_nanoseconds", "cpu_nanoseconds",
                "max_rss_raw")) \
                or lane["finished_monotonic_nanoseconds"] \
                <= lane["started_monotonic_nanoseconds"] \
                or lane["runtime_identity_sha256"] != runtime_sha256:
            raise BeliefV2PreflightError("preflight lane resource drift")
        for row in lane["rounds"]:
            if type(row) is not dict or set(row) != {
                    "artifact_bytes", "cpu_nanoseconds", "decision_count",
                    "engine_adjusted_play_count", "lane", "rank_index",
                    "replicate", "round_seed", "trump_rank",
                    "wall_nanoseconds"}:
                raise BeliefV2PreflightError("preflight round field drift")
            key = (row["lane"], row["trump_rank"], row["replicate"])
            coordinate = expected.get(key)
            if coordinate is None or key in observed \
                    or row["rank_index"] != coordinate.rank_index \
                    or row["round_seed"] != coordinate.round_seed \
                    or any(type(row[name]) is not int or row[name] <= 0
                           for name in ("artifact_bytes", "cpu_nanoseconds",
                                       "decision_count", "wall_nanoseconds")) \
                    or type(row["engine_adjusted_play_count"]) is not int \
                    or row["engine_adjusted_play_count"] < 0:
                raise BeliefV2PreflightError("preflight round identity drift")
            observed[key] = row
    if set(observed) != set(expected) or len(rss_units) != 1:
        raise BeliefV2PreflightError("preflight round population drift")
    if any(lane["cpu_nanoseconds"] < sum(
            row["cpu_nanoseconds"] for row in lane["rounds"])
           for lane in lanes):
        raise BeliefV2PreflightError("preflight lane CPU accounting drift")
    if result["summary"] != _derive_summary(lanes) \
            or result["summary"]["concurrent_lane_overlap_nanoseconds"] <= 0:
        raise BeliefV2PreflightError("preflight summary reconstruction drift")


def preflight_result_bytes(result: dict[str, Any]) -> bytes:
    verify_preflight_result(result)
    return canonical_json_bytes(result)
