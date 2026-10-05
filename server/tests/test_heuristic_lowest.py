"""Independent key oracle for point-seeking discard optimization."""
import random
from collections import Counter

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering, TRUMP, make_deck, points


@pytest.mark.parametrize("void_dump", [False, True])
def test_lowest_matches_original_key(void_dump):
    rng = random.Random(688)
    bot = HeuristicBot()
    bot.VOID_DUMP = void_dump
    for trump in [None, "S", "H", "D", "C"]:
        for rank in ["2", "7", "A"]:
            o = Ordering(trump, rank)
            for _ in range(40):
                cards = rng.sample(make_deck(), rng.randint(1, 25))
                before = cards[:]
                avoid = set(rng.sample(cards, rng.randint(0, len(cards))))
                suit_n = Counter(o.eff_suit(c) for c in cards)
                for seek in [False, True]:
                    for avoid_points in [False, True]:
                        def original(c):
                            trumpish = o.eff_suit(c) == TRUMP
                            vlen = suit_n[o.eff_suit(c)] if void_dump and not trumpish else 0
                            if seek:
                                return (c in avoid, -points(c), trumpish, o.level(c))
                            if avoid_points:
                                return (c in avoid, trumpish, points(c) > 0, vlen, o.level(c))
                            return (c in avoid, trumpish, vlen, o.level(c))
                        assert bot._lowest(cards, o, avoid_points, seek, avoid) == min(cards, key=original)
                        assert cards == before


def test_point_seek_stable_tie_and_empty_input():
    bot = HeuristicBot()
    o = Ordering(None, "2")
    for cards in [["S5", "H5"], ["H5", "S5"], ["S5", "S5"]]:
        assert bot._lowest(cards, o, seek_points=True) == cards[0]
    with pytest.raises(ValueError):
        bot._lowest([], o, seek_points=True)
