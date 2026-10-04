"""Handwritten witnesses plus direct parity against the existing served hook."""
import copy
import random

import numpy as np
import pytest

from shengji.eval.ballot_points_selection import summarize_points_selection
from shengji.train.policy_value_search import PolicyValueBot, TIEBREAK_DEFAULTS


ACTIONS = [["S3"], ["S2"], ["S4"]]  # deliberately not canonical order


def test_default_epsilon_matches_production():
    assert TIEBREAK_DEFAULTS["tiebreak_epsilon"] == 0.02
    result = summarize_points_selection([["S3"]], [.5], [[0]])
    assert result["epsilon"] == TIEBREAK_DEFAULTS["tiebreak_epsilon"]


@pytest.mark.parametrize("means,points,expected,near", [
    ([0.5, 0.49, 0.1], [[-20, -10, 200]], 1, [0, 1]),
    ([0.5, 0.5, 0.1], [[10, 10, 200]], 0, [0, 1]),
    ([0.49, 0.5, 0.49], [[10, 10, 10]], 1, [0, 1, 2]),
    ([0.49, 0.5, 0.49], [[20, 10, 20]], 0, [0, 1, 2]),
    ([0.5, 0.5 - 0.02, 0.1], [[0, 10, 200]], 1, [0, 1]),
    ([0.5, np.nextafter(0.48, -np.inf).item(), 0.1], [[0, 10, 200]], 0, [0]),
    ([0.5, 0.49, 0.1], [[10, 20, 0], [10, -20, 0]], 0, [0, 1]),
])
def test_handwritten_and_served_parity(means, points, expected, near):
    original = copy.deepcopy((ACTIONS, means, points))
    result = summarize_points_selection(ACTIONS, means, points)
    assert result["selected_index"] == expected
    assert result["near_indices"] == near
    assert (ACTIONS, means, points) == original
    assert_served_parity(ACTIONS, means, points, result)


def assert_served_parity(actions, means, points, result):
    # Actual production selection code, but point evidence supplied directly:
    # this tests selector semantics, NOT engine/leaf/world provenance.
    bot = object.__new__(PolicyValueBot)
    bot.tiebreak_points = True
    bot.lead_tiebreak_prior = False
    bot.tiebreak_epsilon = 0.02
    bot._trick_points = lambda rnd, seat, hands, buried, action, world_index: (
        points[world_index][actions.index(action)])
    actual = bot._select(None, 0, actions, np.asarray(means),
                         worlds=[(None, None)] * len(points))
    assert result["raw_index"] == int(np.argmax(means))
    assert result["selected_index"] == actual
    assert result["near_indices"] == bot._tiebreak["tiebreak_near_set"]
    assert result["near_point_means"] == bot._tiebreak["tiebreak_points"]
    assert result["changed"] == bot._tiebreak["tiebreak_applied"]


def test_seeded_selector_parity_and_admission_order():
    rng = random.Random(512)
    for _ in range(100):
        actions = copy.deepcopy(ACTIONS)
        rng.shuffle(actions)
        means = [rng.choice([0.5, 0.49, 0.48, 0.47]) for _ in actions]
        points = [[rng.choice([-20, -10, 0, 10, 20]) for _ in actions]
                  for _ in range(4)]
        result = summarize_points_selection(actions, means, points)
        assert_served_parity(actions, means, points, result)


def test_singleton_reports_no_rebuild_and_keeps_card_multiplicity():
    result = summarize_points_selection([["S3", "S3"]], [.5], [[10]])
    assert result["actions"] == [["S3", "S3"]]
    assert result["near_point_means"] == []
    assert result["selected_index"] == result["raw_index"] == 0
    assert result["conditional_on_complete_rebuild"]
    assert not result["serving_deadline_assessed"]


@pytest.mark.parametrize("actions", [[], [["bad"]], [["S3"], ["S3"]],
                                      [["S3", "S4"], ["S4", "S3"]]])
def test_refuse_invalid_or_duplicate_actions(actions):
    with pytest.raises(ValueError):
        summarize_points_selection(actions, [.5] * len(actions), [[0] * len(actions)])


@pytest.mark.parametrize("means,points,epsilon", [
    ([True, 0, 0], [[0, 0, 0]], .02),
    ([float("nan"), 0, 0], [[0, 0, 0]], .02),
    ([0, 0], [[0, 0, 0]], .02),
    ([0, 0, 0], [], .02),
    ([0, 0, 0], [[0, 0]], .02),
    ([0, 0, 0], [[0, True, 0]], .02),
    ([0, 0, 0], [[0, 1.0, 0]], .02),
    ([0, 0, 0], [[0, None, 0]], .02),
    ([0, 0, 0], [[0, 0, 0]], -.02),
    ([0, 0, 0], [[0, 0, 0]], True),
    ([0, 0, 0], [[0, 0, 0]], float("inf")),
    ([-1e308] * 3, [[0, 0, 0]], 1e308),
])
def test_refuse_incomplete_or_invalid(means, points, epsilon):
    with pytest.raises(ValueError):
        summarize_points_selection(ACTIONS, means, points, epsilon=epsilon)
