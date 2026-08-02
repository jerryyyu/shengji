"""Public-information memory for smarter play.

Built fresh from the round's public trick history plus the bot's own hand —
never from hidden hands — so it is exactly the information a human player
could track: which cards have been seen, who has shown void in which suit,
and whether a given card/pair is the highest still in circulation ("boss").

Note: the banker's 8 buried cards are unseen, so `unseen` slightly
overestimates what opponents can hold. That errs on the cautious side.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import TRUMP, make_deck
from ..engine.combos import pair_count
from ..engine.round import Round


class Memory:
    def __init__(self, rnd: Round, seat: int):
        assert rnd.ordering is not None
        self.o = rnd.ordering
        self.seat = seat
        self.played: Counter[str] = Counter()
        self.voids: dict[int, set[str]] = {s: set() for s in range(4)}
        # Proven "no pair left in suit": the rules FORCE a follower to match
        # pairs up to the number led, so answering a pair/tractor lead with
        # fewer in-suit pairs than led is proof their pairs there are gone.
        self.pair_void: dict[int, set[str]] = {s: set() for s in range(4)}

        tricks = list(rnd.history)
        if rnd.trick and rnd.trick.plays:
            tricks.append(rnd.trick)
        for trick in tricks:
            lead_cards = trick.plays[0].cards
            lead_suit = self.o.eff_suit(lead_cards[0])
            n_led_pairs = pair_count(lead_cards) if len(lead_cards) >= 2 else 0
            for i, tp in enumerate(trick.plays):
                self.played.update(tp.cards)
                # A follower whose play includes any off-suit card was
                # obliged to exhaust the led suit first => void now.
                if i > 0 and any(self.o.eff_suit(c) != lead_suit for c in tp.cards):
                    self.voids[tp.seat].add(lead_suit)
                if i > 0 and n_led_pairs:
                    ins = [c for c in tp.cards
                           if self.o.eff_suit(c) == lead_suit]
                    if pair_count(ins) < n_led_pairs:
                        self.pair_void[tp.seat].add(lead_suit)

        hand = Counter(rnd.hands[seat])
        self.unseen: Counter[str] = Counter()
        for code in set(make_deck()):
            n = 2 - self.played[code] - hand[code]
            if n > 0:
                self.unseen[code] = n

    # ------------------------------------------------------------------ query
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
