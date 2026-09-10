import numpy as np
import pytest

from shengji.train.world_mixture_fit import fit_world_mixture, reweighted_consumer_means


def test_exact_feasible_marginal_fit_and_uniform_control():
    counts = np.array([[0], [0], [1], [1]])
    uniform = fit_world_mixture(counts, [[.5,.5,0]])
    assert np.allclose(uniform['weights'], [.25]*4)
    fitted = fit_world_mixture(counts, [[.75,.25,0]])
    assert np.allclose(fitted['weights'], [.375,.375,.125,.125], atol=1e-7)
    assert fitted['guarded_fit_model_squared_error'] < 1e-12


def test_concentrated_target_hits_ess_guard_without_invalid_worlds():
    counts = np.array([[1]]*4 + [[0]]*12)
    fitted = fit_world_mixture(counts, [[0,1,0]])
    w = np.array(fitted['weights'])
    assert w.shape == (16,) and (w>=0).all() and abs(w.sum()-1)<1e-9
    assert w.max() <= 4/16+1e-9
    assert fitted['ess_fraction'] >= .5-1e-9
    assert fitted['uniform_mix_fit_fraction'] < 1
    assert fitted['guarded_fit_model_squared_error'] < fitted['uniform_model_squared_error']


def test_unrepresentable_target_reported_not_invented():
    fitted = fit_world_mixture(np.zeros((4,2), dtype=int), [[0,1,0],[0,0,1]])
    assert np.allclose(fitted['weights'], [.25]*4)
    assert fitted['guarded_fit_model_squared_error'] == 2


def test_permuting_worlds_only_permutates_weights():
    counts = np.array([[0,1],[1,0],[2,1],[1,1],[0,0],[2,0]])
    probs = [[.2,.3,.5],[.6,.4,0]]
    a = fit_world_mixture(counts, probs)
    order = [3,0,4,1,5,2]
    b = fit_world_mixture(counts[order], probs)
    assert np.allclose(np.array(a['weights'])[order], b['weights'], atol=1e-9)


def test_wrong_inputs_and_iteration_limit():
    with pytest.raises(ValueError, match='invalid world count matrix'):
        fit_world_mixture([[0],[3]], [[.5,.5,0]])
    with pytest.raises(ValueError, match='invalid model count probabilities'):
        fit_world_mixture([[0],[1]], [[float('nan'),.5,0]])
    result = fit_world_mixture([[0],[0],[1]], [[.1,.9,0]], iterations=1)
    assert not result['converged'] and result['iterations'] == 1


def test_max_weight_cap_can_bind_without_ess_guard():
    fitted = fit_world_mixture(np.array([[1]]+[[0]]*15), [[0,1,0]])
    assert abs(fitted['weights'][0]-.25) < 1e-8
    assert fitted['uniform_mix_fit_fraction'] == 1


def test_uniform_mixture_preserves_consumer_arithmetic_exactly():
    values = np.array([[1e16,2.], [1.,3.], [-1e16,4.]])
    # Original sequential summation, which need not equal a BLAS dot product.
    baseline = np.zeros(2)
    for row in values:
        baseline += row
    baseline /= 3
    actual = reweighted_consumer_means(values, np.full(3,1/3), baseline)
    assert np.array_equal(actual,baseline)
    assert np.allclose(reweighted_consumer_means([[1,2],[3,4]], [.25,.75],[2,3]),[2.5,3.5])
