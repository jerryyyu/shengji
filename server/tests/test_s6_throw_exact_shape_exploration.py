"""Contracts for the exploration-tier S6 throw-shape exact screen."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_exact_shape_exploration as S  # noqa: E402


def test_design_is_fresh_balanced_and_nonpromotable():
    assert S.SEED0 == 432_000_000
    assert S.MAX_DEALS == 100_000
    assert S.CELL_QUOTA == 32
    assert S.HAND_CARDS == 4
    assert S.STRATA == ("boss_near", "whole_plain", "whole_trump")


def test_candidate_strata_use_specific_source_precedence():
    assert S.candidate_stratum([S.BOSS_NEAR_BUNDLE]) == "boss_near"
    assert S.candidate_stratum([
        S.BOSS_NEAR_BUNDLE, S.WHOLE_SUIT_EVACUATION,
    ]) == "boss_near"
    assert S.candidate_stratum([S.WHOLE_SUIT_EVACUATION]) == "whole_plain"
    assert S.candidate_stratum([S.WHOLE_TRUMP_EVACUATION]) == "whole_trump"


def _row(role: str, stratum: str, delta: float, points: int):
    return {
        "status": "SCORED",
        "role": role,
        "stratum": stratum,
        "signed_level_utility_delta": delta,
        "signed_point_delta": points,
    }


def test_aggregate_keeps_partial_rows_without_granting_authority():
    rows = [
        _row(role, stratum, 1.0, 10)
        for role in S.ROLES for stratum in S.STRATA
    ]
    rows.append({
        "status": "REFUSED", "role": "attacker", "stratum": "boss_near",
    })
    result = S.aggregate(rows, cell_quota=2)
    assert result["scored_rows"] == 6
    assert result["refused_rows"] == 1
    assert result["coverage_complete"] is False
    assert result["policy_selector_tested"] is False
    assert result["whole_game_execution_authorized"] is False
    assert result["strength_claim"] is False
    assert result["production_deployment"] is False


def test_descriptive_ranking_treats_zero_as_better_than_negative():
    rows = []
    means = {"boss_near": 0.0, "whole_plain": -1.0, "whole_trump": 1.0}
    for role in S.ROLES:
        for stratum in S.STRATA:
            rows.append(_row(role, stratum, means[stratum], 0))
    result = S.aggregate(rows, cell_quota=1)
    assert result["descriptive_ranking"] == [
        "whole_trump", "boss_near", "whole_plain",
    ]
    assert result["coverage_complete"] is True


def test_small_score_free_capture_is_balanced_and_replayable():
    capture = S.capture_states(seed0=S.SEED0, max_deals=200, cell_quota=1)
    assert capture["complete"] is True
    assert len(capture["rows"]) == len(S.ROLES) * len(S.STRATA)
    assert len({row["deal_seed"] for row in capture["rows"]}) == \
        len(capture["rows"])
    assert all(value == 1 for value in capture["cell_counts"].values())
    for record in capture["rows"]:
        rnd = S.replay_capture(record)
        assert rnd.turn == record["seat"]
        assert len(rnd.history) == record["completed_tricks"]
        assert max(map(len, rnd.hands)) == S.HAND_CARDS


def test_one_named_capture_scores_new_source_against_full_live_ballot():
    capture = S.capture_states(seed0=S.SEED0, max_deals=200, cell_quota=1)
    record = capture["rows"][0]
    row = S.score_capture(record)
    assert row["status"] == "SCORED"
    assert row["live_candidate_count"] == len(record["live_candidates"])
    assert row["new_candidate_count"] == len(record["added_candidates"])
    assert row["perfect_information_oracle"] is True
    assert row["strength_claim"] is False
    assert isinstance(row["signed_level_utility_delta"], float)
    assert isinstance(row["signed_point_delta"], int)
