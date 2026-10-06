"""One-pass lead partition versus the historical five stable filters."""

import random

from shengji.ai import heuristic
from shengji.engine import fast
from shengji.engine.cards import Ordering, RANKS, TRUMP, make_deck
from shengji.engine.legal import suit_cards

from test_heuristic_lead_prefilter import _pure_lead, _round


def _old_groups(hand, ordering):
    return {s: suit_cards(hand, s, ordering)
            for s in (*heuristic.PLAIN_SUITS, TRUMP)}


def test_partition_matches_stable_filters_for_every_trump_configuration():
    rng = random.Random(20261006)
    deck = make_deck()
    for suit in (None, *heuristic.PLAIN_SUITS):
        for rank in RANKS:
            ordering = Ordering(suit, rank)
            for size in (0, 1, 2, 8, 25, 33, 108):
                hand = rng.sample(deck, size)
                before = hand.copy()
                got = heuristic._lead_suit_groups(hand, ordering)
                want = _old_groups(hand, ordering)
                assert list(got.items()) == list(want.items())
                assert hand == before
                # A caller cannot mutate the input or a later result via a bucket.
                got[TRUMP].append("BJ")
                assert hand == before
                assert heuristic._lead_suit_groups(hand, ordering) == want


def test_lead_actions_and_rng_match_five_filter_reference(monkeypatch):
    rng = random.Random(20261007)
    deck = make_deck()
    for suit in (None, *heuristic.PLAIN_SUITS):
        for rank in RANKS:
            for _ in range(12):
                hand = rng.sample(deck, rng.randint(1, 33))
                rnd = _round(hand, suit, rank)
                state = random.getstate()
                new = _pure_lead(heuristic.HeuristicBot(), rnd, 0)
                with monkeypatch.context() as patch:
                    patch.setattr(heuristic, "_lead_suit_groups", _old_groups)
                    old = _pure_lead(heuristic.HeuristicBot(), rnd, 0)
                assert new == old, (suit, rank, hand)
                assert rnd.hands[0] == hand
                assert random.getstate() == state


def test_custom_ordering_preserves_filter_call_order_and_unknown_tags(monkeypatch):
    # This is the pure duck-typed surface; the compiled helper requires a
    # real ordering context. Existing native-router tests cover that boundary.
    monkeypatch.setattr(heuristic, "suit_cards", fast._saved.get("suit_cards", suit_cards))
    class CustomOrdering:
        def __init__(self):
            self.calls = []

        def eff_suit(self, card):
            self.calls.append(card)
            return "unknown" if card == "BJ" else card[0]

    ordering = CustomOrdering()
    hand = ["S2", "BJ", "H3", "S2"]
    actual = heuristic._lead_suit_groups(hand, ordering)
    assert ordering.calls == hand * 5
    assert actual == {"S": ["S2", "S2"], "H": ["H3"], "D": [], "C": [], TRUMP: []}
