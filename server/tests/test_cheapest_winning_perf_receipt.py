"""Self-check the bounded `_cheapest_winning` performance receipt."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
RECEIPT = SERVER / "tests/data/cheapest_winning_native_perf_exact_head.v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cheapest_winning_perf_receipt_is_source_pinned_and_reconciles():
    record = json.loads(RECEIPT.read_text())
    head = record["head"]
    assert _sha(SERVER / "shengji/engine/_fast.pyx") == head["fast_pyx_sha256"]
    assert _sha(SERVER / "shengji/engine/fast.py") == head["fast_router_sha256"]
    assert _sha(SERVER / "tests/test_fast_parity.py") == \
        head["parity_test_sha256"]

    rows = record["records"]
    assert len(rows) == record["design"]["pairs"] == 6
    assert [row["seed"] for row in rows] == record["design"]["seeds"]
    assert [row["order"] for row in rows] == \
        ["base_head", "head_base"] * 3
    assert all(len(row["normalized_semantic_sha256"]) == 64 for row in rows)

    base = [row["base_seconds"] for row in rows]
    head_times = [row["head_seconds"] for row in rows]
    reductions = [100.0 * (a - b) / a for a, b in zip(base, head_times)]
    aggregate = record["aggregate"]
    assert math.isclose(sum(base), aggregate["base_wall_seconds"], abs_tol=1e-12)
    assert math.isclose(sum(head_times), aggregate["head_wall_seconds"],
                        abs_tol=1e-12)
    assert math.isclose(
        100.0 * (sum(base) - sum(head_times)) / sum(base),
        aggregate["wall_reduction_percent"], abs_tol=1e-12)
    assert math.isclose(statistics.mean(reductions),
                        aggregate["paired_relative_mean_percent"],
                        abs_tol=1e-12)
    lower = (statistics.mean(reductions)
             - record["design"]["one_sided_t95_df5"]
             * statistics.stdev(reductions) / math.sqrt(len(reductions)))
    assert math.isclose(lower, aggregate["paired_one_sided_95_lb_percent"],
                        abs_tol=1e-12)
    assert aggregate["normalized_semantics_exact"] is True
    assert aggregate["wall_reduction_percent"] >= \
        record["retention_rule"]["minimum_wall_reduction_percent"]
