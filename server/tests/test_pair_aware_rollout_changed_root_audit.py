"""Tests for the fresh high-N audit of selected v1 root changes."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_changed_root_audit as AUDIT  # noqa: E402


def test_frozen_v1_changed_population_replays_exactly():
    payload, rows = AUDIT.changed_v1_rows()
    assert payload["aggregate"]["v1_root_changes"] == len(rows) == 9
    assert len({row["state_id"] for row in rows}) == 9
    for row in rows:
        rnd = AUDIT.ROOT.reconstruct_root(row)
        assert rnd.turn == row["seat"]
        assert len(rnd.history) == row["completed_tricks"]


def test_two_world_single_root_smoke_is_non_authorizing():
    _payload, rows = AUDIT.changed_v1_rows()
    result = AUDIT.audit_root(rows[0], n_worlds=2, sample_seed=17)
    assert result["sampler_work"]["accepted_worlds"] == 2
    assert set(result["by_continuation"]) == {
        "historical_matched_null", "v1_pair_aware",
    }


def test_direction_summary_contract_names_both_metrics():
    root = {
        "by_continuation": {
            policy: {
                "signed_level_utility_delta": {"ci_two_sided_95": [1, 2]},
                "signed_point_delta": {"ci_two_sided_95": [-2, -1]},
            }
            for policy in ("historical_matched_null", "v1_pair_aware")
        }
    }
    summary = AUDIT.direction_summary([root])
    assert set(summary) == {
        "signed_level_utility_delta", "signed_point_delta",
    }
    for policy in ("historical_matched_null", "v1_pair_aware"):
        assert summary["signed_level_utility_delta"][policy] == {
            "v1_action_positive_roots": 1,
            "incumbent_positive_roots": 0,
            "unresolved_roots": 0,
        }
        assert summary["signed_point_delta"][policy] == {
            "v1_action_positive_roots": 0,
            "incumbent_positive_roots": 1,
            "unresolved_roots": 0,
        }
