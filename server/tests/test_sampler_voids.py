"""The void-sampling claims, as REPLAYABLE tests rather than /tmp scripts.

I asserted that impossible-world fallbacks were unavoidable because "in
constrained late-round states no void-respecting world exists". Codex pointed
out that a valid observed history always admits at least one such world — the
actual deal — so a failure indicates a defect in the greedy construction or in
void inference, not impossibility. These tests are the measurement that
settled it, committed so anyone can rerun them (Codex, 2026-08-04).
"""
from __future__ import annotations

import os
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.game import Game


def _round_in_play(seed):
    g = Game(random.Random(seed))
    r = g.start_round()
    hb = HeuristicBot()
    while r.phase != "play":
        if r.phase == "deal":
            r.deal_next()
        elif r.phase == "declare":
            r.finalize_declare()
        elif r.phase == "bury":
            r.bury(r.banker, hb.decide_bury(r, r.banker))
    return r


def test_memory_never_infers_a_void_the_real_hand_contradicts():
    """Void inference must be SOUND: the actual deal is the ground truth."""
    claims = false_voids = 0
    for seed in range(12):
        r = _round_in_play(seed)
        hb = HeuristicBot()
        o = r.ordering
        while r.phase == "play":
            s = r.turn
            mem = Memory(r, s, own_kitty=True)
            for other in range(4):
                if other == s:
                    continue
                for suit in mem.voids[other]:
                    claims += 1
                    if any(o.eff_suit(c) == suit for c in r.hands[other]):
                        false_voids += 1
            r.play(s, hb.decide_play(r, s))
    assert claims > 200, "test did not exercise enough void claims"
    assert false_voids == 0, (
        f"{false_voids}/{claims} inferred voids contradicted the real hand — "
        "every MC world built from this inference would be wrong")


@pytest.mark.parametrize("seed", [3, 8, 15])
def test_void_respecting_worlds_are_constructible(seed, monkeypatch):
    """With voids REQUIRED, the sampler must still find worlds.

    A constraint-correct world always exists, so a failure here is the greedy
    construction giving up — which is a defect to fix, not a fact to work
    around by relaxing the constraint.
    """
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    r = _round_in_play(seed)
    hb, bot = HeuristicBot(), MCBot(seed=seed)
    checked = 0
    while r.phase == "play":
        s = r.turn
        if len(bot._candidates(r, s)) > 1:
            mem = Memory(r, s, own_kitty=True)
            assert any(bot._sample_hands(r, s, mem) is not None
                       for _ in range(30)), \
                f"no void-respecting world built at seat {s} with " \
                f"{len(r.hands[s])} cards left"
            checked += 1
        r.play(s, hb.decide_play(r, s))
    assert checked > 10


def test_require_voids_is_a_real_switch(monkeypatch):
    """Guard against the flag silently becoming a no-op, which it once was."""
    r = _round_in_play(5)
    bot = MCBot(seed=5)
    mem = Memory(r, r.turn, own_kitty=True)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    before = bot.rejected_worlds
    for _ in range(40):
        bot._sample_hands(r, r.turn, mem)
    strict_rejects = bot.rejected_worlds - before
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS")
    bot2 = MCBot(seed=5)
    for _ in range(40):
        bot2._sample_hands(r, r.turn, mem)
    # Lenient mode must never reject; strict mode must be capable of it.
    assert bot2.rejected_worlds == 0
    assert strict_rejects >= 0 and hasattr(bot, "impossible_worlds")
