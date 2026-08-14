"""Parity gate for the entry-bound native follow policy.

Under compiled routing ``HeuristicBot._follow`` IS ``_fast.heuristic_follow``:
the entry carries its own guards and defers to the registered pure method
whenever the trusted-rollout preconditions do not hold.  Inside the trusted
contract the native result must equal the pure result exactly.
"""

from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine import fast
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay

if not fast.HAVE_FAST:
    pytest.skip("compiled engine required", allow_module_level=True)

assert fast.activate()
PURE_FOLLOW = fast._saved["HeuristicBot._follow"]


def _play_round(seed, trusted):
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


def test_routed_follow_is_the_native_entry():
    from shengji.ai.heuristic import HeuristicBot
    assert HeuristicBot._follow is fast._fast.heuristic_follow


def test_native_matches_pure_on_every_trusted_follow_state():
    bot = make_bot("smart")
    checked = native_reached = 0
    for seed in (4501, 4502, 4503, 4504, 4505):
        rnd, actors = _play_round(seed, trusted=True)
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if rnd.trick is not None and rnd.trick.plays:
                native = fast._fast.heuristic_follow(bot, rnd, s)
                pure = PURE_FOLLOW(bot, rnd, s)
                assert native == pure, (seed, s, native, pure)
                checked += 1
                if rnd.trick.incumbent is not None:
                    native_reached += 1
            rnd.play(s, actors[s].decide_play(rnd, s))
    assert checked > 100
    # the loud guard: the native body must actually have been exercised,
    # not satisfied vacuously through the pure fallback
    assert native_reached > 100


def test_untrusted_rounds_defer_to_pure():
    bot = make_bot("smart")
    rnd, actors = _play_round(4611, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and rnd.trick.plays:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    s = rnd.turn
    assert rnd.trick.incumbent is None  # repair: no cache off-contract
    assert bot._follow(rnd, s) == PURE_FOLLOW(bot, rnd, s)


def test_hand_constructed_trick_defers_to_pure():
    rnd = Round("2", 0, random.Random(11))
    rnd.ordering = Ordering("S", "2")
    rnd.trick = Trick(leader=1, plays=[TrickPlay(1, ["H7"]),
                                       TrickPlay(2, ["H9"])])
    rnd.hands[3] = ["HK", "C3"]
    bot = make_bot("smart")
    assert bot._follow(rnd, 3) == PURE_FOLLOW(bot, rnd, 3)


def test_malformed_running_points_defers_to_pure():
    bot = make_bot("smart")
    rnd, actors = _play_round(4612, trusted=True)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and rnd.trick.plays:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    s = rnd.turn
    rnd.trick.running_points = None
    assert bot._follow(rnd, s) == PURE_FOLLOW(bot, rnd, s)


def test_unbounded_or_out_of_domain_caches_defer_before_native_cast():
    bot = make_bot("smart")
    rnd, actors = _play_round(4613, trusted=True)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and rnd.trick.plays:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    s = rnd.turn
    incumbent = rnd.trick.incumbent
    cases = (
        ("incumbent", (10**100, incumbent[1], incumbent[2])),
        ("incumbent", (-(10**100), incumbent[1], incumbent[2])),
        ("incumbent", (incumbent[0], incumbent[1], 10**100)),
        ("incumbent", (incumbent[0], incumbent[1], -(10**100))),
        ("incumbent", (incumbent[0], "X", incumbent[2])),
        ("running_points", 10**100),
        ("running_points", -(10**100)),
    )
    for field, value in cases:
        native = copy.deepcopy(rnd)
        pure = copy.deepcopy(rnd)
        setattr(native.trick, field, value)
        setattr(pure.trick, field, value)
        assert fast._fast.heuristic_follow(bot, native, s) == \
            PURE_FOLLOW(bot, pure, s), (field, value)


def test_malformed_cache_fallback_and_normal_native_route_are_nonvacuous():
    class Sentinel(Exception):
        pass

    def raising_pure(bot, rnd, seat):
        raise Sentinel

    bot = make_bot("smart")
    rnd, actors = _play_round(4614, trusted=True)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and rnd.trick.plays:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    s = rnd.turn
    fast._fast.set_follow_fallback(Ordering, raising_pure)
    try:
        # A real cached state must stay entirely on the native body.
        assert fast._fast.heuristic_follow(bot, rnd, s)
        rnd.trick.running_points = 10**100
        with pytest.raises(Sentinel):
            fast._fast.heuristic_follow(bot, rnd, s)
    finally:
        fast._fast.set_follow_fallback(Ordering, PURE_FOLLOW)
