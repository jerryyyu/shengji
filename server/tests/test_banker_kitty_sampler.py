from collections import Counter
import copy
import random

import pytest

from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.round import Round
from shengji.train.banker_kitty_sampler import banker_kitty_bounds, supported_bot_class


def declared_round(pair=False, declarer=0):
    for seed in range(4, 204):
        rnd = Round("2", 0, random.Random(seed))
        while rnd.phase == "deal":
            rnd.deal_next()
        options = rnd.declare_options(declarer)
        candidates = [o for o in options if len(o) == (2 if pair else 1)]
        if candidates:
            break
    else:
        raise AssertionError("fixture found no declaration")
    option = candidates[0]
    rnd.declare(declarer, option)
    rnd.finalize_declare()
    code = option[0]
    bury = [c for c in rnd.hands[0] if c == code]
    rest = list(rnd.hands[0])
    for c in bury:
        rest.remove(c)
    bury += rest[:8 - len(bury)]
    rnd.bury(0, bury)
    rnd.play(0, [rnd.hands[0][0]])
    return rnd, code


@pytest.mark.parametrize("pair", [False, True])
def test_real_world_consumer_has_banker_and_kitty_support(pair, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, code = declared_round(pair)
    mem = Memory(rnd, 1)
    old = dict(mem.known)
    bot = supported_bot_class(MCBot)(seed=93)
    worlds, attempts = sample_worlds(bot, rnd, 1, 64, mem=mem)
    assert len(worlds) == 64
    assert any(hands[0].count(code) == 0 for hands, _ in worlds)
    assert any(hands[0].count(code) > 0 for hands, _ in worlds)
    needed = len(rnd.declaration["cards"])
    for hands, kitty in worlds:
        assert hands[0].count(code) + kitty.count(code) >= needed
        assert hands[1] == sorted(rnd.hands[1])
        assert [len(h) for h in hands] == [len(h) for h in rnd.hands]
        assert len(kitty) == 8
        assert Counter(c for h in hands for c in h) + Counter(kitty) + mem.played == Counter(rnd.deck)
        for seat in range(4):
            assert not any(rnd.ordering.eff_suit(c) in mem.voids[seat] for c in hands[seat])
    assert mem.known == old  # immutable caller observation
    assert bot.accepted_worlds == len(worlds)
    assert bot.sample_attempts == attempts == bot.accepted_worlds + bot.failed_worlds
    assert bot.rejected_worlds >= bot.reject_cause["banker_kitty_declaration"] > 0


def test_nonbanker_pin_retains_exact_sample_stream():
    rnd, code = declared_round(declarer=2)
    mem = Memory(rnd, 1)
    first, fixed = MCBot(seed=96), supported_bot_class(MCBot)(seed=96)
    assert banker_kitty_bounds(rnd, 1, mem) == {}
    assert sample_worlds(first, rnd, 1, 16, mem=mem) == sample_worlds(fixed, rnd, 1, 16, mem=mem)
    assert first.rng.getstate() == fixed.rng.getstate()
    assert first._sampler_snapshot() == fixed._sampler_snapshot()


def test_actor_banker_retains_known_private_kitty_stream():
    rnd, _ = declared_round()
    mem = Memory(rnd, 0)
    first, fixed = MCBot(seed=95), supported_bot_class(MCBot)(seed=95)
    assert banker_kitty_bounds(rnd, 0, mem) == {}
    assert sample_worlds(first, rnd, 0, 16, mem=mem) == sample_worlds(fixed, rnd, 0, 16, mem=mem)
    assert first.rng.getstate() == fixed.rng.getstate()


def test_only_bankers_plays_reduce_union_bound():
    rnd, code = declared_round(pair=True)
    mem = Memory(rnd, 1)
    assert banker_kitty_bounds(rnd, 1, mem)[code] == 2
    mem.played_by[2][code] = 1
    assert banker_kitty_bounds(rnd, 1, mem)[code] == 2
    mem.played_by[0][code] = 1
    assert banker_kitty_bounds(rnd, 1, mem)[code] == 1
    mem.played_by[0][code] = 2
    assert banker_kitty_bounds(rnd, 1, mem) == {}


def test_hidden_twins_produce_identical_worlds_and_rng():
    rnd, code = declared_round()
    twin = copy.deepcopy(rnd)
    index = twin.buried.index(code)
    twin.buried[index], twin.hands[0][0] = twin.hands[0][0], twin.buried[index]
    first, second = supported_bot_class(MCBot)(seed=19), supported_bot_class(MCBot)(seed=19)
    a = sample_worlds(first, rnd, 1, 16)
    b = sample_worlds(second, twin, 1, 16)
    assert a == b
    assert first.rng.getstate() == second.rng.getstate()


def test_union_refusal_reaches_consumer_counters_and_cap(monkeypatch):
    rnd, code = declared_round()
    def invalid(self, rnd, seat, mem):
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return {0: ["C3"], 2: [], 3: []}, ["D3"]
    monkeypatch.setattr(MCBot, "_sample_hands", invalid)
    bot = supported_bot_class(MCBot)(seed=0)
    bot.SAMPLE_ATTEMPT_FACTOR = 3
    worlds, attempts = sample_worlds(bot, rnd, 1, 2)
    assert worlds == [] and attempts == 6
    assert bot.accepted_worlds == 0
    assert bot.failed_worlds == bot.rejected_worlds == 6
    assert bot.reject_cause["banker_kitty_declaration"] == 6


def test_legacy_registry_class_is_not_modified():
    from shengji.ai.registry import REGISTRY
    base = REGISTRY["mc-s0-report-lcb"]
    assert supported_bot_class(base) is not base
    assert not hasattr(base, "SAMPLER_SUPPORT_RECIPE")


def test_w32_ranking_and_mc_folds_use_corrected_sampler(monkeypatch):
    from shengji.train.cwv_bury_policy import CWVBuryBot
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    import shengji.train.cwv_shortlist as shortlist

    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, code = declared_round()
    class Values:
        def score(self, positions, seat, **kwargs):
            return [float(r.attacker_points) for r in positions]
    bot = supported_bot_class(CWVBuryBot)(Values(), seed=17, arm="hybrid",
        config=CWVShortlistConfig(worlds=4, selection_worlds=4, alternatives=4),
        reuse_successors=True)
    bot.REPORT_FOLD_WORLDS = 30
    ranking_worlds = []
    production_worlds = []
    original = shortlist.sample_worlds
    def capture(*args, **kwargs):
        worlds, attempts = original(*args, **kwargs)
        ranking_worlds.extend(worlds)
        return worlds, attempts
    monkeypatch.setattr(shortlist, "sample_worlds", capture)
    def rollout(r, s, hands, buried, action, **kwargs):
        production_worlds.append((hands, buried))
        return float(sum(ord(c) for card in action for c in card))
    monkeypatch.setattr(bot, "_rollout", rollout)
    picked = bot.decide_play(rnd, 1)
    assert picked
    assert len(ranking_worlds) == 4
    assert production_worlds
    for hands, buried in ranking_worlds + production_worlds:
        assert hands[0].count(code) + buried.count(code) >= 1
    assert bot.last_decision_record["cwv_shortlist"]["cheap_sampler_delta"]["accepted_worlds"] == 4
    assert bot.accepted_worlds > 4
    assert bot.sample_attempts == bot.accepted_worlds + bot.failed_worlds
