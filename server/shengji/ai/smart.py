"""Memory-aware bot: HeuristicBot + card counting, boss detection, void
inference, and safer point feeding. Uses only public information (see
memory.py)."""

from __future__ import annotations

from ..engine.cards import TRUMP, points
from ..engine.combos import decompose
from ..engine.legal import suit_cards, uniform_suit
from ..engine.round import Round
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory


class SmartBot(HeuristicBot):
    FEED_ON_TRUMP = False   # feed points when partner ruffs, even if overtrumpable
    TRUMP_DRAIN = False     # lead boss trumps from long holdings (measured: hurts)
    SAFE_TRACTOR_ONLY = True  # skip tractor leads into likely ruffs

    # ------------------------------------------------------------------- lead
    def _lead(self, rnd: Round, seat: int) -> list[str]:
        o = rnd.ordering
        assert o is not None
        mem = Memory(rnd, seat)
        hand = rnd.hands[seat]
        opps = [s for s in range(4) if s % 2 != seat % 2]
        by_suit = {s: suit_cards(hand, s, o) for s in list(PLAIN_SUITS) + [TRUMP]}

        # Scan plain suits once for boss components (ruff-safe suits only).
        boss_paired: list[tuple[tuple, list[str]]] = []
        boss_single: list[tuple[tuple, list[str]]] = []
        for s in PLAIN_SUITS:
            cards = by_suit[s]
            if not cards or mem.ruff_risk(s, opps):
                continue
            for comp in decompose(cards, o).components:
                top_code = max(comp.cards, key=o.level)
                boss = (mem.pair_is_boss(top_code) if comp.pair_len
                        else mem.is_boss(top_code))
                if boss:
                    pts = sum(points(c) for c in comp.cards)
                    entry = ((comp.pair_len, pts, comp.top), comp.cards)
                    (boss_paired if comp.pair_len else boss_single).append(entry)

        # 1) Boss pairs/tractors: guaranteed winners that also dump cards.
        if boss_paired:
            return max(boss_paired, key=lambda c: c[0])[1]

        # 2) Tractor pressure (forces pairs out), ruff-safe only.
        best_tr: list[str] | None = None
        for s in PLAIN_SUITS:
            if self.SAFE_TRACTOR_ONLY and mem.ruff_risk(s, opps):
                continue
            for comp in decompose(by_suit[s], o).components:
                if comp.pair_len >= 2 and (best_tr is None or comp.size > len(best_tr)):
                    best_tr = comp.cards
        if best_tr:
            return best_tr

        # 3) Boss singles, then boss trumps from a long holding (draining).
        if boss_single:
            return max(boss_single, key=lambda c: c[0])[1]
        if self.TRUMP_DRAIN and len(by_suit[TRUMP]) >= 6 and mem.unseen_trumps() > 0:
            for comp in sorted(decompose(by_suit[TRUMP], o).components,
                               key=lambda c: (-c.pair_len, -c.top)):
                if mem.is_boss(max(comp.cards, key=o.level)):
                    return comp.cards

        # 4) Low card from the longest plain suit no opponent has shown void in.
        safe = [(len(by_suit[s]), s) for s in PLAIN_SUITS
                if by_suit[s] and not any(s in mem.voids[op] for op in opps)]
        if safe:
            _, s = max(safe)
            return [self._lowest(by_suit[s], o, avoid_points=True)]
        plain = [(len(by_suit[s]), s) for s in PLAIN_SUITS if by_suit[s]]
        if plain:
            _, s = max(plain)
            return [self._lowest(by_suit[s], o, avoid_points=True)]
        return [self._lowest(by_suit[TRUMP], o, avoid_points=True)]

    # ----------------------------------------------------------------- follow
    def _follow(self, rnd: Round, seat: int) -> list[str]:
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        mem = Memory(rnd, seat)
        hand = rnd.hands[seat]
        trick = rnd.trick
        lead = trick.plays[0].cards
        n_played = len(trick.plays)
        to_act = [(trick.leader + i) % 4 for i in range(n_played + 1, 4)]
        opp_to_act = [s for s in to_act if s % 2 != seat % 2]

        win_seat, inc_suit, inc_top = self._current_winner(rnd)
        partner_winning = win_seat % 2 == seat % 2
        trick_pts = sum(points(c) for tp in trick.plays for c in tp.cards)

        if partner_winning:
            # Feed points only when the partner's play can't be beaten by
            # anyone still to act; otherwise keep points home.
            secure = not mem.beat_risk(inc_suit, inc_top, opp_to_act)
            if self.FEED_ON_TRUMP and inc_suit == TRUMP:
                secure = True
            return self._forced_follow(hand, lead, o, prefer_points=secure)

        winning = self._cheapest_winning(hand, lead, inc_suit, inc_top, o)
        if winning is not None:
            w_suit = o.eff_suit(winning[0])
            uses_trump = w_suit == TRUMP and uniform_suit(lead, o) != TRUMP
            if not uses_trump:
                return winning  # in-suit wins are cheap tempo — always contest
            # Spending trump: memory decides whether it's worth it.
            w_top = decompose(winning, o).top_level()
            holds = not mem.beat_risk(w_suit, w_top, opp_to_act)
            if trick_pts >= 10 or (holds and trick_pts > 0):
                return winning
        return self._forced_follow(hand, lead, o, prefer_points=False)
