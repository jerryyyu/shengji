"""Tests for replaying the native MC-LCB selector under objective changes."""

import copy

import pytest

from shengji.ai.registry import REGISTRY
from shengji.train.cwv_selector_objective_audit import replay_selector
from tests.test_world_shortlist import play_state


def _ballot(rnd, seat):
    return REGISTRY["mc-s0-report-lcb"](seed=7)._candidates(rnd, seat)[:2]


def _matrices(rnd, seat, values, report=None):
    selection = [list(values), list(values)]
    report = list(values) if report is None else list(report)
    return selection, [list(report) for _ in range(30)]


def test_replay_has_native_fixed_ballot_record_and_exact_saved_work():
    rnd = play_state()
    seat = rnd.turn
    ballot = _ballot(rnd, seat)
    selection, report = _matrices(rnd, seat, [80, 100])
    before = copy.deepcopy(rnd)
    result = replay_selector(rnd, seat, ballot, selection, report, seed=13)
    record = result["record"]
    assert result["played"] == ballot[0]
    assert record["candidates"] == ballot
    assert record["work"]["selection_rollouts"] == 4
    assert record["work"]["report_rollouts"] == 60
    assert record["work"]["complete"] is True
    assert record["replay"] == {
        "mode": "saved_attacker_points", "objective": "points",
        "selection_values": 4, "report_values": 60,
        "fresh_rollouts": 0, "cpu_work": "replayed_values",
    }
    assert rnd.hands == before.hands
    assert rnd.trick.plays == before.trick.plays


def test_points_and_levels_can_choose_opposite_moves_from_actual_report_path():
    rnd = play_state()
    ballot = _ballot(rnd, rnd.turn)
    attacker = next(seat for seat in range(4) if rnd.is_attacker(seat))
    defender = next(seat for seat in range(4) if not rnd.is_attacker(seat))
    # Selection values make the challenger win both objectives.  The report
    # distributions have opposite signed gaps after the level transform:
    # points override, while levels retain the incumbent, for each perspective.
    for seat, selection_values, report_base, report_hi, expected_points, expected_levels in (
        (attacker, [1, 80], 1, (0, 3), ballot[1], ballot[0]),
        (defender, [30, 0], 30, (1, 40), ballot[1], ballot[0]),
    ):
        selection = [list(selection_values), list(selection_values)]
        report = [[report_base, report_hi[0]] for _ in range(15)]
        report.extend([[report_base, report_hi[1]] for _ in range(15)])
        point_result = replay_selector(
            rnd, seat, ballot, selection, report, seed=3, objective="points")
        level_result = replay_selector(
            rnd, seat, ballot, selection, report, seed=3, objective="levels")
        assert point_result["played"] == expected_points
        assert level_result["played"] == expected_levels


def test_positive_report_mean_with_negative_lcb_keeps_incumbent():
    rnd = play_state()
    seat = next(s for s in range(4) if rnd.is_attacker(s))
    ballot = _ballot(rnd, seat)
    selection, _ = _matrices(rnd, seat, [100, 110])
    differences = [10.0] * 15 + [-8.0] * 15
    report = [[100.0, 100.0 + difference] for difference in differences]
    result = replay_selector(rnd, seat, ballot, selection, report, seed=9)
    assert result["record"]["report_fold"]["gap"] > 0
    assert result["record"]["report_fold"]["statistic"] < 0
    assert result["played"] == ballot[0]
    assert result["record"]["reason"] == "report_lcb_below_min_gain"


def test_levels_objective_is_uncapped_above_legacy_three_level_cap():
    rnd = play_state()
    seat = next(s for s in range(4) if rnd.is_attacker(s))
    ballot = _ballot(rnd, seat)
    selection, report = _matrices(rnd, seat, [4000, 4120])
    result = replay_selector(rnd, seat, ballot, selection, report, seed=11,
                             objective="levels")
    assert result["played"] == ballot[1]
    assert result["record"]["means"] == [3940.0, 4060.0]


def test_single_candidate_preserves_native_no_search_behavior():
    rnd = play_state()
    seat = rnd.turn
    ballot = _ballot(rnd, seat)[:1]
    result = replay_selector(rnd, seat, ballot, [[100]], [[100]] * 30, seed=2)
    assert result == {"played": ballot[0], "record": None}


@pytest.mark.parametrize("bad", ["objective", "shape", "fractional", "nan"])
def test_replay_refuses_invalid_inputs(bad):
    rnd = play_state()
    seat = rnd.turn
    ballot = _ballot(rnd, seat)
    selection, report = _matrices(rnd, seat, [100, 80])
    if bad == "objective":
        with pytest.raises(ValueError, match="objective"):
            replay_selector(rnd, seat, ballot, selection, report, seed=1,
                            objective="other")
    elif bad == "shape":
        with pytest.raises(ValueError, match="shape"):
            replay_selector(rnd, seat, ballot, [[100]], report, seed=1)
    elif bad == "fractional":
        with pytest.raises(ValueError, match="integral"):
            replay_selector(rnd, seat, ballot, [[100.5, 80]], report, seed=1)
    else:
        import math
        selection[0][0] = math.nan
        with pytest.raises(ValueError, match="finite"):
            replay_selector(rnd, seat, ballot, selection, report, seed=1)
