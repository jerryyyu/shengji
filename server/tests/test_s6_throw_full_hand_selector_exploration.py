"""Contracts for the S6 actor-visible full-hand selector diagnostic."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_selector_exploration as S  # noqa: E402


RESULT = Path(__file__).with_name("data") / \
    "s6_throw_full_hand_selector_result.v1.json"
RESULT_SHA256 = (
    "5473343472c272d3521a04b67bfb7719393ac2adb4263b0f8c1f070be551984c")


def _state(role: str, delta: float, *, override: bool = True) -> dict:
    return {
        "status": "SCORED",
        "role": role,
        "oracle_new_minus_best_live_level_delta": delta,
        "cluster_mean_level_delta": delta,
        "override_count": int(override),
        "decisions": [{
            "override": override,
            "signed_level_utility_delta": delta if override else 0.0,
            "exact_work_complete": True,
        }],
    }


def test_design_is_reusable_dev_and_has_four_search_streams():
    assert S.MC_REPLICATES == 4
    assert S.DECISION_SEED0 == 435_000_000
    assert S.CAPTURE_SHA256 == \
        "99debb547d8ba92456c9d9d8a7e36dd49fdc061b589b063ddcd86e3ab2de5708"
    assert S.ORACLE_RESULT_SHA256 == \
        "946b029c0922a902ad5974977cef4a8a30ac245430563f57483c25597d65cebe"


def test_public_population_is_pinned_complete_and_aligned():
    capture, oracle = S.load_public_population()
    assert len(capture) == len(oracle) == 128
    assert {row["role"] for row in capture} == {"attacker", "defender"}
    assert all(len(row["added_candidates"]) == 1 for row in capture)


def test_aggregate_advances_only_complete_positive_both_role_selector():
    rows = [_state("attacker", 1.0), _state("defender", 1.0)]
    result = S.aggregate(rows, expected_states=2, replicates=1)
    assert result["coverage_complete"] is True
    assert result["pooled_state_cluster_level_delta"]["lcb_one_sided_95"] > 0
    assert result["status"] == \
        "ADVANCE_TO_FRESH_WHOLE_GAME_PACKET_DESIGN"
    assert result["fresh_whole_game_packet_design_authorized"] is True
    assert result["whole_game_execution_authorized"] is False
    assert result["strength_claim"] is False


def test_aggregate_preserves_learning_but_blocks_incomplete_result():
    rows = [_state("attacker", 1.0), {
        "status": "REFUSED", "role": "defender", "decisions": [],
    }]
    result = S.aggregate(rows, expected_states=2, replicates=1)
    assert result["coverage_complete"] is False
    assert result["refused_states"] == 1
    assert result["fresh_whole_game_packet_design_authorized"] is False


def test_named_state_runs_literal_gate_and_exact_scores_selected_action():
    capture, oracle = S.load_public_population()
    row = S.score_state(
        capture[0], oracle[capture[0]["state_id"]],
        state_index=0, replicates=1)
    assert row["status"] == "SCORED"
    assert row["replicates"] == 1
    assert len(row["decisions"]) == 1
    decision = row["decisions"][0]
    assert decision["exact_work_complete"] is True
    assert decision["report_worlds"] == 300
    assert decision["selected"]["submitted"] in (
        decision["incumbent"]["submitted"],
        capture[0]["added_candidates"][0]["cards"],
    )


def test_air_selector_result_recomputes_and_has_bounded_meaning():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RESULT_SHA256
    payload = json.loads(raw)
    assert payload["git"] == \
        "93b25a2f6173b9856cabf0e062d6ea325a98a38f"
    internal = payload.pop("internal_sha256")
    assert internal == \
        "169870d10ad48bf1fa97983cb700f8708f354dd1e7b33a8abb46556057203301"
    assert S.stable_digest(payload) == internal
    payload["internal_sha256"] = internal
    assert payload["tree_dirty"] is False
    assert payload["aggregate"] == S.aggregate(
        payload["rows"], expected_states=128, replicates=4)

    aggregate = payload["aggregate"]
    assert aggregate["coverage_complete"] is True
    assert aggregate["refused_states"] == 0
    assert aggregate["decisions"] == 512
    assert aggregate["overrides"] == 427
    assert aggregate["beneficial_overrides"] == 101
    assert aggregate["harmful_overrides"] == 20
    assert aggregate["neutral_overrides"] == 306
    assert aggregate["pooled_state_cluster_level_delta"] == {
        "n": 128,
        "mean": 0.306640625,
        "se": 0.08028341447987938,
        "lcb_one_sided_95": 0.17458615950872206,
    }
    assert all(
        row["lcb_one_sided_95"] > 0
        for row in aggregate["role_state_cluster_level_delta"].values())
    assert aggregate["status"] == \
        "ADVANCE_TO_FRESH_WHOLE_GAME_PACKET_DESIGN"
    assert aggregate["fresh_whole_game_packet_design_authorized"] is True
    assert aggregate["whole_game_execution_authorized"] is False
    assert aggregate["strength_claim"] is False
    assert payload["production_deployment"] is False
