"""Parity and fallback gates for the entry-bound native Round.play."""
from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine import fast
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay

if not fast.HAVE_FAST:
    pytest.skip("compiled engine required", allow_module_level=True)


def _played_round(seed, trusted):
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
    if trusted:
        rnd._trusted_rollout = True
    return rnd, actors


def _state(rnd):
    return (
        rnd.phase, rnd.turn, rnd.attacker_points, rnd.kitty_bonus,
        rnd.last_trick_winner, [sorted(h) for h in rnd.hands],
        [(t.winner, t.points, [(p.seat, p.cards) for p in t.plays])
         for t in rnd.history],
    )


def test_routed_play_is_the_native_entry():
    assert fast.activate()
    assert Round.play is fast._fast.round_play


def test_full_trusted_round_matches_pure_state_for_state():
    assert fast.activate()
    bonus_rounds = zero_rounds = 0
    for seed in range(9101, 9141):
        native, actors_a = _played_round(seed, trusted=True)
        pure, actors_b = _played_round(seed, trusted=True)
        pure_play = fast._saved["Round.play"]
        while native.phase == "play":
            s = native.turn
            a = actors_a[s].decide_play(native, s)
            native.play(s, list(a))
            b = actors_b[pure.turn].decide_play(pure, pure.turn)
            assert sorted(a) == sorted(b)
            pure_play(pure, pure.turn, list(b))
            assert _state(native) == _state(pure)
        assert native.phase == pure.phase == "round_end"
        assert native.attacker_points == pure.attacker_points
        assert native.kitty_bonus == pure.kitty_bonus
        if native.kitty_bonus:
            bonus_rounds += 1
        else:
            zero_rounds += 1
        if bonus_rounds >= 3 and zero_rounds >= 3:
            break
    # Smart self-play never hands the attackers the final trick in this seed
    # range (measured 0/60), so natural rounds only exercise the zero-bonus
    # branch; the constructed test below supplies the bonus branch teeth.
    assert zero_rounds >= 3, zero_rounds


def test_untrusted_round_stays_on_pure_path():
    assert fast.activate()
    rnd, actors = _played_round(9111, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))
        if rnd.trick is not None and rnd.trick.plays:
            assert rnd.trick.incumbent is None
            assert rnd.trick.running_points is None


def test_wrong_turn_still_raises_via_pure():
    from shengji.engine.legal import IllegalPlay
    assert fast.activate()
    rnd, actors = _played_round(9112, trusted=True)
    s = rnd.turn
    wrong = (s + 1) % 4
    with pytest.raises(IllegalPlay):
        rnd.play(wrong, [rnd.hands[wrong][0]])


def test_hand_built_trick_defers_to_pure():
    assert fast.activate()
    rnd = Round("2", 0, random.Random(3))
    rnd._trusted_rollout = True
    rnd.phase = "play"
    rnd.turn = 3
    rnd.hands = [["S5"], ["S6"], ["S7"], ["S8", "C3"]]
    from shengji.engine.cards import Ordering
    rnd.ordering = Ordering("H", "2")
    rnd.banker = 0
    rnd.trick = Trick(leader=1, plays=[TrickPlay(1, ["S6"]),
                                       TrickPlay(2, ["S7"])])
    # incumbent is None on a hand-built trick: the native entry must defer to
    # pure, which resolves via full recomputation without cache assumptions.
    rnd.play(3, ["S8"])
    assert rnd.trick.plays[-1].cards == ["S8"]


def _terminal_round():
    """One-trick-remaining trusted round where the ATTACKER wins the last
    trick, exercising the kitty-bonus resolution branch deterministically."""
    from shengji.engine.cards import Ordering
    rnd = Round("2", 0, random.Random(1))
    rnd.banker = 0
    rnd.ordering = Ordering("S", "2")
    rnd.phase = "play"
    rnd.buried = ["S5", "S10", "SK", "C5", "C10", "CK", "D5", "D10"]
    rnd.hands = [["C3"], ["SA"], ["C4"], ["C6"]]
    rnd.trick = Trick(leader=1)
    rnd.turn = 1
    rnd._trusted_rollout = True
    return rnd


def test_attacker_last_trick_kitty_bonus_parity():
    assert fast.activate()
    native = _terminal_round()
    pure = _terminal_round()
    pure_play = fast._saved["Round.play"]
    for seat, cards in ((1, ["SA"]), (2, ["C4"]), (3, ["C6"]), (0, ["C3"])):
        native.play(seat, list(cards))
        pure_play(pure, seat, list(cards))
    assert native.phase == pure.phase == "round_end"
    assert native.last_trick_winner == pure.last_trick_winner == 1
    assert native.kitty_bonus == pure.kitty_bonus
    # the loud guard: the bonus branch must actually fire
    assert native.kitty_bonus > 0
    assert native.attacker_points == pure.attacker_points
