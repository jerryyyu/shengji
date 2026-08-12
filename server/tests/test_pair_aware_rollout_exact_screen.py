"""Contracts for the cheap pair-aware exact-endgame exploration."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import pair_aware_rollout_exact_screen as S  # noqa: E402


ASSET = Path(__file__).parent / "data/pair_aware_rollout_exact_screen.v1.json"
ASSET_SHA256 = (
    "031a365dabff0601ca66299b7b62cb2e38ff4231362b9004f683f26e14112919")


def test_named_fresh_trigger_is_real_and_exactly_scoreable():
    found = S._drive_to_trigger(331_000_032)
    assert found is not None
    rnd, seat, null_action, treatment_action, telemetry = found
    assert rnd.is_attacker(seat) is False
    assert [len(hand) for hand in rnd.hands] == [4, 4, 4, 4]
    assert null_action == ["H4"]
    assert treatment_action == ["H9", "H9"]
    assert telemetry["triggers"] == telemetry["changes"] == 1

    row = S._score_trigger(331_000_032, found)
    assert row["null_final_attacker_points"] == 135
    assert row["treatment_final_attacker_points"] == 125
    assert row["signed_point_delta"] == 10
    assert all(0 < value <= S.MAX_EXACT_NODES
               for value in row["exact_nodes"].values())


def _rows(delta: int, level_delta: float = 0.0):
    rows = []
    for role, count in S.ROLE_QUOTA.items():
        for index in range(count):
            rows.append({
                "deal_seed": (1_000_000 if role == "attacker"
                              else 2_000_000) + index,
                "role": role,
                "signed_point_delta": delta,
                "signed_level_utility_delta": level_delta,
            })
    return rows


def test_exploration_gate_can_advance_or_decline_but_never_authorizes_run():
    positive = S.aggregate(_rows(10, 1.0))
    assert positive["exploration_verdict"] == \
        "ADVANCE_TO_REVIEWED_WHOLE_GAME_SCREEN"
    assert all(positive["criteria"].values())
    assert positive["whole_game_execution_authorized"] is False
    assert positive["strength_claim"] is False
    assert positive["production_promotion"] is False

    negative = S.aggregate(_rows(-10, -1.0))
    assert negative["exploration_verdict"] == "DO_NOT_ADVANCE_THIS_RECIPE"
    assert not all(negative["criteria"].values())


def test_design_is_small_fresh_and_balanced():
    assert S.SEED0 == 331_000_000
    assert S.MAX_DEALS == 100_000
    assert S.ROLE_QUOTA == {"attacker": 32, "defender": 32}
    assert S.MAX_HAND_CARDS == 4
    assert S.MAX_EXACT_NODES == 500_000
    assert S.T_CRITICAL == 1.669


def test_air_result_asset_preserves_the_exploration_verdict_exactly():
    raw = ASSET.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ASSET_SHA256
    result = json.loads(raw)
    assert result["git"] == "c3faec3f34ff3273de003848ea0e5f0f99be68f8"
    assert result["tree_dirty"] is False
    assert result["deals_scanned"] == 24_412
    assert result["exact_refusals"] == {}
    assert result["aggregate"] == {
        "by_role": {
            "attacker": {
                "lcb_one_sided_95": 9.995163823075686,
                "mean": 13.59375,
                "n": 32,
                "se": 2.156133119786887,
            },
            "defender": {
                "lcb_one_sided_95": 1.6979440514398023,
                "mean": 4.84375,
                "n": 32,
                "se": 1.8848447864351094,
            },
        },
        "criteria": {
            "both_role_point_means_ge_0": True,
            "level_utility_mean_ge_0": True,
            "overall_point_lcb_gt_0": True,
        },
        "exploration_verdict": "ADVANCE_TO_REVIEWED_WHOLE_GAME_SCREEN",
        "level_utility_mean": 0.375,
        "losses": 1,
        "points": {
            "lcb_one_sided_95": 6.675695030629216,
            "mean": 9.21875,
            "n": 64,
            "se": 1.5236998018998111,
        },
        "primary": "acting-team signed exact final attacker-point delta",
        "production_promotion": False,
        "strength_claim": False,
        "ties": 33,
        "whole_game_execution_authorized": False,
        "wins": 30,
    }
