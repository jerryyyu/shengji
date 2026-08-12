"""Contracts for the cheap pair-aware exact-endgame exploration."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import pair_aware_rollout_exact_screen as S  # noqa: E402


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
