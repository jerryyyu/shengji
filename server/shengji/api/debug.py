"""Token-gated debug endpoints (live bot X-ray).

Enabled only when SHENGJI_DEBUG_TOKEN is set; otherwise plays dead.
Kept out of server.py: pure diagnostics, no game-state mutation.
"""

from __future__ import annotations

import asyncio
import copy
import os
import time


_BURY_WORK_FIELDS = (
    "cap",
    "worlds_requested",
    "worlds_used",
    "attempts",
    "attempt_cap",
    "candidate_rollouts",
    "complete",
)
_SAMPLER_DELTA_FIELDS = (
    "sample_attempts",
    "accepted_worlds",
    "failed_worlds",
    "rejected_worlds",
    "impossible_worlds",
)
#: the declaration record fields the overlay shows (``pv-value-declare-decision-v1``
#: and ``pv-declare-asap-decision-v1``): cards as text, means, counts and the
#: gate; never a sampled deal
_DECLARE_RECORD_FIELDS = (
    "schema", "final", "cards_dealt", "gate", "evaluated", "heuristic", "value_choice",
    "played", "changed", "worlds", "worlds_completed", "fallback_reason", "outcomes",
    "outcome_means", "heuristic_mean", "best_mean", "margin", "seconds",
    "leaf_first_trick", "leaf_first_trick_fallbacks",
    "options", "chosen", "strength", "overcall", "overcall_self",
)


def _declare_xray(rnd, seat: int, isolated_bot) -> dict:
    """One declaration decision from the cards dealt so far: the heuristic's,
    or the value rule's where its gate admits the chance (`PVSearchBot.decide_declare`).
    ``final`` is the grace window after the deal, as the server calls it."""
    from .debug_play import _scalar, _OMIT, _policy

    final = rnd.phase == "declare"
    options = rnd.declare_options(seat)
    started = time.perf_counter()
    chosen = isolated_bot.decide_declare(rnd, seat, final=final)
    elapsed = time.perf_counter() - started
    record = getattr(isolated_bot, "last_declare_record", None)
    safe = None
    if isinstance(record, dict):
        safe = {}
        for name in _DECLARE_RECORD_FIELDS:
            if name in record:
                value = _scalar(record[name])
                if value is not _OMIT:
                    safe[name] = value
    current = rnd.declaration
    from .debug_play import model_ids
    return {
        "model_ids": model_ids(record),
        "verdict": _declare_verdict(chosen, safe, record),
        "policy": _policy(isolated_bot),
        "phase": rnd.phase, "final": final,
        "cards_dealt": sum(len(h) for h in rnd.hands),
        "options": [list(o) for o in options],
        "chosen": None if chosen is None else list(chosen),
        "current": None if current is None else {
            "seat": current["seat"], "cards": list(current["cards"]),
            "strength": current["strength"]},
        # a bot without the value rule, or a chance its gate did not admit,
        # leaves no record: the heuristic's choice stands
        "record": safe,
        "evaluation_seconds": elapsed,
    }


