"""One round (hand) of Sheng Ji: deal, declare, bury, 25 tricks, scoring."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .cards import BJ, LJ, Ordering, card_rank, card_suit, is_joker, make_deck, total_points
from .combos import decompose
from .legal import IllegalPlay, beats, check_in_hand, uniform_suit, validate_follow, validate_lead

KITTY_SIZE = 8
HAND_SIZE = 25
KITTY_MULTIPLIER = 2  # kitty points x2 if attackers take the last trick


@dataclass
class TrickPlay:
    seat: int
    cards: list[str]


@dataclass
class Trick:
    leader: int
    plays: list[TrickPlay] = field(default_factory=list)
    winner: int | None = None
    points: int = 0


class Round:
    """State machine: declare -> bury -> play -> round_end.

    ``banker`` is None only on the very first round of a game, where the
    first declarer takes it (seat 0 if nobody declares).
    """

    def __init__(self, trump_rank: str, banker: int | None, rng: random.Random | None = None):
        rng = rng or random.Random()
        self.deck = make_deck()
        rng.shuffle(self.deck)
        self.hands: list[list[str]] = [
            self.deck[i * HAND_SIZE:(i + 1) * HAND_SIZE] for i in range(4)
        ]
        self.kitty: list[str] = self.deck[4 * HAND_SIZE:]
        self.trump_rank = trump_rank
        self.banker = banker
        self.first_round = banker is None
        self.phase = "declare"
        self.turn: int | None = banker if banker is not None else 0
        self.declaration: dict | None = None  # {seat, cards, strength}
        self._passes = 0
        self.ordering: Ordering | None = None
        self.trump_suit: str | None | str = None  # set at finalize; "NT" handled as None
        self.trump_is_nt = False
        self.buried: list[str] = []
        self.trick: Trick | None = None
        self.last_trick: Trick | None = None
        self.attacker_points = 0
        self.kitty_bonus = 0
        self.last_trick_winner: int | None = None
        self.message: str | None = None

    # ------------------------------------------------------------------ teams
    def is_attacker(self, seat: int) -> bool:
        assert self.banker is not None
        return seat % 2 != self.banker % 2

    # ---------------------------------------------------------------- declare
    def _declaration_strength(self, cards: list[str]) -> int | None:
        c = Counter(cards)
        if len(cards) == 1 and card_rank(cards[0]) == self.trump_rank:
            return 1
        if len(cards) == 2 and len(c) == 1:
            code = cards[0]
            if card_rank(code) == self.trump_rank:
                return 2
            if code == LJ:
                return 3
            if code == BJ:
                return 4
        return None

    def declare_options(self, seat: int) -> list[list[str]]:
        if self.phase != "declare" or self.turn != seat:
            return []
        current = self.declaration["strength"] if self.declaration else 0
        hand = Counter(self.hands[seat])
        options: list[list[str]] = []
        for code, n in sorted(hand.items()):
            if card_rank(code) == self.trump_rank:
                if current < 1:
                    options.append([code])
                if n >= 2 and current < 2:
                    options.append([code, code])
            if code == LJ and n >= 2 and current < 3:
                options.append([code, code])
            if code == BJ and n >= 2 and current < 4:
                options.append([code, code])
        return options

    def declare(self, seat: int, cards: list[str]) -> None:
        self._require(seat, "declare")
        check_in_hand(self.hands[seat], cards)
        strength = self._declaration_strength(cards)
        current = self.declaration["strength"] if self.declaration else 0
        if strength is None or strength <= current:
            raise IllegalPlay("Not a valid (stronger) declaration.")
        self.declaration = {"seat": seat, "cards": list(cards), "strength": strength}
        self._passes = 0
        self._advance_declare_turn()

    def pass_declare(self, seat: int) -> None:
        self._require(seat, "declare")
        self._passes += 1
        needed = 3 if self.declaration else 4
        if self._passes >= needed:
            self._finalize_declare()
        else:
            self._advance_declare_turn()

    def _advance_declare_turn(self) -> None:
        assert self.turn is not None
        self.turn = (self.turn + 1) % 4
        if self.declaration and self.turn == self.declaration["seat"]:
            # declarer needn't outbid themselves
            self._passes += 1
            if self._passes >= 3:
                self._finalize_declare()
            else:
                self.turn = (self.turn + 1) % 4

    def _finalize_declare(self) -> None:
        if self.declaration:
            code = self.declaration["cards"][0]
            self.trump_is_nt = is_joker(code)
            self.trump_suit = None if self.trump_is_nt else card_suit(code)
            if self.banker is None:
                self.banker = self.declaration["seat"]
            who = self.declaration["seat"]
            label = "NT" if self.trump_is_nt else self.trump_suit
            self.message = f"Seat {who} declared {label}{'' if self.trump_is_nt else self.trump_rank}"
        else:
            flipped = next((c for c in self.kitty if not is_joker(c)), None)
            self.trump_suit = card_suit(flipped) if flipped else None
            self.trump_is_nt = flipped is None
            if self.banker is None:
                self.banker = 0
            self.message = "No declaration — trump flipped from the kitty: " + (
                self.trump_suit or "NT")
        self.ordering = Ordering(self.trump_suit, self.trump_rank)
        self.hands[self.banker].extend(self.kitty)
        self.phase = "bury"
        self.turn = self.banker

    # ------------------------------------------------------------------- bury
    def bury(self, seat: int, cards: list[str]) -> None:
        self._require(seat, "bury")
        if len(cards) != KITTY_SIZE:
            raise IllegalPlay(f"Bury exactly {KITTY_SIZE} cards.")
        check_in_hand(self.hands[seat], cards)
        self._remove(seat, cards)
        self.buried = list(cards)
        self.phase = "play"
        self.trick = Trick(leader=seat)
        self.turn = seat

    # ------------------------------------------------------------------- play
    def play(self, seat: int, cards: list[str]) -> None:
        self._require(seat, "play")
        assert self.trick is not None and self.ordering is not None
        self.message = None
        if not self.trick.plays:
            others = [self.hands[s] for s in range(4) if s != seat]
            cards, msg = validate_lead(cards, self.hands[seat], others, self.ordering)
            self.message = msg
        else:
            lead = self.trick.plays[0].cards
            validate_follow(cards, self.hands[seat], lead, self.ordering)
        self._remove(seat, cards)
        self.trick.plays.append(TrickPlay(seat, list(cards)))
        if len(self.trick.plays) == 4:
            self._resolve_trick()
        else:
            self.turn = (seat + 1) % 4

    def _resolve_trick(self) -> None:
        assert self.trick and self.ordering
        lead = self.trick.plays[0].cards
        inc_suit = uniform_suit(lead, self.ordering)
        assert inc_suit is not None
        inc_top = decompose(lead, self.ordering).top_level()
        winner = self.trick.plays[0].seat
        for tp in self.trick.plays[1:]:
            won, top = beats(tp.cards, lead, inc_suit, inc_top, self.ordering)
            if won:
                winner, inc_top = tp.seat, top
                inc_suit = self.ordering.eff_suit(tp.cards[0])
        pts = total_points(c for tp in self.trick.plays for c in tp.cards)
        self.trick.winner, self.trick.points = winner, pts
        if self.is_attacker(winner):
            self.attacker_points += pts
        self.last_trick = self.trick
        if not any(self.hands):
            self.last_trick_winner = winner
            if self.is_attacker(winner):
                self.kitty_bonus = total_points(self.buried) * KITTY_MULTIPLIER
                self.attacker_points += self.kitty_bonus
            self.phase = "round_end"
            self.turn = None
            self.trick = None
        else:
            self.trick = Trick(leader=winner)
            self.turn = winner

    # ------------------------------------------------------------------ utils
    def _require(self, seat: int, phase: str) -> None:
        if self.phase != phase:
            raise IllegalPlay(f"Not in {phase} phase.")
        if self.turn != seat:
            raise IllegalPlay("Not your turn.")

    def _remove(self, seat: int, cards: list[str]) -> None:
        hand = self.hands[seat]
        for c in cards:
            hand.remove(c)

    def sorted_hand(self, seat: int) -> list[str]:
        if self.ordering:
            return sorted(self.hands[seat], key=self.ordering.sort_key)
        from .cards import natural_sort_key
        return sorted(self.hands[seat], key=natural_sort_key)
