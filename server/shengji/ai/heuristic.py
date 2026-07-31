"""Rule-based baseline bot.

Every decision method returns concrete cards and is guaranteed legal: plays
are constructed constructively, then double-checked against the engine's
validators (with a safe fallback) so the server can trust bot output.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import BJ, LJ, TRUMP, Ordering, card_rank, is_joker, points
from ..engine.combos import decompose, find_tractor_runs, pair_count
from ..engine.legal import IllegalPlay, suit_cards, uniform_suit, validate_follow
from ..engine.round import Round

PLAIN_SUITS = "SHDC"


class HeuristicBot:
    # ---------------------------------------------------------------- declare
    def decide_declare(self, rnd: Round, seat: int,
                       final: bool = False) -> list[str] | None:
        """Called after each dealt card and once more in the grace window
        (``final=True``, lower bar so weak-trump rounds still get a suit)."""
        options = rnd.declare_options(seat)
        if not options:
            return None
        hand = rnd.hands[seat]
        best, best_score = None, 0
        for opt in options:
            code = opt[0]
            if is_joker(code):
                n_rank = sum(1 for c in hand if card_rank(c) == rnd.trump_rank)
                score = 14 + n_rank if n_rank >= 3 else 0  # NT needs rank support
            else:
                suit = code[0]
                n_trump = sum(
                    1 for c in hand
                    if is_joker(c) or card_rank(c) == rnd.trump_rank or c[0] == suit
                )
                score = n_trump + (2 if len(opt) == 2 else 0)
            if score > best_score:
                best, best_score = opt, score
        return best if best_score >= (7 if final else 9) else None

    # ------------------------------------------------------------------- bury
    def decide_bury(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.ordering is not None
        o = rnd.ordering
        hand = list(rnd.hands[seat])
        cnt = Counter(hand)
        suit_len = Counter(o.eff_suit(c) for c in hand)

        def keep_value(c: str) -> float:
            if o.eff_suit(c) == TRUMP:
                return 100 + o.level(c)
            v = float(o.level(c))
            if o.level(c) >= len(o.plain_ranks) - 1:
                v += 40  # aces
            if cnt[c] >= 2:
                v += 25  # don't break pairs
            v += points(c) * 2.5
            v -= (8 - min(suit_len[o.eff_suit(c)], 8)) * 0.5  # shed short suits
            return v

        ranked = sorted(hand, key=keep_value)
        return ranked[:8]

    # ------------------------------------------------------------------- play
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        if not rnd.trick.plays:
            return self._lead(rnd, seat)
        play = self._follow(rnd, seat)
        try:
            validate_follow(play, rnd.hands[seat], rnd.trick.plays[0].cards, rnd.ordering)
        except IllegalPlay:
            play = self._forced_follow(rnd.hands[seat], rnd.trick.plays[0].cards,
                                       rnd.ordering, prefer_points=False)
        return play

    # ------------------------------------------------------------------- lead
    def _lead(self, rnd: Round, seat: int) -> list[str]:
        o = rnd.ordering
        assert o is not None
        hand = rnd.hands[seat]
        by_suit = {s: suit_cards(hand, s, o) for s in list(PLAIN_SUITS) + [TRUMP]}

        # Longest tractor anywhere (>=2 pairs) is a strong lead.
        best_tr: list[str] | None = None
        for s, cards in by_suit.items():
            for k in range(5, 1, -1):
                runs = find_tractor_runs(cards, o, k)
                if runs and (best_tr is None or len(runs[-1]) > len(best_tr)):
                    best_tr = runs[-1]
                    break
        if best_tr:
            return best_tr

        top_plain = len(o.plain_ranks) - 1
        # Ace pair, then lone ace, in plain suits.
        for s in PLAIN_SUITS:
            cards = by_suit[s]
            aces = [c for c in cards if o.level(c) == top_plain]
            if len(aces) >= 2:
                return aces[:2]
        for s in PLAIN_SUITS:
            aces = [c for c in by_suit[s] if o.level(c) == top_plain]
            if aces:
                return aces[:1]
        # High plain pair.
        pairs = [(o.level(c), c) for s in PLAIN_SUITS for c, n in
                 Counter(by_suit[s]).items() if n >= 2]
        if pairs:
            lv, c = max(pairs)
            if lv >= top_plain - 3:
                return [c, c]
        # Low single from the longest plain suit (avoid points).
        plain = [(len(by_suit[s]), s) for s in PLAIN_SUITS if by_suit[s]]
        if plain:
            _, s = max(plain)
            return [self._lowest(by_suit[s], o, avoid_points=True)]
        return [self._lowest(by_suit[TRUMP], o, avoid_points=True)]

    # ----------------------------------------------------------------- follow
    def _follow(self, rnd: Round, seat: int) -> list[str]:
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        hand = rnd.hands[seat]
        lead = rnd.trick.plays[0].cards
        win_seat, inc_suit, inc_top = self._current_winner(rnd)
        partner_winning = win_seat % 2 == seat % 2
        trick_pts = sum(points(c) for tp in rnd.trick.plays for c in tp.cards)
        is_last = len(rnd.trick.plays) == 3

        if partner_winning:
            strong = inc_suit == TRUMP or inc_top >= len(o.plain_ranks) - 1
            return self._forced_follow(hand, lead, o,
                                       prefer_points=strong or is_last)

        winning = self._cheapest_winning(hand, lead, inc_suit, inc_top, o)
        if winning is not None:
            uses_trump = o.eff_suit(winning[0]) == TRUMP and \
                uniform_suit(lead, o) != TRUMP
            worth = trick_pts >= 10 or (is_last and trick_pts > 0) or not uses_trump
            if worth:
                return winning
        return self._forced_follow(hand, lead, o, prefer_points=False)

    def _current_winner(self, rnd: Round) -> tuple[int, str, int]:
        from ..engine.legal import beats
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        lead = rnd.trick.plays[0].cards
        suit = uniform_suit(lead, o)
        assert suit is not None
        top = decompose(lead, o).top_level()
        winner = rnd.trick.plays[0].seat
        for tp in rnd.trick.plays[1:]:
            won, t = beats(tp.cards, lead, suit, top, o)
            if won:
                winner, top = tp.seat, t
                suit = o.eff_suit(tp.cards[0])
        return winner, suit, top

    def _cheapest_winning(self, hand: list[str], lead: list[str], inc_suit: str,
                          inc_top: int, o: Ordering) -> list[str] | None:
        lead_dec = decompose(lead, o)
        if len(lead_dec.components) != 1:
            return None  # don't try to beat throws
        comp = lead_dec.components[0]
        lead_suit = uniform_suit(lead, o)
        assert lead_suit is not None
        h_lead = suit_cards(hand, lead_suit, o)

        def combo_in(cards: list[str], min_top: int) -> list[str] | None:
            if comp.kind == "single":
                cands = sorted((c for c in cards if o.level(c) > min_top),
                               key=o.level)
                return [cands[0]] if cands else None
            if comp.kind == "pair":
                cands = sorted((c for c, n in Counter(cards).items()
                                if n >= 2 and o.level(c) > min_top), key=o.level)
                return [cands[0]] * 2 if cands else None
            runs = [r for r in find_tractor_runs(cards, o, comp.pair_len)
                    if o.level(r[-1]) > min_top]
            return runs[0] if runs else None

        if len(h_lead) >= len(lead):
            if inc_suit == lead_suit:
                return combo_in(h_lead, inc_top)
            return None  # someone trumped; in-suit can't win
        if h_lead:
            return None  # must dump remaining lead-suit cards; can't win
        trumps = suit_cards(hand, TRUMP, o)
        if lead_suit != TRUMP and len(trumps) >= len(lead):
            floor = inc_top if inc_suit == TRUMP else -1
            return combo_in(trumps, floor)
        return None

    def _forced_follow(self, hand: list[str], lead: list[str], o: Ordering,
                       prefer_points: bool) -> list[str]:
        """Construct a legal minimal follow, dumping points if asked."""
        n = len(lead)
        lead_suit = uniform_suit(lead, o)
        assert lead_suit is not None
        h_suit = suit_cards(hand, lead_suit, o)
        picked: list[str] = []
        if len(h_suit) >= n:
            pool = list(h_suit)
            lead_dec = decompose(lead, o)
            # tractor obligation
            if len(lead_dec.components) == 1 and lead_dec.components[0].kind == "tractor":
                runs = find_tractor_runs(pool, o, lead_dec.components[0].pair_len)
                if runs:
                    picked += runs[0]
                    self._take(pool, runs[0])
            # pair obligation
            need = min(lead_dec.n_pairs, pair_count(h_suit)) - pair_count(picked)
            pairs = sorted((c for c, k in Counter(pool).items() if k >= 2),
                           key=o.level)
            for c in pairs[:max(0, need)]:
                picked += [c, c]
                self._take(pool, [c, c])
            fill_pool = pool
        else:
            picked = list(h_suit)
            fill_pool = self._minus(hand, picked)
        while len(picked) < n:
            c = self._lowest(fill_pool, o, avoid_points=not prefer_points,
                             seek_points=prefer_points)
            picked.append(c)
            fill_pool.remove(c)
        return picked[:n]

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _take(pool: list[str], cards: list[str]) -> None:
        for c in cards:
            pool.remove(c)

    @staticmethod
    def _minus(hand: list[str], used: list[str]) -> list[str]:
        pool = list(hand)
        for c in used:
            pool.remove(c)
        return pool

    def _lowest(self, cards: list[str], o: Ordering, avoid_points: bool = False,
                seek_points: bool = False) -> str:
        def key(c: str) -> tuple:
            trumpish = o.eff_suit(c) == TRUMP
            if seek_points:
                return (-points(c), trumpish, o.level(c))
            if avoid_points:
                return (trumpish, points(c) > 0, o.level(c))
            return (trumpish, o.level(c))
        return min(cards, key=key)
