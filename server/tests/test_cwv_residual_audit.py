import numpy as np
import pytest

from shengji.train.cwv_residual_audit import (
    action_gaps, corrected_gaps, gap_moments, held_world_comparison,
)


def test_action_common_offset_cancels_but_action_bias_is_corrected():
    y = np.array([[1., 3.], [2., 6.], [3., 3.], [4., 2.]])
    x = y + np.arange(4)[:, None] + np.array([0., 7.])
    moments = gap_moments(x, y)
    assert moments["mean_absolute_model_gap_bias"] == 7.
    assert moments["mean_residual_gap_variance"] == 0.
    assert moments["residual_variance_ratio"] == 0.
    np.testing.assert_array_equal(corrected_gaps(x[:2], x[2:], y[2:]),
                                  action_gaps(y[:2]).mean(0))


def test_constant_model_reduces_exactly_to_plain_mc():
    y = np.array([[0., 1.], [0., -3.], [0., 5.], [0., 2.]])
    x = np.tile([17., -4.], (4, 1))
    assert gap_moments(x, y)["residual_variance_ratio"] == 1.
    np.testing.assert_array_equal(corrected_gaps(x[:2], x[2:], y[2:]),
                                  action_gaps(y[2:]).mean(0))


def test_anti_predictor_makes_residual_variance_four_times_worse():
    y = np.array([[0., 1.], [0., -3.], [0., 5.], [0., 2.]])
    result = gap_moments(-y, y)
    assert result["residual_variance_ratio"] == 4.
    assert result["mean_gap_covariance"] == -result["mean_rollout_gap_variance"]


def test_held_world_wiring_uses_disjoint_reference_cheap_and_paired_rows():
    rng = np.random.default_rng(37)
    y = rng.normal(size=(1024, 3))
    x = y + np.array([0., 10., -5.])
    got = held_world_comparison(x, y, seed=5, repetitions=1)
    p = np.random.default_rng(5).permutation(1024)
    ref, cheap, paired = p[:512], p[512:896], p[896:]
    assert not set(ref) & set(cheap) and not set(ref) & set(paired)
    assert not set(cheap) & set(paired)
    target, model = action_gaps(y[ref]).mean(0), action_gaps(y[cheap]).mean(0)
    expected = float(np.square(model[1:] - target[1:]).mean())
    assert got["corrected_32"]["gap_mse"] == pytest.approx(expected, abs=1e-13)
    assert got["corrected_128"]["gap_mse"] == pytest.approx(expected, abs=1e-13)
    assert got["model_384"]["gap_mse"] > 50
    raw = action_gaps(y[paired[:32]]).mean(0)
    assert got["mc_32"]["gap_mse"] == pytest.approx(float(np.square(raw[1:] - target[1:]).mean()))


def test_noiseless_fixed_action_values_choose_correct_move():
    y = np.tile([0., -1., 2.], (1024, 1))
    got = held_world_comparison(y, y, seed=0)
    for arm in got.values():
        assert arm == dict(gap_mse=0., reference_regret=0., reference_lift_vs_incumbent=2.)
    assert gap_moments(y, y)["residual_variance_ratio"] is None


@pytest.mark.parametrize("bad", [np.ones((3,)), [[0., float('nan')], [1., 2.]], [[1., 2.]]])
def test_malformed_matrix_refuses(bad):
    with pytest.raises(ValueError, match="^expected finite world-by-action matrix"):
        action_gaps(bad)


def test_shape_and_incumbent_refuse():
    with pytest.raises(ValueError, match="^paired world/action shape mismatch$"):
        corrected_gaps(np.ones((4, 3)), np.ones((2, 3)), np.ones((3, 3)))
    with pytest.raises(ValueError, match="^invalid incumbent column$"):
        action_gaps(np.ones((4, 3)), True)
    with pytest.raises(ValueError, match="^expected paired 1024-world matrices$"):
        held_world_comparison(np.ones((64, 3)), np.ones((64, 3)), seed=1)
