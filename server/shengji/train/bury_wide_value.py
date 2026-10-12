"""The OPTIONAL wide value-only bury chooser of the served pv-search bot
(``SHENGJI_PV_BURY_WIDE_VALUE``, bury-name token ``bwv``; #707 S15).

Today's hybrid bury (`cwv_bury_policy.CWVBuryMixin._decide_bury`) scores the
structured ballot (`ai.bury.structured_bury_ballot`: the heuristic incumbent
plus the five discard profiles and the forced voids, 19-32 candidates on the
DEV bury roots) with the value head over ``model_worlds`` sampled worlds, then
sends the value top-``alternatives`` and the incumbent to MC rollouts, which
decide.  September's bury-chooser screen (v48bury, release 38's package) found
value-only +0.0024, MC-on-all -0.0058 and hybrid-8 +0.0139, all inconclusive,
on that ballot.

With the flag on the chooser is (a) WIDER -- the ballot is extended with the
single-card swaps of the heuristic incumbent (one buried card out, one kept
card in), enumerated in a deterministic order and deduplicated by card
multiset, the whole set capped at ``k`` (``SHENGJI_PV_BURY_WIDE_K``, default
``WIDE_K_DEFAULT``) with the literal incumbent always at index 0 -- and (b)
VALUE-ONLY: the value head's mean over the arm's ``model_worlds`` worlds
(`cwv_bury.score_bury_candidates`, the same leaf as the hybrid's value pass:
the heuristic first trick, or the policy head's under ``lpft``) picks the
argmax (lowest index on a tie); no MC rollout stage runs.  The budget contract
is #972's: ``check_budget`` runs at every expensive boundary (after the
enumeration, before and after the world sampling, inside the scoring before
every predictor batch, after the leaf and after every value batch, and before
the argmax), and an expiry or an error falls back to the heuristic incumbent
through the mixin's `decide_bury` exactly as today (the same
``cwv-bury-fallback-v1`` record and reason fields).

The decision record is the shipped ``cwv-bury-policy-v1`` (the keys a screen
reader already knows, with the MC fields empty as the ``value`` arm leaves
them) plus ``wide_value``: ``candidates``, ``worlds``, ``chosen_index``,
``chosen_is_incumbent``, ``seconds`` (the chooser's wall time), and the
enumeration's ``k``, ``ballot_count``, ``swap_count`` and ``swaps_enumerated``.

Off (the default) nothing here is called by a decision: the bot's
`_decide_bury` is the mixin's, every name, digest and record are unchanged.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict
from typing import Any

import numpy as np

from ..ai.registry import make_bot
from ..engine.cards import TRUMP, points
from .cwv_bury import score_bury_candidates
from .cwv_bury_policy import BuryPolicyError, _seed, _worlds

#: the default cap on the widened candidate set (the incumbent included)
WIDE_K_DEFAULT = 32
#: the key the decision record carries the chooser's telemetry under
RECORD_KEY = "wide_value"
#: the chooser's identity inside the ``cwv-bury-recipe-v1`` digest
CHOOSER = "value-argmax-over-model-worlds"
#: the bury-name token (``...-bury-<arm>-bwv-<12 hex>``)
TOKEN = "bwv"


def check_wide_k(k) -> int:
    """``k`` is a positive int, at least 2 (the incumbent and one alternative;
    a chooser with nothing to choose between would be a lie)."""
    if type(k) is not int or k < 2:
        raise BuryPolicyError("bury_wide_k must be an int >= 2")
    return k


def _swap_key(code: str, ordering) -> tuple:
    """Low-to-high discard preference of one card: a non-trump, pointless,
    low card first (the ``low_strength`` profile of `ai.bury`, points ahead
    of level)."""
    point = points(code)
    return (ordering.eff_suit(code) == TRUMP, point > 0, point, ordering.level(code), code)


def single_card_swaps(hand, incumbent, ordering) -> list[list[str]]:
    """Every eight-card bury that differs from ``incumbent`` by exactly one
    card, deterministically ordered: the card swapped IN by discard preference
    (the kept card the banker would most like to bury first), then the card
    swapped OUT by the reverse (the buried card that least deserves the kitty
    first).  Deduplicated by card multiset; ``incumbent`` itself is never
    returned.  The result keeps each incumbent card's position, so a swap is
    readable next to the incumbent."""
    hand_counts = Counter(hand)
    incumbent = list(incumbent)
    if Counter(incumbent) - hand_counts:
        raise BuryPolicyError("incumbent contains cards outside the banker hand")
    kept = sorted((hand_counts - Counter(incumbent)).elements(),
                  key=lambda code: _swap_key(code, ordering))
    outs = sorted(range(len(incumbent)),
                  key=lambda i: _swap_key(incumbent[i], ordering), reverse=True)
    seen = {tuple(sorted(incumbent))}
    swaps: list[list[str]] = []
    for card_in in kept:
        for i in outs:
            if incumbent[i] == card_in:
                continue
            swap = list(incumbent)
            swap[i] = card_in
            key = tuple(sorted(swap))
            if key in seen:
                continue
            seen.add(key)
            swaps.append(swap)
    return swaps


def wide_bury_candidates(rnd, banker: int, ballot, k: int) -> tuple[list[list[str]], dict]:
    """The widened set: ``ballot`` (the mixin's structured ballot, its literal
    incumbent at index 0) followed by the incumbent's single-card swaps, minus
    the multisets the ballot already holds, cut to ``k`` in all.  Returns the
    candidates and the enumeration's counts."""
    k = check_wide_k(k)
    ballot = [list(candidate) for candidate in ballot]
    if not ballot:
        raise BuryPolicyError("wide bury needs the ballot's incumbent")
    incumbent = ballot[0]
    seen = {tuple(sorted(candidate)) for candidate in ballot}
    if len(seen) != len(ballot):
        raise BuryPolicyError("bury ballot holds duplicates")
    swaps = single_card_swaps(rnd.hands[banker], incumbent, rnd.ordering)
    candidates = ballot[:k]
    added = 0
    for swap in swaps:
        if len(candidates) >= k:
            break
        key = tuple(sorted(swap))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(swap)
        added += 1
    counts = {"k": k, "ballot_count": len(ballot), "swap_count": added,
              "swaps_enumerated": len(swaps)}
    return candidates, counts


