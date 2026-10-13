"""Synthetic PV admission witness for the opt-in tractor reservation."""

from types import SimpleNamespace
import asyncio
import copy
import random

import numpy as np
import pytest

from shengji.engine.cards import Ordering
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.api import server as srv
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import _play_state, package  # noqa: F401
from shengji.train.policy_value_search import PolicyValueBot


class _Evaluator:
    pass


class _LengthEvaluator:
    """Deterministic value head: playing more cards is better."""

    backend = "numpy"

    def score(self, leaves, seat):
        return np.asarray([-len(leaf.hands[seat]) for leaf in leaves], dtype=np.float64)


def _round(*, follow=False):
    return SimpleNamespace(
        ordering=Ordering("H", "7"),
        trick=SimpleNamespace(plays=[object()] if follow else []),
    )


def _actions():
    return [
        ["C2"],                         # heuristic anchor
        ["S9"], ["D9"], ["C10"],       # policy-ranked non-tractors
        ["S3", "S3", "S4", "S4"],      # omitted pure tractor
    ]


def _pure_tractor(rnd, action):
    if len(action) < 4:
        return False
    if len({rnd.ordering.eff_suit(card) for card in action}) != 1:
        return False
    components = decompose(list(action), rnd.ordering).components
    return len(components) == 1 and components[0].pair_len >= 2


def _bot(**kwargs):
    options = {"candidates": 4, **kwargs}
    return PolicyValueBot(lambda *_: None, evaluator=_Evaluator(), **options)


def test_default_admission_keeps_byte_compatible_ranked_prefix():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot()
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 3]


def test_opt_in_reserves_one_pure_tractor_without_widening_or_moving_anchor():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot(tractor_reservation=True)
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 4]
    assert chosen[0] == 0 and len(chosen) == 4 and len(set(chosen)) == 4


def test_reservation_does_not_change_follow_admission():
    rnd, actions = _round(follow=True), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    plain = _bot()._admit(rnd, 0, actions, preferences, anchor_index=0)
    reserved = _bot(tractor_reservation=True)._admit(
        rnd, 0, actions, preferences, anchor_index=0)
    assert plain == reserved == [0, 1, 2, 3]


def test_existing_tractor_is_not_replaced_or_duplicated():
    rnd, actions = _round(), _actions()
    actions[2] = actions[4]
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot(tractor_reservation=True)
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 3]
    assert len(chosen) == len(set(chosen)) == 4


def test_diversity_setting_still_reserves_one_tractor():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    bot = _bot(admission_diversity=True, tractor_reservation=True)
    assert bot._admit(rnd, 0, actions, preferences, anchor_index=0) == [0, 1, 2, 4]


def test_k_one_and_no_tractor_are_safe_noops():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    assert _bot(candidates=1, tractor_reservation=True)._admit(
        rnd, 0, actions, preferences, anchor_index=0) == [0]
    no_tractor = [action for action in actions if len(action) < 4]
    assert _bot(tractor_reservation=True)._admit(
        rnd, 0, no_tractor, preferences[:4], anchor_index=0) == [0, 1, 2, 3]


def test_actual_enumerate_legal_to_admit_witness():
    rnd = Game(random.Random(625091990)).start_round()
    heuristic = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        declaration = heuristic.decide_declare(rnd, seat)
        if declaration:
            rnd.declare(seat, declaration)
    for seat in range(4):
        declaration = heuristic.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    seat = rnd.turn
    anchor = [rnd.hands[seat][0]]
    legal = enumerate_legal(rnd, seat, cap=4000, must_include=[anchor])
    pure_tractor = lambda action: (
        len(action) >= 4
        and len({rnd.ordering.eff_suit(card) for card in action}) == 1
        and len(decompose(list(action), rnd.ordering).components) == 1
        and decompose(list(action), rnd.ordering).components[0].pair_len >= 2)
    tractors = [i for i, action in enumerate(legal.actions) if pure_tractor(action)]
    assert tractors
    preferences = np.asarray([
        (-1000.0 if pure_tractor(action) else 100.0 - i)
        for i, action in enumerate(legal.actions)])
    anchor_index = next(i for i, action in enumerate(legal.actions) if action == anchor)
    plain = _bot()._admit(rnd, seat, legal.actions, preferences, anchor_index)
    reserved = _bot(tractor_reservation=True)._admit(
        rnd, seat, legal.actions, preferences, anchor_index)
    assert not any(pure_tractor(legal.actions[i]) for i in plain)
    assert any(pure_tractor(legal.actions[i]) for i in reserved)
    assert reserved[0] == anchor_index and len(reserved) == len(set(reserved)) == 4


