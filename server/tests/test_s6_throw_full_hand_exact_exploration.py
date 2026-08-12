"""Contracts for the fresh S6 full-hand exact exploration."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_exact_exploration as S  # noqa: E402


def _row(role: str, delta: float, points: int = 0):
    return {
        "status": "SCORED",
        "role": role,
        "signed_level_utility_delta": delta,
        "signed_point_delta": points,
    }


def test_design_is_fresh_balanced_and_nonpromotable():
    assert S.SEED0 == 433_000_000
    assert S.HAND_CARDS == 4
    assert S.ROLE_QUOTA == 64
    assert S.ROLES == ("attacker", "defender")


def test_named_full_hand_winner_is_selected_and_replays():
    rnd, actors = S.BASE._start_round(432_000_152)
    while rnd.phase == "play":
        seat = rnd.turn
        if len(rnd.history) == 15 and seat == 3 and not rnd.trick.plays:
            source = S.qualifying_candidates(rnd, seat)
            assert source is not None
            assert source["added_candidates"][0]["cards"] == [
                "H5", "H8", "HK", "HQ",
            ]
            assert all(len(row["cards"]) == len(rnd.hands[seat])
                       for row in source["added_candidates"])
            return
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    raise AssertionError("named full-hand state disappeared")


def test_aggregate_advances_only_complete_positive_both_role_result():
    rows = []
    for role in S.ROLES:
        rows.extend(_row(role, 1.0) for _ in range(3))
        rows.extend(_row(role, 0.0) for _ in range(61))
    result = S.aggregate(rows, role_quota=64)
    assert result["coverage_complete"] is True
    assert result["pooled_level_delta"]["lcb_one_sided_95"] > 0
    assert result["status"] == "ADVANCE_TO_PUBLIC_GATE_DEV_SCREEN"
    assert result["public_gate_dev_screen_design_authorized"] is True
    assert result["whole_game_execution_authorized"] is False
    assert result["strength_claim"] is False


def test_aggregate_keeps_partial_learning_without_advancing():
    rows = [_row("attacker", 2.0), _row("defender", 2.0), {
        "status": "REFUSED", "role": "attacker",
    }]
    result = S.aggregate(rows, role_quota=2)
    assert result["coverage_complete"] is False
    assert result["refused_rows"] == 1
    assert result["status"] == "NO_EXACT_ACTION_SET_SIGNAL"
    assert result["public_gate_dev_screen_design_authorized"] is False


def test_negative_role_blocks_advance_even_with_positive_pool():
    rows = ([_row("attacker", 1.0) for _ in range(64)]
            + [_row("defender", -0.01) for _ in range(64)])
    result = S.aggregate(rows, role_quota=64)
    assert result["pooled_level_delta"]["mean"] > 0
    assert result["roles"]["defender"]["level_delta"]["mean"] < 0
    assert result["public_gate_dev_screen_design_authorized"] is False
