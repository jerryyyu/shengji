"""Focused witnesses for the isolated world-shortlist experiment."""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.engine.game import Game
from shengji.oracle.screen import OracleValueMixin
from shengji.rl.encode import ACT_DIM, OBS_DIM, encode_obs
from shengji.train.leaf_policy import PointsHead
from shengji.train.model import ValuePriorNet
from shengji.train.search_inference import SearchHeads
from shengji.train.search_policy import SearchError, terminal_utility
from shengji.train.world_shortlist import (
    WorldShortlistBot, WorldShortlistConfig,
)


def play_state(seed=431):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policy = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policy.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policy.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, policy.decide_bury(rnd, rnd.banker))
    return rnd


class Heads:
    def __init__(self, value=1.0):
        self.value = value
        self.calls = []

    def values(self, leaves):
        self.calls.append(len(leaves))
        return [self.value] * len(leaves)


def tiny_model(aux_points=True):
    return ValuePriorNet({
        "obs_dim": OBS_DIM, "act_dim": ACT_DIM, "trunk": [16, 8],
        "value_hidden": 4, "prior_hidden": 5, "dropout": 0.0,
        "aux_points": aux_points, "aux_search_mean": False,
    }).eval()


class ModelHeads(Heads):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.metadata = {"fixture": "world-shortlist"}


def round_signature(rnd):
    return (rnd.phase, rnd.turn, rnd.attacker_points,
            tuple(tuple(h) for h in rnd.hands), tuple(rnd.buried),
            tuple(tuple((p.seat, tuple(p.cards)) for p in t.plays)
                  for t in rnd.history),
            None if rnd.trick is None else
            tuple((p.seat, tuple(p.cards)) for p in rnd.trick.plays))


def fixed_world(rnd, seat):
    sampled = {s: list(h) for s, h in enumerate(rnd.hands) if s != seat}
    return sampled, list(rnd.buried)


def test_config_is_frozen_and_fail_closed():
    cfg = WorldShortlistConfig(cheap_worlds=2, refine_worlds=1)
    with pytest.raises((AttributeError, TypeError)):
        cfg.cheap_worlds = 3
    with pytest.raises(ValueError):
        WorldShortlistConfig(cheap_worlds=0)
    with pytest.raises(ValueError):
        WorldShortlistConfig(value_kind="bad")


def test_cheap_batches_cross_candidates_and_worlds():
    rnd = play_state()
    seat = rnd.turn
    heads = Heads()
    bot = WorldShortlistBot(
        heads, config=WorldShortlistConfig(cheap_worlds=3, refine_worlds=1,
                                           batch_size=3))
    # Memory construction is an inherited production detail; use the public
    # decision path to obtain a valid sampled-world dose for this witness.
    bot.TRACTOR_LOCK = False
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"
    bot.decide_play(rnd, seat)
    assert len(heads.calls) > 1
    assert max(heads.calls) <= 3
    assert bot.hybrid_counts["cheap_worlds"] == 3
    assert bot.hybrid_counts["cheap_evaluations"] > 3


