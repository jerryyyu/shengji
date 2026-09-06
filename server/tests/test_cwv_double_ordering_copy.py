"""Skip pure Ordering-memo copies, never the mutable simulation state."""
from __future__ import annotations

import copy

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.combos import decompose, find_tractor_runs
from shengji.engine.round import Round
from shengji.train.cwv_double_shortlist import CWVDoubleShortlistBot
from tests.test_cwv_double_shortlist import PointsNet
from tests.test_cwv_double_successor_reuse import (
    _real_bot, _scientific,
)
from tests.test_cwv_static_public import _state_after
from tests.test_world_shortlist import round_signature


def test_only_ordering_is_shared_and_trick_cache_aliases_stay_isolated():
    state = _state_after(73, 48)
    state._trusted_rollout = True
    state._determinized_world = True
    policy = HeuristicBot()
    state.play(state.turn, policy.decide_play(state, state.turn))
    assert state.trick.incumbent is not None
    assert state.trick.running_points is not None
    assert state.last_trick is state.history[-1]
    state.extra_mutable_cache = {"cards": list(state.hands[0])}
    decompose(["S3", "S3"], state.ordering)
    find_tractor_runs(["S3", "S3", "S4", "S4"], state.ordering, 2)
    before = copy.deepcopy(state)

    clone = CWVDoubleShortlistBot(PointsNet())._copy_state(state)
    assert clone.ordering is state.ordering
    assert clone.ordering._dcache is state.ordering._dcache
    assert clone.ordering._trcache is state.ordering._trcache
    assert clone.last_trick is clone.history[-1]
    assert clone.last_trick is not state.last_trick
    assert clone.trick is not state.trick
    assert clone.trick.incumbent == state.trick.incumbent
    assert clone.trick.running_points == state.trick.running_points
    assert clone.hands is not state.hands
    assert all(a is not b for a, b in zip(clone.hands, state.hands))
    assert clone.history is not state.history
    assert clone.buried is not state.buried
    assert clone.deck is not state.deck
    assert clone.kitty is not state.kitty
    assert clone.passed is not state.passed
    assert clone.declaration is not state.declaration
    clone.extra_mutable_cache["cards"].clear()
    clone.history[-1].plays[0].cards.clear()
    clone.trick.plays[0].cards.clear()
    clone.hands[0].clear()
    clone.buried.clear()
    assert round_signature(state) == round_signature(before)
    assert state.extra_mutable_cache == before.extra_mutable_cache
    assert state.trick.incumbent == before.trick.incumbent
    assert state.trick.running_points == before.trick.running_points


@pytest.mark.parametrize("kind", ["policy", "round", "ordering", "no-ordering"])
def test_custom_types_keep_full_deepcopy(kind):
    class CustomRound(Round):
        pass

    class CustomOrdering(Ordering):
        pass

    class CustomPolicy(HeuristicBot):
        pass

    state = _state_after(73, 50)
    bot = CWVDoubleShortlistBot(PointsNet())
    if kind == "policy":
        bot.rollout_policy = CustomPolicy()
    elif kind == "round":
        state.__class__ = CustomRound
    elif kind == "ordering":
        state.ordering.__class__ = CustomOrdering
    else:
        state.ordering = None
    clone = bot._copy_state(state)
    assert type(clone) is type(state)
    if state.ordering is not None:
        assert type(clone.ordering) is type(state.ordering)
        assert clone.ordering is not state.ordering
        clone.ordering._eff.clear()
        assert state.ordering._eff
    else:
        assert clone.ordering is None
    assert round_signature(clone) == round_signature(state)


@pytest.mark.parametrize("mode", ["learned", "uniform", "heuristic"])
def test_decide_play_skips_ordering_copy_with_exact_batches_scores_rng_and_record(
        mode, monkeypatch):
    import torch
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork

    torch.manual_seed(37)
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    state = _state_after(73, 50)
    before = round_signature(state)
    reference, reference_eval = _real_bot(state, model, True)
    actual, actual_eval = _real_bot(state, model, True)
    reference.inner_mode = actual.inner_mode = mode
    # Independent old algorithm, not the new helper invoked twice.
    reference._copy_state = copy.deepcopy
    reference_input, actual_input = copy.deepcopy(state), copy.deepcopy(state)
    expected_play = reference.decide_play(reference_input, state.turn)

    def forbidden_ordering_copy(self, memo):
        raise AssertionError("actual consumer copied the pure Ordering cache")

    monkeypatch.setattr(Ordering, "__deepcopy__", forbidden_ordering_copy,
                        raising=False)
    calls = []
    copy_state = actual._copy_state

    def witnessed_copy(parent):
        clone = copy_state(parent)
        assert clone.ordering is parent.ordering
        assert clone is not parent
        calls.append(1)
        return clone

    actual._copy_state = witnessed_copy
    assert actual.decide_play(actual_input, state.turn) == expected_play
    assert calls  # Tripwire covers real root/finalist cloning, not an idle arm.
    assert actual_eval.batches == reference_eval.batches
    assert actual_eval.outputs == reference_eval.outputs
    assert actual.rng.getstate() == reference.rng.getstate()
    assert _scientific(actual.last_decision_record) == _scientific(
        reference.last_decision_record)
    assert round_signature(reference_input) == before
    assert round_signature(actual_input) == before


@pytest.mark.parametrize("plies", [48, 49, 50, 51, 70])
def test_whole_heuristic_continuation_keeps_every_play_and_terminal(plies):
    state = _state_after(73, plies)
    state._trusted_rollout = True
    state._determinized_world = True
    before = round_signature(state)
    baseline = copy.deepcopy(state)
    actual = CWVDoubleShortlistBot(PointsNet())._copy_state(state)
    traces = []
    for clone in (baseline, actual):
        trace = []
        policy = HeuristicBot()
        while clone.phase == "play":
            seat = clone.turn
            play = policy.decide_play(clone, seat)
            clone.play(seat, list(play))
            trace.append((seat, tuple(play), round_signature(clone)))
        traces.append((trace, clone.kitty_bonus, clone.last_trick_winner,
                       [(t.winner, t.points) for t in clone.history]))
    assert traces[0] == traces[1]
    assert traces[0][0]
    assert round_signature(state) == before
