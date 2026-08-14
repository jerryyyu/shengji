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
        rnd.last_trick_winner, [list(h) for h in rnd.hands],
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


# ---------------------------------------------------------------- witnesses
# Codex HOLD findings on PR #102 head 49ba308: the native entry must never
# partially mutate a state it cannot finish, must honor subclass helper
# overrides by deferring, and must be provably non-vacuous.

def _snapshot_all(rnd):
    t = rnd.trick
    return (list(map(list, rnd.hands)), rnd.phase, rnd.turn, rnd.message,
            rnd.attacker_points, rnd.kitty_bonus,
            None if t is None else (t.leader, t.incumbent, t.running_points,
                                    [(p.seat, list(p.cards)) for p in t.plays]))


def _mid_trick_round(seed=9301):
    rnd, actors = _played_round(seed, trusted=True)
    while rnd.phase == "play" and (rnd.trick is None or not rnd.trick.plays):
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))
    return rnd, actors


def test_huge_int_caches_native_matches_pure_exactly():
    """Codex finding 1: the native entry must never mutate before its own
    narrowing raise.  Repaired contract: the entry defers pre-mutation, so
    whatever the pure path does with the hostile value (including raising
    from routed kernels mid-maintenance) happens identically both ways."""
    assert fast.activate()
    pure_play = fast._saved["Round.play"]
    for field, value in (("incumbent", (1, "T", 10 ** 100)),
                         ("running_points", 10 ** 100)):
        native, actors = _mid_trick_round()
        pure, _ = _mid_trick_round()
        setattr(native.trick, field, value)
        setattr(pure.trick, field, value)
        seat = native.turn
        cards = actors[seat].decide_play(copy.deepcopy(native), seat)
        native_exc = pure_exc = None
        try:
            native.play(seat, list(cards))
        except Exception as exc:  # noqa: BLE001 - parity witness
            native_exc = type(exc)
        try:
            pure_play(pure, seat, list(cards))
        except Exception as exc:  # noqa: BLE001 - parity witness
            pure_exc = type(exc)
        assert native_exc is pure_exc, (field, native_exc, pure_exc)
        assert _snapshot_all(native) == _snapshot_all(pure), field


def test_round_subclass_remove_override_is_honored():
    assert fast.activate()
    calls = []

    class Counting(Round):
        def _remove(self, seat, cards):
            calls.append(seat)
            super()._remove(seat, cards)

    rnd, actors = _mid_trick_round(9302)
    sub = copy.deepcopy(rnd)
    sub.__class__ = Counting
    seat = sub.turn
    cards = actors[seat].decide_play(copy.deepcopy(sub), seat)
    sub.play(seat, list(cards))
    assert calls == [seat], "subclass _remove was bypassed by the native entry"


def test_non_list_member_hand_defers_untouched():
    assert fast.activate()
    rnd, actors = _mid_trick_round(9303)
    seat = rnd.turn
    cards = actors[seat].decide_play(copy.deepcopy(rnd), seat)
    victim = next(i for i in range(4) if i != seat)
    rnd.hands[victim] = tuple(rnd.hands[victim])
    before = _snapshot_all(rnd)
    pure, _ = _mid_trick_round(9303)
    pure.hands[victim] = tuple(pure.hands[victim])
    pure_play = fast._saved["Round.play"]
    native_exc = pure_exc = None
    try:
        rnd.play(seat, list(cards))
    except Exception as exc:  # noqa: BLE001 - parity witness
        native_exc = type(exc)
        assert _snapshot_all(rnd) == before, "native mutated before raise"
    try:
        pure_play(pure, seat, list(cards))
    except Exception as exc:  # noqa: BLE001 - parity witness
        pure_exc = type(exc)
    assert native_exc is pure_exc
    assert _snapshot_all(rnd) == _snapshot_all(pure)


def test_native_body_is_not_vacuously_bypassed():
    assert fast.activate()
    from shengji.engine.round import KITTY_MULTIPLIER, TrickPlay

    class Sentinel(Exception):
        pass

    def raising_pure(rnd, seat, cards):
        raise Sentinel

    rnd, actors = _mid_trick_round(9304)
    seat = rnd.turn
    cards = actors[seat].decide_play(copy.deepcopy(rnd), seat)
    fast._fast.set_play_deps(Round, Trick, TrickPlay, raising_pure,
                             KITTY_MULTIPLIER)
    try:
        # valid trusted follow: the native body must handle it entirely,
        # never touching the (raising) pure fallback
        rnd.play(seat, list(cards))
        # malformed cards: must defer, which the sentinel proves loudly
        if rnd.phase == "play" and rnd.trick is not None and rnd.trick.plays:
            with pytest.raises(Sentinel):
                rnd.play(rnd.turn, ["XX"])
    finally:
        fast._fast.set_play_deps(Round, Trick, TrickPlay,
                                 fast._saved["Round.play"], KITTY_MULTIPLIER)
