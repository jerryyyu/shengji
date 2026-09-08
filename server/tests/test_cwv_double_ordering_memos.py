"""Bounded lifetime tests for the double-shortlist Ordering memos."""
from __future__ import annotations

import copy

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round
from shengji.train.cwv_double_shortlist import CWVDoubleShortlistBot
from tests.test_cwv_double_shortlist import PointsNet
from tests.test_cwv_double_successor_reuse import _real_bot, _scientific
from tests.test_cwv_static_public import _state_after
from tests.test_world_shortlist import round_signature


def _memo_sizes(state):
    ordering = state.ordering
    return (len(getattr(ordering, "_dcache", {})),
            len(getattr(ordering, "_trcache", {})))


def _seed_memos(state, dcount, tcount):
    state.ordering._dcache = {("d", i): object() for i in range(dcount)}
    state.ordering._trcache = {(("t", i), 1): object() for i in range(tcount)}


@pytest.mark.parametrize("mode,reuse", [("learned", False), ("learned", True),
                                        ("uniform", True)])
def test_real_decision_low_limits_clear_memos_without_semantic_drift(monkeypatch, mode, reuse):
    import torch
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork

    torch.manual_seed(37)
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    source = _state_after(73, 50)
    reference, reference_eval = _real_bot(source, model, reuse)
    bounded, bounded_eval = _real_bot(source, model, reuse)
    reference.inner_mode = bounded.inner_mode = mode
    reference.reuse_successors = bounded.reuse_successors = reuse
    # Establish the effectively-unbounded reference before enabling the
    # deliberately tiny production limits on the second consumer.
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_DECOMPOSITION_LIMIT", 10**9)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_TRACTOR_LIMIT", 10**9)
    reference_input = copy.deepcopy(source)
    expected = reference.decide_play(reference_input, source.turn)

    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_DECOMPOSITION_LIMIT", 1)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_TRACTOR_LIMIT", 1)
    clears = []
    trim = CWVDoubleShortlistBot._trim_ordering_memos

    def witnessed_trim(self, states):
        before = [_memo_sizes(state) for state in states
                  if type(state) is Round and type(state.ordering) is Ordering]
        result = trim(self, states)
        after = [_memo_sizes(state) for state in states
                 if type(state) is Round and type(state.ordering) is Ordering]
        if any(b != a and (a[0] == 0 or a[1] == 0)
               for b, a in zip(before, after)):
            clears.append((len(states), before, after))
        return result

    monkeypatch.setattr(CWVDoubleShortlistBot, "_trim_ordering_memos",
                        witnessed_trim)
    bounded_input = copy.deepcopy(source)
    actual = bounded.decide_play(bounded_input, source.turn)

    assert clears, "low limits must witness an actual memo clear"
    if mode == "learned":
        assert any(count > 1 for count, _, _ in clears), (
            "a real multi-row rank batch must clear, not only a later clone")
    assert actual == expected
    assert bounded_eval.batches == reference_eval.batches
    assert bounded_eval.outputs == reference_eval.outputs
    assert _scientific(bounded.last_decision_record) == _scientific(
        reference.last_decision_record)
    assert bounded.rng.getstate() == reference.rng.getstate()
    assert round_signature(reference_input) == round_signature(source)
    assert round_signature(bounded_input) == round_signature(source)


def test_fast_context_keeps_dict_aliases_while_contents_are_cleared(monkeypatch):
    from shengji.engine import fast

    state = _state_after(73, 50)
    ordering = state.ordering
    ctx = fast._ctx(ordering)
    dcache, trcache = ordering._dcache, ordering._trcache
    assert ctx[0] is dcache and ctx[1] is trcache
    dcache.clear()
    trcache.clear()
    dcache.update({("d", i): object() for i in range(3)})
    trcache.update({(("t", i), 1): object() for i in range(3)})
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_DECOMPOSITION_LIMIT", 2)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_TRACTOR_LIMIT", 2)
    CWVDoubleShortlistBot(PointsNet())._trim_ordering_memos([state])
    assert ordering._dcache is dcache and ordering._trcache is trcache
    assert ordering._fast_ctx[0] is dcache and ordering._fast_ctx[1] is trcache
    assert not dcache and not trcache

    pure = _state_after(73, 50)
    pure.ordering = Ordering(pure.trump_suit, pure.trump_rank)
    pure.ordering._dcache = {("d", i): object() for i in range(3)}
    pure.ordering._trcache = {(("t", i), 1): object() for i in range(3)}
    assert not hasattr(pure.ordering, "_fast_ctx")
    CWVDoubleShortlistBot(PointsNet())._trim_ordering_memos([pure])
    assert _memo_sizes(pure) == (0, 0)


@pytest.mark.parametrize("kind", ["policy", "round", "ordering"])
def test_custom_types_do_not_enter_exact_memo_trim(monkeypatch, kind):
    class CustomPolicy(HeuristicBot):
        pass

    class CustomRound(Round):
        pass

    class CustomOrdering(Ordering):
        pass

    state = _state_after(73, 50)
    bot = CWVDoubleShortlistBot(PointsNet())
    if kind == "policy":
        bot.rollout_policy = CustomPolicy()
    elif kind == "round":
        state.__class__ = CustomRound
    else:
        state.ordering.__class__ = CustomOrdering
    _seed_memos(state, 3, 3)
    before = _memo_sizes(state)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_DECOMPOSITION_LIMIT", 1)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_TRACTOR_LIMIT", 1)
    bot._trim_ordering_memos([state])
    assert _memo_sizes(state) == before


def test_memo_limits_are_inclusive_and_clear_only_when_exceeded(monkeypatch):
    state = _state_after(73, 50)
    bot = CWVDoubleShortlistBot(PointsNet())
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_DECOMPOSITION_LIMIT", 2)
    monkeypatch.setattr(CWVDoubleShortlistBot, "ORDERING_TRACTOR_LIMIT", 2)
    _seed_memos(state, 2, 2)
    bot._trim_ordering_memos([state])
    assert _memo_sizes(state) == (2, 2)
    state.ordering._dcache[("d", 2)] = object()
    bot._trim_ordering_memos([state])
    assert _memo_sizes(state) == (0, 2)
    state.ordering._trcache[(("t", 2), 1)] = object()
    bot._trim_ordering_memos([state])
    assert _memo_sizes(state) == (0, 0)
