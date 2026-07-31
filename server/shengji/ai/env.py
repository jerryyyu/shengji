"""Self-play harness + future RL environment.

Today this runs policy-vs-policy games headlessly (evaluation / data
collection). A policy is any object with the HeuristicBot interface:

    decide_declare(round, seat) -> cards | None
    decide_bury(round, seat)    -> 8 cards
    decide_play(round, seat)    -> cards

RL roadmap (see README):
 1. Wrap this loop in a PettingZoo AEC env: observation = encoded hand +
    trick + trump + point/level context (a few hundred binary features),
    action space = discrete over generated legal plays with action masking.
 2. Train with self-play PPO (e.g. CleanRL/RLlib), opponent pool of past
    checkpoints; reward = round score delta (level change) at round end.
 3. Swap the trained policy into the server by implementing the same
    three-method interface (see api/server.py BOT construction).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..engine.game import Game
from ..engine.round import Round


@dataclass
class RoundLog:
    trump_rank: str
    banker: int
    attacker_points: int
    winner_team: int
    level_change: int
    tricks: int = 25
    history: list = field(default_factory=list)  # (seat, cards) in play order


def play_round(game: Game, policies: list, record: bool = False) -> RoundLog:
    """Drive one round to completion with the given 4 policies."""
    rnd = game.start_round()
    while rnd.phase == "declare":
        seat = rnd.turn
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
        else:
            rnd.pass_declare(seat)
    assert rnd.banker is not None
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(rnd, rnd.banker))
    history = []
    while rnd.phase == "play":
        seat = rnd.turn
        cards = policies[seat].decide_play(rnd, seat)
        rnd.play(seat, cards)
        if record:
            history.append((seat, list(cards)))
    result = game.finish_round()
    return RoundLog(rnd.trump_rank, rnd.banker, result.attacker_points,
                    result.winner_team, result.level_change, history=history)


def play_game(policies: list, seed: int | None = None, max_rounds: int = 200):
    game = Game(random.Random(seed))
    logs = []
    while not game.game_over and game.round_no < max_rounds:
        logs.append(play_round(game, policies))
    winner = 0 if game.level_idx[0] >= game.level_idx[1] else 1
    return winner, game, logs


def evaluate(policy_a, policy_b, n_games: int = 100, seed: int = 0) -> dict:
    """Team 0 = policy_a (seats 0,2), team 1 = policy_b (seats 1,3)."""
    wins = [0, 0]
    rounds = 0
    for g in range(n_games):
        policies = [policy_a, policy_b, policy_a, policy_b]
        winner, game, logs = play_game(policies, seed=seed + g)
        wins[winner] += 1
        rounds += len(logs)
    return {"games": n_games, "wins_a": wins[0], "wins_b": wins[1],
            "avg_rounds_per_game": rounds / n_games}


if __name__ == "__main__":
    from .heuristic import HeuristicBot
    print(evaluate(HeuristicBot(), HeuristicBot(), n_games=20))