def _declare_verdict(chosen, safe, record) -> dict:
    """At a glance: the declaration, who decided it, the outcomes by value and
    whether the evaluation degraded."""
    from .debug_play import _number, _warning, model_ids
    cards = "PASS" if chosen is None else " ".join(chosen)
    if safe is None:
        return {"declared": cards, "decided_by": "heuristic",
                "summary": f"declares {cards}: heuristic (no value evaluation on this chance)",
                "top": [], "gap": None, "threshold": None, "warnings": [],
                "degraded": False, "model_ids": None}
    labels = [part.split("=", 1)[-1].strip() for part in str(record.get("outcomes") or "").split("|")]
    means = safe.get("outcome_means") if isinstance(safe.get("outcome_means"), list) else []
    outcomes = sorted(((labels[i] if i < len(labels) else f"#{i}", _number(m))
                       for i, m in enumerate(means) if _number(m) is not None),
                      key=lambda o: -o[1])
    top = [{"play": label, "value": mean,
            "margin_to_next": None if k + 1 >= len(outcomes) else mean - outcomes[k + 1][1],
            "heuristic": label == safe.get("heuristic"), "bot_plays": label == cards}
           for k, (label, mean) in enumerate(outcomes[:5])]
    best, heuristic = _number(safe.get("best_mean")), _number(safe.get("heuristic_mean"))
    gap = None if best is None or heuristic is None else best - heuristic
    warnings = []
    if safe.get("fallback_reason"):
        warnings.append(_warning("declare_fallback",
                                 f"value evaluation abandoned ({safe['fallback_reason']}); the heuristic declared"))
    done, asked = _number(safe.get("worlds_completed")), _number(safe.get("worlds"))
    if done is not None and asked is not None and done < asked and not safe.get("fallback_reason"):
        warnings.append(_warning("declare_underfilled", f"{done} of {asked} worlds completed"))
    if model_ids(record) is None:
        warnings.append(_warning("no_model_ids", "the record names no package ids", "info"))
    decided_by = "value" if safe.get("changed") is True else "heuristic"
    why = ("value changed it" if decided_by == "value" else
           "value agreed" if safe.get("value_choice") == safe.get("heuristic") else
           "value gap within the threshold" if safe.get("evaluated") else "not evaluated")
    gap_text = "n/a" if gap is None else f"{gap:+.3f}"
    return {"declared": cards, "decided_by": decided_by,
            "summary": f"declares {cards}: {decided_by} ({why}); best {safe.get('value_choice')} "
                       f"{gap_text} vs the heuristic's {safe.get('heuristic')}"[:240],
            "top": top, "gap": gap, "threshold": _number(safe.get("margin")),
            "warnings": warnings,
            "degraded": any(w["severity"] == "degraded" for w in warnings),
            "model_ids": model_ids(record)}


def _declare_view(rnd, seat: int, isolated_bot) -> dict:
    """The overlay before trump exists: the hand and the declaration decision.
    The memory blocks need an ordering, so they are empty here."""
    return {
        "seat": seat,
        "phase": rnd.phase,
        "hand": sorted(rnd.hands[seat]),
        "is_attacker": None,
        "voids": {}, "unseen_trumps": None, "unseen_by_suit": {},
        "boss_cards": [], "ruff_risky_suits": [],
        "candidates": None, "bury": None, "analysis": None, "ml": None,
        "declare": _declare_xray(rnd, seat, isolated_bot),
    }


def _snapshot_xray(rnd, source_bot):
    """Detach every object the worker may read or mutate.

    The caller holds the room lock.  Copying both values here means the worker
    neither advances the live bot nor reads a round that can change underneath
    it after the lock is released.
    """
    return copy.deepcopy(rnd), copy.deepcopy(source_bot)


#: the wide value-only bury's candidates the overlay lists, best value first
#: (the incumbent and the chosen bury are always listed)
BURY_TOP = 12
_BURY_BELIEF_FIELDS = ("bury_belief_worlds", "bury_belief_fallbacks", "bury_belief_error",
                       "bury_belief_ms")


def _bury_belief(raw):
    """The bury's belief-world draw (``bbw``), or None where the record has none."""
    if not isinstance(raw, dict) or "bury_belief_worlds" not in raw:
        return None
    from .debug_play import _scalar, _OMIT
    out = {}
    for name in _BURY_BELIEF_FIELDS:
        value = _scalar(raw.get(name))
        out[name] = None if value is _OMIT else value
    return out


