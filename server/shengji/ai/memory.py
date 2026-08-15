"""Public-information memory for smarter play.

Built fresh from the round's public trick history plus the bot's own hand —
never from hidden hands — so it is exactly the information a human player
could track: which cards have been seen, who has shown void in which suit,
and whether a given card/pair is the highest still in circulation ("boss").

Note: when this seat IS the banker its own buried cards count as known
(its own information). For every other seat the kitty is genuinely
unseen, which errs on the cautious side.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import TRUMP, make_deck
from ..engine.combos import decompose, pair_count
from ..engine.round import Round


class Memory:
    def __init__(self, rnd: Round, seat: int, own_kitty: bool = True):
        assert rnd.ordering is not None
        self.o = rnd.ordering
        self.seat = seat
        self.played: Counter[str] = Counter()
        self.played_by: dict[int, Counter[str]] = {s: Counter() for s in range(4)}
        self.voids: dict[int, set[str]] = {s: set() for s in range(4)}
        # Proven UPPER BOUND on pairs left in a suit. `validate_follow`
        # enforces `need_pairs = min(lead_pairs, pair_count(their_suit))`, so a
        # follower who shows fewer pairs than were led had no more to give and
        # played all of them. The remaining count is ZERO in every such case,
        # whether a pair or a tractor was led.
        #
        # Kept as an int rather than a set because the sampler wants a number
        # and a future inference may prove a nonzero bound; the value today is
        # always 0.
        self.pair_cap: dict[int, dict[str, int]] = {s: {} for s in range(4)}
        # Provable upper bound on the longest PAIR RUN (tractor) still held.
        # Answering a pure k-pair tractor lead with a shorter run proves no
        # k-run remains. Distinct from pair_cap: a seat can hold two pairs and
        # still have no 2-RUN if they are not consecutive.
        self.run_cap: dict[int, dict[str, int]] = {s: {} for s in range(4)}

        tricks = list(rnd.history)
        if rnd.trick and rnd.trick.plays:
            tricks.append(rnd.trick)
        for trick in tricks:
            lead_cards = trick.plays[0].cards
            lead_suit = self.o.eff_suit(lead_cards[0])
            n_led_pairs = pair_count(lead_cards) if len(lead_cards) >= 2 else 0
            _ldec = decompose(list(lead_cards), self.o)
            pure_tractor = (len(_ldec.components) == 1
                            and _ldec.components[0].pair_len >= 2)
            for i, tp in enumerate(trick.plays):
                self.played.update(tp.cards)
                self.played_by[tp.seat].update(tp.cards)
                # A follower whose play includes any off-suit card was
                # obliged to exhaust the led suit first => void now.
                if i > 0 and any(self.o.eff_suit(c) != lead_suit for c in tp.cards):
                    self.voids[tp.seat].add(lead_suit)
                if i > 0 and n_led_pairs:
                    ins = [c for c in tp.cards
                           if self.o.eff_suit(c) == lead_suit]
                    shown = pair_count(ins)
                    if shown < n_led_pairs:
                        # The engine enforces need_pairs = min(led_pairs,
                        # their_pairs), so showing FEWER pairs than led proves
                        # they played every pair they had in this suit. What
                        # remains is therefore ZERO, not `shown` — I recorded
                        # `shown` and Codex caught it: sound but strictly
                        # weaker than the boolean it replaced, which had the
                        # inference right all along.
                        self.pair_cap[tp.seat][lead_suit] = 0
                    if pure_tractor and ins:
                        k = _ldec.components[0].pair_len
                        if decompose(ins, self.o).max_pair_run() < k:
                            prev = self.run_cap[tp.seat].get(lead_suit)
                            self.run_cap[tp.seat][lead_suit] = (
                                k - 1 if prev is None else min(prev, k - 1))

        # Declarer's shown cards (RTLT 2026-08-03: a declared trump-rank
        # PAIR is provably in ONE hand — sampling it split made KK-pair
        # leads look boss in most worlds). Track declared cards still
        # unplayed and not our own: the sampler pins them to the declarer.
        self.known: dict[str, tuple[int, int]] = {}  # code -> (seat, copies)
        decl = rnd.declaration
        if decl is not None and decl.get("seat") is not None                 and decl["seat"] != seat:
            dc = Counter(decl["cards"])
            for code, n in dc.items():
                # subtract only the DECLARER's own plays: a copy played by
                # someone else is a different physical card and must not
                # unpin the declarer's shown one (Codex audit 2026-08-03)
                left = n - self.played_by[decl["seat"]][code]
                if left > 0:
                    self.known[code] = (decl["seat"], left)

        hand = Counter(rnd.hands[seat])
        # The BANKER buried 8 cards itself — its own private information,
        # exactly like its hand, and it makes those cards provably
        # unavailable to opponents. Without this a banker that buried the
        # other ace does not know its own K is boss (the pair_is_boss class
        # of bug; that fix was worth +13 points). MCBot's world sampler
        # already accounted for this; Memory did not.
        # Flag it: the world sampler must NOT subtract the burial a second
        # time from `unseen` (doing so deleted real opponent copies, left the
        # pool 8 cards short, and failed EVERY sample — the banker then took
        # candidate 0 with no search at all. Codex audit, 2026-08-03).
        self.own_kitty_known = bool(own_kitty and rnd.banker == seat
                                    and rnd.buried)
        if self.own_kitty_known:
            hand = hand + Counter(rnd.buried)
        self.unseen: Counter[str] = Counter()
        # sorted: set iteration is hash-randomized PER PROCESS — unseen's
        # insertion order fed the world sampler and made "fixed-seed" MC
        # runs differ across processes (caught by the golden parity test,
        # 2026-08-02; same bug class as the tournament-chunk incident).
        for code in sorted(set(make_deck())):
            n = 2 - self.played[code] - hand[code]
            if n > 0:
                self.unseen[code] = n

    # ------------------------------------------------------------------ query
    @property
    def pair_void(self) -> dict[int, set[str]]:
        """Suits where a seat provably holds NO pair — cap of exactly zero.

        Derived so existing readers keep the SOUND half of the old meaning. A
        tractor lead only bounds a seat below two pairs, and treating that as
        "no pairs" was the unsound part.
        """
        return {s: {suit for suit, cap in caps.items() if cap == 0}
                for s, caps in self.pair_cap.items()}

    def max_pairs(self, seat: int, eff_suit: str) -> int | None:
        """Provable upper bound on pairs, or None if nothing is known."""
        return self.pair_cap[seat].get(eff_suit)

    def max_run(self, seat: int, eff_suit: str) -> int | None:
        """Provable upper bound on the longest pair RUN, or None."""
        return self.run_cap[seat].get(eff_suit)

    def higher_unseen(self, eff_suit: str, level: int) -> int:
        """How many unseen cards of ``eff_suit`` beat ``level``."""
        return sum(n for c, n in self.unseen.items()
                   if self.o.eff_suit(c) == eff_suit and self.o.level(c) > level)

    def is_boss(self, code: str) -> bool:
        """No unseen card outranks this one (ties lose to the earlier play)."""
        return self.higher_unseen(self.o.eff_suit(code), self.o.level(code)) == 0

    def pair_is_boss(self, code: str) -> bool:
        """A pair is beaten only by a higher PAIR: boss iff no higher rank
        in the suit has TWO+ copies unseen. (Holding A+KK, one ace is in
        hand → AA impossible → KK is boss, even though an ace is unseen.
        The old any-higher-card check wrongly vetoed exactly this, which is
        why bots led AA+K but never A+KK — user-spotted from prod logs.)"""
        lvl = self.o.level(code)
        eff = self.o.eff_suit(code)
        return not any(self.o.eff_suit(c) == eff and self.o.level(c) > lvl
                       and n >= 2 for c, n in self.unseen.items())

    def points_left(self, eff_suit: str | None = None) -> int:
        """Point cards (5/10/K) still in circulation — unseen pool, which
        includes the kitty (conservative: kitty points can't be captured
        in tricks, so this over-estimates what's winnable). 0 means every
        remaining trick is worthless except the last (kitty multiplier).
        Exact from public info (user idea, 2026-08-03)."""
        from ..engine.cards import points
        return sum(points(c) * n for c, n in self.unseen.items()
                   if eff_suit is None or self.o.eff_suit(c) == eff_suit)

    def unseen_trumps(self) -> int:
        return sum(n for c, n in self.unseen.items()
                   if self.o.eff_suit(c) == TRUMP)

    def ruff_risk(self, lead_suit: str, seats: list[int]) -> bool:
        """Could any of ``seats`` trump a lead of ``lead_suit``?"""
        if lead_suit == TRUMP or self.unseen_trumps() == 0:
            return False
        return any(lead_suit in self.voids[s] or self._maybe_void(s, lead_suit)
                   for s in seats)

    def _maybe_void(self, seat: int, eff_suit: str) -> bool:
        """Void by exhaustion: fewer unseen cards of the suit exist than the
        number of opponents who could hold them makes meaningful. Cheap
        version: the suit is nearly exhausted publicly."""
        remaining = sum(n for c, n in self.unseen.items()
                        if self.o.eff_suit(c) == eff_suit)
        return remaining <= 2

    def beat_risk(self, eff_suit: str, level: int, seats: list[int]) -> bool:
        """Could any of ``seats`` beat a card of (eff_suit, level) — either
        in suit or by ruffing?"""
        in_suit = self.higher_unseen(eff_suit, level) > 0 and any(
            eff_suit not in self.voids[s] for s in seats)
        return in_suit or self.ruff_risk(eff_suit, seats)
