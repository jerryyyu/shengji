import numpy as np
import pytest

from shengji.train.simple_belief_features import actor_features, ownership_targets
from shengji.train.simple_belief_reference import corrected_reference, empirical_count_probabilities
from test_banker_kitty_sampler import declared_round


def test_brier_correction_has_exact_nonzero_witness():
    counts = np.zeros((2, 4, 54), dtype=np.int64)
    counts[1] = 1
    p, correction = empirical_count_probabilities(counts)
    np.testing.assert_array_equal(p[..., :2], np.full((4, 54, 2), .5))
    np.testing.assert_array_equal(correction, np.full((4, 54), .5))
    # Averaging every two-draw outcome for calibrated Bernoulli(.5) gives
    # true expected Brier .5, whereas uncorrected empirical Brier is .75.
    raw, adjusted = [], []
    for first, second in ((0, 0), (0, 1), (1, 0), (1, 1)):
        c = np.full((2, 4, 54), first, dtype=np.int64)
        c[1] = second
        prob, bias = empirical_count_probabilities(c)
        for truth in (0, 1):
            score = np.square(prob-np.eye(3)[truth]).sum(axis=-1)
            raw.append(score.mean())
            adjusted.append((score-bias).mean())
    assert np.mean(raw) == .75 and np.mean(adjusted) == .5
    with pytest.raises(ValueError, match='at least two'):
        empirical_count_probabilities(counts[:1])


def test_real_corrected_sampler_matches_new_mask_and_known_kitty():
    rnd, code = declared_round()
    ref = corrected_reference(rnd, 1, seed=93, n=64)
    _, mask = actor_features(rnd, 1)
    assert np.all(ref['probabilities'][~mask] == 0)
    assert ref['unique_worlds'] > 1
    assert ref['attempts'] >= ref['worlds'] == 64
    # A banker is entitled to know their own burial, never to redraw it.
    own = corrected_reference(rnd, 0, seed=95, n=16)
    np.testing.assert_array_equal(own['probabilities'][3], np.eye(3)[ownership_targets(rnd, 0)[3]])
    assert not own['brier_correction'][3].any()