def _wide_bury_view(raw, pick, policy) -> dict:
    """The wide value-only chooser: every candidate scored by the value head on
    the same worlds, the argmax buried; its ``model_means`` are the banker
    team's expected signed levels, not the MC ``banker_avg`` points."""
    from .debug_play import _number
    pool = [list(c) for c in raw["candidates"]]
    means = [_number(v) for v in raw.get("model_means") or []]
    picked = raw.get("picked_index")
    wide = raw["wide_value"]
    ballot = wide.get("ballot_count") if isinstance(wide.get("ballot_count"), int) else None
    scored = [i for i in range(len(pool)) if i < len(means) and means[i] is not None]
    order = sorted(scored, key=lambda i: (-means[i], i))
    rank = {i: r + 1 for r, i in enumerate(order)}
    shown = []
    for i in order[:BURY_TOP] + [0, picked]:
        if isinstance(i, int) and 0 <= i < len(pool) and i not in shown:
            shown.append(i)
    rows = []
    for i in shown:
        nxt = order[rank[i]] if i in rank and rank[i] < len(order) else None
        rows.append({
            "cards": pool[i],
            "sources": ["incumbent"] if i == 0 else
                       ["ballot"] if ballot is not None and i < ballot else ["swap"],
            "banker_avg": None, "worlds": _number(wide.get("worlds")),
            "value": means[i] if i < len(means) else None, "rank": rank.get(i),
            "margin_to_next": (None if nxt is None or i not in rank
                               else means[i] - means[nxt]),
            "incumbent": i == 0, "raw_winner": i == (order[0] if order else None),
            "bot_buries": sorted(pool[i]) == sorted(pick),
        })
    others = [means[i] for i in scored if i != picked]
    chosen_value = means[picked] if isinstance(picked, int) and picked in rank else None
    counts = raw.get("world_counts") if isinstance(raw.get("world_counts"), dict) else {}
    return {
        "policy": policy, "mode": raw.get("arm"), "chooser": "wide_value",
        "chosen": pick, "reason": "value-head-argmax",
        "fallback": False,
        "margin": (chosen_value - max(others)) if chosen_value is not None and others else None,
        "gap_vs_incumbent": (chosen_value - means[0]) if chosen_value is not None and means else None,
        "search_secs": _number(raw.get("elapsed_seconds")) or 0.0,
        "work": {"worlds_requested": _number(raw.get("model_worlds")),
                 "worlds_used": _number(counts.get("model")),
                 "attempts": _number(counts.get("model_attempts")),
                 "candidate_rollouts": _number(raw.get("mc_rollouts")), "complete": True},
        "sampler_delta": None,
        "candidates": rows,
        "candidate_count": len(pool),
        "candidates_truncated": len(rows) < len(pool),
        "value_units": "expected signed levels for the banker's team",
        "model_positions": _number(raw.get("model_positions")),
        "enumeration": {k: _number(wide.get(k)) for k in
                        ("k", "ballot_count", "swap_count", "swaps_enumerated", "two_swap_count")
                        if k in wide},
        "chosen_value": chosen_value,
    }


def _bury_verdict(view, raw) -> dict:
    """At a glance: what was buried, what decided it, the margin, whether
    anything degraded and which packages decided."""
    from .debug_play import _warning, model_ids
    warnings = []
    if view.get("mode") == "heuristic" or view.get("reason") == "heuristic_pick":
        decided_by = "heuristic"
    elif raw is not None and raw.get("schema") == "cwv-bury-fallback-v1":
        decided_by = "fallback"
        warnings.append(_warning("bury_fallback",
                                 f"bury search fell back to the heuristic incumbent ({view.get('reason')})"))
    elif view.get("chooser") == "wide_value":
        decided_by = "wide_value"
    else:
        decided_by = "mc_search"
        if view.get("fallback"):
            warnings.append(_warning("bury_incumbent_kept",
                                     "the raw MC winner was not buried (incumbent margin rule)", "info"))
    belief = view.get("belief")
    if belief is not None and (belief.get("bury_belief_fallbacks") or 0) > 0:
        warnings.append(_warning("bury_belief_fallback",
                                 f"belief worlds fell back to the sampler ({belief.get('bury_belief_error') or 'n/a'})"))
    work = view.get("work")
    if isinstance(work, dict) and work.get("complete") is False:
        warnings.append(_warning("bury_underfilled", "the bury search underfilled its worlds"))
    ids = model_ids(raw)
    if raw is not None and ids is None:
        warnings.append(_warning("no_model_ids", "the record names no package ids", "info"))
    for key in ("two_stage", "kitty_charge"):
        if isinstance(raw, dict) and key in raw:
            warnings.append(_warning(key, f"the record carries a {key} block (not rendered)", "info"))
    cards = " ".join(view.get("chosen") or [])
    if decided_by == "wide_value":
        worlds = (view.get("work") or {}).get("worlds_used")
        source = ("belief" if belief is not None and belief.get("bury_belief_worlds")
                  and not belief.get("bury_belief_fallbacks") else "sampled")
        rank = next((r.get("rank") for r in view["candidates"] if r.get("bot_buries")), None)
        margin = view.get("margin")
        summary = (f"buried {cards}: value argmax (rank {rank}) of {view.get('candidate_count')} "
                   f"candidates on {worlds} {source} worlds; "
                   f"{'n/a' if margin is None else f'{margin:+.3f}'} vs the next best")
    else:
        summary = f"buried {cards}: {decided_by} ({view.get('reason')})"
    return {"buried": view.get("chosen"), "decided_by": decided_by, "summary": summary[:240],
            "warnings": warnings,
            "degraded": any(w["severity"] == "degraded" for w in warnings),
            "model_ids": ids}


