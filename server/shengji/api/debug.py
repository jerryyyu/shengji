"""Token-gated debug endpoints (live bot X-ray).

Enabled only when SHENGJI_DEBUG_TOKEN is set; otherwise plays dead.
Kept out of server.py: pure diagnostics, no game-state mutation.
"""

from __future__ import annotations

import asyncio
import copy
import os


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


def _snapshot_xray(rnd, source_bot):
    """Detach every object the worker may read or mutate.

    The caller holds the room lock.  Copying both values here means the worker
    neither advances the live bot nor reads a round that can change underneath
    it after the lock is released.
    """
    return copy.deepcopy(rnd), copy.deepcopy(source_bot)


def _bury_xray(rnd, seat: int, isolated_bot) -> dict:
    """Run and redact one banker-kitty decision for the debug overlay.

    ``last_bury_record`` intentionally contains replay-only material such as
    the full pre-decision RNG state.  The browser needs the action, scores and
    finite-work account, not that internal record.  Keep an explicit allowlist
    here so future fields do not become client-visible by accident.
    """
    pick = list(isolated_bot.decide_bury(rnd, seat))
    policy = getattr(
        isolated_bot, "policy_name", type(isolated_bot).__name__)
    record = getattr(isolated_bot, "last_bury_record", None)

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
        }

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
    }


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
    }
    if rnd.phase == "bury" and rnd.turn == seat:
        out["bury"] = _bury_xray(rnd, seat, isolated_bot)
    elif rnd.phase == "play" and rnd.turn == seat:
        # The snapshot starts at the live bot's exact RNG position.  The pick
        # and displayed values come from the same isolated evaluation.
        pick = isolated_bot.decide_play(rnd, seat)
        if getattr(isolated_bot, "last_eval", None) is not None:
            cands, means = isolated_bot.last_eval
            # last_eval is acting-team perspective; report attacker points.
            sign = 1.0 if rnd.is_attacker(seat) else -1.0
            vals = [[sign * m] for m in means]
        else:                          # TRACTOR_LOCK / forced play: no search
            cands, vals = [pick], [[]]

        def stats(values: list[float]) -> tuple[float, float]:
            n = max(len(values), 1)
            mean = sum(values) / n
            var = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
            return mean, (var / n) ** 0.5

        out["candidates"] = sorted(
            [{"play": candidate,
              "attackers_avg": round(stats(vals[index])[0], 1),
              "se": round(stats(vals[index])[1], 1),
              "heuristic_pick": index == 0,
              "bot_plays": sorted(candidate) == sorted(pick)}
             for index, candidate in enumerate(cands)],
            key=lambda item: item["attackers_avg"],
            reverse=bool(out["is_attacker"]),
        )
    return out


async def _xray_off_loop(rnd, seat: int, isolated_bot) -> dict:
    """Run CPU-heavy X-ray search without blocking WebSockets.

    Both inputs are detached before this call.  Cancellation is delayed until
    the worker exits so cancelled debug requests cannot accumulate orphaned
    report-LCB searches.
    """
    worker = asyncio.create_task(
        asyncio.to_thread(_xray, rnd, seat, isolated_bot),
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
    async with room.lock:
        if room.round is None or room.round.ordering is None:
            return {"error": "no active round"}
        source_bot = getattr(room, "bot", None) or fallback_bot
        rnd_copy, bot_copy = _snapshot_xray(room.round, source_bot)
    return await _xray_off_loop(rnd_copy, seat, bot_copy)


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
