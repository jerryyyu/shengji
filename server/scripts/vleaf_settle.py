"""PREREGISTERED settling experiment: is mc-vleaf(v7w-ep02) better than mc?

Everything about this run is declared before it starts, because the previous
vleaf headline (60.3%, n=360, "Elo 1163") was invalid pooling of heterogeneous
blocks with reused seeds, and the honest direct evidence was 64-56 = 53.3%,
Wilson [44.4%, 62.0%] — an interval that includes 50%.

Design, fixed in advance:
  * 300 INDEPENDENT mirrored seed clusters, no seed reused from any earlier
    vleaf block (seed0 is far from the 0 / 500k / 900k ranges used before).
  * Both sides seeded deterministically per pairing, so this reproduces.
  * Per-seed records written to a JSONL so a later analysis cannot silently
    pool this with anything else.
  * Paired LEVEL UTILITY reported alongside round win-rate: winning a round
    by three levels is not the same as scraping one, and round win-rate hides
    that entirely.
  * Equal-wall-time note: vleaf truncates rollouts at 4 tricks and is the
    CHEAPER bot per decision, so a win here is not bought with extra compute.

Bar, declared now:
  * Wilson 95% lower bound > 50%  => vleaf is genuinely ahead; ledger it.
  * Point estimate >= 55%         => adoption candidate (still needs Jerry).
  * Interval spanning 50%         => NOT better; stop calling it the leader.

    uv run python scripts/vleaf_settle.py [n_seeds] [seed0]
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

os.environ.setdefault("SHENGJI_STRICT_SAMPLING", "1")

sys.path.insert(0, ".")
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.tournament import _seeded  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

OUT = "runs/logs/vleaf_settle_seeds.jsonl"


def wilson(wins: int, n: int) -> tuple[float, float, float]:
    if not n:
        return 0.0, 0.0, 0.0
    z, p = 1.96, wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return p, centre - half, centre + half


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 7_100_000

    make_a = lambda **kw: make_bot("mc-vleaf-v7w-ep02")  # noqa: E731
    make_b = lambda **kw: MCBot(**kw)                     # noqa: E731

    print(f"PREREGISTERED vleaf settling duel: mc-vleaf-v7w-ep02 vs mc, "
          f"{2 * n_seeds} rounds over {n_seeds} independent clusters, "
          f"seed0={seed0}", flush=True)
    wins = [0, 0]
    levels = [0, 0]
    t0 = time.time()
    with open(OUT, "a") as fh:
        for s_i in range(n_seeds):
            seed = seed0 + s_i
            for flip in (0, 1):
                a1 = _seeded(make_a, seed)
                a2 = _seeded(make_a, seed + 500_000)
                b1 = _seeded(make_b, seed + 1_000_000)
                b2 = _seeded(make_b, seed + 1_500_000)
                pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
                game = Game(random.Random(seed))
                log = play_round(game, pol)
                a_team = 0 if flip == 0 else 1
                won = int(log.winner_team == a_team)
                wins[0 if won else 1] += 1
                levels[0 if won else 1] += max(1, int(log.level_change))
                fh.write(json.dumps({
                    "seed": seed, "flip": flip, "vleaf_won": won,
                    "level_change": log.level_change,
                    "winner_team": log.winner_team}) + "\n")
            if s_i and s_i % 15 == 0:
                p, lo, hi = wilson(wins[0], sum(wins))
                print(f"PROGRESS {2 * s_i}/{2 * n_seeds} rounds  "
                      f"vleaf {wins[0]}-{wins[1]} ({100 * p:.1f}%) "
                      f"Wilson[{100 * lo:.1f},{100 * hi:.1f}]  "
                      f"{(time.time() - t0) / 60:.0f}m", flush=True)

    n = sum(wins)
    p, lo, hi = wilson(wins[0], n)
    print(f"RESULT vleaf(v7w-ep02) vs mc: {wins[0]}-{wins[1]} ({100 * p:.1f}%) "
          f"n={n} Wilson95=[{100 * lo:.1f}%, {100 * hi:.1f}%]", flush=True)
    print(f"LEVEL UTILITY vleaf={levels[0]} mc={levels[1]} "
          f"(paired, levels gained by the winning side)", flush=True)
    if lo > 0.5 and p >= 0.55:
        print("VERDICT: ADOPTION CANDIDATE — beats mc, point estimate >= 55%")
    elif lo > 0.5:
        print("VERDICT: genuinely ahead of mc, below the 55% adoption bar")
    else:
        print("VERDICT: NOT distinguishable from mc — retire the "
              "'seeded-pool leader' framing")


if __name__ == "__main__":
    main()
