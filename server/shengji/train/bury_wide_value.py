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

Optional two-card swaps (``SHENGJI_PV_BURY_WIDE_SWAPS=2``, ``swaps``; only with
the chooser on; bury-name token ``bwv2`` in place of ``bwv``): after the ballot
the free slots are filled from ONE merged, preference-ordered stream of the
incumbent's single-card AND two-card swaps (two buried cards out, two kept
cards in) -- the two kinds INTERLEAVED, not two-card swaps only after the
single ones run out (at ``k`` <= 128 the single swaps alone, 150-200 per root,
would fill every slot and no two-card swap would ever be seen).  Each kept
card has its discard-preference rank (0 = the card the banker would most like
to bury, `_swap_key`) and each buried card its reverse rank (0 = the one that
least deserves the kitty); a swap's score is the sum of the ranks it moves, so
a single swap ``(in i, out o)`` scores ``i + o`` and a two-card swap ``(in
{a < b}, out {c < d})`` scores ``a + b + c + d``.  The stream is ordered by
score, a single swap before a two-card swap of the same score, then by the
in-ranks, then by the out-ranks; it is generated lazily, score by score, so
the work is bounded by the slots it fills (plus the multisets it skips as
duplicates) and the 300 + 28 rank pairs, never all C(25,2) x C(8,2) two-card
swaps.  A two-card swap that moves fewer than two cards (a kept card equal to
a buried one) is skipped; everything is deduplicated by multiset against the
ballot and the swaps already taken.  The record's ``wide_value`` gains
``swaps`` (2) and ``two_swap_count``; ``swap_count`` counts the single swaps
taken.  ``swaps=1`` (the default) is the enumeration above, byte for byte.

Optional second stage (``SHENGJI_PV_BURY_TWO_STAGE=1``, ``bury_two_stage``;
only with the chooser on; bury-name token ``bts`` after ``bwv``/``bwv2``): after
the argmax above, `bury_two_stage.run_stage_two` re-scores the value top-N on
fresh common worlds with deeper policy-played positions and may replace the
argmax; its record key is ``two_stage``.  Off (``bury_two_stage`` None, the
class default) the chooser is the code above, byte for byte.

Optional kitty charge (``SHENGJI_PV_BURY_KITTY_CHARGE=1``, ``bury_kitty_charge``;
only with the chooser on, exclusive with the second stage; bury-name token
``bkc`` after ``bwv``/``bwv2``): the argmax is taken over the value means less
each candidate kitty's expected bonus (`bury_kitty_charge.charged_choice`); its
record key is ``kitty_charge``.  Off (``bury_kitty_charge`` False, the class
default) the chooser is the code above, byte for byte.

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
from .bury_kitty_charge import RECORD_KEY as KITTY_CHARGE_RECORD_KEY, charged_choice
from .bury_two_stage import RECORD_KEY as TWO_STAGE_RECORD_KEY, run_stage_two
from .cwv_bury import score_bury_candidates
from .cwv_bury_policy import BuryPolicyError, _seed, _worlds

#: the default cap on the widened candidate set (the incumbent included)
WIDE_K_DEFAULT = 32
#: the largest cap a configuration may ask for (the enumeration itself is not capped)
WIDE_K_MAX = 128
#: the swap depth: 1 = single-card swaps (the default), 2 = single and two-card swaps
WIDE_SWAPS_DEFAULT = 1
WIDE_SWAPS = (1, 2)
#: the key the decision record carries the chooser's telemetry under
RECORD_KEY = "wide_value"
#: the chooser's identity inside the ``cwv-bury-recipe-v1`` digest
CHOOSER = "value-argmax-over-model-worlds"
#: the bury-name token (``...-bury-<arm>-bwv-<12 hex>``)
TOKEN = "bwv"
#: the bury-name token with two-card swaps (``...-bury-<arm>-bwv2-<12 hex>``)
TOKEN_TWO_SWAPS = "bwv2"


def check_wide_k(k) -> int:
    """``k`` is a positive int, at least 2 (the incumbent and one alternative;
    a chooser with nothing to choose between would be a lie)."""
    if type(k) is not int or k < 2:
        raise BuryPolicyError("bury_wide_k must be an int >= 2")
    return k


def check_wide_swaps(swaps) -> int:
    """``swaps`` is the int 1 or 2."""
    if type(swaps) is not int or swaps not in WIDE_SWAPS:
        raise BuryPolicyError("bury_wide_swaps must be the int 1 or 2")
    return swaps


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


