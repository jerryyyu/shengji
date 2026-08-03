"""Numpy inference must match torch bit-for-bit-ish (float32 tolerance).

Production runs the numpy path (no torch in the image), so any drift
here silently changes how the deployed bot plays.
"""
import sys

import numpy as np
import pytest

sys.path.insert(0, ".")

pytest.importorskip("torch")
from shengji.rl.model import load_any_net  # noqa: E402
from shengji.rl.npnet import NpNet  # noqa: E402
from shengji.rl.encode import ACT_DIM, OBS_DIM  # noqa: E402


def test_npnet_matches_torch():
    t = load_any_net("snapshots_v7w/ep02.pt")
    n = NpNet("weights_v7w_ep02.npz")
    rng = np.random.default_rng(0)
    for trial in range(200):
        k = int(rng.integers(1, 20))
        obs = rng.standard_normal(OBS_DIM).astype(np.float32)
        acts = rng.standard_normal((k, ACT_DIM)).astype(np.float32)
        tv = np.asarray(t.value_candidates(obs, acts)).ravel()
        nv = np.asarray(n.value_candidates(obs, acts)).ravel()
        assert np.allclose(tv, nv, atol=2e-4), (
            f"value head drift at trial {trial}: max {np.abs(tv-nv).max()}")
        tp = np.asarray(t.score_candidates(obs, acts)).ravel()
        np_ = np.asarray(n.score_candidates(obs, acts)).ravel()
        assert np.allclose(tp, np_, atol=2e-4), "policy head drift"
        # the decision itself must be identical, not just close
        assert int(tv.argmax()) == int(nv.argmax())
        assert int(tp.argmax()) == int(np_.argmax())
