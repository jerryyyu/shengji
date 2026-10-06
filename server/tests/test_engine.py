import pytest

from shengji.engine.cards import BJ, LJ, Ordering, make_deck, points, total_points
from shengji.engine.combos import decompose, find_tractor_runs, has_tractor
from shengji.engine.legal import IllegalPlay, beats, validate_follow, validate_lead


def test_uniform_singleton_matches_set_reference_across_all_orderings():
    from shengji.engine import fast, legal
    from shengji.engine.cards import RANKS, SUITS

    uniform = fast._saved.get("uniform_suit", legal.uniform_suit)
    deck = make_deck()[:54]
    for suit in (None, *SUITS):
        for rank in RANKS:
            ordering = Ordering(suit, rank)
            for play in [[], *[[c] for c in deck], *[[c, c] for c in deck], deck]:
                suits = {ordering.eff_suit(c) for c in play}
                expected = suits.pop() if len(suits) == 1 else None
                before = play.copy()
                assert uniform(play, ordering) == expected
                assert play == before


def test_uniform_singleton_preserves_general_iterable_and_ordering_behavior():
    from shengji.engine import fast, legal

    uniform = fast._saved.get("uniform_suit", legal.uniform_suit)
    ordering = Ordering("H", "7")
    assert uniform(iter(["S2"]), ordering) == "S"
    assert uniform(("S2", "H2"), ordering) is None

    class CustomOrdering:
        def eff_suit(self, card):
            return []  # historical set construction must still reject this

    with pytest.raises(TypeError):
        uniform(["S2"], CustomOrdering())


def test_pair_free_follow_skips_pair_counts(monkeypatch):
    from shengji.engine import fast, legal
    from shengji.engine.cards import RANKS

    follow = fast._saved.get("validate_follow", legal.validate_follow)

    def forbidden(*args):
        raise AssertionError("pair-free lead must not count pairs")

    monkeypatch.setattr(legal, "pair_count", forbidden)
    for suit in (None, "S", "H", "D", "C"):
        for rank in RANKS:
            ordering = Ordering(suit, rank)
            cards = [c for c in dict.fromkeys(make_deck())
                     if ordering.eff_suit(c) == "S"]
            if len(cards) < 3:
                cards = [c for c in dict.fromkeys(make_deck())
                         if ordering.eff_suit(c) == "D"]
            a, b, c = cards[:3]
            hand = [a, a, b, c]
            before = list(hand)
            follow([b], hand, [a], ordering)
            follow([b, c], hand, [a, b], ordering)
            assert hand == before
            # A missing-card failure must still happen before shape checks.
            with pytest.raises(IllegalPlay):
                follow([b, b], hand, [a, b], ordering)


def test_pair_follow_still_requires_available_pair():
    from shengji.engine import fast, legal

    follow = fast._saved.get("validate_follow", legal.validate_follow)
    ordering = Ordering("H", "7")
    hand = ["S3", "S3", "S5", "S6"]
    with pytest.raises(IllegalPlay, match="must play pairs"):
        follow(["S5", "S6"], hand, ["S3", "S3"], ordering)
    follow(["S3", "S3"], hand, ["S3", "S3"], ordering)


def test_single_beats_specialization_matches_legacy(monkeypatch):
    """Singleton beats agrees with decomposition and bypasses both helpers."""
    from shengji.engine import fast, legal
    from shengji.engine.cards import RANKS, TRUMP

    active = bool(fast._saved)
    if active:
        fast.deactivate()
    try:
        pure_uniform_suit = legal.uniform_suit
        pure_decompose = legal.decompose
        pure_decompose_matching = legal.decompose_matching

        def legacy(challenger, lead, incumbent_suit, incumbent_top, ordering):
            eff = pure_uniform_suit(challenger, ordering)
            if eff is None:
                return False, 0
            lead_dec = pure_decompose(lead, ordering)
            ch_dec = pure_decompose_matching(
                challenger, ordering, lead_dec.shape())
            if ch_dec is None:
                return False, 0
            top = ch_dec.top_level()
            if eff == incumbent_suit:
                return top > incumbent_top, top
            if eff == TRUMP:
                return True, top
            return False, 0

        # The non-singleton route remains decomposition-based.
        ordering = Ordering("H", "7")
        lead = ["S5", "S5"]
        challenger = ["SK", "SK"]
        assert legal.beats(challenger, lead, "S", 2, ordering) == \
            legacy(challenger, lead, "S", 2, ordering)

        def forbidden(*args, **kwargs):
            raise AssertionError("singleton beats called a decomposition helper")

        with monkeypatch.context() as patch:
            patch.setattr(legal, "decompose", forbidden)
            patch.setattr(legal, "decompose_matching", forbidden)

            cards = sorted(set(make_deck()))
            incumbent_suits = ("S", "H", "D", "C", TRUMP)
            for trump_suit in (None, "S", "H", "D", "C"):
                for trump_rank in RANKS:
                    ordering = Ordering(trump_suit, trump_rank)
                    for lead_card in cards:
                        for challenger_card in cards:
                            lead = [lead_card]
                            challenger = [challenger_card]
                            top = ordering.level(challenger_card)
                            for incumbent_suit in incumbent_suits:
                                boundaries = (top - 1, top, top + 1) \
                                    if incumbent_suit == ordering.eff_suit(challenger_card) \
                                    else (top,)
                                for incumbent_top in boundaries:
                                    before = (list(challenger), list(lead))
                                    got = legal.beats(
                                        challenger, lead, incumbent_suit,
                                        incumbent_top, ordering)
                                    assert got == legacy(
                                        challenger, lead, incumbent_suit,
                                        incumbent_top, ordering)
                                    assert (challenger, lead) == before
    finally:
        # Restore pure helper bindings before compiled routing snapshots them.
        monkeypatch.undo()
        if active:
            fast.activate()


