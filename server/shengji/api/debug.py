"""Token-gated debug endpoints (live bot X-ray).

Enabled only when SHENGJI_DEBUG_TOKEN is set; otherwise plays dead.
Kept out of server.py: pure diagnostics, no game-state mutation.
"""

from __future__ import annotations

import asyncio
import copy
import os


def _snapshot_xray(rnd, source_bot):
    """Detach every object the worker may read or mutate.

    The caller holds the room lock.  Copying both values here means the worker
    neither advances the live bot nor reads a round that can change underneath
    it after the lock is released.
    """
    return copy.deepcopy(rnd), copy.deepcopy(source_bot)


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
    }
    if rnd.phase == "play" and rnd.turn == seat:
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
