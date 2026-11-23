"""Release-54 play decisions along fixed self-play deals: the flag-off identity witness of rules
added to the release-54 search.

One release-54 bot, built as the server builds it (`test_release53_fly_config.served_bot` on the
repo's ``fly.toml``), with its clocks lifted (`r50_flag_positions.lift`; the belief preparation
budget by `test_unified_serving.served_functions`), plays all four seats of the deals ``SEEDS`` from the deal through the last trick.  Every
play decision is projected as `r50_flag_positions.decision` projects it (played cards, base-world
digest, the record without the fields that measure the run) and digested exactly (`digest`).
``fixtures/r54_flag_off_decisions.<platform>.json`` (`pinned`) holds each engine's full projections
and their exact integrity digests. Pure replays require exact digests. Compiled replays permit
bounded float32 BLAS variation in the five measured fields of the decision record, with exact
structure, cards, worlds, and all other values.
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

# Absolute bounds cover the observed cross-platform drift across all pinned compiled decisions:
# value/margin fields differ by at most 6.83e-7, and log odds by at most 3.06e-5.
_COMPILED_FLOAT_ATOL = {
    "value_means": 1e-6,
    "exact_lead_base_value_means": 1e-6,
    "singleton_probe_margin": 1e-6,
    "policy_log_odds_listing": 4e-5,
    "policy_log_odds_admitted": 4e-5,
}


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
    """The exact sha256 of a projection, including its serialized float values."""
    return hashlib.sha256(json.dumps(projection, sort_keys=True, default=list).encode()).hexdigest()


def pinned(platform_key: str = None):
    """The fixture path for ``platform_key`` (this host's `PLATFORM` by default)."""
    return FIXTURES / PINS.format(platform=platform_key or PLATFORM)


def first_difference(actual, expected, *, compiled=False):
    """The first differing field, or None. Only compiled replays allow measured float drift."""
    return _first_difference(actual, expected, "decision", compiled, 0.0)


def _first_difference(actual, expected, path, compiled, atol):
    if isinstance(expected, float) and isinstance(actual, float):
        if float.__repr__(actual) == float.__repr__(expected):
            return None
        if atol:
            if math.isclose(actual, expected, rel_tol=0.0, abs_tol=atol):
                return None
            return f"{path} (actual {actual!r}, expected {expected!r}, absolute tolerance {atol:g})"
        return path
    if type(actual) is not type(expected):
        return f"{path} (type)"
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            return f"{path} (keys {sorted(set(actual) ^ set(expected))})"
        tolerances = _COMPILED_FLOAT_ATOL if compiled and path == "decision.record" else {}
        for key in expected:
            found = _first_difference(actual[key], expected[key], f"{path}.{key}",
                                      compiled, tolerances.get(key, 0.0))
            if found:
                return found
        return None
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path} (length)"
        for i, (a, e) in enumerate(zip(actual, expected)):
            found = _first_difference(a, e, f"{path}[{i}]", compiled, atol)
            if found:
                return found
        return None
    return None if actual == expected else path


def label(seed: int, trick: int, pos: int) -> str:
    return f"{seed}:{trick}:{pos}"