def test_reservation_does_not_mutate_inputs_or_sampler_rng():
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    before_actions = [list(action) for action in actions]
    before_preferences = preferences.copy()
    bot = _bot(tractor_reservation=True)
    rng_before = bot.sampler.rng.getstate()
    bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert actions == before_actions and np.array_equal(preferences, before_preferences)
    assert bot.sampler.rng.getstate() == rng_before


def test_recipe_and_environment_identity_are_off_by_default_and_opt_in():
    off = pv.PVSearchConfig(checkpoint_sha256="f" * 64)
    assert "tractor_reservation" not in pv.recipe_payload(off)
    on = pv.PVSearchConfig(checkpoint_sha256="f" * 64, tractor_reservation=True)
    assert pv.recipe_payload(on)["tractor_reservation"] is True
    env = {"SHENGJI_PV_CKPT": "/tmp/model.npz",
           "SHENGJI_PV_SHA256": "f" * 64,
           "SHENGJI_PV_TRACTOR_RESERVATION": "1"}
    assert pv.pv_env_recipe(env)["tractor_reservation"] is True


def test_registry_factory_builds_real_package_bot_and_admits_tractor(package):
    path, sha = package
    entries = pv.pv_registry_entries(
        path, sha256=sha, worlds=2, candidates=4, cap=400,
        tractor_reservation=True)
    name, factory = next(iter(entries.items()))
    assert "-tr-" in name
    bot = factory(seed=7)
    rnd, actions = _round(), _actions()
    preferences = np.asarray([0.0, 4.0, 3.0, 2.0, 1.0])
    chosen = bot._admit(rnd, 0, actions, preferences, anchor_index=0)
    assert chosen == [0, 1, 2, 4]


def test_registry_api_snapshot_commit_scores_and_selects_reserved_tractor(package, monkeypatch):
    """The opt-in ballot survives the real registry/server transaction.

    The package remains real, while policy and value scoring are deterministic so
    the fixture isolates admission: policy ranks tractors below the top K, and the
    value fixture prefers the admitted four-card tractor.
    """
    path, sha = package

    def policy_scores(self, rnd, seat, actions, worlds):
        values = np.asarray([
            -1000.0 if _pure_tractor(rnd, action) else 10000.0 - i
            for i, action in enumerate(actions)
        ])
        return np.repeat(values[None, :], len(worlds), axis=0)

    monkeypatch.setattr(pv.PVSearchBot, "scores", policy_scores)

    # Keep the actual legal generator, but force its ordinary heuristic anchor to
    # be a legal singleton so the tractor is genuinely omitted by K=4.
    root = _play_state()
    seat = root.turn
    anchor = [root.hands[seat][0]]
    monkeypatch.setattr(HeuristicBot, "decide_play",
                        lambda self, rnd, s: [rnd.hands[s][0]])

    def build(enabled):
        entries = pv.pv_registry_entries(
            path, sha256=sha, worlds=2, candidates=4, cap=400,
            batch_size=16, tractor_reservation=enabled)
        _, factory = next(iter(entries.items()))
        bot = factory(seed=23)
        bot.evaluator = _LengthEvaluator()
        game = Game(random.Random(7))
        game.round = copy.deepcopy(root)
        rnd = game.round
        room = srv.Room(code=f"TR{int(enabled)}", game=game, bot=bot,
                        seats=[srv.Seat(str(i), is_bot=True) for i in range(4)],
                        log_dir=None)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda *args, **kwargs: None
        return room, rnd, bot

    async def run(enabled):
        room, rnd, bot = build(enabled)
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["admitted_indices"]
        actions = enumerate_legal(rnd, seat, cap=400,
                                  must_include=[anchor]).actions
        tractor = next(action for action in actions if _pure_tractor(rnd, action))
        if not enabled:
            assert not any(_pure_tractor(rnd, actions[i])
                           for i in record["admitted_indices"])
        else:
            assert any(_pure_tractor(rnd, actions[i])
                       for i in record["admitted_indices"])
            assert prepared.decision.cards == tractor
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)
        return prepared.decision.cards

    baseline, treatment = asyncio.run(run(False)), asyncio.run(run(True))
    assert len(baseline) < len(treatment)

