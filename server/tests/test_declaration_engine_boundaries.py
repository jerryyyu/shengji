"""Declaration research assumptions exercised through the actual engine."""
from collections import Counter
import random

import pytest

from shengji.engine.cards import card_suit, is_joker, make_deck
from shengji.engine.round import IllegalPlay, Round


def dealt_round(banker=None):
    rnd = Round("7", banker, random.Random(117))
    # Preserve the physical deck while arranging a visible declaration ladder.
    for position, card in enumerate(("S7", "LJ", "BJ", "H7", "S7", "LJ", "BJ")):
        source = rnd.deck.index(card, position)
        rnd.deck[position], rnd.deck[source] = rnd.deck[source], rnd.deck[position]
    rnd.kitty = rnd.deck[100:]
    while rnd.phase == "deal":
        rnd.deal_next()
    assert Counter(c for hand in rnd.hands for c in hand) + Counter(rnd.kitty) == Counter(make_deck())
    return rnd


def test_only_stronger_redeclarations_are_legal_and_passes_reset():
    rnd = dealt_round()
    rnd.declare(0, ["S7"])
    rnd.pass_declare(1)
    rnd.pass_declare(3)
    assert rnd.passed == {1, 3}
    assert ["H7"] not in rnd.declare_options(3)
    with pytest.raises(IllegalPlay) as error:
        rnd.declare(3, ["H7"])
    assert str(error.value) == "Not a valid (stronger) declaration."
    assert rnd.passed == {1, 3}
    rnd.declare(0, ["S7", "S7"])
    assert rnd.declaration["strength"] == 2
    assert rnd.passed == set()
    with pytest.raises(IllegalPlay) as error:
        rnd.declare(0, ["S7"])
    assert str(error.value) == "Not a valid (stronger) declaration."
    rnd.declare(1, ["LJ", "LJ"])
    assert rnd.declaration["strength"] == 3
    rnd.declare(2, ["BJ", "BJ"])
    assert rnd.declaration["strength"] == 4
    assert all(rnd.declare_options(seat) == [] for seat in range(4))


@pytest.mark.parametrize("banker,expected_banker", [(None, 2), (1, 1)])
def test_nt_finalization_uses_final_winner_only_for_unknown_banker(banker, expected_banker):
    rnd = dealt_round(banker)
    rnd.declare(0, ["S7"])
    rnd.declare(2, ["BJ", "BJ"])
    rnd.finalize_declare()
    assert rnd.trump_is_nt is True and rnd.trump_suit is None
    assert rnd.banker == expected_banker and rnd.turn == expected_banker
    assert rnd.phase == "bury" and len(rnd.hands[expected_banker]) == 33
    assert all(rnd.declare_options(seat) == [] for seat in range(4))
    with pytest.raises(IllegalPlay) as error:
        rnd.declare(0, ["S7", "S7"])
    assert str(error.value) == "Declarations are closed."
    with pytest.raises(IllegalPlay) as error:
        rnd.pass_declare(0)
    assert str(error.value) == "Nothing to pass on."


def test_no_declaration_uses_first_nonjoker_in_real_eight_card_kitty():
    rnd = dealt_round()
    expected = card_suit(next(c for c in rnd.kitty if not is_joker(c)))
    for seat in range(4):
        rnd.pass_declare(seat)
    assert rnd.passed == {0, 1, 2, 3}
    assert rnd.phase == "declare"  # Caller, not pass(), closes the window.
    rnd.finalize_declare()
    assert rnd.banker == 0 and rnd.trump_suit == expected
    assert rnd.trump_is_nt is False and rnd.phase == "bury"
    # Eight kitty cards cannot all be jokers in this physical four-joker deck.
    assert sum(is_joker(c) for c in make_deck()) == 4 < 8
