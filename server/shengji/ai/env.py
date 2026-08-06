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
from ..engine.round import actual_play_after
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


class FullGameCutoff(RuntimeError):
    """A full game exhausted its round budget without a rules winner.

    A level leader at an arbitrary cutoff is not a game winner.  Carry the
    partial state for diagnostics, but refuse to expose a score that a caller
    could accidentally charge to either policy.
    """

    def __init__(self, *, seed: int | None, max_rounds: int,
                 game: Game, logs: list[RoundLog]):
        self.seed = seed
        self.max_rounds = max_rounds
        self.rounds = game.round_no
        self.level_idx = tuple(game.level_idx)
        self.levels = game.levels
        self.game = game
        self.logs = tuple(logs)
        super().__init__(
            "full game reached "
            f"max_rounds={max_rounds} without a rules-complete winner "
            f"(seed={seed!r}, rounds={game.round_no}, "
            f"level_idx={self.level_idx}); refusing to score cutoff")


def play_round(game: Game, policies: list, record: bool = False) -> RoundLog:
    """Drive one round to completion with the given 4 policies."""
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):  # last chance with a lower bar, like the grace window
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(rnd, rnd.banker))
    history = []
    while rnd.phase == "play":
        seat = rnd.turn
        cards = policies[seat].decide_play(rnd, seat)
        prev_last = rnd.last_trick
        rnd.play(seat, cards)
        if record:  # engine truth, not the attempt (failed throws differ)
            history.append((seat, actual_play_after(rnd, seat, prev_last)))
    result = game.finish_round()
    return RoundLog(rnd.trump_rank, rnd.banker, result.attacker_points,
                    result.winner_team, result.level_change, history=history)


def play_game(policies: list, seed: int | None = None,
              max_rounds: int = 200) -> tuple[int, Game, list[RoundLog]]:
    """Play until the engine declares a winner; refuse an arbitrary cutoff.

    Completed games retain the historical ``(winner, game, logs)`` return.
    ``FullGameCutoff`` is raised for every unfinished game, including exact
    level ties and unequal partial levels.
    """
    if (isinstance(max_rounds, bool) or not isinstance(max_rounds, int)
            or max_rounds < 1):
        raise ValueError("max_rounds must be a positive integer")
    game = Game(random.Random(seed))
    logs = []
    while not game.game_over and game.round_no < max_rounds:
        logs.append(play_round(game, policies))
    if not game.game_over:
        raise FullGameCutoff(seed=seed, max_rounds=max_rounds,
                             game=game, logs=logs)
    if game.result is None:  # impossible under Game.finish_round(); fail closed
        raise RuntimeError("game_over is true but the engine has no result")
    return game.result.winner_team, game, logs


def evaluate(policy_a, policy_b, n_games: int = 100, seed: int = 0,
             mirrored: bool = True, max_rounds: int = 200) -> dict:
    """Head-to-head win rates. With ``mirrored`` (default), games run in
    pairs on the SAME shuffle sequence with the teams swapped, so card luck
    cancels and variance drops sharply. n_games is total games (2 per pair).

    A cutoff in either flip raises ``FullGameCutoff`` and invalidates the whole
    evaluation; no partial win count is returned.
    """
    wins = [0, 0]
    rounds = 0
    flips = (0, 1) if mirrored else (0,)
    n_seeds = n_games // len(flips)
    for g in range(n_seeds):
        for flip in flips:
            if flip == 0:
                policies = [policy_a, policy_b, policy_a, policy_b]
            else:
                policies = [policy_b, policy_a, policy_b, policy_a]
            winner, game, logs = play_game(
                policies, seed=seed + g, max_rounds=max_rounds)
            # Defense in depth: if a future play_game API represents a cutoff
            # as an explicit tie, it must not fall through `winner == flip`
            # and silently charge policy B.
            if winner is None:
                raise FullGameCutoff(seed=seed + g, max_rounds=max_rounds,
                                     game=game, logs=logs)
            if winner not in (0, 1):
                raise RuntimeError(f"invalid full-game winner {winner!r}")
            a_won = winner == flip  # a is team 0 unflipped, team 1 flipped
            wins[0 if a_won else 1] += 1
            rounds += len(logs)
            done = wins[0] + wins[1]
            if done % 20 == 0:  # status heartbeat (Jerry, 2026-08-03)
                print(f"PROGRESS {done}/{total if False else n_seeds*len(flips)}"
                      f" a={wins[0]} b={wins[1]}"
                      f" ({100*wins[0]/done:.0f}%)", flush=True)
    total = n_seeds * len(flips)
    return {"games": total, "wins_a": wins[0], "wins_b": wins[1],
            "mirrored": mirrored, "avg_rounds_per_game": rounds / total}


if __name__ == "__main__":
    from .heuristic import HeuristicBot
    from .smart import SmartBot
    print("SmartBot (a) vs HeuristicBot (b), mirrored deals:")
    print(evaluate(SmartBot(), HeuristicBot(), n_games=200))