def ranked_swaps(hand, incumbent, ordering):
    """The merged single- and two-card swap stream of ``swaps=2`` (module
    docstring), lazily: yields ``(moved, swap)`` with ``moved`` 1 or 2, every
    swap an eight-card bury of ``hand`` that moves exactly ``moved`` cards
    from ``incumbent`` (each incumbent card keeps its position).  Not
    deduplicated (a kept card held twice yields the same multiset twice): the
    consumer dedupes."""
    hand_counts = Counter(hand)
    incumbent = list(incumbent)
    if Counter(incumbent) - hand_counts:
        raise BuryPolicyError("incumbent contains cards outside the banker hand")
    incumbent_counts = Counter(incumbent)
    kept = sorted((hand_counts - incumbent_counts).elements(),
                  key=lambda code: _swap_key(code, ordering))
    outs = sorted(range(len(incumbent)),
                  key=lambda i: _swap_key(incumbent[i], ordering), reverse=True)
    n_in, n_out = len(kept), len(outs)
    in_pairs: dict[int, list[tuple[int, int]]] = {}
    for a in range(n_in):
        for b in range(a + 1, n_in):
            in_pairs.setdefault(a + b, []).append((a, b))
    out_pairs: dict[int, list[tuple[int, int]]] = {}
    for c in range(n_out):
        for d in range(c + 1, n_out):
            out_pairs.setdefault(c + d, []).append((c, d))
    top = max((n_in - 1) + (n_out - 1), (2 * n_in - 3) + (2 * n_out - 3), 0)
    for score in range(top + 1):
        for i in range(max(0, score - (n_out - 1)), min(score, n_in - 1) + 1):
            o = outs[score - i]
            if incumbent[o] == kept[i]:
                continue
            swap = list(incumbent)
            swap[o] = kept[i]
            yield 1, swap
        for t in sorted(in_pairs):
            pairs_out = out_pairs.get(score - t)
            if t > score or not pairs_out:
                continue
            for a, b in in_pairs[t]:
                for c, d in pairs_out:
                    swap = list(incumbent)
                    swap[outs[c]] = kept[a]
                    swap[outs[d]] = kept[b]
                    if sum((Counter(swap) - incumbent_counts).values()) != 2:
                        continue
                    yield 2, swap


def wide_bury_candidates(rnd, banker: int, ballot, k: int,
                         swaps: int = WIDE_SWAPS_DEFAULT) -> tuple[list[list[str]], dict]:
    """The widened set: ``ballot`` (the mixin's structured ballot, its literal
    incumbent at index 0) followed by the incumbent's single-card swaps (with
    ``swaps=2``: the merged single- and two-card swap stream, `ranked_swaps`),
    minus the multisets already held, cut to ``k`` in all.  Returns the
    candidates and the enumeration's counts."""
    k = check_wide_k(k)
    swaps = check_wide_swaps(swaps)
    ballot = [list(candidate) for candidate in ballot]
    if not ballot:
        raise BuryPolicyError("wide bury needs the ballot's incumbent")
    incumbent = ballot[0]
    seen = {tuple(sorted(candidate)) for candidate in ballot}
    if len(seen) != len(ballot):
        raise BuryPolicyError("bury ballot holds duplicates")
    singles = single_card_swaps(rnd.hands[banker], incumbent, rnd.ordering)
    candidates = ballot[:k]
    if swaps == 2:
        added = {1: 0, 2: 0}
        if len(candidates) < k:
            for moved, swap in ranked_swaps(rnd.hands[banker], incumbent, rnd.ordering):
                key = tuple(sorted(swap))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(swap)
                added[moved] += 1
                if len(candidates) >= k:
                    break
        counts = {"k": k, "ballot_count": len(ballot), "swap_count": added[1],
                  "swaps_enumerated": len(singles), "swaps": 2, "two_swap_count": added[2]}
        return candidates, counts
    added = 0
    for swap in singles:
        if len(candidates) >= k:
            break
        key = tuple(sorted(swap))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(swap)
        added += 1
    counts = {"k": k, "ballot_count": len(ballot), "swap_count": added,
              "swaps_enumerated": len(singles)}
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
        rnd, seat, bot._bury_candidates(rnd, incumbent), bot.bury_wide_k,
        bot.bury_wide_swaps)
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
    kitty_charge = None
    if bot.bury_kitty_charge:
        picked, kitty_charge = charged_choice(candidates, means)
    else:
        picked = min(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    model_counter_after = bot._counter(model_bot)
    if check_budget is not None:
        check_budget()
    two_stage = bot.bury_two_stage
    if two_stage is not None:
        # the optional second stage (`bury_two_stage`): stage 1 is complete and
        # inside the budget here; the stage has its own deadline and keeps
        # ``picked`` on an expiry or an error, so it never reaches the fallback
        stage1_seconds = time.perf_counter() - chooser_started
        picked, stage_two = run_stage_two(bot, rnd, seat, candidates, means, two_stage,
                                          started=started)
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
    if kitty_charge is not None:
        bot.last_bury_record[KITTY_CHARGE_RECORD_KEY] = kitty_charge
    if two_stage is not None:
        # ``model_seconds`` stays stage 1's; ``wide_value.seconds`` and
        # ``elapsed_seconds`` include stage 2
        bot.last_bury_record["model_seconds"] = stage1_seconds
        bot.last_bury_record[TWO_STAGE_RECORD_KEY] = stage_two
    return list(candidates[picked])


__all__ = ["WIDE_K_DEFAULT", "WIDE_K_MAX", "WIDE_SWAPS_DEFAULT", "WIDE_SWAPS", "RECORD_KEY",
           "CHOOSER", "TOKEN", "TOKEN_TWO_SWAPS", "check_wide_k", "check_wide_swaps",
           "single_card_swaps", "ranked_swaps", "wide_bury_candidates", "decide_wide_value_bury"]
