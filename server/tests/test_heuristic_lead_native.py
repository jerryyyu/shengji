"""Semantic parity for the native rollout-lead kernel."""

from __future__ import annotations

import random
import subprocess
import sys
from types import SimpleNamespace

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.smart import SmartBot
from shengji.engine import fast
from shengji.engine.cards import Ordering, make_deck


CONFIGS = (("S", "2"), ("H", "7"), ("C", "10"), ("D", "A"),
           (None, "7"), (None, "A"))


def _state(hand, config):
    suit, rank = config
    return SimpleNamespace(
        ordering=Ordering(suit, rank),
        hands=[list(hand), [], [], []],
    )


def test_native_lead_matches_pure_on_random_engine_hands():
    rng = random.Random(2026081301)
    deck = make_deck()
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    try:
        pure_bot = HeuristicBot()
        native_bot = HeuristicBot()
        for _ in range(20_000):
            hand = rng.sample(deck, rng.randint(1, 33))
            config = CONFIGS[rng.randrange(len(CONFIGS))]
            expected = pure_bot._lead(_state(hand, config), 0)
            actual = fast._fast.heuristic_lead(
                native_bot, _state(hand, config), 0)
            assert actual == expected, (hand, config, expected, actual)
    finally:
        if was_active:
            fast.activate()


def test_fast_activation_routes_and_restores_native_lead():
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    pure = HeuristicBot._lead
    try:
        assert fast.activate()
        assert HeuristicBot._lead is fast._fast.heuristic_lead
        fast.deactivate()
        assert HeuristicBot._lead is pure
    finally:
        if was_active:
            fast.activate()


def _outcome(call):
    try:
        return ("value", call())
    except BaseException as exc:  # parity includes the pure exception surface
        return ("exception", type(exc), exc.args)


def test_native_router_preserves_malformed_public_call_semantics():
    class OrderingSubclass(Ordering):
        pass

    cases = [
        # Negative one is a valid Python list index; more-negative and huge
        # indices raise IndexError in pure Python rather than crashing or
        # narrowing in C.
        (-1, [["S2"], ["H2"], ["C2"], ["D2"]]),
        (-5, [["S2"], ["H2"], ["C2"], ["D2"]]),
        (2**100, [["S2"], ["H2"], ["C2"], ["D2"]]),
        (1.5, [["S2"], ["H2"], ["C2"], ["D2"]]),
        # bool is intentionally not an exact int, but pure list indexing
        # accepts it; the fallback must preserve that value behavior.
        (True, [["S2"], ["H2"], ["C2"], ["D2"]]),
        # Non-engine containers and impossible engine hand sizes stay pure.
        (0, [("S2",), [], [], []]),
        (0, [[], [], [], []]),
        (0, [["S2"] * 34, [], [], []]),
        (0, [["S2"] * 129, [], [], []]),
    ]
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    try:
        for seat, hands in cases:
            rnd = SimpleNamespace(
                ordering=Ordering("H", "7"), hands=hands)
            fast.activate()
            # Activation rewrites imported pure helper aliases in the
            # heuristic module.  The router's malformed fallback must be
            # compared under that same active-helper environment.
            expected = _outcome(
                lambda: fast._saved["HeuristicBot._lead"](
                    HeuristicBot(), rnd, seat))
            actual = _outcome(lambda: HeuristicBot()._lead(rnd, seat))
            fast.deactivate()
            assert actual == expected, (seat, hands, expected, actual)

        # Only the real engine's exact Ordering and four-seat hand layout enter
        # a bounds-check-free native kernel. Duck-typed/subclass state remains
        # a supported pure-Python call surface.
        for ordering, hands, seat in (
                (OrderingSubclass("H", "7"),
                 [["S2"], ["H2"], ["C2"], ["D2"]], 0),
                (Ordering("H", "7"),
                 [["S2"], ["H2"], ["C2"], ["D2"], ["S3"]], 4)):
            rnd = SimpleNamespace(ordering=ordering, hands=hands)
            fast.activate()
            expected = _outcome(
                lambda: fast._saved["HeuristicBot._lead"](
                    HeuristicBot(), rnd, seat))
            actual = _outcome(lambda: HeuristicBot()._lead(rnd, seat))
            fast.deactivate()
            assert actual == expected, (ordering, hands, seat, expected, actual)
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()


def test_negative_seat_cannot_reach_unchecked_native_index():
    """A missing router guard used to terminate CPython with SIGSEGV."""
    code = """
from types import SimpleNamespace
from shengji.ai.heuristic import HeuristicBot
from shengji.engine import fast
from shengji.engine.cards import Ordering
rnd = SimpleNamespace(
    ordering=Ordering('H', '7'),
    hands=[['S2'], ['H2'], ['C2'], ['D2']],
)
fast.activate()
assert HeuristicBot()._lead(rnd, -1) == ['D2']
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, (
        completed.returncode, completed.stdout, completed.stderr)


def test_normal_engine_state_still_routes_to_native(monkeypatch):
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    try:
        fast.activate()
        # Entry-bound: the class attribute IS the native entry, so routing is
        # proven by identity plus a live engine-shaped call returning through
        # the native path (the pure fallback would produce the same cards, so
        # non-vacuity is asserted via the binding identity above and the
        # malformed-state fallback tests below).
        rnd = SimpleNamespace(
            ordering=Ordering("H", "7"),
            hands=[["S2"], [], [], []],
        )
        assert HeuristicBot._lead is fast._fast.heuristic_lead
        assert HeuristicBot()._lead(rnd, 0) == ["S2"]
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()


def test_native_base_route_preserves_subclass_lead_dispatch():
    class CustomLead(HeuristicBot):
        def _lead(self, rnd, seat):
            return ["custom", seat]

    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    smart_lead = SmartBot._lead
    custom_lead = CustomLead._lead
    try:
        fast.activate()
        # SmartBot's structured throw/lead policy and any future explicit
        # subclass leaf must win ordinary Python method dispatch. Only classes
        # inheriting HeuristicBot._lead unchanged use the native kernel.
        assert SmartBot._lead is smart_lead
        assert CustomLead._lead is custom_lead
        assert CustomLead()._lead(None, 3) == ["custom", 3]
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()
