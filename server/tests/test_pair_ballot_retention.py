from __future__ import annotations

import copy
import random
from collections import Counter

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import SUITS, TRUMP
from shengji.engine.game import Game
from shengji.engine.legal import suit_cards


def _opening_lead(seed: int = 861614):
    """Rebuild a natural cap-saturation witness without a frozen outcome."""
    game = Game(random.Random(seed))
    bots = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        declaration = bots[seat].decide_declare(rnd, seat)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    assert rnd.trick is not None and not rnd.trick.plays
    assert rnd.turn is not None
    return rnd, rnd.turn


def _pairs(rnd, seat: int) -> set[tuple[str, str]]:
    result = set()
    for suit in list(SUITS) + [TRUMP]:
        cards = suit_cards(rnd.hands[seat], suit, rnd.ordering)
        result.update((code, code) for code, count in Counter(cards).items()
                      if count >= 2)
    return result


def _action_set(bot, rnd, seat: int) -> set[tuple[str, ...]]:
    return {tuple(sorted(action)) for action in bot._candidates(rnd, seat)}


def test_retention_repairs_named_natural_cap_witness_at_equal_width():
    rnd, seat = _opening_lead()
    current = make_bot("mc", seed=1)
    retained = make_bot("mc", seed=1)
    retained.RETAIN_ALL_LEAD_PAIRS = True

    current_actions = current._candidates(rnd, seat)
    retained_actions = retained._candidates(rnd, seat)
    pairs = _pairs(rnd, seat)

    assert pairs - {tuple(sorted(a)) for a in current_actions} == {
        ("C2", "C2"), ("D2", "D2"), ("D5", "D5"),
        ("DA", "DA"), ("DK", "DK"), ("LJ", "LJ"),
    }
    assert pairs <= {tuple(sorted(a)) for a in retained_actions}
    assert retained_actions[0] == current_actions[0]
    assert len(current_actions) == len(retained_actions) == \
        retained.LEAD_MAX_CANDIDATES


def test_retained_source_uses_actor_information_only():
    rnd, seat = _opening_lead()
    bot = make_bot("mc", seed=1)
    bot.RETAIN_ALL_LEAD_PAIRS = True
    expected = _action_set(bot, rnd, seat)

    actor_view = copy.deepcopy(rnd)
    for other in range(4):
        if other != seat:
            actor_view.hands[other] = []
    actor_view.deck = []
    assert _action_set(bot, actor_view, seat) == expected


def test_retention_uses_the_lead_cap_even_if_wide_source_is_disabled():
    rnd, seat = _opening_lead()
    bot = make_bot("mc", seed=1)
    bot.WIDE_LEAD_BALLOT = False
    bot.RETAIN_ALL_LEAD_PAIRS = True
    actions = bot._candidates(rnd, seat)
    assert _pairs(rnd, seat) <= {tuple(sorted(a)) for a in actions}
    assert len(actions) > bot.MAX_CANDIDATES
    assert len(actions) <= bot.LEAD_MAX_CANDIDATES


def test_retention_refuses_a_cap_that_cannot_keep_its_contract():
    rnd, seat = _opening_lead()
    bot = make_bot("mc", seed=1)
    bot.RETAIN_ALL_LEAD_PAIRS = True
    bot.LEAD_MAX_CANDIDATES = 4
    with pytest.raises(ValueError, match="candidate zero and every legal pair"):
        bot._candidates(rnd, seat)
