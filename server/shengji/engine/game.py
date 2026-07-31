"""Multi-round game state: team levels, banker rotation, victory."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import RANKS
from .round import Round

A_INDEX = len(RANKS) - 1


@dataclass
class RoundResult:
    attacker_points: int
    kitty_points: int
    kitty_cards: list[str]
    winner_team: int
    level_change: int
    next_banker: int
    new_levels: tuple[str, str]
    game_over: bool


class Game:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.level_idx = [0, 0]  # per team (seats 0+2 = team 0, 1+3 = team 1)
        self.banker: int | None = None
        self.round: Round | None = None
        self.round_no = 0
        self.game_over = False
        self.result: RoundResult | None = None

    @property
    def levels(self) -> tuple[str, str]:
        return (RANKS[self.level_idx[0]], RANKS[self.level_idx[1]])

    def start_round(self) -> Round:
        assert not self.game_over
        trump_rank = RANKS[self.level_idx[self.banker % 2]] if self.banker is not None else RANKS[0]
        self.round = Round(trump_rank, self.banker, self.rng)
        self.round_no += 1
        self.result = None
        return self.round

    def finish_round(self) -> RoundResult:
        """Call when the round reaches phase 'round_end'."""
        rnd = self.round
        assert rnd is not None and rnd.phase == "round_end" and rnd.banker is not None
        banker_team = rnd.banker % 2
        attacker_team = 1 - banker_team
        p = rnd.attacker_points
        if p >= 80:
            winner = attacker_team
            gain = (p - 80) // 40
            next_banker = (rnd.banker + 1) % 4
        else:
            winner = banker_team
            gain = 3 if p == 0 else (2 if p < 40 else 1)
            next_banker = (rnd.banker + 2) % 4
        # The game is won only by successfully DEFENDING at rank A: attackers
        # winning at A merely take over the deal and must then hold their A.
        over = winner == banker_team and self.level_idx[banker_team] == A_INDEX
        if not over:
            self.level_idx[winner] = min(A_INDEX, self.level_idx[winner] + gain)
        self.banker = next_banker
        self.game_over = over
        self.result = RoundResult(
            attacker_points=p,
            kitty_points=rnd.kitty_bonus,
            kitty_cards=list(rnd.buried),
            winner_team=winner,
            level_change=gain,
            next_banker=next_banker,
            new_levels=self.levels,
            game_over=over,
        )
        return self.result
