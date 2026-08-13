"""Fail-closed contracts for the non-executable Pair successor design."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_checkpoint_successor_design as DESIGN  # noqa: E402


PROFILE = "a" * 64
PACKET = "b" * 64
MANIFEST_SHA = "c" * 64


def _capacity(workers=16, seconds=800.0):
    return {
        "schema": DESIGN.CAPACITY_SCHEMA,
        "run_id": DESIGN.CAPACITY_RUN_ID,
        "seed0": DESIGN.CAPACITY_SEED0,
        "workers": workers,
        "clusters_per_worker": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
        "runtime_profile_sha256": PROFILE,
        "score_free": True,
        "outcomes_published": False,
        "exact_work_complete": True,
        "concurrent_saturation_verified": True,
        "lanes": [
            {"index": index,
             "clusters": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
             "elapsed_seconds": seconds + index}
            for index in range(workers)
        ],
    }


def _manifest(indices=(0, 2)):
    return {
        "schema": DESIGN.MANIFEST_SCHEMA,
        "run_id": DESIGN.RUN_ID,
        "packet_sha256": PACKET,
        "outcomes_opened": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "population": {
            "seed0": DESIGN.SCREEN_SEED0,
            "clusters": DESIGN.SCREEN_CLUSTERS,
            "stream_stride": DESIGN.STREAM_STRIDE,
            "max_role_offset": DESIGN.MAX_ROLE_OFFSET,
            "microshard_clusters": DESIGN.MICROSHARD_CLUSTERS,
            "microshards": DESIGN.MICROSHARDS,
        },
        "campaign_runtime_profile_sha256": PROFILE,
        "completed": [
            {
                "microshard_index": index,
                "cluster_index_start": index * DESIGN.MICROSHARD_CLUSTERS,
                "seed0": DESIGN.SCREEN_SEED0 + DESIGN.STREAM_STRIDE
                * (index * DESIGN.MICROSHARD_CLUSTERS),
                "clusters": DESIGN.MICROSHARD_CLUSTERS,
                "sha256": f"{index + 1:064x}",
                "elapsed_seconds": 10.0 + index,
                "worker_runtime_profile_sha256": PROFILE,
            }
            for index in indices
        ],
    }


def _review():
    return {
        "schema": DESIGN.MANIFEST_REVIEW_SCHEMA,
        "run_id": DESIGN.RUN_ID,
        "packet_sha256": PACKET,
        "manifest_sha256": MANIFEST_SHA,
        "manifest_verified": True,
        "independent_review": True,
        "outcomes_opened": False,
        "resume_missing_only_authorized": True,
        "verdict": "PASS",
    }


def test_design_is_fresh_checkpointed_and_non_authorizing():
    assert DESIGN.design_problems(DESIGN.DESIGN) == []
    assert DESIGN.SCREEN_CLUSTERS == 7_168
    assert DESIGN.MICROSHARDS == 224
    assert DESIGN.DESIGN["parent"][
        "current_namespace_retry_or_extension_authorized"] is False
    assert DESIGN.DESIGN["parent"]["current_outcomes_or_shards_reusable"] \
        is False
    assert "atomically renames" in DESIGN.DESIGN["screen"][
        "atomic_complete_bundle_directory"]
    assert not any(DESIGN.DESIGN["authority"].values())


def test_fresh_capacity_and_screen_ranges_avoid_all_reserved_ranges():
    screen = DESIGN.Population(DESIGN.SCREEN_SEED0, DESIGN.SCREEN_CLUSTERS)
    capacity = DESIGN.Population(
        DESIGN.CAPACITY_SEED0,
        DESIGN.MIN_WORKERS * DESIGN.CAPACITY_CLUSTERS_PER_WORKER)
    assert not DESIGN.populations_overlap(screen, capacity)
    for value in DESIGN.RESERVED_POPULATIONS:
        reserved = DESIGN._reserved_population(value)
        assert not DESIGN.populations_overlap(screen, reserved)
        assert not DESIGN.populations_overlap(capacity, reserved)


def test_live_pace_reproduces_acceleration_problem_without_outcomes():
    pace = DESIGN.pace_projection(
        elapsed_hours=21 + 56 / 60, clusters_complete=240)
    assert pace["projected_total_hours_at_current_rate"] == \
        pytest.approx(81.87, abs=0.02)
    assert pace["required_throughput_acceleration_fraction"] == \
        pytest.approx(0.424, abs=0.002)


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(workers=1),
    lambda row: row.update(outcomes_published=True),
    lambda row: row.update(score_free=False),
    lambda row: row.update(concurrent_saturation_verified=False),
    lambda row: row.update(runtime_profile_sha256="c" * 64),
    lambda row: row.update(utility=0),
    lambda row: row.update(screen_execution_authorized=True),
    lambda row: row["lanes"].pop(),
    lambda row: row["lanes"][0].update(clusters=1),
])
def test_capacity_refuses_idle_runtime_outcome_and_lane_drift(mutation):
    result = _capacity()
    mutation(result)
    assert DESIGN.concurrent_capacity_problems(
        result, expected_workers=16, runtime_profile_sha256=PROFILE)


def test_capacity_uses_slowest_concurrent_lane_not_mean():
    result = _capacity(seconds=800.0)
    projected = DESIGN.capacity_projection(
        result, expected_workers=16, runtime_profile_sha256=PROFILE)
    assert projected["measured_slowest_lane_seconds_per_cluster"] == \
        pytest.approx(815.0 / 8)
    assert projected["planning_seconds_per_cluster"] == \
        pytest.approx(815.0 / 8 * 1.5)


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(outcomes_opened=True),
    lambda row: row.update(statistics_published=True),
    lambda row: row.update(aggregate_execution_authorized=True),
    lambda row: row["population"].update(seed0=DESIGN.PARENT_SEED0),
    lambda row: row.update(campaign_runtime_profile_sha256="d" * 64),
    lambda row: row["completed"].append(copy.deepcopy(row["completed"][0])),
    lambda row: row["completed"][0].update(sha256="bad"),
    lambda row: row["completed"][0].update(clusters=31),
    lambda row: row["completed"][0].update(cluster_index_start=32),
    lambda row: row["completed"][0].update(seed0=DESIGN.SCREEN_SEED0 + 1),
    lambda row: row["completed"][0].update(
        worker_runtime_profile_sha256="c" * 64),
])
def test_manifest_refuses_authority_duplicate_hash_and_runtime_drift(mutation):
    manifest = _manifest()
    mutation(manifest)
    assert DESIGN.manifest_problems(
        manifest, packet_sha256=PACKET,
        runtime_profile_sha256=PROFILE)


def test_reviewed_resume_constructs_only_the_missing_fixed_indices():
    missing = DESIGN.missing_microshards(
        _manifest(), packet_sha256=PACKET,
        runtime_profile_sha256=PROFILE, manifest_review=_review(),
        manifest_sha256=MANIFEST_SHA,
        surviving_prior_workers=0)
    assert 0 not in missing and 2 not in missing
    assert len(missing) == DESIGN.MICROSHARDS - 2
    assert missing == sorted(missing)


def test_manifest_cannot_relabel_parent_population_or_parent_run():
    manifest = _manifest()
    manifest["run_id"] = DESIGN.PARENT_RUN_ID
    manifest["population"]["seed0"] = DESIGN.PARENT_SEED0
    assert DESIGN.manifest_problems(
        manifest, packet_sha256=PACKET,
        runtime_profile_sha256=PROFILE)


def test_resume_refuses_surviving_worker_or_missing_review():
    with pytest.raises(DESIGN.DesignRefused, match="workers still survive"):
        DESIGN.missing_microshards(
            _manifest(), packet_sha256=PACKET,
            runtime_profile_sha256=PROFILE, manifest_review=_review(),
            manifest_sha256=MANIFEST_SHA,
            surviving_prior_workers=1)
    review = _review()
    review["resume_missing_only_authorized"] = False
    with pytest.raises(DESIGN.DesignRefused, match="review"):
        DESIGN.missing_microshards(
            _manifest(), packet_sha256=PACKET,
            runtime_profile_sha256=PROFILE, manifest_review=review,
            manifest_sha256=MANIFEST_SHA,
            surviving_prior_workers=0)
    with pytest.raises(DESIGN.DesignRefused, match="malformed"):
        DESIGN.missing_microshards(
            _manifest(), packet_sha256=PACKET,
            runtime_profile_sha256=PROFILE, manifest_review=_review(),
            manifest_sha256="not-a-hash", surviving_prior_workers=0)
