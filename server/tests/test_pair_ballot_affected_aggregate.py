from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_aggregate as AGG  # noqa: E402


def _rows(policy_values, source_values):
    rows = []
    index = 0
    for band in ("early", "mid", "late"):
        for policy, source in zip(
                policy_values[band], source_values[band], strict=True):
            rows.append({
                "band": band,
                "deal_seed": 100 + index,
                "estimands": {
                    "retained_policy_minus_current": policy,
                    "best_inserted_pair_minus_current": source,
                },
            })
            index += 1
    return rows


def test_natural_weighted_stats_use_band_weights_not_capture_mix():
    rows = _rows(
        {"early": [1.0, 3.0], "mid": [2.0, 4.0], "late": [10.0, 14.0]},
        {"early": [0.0, 0.0], "mid": [0.0, 0.0], "late": [0.0, 0.0]},
    )
    result = AGG.weighted_cluster_stats(
        rows, "retained_policy_minus_current",
        {"early": 0.8, "mid": 0.15, "late": 0.05})
    assert result["natural_weighted_mean"] == pytest.approx(
        0.8 * 2.0 + 0.15 * 3.0 + 0.05 * 12.0)
    assert result["rows"] == 6
    assert result["deal_clusters"] == 6
    assert result["cluster_robust_se"] > 0


def test_cluster_robust_se_keeps_same_deal_rows_together():
    rows = _rows(
        {"early": [-1.0, 1.0], "mid": [-1.0, 1.0], "late": [-1.0, 1.0]},
        {"early": [0.0, 0.0], "mid": [0.0, 0.0], "late": [0.0, 0.0]},
    )
    independent = AGG.weighted_cluster_stats(
        rows, "retained_policy_minus_current",
        {band: 1 / 3 for band in ("early", "mid", "late")})
    correlated_rows = copy.deepcopy(rows)
    for index, row in enumerate(correlated_rows):
        row["deal_seed"] = index % 2
    correlated = AGG.weighted_cluster_stats(
        correlated_rows, "retained_policy_minus_current",
        {band: 1 / 3 for band in ("early", "mid", "late")})
    assert correlated["deal_clusters"] == 2
    assert correlated["cluster_robust_se"] > independent["cluster_robust_se"]


@pytest.mark.parametrize(("policy", "source", "expected"), [
    (0.1, 0.2, "POLICY_AND_SOURCE_PROMISING_TEST_NATURAL_DOSE"),
    (-0.1, 0.2, "SOURCE_PROMISING_SELECTOR_NOT_EXPLOITING"),
    (0.1, -0.2, "POLICY_POSITIVE_WITHOUT_INSERTED_PAIR_HEADROOM_AUDIT_EVICTIONS"),
    (-0.1, -0.2, "FIXED_WIDTH_RETENTION_NOT_PROMISING_TRY_CONTEXTUAL_PAIR_SOURCE"),
])
def test_diagnostic_route_preserves_learning(policy, source, expected):
    assert AGG.diagnostic_route(policy, source) == expected


def test_stats_refuse_missing_band_or_invalid_weights():
    rows = _rows(
        {"early": [1.0], "mid": [1.0], "late": [1.0]},
        {"early": [1.0], "mid": [1.0], "late": [1.0]},
    )
    with pytest.raises(AGG.EVAL.EvalRefused, match="band population"):
        AGG.weighted_cluster_stats(
            rows[:-1], "retained_policy_minus_current",
            {band: 1 / 3 for band in ("early", "mid", "late")})
    with pytest.raises(AGG.EVAL.EvalRefused, match="natural weights"):
        AGG.weighted_cluster_stats(
            rows, "retained_policy_minus_current",
            {"early": 0.5, "mid": 0.5, "late": 0.5})
