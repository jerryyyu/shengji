"""Contracts for the fresh S6 full-hand exact exploration."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_full_hand_exact_exploration as S  # noqa: E402


DATA = Path(__file__).with_name("data")
CAPTURE = DATA / "s6_throw_full_hand_exact_capture.v1.json"
RESULT = DATA / "s6_throw_full_hand_exact_result.v1.json"
CAPTURE_SHA256 = (
    "99debb547d8ba92456c9d9d8a7e36dd49fdc061b589b063ddcd86e3ab2de5708")
RESULT_SHA256 = (
    "946b029c0922a902ad5974977cef4a8a30ac245430563f57483c25597d65cebe")


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


def test_fresh_air_result_recomputes_and_preserves_bounded_meaning():
    capture_raw = CAPTURE.read_bytes()
    result_raw = RESULT.read_bytes()
    assert hashlib.sha256(capture_raw).hexdigest() == CAPTURE_SHA256
    assert hashlib.sha256(result_raw).hexdigest() == RESULT_SHA256
    capture = json.loads(capture_raw)
    result = json.loads(result_raw)

    assert capture["git"] == \
        "b9e8c205359f951cb0c2a9f84d48e0f3d56a3a7d"
    assert capture["seed0"] == S.SEED0
    assert capture["role_counts"] == {"attacker": 64, "defender": 64}
    assert capture["complete"] is True
    assert capture["score_free"] is True
    assert capture["outcomes_computed"] is False
    assert len(capture["rows"]) == 128
    assert all(row["score_free_selection"] is True
               for row in capture["rows"])

    internal = result.pop("internal_sha256")
    assert internal == \
        "3741bc6f9e4f7e17b719380a143305d2b04bc1c4a1f78b6c1448bc02b3823f45"
    assert S.stable_digest(result) == internal
    result["internal_sha256"] = internal
    assert result["tree_dirty"] is False
    assert result["capture_sha256"] == S.stable_digest(capture)
    assert result["aggregate"] == S.aggregate(result["rows"], role_quota=64)

    aggregate = result["aggregate"]
    assert aggregate["coverage_complete"] is True
    assert aggregate["refused_rows"] == 0
    assert aggregate["pooled_level_delta"] == {
        "n": 128,
        "mean": 0.234375,
        "se": 0.08187364758154535,
        "lcb_one_sided_95": 0.0997048338237485,
    }
    assert (sum(role["wins"] for role in aggregate["roles"].values()),
            sum(role["losses"] for role in aggregate["roles"].values()),
            sum(role["ties"] for role in aggregate["roles"].values())) == \
        (24, 8, 96)
    assert aggregate["status"] == "ADVANCE_TO_PUBLIC_GATE_DEV_SCREEN"
    assert aggregate["public_gate_dev_screen_design_authorized"] is True
    assert aggregate["whole_game_execution_authorized"] is False
    assert aggregate["strength_claim"] is False
    assert result["production_deployment"] is False
