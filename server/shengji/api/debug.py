"""Token-gated debug endpoints (live bot X-ray).

Enabled only when SHENGJI_DEBUG_TOKEN is set; otherwise plays dead.
Kept out of server.py: pure diagnostics, no game-state mutation.
"""

from __future__ import annotations

import os


def register_debug(app, rooms) -> None:
    # ------------------------------------------------------------------- debug
    DEBUG_TOKEN = os.environ.get("SHENGJI_DEBUG_TOKEN", "")


    def _xray(rnd, seat: int) -> dict:
        """What the bot sees and would play from this seat, right now."""
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
                                 if suit_cards(hand, s, o) and mem.ruff_risk(s, opps)],
            "candidates": None,
        }
        if rnd.phase == "play" and rnd.turn == seat:
            mc = room_bot_for_xray
            cands = mc._candidates(rnd, seat)
            vals: list[list[float]] = [[] for _ in cands]
            for _ in range(30):
                smp = mc._sample_hands(rnd, seat, mem)
                if smp is None:
                    continue
                hands_s, buried = smp
                for i, c in enumerate(cands):
                    vals[i].append(mc._rollout(rnd, seat, hands_s, buried, list(c)))
            pick = mc.decide_play(rnd, seat)

            def stats(v: list[float]) -> tuple[float, float]:
                n = max(len(v), 1)
                mean = sum(v) / n
                var = sum((x - mean) ** 2 for x in v) / max(n - 1, 1)
                return mean, (var / n) ** 0.5
            out["candidates"] = sorted(
                [{"play": c,
                  "attackers_avg": round(stats(vals[i])[0], 1),
                  "se": round(stats(vals[i])[1], 1),  # differences under ~2 SE
                  #                                     are noise; the bot's margin
                  #                                     rule ignores them
                  "heuristic_pick": i == 0,
                  "bot_plays": sorted(c) == sorted(pick)}
                 for i, c in enumerate(cands)],
                key=lambda x: x["attackers_avg"],
                reverse=bool(out["is_attacker"]))
        return out


    from ..ai.mcbot import MCBot as _XrayBot  # noqa: E402
    room_bot_for_xray = _XrayBot(seed=1234)


    @app.get("/debug/xray")
    async def debug_xray(room: str, seat: int, token: str = "") -> dict:
        if not DEBUG_TOKEN or token != DEBUG_TOKEN:
            return {"error": "not found"}
        r = rooms.get(room.upper())
        if r is None or r.round is None or r.round.ordering is None:
            return {"error": "no active round"}
        async with r.lock:
            return _xray(r.round, seat)


