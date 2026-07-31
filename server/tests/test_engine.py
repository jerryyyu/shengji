import pytest

from shengji.engine.cards import BJ, LJ, Ordering, make_deck, points, total_points
from shengji.engine.combos import decompose, find_tractor_runs, has_tractor
from shengji.engine.legal import IllegalPlay, beats, validate_follow, validate_lead


def test_deck():
    deck = make_deck()
    assert len(deck) == 108
    assert deck.count("S5") == 2 and deck.count(BJ) == 2
    assert total_points(deck) == 200


def test_ordering_suited_trump():
    o = Ordering("H", "7")
    assert o.is_trump("H3") and o.is_trump("S7") and o.is_trump(LJ)
    assert not o.is_trump("S8")
    # ladder: H2..H6,H8..HA < S7/D7/C7 < H7 < LJ < BJ
    assert o.level("HA") < o.level("S7") == o.level("D7") < o.level("H7") \
        < o.level(LJ) < o.level(BJ)
    # plain suit skips the trump rank
    assert o.level("S8") == o.level("S6") + 1


def test_ordering_no_trump():
    o = Ordering(None, "2")
    assert o.is_trump("S2") and o.is_trump(BJ)
    assert not o.is_trump("SA")
    assert o.level("S2") == o.level("H2") < o.level(LJ) < o.level(BJ)


def test_decompose_pair_and_tractor():
    o = Ordering("H", "7")
    d = decompose(["S5", "S5"], o)
    assert d.shape() == ((1,), 0)
    # H6 H6 H8 H8 is a tractor across the removed trump rank
    d = decompose(["H6", "H6", "H8", "H8"], o)
    assert [c.kind for c in d.components] == ["tractor"]
    # trump-suit rank pair + little joker pair chain
    d = decompose(["H7", "H7", LJ, LJ], o)
    assert d.components[0].kind == "tractor"
    # two off-suit rank pairs share a level: NOT a tractor
    d = decompose(["S7", "S7", "D7", "D7"], o)
    assert sorted(c.kind for c in d.components) == ["pair", "pair"]
    assert d.shape() == ((1, 1), 0)


def test_throw_validation():
    o = Ordering("H", "2")
    hand = ["SA", "SK", "SK", "S3"]
    others = [["SQ", "S4"], ["H5"], ["C6"]]
    # SA + SKSK throw: nobody can beat either component
    play, msg = validate_lead(["SA", "SK", "SK"], hand, others, o)
    assert msg is None and len(play) == 3
    # S3 + SKSK: SQ... no single beats SK? SA is in hand not others; SQ<SK ok,
    # but S3 single is beatable by SQ -> forced to lowest component (S3)
    play, msg = validate_lead(["S3", "SK", "SK"], hand, others, o)
    assert play == ["S3"] and msg is not None


def test_follow_rules():
    o = Ordering("H", "2")
    lead = ["S5", "S5"]
    hand = ["S3", "S4", "S9", "S9", "C2", "C7"]
    # must play the pair
    with pytest.raises(IllegalPlay):
        validate_follow(["S3", "S4"], hand, lead, o)
    validate_follow(["S9", "S9"], hand, lead, o)
    # short-suited: must dump all lead-suit cards
    hand2 = ["S3", "C7", "C8", "D4"]
    with pytest.raises(IllegalPlay):
        validate_follow(["C7", "C8"], hand2, lead, o)
    validate_follow(["S3", "D4"], hand2, lead, o)
    # void: anything goes
    hand3 = ["C7", "C8", "D4"]
    validate_follow(["C7", "D4"], hand3, lead, o)


def test_tractor_obligation():
    o = Ordering("H", "2")
    lead = ["S5", "S5", "S6", "S6"]
    hand = ["S9", "S9", "S10", "S10", "S3", "SK"]
    with pytest.raises(IllegalPlay):
        validate_follow(["S9", "S9", "S3", "SK"], hand, lead, o)
    validate_follow(["S9", "S9", "S10", "S10"], hand, lead, o)


def test_beats():
    o = Ordering("H", "2")
    lead = ["S5", "S5"]
    top = decompose(lead, o).top_level()
    # higher in-suit pair wins
    won, _ = beats(["SK", "SK"], lead, "S", top, o)
    assert won
    # trump pair beats plain pair
    won, _ = beats(["H3", "H3"], lead, "S", top, o)
    assert won
    # two mismatched cards never win
    won, _ = beats(["SK", "SA"], lead, "S", top, o)
    assert not won
    # off-suit non-trump never wins
    won, _ = beats(["CA", "CA"], lead, "S", top, o)
    assert not won


def test_beats_alternative_decomposition():
    # Audit finding: hearts trump rank 7. Lead = two 2-tractors in spades.
    # HA-HA S7-S7 D7-D7 H7-H7 greedily decomposes as 3-tractor + pair, but is
    # also two 2-tractors ([HA,S7] + [D7,H7]) and must win as a ruff.
    o = Ordering("H", "7")
    lead = ["S3", "S3", "S4", "S4", "S9", "S9", "S10", "S10"]
    top = decompose(lead, o).top_level()
    ruff = ["HA", "HA", "S7", "S7", "D7", "D7", "H7", "H7"]
    won, _ = beats(ruff, lead, "S", top, o)
    assert won


def test_beats_pair_as_two_singles():
    # A trump pair can beat a thrown pair of singles by splitting.
    o = Ordering("H", "2")
    lead = ["S5", "S8"]
    top = decompose(lead, o).top_level()
    won, _ = beats(["H3", "H3"], lead, "S", top, o)
    assert won


def test_points():
    assert points("S5") == 5 and points("H10") == 10 and points("CK") == 10
    assert points("SA") == 0 and points(BJ) == 0
