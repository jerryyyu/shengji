"""Production inference parity, from COMMITTED fixtures (Codex P1).

Prod runs the numpy mirror (`rl/npnet.py`) because the image ships without
torch — so every strength number, all of which were measured under torch, is
only meaningful if the numpy path computes the same thing. The existing
parity test passed only because of untracked local checkpoints, which means it
was green on machines where it proved nothing.

The fixture here is committed: real decision states, their candidate ballots,
and the values torch produced for them. It fails on any machine where the
numpy path drifts, with or without torch installed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

FIX = Path(__file__).parent / "fixtures" / "npnet_v11pair.npz"
NPZ = Path(__file__).resolve().parents[1] / "snapshots_v11pair" / "ep07.npz"

# Prod tolerance: float32 matmul reassociation, nothing larger.
ATOL = 1e-4


def _load():
    if not FIX.exists():
        pytest.skip("parity fixture missing")
    if not NPZ.exists():
        pytest.skip("v11pair numpy weights not present")
    from shengji.rl.npnet import NpNet

    return np.load(FIX, allow_pickle=False), NpNet(str(NPZ))


def test_npnet_matches_committed_torch_values():
    d, net = _load()
    obs, acts, off, exp = d["obs"], d["actions"], d["offsets"], d["expected"]
    worst = 0.0
    for i in range(len(obs)):
        a, b = int(off[i]), int(off[i + 1])
        got = np.asarray(net.value_candidates(obs[i], list(acts[a:b])),
                         dtype=np.float64)
        want = exp[a:b].astype(np.float64)
        worst = max(worst, float(np.max(np.abs(got - want))))
    assert worst < ATOL, f"numpy inference drifted from torch by {worst:.2e}"


def test_npnet_preserves_the_deployed_decision():
    """Values may wobble in the last bits; the CHOSEN action may not."""
    d, net = _load()
    obs, acts, off, exp = d["obs"], d["actions"], d["offsets"], d["expected"]
    for i in range(len(obs)):
        a, b = int(off[i]), int(off[i + 1])
        got = np.asarray(net.value_candidates(obs[i], list(acts[a:b])),
                         dtype=np.float64)
        want = exp[a:b].astype(np.float64)
        # The override gates on deltas against candidate 0, so compare those.
        assert int(np.argmax(got - got[0])) == int(np.argmax(want - want[0])), \
            f"decision {i} differs between numpy and torch"


def test_fixture_encoding_version_matches_code():
    """A fixture built under a different encoder proves nothing."""
    d, _ = _load()
    from shengji.rl.encode import ENC_VERSION

    assert int(d["enc_version"]) == ENC_VERSION, (
        "fixture was built with a different ENC_VERSION — regenerate it and "
        "re-verify the checkpoint rather than relaxing this assert")
