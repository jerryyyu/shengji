from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_aggregate as AGG  # noqa: E402


def _scored_runtime() -> dict:
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "host": "test-host",
        "python": "3.14.0",
        "fast_engine": True,
        "score_free": False,
        "outcomes_computed": True,
        "strength_claim": False,
        "production_authority": False,
        "diagnostic_only": True,
    }


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


def test_capture_event_band_weighted_stats_disclose_hybrid_estimand():
    rows = _rows(
        {"early": [1.0, 3.0], "mid": [2.0, 4.0], "late": [10.0, 14.0]},
        {"early": [0.0, 0.0], "mid": [0.0, 0.0], "late": [0.0, 0.0]},
    )
    result = AGG.weighted_cluster_stats(
        rows, "retained_policy_minus_current",
        {"early": 0.8, "mid": 0.15, "late": 0.05})
    assert result["capture_event_band_weighted_mean"] == pytest.approx(
        0.8 * 2.0 + 0.15 * 3.0 + 0.05 * 12.0)
    assert result["selected_population_mean"] == pytest.approx(34 / 6)
    assert result["band_weight_unit"] == \
        "all_search_reachable_omission_events"
    assert result["within_band_sampling_unit"] == \
        "first_affected_state_per_deal_band_in_frozen_population"
    assert result["exact_natural_decision_estimand"] is False
    assert result["exact_whole_round_estimand"] is False
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
    with pytest.raises(AGG.EVAL.EvalRefused, match="capture-event weights"):
        AGG.weighted_cluster_stats(
            rows, "retained_policy_minus_current",
            {"early": 0.5, "mid": 0.5, "late": 0.5})


def test_scored_runtime_refuses_capture_authority_lie():
    runtime = _scored_runtime()
    AGG._validate_scored_runtime(runtime)

    capture_claim = copy.deepcopy(runtime)
    capture_claim["score_free"] = True
    capture_claim["outcomes_computed"] = False
    with pytest.raises(
            AGG.EVAL.EvalRefused, match="scored-runtime authority"):
        AGG._validate_scored_runtime(capture_claim)
