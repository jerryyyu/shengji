"""Rule-based baseline bot.

Every decision method returns concrete cards and is guaranteed legal: plays
are constructed constructively, then double-checked against the engine's
validators (with a safe fallback) so the server can trust bot output.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import BJ, LJ, TRUMP, Ordering, card_rank, is_joker, points
from ..engine.combos import decompose, find_tractor_runs, pair_count
from ..engine.legal import IllegalPlay, beats, suit_cards, uniform_suit, validate_follow
from ..engine.round import Round

PLAIN_SUITS = "SHDC"


class HeuristicBot:
    DECLARE_MIN = 9     # trump-count needed to declare during the deal
    DECLARE_FINAL = 7   # lower bar in the grace window
    VOID_DUMP = True    # when dumping junk, prefer emptying short suits —
    #                     opens ruff lanes (user-observed gap via X-ray;
    #                     measured 55% head-to-head vs plain, n=150 games)

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
        return best if best_score >= (self.DECLARE_FINAL if final
                                      else self.DECLARE_MIN) else None

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
            v += points(c) * self._bury_points_mult(suit_len[TRUMP],
                                                    hand.count("BJ") > 0)
            v -= self._bury_short_bonus(suit_len[o.eff_suit(c)])  # shed short suits
            return v

        ranked = sorted(hand, key=keep_value)
        return ranked[:8]

    def _bury_short_bonus(self, suit_len: int) -> float:
        return (8 - min(suit_len, 8)) * 0.5

    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 2.5

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
            # A k-pair tractor needs at least k physical pairs.  Most rollout
            # suits contain fewer than two, so avoid asking the tractor
            # enumerator questions whose answer is provably empty.
            available_pairs = pair_count(cards)
            if available_pairs < 2:
                continue
            for k in range(min(5, available_pairs), 1, -1):
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
        # Count the hand once.  Building one Counter per plain suit was the
        # hottest allocation inside rollout leads; tuple-max below already
        # supplies the exact level/card tie-break, so item order is irrelevant.
        pairs = [(o.level(c), c) for c, n in Counter(hand).items()
                 if n >= 2 and o.eff_suit(c) in PLAIN_SUITS]
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
        trick_pts = (getattr(rnd.trick, "running_points", None)
                     if getattr(rnd, "_trusted_rollout", False) else None)
        if trick_pts is None:
            trick_pts = sum(
                points(c) for tp in rnd.trick.plays for c in tp.cards)
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
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        if getattr(rnd, "_trusted_rollout", False):
            inc = getattr(rnd.trick, "incumbent", None)
            if inc is not None:
                return inc
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
        lead_suit = uniform_suit(lead, o)
        assert lead_suit is not None
        h_lead = suit_cards(hand, lead_suit, o)
        if len(lead_dec.components) != 1:
            # A throw is beatable only by matching its whole shape in trump.
            if lead_suit == TRUMP or h_lead:
                return None  # must be void in the led suit to ruff
            trumps = suit_cards(hand, TRUMP, o)
            if len(trumps) < len(lead):
                return None
            play = self._trump_shape_match(trumps, lead_dec, o)
            if play is not None:
                won, _ = beats(play, lead, inc_suit, inc_top, o)
                if won:
                    return play
            return None
        comp = lead_dec.components[0]

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

    def _trump_shape_match(self, trumps: list[str], lead_dec,
                           o: Ordering) -> list[str] | None:
        """Cheapest all-trump set matching a throw's shape (runs + singles)."""
        runs = sorted((c.pair_len for c in lead_dec.components if c.pair_len),
                      reverse=True)
        n_singles = sum(1 for c in lead_dec.components if not c.pair_len)
        pool = list(trumps)
        picked: list[str] = []
        for k in runs:
            if k == 1:
                pairs = sorted((c for c, n in Counter(pool).items() if n >= 2),
                               key=o.level)
                if not pairs:
                    return None
                c = pairs[0]
                picked += [c, c]
                self._take(pool, [c, c])
            else:
                rs = find_tractor_runs(pool, o, k)
                if not rs:
                    return None
                picked += rs[0]
                self._take(pool, rs[0])
        for _ in range(n_singles):
            if not pool:
                return None
            c = self._lowest(pool, o, avoid_points=True)
            picked.append(c)
            pool.remove(c)
        return picked

    def _forced_follow(self, hand: list[str], lead: list[str], o: Ordering,
                       prefer_points: bool,
                       avoid: set[str] | None = None) -> list[str]:
        """Construct a legal minimal follow, dumping points if asked.
        Cards in ``avoid`` are kept back when there's any alternative."""
        avoid = avoid or set()
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
                           key=lambda c: (c in avoid, o.level(c)))
            for c in pairs[:max(0, need)]:
                picked += [c, c]
                self._take(pool, [c, c])
            fill_pool = pool
        else:
            picked = list(h_suit)
            fill_pool = self._minus(hand, picked)
        while len(picked) < n:
            c = self._lowest(fill_pool, o, avoid_points=not prefer_points,
                             seek_points=prefer_points, avoid=avoid)
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
                seek_points: bool = False, avoid: set[str] | None = None) -> str:
        avoid = avoid or set()
        if self.VOID_DUMP:
            suit_n = Counter(o.eff_suit(c) for c in cards)

        def key(c: str) -> tuple:
            trumpish = o.eff_suit(c) == TRUMP
            # shorter suit first when junking (1 card from a singleton beats
            # an equal card from a long suit: it opens a ruff lane)
            vlen = suit_n[o.eff_suit(c)] if self.VOID_DUMP and not trumpish else 0
            if seek_points:
                return (c in avoid, -points(c), trumpish, o.level(c))
            if avoid_points:
                return (c in avoid, trumpish, points(c) > 0, vlen, o.level(c))
            return (c in avoid, trumpish, vlen, o.level(c))
        return min(cards, key=key)
