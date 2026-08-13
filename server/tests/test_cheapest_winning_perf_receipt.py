"""Self-check the durable `_cheapest_winning` performance receipt."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path


RECEIPT = (Path(__file__).resolve().parent / "data" /
           "cheapest_winning_native_perf_exact_head.v2.json")
COMPOSITION = (Path(__file__).resolve().parent / "data" /
               "cheapest_winning_counter_composition_perf.v1.json")


def test_cheapest_winning_perf_receipt_reconciles_and_supersedes_v1():
    record = json.loads(RECEIPT.read_text())
    assert record["schema"] == "cheapest-winning-native-perf-exact-head-v2"
    assert record["claim_boundary"] == {
        "performance_only": True,
        "production_deployment": False,
        "strength_claim": False,
    }
    assert record["supersedes"]["schema"] == \
        "cheapest-winning-native-perf-exact-head-v1"
    assert record["supersedes"]["status"] == \
        "hold_unverifiable_raw_evidence"

    evidence = record["durable_evidence"]
    assert evidence["raw_artifacts_preserved"] is True
    assert evidence["separate_normalized_arm_artifacts_preserved"] is True
    for field in (
        "archive_sha256", "bundle_manifest_sha256", "result_sha256",
        "design_sha256", "environment_sha256", "harness_sha256",
        "runner_sha256", "on_host_validator_sha256",
    ):
        assert len(evidence[field]) == 64
    assert evidence["file_count_excluding_manifest"] == 61

    design = record["design"]
    rows = record["records"]
    assert len(rows) == design["pairs"] == 6
    assert [row["seed"] for row in rows] == design["seeds"]
    assert [row["order"] for row in rows] == design["orders"]
    assert design["one_fresh_batch_no_retry"] is True

    for row in rows:
        base, head = row["base"], row["head"]
        assert base["raw_semantic_sha256"] != head["raw_semantic_sha256"]
        assert base["normalized_semantic_sha256"] == \
            head["normalized_semantic_sha256"]
        assert base["rollouts"] == head["rollouts"]
        assert base["search_calls"] == head["search_calls"]

    base_times = [row["base"]["elapsed_seconds"] for row in rows]
    head_times = [row["head"]["elapsed_seconds"] for row in rows]
    reductions = [100.0 * (a - b) / a
                  for a, b in zip(base_times, head_times)]
    aggregate = record["aggregate"]
    assert math.isclose(sum(base_times), aggregate["base_wall_seconds"],
                        abs_tol=1e-12)
    assert math.isclose(sum(head_times), aggregate["head_wall_seconds"],
                        abs_tol=1e-12)
    assert math.isclose(
        100.0 * (sum(base_times) - sum(head_times)) / sum(base_times),
        aggregate["wall_reduction_percent"], abs_tol=1e-12)
    assert math.isclose(
        100.0 * (sum(base_times) / sum(head_times) - 1.0),
        aggregate["throughput_increase_percent"], abs_tol=1e-12)
    assert math.isclose(statistics.mean(reductions),
                        aggregate["paired_relative_mean_percent"],
                        abs_tol=1e-12)
    lower = (statistics.mean(reductions)
             - design["one_sided_t_critical"]
             * statistics.stdev(reductions) / math.sqrt(len(reductions)))
    assert math.isclose(lower, aggregate["paired_one_sided_95_lb_percent"],
                        abs_tol=1e-12)
    assert aggregate["normalized_semantics_exact"] is True
    assert aggregate["wall_reduction_percent"] >= \
        design["minimum_wall_reduction_percent"]
    assert aggregate["decision"] == "retain"


def test_one_counter_composition_receipt_reconciles():
    record = json.loads(COMPOSITION.read_text())
    assert record["schema"] == \
        "cheapest-winning-counter-composition-perf-v1"
    assert record["claim_boundary"]["performance_only"] is True
    assert record["durable_evidence"]["raw_artifacts_preserved"] is True
    assert record["durable_evidence"]["external_on_host_validation"] == \
        "VERIFIED_ON_HOST"
    rows, design = record["records"], record["design"]
    assert len(rows) == design["pairs"] == 3
    assert [row["seed"] for row in rows] == design["seeds"]
    assert [row["order"] for row in rows] == design["orders"]
    for row in rows:
        assert row["base"]["normalized_semantic_sha256"] == \
            row["head"]["normalized_semantic_sha256"]
        assert row["base"]["rollouts"] == row["head"]["rollouts"]
        assert row["base"]["search_calls"] == row["head"]["search_calls"]
    base = [row["base"]["elapsed_seconds"] for row in rows]
    head = [row["head"]["elapsed_seconds"] for row in rows]
    reductions = [100.0 * (a - b) / a for a, b in zip(base, head)]
    aggregate = record["aggregate"]
    assert math.isclose(sum(base), aggregate["base_wall_seconds"],
                        abs_tol=1e-12)
    assert math.isclose(sum(head), aggregate["head_wall_seconds"],
                        abs_tol=1e-12)
    assert math.isclose(
        100.0 * (sum(base) - sum(head)) / sum(base),
        aggregate["wall_reduction_percent"], abs_tol=1e-12)
    assert math.isclose(statistics.mean(reductions),
                        aggregate["paired_relative_mean_percent"],
                        abs_tol=1e-12)
    lower = (statistics.mean(reductions)
             - design["one_sided_t_critical"]
             * statistics.stdev(reductions) / math.sqrt(len(reductions)))
    assert math.isclose(lower, aggregate["paired_one_sided_95_lb_percent"],
                        abs_tol=1e-12)
    assert aggregate["normalized_semantics_exact"] is True
    assert lower > design["retention_minimum"]
    assert aggregate["decision"] == "retain"
