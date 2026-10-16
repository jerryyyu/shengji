"""Bounded offline consumer for one captured PV-tree decision.

This is a diagnostic only: it consumes the serving bot's own admitted actions,
sampled worlds, PV matrix, and actual PV winner, then evaluates fixed offline
lookahead settings. The baseline samples once; lookahead does not resample.
It makes no oracle comparison or playing-strength claim.
"""

from __future__ import annotations

import copy
import time

import numpy as np

from shengji.train.lead_root_capture import fingerprint


def run_hybrid_search_probe(bot, rnd, seat, *, completed_tricks,
                            exact_max_cards, gate=None, exact_max_nodes=250_000):
    """Capture one real decision and consume it through bounded lookahead.

    ``bot`` must be a constructed ``PVTreeSearchBot`` configured with
    ``tree.sims == 0``.  ``completed_tricks`` and ``exact_max_cards`` select
    one bounded offline setting. ``gate`` is passed explicitly to the call;
    an expiry or any incomplete lookahead raises and produces no result.
    The returned ``baseline`` is the actual serving PV winner; the
    ``hybrid_value_argmax_index`` is only an offline value-ranking proposal.
    """
    tree_config = getattr(bot, "tree_config", None)
    if tree_config is None or int(tree_config.sims) != 0:
        raise ValueError("hybrid probe requires a tree.sims=0 baseline bot")
    if gate is not None and not callable(gate):
        raise TypeError("gate must be callable or None")
    if isinstance(completed_tricks, bool) or not isinstance(completed_tricks, int) \
            or not 1 <= completed_tricks <= 3:
        raise ValueError("completed_tricks must be an integer in [1, 3]")
    if isinstance(exact_max_cards, bool) or not isinstance(exact_max_cards, int) \
            or not 0 <= exact_max_cards <= 7:
        raise ValueError("exact_max_cards must be an integer in [0, 7]")
    if isinstance(exact_max_nodes, bool) or not isinstance(exact_max_nodes, int) \
            or exact_max_nodes < 1:
        raise ValueError("exact_max_nodes must be a positive integer")

    captured = {}
    before_round = fingerprint(rnd)
    original = bot._tree_decide

    def capture(root, acting_seat, admitted, means, worlds, pv_winner, fields,
                select_kwargs):
        captured.update(
            admitted=copy.deepcopy(admitted),
            means=np.asarray(means, dtype=np.float64).copy(),
            worlds=copy.deepcopy(worlds),
            v0=np.asarray(bot._tree_v0, dtype=np.float64).copy()
            if bot._tree_v0 is not None else None,
            pv_winner=int(pv_winner),
        )
        return original(root, acting_seat, admitted, means, worlds, pv_winner,
                        fields, select_kwargs)

    had_own = "_tree_decide" in vars(bot)
    previous = vars(bot).get("_tree_decide")
    bot._tree_decide = capture
    baseline_started = time.perf_counter()
    try:
        actual_cards = bot.decide_play(rnd, seat)
        baseline_seconds = time.perf_counter() - baseline_started
    finally:
        if had_own:
            bot._tree_decide = previous
        else:
            del bot._tree_decide

    required = ("admitted", "means", "worlds", "v0", "pv_winner")
    if any(name not in captured or captured[name] is None for name in required):
        raise RuntimeError("baseline decision did not produce a complete PV capture")
    admitted = captured["admitted"]
    means = captured["means"]
    worlds = captured["worlds"]
    v0 = captured["v0"]
    pv_winner = captured["pv_winner"]
    if not 0 <= pv_winner < len(admitted):
        raise RuntimeError("baseline PV winner is outside the admitted set")
    if sorted(actual_cards) != sorted(admitted[pv_winner]):
        raise RuntimeError("post-selection actual cards differ from captured PV winner")
    if len(admitted) == 0 or len(worlds) == 0:
        raise RuntimeError("baseline decision produced an empty PV capture")
    if means.shape != (len(admitted),) or v0.shape != (len(worlds), len(admitted)):
        raise RuntimeError("baseline PV capture dimensions are incomplete")
    if not np.isfinite(means).all() or not np.isfinite(v0).all():
        raise RuntimeError("baseline PV capture contains non-finite values")
    if not np.allclose(means, v0.mean(axis=0), rtol=1e-7, atol=1e-12):
        raise RuntimeError("baseline means disagree with the captured PV matrix")
    if fingerprint(rnd) != before_round:
        raise RuntimeError("baseline decision mutated the round")

    # Lookahead consumes the captured worlds directly.  A sampler state snapshot
    # makes accidental resampling a hard diagnostic failure.
    sampler = getattr(bot, "sampler", None)
    rng = getattr(sampler, "rng", None)
    sampler_state = copy.deepcopy(rng.getstate()) if rng is not None else None
    root_state = fingerprint(rnd)
    call_started = time.perf_counter()
    values, stats = bot._tree_lookahead(
        rnd, seat, admitted, worlds, gate,
        completed_tricks=completed_tricks,
        exact_max_cards=exact_max_cards,
        exact_max_nodes=exact_max_nodes)
    if values.shape != (len(worlds), len(admitted)) or not np.isfinite(values).all():
        raise RuntimeError("lookahead returned an incomplete value matrix")
    hybrid_means = values.mean(axis=0)
    hybrid_winner = int(np.argmax(hybrid_means))
    lookahead_seconds = time.perf_counter() - call_started
    if fingerprint(rnd) != root_state:
        raise RuntimeError("offline lookahead mutated the round")
    if rng is not None and rng.getstate() != sampler_state:
        raise RuntimeError("offline lookahead advanced the bot sampler")
    if gate is not None:
        gate()
    return {
        "baseline": {"pv_winner": pv_winner,
                     "means": [float(value) for value in means],
                     "seconds": baseline_seconds},
        "admitted": copy.deepcopy(admitted),
        "worlds": copy.deepcopy(worlds),
        "v0": v0.copy(),
        "completed_tricks": completed_tricks,
        "exact_max_cards": exact_max_cards,
        "hybrid_value_argmax_index": hybrid_winner,
        "changed": hybrid_winner != pv_winner,
        "matrix_means": [float(value) for value in hybrid_means],
        "seconds": lookahead_seconds,
        "leafstats": {key: int(value) for key, value in stats.items()},
    }
