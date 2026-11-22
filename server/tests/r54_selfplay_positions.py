"""Release-54 play decisions along fixed self-play deals: the flag-off identity witness of rules
added to the release-54 search.

One release-54 bot, built as the server builds it (`test_release53_fly_config.served_bot` on the
repo's ``fly.toml``), with its clocks lifted (`r50_flag_positions.lift`; the belief preparation
budget by `test_unified_serving.served_functions`), plays all four seats of the deals ``SEEDS`` from the deal through the last trick.  Every
play decision is projected as `r50_flag_positions.decision` projects it (played cards, base-world
digest, the record without the fields that measure the run) and digested exactly (`digest`).
``fixtures/r54_flag_off_decisions.<platform>.json`` (`pinned`) holds, per engine, each decision's full
projection and its digest, computed on main 44f0c2f9's code on that platform (``pinned_on``): the
unified model is float32 and its matrix products take the host's BLAS, so the same code's values
differ in their last bits between platforms, and each platform is pinned on its own.  A rule that is
off must reproduce every digest exactly on the platform and engine the fixture names;
`first_difference` names the first departing field when one does not.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import sys
from pathlib import Path

import r50_flag_positions as P

FIXTURES = Path(__file__).parent / "fixtures"
PINS = "r54_flag_off_decisions.{platform}.json"
#: four deals, about sixty play decisions each, leads and follows above and inside the
#: exact stages' seven-card bound
SEEDS = (2669920000, 2669920001, 2669920002, 2669920003)
BOT_SEED = 54
#: the platform the pins were computed on
PLATFORM = f"{sys.platform}-{platform.machine()}"


def deal_decisions(bot, seed, limit=None):
    """``[(trick, position in trick, projection)]`` for the play decisions of deal ``seed`` (the first
    ``limit`` of them), the game continuing on each decision's cards."""
    from shengji.ai.env import observe_committed_play, prepare_round
    from shengji.engine.cards import RANKS
    from shengji.engine.game import Game

    game = Game(rng=random.Random(seed), start_level=RANKS[seed % len(RANKS)])
    rnd = prepare_round(game, [bot] * 4)
    out, trick, pos = [], 1, 0
    while rnd.phase == "play" and (limit is None or len(out) < limit):
        seat = rnd.turn
        projection = P.decision(bot, rnd)
        out.append((trick, pos, projection))
        before = len(rnd.history)
        rnd.play(seat, list(projection["cards"]))
        observe_committed_play(rnd, [bot] * 4)
        pos += 1
        if len(rnd.history) != before:
            trick, pos = trick + 1, 0
    return out


def digest(projection) -> str:
    """The sha256 of a projection, floats by ``repr`` (exact): the same engine on the same code
    gives the same digest."""
    return hashlib.sha256(json.dumps(projection, sort_keys=True, default=list).encode()).hexdigest()


def pinned(platform_key: str = None):
    """The fixture path for ``platform_key`` (this host's `PLATFORM` by default)."""
    return FIXTURES / PINS.format(platform=platform_key or PLATFORM)


def first_difference(actual, expected, path="decision"):
    """The path of the first value where ``actual`` departs from ``expected`` (every value exactly;
    NaN equals NaN), or None."""
    if isinstance(expected, float) and isinstance(actual, float):
        same = actual == expected or (math.isnan(actual) and math.isnan(expected))
        return None if same else path
    if type(actual) is not type(expected):
        return f"{path} (type)"
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            return f"{path} (keys {sorted(set(actual) ^ set(expected))})"
        for key in expected:
            found = first_difference(actual[key], expected[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path} (length)"
        for i, (a, e) in enumerate(zip(actual, expected)):
            found = first_difference(a, e, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if actual == expected else path


def label(seed: int, trick: int, pos: int) -> str:
    return f"{seed}:{trick}:{pos}"