def decide_wide_value_bury(bot: Any, rnd, seat: int, *, started, incumbent,
                           check_budget=None, progress) -> list[str]:
    """The chooser, in the mixin's `_decide_bury` slot (the mixin's
    `decide_bury` owns the budget clock, the incumbent and the fallback).
    Sets ``bot.last_bury_record`` and returns the chosen bury."""
    options = {} if check_budget is None else {"check_budget": check_budget}
    progress["leaf_first_trick"] = "heuristic"
    progress["leaf_first_trick_fallbacks"] = 0
    progress["finalist_count"] = 0
    if check_budget is not None:
        check_budget()
    chooser_started = time.perf_counter()
    candidates, counts = wide_bury_candidates(
        rnd, seat, bot._bury_candidates(rnd, incumbent), bot.bury_wide_k)
    progress["candidate_count"] = len(candidates)
    if check_budget is not None:
        check_budget()                       # after the enumeration, before sampling
    worlds = bot.bury_config.model_worlds
    model_bot = make_bot("mc-s0-report-lcb", seed=_seed("model", bot.seed))
    model_counter_before = bot._counter(model_bot)
    progress["model_positions"] = None
    model_worlds, model_attempts = _worlds(model_bot, rnd, seat, worlds, "model", **options)
    leaf = bot._leaf_first_trick(model_bot.rollout_policy, check_budget)
    if leaf is None:
        first_trick = {"first_trick_policy": model_bot.rollout_policy}
    else:
        progress["leaf_first_trick"] = "policy"
        first_trick = {"first_trick_batch": leaf.play_first_tricks}
    if check_budget is not None:
        check_budget()                       # before the scoring begins
    try:
        values = score_bury_candidates(rnd, candidates, model_worlds, bot.evaluator,
                                       **first_trick, **options)
    finally:
        if leaf is not None:
            progress["leaf_first_trick_fallbacks"] = int(leaf.fallbacks)
    progress["model_positions"] = len(candidates) * worlds
    if check_budget is not None:
        check_budget()                       # after the last value batch, before the argmax
    if not np.isfinite(values).all():
        raise BuryPolicyError("model bury values must be finite")
    means = np.mean(values, axis=0)
    picked = min(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    model_counter_after = bot._counter(model_bot)
    if check_budget is not None:
        check_budget()
    now = time.perf_counter()
    bot.last_bury_record = {
        "schema": "cwv-bury-policy-v1",
        "arm": bot.bury_arm,
        "bury_config": asdict(bot.bury_config),
        "candidates": [list(candidate) for candidate in candidates],
        "shortlist": [0],
        "picked_index": int(picked),
        "candidate_count": len(candidates),
        "finalist_count": 0,
        "fallback_reason": None,
        "model_means": means.tolist(),
        "mc_evidence": None,
        "model_worlds": worlds,
        "selection_worlds": 0,
        "world_counts": {"model": worlds, "selection": 0,
                         "model_attempts": model_attempts, "selection_attempts": 0},
        "elapsed_seconds": now - started,
        "model_seconds": now - chooser_started,
        "rollout_seconds": 0.0,
        "mc_rollouts": 0,
        "model_positions": len(candidates) * worlds,
        "leaf_first_trick": progress["leaf_first_trick"],
        "leaf_first_trick_fallbacks": progress["leaf_first_trick_fallbacks"],
        "counters": {
            "wrapper": bot._counter(bot),
            "model_before": model_counter_before,
            "model_after": model_counter_after,
            "mc_before": None,
            "mc_after": None,
        },
        RECORD_KEY: {
            "candidates": len(candidates),
            "worlds": worlds,
            "chosen_index": int(picked),
            "chosen_is_incumbent": picked == 0,
            "seconds": now - chooser_started,
            **counts,
        },
    }
    return list(candidates[picked])


__all__ = ["WIDE_K_DEFAULT", "RECORD_KEY", "CHOOSER", "TOKEN", "check_wide_k",
           "single_card_swaps", "wide_bury_candidates", "decide_wide_value_bury"]