def _bury_xray(rnd, seat: int, isolated_bot) -> dict:
    """The bury view (`_bury_view`) with its verdict, package ids and belief draw."""
    view, raw = _bury_view(rnd, seat, isolated_bot)
    from .debug_play import model_ids
    view["belief"] = _bury_belief(raw)
    view["model_ids"] = model_ids(raw)
    view["verdict"] = _bury_verdict(view, raw)
    return view


def _bury_view(rnd, seat: int, isolated_bot):
    """Run and redact one banker-kitty decision for the debug overlay; returns
    the view and the raw record it read (never sent).

    ``last_bury_record`` intentionally contains replay-only material such as
    the full pre-decision RNG state.  The browser needs the action, scores and
    finite-work account, not that internal record.  Keep an explicit allowlist
    here so future fields do not become client-visible by accident.
    """
    pick = list(isolated_bot.decide_bury(rnd, seat))
    policy = getattr(
        isolated_bot, "policy_name", type(isolated_bot).__name__)
    record = getattr(isolated_bot, "last_bury_record", None)
    original = record if isinstance(record, dict) else None

    if record is not None and record.get("schema") == "cwv-bury-fallback-v1":
        return {
            "policy": policy, "mode": record["arm"], "chosen": pick,
            "reason": record["reason"], "fallback": True,
            "margin": None, "gap_vs_incumbent": None,
            "search_secs": record["elapsed_seconds"],
            # Partial compute is not zero work or complete MC evidence.
            "work": None, "sampler_delta": None,
            "candidates": [{"cards": pick, "sources": ["heuristic-fallback"],
                            "banker_avg": None, "worlds": 0, "incumbent": True,
                            "raw_winner": False, "bot_buries": True}],
        }, original
    if (record is not None and record.get("schema") == "cwv-bury-policy-v1"
            and isinstance(record.get("wide_value"), dict) and record.get("mc_evidence") is None):
        return _wide_bury_view(record, pick, policy), original
    if record is not None and record.get("schema") == "cwv-bury-policy-v1":
        from ..train.cwv_bury_policy import trajectory_bury_record
        raw = record
        if raw["arm"] == "value":
            # No rollouts ran, so there is no MC ballot to map.  Show the ranked
            # pool; the head's means are signed levels, not the MC objective
            # ``banker_avg`` carries, and stay out of that column.
            record = {"candidates": [{"cards": list(cards), "mean_banker_value": None,
                                      "worlds": 0} for cards in raw["candidates"]],
                      "played_index": raw["picked_index"],
                      "raw_winner_index": raw["picked_index"],
                      "reason": "value-head-top-ranked"}
        else:
            record = trajectory_bury_record(raw)
        record.update(mode=raw["arm"], incumbent_index=0, fallback=False,
                      search_secs=raw["elapsed_seconds"],
                      work={"worlds_requested": raw["selection_worlds"],
                            "worlds_used": raw["selection_worlds"],
                            "candidate_rollouts": raw["mc_rollouts"], "complete": True})
        evidence = raw["mc_evidence"]
        if evidence is not None:
            means = evidence["mean_banker_values"]
            record.update(margin=evidence["incumbent_margin"],
                          gap_vs_incumbent=max(means) - means[0])

    if record is None:
        return {
            "policy": policy,
            "mode": "heuristic",
            "chosen": pick,
            "reason": "heuristic_pick",
            "fallback": False,
            "margin": None,
            "gap_vs_incumbent": None,
            "search_secs": 0.0,
            "work": None,
            "sampler_delta": None,
            "candidates": [{
                "cards": pick,
                "sources": ["heuristic"],
                "banker_avg": None,
                "worlds": 0,
                "incumbent": True,
                "raw_winner": True,
                "bot_buries": True,
            }],
        }, original

    incumbent_index = record.get("incumbent_index")
    raw_winner_index = record.get("raw_winner_index")
    played_index = record.get("played_index")
    candidates = []
    for index, candidate in enumerate(record.get("candidates", [])):
        cards = list(candidate.get("cards", []))
        candidates.append({
            "cards": cards,
            "sources": list(candidate.get("sources", [])),
            "banker_avg": candidate.get("mean_banker_value"),
            "worlds": candidate.get("worlds", 0),
            "incumbent": index == incumbent_index,
            "raw_winner": index == raw_winner_index,
            # Bind the UI to the action actually returned, not merely to a
            # stored index: this stays truthful if a future fallback rewrites
            # the returned action after search.
            "bot_buries": sorted(cards) == sorted(pick),
        })
    if not candidates:
        candidates = [{
            "cards": pick,
            "sources": ["recorded_choice"],
            "banker_avg": None,
            "worlds": 0,
            "incumbent": played_index == incumbent_index,
            "raw_winner": played_index == raw_winner_index,
            "bot_buries": True,
        }]

    raw_work = record.get("work")
    work = ({name: raw_work[name] for name in _BURY_WORK_FIELDS
             if name in raw_work}
            if isinstance(raw_work, dict) else None)
    raw_sampler = record.get("sampler_counters")
    raw_delta = (raw_sampler.get("delta")
                 if isinstance(raw_sampler, dict) else None)
    sampler_delta = ({name: raw_delta[name] for name in _SAMPLER_DELTA_FIELDS
                      if name in raw_delta}
                     if isinstance(raw_delta, dict) else None)

    return {
        "policy": record.get("policy", policy),
        "mode": record.get("mode", "search"),
        "chosen": pick,
        "reason": record.get("reason", "recorded_choice"),
        "fallback": (raw_winner_index is not None
                     and played_index is not None
                     and raw_winner_index != played_index),
        "margin": record.get("margin"),
        "gap_vs_incumbent": record.get("gap_vs_incumbent"),
        "search_secs": record.get("search_secs", 0.0),
        "work": work,
        "sampler_delta": sampler_delta,
        "candidates": candidates,
    }, original


