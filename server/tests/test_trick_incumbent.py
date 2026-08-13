"""Parity gate for the incremental trick incumbent.

``Round.play`` now maintains ``Trick.incumbent`` (winner_seat, eff_suit,
top_level) once per play.  These tests pin it to the legacy full
recomputation on real played rounds, and pin the fallback for
hand-constructed tricks that never went through ``play``.
"""

from __future__ import annotations

import random

from shengji.ai.registry import make_bot
from shengji.engine.cards import Ordering
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.legal import beats, uniform_suit
from shengji.engine.round import Round, Trick, TrickPlay


def _legacy_current_winner(rnd):
    lead = rnd.trick.plays[0].cards
    suit = uniform_suit(lead, rnd.ordering)
    top = decompose(lead, rnd.ordering).top_level()
    winner = rnd.trick.plays[0].seat
    for tp in rnd.trick.plays[1:]:
        won, t = beats(tp.cards, lead, suit, top, rnd.ordering)
        if won:
            winner, top = tp.seat, t
            suit = rnd.ordering.eff_suit(tp.cards[0])
    return winner, suit, top


def _play_round(seed):
    game = Game(random.Random(seed))
    actors = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        c = actors[s].decide_declare(rnd, s)
        if c:
            rnd.declare(s, c)
    for s in range(4):
        c = actors[s].decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, list(actors[rnd.banker].decide_bury(rnd, rnd.banker)))
    return rnd, actors


def test_incumbent_matches_legacy_recomputation_on_played_rounds():
    checked = 0
    for seed in (1201, 1202, 1203, 1204, 1205):
        rnd, actors = _play_round(seed)
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if rnd.trick is not None and rnd.trick.plays:
                assert rnd.trick.incumbent is not None
                assert rnd.trick.incumbent == _legacy_current_winner(rnd)
                checked += 1
            rnd.play(s, actors[s].decide_play(rnd, s))
    # A degenerate loop that never checked anything must fail loudly.
    assert checked > 100


def test_resolved_trick_winner_matches_legacy_on_played_rounds():
    for seed in (2301, 2302, 2303):
        rnd, actors = _play_round(seed)
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if rnd.trick is not None and len(rnd.trick.plays) == 3:
                # About to resolve: capture the legacy prediction first.
                pending = _legacy_current_winner(rnd)
                seat_cards = actors[s].decide_play(rnd, s)
                won, _ = beats(
                    list(seat_cards), rnd.trick.plays[0].cards,
                    pending[1], pending[2], rnd.ordering)
                expected = s if won else pending[0]
                rnd.play(s, seat_cards)
                assert rnd.last_trick.winner == expected
            else:
                rnd.play(s, actors[s].decide_play(rnd, s))


def test_hand_constructed_trick_falls_back_without_incumbent():
    rnd = Round("2", 0, random.Random(9))
    rnd.ordering = Ordering("S", "2")
    rnd.trick = Trick(leader=1, plays=[TrickPlay(1, ["H7"]),
                                       TrickPlay(2, ["H9"])])
    rnd.hands[3] = ["HK", "C3"]
    assert rnd.trick.incumbent is None
    bot = make_bot("smart")
    winner, suit, top = bot._current_winner(rnd)
    assert (winner, suit) == (2, "H")
