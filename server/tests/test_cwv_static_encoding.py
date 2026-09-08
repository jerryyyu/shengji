"""Differential and refusal witnesses for the opt-in CWV MLP adapter."""
from __future__ import annotations

import copy
import random
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai import cwv_policy
from shengji.ai import cwv_static_encoding as static
from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.douzero_micro import DouZeroMicroError
from shengji.rl import value_afterstate
from shengji.rl.encode import CARD_INDEX, OBS_DIM
from shengji.rl.value_afterstate import ValueAfterstateError, tensors_from_round
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import cwv_shortlist_screen as screen
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


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
    return rnd


@pytest.fixture(scope="module")
def model():
    import torch
    torch.manual_seed(19)
    return ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))


def test_static_rows_and_scores_are_reference_fixed_inputs(model):
    for plies in (1, 35, 70):
        rnd = _state_after(41, plies)
        assert rnd.phase == "play"
        positions = [rnd]
        for seat in range(4):
            reference = tensors_from_round(rnd, seat)
            fast = static.tensors_from_round_static(rnd, seat)
            assert np.array_equal(reference.public, fast.public)
            assert np.array_equal(reference.world, fast.world)
            assert np.array_equal(reference.perspective, fast.perspective)
            assert fast.history.shape == (1, reference.history.shape[1])
            assert not np.any(fast.history)
            positions.append(copy.deepcopy(rnd))
        reference_eval = CompleteWorldEvaluator(None, model=model,
                                                 encoding="reference")
        fast_eval = CompleteWorldEvaluator(None, model=model,
                                           encoding="mlp-static")
        assert np.array_equal(reference_eval.score(positions, 0),
                              fast_eval.score(positions, 0))
        assert fast_eval.identity()["encoding"] == "mlp-static"
        assert fast_eval.identity()["effective_encoding"] == "mlp-static"
        assert fast_eval.identity()["adapter"]["schema"] == static.STATIC_ENCODING_SCHEMA


def test_hidden_world_twin_changes_world_input_and_score_on_identical_batch():
    import torch

    rnd = _state_after(43, 12)
    twin = copy.deepcopy(rnd)
    root = 0
    # Swap two still-hidden cards; public observations and root perspective
    # remain unchanged, while the complete-world input must change.
    twin.hands[1][0], twin.hands[2][0] = twin.hands[2][0], twin.hands[1][0]
    changed_card = rnd.hands[1][0]
    first = static.tensors_from_round_static(rnd, root)
    second = static.tensors_from_round_static(twin, root)
    assert np.array_equal(first.public, second.public)
    assert np.array_equal(first.perspective, second.perspective)
    assert not np.array_equal(first.world, second.world)

    class ReceiverSensitive(torch.nn.Module):
        config = SimpleNamespace(architecture="mlp")

        def forward(self, public, history, mask, world, perspective):
            logits = torch.zeros((len(public), 204), dtype=public.dtype)
            logits[:, 0] = world[:, 1, CARD_INDEX[changed_card]]
            return logits

    reference = CompleteWorldEvaluator(None, model=ReceiverSensitive(),
                                       encoding="reference")
    fast = CompleteWorldEvaluator(None, model=ReceiverSensitive(),
                                  encoding="mlp-static")
    reference_scores = reference.score([rnd, twin], root)
    fast_scores = fast.score([rnd, twin], root)
    assert np.array_equal(reference_scores, fast_scores)
    assert reference_scores[0] != reference_scores[1]


def _same_refusal(rnd, monkeypatch=None, expected=(ValueAfterstateError, DouZeroMicroError)):
    if monkeypatch is not None:
        # Keep malformed-history checks independent of encode_obs indexing.
        valid_obs = lambda _rnd, _seat: [0.0] * OBS_DIM
        monkeypatch.setattr(value_afterstate, "encode_obs", valid_obs)
        monkeypatch.setattr(static, "encode_obs", valid_obs)
    with pytest.raises(expected) as reference_error:
        tensors_from_round(rnd, 0)
    with pytest.raises(type(reference_error.value)) as fast_error:
        static.tensors_from_round_static(rnd, 0)
    assert str(fast_error.value) == str(reference_error.value)


def test_zero_history_refusal_is_exact():
    # A genuine first-play state has a physically complete deck.
    _same_refusal(_state_after(47, 0))
    with pytest.raises(ValueAfterstateError, match="^history tensor length drift$"):
        static.tensors_from_round_static(_state_after(47, 0), 0)


def test_history_event_guards_preserve_exact_reference_errors(monkeypatch):
    first = _state_after(47, 0)
    # Empty-card events preserve physical conservation while exercising the
    # public history's position and seat validation.
    bad_seat = copy.deepcopy(first)
    from shengji.engine.round import Trick, TrickPlay
    bad_seat.trick.plays = [TrickPlay(4, [])]
    _same_refusal(bad_seat, monkeypatch)

    float_seat = copy.deepcopy(first)
    float_seat.trick.plays = [TrickPlay(1.0, [])]
    _same_refusal(float_seat, monkeypatch, expected=IndexError)

    bad_position = copy.deepcopy(first)
    bad_position.trick.plays = [TrickPlay(seat, []) for seat in (0, 1, 2, 3, 0)]
    _same_refusal(bad_position, monkeypatch)

    over_cap = copy.deepcopy(first)
    over_cap.history = [Trick(leader=0, plays=[TrickPlay(0, [])]) for _ in range(101)]
    _same_refusal(over_cap, monkeypatch)


def test_physical_and_unknown_card_refusal_remains_fail_closed():
    corrupt = _state_after(47, 0)
    corrupt.hands[0].append("not-a-card")
    with pytest.raises(ValueAfterstateError, match="^afterstate violates physical deck conservation$"):
        static.tensors_from_round_static(corrupt, 0)


