"""Recompute the bounded native-lead exploratory performance receipt."""

from __future__ import annotations

import json
import math
from pathlib import Path
import statistics


RECEIPT = (Path(__file__).resolve().parent / "data" /
           "heuristic_lead_native_perf_exploratory.v1.json")


def test_native_lead_exploratory_receipt_reconciles_without_authority():
    record = json.loads(RECEIPT.read_text())
    assert record["schema"] == "heuristic-lead-native-perf-exploratory-v1"
    assert record["claim_boundary"] == {
        "confirmatory": False,
        "exploratory_only": True,
        "merge_authority": False,
        "performance_only": True,
        "production_deployment": False,
        "review_authority": False,
        "sampling_or_rng_change": False,
        "strength_claim": False,
    }

    evidence = record["evidence"]
    assert evidence["manifest_present"] is False
    assert evidence["manifest_sha256"] is None
    assert evidence["raw_artifacts_committed"] is False
    assert evidence["raw_artifacts_preserved_at_remote_root"] is True
    assert evidence["result_schema"] == \
        "cheapest-winning-native-perf-result-v2"
    for key in ("design_sha256", "result_sha256", "harness_sha256",
                "runner_sha256"):
        assert len(evidence[key]) == 64

    assert record["base"]["git"] == \
        "c6c7126804231ec9ad5b029c011c4687ca778fdb"
    assert record["head"]["git"] == \
        "8e698e1456ab8d57dd515c6ca5fbf48c45a4b674"
    runtime = record["runtime"]
    assert runtime["machine"] == "x86_64"
    assert runtime["logical_cpus"] == 16
    assert runtime["python_version"] == "3.14.4"
    assert runtime["compiled_engine_required"] is True
    assert runtime["void_respecting_sampler_required"] is True

    normalization = record["normalization"]
    assert normalization["all_other_serialized_bytes_compared_exactly"] \
        is True
    assert normalization["removed_for_arm_comparison"] == [
        "decision_records[*].record.ballot.digest",
        "decision_records[*].record.ballot.display",
        "decision_records[*].record.ballot.source_digest",
    ]

    design, rows = record["design"], record["records"]
    assert design["policy"] == "mc-s0-report-lcb"
    assert design["n_determinizations"] == 30
    assert design["report_fold_worlds"] == 300
    assert len(rows) == design["pairs"] == 3
    assert [row["seed"] for row in rows] == design["seeds"]
    assert [row["order"] for row in rows] == design["orders"]
    assert design["one_fresh_batch_no_tuning_or_retry"] is True
    assert record["validation"]["every_searched_decision_n30_r300"] \
        is True
    assert record["validation"]["short_search_decisions"] == 0
    assert record["validation"]["zero_world_decisions"] == 0

    for row in rows:
        base, head = row["base"], row["head"]
        assert base["raw_semantic_sha256"] != head["raw_semantic_sha256"]
        assert base["normalized_semantic_sha256"] == \
            head["normalized_semantic_sha256"]
        assert base["rollouts"] == head["rollouts"]
        assert base["search_calls"] == head["search_calls"]
        assert base["normalization_removals_per_field"] == \
            head["normalization_removals_per_field"] > 0

    base_times = [row["base"]["elapsed_seconds"] for row in rows]
    head_times = [row["head"]["elapsed_seconds"] for row in rows]
    reductions = [100.0 * (base - head) / base
                  for base, head in zip(base_times, head_times)]
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
    assert math.isclose(lower,
                        aggregate["paired_one_sided_95_lb_percent"],
                        abs_tol=1e-12)
    assert all(reduction > 0 for reduction in reductions)
    assert aggregate["normalized_semantics_exact"] is True
    assert "not a confirmatory verdict" in aggregate["interpretation"]