def test_submultiset_matches_counter_reference_without_mutation():
    from collections import Counter
    from itertools import product
    from shengji.engine.legal import _is_submultiset

    pools = [list(cards) for n in range(5)
             for cards in product(("S2", "H5", BJ), repeat=n)]
    for small in pools:
        for big in pools:
            before = (list(small), list(big))
            required, available = Counter(small), Counter(big)
            expected = all(available[c] >= n for c, n in required.items())
            assert _is_submultiset(small, big) == expected
            assert (small, big) == before


def test_small_submultiset_avoids_counter_but_keeps_multiplicity(monkeypatch):
    from shengji.engine import legal

    original = legal.Counter
    calls = []

    def counted(cards):
        calls.append(list(cards))
        return original(cards)

    monkeypatch.setattr(legal, "Counter", counted)
    assert legal._is_submultiset([], [])
    assert legal._is_submultiset([], ["S2"])
    assert legal._is_submultiset(["S2"], ["H5", "S2", "S2"])
    assert not legal._is_submultiset(["S2"], [])
    assert not legal._is_submultiset(["S2"], ["H5"])
    assert calls == []
    assert not legal._is_submultiset(["S2", "S2"], ["S2", "H5"])
    assert len(calls) == 2


def test_small_ownership_fast_path_preserves_legality_rejections():
    from shengji.engine.legal import check_in_hand

    for play in ([], ["H5"], ["S2", "S2"]):
        with pytest.raises(IllegalPlay):
            check_in_hand(["S2"], play)
    check_in_hand(["S2", "H5"], ["S2"])
    o = Ordering("H", "7")
    # Being void permits an off-suit card, but cannot excuse an unowned card.
    validate_follow(["H5"], ["H5"], ["S2"], o)
    with pytest.raises(IllegalPlay):
        validate_follow(["H5"], ["S3", "H5"], ["S2"], o)
    with pytest.raises(IllegalPlay):
        validate_follow(["H5"], ["D4"], ["S2"], o)


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
    # but S3 single is beatable by SQ -> forced to the BEATEN component (S3)
    play, msg = validate_lead(["S3", "SK", "SK"], hand, others, o)
    assert play == ["S3"] and msg is not None
    # low pair + boss ace: if the PAIR is the beatable part, the penalty
    # forces the pair (not the ace — user-raised, standard rule)
    hand2 = ["SA", "S5", "S5"]
    others2 = [["S9", "S9"], ["H2"], ["C3"]]  # S9 pair beats S5 pair
    play, msg = validate_lead(["SA", "S5", "S5"], hand2, others2, o)
    assert play == ["S5", "S5"] and msg is not None


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


def test_v3_lead_equivalence_accounts_for_residual_structure():
    """Cards tied in LEVEL are not interchangeable actions.

    Under trump rank 7, S7 and C7 tie in effective level. From a hand of
    S7-S7-C7, leading S7 breaks the pair while leading C7 keeps it. V3's first
    version offered one representative per level and silently dropped the
    difference (Codex P0, 2026-08-04).
    """
    from shengji.engine.cards import Ordering
    from shengji.engine.combos import decompose

    o = Ordering(trump_suit="H", trump_rank="7")
    hand = ["S7", "S7", "C7"]
    shapes = set()
    for play in ("S7", "C7"):
        rest = list(hand)
        rest.remove(play)
        shapes.add(decompose(rest, o).shape())
    assert len(shapes) == 2, (
        "S7 and C7 leave different residual structure, so an equivalence "
        "keyed only on effective level is unsound")
def test_heuristic_single_forced_follow_preserves_selection_and_inputs():
    """Single-lead shortcut: independent key, all trumps/preferences, duplicates."""
    from collections import Counter
    import random
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.cards import Ordering, TRUMP, make_deck, points
    from shengji.engine.legal import validate_follow

    rng = random.Random(60105)
    bot = HeuristicBot()
    for trump in (None, "S", "H", "D", "C"):
        for rank in ("2", "7", "A"):
            ordering = Ordering(trump, rank)
            for _ in range(40):
                hand = rng.sample(make_deck(), rng.randint(1, 25))
                lead = [rng.choice(make_deck())]
                avoid = set(rng.sample(hand, rng.randint(0, len(hand))))
                original = (list(hand), list(lead), set(avoid))
                eligible = [c for c in hand if ordering.eff_suit(c) == ordering.eff_suit(lead[0])]
                eligible = eligible or hand
                counts = Counter(ordering.eff_suit(c) for c in eligible)
                for dump in (False, True):
                    bot.VOID_DUMP = dump
                    for prefer in (False, True):
                        def key(card):
                            suit = ordering.eff_suit(card)
                            if prefer:
                                return (card in avoid, -points(card), suit == TRUMP, ordering.level(card))
                            length = counts[suit] if dump and suit != TRUMP else 0
                            return (card in avoid, suit == TRUMP, points(card) > 0, length, ordering.level(card))
                        expected = [min(eligible, key=key)]
                        actual = bot._forced_follow(hand, lead, ordering, prefer, avoid)
                        assert actual == expected
                        validate_follow(actual, hand, lead, ordering)
                        assert (hand, lead, avoid) == original
