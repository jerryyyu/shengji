"""Actual-consumer witnesses for reuse of v1 public unseen counts."""
import copy

import numpy as np
import pytest

from scripts import cwv_prepared_lead_probe as probe
from shengji.ai import cwv_static_encoding as static
from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.ai.memory import Memory
from shengji.engine.cards import Ordering
from shengji.rl import encode_versions
from shengji.rl import value_afterstate_v2 as v2
from tests.test_cwv_v2_static_widen import _state_after, _v2_model


def test_actual_evaluator_does_not_rebuild_memory_for_v2_columns(monkeypatch):
    rnd = _state_after(65, 35)
    model = _v2_model()
    expected = CompleteWorldEvaluator(None, model=model, encoding="reference").score([rnd], rnd.turn)

    def tripwire(*_args, **_kwargs):
        raise AssertionError("v2 rebuilt unused Memory deductions")

    monkeypatch.setattr(encode_versions, "Memory", tripwire)
    evaluator = CompleteWorldEvaluator(None, model=model, encoding="mlp-static")
    actual = evaluator.score([rnd], rnd.turn)
    np.testing.assert_array_equal(actual, expected)
    assert evaluator.model_rows == 1
    # Disconnect the optimization at the actual call site. Keeping the pure
    # feature helper correct must not let this old-wiring mutation pass.
    monkeypatch.setattr(static, "_widen_v2_static", static.widen_v2)
    with pytest.raises(AssertionError, match="^v2 rebuilt unused Memory deductions$"):
        evaluator.score([rnd], rnd.turn)


def test_banker_unseen_counts_keep_private_kitty_in_historical_v1_plane():
    rnd = _state_after(61, 35)
    suit = next(card[0] for card in rnd.buried if card[0] in "SHDC")
    rnd.trump_suit, rnd.trump_rank, rnd.trump_is_nt = suit, "7", False
    rnd.ordering = Ordering(suit, "7")
    seat = rnd.banker
    historical = Memory(rnd, seat, own_kitty=False).unseen_trumps()
    private = Memory(rnd, seat, own_kitty=True).unseen_trumps()
    assert historical > private, "fixture must contain buried trump cards"
    actual = static.tensors_from_round_static(rnd, seat, version=2)
    expected = v2.tensors_from_round(rnd, seat, version=2)
    assert actual.public[531 + 26] == np.float32(historical / 27.0)
    assert actual.public[531 + 26] != np.float32(private / 27.0)
    np.testing.assert_array_equal(actual.public, expected.public)


def test_unsupported_shape_retains_previous_reference_path(monkeypatch):
    rnd = _state_after(62, 35)
    expected = static.tensors_from_round_static(rnd, rnd.turn, version=2)
    seen = []
    original = encode_versions.Memory

    def memory(*args, **kwargs):
        seen.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(static, "_fused_static_tensors", lambda *_: None)
    monkeypatch.setattr(encode_versions, "Memory", memory)
    fallback = static.tensors_from_round_static(rnd, rnd.turn, version=2)
    np.testing.assert_array_equal(fallback.public, expected.public)
    assert seen == [{"own_kitty": False}]
    corrupt = copy.deepcopy(rnd)
    corrupt.hands[0].append("not-a-card")
    with pytest.raises(Exception) as old_error:
        v2.tensors_from_round(corrupt, rnd.turn, version=2)
    with pytest.raises(type(old_error.value)) as new_error:
        static.tensors_from_round_static(corrupt, rnd.turn, version=2)
    assert str(new_error.value) == str(old_error.value)


def test_probe_switch_restores_only_v2_unseen_path_on_error():
    original = static._widen_v2_static
    fused = static._fused_static_tensors
    with pytest.raises(RuntimeError, match="^probe interruption$"):
        with probe._optimization_context("v2-unseen", False):
            assert static._widen_v2_static is static.widen_v2
            assert static._fused_static_tensors is fused
            raise RuntimeError("probe interruption")
    assert static._widen_v2_static is original
    with probe._optimization_context("v2-unseen", True):
        assert static._widen_v2_static is original
    semantic = {"shortlist": {"successor_reuse": {"tensor_hits": 7}}}
    assert probe._comparison_semantic(semantic, "v2-unseen") is semantic
