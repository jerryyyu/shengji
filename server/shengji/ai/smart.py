"""Memory-aware bot: HeuristicBot + card counting, boss detection, void
inference, and safer point feeding. Uses only public information (see
memory.py)."""

from __future__ import annotations

from collections import Counter

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
    SAFE_THROWS = True      # lead multi-component throws when every part is boss
    RESERVE_LAST = False    # hold a boss combo for the last trick (measured: hurts)
    RESERVE_MARGIN = 3      # keep the reserve while hand exceeds its size by this
    CONTEST_PTS = 10        # trump-spend threshold when the win isn't guaranteed
    TEMPO_GUARD = True      # don't burn rank-trumps/jokers winning 0-point
    #                         tricks (XCYB: BJ spent beating a rank-4)
    TRACTOR_FIRST = False   # tractors outrank boss pairs in the lead order
    #                         (user: "if there is a tractor, HIGHLY consider")
    SIZE_FIRST = False      # strict "more cards is better" lead order: any
    #                         ruff-safe tractor, then any ruff-safe pair,
    #                         before all smaller leads (user idea, 2026-08-02)
    ACE_SEQ = False         # cash boss singles in follow-able suits before
    #                         ruff-risky ones (expert research #1, 2026-08-02)
    NO_OPEN_POINT_SUIT = False  # don't open point-bearing suits we don't
    #                             boss (expert research #3, 2026-08-02)
    PAIR_VOID_BOSS = False  # lead a LOW pair once all opponents have proven
    #                         pair-void in its suit (forced pair-matching
    #                         makes a broken answer proof; user, 2026-08-02)
    ANY_PAIR_OVER_JUNK = False  # last-resort leads prefer ANY pair to a
    #                             passive low single (user: junk needs a reason)
    LATE_TRUMP_PAIRS = True   # lead top trump pair when hand <= 12 (mined
    #                           from human play: +7.3/decision, 8/8 better)
    TEMPO_SEEK = False      # spend cheap trump winning low-point tricks when
    #                         a boss-pair/throw follow-up is waiting (user)
    BURY_VOID = True        # bury toward emptying 1-3 card suits (ruff setup)
    CONTROL_LEADS = True    # user-spec leader hierarchy: pairs > suit-emptying
    #                         > forcing singles > junk (measured 67% h2h, n=150)
    DECLARE_MIN = 8         # slightly more eager declarer than baseline (9)
    DECLARE_FINAL = 6
    # --- research-derived toggles (see AI_POLICIES.md for measurements) ---
    ENDGAME_CONTROL = True    # contest every winnable trick in the last ~6
    TRUMP_DRAIN_V2 = False    # banker cheap-trump draining (measured: hurts)
    DECLARE_TUNE = False      # weak-suit declaration (measured: hurts)
    BURY_TRUMP_GATE = True    # bury points only when trump can defend the kitty
    PARTNER_VOID_LEAD = False # feed partner ruffs (neutral alone, hurts combined)

    # ---------------------------------------------------------------- declare
    def decide_declare(self, rnd: Round, seat: int,
                       final: bool = False) -> list[str] | None:
        if not self.DECLARE_TUNE:
            return super().decide_declare(rnd, seat, final)
        from ..engine.cards import card_rank, is_joker
        options = rnd.declare_options(seat)
        if not options:
            return None
        hand = rnd.hands[seat]
        threshold = self.DECLARE_FINAL if final else self.DECLARE_MIN
        if rnd.trump_rank in ("5", "10", "K"):
            threshold -= 1  # rank cards are points; protect them as trump
        scored = []
        for opt in options:
            code = opt[0]
            if is_joker(code):
                n_rank = sum(1 for c in hand if card_rank(c) == rnd.trump_rank)
                score = 14 + n_rank if n_rank >= 3 else 0
                quality = 0.0
            else:
                suit = code[0]
                suit_cards_ = [c for c in hand
                               if not is_joker(c) and c[0] == suit]
                score = sum(
                    1 for c in hand
                    if is_joker(c) or card_rank(c) == rnd.trump_rank or c[0] == suit
                ) + (2 if len(opt) == 2 else 0)
                from collections import Counter as _C
                cnt = _C(suit_cards_)
                quality = (sum(1 for c in suit_cards_ if card_rank(c) in ("A", "K"))
                           + 2 * sum(1 for _, k in cnt.items() if k >= 2))
            scored.append((score, quality, opt))
        best = max(s for s, _, _ in scored)
        if best < threshold:
            return None
        # among near-best options, declare the WEAKER suit: trump power
        # compensates, and the strong suit becomes a scoring engine
        close = [x for x in scored if x[0] >= best - 1]
        return min(close, key=lambda x: x[1])[2]

    # ------------------------------------------------------------------- bury
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        if not self.BURY_TRUMP_GATE:
            return super()._bury_points_mult(trump_count, has_big_joker)
        if trump_count >= 11 and has_big_joker:
            return 1.5   # strong trump: loose points in the kitty are safe
        if trump_count < 9 or not has_big_joker:
            return 6.0   # can't defend the kitty: never bury points
        return 2.5

    def _bury_short_bonus(self, suit_len: int) -> float:
        if self.BURY_VOID and suit_len <= 3:
            return {1: 15.0, 2: 12.0, 3: 8.0}[suit_len]
        return super()._bury_short_bonus(suit_len)

    def near_boss_throws(self, rnd: Round, seat: int, mem: Memory) -> list[list[str]]:
        """Candidate throws whose pair components are boss OR near-boss
        (beatable only if one opponent holds BOTH copies of a higher rank)
        and whose singles are boss. Not provably safe — meant for MCBot's
        ballot, where sampled worlds price the risk (e.g. A+QQ: AA blocked
        by the held ace, KK possible but ~25-30% likely)."""
        o = rnd.ordering
        assert o is not None
        opps = [s for s in range(4) if s % 2 != seat % 2]
        out: list[list[str]] = []
        for s in PLAIN_SUITS:
            cards = suit_cards(rnd.hands[seat], s, o)
            if not cards or mem.ruff_risk(s, opps):
                continue
            comps = decompose(cards, o).components
            ok, has_near = [], False
            for comp in comps:
                top_code = max(comp.cards, key=o.level)
                if comp.pair_len:
                    if mem.pair_is_boss(top_code):
                        ok.append(comp)
                    else:
                        # near-boss: no single unseen rank above with 2 copies
                        # is required to be absent — allow exactly one such
                        # threat rank (the "KK over QQ" case)
                        lvl = o.level(top_code)
                        threats = sum(1 for c, n in mem.unseen.items()
                                      if o.eff_suit(c) == s and o.level(c) > lvl
                                      and n >= 2)
                        if threats == 1:
                            ok.append(comp)
                            has_near = True
                        else:
                            ok = []
                            break
                else:
                    if mem.is_boss(top_code):
                        ok.append(comp)
                    else:
                        ok = []
                        break
            if len(ok) >= 2 and has_near:
                out.append([c for comp in ok for c in comp.cards])
        return out

    def _followup_size(self, rnd: Round, seat: int, mem: Memory) -> int:
        """Cards in guaranteed paired winners waiting in hand (boss pairs /
        tractors) — the prize that winning the current trick unlocks."""
        boss = self._boss_components(rnd, seat, mem)
        return sum(c.size for comps in boss.values() for c in comps
                   if c.pair_len)

    # ---------------------------------------------------------------- helpers
    def _boss_components(self, rnd: Round, seat: int, mem: Memory) -> dict[str, list]:
        """Boss components per ruff-safe plain suit."""
        o = rnd.ordering
        assert o is not None
        opps = [s for s in range(4) if s % 2 != seat % 2]
        out: dict[str, list] = {}
        for s in PLAIN_SUITS:
            cards = suit_cards(rnd.hands[seat], s, o)
            if not cards or mem.ruff_risk(s, opps):
                continue
            comps = []
            for comp in decompose(cards, o).components:
                top_code = max(comp.cards, key=o.level)
                boss = (mem.pair_is_boss(top_code) if comp.pair_len
                        else mem.is_boss(top_code))
                if boss:
                    comps.append(comp)
            if comps:
                out[s] = comps
        return out

    def _reserve(self, rnd: Round, seat: int, mem: Memory,
                 boss: dict[str, list] | None = None) -> set[str]:
        """Attackers save their biggest boss paired combo for the last trick
        (the kitty multiplier scales with its size)."""
        if not self.RESERVE_LAST or rnd.banker is None or not rnd.is_attacker(seat):
            return set()
        if boss is None:
            boss = self._boss_components(rnd, seat, mem)
        paired = [c for comps in boss.values() for c in comps if c.pair_len]
        if not paired:
            return set()
        r = max(paired, key=lambda c: (c.pair_len, c.top))
        if len(rnd.hands[seat]) - r.size >= self.RESERVE_MARGIN:
            return set(r.cards)
        return set()

    # ------------------------------------------------------------------- lead
    def _lead(self, rnd: Round, seat: int) -> list[str]:
        o = rnd.ordering
        assert o is not None
        mem = Memory(rnd, seat)
        hand = rnd.hands[seat]
        opps = [s for s in range(4) if s % 2 != seat % 2]
        by_suit = {s: suit_cards(hand, s, o) for s in list(PLAIN_SUITS) + [TRUMP]}

        boss = self._boss_components(rnd, seat, mem)
        reserve = self._reserve(rnd, seat, mem, boss)
        if reserve:
            boss = {s: [c for c in comps if not (set(c.cards) & reserve)]
                    for s, comps in boss.items()}
            boss = {s: comps for s, comps in boss.items() if comps}

        def entry(comp) -> tuple[tuple, list[str]]:
            pts = sum(points(c) for c in comp.cards)
            # list(): comp.cards aliases the decompose cache — never let it
            # escape as a play the caller might mutate (cache-poison class)
            return ((comp.pair_len, pts, comp.top), list(comp.cards))

        # 0) Safe throw: several boss components in one suit, led together.
        #    Every part is unbeatable in-suit, so the throw can never fail.
        if self.SAFE_THROWS:
            best_throw: list[str] | None = None
            for comps in boss.values():
                if len(comps) >= 2:
                    cards = [c for comp in comps for c in comp.cards]
                    if best_throw is None or len(cards) > len(best_throw):
                        best_throw = cards
            if best_throw:
                return best_throw

        # 1) Tractors first when enabled: only an equal-length higher tractor
        #    answers (rarest holding), and they shed the most cards.
        best_tr: list[str] | None = None
        for s in PLAIN_SUITS:
            if self.SAFE_TRACTOR_ONLY and mem.ruff_risk(s, opps):
                continue
            for comp in decompose(by_suit[s], o).components:
                if set(comp.cards) & reserve:
                    continue
                if comp.pair_len >= 2 and (best_tr is None or comp.size > len(best_tr)):
                    best_tr = list(comp.cards)  # decouple from decompose cache
        if self.TRACTOR_FIRST and best_tr:
            return best_tr

        # 1.5) Strict size-first: the biggest ruff-safe structure leads, rank
        #      be damned. (Supersedes TRACTOR_FIRST + ANY_PAIR_OVER_JUNK.)
        if self.SIZE_FIRST:
            if best_tr:
                return best_tr
            sz_pairs = []
            for s in PLAIN_SUITS:
                if mem.ruff_risk(s, opps):
                    continue
                for c, k in Counter(by_suit[s]).items():
                    if k >= 2 and c not in reserve:
                        sz_pairs.append((o.level(c), c))
            if sz_pairs:
                _, c = max(sz_pairs)
                return [c, c]

        # 2) Boss pairs: guaranteed winners that also dump cards.
        boss_paired = [entry(c) for comps in boss.values() for c in comps if c.pair_len]
        boss_single = [entry(c) for comps in boss.values() for c in comps
                       if not c.pair_len]
        if self.ACE_SEQ and boss_single:
            # Expert rule (研究 #1): cash aces opponents must FOLLOW before
            # aces in their likely-void suits — ruff-risky boss suits last.
            safe_bs = [e for e in boss_single
                       if not mem.ruff_risk(o.eff_suit(e[1][0]), opps)]
            if safe_bs:
                boss_single = safe_bs
        if boss_paired:
            return max(boss_paired, key=lambda c: c[0])[1]
        if best_tr:
            return best_tr

        # 2.5) Banker-side draining: with clearly superior trump, lead CHEAP
        # trumps to strip opponents while keeping jokers/rank pairs.
        if (self.TRUMP_DRAIN_V2 and rnd.banker is not None
                and seat % 2 == rnd.banker % 2):
            trumps = by_suit[TRUMP]
            if (len(trumps) >= 8 and mem.unseen_trumps() >= 4
                    and any(mem.is_boss(c) for c in trumps)):
                return [self._lowest(trumps, o, avoid_points=True)]

        # 3) Boss singles, then boss trumps from a long holding (draining).
        if boss_single:
            return max(boss_single, key=lambda c: c[0])[1]
        if self.TRUMP_DRAIN and len(by_suit[TRUMP]) >= 6 and mem.unseen_trumps() > 0:
            for comp in sorted(decompose(by_suit[TRUMP], o).components,
                               key=lambda c: (-c.pair_len, -c.top)):
                if mem.is_boss(max(comp.cards, key=o.level)):
                    return list(comp.cards)  # decouple from decompose cache

        # 3.5) Feed partner ruffs: lead a suit partner is void in (and no
        # opponent is), while partner can still hold trump.
        if self.PARTNER_VOID_LEAD:
            partner = (seat + 2) % 4
            for s in PLAIN_SUITS:
                if (by_suit[s] and s in mem.voids[partner]
                        and TRUMP not in mem.voids[partner]
                        and not any(s in mem.voids[op] for op in opps)
                        and mem.unseen_trumps() > 0):
                    return [self._lowest(by_suit[s], o, avoid_points=True)]

        # 4) Low card from the longest plain suit no opponent has shown void in.
        safe = [(len(by_suit[s]), s) for s in PLAIN_SUITS
                if by_suit[s] and not any(s in mem.voids[op] for op in opps)]
        if self.CONTROL_LEADS:
            # User-specified leader hierarchy (54% of in-control bot leads
            # were weak junk): non-boss PAIRS first (only a rarer higher
            # pair or ruff answers), then forcing high non-point singles;
            # weak singles only when they FINISH a short suit.
            # Disagreement mining (2026-08-02, 884 human decisions): LATE
            # trump-pair leads were humans' strongest edge over the bot
            # (+7.3/decision, 8/8) — depleted opponents can't answer pairs.
            if self.LATE_TRUMP_PAIRS and len(hand) <= 12:
                tp = [(o.level(c), c) for c, k in
                      Counter(by_suit[TRUMP]).items() if k >= 2]
                if tp:
                    _, c = max(tp)
                    return [c, c]
            ruff_safe = [s for s in PLAIN_SUITS
                         if by_suit[s] and not mem.ruff_risk(s, opps)]
            pairs = []
            for s in ruff_safe:
                for c, k in Counter(by_suit[s]).items():
                    if k >= 2 and not (set([c]) & reserve):
                        pairs.append((o.level(c), c, s))
            if pairs:
                lv, c, _ = max(pairs)
                if lv >= len(o.plain_ranks) - 5:  # J-ish or better
                    return [c, c]
                if self.PAIR_VOID_BOSS:
                    # User insight (2026-08-02): a low pair is boss-shaped
                    # once every opponent has PROVEN no pair in that suit
                    # (rules force pair-matching, so a broken answer is
                    # proof). Ruff risk already screened via ruff_safe.
                    for plv, pc, ps in sorted(pairs, reverse=True):
                        if all(ps in mem.pair_void[op] or ps in mem.voids[op]
                               for op in opps):
                            return [pc, pc]
                if self.ANY_PAIR_OVER_JUNK:
                    low_pair = (lv, c)  # remember: beats junk as last resort
                else:
                    low_pair = None
            else:
                low_pair = None
            for s in ruff_safe:
                if len(by_suit[s]) <= 2:  # emptying a short suit is fine
                    return [self._lowest(by_suit[s], o, avoid_points=True)]
            if safe:
                pool_s = safe
                if self.NO_OPEN_POINT_SUIT:
                    # Expert rule (研究 #3): don't open a suit with points
                    # still out unless we hold its boss — leave it for the
                    # opponents to break.
                    ok = [e for e in safe if not (
                        any(points(c) and o.eff_suit(c) == e[1]
                            for c in mem.unseen)
                        and not any(mem.is_boss(c) for c in by_suit[e[1]]))]
                    if ok:
                        pool_s = ok
                _, s2 = max(pool_s)
                nonpoint = [c for c in by_suit[s2] if points(c) == 0]
                if nonpoint:
                    return [max(nonpoint, key=o.level)]
            if low_pair is not None:
                return [low_pair[1], low_pair[1]]  # any pair > passive junk
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

        reserve = self._reserve(rnd, seat, mem)

        if partner_winning:
            # Feed points only when the partner's play can't be beaten by
            # anyone still to act; otherwise keep points home.
            secure = not mem.beat_risk(inc_suit, inc_top, opp_to_act)
            if self.FEED_ON_TRUMP and inc_suit == TRUMP:
                secure = True
            return self._forced_follow(hand, lead, o, prefer_points=secure,
                                       avoid=reserve)

        winning = self._cheapest_winning(hand, lead, inc_suit, inc_top, o)
        if winning is not None:
            w_suit = o.eff_suit(winning[0])
            uses_trump = w_suit == TRUMP and uniform_suit(lead, o) != TRUMP
            if not uses_trump:
                # in-suit wins are cheap tempo — contest, UNLESS the trick is
                # pointless and winning burns a premium trump (rank cards /
                # jokers): prod XCYB spent BJ on a 0-point trick this way.
                # EXCEPTION (user): a strong waiting combo justifies even a
                # premium spend — the lead it buys repays it.
                premium = (w_suit == TRUMP and
                           min(o.level(c) for c in winning) >= len(o.plain_ranks))
                if premium and self.TEMPO_GUARD and trick_pts == 0:
                    if self.TEMPO_SEEK and self._followup_size(rnd, seat, mem) >= 4:
                        return winning
                else:
                    return winning
            # Spending trump: memory decides whether it's worth it.
            w_top = decompose(winning, o).top_level()
            holds = not mem.beat_risk(w_suit, w_top, opp_to_act)
            contest_at = self.CONTEST_PTS
            if self.ENDGAME_CONTROL and len(hand) <= 6:
                contest_at = 0  # endgame: every trick controls the finish
            elif self.TEMPO_SEEK and holds:
                # winning buys the LEAD; a waiting combo justifies the spend
                # — cheap trumps for modest follow-ups, ANY trump (incl.
                # premium) when the follow-up is a big combo (user: "sometimes
                # you need to play a high trump to get tempo for the combo")
                premium = min(o.level(c) for c in winning) >= len(o.plain_ranks)
                followup = self._followup_size(rnd, seat, mem)
                if followup >= (4 if premium else 2):
                    contest_at = 0
            if trick_pts >= contest_at or (holds and trick_pts > 0):
                return winning
        return self._forced_follow(hand, lead, o, prefer_points=False,
                                   avoid=reserve)
