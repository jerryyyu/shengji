import copy
import math

import pytest

from shengji.eval.ballot_matrix import summarize_ballot_matrix


def test_hand_computable_summary_and_paired_difference():
    actions = [["S2"], ["H5"], ["BJ"]]
    out = summarize_ballot_matrix(
        actions, [["S2"], ["H5"]], [["H5"], ["BJ"]],
        [[1, 4, 2], [3, 2, 5], [5, 0, 8]],
    )
    assert out["world_count"] == 3 and out["action_count"] == 3
    assert out["action_means"] == [3.0, 2.0, 5.0]
    assert out["control"] == {
        "selected_action": ["S2"], "selected_mean": 3.0,
        "gap_to_runner_up": 1.0, "tied_best_count": 1,
    }
    assert out["treatment"]["selected_action"] == ["BJ"]
    assert out["union"]["selected_action"] == ["BJ"]
    assert out["paired_selected_action_difference"] == {
        "mean": 2.0, "se": pytest.approx(1 / math.sqrt(3)),
    }
    assert not out["union_best_available_in_control"]
    assert out["union_best_available_in_treatment"]


def test_same_ballot_sets_same_choice_and_multiplicity_is_preserved():
    out = summarize_ballot_matrix(
        [["S2", "S2"], ["BJ"]], [["S2", "S2"], ["BJ"]],
        [["BJ"], ["S2", "S2"]], [[2, 4], [6, 0]],
    )
    assert out["control"]["selected_action"] == ["S2", "S2"]
    assert out["treatment"]["selected_action"] == ["S2", "S2"]
    assert out["actions"][0] == ["S2", "S2"]
    assert out["actions"][1] == ["BJ"]


@pytest.mark.parametrize("bad", [
    lambda: summarize_ballot_matrix([["S2"], ["S2"]], [["S2"]], [["S2"]], [[1, 2]]),
    lambda: summarize_ballot_matrix([["S2", "H2"], ["H2", "S2"]],
                                    [["S2", "H2"]], [["H2", "S2"]], [[1, 2]]),
    lambda: summarize_ballot_matrix([["S2"]], [["S2"], ["S2"]], [["S2"]], [[1]]),
    lambda: summarize_ballot_matrix([["S2"]], [["S2"]], [["H2"]], [[1]]),
    lambda: summarize_ballot_matrix([["S2"], ["H2"]], [["S2"]], [["S2"]], [[1, 2]]),
    lambda: summarize_ballot_matrix([["NOPE"]], [["NOPE"]], [["NOPE"]], [[1]]),
    lambda: summarize_ballot_matrix([], [["S2"]], [["S2"]], [[1]]),
    lambda: summarize_ballot_matrix([["S2"]], [], [["S2"]], [[1]]),
    lambda: summarize_ballot_matrix([["S2"]], [["S2"]], [["S2"]], [(1,)]),
])
def test_duplicate_missing_and_extraneous_actions_refused(bad):
    with pytest.raises(ValueError):
        bad()


@pytest.mark.parametrize("worlds", [
    [], [[1]], [[1], [2, 3]], [[1, math.inf]], [[1, math.nan]], [[True, 0]],
])
def test_world_matrix_shape_and_values_are_strict(worlds):
    with pytest.raises(ValueError):
        summarize_ballot_matrix([["S2"], ["H2"]], [["S2"]], [["H2"]], worlds)


def test_single_world_and_single_action_margins():
    out = summarize_ballot_matrix([["S2"]], [["S2"]], [["S2"]], [[7]])
    assert out["control"]["gap_to_runner_up"] is None
    assert out["paired_selected_action_difference"] == {"mean": 0.0, "se": None}


def test_permutations_ties_and_rows_are_invariant():
    args = ([["H2"], ["S2"], ["BJ"]], [["S2"], ["H2"]], [["BJ"], ["H2"]],
            [[5, 5, 1], [5, 5, 9]])
    a = summarize_ballot_matrix(*args)
    b = summarize_ballot_matrix(
        [["BJ"], ["S2"], ["H2"]], [["H2"], ["S2"]], [["H2"], ["BJ"]],
        [[9, 5, 5], [1, 5, 5]],
    )
    # The second matrix permutes columns, ballots, and rows.  Canonical S2
    # wins the exact three-way tie.
    assert a == b
    assert a["union"]["selected_action"] == ["S2"]
    assert a["union"]["tied_best_count"] == 3


def test_common_huge_effect_cancels_and_inputs_are_not_mutated():
    actions = [["S2"], ["H2"]]
    control = [["S2"]]
    treatment = [["H2"]]
    worlds = [[1e200, 1e200 + 1e185], [1e200, 1e200 + 1e185]]
    original = copy.deepcopy((actions, control, treatment, worlds))
    out = summarize_ballot_matrix(actions, control, treatment, worlds)
    expected_delta = worlds[0][1] - worlds[0][0]
    assert out["paired_selected_action_difference"]["mean"] == pytest.approx(
        expected_delta)
    assert out["paired_selected_action_difference"]["se"] == 0.0
    assert (actions, control, treatment, worlds) == original


def test_derived_overflow_is_refused():
    with pytest.raises(ValueError):
        summarize_ballot_matrix([["S2"], ["H2"]], [["S2"]], [["H2"]],
                                [[1e308, -1e308]])


def test_column_mean_overflow_is_refused():
    with pytest.raises(ValueError):
        summarize_ballot_matrix([["S2"], ["H2"]], [["S2"]], [["H2"]],
                                [[1e308, 1e308], [1e308, 1e308]])


def test_paired_se_overflow_is_refused():
    with pytest.raises(ValueError):
        summarize_ballot_matrix([["S2"], ["H2"]], [["S2"]], [["H2"]],
                                [[1e308, 0.0], [-1e308, 0.0]])
