"""Tests for the fresh high-N audit of selected v1 root changes."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_changed_root_audit as AUDIT  # noqa: E402


RESULT = Path(__file__).with_name("data") / (
    "pair_aware_rollout_v1_changed_root_audit.v2.json")
RESULT_SHA256 = (
    "131a64e72df8203c30501c245a3ce82a20be9cc14aa94dcc9503fafbf8a7eaa3")
RESULT_INTERNAL_SHA256 = (
    "0c43efc47bd97a11d3608c2b1518f5385db32f32a9398adc9423b4d8a642b6a5")


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


def test_frozen_high_n_result_is_exact_and_non_authorizing():
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == RESULT_SHA256
    payload = json.loads(RESULT.read_bytes())
    assert payload["schema"] == AUDIT.SCHEMA
    assert payload["git"] == (
        "ec9c98b503d9e6d17512bbe04aac8b48f0ca5caf")
    assert payload["tree_dirty"] is False
    assert payload["design"]["primary_metric"] == (
        "signed_level_utility_delta")
    assert len(payload["roots"]) == 9
    assert {row["sampler_work"]["accepted_worlds"]
            for row in payload["roots"]} == {4096}
    assert payload["internal_sha256"] == RESULT_INTERNAL_SHA256
    unsigned = dict(payload)
    del unsigned["internal_sha256"]
    assert AUDIT.ROOT.stable_digest(unsigned) == RESULT_INTERNAL_SHA256
    assert payload["direction_summary_by_metric"] == {
        "signed_level_utility_delta": {
            "historical_matched_null": {
                "incumbent_positive_roots": 2,
                "unresolved_roots": 2,
                "v1_action_positive_roots": 5,
            },
            "v1_pair_aware": {
                "incumbent_positive_roots": 1,
                "unresolved_roots": 2,
                "v1_action_positive_roots": 6,
            },
        },
        "signed_point_delta": {
            "historical_matched_null": {
                "incumbent_positive_roots": 1,
                "unresolved_roots": 2,
                "v1_action_positive_roots": 6,
            },
            "v1_pair_aware": {
                "incumbent_positive_roots": 0,
                "unresolved_roots": 3,
                "v1_action_positive_roots": 6,
            },
        },
    }
    assert payload["exploration_only"] is True
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["production_promotion"] is False
