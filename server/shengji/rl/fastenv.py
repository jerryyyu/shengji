"""Phase 0 throughput benchmark: multiprocess self-play workers.

Usage:  uv run python -m shengji.rl.fastenv [n_workers] [rounds_per_worker]
Target (RL_PLAN.md): >2,000 rounds/s aggregate for heuristic rollouts.
"""

from __future__ import annotations

import multiprocessing as mp
import random
import sys
import time


def _worker(args) -> int:
    worker_id, n_rounds = args
    from ..ai.env import play_round
    from ..ai.heuristic import HeuristicBot
    from ..engine.game import Game
    bots = [HeuristicBot() for _ in range(4)]
    done = 0
    seed = worker_id * 1_000_000
    while done < n_rounds:
        game = Game(random.Random(seed))
        seed += 1
        while not game.game_over and done < n_rounds:
            play_round(game, bots)
            done += 1
    return done


def main() -> None:
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, mp.cpu_count() - 2)
    per_worker = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    t0 = time.time()
    with mp.Pool(n_workers) as pool:
        counts = pool.map(_worker, [(i, per_worker) for i in range(n_workers)])
    dt = time.time() - t0
    total = sum(counts)
    print(f"{total} rounds, {n_workers} workers, {dt:.1f}s "
          f"-> {total/dt:.0f} rounds/s aggregate")


if __name__ == "__main__":
    main()
