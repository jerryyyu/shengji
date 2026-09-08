"""Torch-free public-history extraction parity and import-boundary tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from shengji.rl import douzero_micro
from shengji.rl.public_history import (
    HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS, PublicHistoryError,
    encode_public_history,
)
from tests.test_cwv_static_public import _state_after


@pytest.mark.parametrize("plies", [1, 24, 48, 72])
def test_public_history_matches_legacy_for_every_seat(plies):
    rnd = _state_after(73, plies)
    for seat in range(4):
        expected = douzero_micro.encode_public_history(rnd, seat)
        actual = encode_public_history(rnd, seat)
        assert np.array_equal(actual, expected)
        assert actual.shape[1] == HISTORY_EVENT_DIM


def test_public_history_errors_keep_messages_and_value_error_base():
    rnd = _state_after(73, 24)
    rnd.history[0].plays[0].seat = 4
    with pytest.raises(PublicHistoryError, match="^invalid public trick event$"):
        encode_public_history(rnd, 0)

    rnd = _state_after(73, 24)
    rnd.history[0].plays[0].cards[0] = "not-a-card"
    with pytest.raises(PublicHistoryError, match="^unknown public card code"):
        encode_public_history(rnd, 0)

    rnd = _state_after(73, 24)
    for _ in range(HISTORY_MAX_EVENTS + 1):
        rnd.history[0].plays.append(rnd.history[0].plays[0])
    with pytest.raises(PublicHistoryError,
                       match=r"^public history has \d+ events; cap is 100$"):
        encode_public_history(rnd, 0)
    assert issubclass(PublicHistoryError, ValueError)


def test_public_history_imports_without_torch():
    root = Path(__file__).resolve().parents[1]
    code = ("import builtins; real=builtins.__import__; "
            "builtins.__import__=lambda n,*a,**k: (_ for _ in ()).throw(" 
            "RuntimeError('torch import blocked')) if n == 'torch' or "
            "n.startswith('torch.') else real(n,*a,**k); "
            "from shengji.rl.public_history import encode_public_history, "
            "HISTORY_EVENT_DIM; assert callable(encode_public_history) and "
            "HISTORY_EVENT_DIM == 64")
    result = subprocess.run([sys.executable, "-c", code], cwd=root,
                            check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
