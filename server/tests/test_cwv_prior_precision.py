"""Wide-ballot normalization repair preserves accepted prior probability bytes."""
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from shengji.ai.cwv_policy import CWVError
from shengji.ai.cwv_puct import PublicPriorHead
from shengji.rl.encode import ACT_DIM


class LogitsModel:
    def __init__(self, logits):
        self.logits = logits

    def __call__(self, obs, cand, mask):
        return SimpleNamespace(logits=self.logits)


def head(logits):
    result = object.__new__(PublicPriorHead)
    result.model = LogitsModel(logits)
    result.forward_calls = result.rows = 0
    result.wall_secs = 0.0
    return result


def rows(*widths):
    return [(np.zeros(531, np.float32), np.zeros((w, ACT_DIM), np.float32))
            for w in widths]


def test_accepted_probability_bytes_are_unchanged():
    logits = torch.tensor([[1., 2., 3.], [-2., 1., -torch.inf]])
    expected = torch.softmax(logits, dim=1).double().numpy()
    actual = head(logits).batch_from_encoded(rows(3, 2))
    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1, :2].tobytes()


def test_wide_finite_roundoff_retries_in_double_and_preserves_order(monkeypatch):
    logits = torch.linspace(-29.2576675, 1.9766083, 82956).reshape(1, -1)
    real = torch.softmax
    calls = []

    def softmax(value, dim):
        calls.append(value.dtype)
        answer = real(value, dim=dim)
        # Reproduce the measured float32 reduction error independently of
        # whether this host's torch kernel happens to have the same error.
        return answer * 1.00002 if value.dtype == torch.float32 else answer

    monkeypatch.setattr(torch, "softmax", softmax)
    actual = head(logits).batch_from_encoded(rows(82956))[0]
    assert calls == [torch.float32, torch.float64]
    assert actual.tobytes() == real(logits[0].double(), dim=0).numpy().tobytes()
    assert abs(actual.sum() - 1) < 1e-12
    assert np.all(np.diff(actual) > 0)


@pytest.mark.parametrize("logits,widths", [
    ([[float('nan'), 0.]], (2,)),
    ([[float('inf'), 0.]], (2,)),
    ([[-float('inf'), -float('inf')]], (2,)),
    # A malformed producer leaves positive probability on padded actions.
    # The fallback must NOT simply normalize the truncated prefix.
    ([[0., 0.], [0., 0.]], (1, 2)),
])
def test_precision_fallback_does_not_hide_invalid_outputs(logits, widths):
    with pytest.raises(CWVError, match="^prior head probability drift$"):
        head(torch.tensor(logits)).batch_from_encoded(rows(*widths))
