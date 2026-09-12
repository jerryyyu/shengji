"""The optional native loop must preserve stdlib erf and full probabilities."""
import math
import subprocess
import sys

import numpy as np
import pytest

from shengji.ai import cwv_numpy
from tests.test_cwv_numpy import _weights


def test_fresh_runtime_keeps_pure_fallback_when_extension_is_absent():
    code = """
import sys, math, numpy as np
sys.modules['shengji.ai._cwv_math'] = None
from shengji.ai import cwv_numpy
assert cwv_numpy._native_erf is None
assert 'torch' not in sys.modules
x = np.array([-3., -0., 0., 2.])
want = (x * (1 + np.vectorize(math.erf, otypes=[np.float64])(x / math.sqrt(2))) * .5).astype(np.float64)
assert cwv_numpy._gelu_exact(x).tobytes() == want.tobytes()
"""
    subprocess.run([sys.executable, '-c', code], check=True, timeout=30)


def test_native_erf_matches_stdlib_bits_and_keeps_input():
    native = pytest.importorskip('shengji.ai._cwv_math')
    values = np.concatenate((np.random.default_rng(12).normal(0, 5, 100000),
                             [0., -0., 1e-300, -1e-300, np.inf, -np.inf]))
    for x in (values, values[::-2], values.astype(np.float32)):
        before = x.tobytes()
        expected = np.vectorize(math.erf, otypes=[np.float64])(x)
        actual = native.erf_array(x)
        assert actual.dtype == np.float64
        assert actual.shape == x.shape
        assert actual.tobytes() == expected.tobytes()
        assert x.tobytes() == before
    assert native.erf_array(np.empty((0, 4))).shape == (0, 4)


@pytest.mark.parametrize('version,width', [(1, 532), (2, 561)])
def test_full_probabilities_exact_with_native_or_fallback(monkeypatch, version, width):
    native = pytest.importorskip('shengji.ai._cwv_math')
    cfg = cwv_numpy.CWVNumpyConfig('mlp', 32, 64, width, version)
    model = cwv_numpy.CWVNumpyMLP(cfg, _weights(cfg))
    rng = np.random.default_rng(17)
    public = rng.normal(size=(128, width)).astype('f4')
    world = rng.normal(size=(128, 5, 54)).astype('f4')
    perspective = np.tile(np.array([[1., 0.]], dtype='f4'), (128, 1))
    monkeypatch.setattr(cwv_numpy, '_native_erf', None)
    expected = model.probabilities(public, world, perspective)
    calls = []

    def counted(x):
        calls.append(x.shape)
        return native.erf_array(x)

    monkeypatch.setattr(cwv_numpy, '_native_erf', counted)
    actual = model.probabilities(public, world, perspective)
    assert calls == [(128, 64), (128, 32)]
    assert actual.tobytes() == expected.tobytes()
