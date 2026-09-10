from __future__ import annotations

import random

import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.engine.round import Round
from shengji.engine.cards import RANKS
from shengji.train.declare_policy import (
    DeclareView,
    capture_declare_view,
    choose_declaration,
)


def _natural_views(seed: int, rank: str, banker: int | None):
    rnd = Round(rank, banker, random.Random(seed))
    bot = SmartBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        yield rnd, seat, capture_declare_view(rnd, seat)
        action = bot.decide_declare(rnd, seat)
        if action:
            rnd.declare(seat, action)
    for seat in range(4):
        yield rnd, seat, capture_declare_view(rnd, seat, final=True)
        action = bot.decide_declare(rnd, seat, final=True)
        if action:
            rnd.declare(seat, action)


def test_baseline_matches_smartbot_on_seeded_natural_deals_and_final_calls():
    for index, (rank, banker) in enumerate(
            zip((RANKS[0], RANKS[3], RANKS[8], RANKS[11], RANKS[12]),
                (None, 0, 1, 2, 3))):
        for rnd, seat, view in _natural_views(3 + index * 37, rank, banker):
            expected = SmartBot().decide_declare(rnd, seat, final=view.final)
            assert choose_declaration(view) == expected


def test_view_is_frozen_and_capture_does_not_read_hidden_state():
    class PoisonRound:
        trump_rank = "5"
        phase = "deal"
        banker = 2
        declaration = None

        def __init__(self):
            self.hands = [["S5", "S5", "S2"]] + [[] for _ in range(3)]

        @property
        def deck(self):
            raise AssertionError("capture read deck")

        @property
        def kitty(self):
            raise AssertionError("capture read kitty")

        def declare_options(self, seat):
            assert seat == 0
            return [["S5"], ["S5", "S5"]]

    view = capture_declare_view(PoisonRound(), 0)
    assert view == DeclareView(0, "5", ("S5", "S5", "S2"),
                               (("S5",), ("S5", "S5")), "deal", False,
                               2, None)
    with pytest.raises(AttributeError):
        view.seat = 1


def test_hidden_twins_and_future_draws_do_not_change_view_or_choice():
    class ActorOnlyHands:
        def __init__(self, actor_hand, other_hands):
            self._hands = [actor_hand, *other_hands]

        def __getitem__(self, seat):
            if seat != 0:
                raise AssertionError("non-actor hand was read")
            return self._hands[seat]

    def twin(other_hands, seed, future, kitty):
        rnd = Round("5", 2, random.Random(seed))
        rnd.hands = ActorOnlyHands(["S5", "S5", "S2", "S3"], other_hands)
        rnd.deck = list(future)
        rnd.kitty = list(kitty)
        return rnd

    first = capture_declare_view(twin([["HA"], ["D2"], ["C3"]], 1,
                                      ["BJ", "C2"], ["S4"]), 0)
    second = capture_declare_view(twin([["C2", "D10"], ["LJ"], ["H4"]], 2,
                                       ["S3", "D4"], ["H5", "H6"]), 0)
    assert first == second
    assert choose_declaration(first, "pair-eager") == \
        choose_declaration(second, "pair-eager")


def test_capture_and_choice_do_not_consume_rng():
    rng = random.Random(123)
    rnd = Game(rng).start_round()
    rnd.deal_next()
    before = rng.getstate()
    view = capture_declare_view(rnd, 0)
    choose_declaration(view, "pair-eager")
    assert rng.getstate() == before


@pytest.mark.parametrize("cards, expected", [
    (("S5", "S5", "S2", "S3"), ["S5", "S5"]),  # score 6
    (("S5", "S5", "S2", "S3", "S4"), ["S5", "S5"]),  # score 7
])
def test_pair_eager_relaxes_only_a_during_deal_suited_pair(cards, expected):
    view = DeclareView(0, "5", cards,
                       (("S5",), ("S5", "S5")), "deal", False, None, None)
    assert choose_declaration(view) is None
    assert choose_declaration(view, "pair-eager") == expected


def test_pair_eager_keeps_baseline_and_does_not_ease_singleton_or_nt():
    accepted = DeclareView(0, "5", ("S5", "S5", "S2", "S3", "S4", "S6"),
                           (("S5",), ("S5", "S5")), "deal", False, None, None)
    assert choose_declaration(accepted) == ["S5", "S5"]
    assert choose_declaration(accepted, "pair-eager") == ["S5", "S5"]

    singleton = DeclareView(0, "5", ("S5", "S2", "S3", "S4"),
                            (("S5",),), "deal", False, None, None)
    assert choose_declaration(singleton, "pair-eager") is None

    no_nt_support = DeclareView(0, "5", ("LJ", "LJ", "S5", "S5"),
                                 (("LJ", "LJ"),), "deal", False, None, None)
    assert choose_declaration(no_nt_support, "pair-eager") is None


def test_pair_eager_final_and_unknown_arm():
    view = DeclareView(0, "5", ("S5", "S5", "S2", "S3"),
                       (("S5",), ("S5", "S5")), "declare", True, None, None)
    assert choose_declaration(view, "pair-eager") == ["S5", "S5"]
    with pytest.raises(ValueError, match="unknown declaration arm"):
        choose_declaration(view, "other")


def test_declare_phase_without_final_flag_uses_during_deal_threshold():
    view = DeclareView(0, "5", ("S5", "S5", "S2", "S3"),
                       (("S5",), ("S5", "S5")), "declare", False, None, None)
    assert choose_declaration(view) is None
    assert choose_declaration(view, "pair-eager") == ["S5", "S5"]


def test_choice_is_always_one_of_captured_options():
    view = DeclareView(0, "5", ("S5", "S5", "S2", "S3"),
                       (("S5",), ("S5", "S5")), "deal", False, None, None)
    action = choose_declaration(view, "pair-eager")
    assert action is None or tuple(action) in view.options