def _xray(rnd, seat: int, isolated_bot) -> dict:
    """Build one X-ray from an already-isolated round and bot snapshot."""
    from ..ai.memory import Memory
    from ..engine.cards import SUITS, TRUMP
    from ..engine.legal import suit_cards

    o = rnd.ordering
    mem = Memory(rnd, seat)
    opps = [s for s in range(4) if s % 2 != seat % 2]
    hand = rnd.sorted_hand(seat)
    out: dict = {
        "seat": seat,
        "phase": rnd.phase,
        "hand": hand,
        "is_attacker": rnd.is_attacker(seat) if rnd.banker is not None else None,
        "voids": {s: sorted(mem.voids[s]) for s in range(4) if s != seat},
        "unseen_trumps": mem.unseen_trumps(),
        "unseen_by_suit": {
            eff: sorted((c for c in mem.unseen.elements()
                         if o.eff_suit(c) == eff), key=o.level, reverse=True)[:10]
            for eff in list(SUITS) + [TRUMP]},
        "boss_cards": [c for c in dict.fromkeys(hand) if mem.is_boss(c)],
        "ruff_risky_suits": [s for s in SUITS
                             if suit_cards(hand, s, o)
                             and mem.ruff_risk(s, opps)],
        "candidates": None,
        "bury": None,
        "analysis": None,
        # Learned inputs, named and marked, so they are never read as heuristics.
        # Only bots that carry a value evaluator have them; MCBot gets None.
        "ml": None,
    }
    evaluator = getattr(isolated_bot, "evaluator", None)
    if evaluator is not None:
        from .debug_features import ml_input_features
        out["ml"] = {"inputs": ml_input_features(rnd, seat, evaluator),
                     "inputs_scope": "root_state_preview; scored inputs are per-candidate "
                                     "trick-completed afterstates in sampled worlds",
                     "outputs_note": "per-candidate model_score rows in candidates[] "
                                     "and analysis.model are model-output"}
    if rnd.phase == "bury" and rnd.turn == seat:
        out["bury"] = _bury_xray(rnd, seat, isolated_bot)
    elif rnd.phase == "play" and rnd.turn == seat:
        # The snapshot starts at the live bot's exact RNG position.  The pick
        # and displayed values come from the same isolated evaluation.
        from .debug_play import play_analysis
        started = time.perf_counter()
        pick = isolated_bot.decide_play(rnd, seat)
        out["candidates"], out["analysis"] = play_analysis(
            isolated_bot, pick, is_attacker=out["is_attacker"],
            elapsed=time.perf_counter() - started,
            # public: whether this play follows and the largest hand's size
            context={"following": bool(rnd.trick.plays),
                     "max_hand": max(len(h) for h in rnd.hands)})
        out["analysis"]["snapshot"] = {
            "trick_number": len(rnd.history) + 1,
            "plays_in_trick": len(rnd.trick.plays),
            "acting_seat": seat,
        }
    return out


