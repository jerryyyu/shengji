import copy
import math

import pytest

from shengji.eval.ballot_full_pool import summarize_full_pool_matrix


def test_full_pool_reports_ties_availability_gaps_and_restricted_union():
    out = summarize_full_pool_matrix(
        [["S2"], ["H2"], ["BJ"], ["S2", "S2"]],
        [["H2"]], [["BJ"], ["H2"]],
        [[1, 4, 3, 2], [3, 2, 3, 2], [5, 0, 3, 2]],
    )
    assert out["full_pool"] == {
        "best_predicted_value": 3.0,
        "exact_maximizers": [["S2"], ["BJ"]],
    }
    assert out["control"] == {
        "raw_best_action": ["H2"],
        "raw_best_actions": [["H2"]],
        "raw_best_predicted_value": 2.0,
        "predicted_value_gap_to_full_maximum": 1.0,
        "any_maximum_available": False,
        "all_maximum_available": False,
    }
    assert out["treatment"]["raw_best_actions"] == [["BJ"]]
    assert out["treatment"]["any_maximum_available"]
    assert not out["treatment"]["all_maximum_available"]
    assert out["treatment"]["predicted_value_gap_to_full_maximum"] == 0.0
    assert out["union"]["selected_action"] == ["BJ"]
    assert out["union_summary"]["action_count"] == 2
    assert out["action_count"] == 4
    assert not out["strategic_quality_assessed"]
    assert not out["causal_mechanism_assessed"]


def test_full_pool_reorders_actions_columns_rows_and_preserves_multiplicity():
    args = (
        [["BJ"], ["S2", "S2"], ["H2"]], [["H2"], ["BJ"]], [["S2", "S2"], ["H2"]],
        [[1, 2, 4], [5, 2, 4]],
    )
    original = copy.deepcopy(args)
    out = summarize_full_pool_matrix(*args)
    permuted = summarize_full_pool_matrix(
        [["H2"], ["BJ"], ["S2", "S2"]], [["BJ"], ["H2"]], [["H2"], ["S2", "S2"]],
        [[4, 5, 2], [4, 1, 2]],
    )
    assert out == permuted
    assert args == tuple(original)
    assert out["actions"] == [["S2", "S2"], ["H2"], ["BJ"]]


def test_unique_full_pool_best_can_be_absent_from_both_ballots():
    out = summarize_full_pool_matrix(
        [["S2"], ["H2"], ["BJ"]], [["H2"]], [["BJ"]],
        [[9, 2, 3], [9, 2, 3]],
    )
    assert out["full_pool"]["exact_maximizers"] == [["S2"]]
    assert out["control"]["any_maximum_available"] is False
    assert out["treatment"]["any_maximum_available"] is False
    assert out["union"]["selected_action"] == ["BJ"]


@pytest.mark.parametrize("bad", [
    lambda: summarize_full_pool_matrix([], [["S2"]], [["S2"]], [[1]]),
    lambda: summarize_full_pool_matrix([["S2"]], [], [["S2"]], [[1]]),
    lambda: summarize_full_pool_matrix([["S2"]], [["S2"]], [], [[1]]),
    lambda: summarize_full_pool_matrix([["S2"], ["S2"]], [["S2"]], [["S2"]], [[1, 2]]),
    lambda: summarize_full_pool_matrix([["S2", "H2"], ["H2", "S2"]], [["S2", "H2"]], [["H2", "S2"]], [[1, 2]]),
    lambda: summarize_full_pool_matrix([["S2"]], [["H2"]], [["S2"]], [[1]]),
    lambda: summarize_full_pool_matrix([["S2"]], [["S2"]], [["S2"]], []),
    lambda: summarize_full_pool_matrix([["S2"]], [["S2"]], [["S2"]], [[1], [2, 3]]),
    lambda: summarize_full_pool_matrix([["S2"]], [["S2"]], [["S2"]], [[True]]),
    lambda: summarize_full_pool_matrix([["S2"]], [["S2"]], [["S2"]], [[math.inf]]),
])
def test_refuses_invalid_inputs(bad):
    with pytest.raises(ValueError):
        bad()


def test_refuses_derived_gap_overflow():
    with pytest.raises(ValueError):
        summarize_full_pool_matrix(
            [["S2"], ["H2"]], [["S2"]], [["S2"]],
            [[-1e308, 1e308]],
        )


def test_single_action_ballots_have_zero_gap_and_all_availability():
    out = summarize_full_pool_matrix(
        [["S2"], ["H2"]], [["S2"]], [["S2"]], [[7, 3]],
    )
    assert out["full_pool"]["exact_maximizers"] == [["S2"]]
    assert out["control"]["predicted_value_gap_to_full_maximum"] == 0.0
    assert out["control"]["any_maximum_available"]
    assert out["control"]["all_maximum_available"]