def test_fast_valid_path_does_not_call_reference_history_allocator(model, monkeypatch):
    from shengji.ai import cwv_policy

    rnd = _state_after(53, 25)
    positions = [rnd]

    def tripwire(*_args, **_kwargs):
        raise AssertionError("reference history allocator called")

    monkeypatch.setattr(value_afterstate, "encode_public_history", tripwire)
    evaluator = CompleteWorldEvaluator(None, model=model, encoding="mlp-static")
    evaluator.score(positions, 0)
    with pytest.raises(AssertionError, match="reference history allocator"):
        CompleteWorldEvaluator(None, model=model, encoding="reference").score(positions, 0)
    gru = ValueNetwork(ValueModelConfig(
        architecture="gru", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    with pytest.raises(AssertionError, match="reference history allocator"):
        CompleteWorldEvaluator(None, model=gru, encoding="mlp-static").score(
            positions, 0)


def test_non_mlp_fast_request_falls_back_to_reference(monkeypatch):
    model = ValueNetwork(ValueModelConfig(
        architecture="gru", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    rnd = _state_after(59, 10)
    evaluator = CompleteWorldEvaluator(None, model=model, encoding="mlp-static")
    assert evaluator.identity()["effective_encoding"] == "reference"
    # The fallback remains the sequence path and therefore sees the history.
    assert evaluator.score([rnd], 0).shape == (1,)


def test_shortlist_worker_receives_mode_and_legacy_recipe_defaults_reference(monkeypatch):
    captured = {}

    class Evaluator:
        checkpoint_sha256 = "configured"

    def shared(*args, **kwargs):
        captured.update(kwargs)
        return Evaluator()

    monkeypatch.setattr(screen, "shared_evaluator", shared)
    config = {
        "schema": "cwv-shortlist-config-v1", "arm": "learned",
        "checkpoint": "checkpoint.pt", "checkpoint_sha256": "configured",
        "encoding": "mlp-static", "shortlist": {
            "worlds": 1, "selection_worlds": 1, "alternatives": 1,
            "batch_size": 1, "uniform": False}, "report_worlds": 30,
        "production_multiplier": 1, "target_wall_multiplier": 1,
        "seed0": 1, "clusters": 1,
    }
    screen.make_side(config, "arm", 1)
    assert captured["encoding"] == "mlp-static"
    legacy = dict(config)
    legacy.pop("encoding")
    assert screen._recipe(legacy)["rank"] == "2"
    assert "encoding" not in screen._recipe(legacy)


def test_shared_evaluator_cache_separates_requested_modes(monkeypatch):
    from shengji.ai import cwv_policy

    made = []

    class Evaluator:
        def __init__(self, *args, **kwargs):
            made.append(kwargs["encoding"])

    cwv_policy._shared_evaluator.cache_clear()
    monkeypatch.setattr(cwv_policy, "CompleteWorldEvaluator", Evaluator)
    reference = cwv_policy._shared_evaluator("checkpoint", 1, 1, 1, 8, "reference")
    assert reference is cwv_policy._shared_evaluator(
        "checkpoint", 1, 1, 1, 8, "reference")
    fast = cwv_policy._shared_evaluator("checkpoint", 1, 1, 1, 8, "mlp-static")
    assert fast is not reference
    assert made == ["reference", "mlp-static"]
    cwv_policy._shared_evaluator.cache_clear()


def test_whole_shortlist_candidates_are_seeded_and_batch_order_parity(model):
    class RecordedEvaluator(CompleteWorldEvaluator):
        def __init__(self, encoding):
            super().__init__(None, model=model, encoding=encoding)
            self.batch_sizes = []
            self.signatures = []
            self.scores = []

        def score(self, states, seat):
            self.batch_sizes.append(len(states))
            self.signatures.extend(round_signature(state) for state in states)
            values = super().score(states, seat)
            self.scores.extend(values)
            return values

    config = CWVShortlistConfig(worlds=2, selection_worlds=2,
                                alternatives=3, batch_size=17)
    left_eval = RecordedEvaluator("reference")
    right_eval = RecordedEvaluator("mlp-static")
    left = CWVShortlistBot(left_eval, seed=71, config=config)
    right = CWVShortlistBot(right_eval, seed=71, config=config)
    left_state = play_state()
    right_state = copy.deepcopy(left_state)
    left_rng = left.rng.getstate()
    right_rng = right.rng.getstate()
    assert left._candidates(left_state, left_state.turn) == right._candidates(
        right_state, right_state.turn)
    ldetail, rdetail = left.last_shortlist, right.last_shortlist
    assert ldetail["shortlist_indices"] == rdetail["shortlist_indices"]
    assert ldetail["shortlist_means"] == rdetail["shortlist_means"]
    assert ldetail["legal_sha256"] == rdetail["legal_sha256"]
    assert ldetail["world_seed"] == rdetail["world_seed"]
    assert ldetail["config"] == rdetail["config"]
    assert left_eval.batch_sizes == right_eval.batch_sizes
    assert left_eval.signatures == right_eval.signatures
    assert len(left_eval.scores) > 0
    assert np.array_equal(left_eval.scores, right_eval.scores)
    assert left.rng.getstate() == left_rng
    assert right.rng.getstate() == right_rng

    # Exercise the inherited MC selection/report consumer too; encoding must
    # not change the final decision or its production RNG trajectory.
    left.REPORT_FOLD_WORLDS = right.REPORT_FOLD_WORLDS = 30
    assert left.decide_play(left_state, left_state.turn) == right.decide_play(
        right_state, right_state.turn)
    assert left.rng.getstate() == right.rng.getstate()
    assert left.shortlist_counts == right.shortlist_counts