async def _xray_off_loop(rnd, seat: int, isolated_bot, view=None) -> dict:
    """Run CPU-heavy X-ray search without blocking WebSockets.

    Both inputs are detached before this call.  Cancellation is delayed until
    the worker exits so cancelled debug requests cannot accumulate orphaned
    report-LCB searches.  ``view`` is the builder (`_xray`, or `_declare_view`
    before trump exists); resolved at call time so a patched `_xray` is used.
    """
    worker = asyncio.create_task(
        asyncio.to_thread(view or _xray, rnd, seat, isolated_bot),
        name=f"xray-{seat}",
    )
    cancelled: asyncio.CancelledError | None = None
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as exc:
            cancelled = exc
    result = worker.result()
    if cancelled is not None:
        raise cancelled
    return result


async def _xray_room(room, seat: int, fallback_bot) -> dict:
    """Snapshot one room under its lock, then search after releasing it."""
    from .model_serving import run_debug_search

    async def compute():
        async with room.lock:
            rnd = room.round
            if rnd is None:
                return {"error": "no active round"}
            if type(seat) is not int or not 0 <= seat < 4:
                return {"error": "invalid seat"}
            # before trump exists the overlay is the declaration decision alone
            declaring = rnd.phase in ("deal", "declare")
            if not declaring and rnd.ordering is None:
                return {"error": "no active round"}
            source_bot = getattr(room, "bot", None) or fallback_bot
            rnd_copy, bot_copy = _snapshot_xray(rnd, source_bot)
        return await _xray_off_loop(rnd_copy, seat, bot_copy,
                                    _declare_view if declaring else _xray)

    return await run_debug_search(compute)


def register_debug(app, rooms) -> None:
    # ------------------------------------------------------------------- debug
    DEBUG_TOKEN = os.environ.get("SHENGJI_DEBUG_TOKEN", "")
    from ..ai.mcbot import MCBot as _XrayBot  # noqa: E402
    room_bot_for_xray = _XrayBot(seed=1234)


    @app.get("/debug/xray")
    async def debug_xray(room: str, seat: int, token: str = "") -> dict:
        if not DEBUG_TOKEN or token != DEBUG_TOKEN:
            return {"error": "not found"}
        r = rooms.get(room.upper())
        if r is None:
            return {"error": "no active round"}
        return await _xray_room(r, seat, room_bot_for_xray)