def test_report_is_inherited_and_model_stays_out_of_refinement(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    heads = Heads()
    bot = WorldShortlistBot(
        heads, seed=13,
        config=WorldShortlistConfig(cheap_worlds=2, refine_worlds=1,
                                    shortlist_size=2, batch_size=8))
    bot.TRACTOR_LOCK = False
    bot.REPORT_FOLD_WORLDS = 30
    bot.MARGIN = 0
    bot.decide_play(rnd, rnd.turn)
    rec = bot.last_decision_record
    assert rec["report_rule"] == "lcb"
    assert rec["work"]["report_rollouts"] == 60
    assert bot.hybrid_counts["refine_full_rollouts"] == 2
    assert bot.hybrid_counts["report_full_rollouts"] == 60
    assert rec["world_shortlist"]["stage_counts_delta"]["report_full_rollouts"] == 60
    assert all(value >= 0 for value in rec["world_shortlist"]["cheap_means"])


def test_underfilled_cheap_stage_falls_back_without_report(monkeypatch):
    rnd = play_state()
    heads = Heads()
    bot = WorldShortlistBot(
        heads, config=WorldShortlistConfig(cheap_worlds=2, refine_worlds=1))
    bot.TRACTOR_LOCK = False
    bot.REPORT_FOLD_WORLDS = 30
    monkeypatch.setattr(bot, "_sample_hands", lambda *_: None)
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_decision_record["reason"] == "selection_underfilled"
    assert "report_fold" not in bot.last_decision_record
    assert bot.hybrid_counts["report_full_rollouts"] == 0


@pytest.mark.parametrize("value_kind", ["levels", "points"])
def test_fixed_sampled_world_replaces_true_hidden_hands_and_burial(value_kind):
    rnd = play_state()
    seat = rnd.turn
    sampled, buried = fixed_world(rnd, seat)
    twin = copy.deepcopy(rnd)
    hidden = next(s for s in range(4) if s != seat and twin.hands[s])
    swap = next(((s, i) for s in range(4) if s != seat
                 for i, card in enumerate(twin.hands[s])
                 if card != twin.buried[0]), None)
    if swap is None:
        pytest.skip("fixture has no distinct hidden/burial card to swap")
    hidden, hand_index = swap
    twin.hands[hidden][hand_index], twin.buried[0] = (
        twin.buried[0], twin.hands[hidden][hand_index])
    assert round_signature(twin) != round_signature(rnd)
    model_heads = ModelHeads(tiny_model())
    bot = WorldShortlistBot(
        model_heads if value_kind == "points" else Heads(),
        config=WorldShortlistConfig(cheap_worlds=1, refine_worlds=1,
                                    shortlist_size=2, value_kind=value_kind))
    action = HeuristicBot().decide_play(rnd, seat)
    first, _ = bot._cheap_leaf(
        rnd, seat, sampled, buried, action, len(rnd.history) + 1,
        rnd.is_attacker(seat))
    second, _ = bot._cheap_leaf(
        twin, seat, sampled, buried, action, len(twin.history) + 1,
        twin.is_attacker(seat))
    assert first is not None and second is not None
    assert round_signature(first) == round_signature(second)
    assert first.buried == sorted(buried)


@pytest.mark.parametrize("value_kind", ["levels", "points"])
def test_terminal_leaf_bypasses_network_and_preserves_units_and_sign(value_kind):
    rnd = play_state()
    policy = HeuristicBot()
    while sum(map(len, rnd.hands)) > 4 or len(rnd.trick.plays) != 3:
        rnd.play(rnd.turn, policy.decide_play(rnd, rnd.turn))
    seat = rnd.turn
    sampled, buried = fixed_world(rnd, seat)
    heads = ModelHeads(tiny_model()) if value_kind == "points" else Heads()
    bot = WorldShortlistBot(
        heads, config=WorldShortlistConfig(cheap_worlds=1, refine_worlds=1,
                                           shortlist_size=2, value_kind=value_kind))
    if value_kind == "points":
        bot._points_head.forward = lambda _obs: (_ for _ in ()).throw(
            AssertionError("terminal leaf called points network"))
    action = policy.decide_play(rnd, seat)
    leaf, got = bot._cheap_leaf(
        rnd, seat, sampled, buried, action, len(rnd.history) + 1,
        rnd.is_attacker(seat))
    assert leaf is None
    truth = bot._cheap_leaf(
        rnd, seat, sampled, buried, action, len(rnd.history) + 1,
        rnd.is_attacker(seat))[1]
    if value_kind == "points":
        clone = OracleValueMixin._oracle_world_clone(bot, rnd, seat, sampled, buried)
        clone.play(seat, action)
        expected = float(clone.attacker_points)
        if not rnd.is_attacker(seat):
            expected = -expected
    else:
        clone = OracleValueMixin._oracle_world_clone(bot, rnd, seat, sampled, buried)
        clone.play(seat, action)
        expected = 40 * terminal_utility(clone, seat % 2)
    assert got == truth == expected
    if value_kind == "levels":
        assert heads.calls == []


@pytest.mark.parametrize("bad", ["shape", "finite"])
def test_bad_level_head_outputs_are_refused(bad):
    rnd = play_state()
    seat = rnd.turn
    sampled, buried = fixed_world(rnd, seat)
    candidates = [HeuristicBot().decide_play(rnd, seat)]

    class BadHeads(Heads):
        def values(self, leaves):
            if bad == "shape":
                return []
            return [float("nan")] * len(leaves)

    bot = WorldShortlistBot(
        BadHeads(), config=WorldShortlistConfig(cheap_worlds=1, refine_worlds=1,
                                                shortlist_size=2))
    with pytest.raises(SearchError):
        bot._cheap_values(rnd, seat, candidates, [(sampled, buried)], True)


def test_bad_points_head_outputs_are_refused():
    rnd = play_state()
    seat = rnd.turn
    sampled, buried = fixed_world(rnd, seat)
    action = HeuristicBot().decide_play(rnd, seat)
    bot = WorldShortlistBot(
        ModelHeads(tiny_model()), config=WorldShortlistConfig(
            cheap_worlds=1, refine_worlds=1, shortlist_size=2, value_kind="points"))
    bot._points_head.forward = lambda obs: np.zeros((len(obs), 1))
    with pytest.raises(SearchError, match="cheap points head must return"):
        bot._cheap_values(rnd, seat, [action], [(sampled, buried)], True)
    bot._points_head.forward = lambda obs: np.full((len(obs), 2), np.nan)
    with pytest.raises(SearchError, match="non-finite"):
        bot._cheap_values(rnd, seat, [action], [(sampled, buried)], True)


def test_real_points_head_batch_matches_scalar_and_crosses_world_boundary():
    model = tiny_model()
    heads = SearchHeads(model, batch_size=8)
    exported = PointsHead.from_model(model, metadata=heads.metadata)
    rnd = play_state()
    search_batch = heads.values([rnd, rnd])
    search_scalar = [heads.values([rnd])[0], heads.values([rnd])[0]]
    assert np.allclose(search_batch, search_scalar, rtol=1e-6, atol=1e-6)
    obs = np.asarray([encode_obs(rnd, rnd.turn), encode_obs(rnd, rnd.turn)], dtype=np.float64)
    batched = exported.forward(obs)
    scalar = np.vstack([exported.forward(row) for row in obs])
    assert np.allclose(batched, scalar, rtol=1e-12, atol=1e-12)

    class RecordingHeads(Heads):
        pass

    bot = WorldShortlistBot(
        RecordingHeads(), config=WorldShortlistConfig(
            cheap_worlds=2, refine_worlds=1, shortlist_size=2, batch_size=2))
    seat = rnd.turn
    sampled, buried = fixed_world(rnd, seat)
    action = HeuristicBot().decide_play(rnd, seat)
    bot._cheap_values(rnd, seat, [action, action],
                      [(sampled, buried), (sampled, buried)], True)
    assert len(bot.heads.calls) > 1
    assert max(bot.heads.calls) <= 2


@pytest.mark.parametrize("value_kind", ["levels", "points"])
@pytest.mark.parametrize("batch_size", [5, 128])
def test_varying_leaf_scores_keep_candidate_world_mapping(value_kind, batch_size):
    """Batch transport must preserve nonconstant per-candidate/world values."""
    rnd = play_state()
    seat = rnd.turn
    weights = np.random.default_rng(81).normal(size=OBS_DIM)

    def scores(observations):
        return np.asarray(observations, dtype=np.float64) @ weights

    class VaryingHeads(Heads):
        def values(self, leaves):
            self.calls.append(len(leaves))
            return scores([encode_obs(leaf, leaf.turn) for leaf in leaves])

    def make(batch):
        bot = WorldShortlistBot(
            ModelHeads(tiny_model()) if value_kind == "points" else VaryingHeads(),
            seed=29, config=WorldShortlistConfig(
                cheap_worlds=6, refine_worlds=1, value_kind=value_kind,
                batch_size=batch))
        if value_kind == "points":
            bot._points_head.forward = lambda obs: np.column_stack(
                (np.zeros(len(obs)), scores(obs)))
        return bot

    scalar = make(1)
    candidates = scalar._candidates(rnd, seat)
    worlds, _, _ = scalar._sample_stage(
        rnd, seat, Memory(rnd, seat, own_kitty=scalar.BANKER_KITTY), 6, None)
    assert len(candidates) >= 3 and len(worlds) == 6
    expected = np.asarray(scalar._cheap_values(
        rnd, seat, candidates, worlds, rnd.is_attacker(seat)))
    # Prove neither matrix axis is constant: a row permutation or transposed
    # assignment must not be masked by identical fixture predictions.
    assert np.max(np.ptp(expected, axis=0)) > 1e-6
    assert np.max(np.ptp(expected, axis=1)) > 1e-6
    batched = make(batch_size)
    got = batched._cheap_values(
        rnd, seat, candidates, worlds, rnd.is_attacker(seat))
    np.testing.assert_allclose(got, expected, rtol=1e-12, atol=1e-10)
    assert batched.hybrid_counts["model_batches"] < scalar.hybrid_counts["model_batches"]


def test_refine_underfill_keeps_cheap_work_but_no_refinement_or_report(monkeypatch):
    rnd = play_state()
    seat = rnd.turn
    bot = WorldShortlistBot(
        Heads(), config=WorldShortlistConfig(cheap_worlds=2, refine_worlds=2,
                                             shortlist_size=2))
    bot.TRACTOR_LOCK = False
    bot.REPORT_FOLD_WORLDS = 30
    original = bot._sample_hands
    first = original(rnd, seat, Memory(
        rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True)))
    calls = 0

    def sample(*args):
        nonlocal calls
        calls += 1
        return first if calls <= 2 else None

    monkeypatch.setattr(bot, "_sample_hands", sample)
    bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert rec["reason"] == "selection_underfilled"
    assert rec["alloc"]["rollouts"] == rec["work"]["selection_rollouts"]
    assert bot.hybrid_counts["cheap_evaluations"] > 0
    assert bot.hybrid_counts["refine_full_rollouts"] == 0
    assert bot.hybrid_counts["report_full_rollouts"] == 0
    assert not rec["work"]["complete"]


