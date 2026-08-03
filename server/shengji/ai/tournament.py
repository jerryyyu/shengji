"""Round-robin tournament + Elo (Bradley-Terry) ratings over the policy pool.

Every pair of policies plays mirrored round-pairs (same shuffles, teams
swapped), so card luck cancels within each pairing. Ratings are fit with
Bradley-Terry maximum likelihood (batch, order-independent) and reported on
the Elo scale, anchored so `heuristic` = 1000.

Run:  uv run python -m shengji.ai.tournament [rounds_per_pair]
"""

from __future__ import annotations

import math
import random

from ..engine.game import Game
from .env import play_round
from .registry import REGISTRY


def play_pairing(make_a, make_b, n_seeds: int, seed0: int) -> tuple[int, int]:
    """Mirrored round-pairs; returns (wins_a, wins_b) over 2*n_seeds rounds."""
    wins = [0, 0]
    for s in range(n_seeds):
        if s and s % 15 == 0:
            print(f"PROGRESS pairing {2*s}/{2*n_seeds} rounds"
                  f" a={wins[0]} b={wins[1]}", flush=True)
        for flip in (0, 1):
            a1, a2, b1, b2 = make_a(), make_a(), make_b(), make_b()
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            game = Game(random.Random(seed0 + s))
            log = play_round(game, pol)
            a_team = 0 if flip == 0 else 1
            wins[0 if log.winner_team == a_team else 1] += 1
    return wins[0], wins[1]


def fit_elo(names: list[str], wins: dict[tuple[int, int], int],
            anchor: str = "heuristic") -> dict[str, float]:
    """Bradley-Terry MLE via minorization-maximization, mapped to Elo."""
    n = len(names)
    p = [1.0] * n
    for _ in range(2000):
        new = []
        for i in range(n):
            w_i = sum(wins.get((i, j), 0) for j in range(n) if j != i)
            den = 0.0
            for j in range(n):
                if j == i:
                    continue
                n_ij = wins.get((i, j), 0) + wins.get((j, i), 0)
                if n_ij:
                    den += n_ij / (p[i] + p[j])
            new.append(w_i / den if den else p[i])
        s = sum(new) / n
        p = [x / s for x in new]
    elo = {name: 400.0 * math.log10(p[i]) for i, name in enumerate(names)}
    shift = 1000.0 - elo.get(anchor, 0.0)
    return {k: v + shift for k, v in elo.items()}


def run_tournament(pool: list[str], n_seeds: int = 60, seed0: int = 0) -> None:
    names = list(pool)
    wins: dict[tuple[int, int], int] = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            wa, wb = play_pairing(lambda i=i: REGISTRY[names[i]](),
                                  lambda j=j: REGISTRY[names[j]](),
                                  n_seeds, seed0)
            wins[(i, j)] = wa
            wins[(j, i)] = wb
            total = wa + wb
            print(f"{names[i]:12s} vs {names[j]:12s}  {wa:3d} - {wb:3d} "
                  f"({wa/total:.0%})", flush=True)
    elo = fit_elo(names, wins)
    print("\nElo ratings (round-level, heuristic = 1000):")
    for name, r in sorted(elo.items(), key=lambda kv: -kv[1]):
        print(f"  {name:12s} {r:7.0f}")


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    run_tournament(["heuristic", "smart-v1", "smart-v2", "smart", "mc"],
                   n_seeds=n)
