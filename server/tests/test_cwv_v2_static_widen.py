"""Witnesses for the v2 static adapter's canonical widen composition."""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai import cwv_policy
from shengji.ai import cwv_static_encoding as static
from shengji.ai.cwv_policy import CWVError, CompleteWorldEvaluator
from shengji.ai.smart import SmartBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.rl import value_afterstate, value_afterstate_v2 as v2
from shengji.rl.value_afterstate import ValueAfterstateError
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import round_signature


def _state_after(seed: int, plies: int):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bots = [SmartBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    for _ in range(plies):
        if rnd.phase != "play":
            break
        seat = rnd.turn
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    assert rnd.phase == "play"
    return rnd


def _v2_model(architecture="mlp"):
    return ValueNetwork(ValueModelConfig(
        architecture=architecture, width=8, feedforward_width=16,
        history_layers=1, attention_heads=1, public_dim=v2.public_dim(2),
        enc_version=2))


@pytest.mark.parametrize("trump_rank,trump_suit,is_nt", [
    ("2", "S", False), ("7", "H", False), ("A", "D", False),
    ("5", None, True),
])
@pytest.mark.parametrize("seed,plies", [(61, 1), (62, 35), (63, 70)])
def test_v2_static_public_world_perspective_are_exact_reference_inputs(
        seed, plies, trump_rank, trump_suit, is_nt):
    original = _state_after(seed, plies)
    rnd = copy.deepcopy(original)
    rnd.trump_rank = trump_rank
    rnd.trump_suit = trump_suit
    rnd.trump_is_nt = is_nt
    rnd.ordering = Ordering(trump_suit, trump_rank)
    for seat in range(4):
        reference = v2.tensors_from_round(rnd, seat, version=2)
        fast = static.tensors_from_round_static(rnd, seat, version=2)
        assert fast.public.shape == (561,)
        assert np.array_equal(fast.public, reference.public)
        assert np.array_equal(fast.world, reference.world)
        assert np.array_equal(fast.perspective, reference.perspective)
        assert fast.history.shape == (1, reference.history.shape[1])
        assert not np.any(fast.history)


def test_v2_consumer_refuses_a_bare_v1_row_with_exact_width_error():
    rnd = _state_after(64, 35)
    seat = rnd.turn
    expected = v2.tensors_from_round(rnd, seat, version=2)

    # A mutation that omits canonical widening must fail at the actual model
    # consumer, not merely at a helper-level shape assertion.
    v1 = static.tensors_from_round_static(rnd, seat, version=1)

    class BareV1Evaluator(CompleteWorldEvaluator):
        @property
        def encoder(self):
            return lambda _rnd, _seat: v1

    evaluator = BareV1Evaluator(None, model=_v2_model(), encoding="mlp-static")
    with pytest.raises(CWVError,
                       match=r"public tensor width \[532\] != the net's 561"):
        evaluator.score([rnd], seat)
    assert expected.public.shape == (561,)
    assert v1.public.shape == (532,)


def test_v2_static_evaluator_skips_reference_history_allocator(monkeypatch):
    rnd = _state_after(65, 35)
    reference = CompleteWorldEvaluator(
        None, model=_v2_model(), encoding="reference", max_batch=3)
    optimized = CompleteWorldEvaluator(
        None, model=_v2_model(), encoding="mlp-static", max_batch=3)
    positions = [copy.deepcopy(rnd) for _ in range(7)]

    def tripwire(*_args, **_kwargs):
        raise AssertionError("full reference history allocator called")

    monkeypatch.setattr(value_afterstate, "encode_public_history", tripwire)
    actual = optimized.score(positions, rnd.turn)
    with pytest.raises(AssertionError, match="full reference history allocator"):
        reference.score(positions, rnd.turn)
    assert actual.shape == (7,)
    assert np.isfinite(actual).all()
    assert optimized.model_rows == 7
    assert optimized.forward_calls == 3


def test_reference_context_switch_restores_static_v2_route():
    from scripts import cwv_prepared_lead_probe as probe

    rnd = _state_after(66, 35)
    positions = [copy.deepcopy(rnd), copy.deepcopy(rnd)]
    evaluator = CompleteWorldEvaluator(
        None, model=_v2_model(), encoding="mlp-static", max_batch=8)
    original = cwv_policy.tensors_from_round_static

    with probe._optimization_context("v2-static", False):
        reference_values = evaluator.score(positions, rnd.turn)
    assert cwv_policy.tensors_from_round_static is original
    optimized_values = evaluator.score(positions, rnd.turn)
    assert np.array_equal(reference_values, optimized_values)


def test_non_mlp_static_request_refuses_fast_route_and_keeps_full_history(
        monkeypatch):
    rnd = _state_after(67, 35)
    model = _v2_model("gru")
    evaluator = CompleteWorldEvaluator(
        None, model=model, encoding="mlp-static", max_batch=8)
    assert evaluator.effective_encoding == "reference"
    expected = v2.tensors_from_round(rnd, rnd.turn, version=2)
    row = evaluator.encoder(rnd, rnd.turn)
    assert row.history.shape == expected.history.shape
    assert np.array_equal(row.history, expected.history)
    assert np.any(row.history)

    def tripwire(*_args, **_kwargs):
        raise AssertionError("MLP static route used by non-MLP model")

    monkeypatch.setattr(cwv_policy, "tensors_from_round_static", tripwire)
    values = evaluator.score([rnd], rnd.turn)
    assert values.shape == (1,)


def test_v1_static_width_and_v2_invalid_input_refusal_remain_unchanged():
    rnd = _state_after(68, 1)
    assert static.tensors_from_round_static(rnd, rnd.turn, version=1).public.shape == (532,)
    corrupt = copy.deepcopy(rnd)
    corrupt.hands[0].append("not-a-card")
    with pytest.raises(ValueAfterstateError) as reference_error:
        v2.tensors_from_round(corrupt, rnd.turn, version=2)
    with pytest.raises(type(reference_error.value)) as static_error:
        static.tensors_from_round_static(corrupt, rnd.turn, version=2)
    assert str(static_error.value) == str(reference_error.value)


class _RecordingEvaluator(CompleteWorldEvaluator):
    def __init__(self, model, encoding):
        super().__init__(None, model=model, encoding=encoding, max_batch=8)
        self.score_batches = []
        self.score_values = []

    def score(self, positions, root_seat, **kwargs):
        self.score_batches.append(len(positions))
        values = super().score(positions, root_seat, **kwargs)
        self.score_values.extend(values.tolist())
        return values


def _stable_bot_observations(bot):
    def without_timing(value):
        if isinstance(value, dict):
            return {key: without_timing(inner) for key, inner in value.items()
                    if key not in {"search_secs", "wall_seconds"}}
        if isinstance(value, list):
            return [without_timing(inner) for inner in value]
        return value

    return (without_timing(copy.deepcopy(bot.last_decision_record)),
            without_timing(copy.deepcopy(bot.last_shortlist)))


def test_actual_shortlist_v2_reference_and_static_paths_match_batches_report_and_rng():
    import torch

    rnd = _state_after(69, 35)
    torch.manual_seed(6901)
    reference_eval = _RecordingEvaluator(_v2_model(), "reference")
    torch.manual_seed(6901)
    optimized_eval = _RecordingEvaluator(_v2_model(), "mlp-static")
    config = CWVShortlistConfig(
        worlds=1, selection_worlds=1, alternatives=1, batch_size=11)
    reference_bot = CWVShortlistBot(
        reference_eval, seed=6902, config=config)
    optimized_bot = CWVShortlistBot(
        optimized_eval, seed=6902, config=config)
    for bot in (reference_bot, optimized_bot):
        bot.TRACTOR_LOCK = False
        bot.REPORT_RULE = "lcb"
        bot.REPORT_FOLD_WORLDS = 30

    reference_played = reference_bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    optimized_played = optimized_bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert reference_played == optimized_played
    assert reference_bot.rng.getstate() == optimized_bot.rng.getstate()
    assert reference_eval.score_values and optimized_eval.score_values
    assert reference_eval.score_batches == optimized_eval.score_batches
    assert np.array_equal(reference_eval.score_values, optimized_eval.score_values)
    assert reference_eval.forward_calls == optimized_eval.forward_calls
    assert np.array_equal(reference_eval.support, optimized_eval.support)

    reference_record, reference_shortlist = _stable_bot_observations(reference_bot)
    optimized_record, optimized_shortlist = _stable_bot_observations(optimized_bot)
    assert reference_shortlist == optimized_shortlist
    assert reference_record == optimized_record
    assert reference_bot.last_override_stats == optimized_bot.last_override_stats
    assert reference_record["played"] == list(reference_played)
    assert reference_record["report_fold"]
    assert reference_record["report_fold"]["worlds"] == 30
    assert reference_record["report_fold"] == optimized_record["report_fold"]
    assert reference_shortlist["shortlist"] == reference_record["candidates"]
    assert round_signature(rnd) == round_signature(_state_after(69, 35))