def test_shortlist_always_retains_badly_ranked_incumbent(monkeypatch):
    rnd = play_state()
    bot = WorldShortlistBot(
        Heads(), config=WorldShortlistConfig(cheap_worlds=1, refine_worlds=1,
                                             shortlist_size=2))
    bot.TRACTOR_LOCK = False
    bot.REPORT_RULE = "none"
    bot.REPORT_FOLD_WORLDS = 0
    monkeypatch.setattr(bot, "_cheap_values", lambda _r, _s, c, _w, _a:
                        [[-100.0] if i == 0 else [100.0]
                         for i in range(len(c))])
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_decision_record["world_shortlist"]["shortlist_indices"][0] == 0
    assert bot.last_decision_record["world_shortlist"]["shortlist_indices"] == [0, 1]


def test_phase_tripwire_rejects_model_calls_after_cheap_stage():
    rnd = play_state()
    bot = WorldShortlistBot(
        Heads(), config=WorldShortlistConfig(cheap_worlds=1, refine_worlds=1,
                                             shortlist_size=2))
    bot.TRACTOR_LOCK = False
    bot.REPORT_FOLD_WORLDS = 30
    phase = [None]
    original_cheap = bot._cheap_values

    def cheap(*args):
        phase[0] = "cheap"
        return original_cheap(*args)

    original_rollout = bot._rollout

    def rollout(*args, **kwargs):
        phase[0] = "full"
        return original_rollout(*args, **kwargs)

    bot._cheap_values = cheap
    bot._rollout = rollout

    class Tripwire(Heads):
        def values(self, leaves):
            assert phase[0] == "cheap"
            return super().values(leaves)

    bot.heads = Tripwire()
    bot.decide_play(rnd, rnd.turn)
    assert phase[0] == "full"


def test_cheap_advances_parent_rng_refine_uses_distinct_restored_stream():
    rnd = play_state()
    bot = WorldShortlistBot(
        Heads(), seed=77, config=WorldShortlistConfig(
            cheap_worlds=2, refine_worlds=1, shortlist_size=2))
    bot.TRACTOR_LOCK = False
    bot.REPORT_RULE = "none"
    bot.REPORT_FOLD_WORLDS = 0
    parent_object = id(bot.rng)
    before = bot.rng.getstate()
    streams = []
    original = bot._sample_hands

    def sample(*args):
        streams.append(id(bot.rng))
        return original(*args)

    bot._sample_hands = sample
    bot.decide_play(rnd, rnd.turn)
    assert before != bot.rng.getstate()
    assert streams[:2] == [parent_object, parent_object]
    assert streams[2] != parent_object
    assert id(bot.rng) == parent_object
