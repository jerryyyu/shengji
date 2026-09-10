import math

import numpy as np
import pytest

from shengji.train.r4_w32_capture import RecordingEvaluator, replay_consumer_means
from shengji.train.r4_w32_weight_diagnostic import cell_count, marginal_energies, shortlist


def test_recording_wrapper_preserves_exact_batches_values_and_cache():
    cache = object()
    values = np.array([1.25, -2.5])
    class Evaluator:
        def score(self, positions, seat, *, tensor_cache):
            assert positions == ["first", "second"] and seat == 3
            assert tensor_cache is cache
            return values
    recording = RecordingEvaluator(Evaluator())
    assert recording.score(["first", "second"], 3, tensor_cache=cache) is values
    assert recording.values == [1.25, -2.5]


def test_matrix_replay_uses_sequential_consumer_reduction_not_pairwise_sum():
    values = np.random.default_rng(12).normal(size=(32, 1))
    sums = np.zeros(1)
    for batch in np.array_split(values, 4):
        np.add.at(sums, [0]*len(batch), batch[:, 0])
    assert np.array_equal(replay_consumer_means(values), sums/32)
    assert not np.array_equal(values.sum(axis=0)/32, sums/32)


def test_relative_receivers_and_kitty_do_not_alias():
    world = ([["S2"], [], ["S2", "S2"], []], ["H2"])
    assert cell_count(world, 1, "S2", "seat-relative-1") == 2
    assert cell_count(world, 1, "S2", "seat-relative-3") == 1
    assert cell_count(world, 1, "H2", "hidden-kitty") == 1
    with pytest.raises(ValueError, match="unexpected hidden receiver"):
        cell_count(world, 1, "S2", "seat-relative-0")


def test_marginal_energy_has_exact_direction_and_jeffreys_denominator():
    zero = ([[], [], [], []], [])
    one = ([[], ["S2"], [], []], [])
    ownership = {"count_probabilities": [{"card": "S2", "receiver": "seat-relative-1",
                                         "count_probability_ppb": [250000000, 750000000, 0]}]}
    scores = marginal_energies(ownership, [zero, one], [zero]*128 + [one]*128, 0)
    assert scores == tuple(round(math.log(p / (128.5/257.5))*1e9) for p in (.25, .75))
    assert scores[1] > scores[0]
    with pytest.raises(ValueError, match="256-world reference"):
        marginal_energies(ownership, [one], [zero]*32, 0)


def test_incumbent_is_retained_and_ties_follow_actual_lexical_shortlist():
    assert shortlist([["S2"], ["H2"], ["D2"]], [10, -20, 10], ["H2"], 1) == [1, 2]


def test_invalid_probabilities_fail_before_weights_are_computed():
    w = ([[], [], [], []], [])
    row = {"card": "S2", "receiver": "seat-relative-1", "count_probability_ppb": [1, 2, 3]}
    with pytest.raises(ValueError, match="invalid marginal probability mass"):
        marginal_energies({"count_probabilities": [row]}, [w], [w]*256, 0)
