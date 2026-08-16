"""Schedule, resource-wiring, and authority witnesses for V2 preflight."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from shengji.rl.belief_v2_preflight import (
    PREFLIGHT_REPLICATES_PER_LANE_RANK,
    PREFLIGHT_ROUND_COUNT,
    BeliefV2PreflightError,
    _derive_summary,
    preflight_coordinates,
    preflight_result_bytes,
    preflight_schedule_sha256,
    verify_preflight_result,
)
from shengji.rl.belief_v2_protocol import (
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    V2_CAPTURE_LANES,
    V2_RANKS,
    v2_round_coordinates,
)


EXPECTED_PREFLIGHT_SCHEDULE_SHA256 = (
    "ffbd1a5cf76886d11fc27c511e8899348342943f29866c2c349c650cf606e698")


def _result():
    runtime = {
        "git_head": "a" * 40,
        "source_tree_dirty": False,
        "source_file_count": 100,
        "source_population_sha256": "b" * 64,
        "python_implementation": "CPython",
        "python_version": "3.14.3",
        "python_executable_sha256": "c" * 64,
        "native_extension_sha256": "d" * 64,
        "hostname": "host",
        "platform": "test",
        "machine": "x86_64",
        "logical_cpu_count": 16,
        "memory_bytes": 32 * 1024**3,
        "boot_identity": "e" * 64,
        "compiled_engine": True,
        "strict_voids": True,
    }
    import hashlib
    from shengji.rl.belief_contract import canonical_json_bytes
    runtime_sha = hashlib.sha256(canonical_json_bytes(runtime)).hexdigest()
    lane_rows = []
    for lane in range(V2_CAPTURE_LANES):
        rounds = []
        for coordinate in preflight_coordinates():
            if coordinate.lane != lane:
                continue
            rounds.append({
                "artifact_bytes": 500_000 + coordinate.rank_index,
                "cpu_nanoseconds": 7_000_000_000 + coordinate.rank_index,
                "decision_count": 60 + coordinate.replicate,
                "engine_adjusted_play_count": coordinate.replicate,
                "lane": lane,
                "rank_index": coordinate.rank_index,
                "replicate": coordinate.replicate,
                "round_seed": coordinate.round_seed,
                "trump_rank": coordinate.trump_rank,
                "wall_nanoseconds": 7_100_000_000 + coordinate.rank_index,
            })
        lane_rows.append({
            "lane": lane,
            "started_monotonic_nanoseconds": 1_000_000_000 + lane,
            "finished_monotonic_nanoseconds": 20_000_000_000 + lane,
            "cpu_nanoseconds": sum(row["cpu_nanoseconds"] for row in rounds),
            "max_rss_raw": 100_000 + lane,
            "max_rss_unit": "bytes",
            "runtime_identity_sha256": runtime_sha,
            "rounds": rounds,
        })
    return {
        "schema": "belief-v1-v2-capture-capacity-result-v2",
        "schedule_sha256": preflight_schedule_sha256(),
        "runtime": runtime,
        "lanes": lane_rows,
        "summary": _derive_summary(lane_rows),
        "preflight_only": True,
        "captured_rows_retained": False,
        "production_seed_opened": False,
        "population_capture_authorized": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }


def test_preflight_population_is_exact_balanced_and_disjoint():
    rows = preflight_coordinates()
    production = {row.round_seed for row in v2_round_coordinates()}
    assert len(rows) == PREFLIGHT_ROUND_COUNT == 416
    assert len({row.round_seed for row in rows}) == len(rows)
    assert all(row.round_seed not in production for row in rows)
    assert all(not V1_B2_SEED_START <= row.round_seed <= V1_B2_SEED_END
               for row in rows)
    assert Counter((row.lane, row.trump_rank) for row in rows) == Counter({
        (lane, rank): PREFLIGHT_REPLICATES_PER_LANE_RANK
        for lane in range(V2_CAPTURE_LANES) for rank in V2_RANKS})
    assert preflight_schedule_sha256() == EXPECTED_PREFLIGHT_SCHEDULE_SHA256


def test_preflight_result_reopens_and_authorizes_nothing():
    result = _result()
    verify_preflight_result(result)
    assert preflight_result_bytes(result).endswith(b"\n")
    assert result["summary"]["aggregate_parallel_wall_nanoseconds"] \
        == 19_000_000_015
    assert result["summary"]["concurrent_lane_overlap_nanoseconds"] \
        == 18_999_999_985
    assert result["summary"]["aggregate_cpu_nanoseconds"] == sum(
        lane["cpu_nanoseconds"] for lane in result["lanes"])
    for key in (
            "captured_rows_retained", "production_seed_opened",
            "population_capture_authorized", "training_authorized",
            "test_open_authorized", "strength_claim_authorized"):
        assert result[key] is False


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda result: result["lanes"][0]["rounds"][0].__setitem__(
        "round_seed", result["lanes"][0]["rounds"][1]["round_seed"]),
     "round identity"),
    (lambda result: result["lanes"][0].__setitem__(
        "finished_monotonic_nanoseconds",
        result["lanes"][0]["started_monotonic_nanoseconds"]),
     "lane resource"),
    (lambda result: result["summary"].__setitem__(
        "aggregate_cpu_nanoseconds", 1), "summary reconstruction"),
    (lambda result: result["lanes"][0].__setitem__(
        "cpu_nanoseconds", 1), "lane CPU accounting"),
    (lambda result: result.__setitem__("training_authorized", True),
     "identity/authority"),
])
def test_preflight_wiring_refuses_exact_mutations(mutation, message):
    result = copy.deepcopy(_result())
    mutation(result)
    with pytest.raises(BeliefV2PreflightError, match=message):
        verify_preflight_result(result)


def test_preflight_requires_a_real_common_sixteen_lane_overlap():
    result = _result()
    lane = result["lanes"][0]
    lane["finished_monotonic_nanoseconds"] = (
        lane["started_monotonic_nanoseconds"] + 1)
    result["summary"] = _derive_summary(result["lanes"])
    assert result["summary"]["concurrent_lane_overlap_nanoseconds"] < 0
    with pytest.raises(BeliefV2PreflightError,
                       match="summary reconstruction"):
        verify_preflight_result(result)


def test_cli_independently_reopens_exact_canonical_result(tmp_path):
    result_path = tmp_path / "preflight.json"
    result_path.write_bytes(preflight_result_bytes(_result()))
    server = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(server / "scripts" / "belief_v2_preflight.py"),
         "verify", str(result_path)],
        cwd=server, env=environment, text=True, capture_output=True,
        check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "verified=true\n"

    result_path.write_bytes(result_path.read_bytes() + b"\n")
    rejected = subprocess.run(
        [sys.executable, str(server / "scripts" / "belief_v2_preflight.py"),
         "verify", str(result_path)],
        cwd=server, env=environment, text=True, capture_output=True,
        check=False)
    assert rejected.returncode != 0
    assert "not canonical bytes" in rejected.stderr
