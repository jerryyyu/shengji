"""Semantic parity for the native rollout-lead kernel."""

from __future__ import annotations

import random
from types import SimpleNamespace

from shengji.ai.heuristic import HeuristicBot
from shengji.engine import fast
from shengji.engine.cards import Ordering, make_deck


CONFIGS = (("S", "2"), ("H", "7"), ("C", "10"), ("D", "A"),
           (None, "7"), (None, "A"))


def _state(hand, config):
    suit, rank = config
    return SimpleNamespace(
        ordering=Ordering(suit, rank),
        hands=[list(hand), [], [], []],
    )


def test_native_lead_matches_pure_on_random_engine_hands():
    rng = random.Random(2026081301)
    deck = make_deck()
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    try:
        pure_bot = HeuristicBot()
        native_bot = HeuristicBot()
        for _ in range(20_000):
            hand = rng.sample(deck, rng.randint(1, 33))
            config = CONFIGS[rng.randrange(len(CONFIGS))]
            expected = pure_bot._lead(_state(hand, config), 0)
            actual = fast._fast.heuristic_lead(
                native_bot, _state(hand, config), 0)
            assert actual == expected, (hand, config, expected, actual)
    finally:
        if was_active:
            fast.activate()


def test_fast_activation_routes_and_restores_native_lead():
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    pure = HeuristicBot._lead
    try:
        assert fast.activate()
        assert HeuristicBot._lead is fast._lead_fast
        fast.deactivate()
        assert HeuristicBot._lead is pure
    finally:
        if was_active:
            fast.activate()
