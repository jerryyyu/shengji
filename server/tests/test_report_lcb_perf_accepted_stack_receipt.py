"""Durable, non-authorizing receipt for the terminal-reviewed V5 A/B."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
RECEIPT = (
    SERVER / "tests" / "data" /
    "report_lcb_perf_accepted_stack_v5.v1.json"
)
EXPECTED_RECEIPT_SHA256 = (
    "fb78b201f699fbb8dc0f2841e8e8b0f840650a21af28b48f075053175d50c1d9"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt() -> dict:
    value = json.loads(RECEIPT.read_text())
    assert isinstance(value, dict)
    return value


def test_receipt_and_measured_source_bytes_are_exact():
    value = _receipt()
    assert _sha256(RECEIPT) == EXPECTED_RECEIPT_SHA256
    assert value["schema"] == \
        "report-lcb-perf-accepted-stack-v5-receipt-v1"
    for logical, expected in value["source_sha256s"].items():
        assert _sha256(SERVER.parent / logical) == expected


def test_receipt_recomputes_the_terminal_retention_statistics():
    measurement = _receipt()["measurement"]
    rows = measurement["records"]
    assert len(rows) == 6
    assert len({row["seed"] for row in rows}) == 6
    assert [row["order"] for row in rows] == [
        "base_head", "head_base", "base_head",
        "head_base", "base_head", "head_base",
    ]
    assert all(
        isinstance(row["base_elapsed_ns"], int)
        and not isinstance(row["base_elapsed_ns"], bool)
        and row["base_elapsed_ns"] > 0
        and isinstance(row["head_elapsed_ns"], int)
        and not isinstance(row["head_elapsed_ns"], bool)
        and row["head_elapsed_ns"] > 0
        and len(row["normalized_semantic_sha256"]) == 64
        for row in rows
    )

    base_total = sum(row["base_elapsed_ns"] for row in rows)
    head_total = sum(row["head_elapsed_ns"] for row in rows)
    relative = [
        100.0 * (row["base_elapsed_ns"] - row["head_elapsed_ns"])
        / row["base_elapsed_ns"]
        for row in rows
    ]
    mean = statistics.fmean(relative)
    sample_sd = statistics.stdev(relative)
    paired = measurement["paired"]
    lcb = mean - paired["t_critical"] * sample_sd / math.sqrt(len(rows))
    wall_reduction = 100.0 * (base_total - head_total) / base_total
    throughput = 100.0 * (base_total / head_total - 1.0)

    assert base_total == measurement["aggregate"]["base_wall_ns"]
    assert head_total == measurement["aggregate"]["head_wall_ns"]
    assert math.isclose(
        wall_reduction,
        measurement["aggregate"]["wall_reduction_percent"],
        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(
        throughput,
        measurement["aggregate"]["throughput_increase_percent"],
        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(
        mean, paired["relative_reduction_mean_percent"],
        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(
        sample_sd, paired["relative_reduction_sample_sd_percent"],
        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(
        lcb, paired["one_sided_95_lcb_percent"],
        rel_tol=0.0, abs_tol=1e-12)
    assert wall_reduction >= measurement["retention"][
        "aggregate_minimum_percent_inclusive"]
    assert lcb > measurement["retention"][
        "paired_lcb_minimum_percent_exclusive"]
    assert measurement["decision"] == "retain"


def test_receipt_grants_no_execution_strength_or_deployment_authority():
    value = _receipt()
    assert value["authority"] == {
        "benchmark_retry_authorized": False,
        "deployment_authorized": False,
        "merge_authorized": False,
        "performance_only": True,
        "production_mutation_authorized": False,
        "strength_claim": False,
    }
    assert value["measurement"]["normalized_fields"] == [
        "ballot.digest", "ballot.display", "ballot.source_digest"]
    assert value["evidence"]["terminal_review_commit"] == \
        "e5818eec0bc8b96053424384f39d4cf2b40715af"
