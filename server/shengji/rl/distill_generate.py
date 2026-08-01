"""Search distillation data: MCBot self-play with per-candidate MC values.

Each worker plays full MCBot-vs-MCBot rounds and records, for every
decision the search evaluated, the observation, all candidate encodings,
the search's per-candidate values (dense targets — no credit assignment),
the chosen action, and the round's terminal return.

Usage:  uv run python -m shengji.rl.distill_generate <out_dir> <n_rounds> [workers]
"""

from __future__ import annotations

import multiprocessing as mp
import random
import sys
import time

from ..ai.env import play_round
from ..ai.mcbot import MCBot
from ..engine.game import Game
from .bc_generate import round_value
from .dataset import Decision, TrajectoryWriter
from .encode import encode_action, encode_obs


class RecordingMCBot(MCBot):
    def __init__(self, seed=None):
        super().__init__(seed)
        self.decisions: list[Decision] = []

    def decide_play(self, rnd, seat):
        play = super().decide_play(rnd, seat)
        if self.last_eval is not None:
            candidates, values = self.last_eval
            key = sorted(play)
            chosen = next((i for i, a in enumerate(candidates)
                           if sorted(a) == key), 0)
            self.decisions.append(Decision(
                obs=encode_obs(rnd, seat),
                actions=[encode_action(a, rnd) for a in candidates],
                chosen=chosen, seat=seat,
                action_values=list(values)))
        return play


def worker(args):
    worker_id, n_rounds, out_dir = args
    writer = TrajectoryWriter(out_dir)
    writer._shard = worker_id * 1000  # disjoint shard numbering per worker
    bot = RecordingMCBot(seed=worker_id)
    bots = [bot] * 4
    seed = worker_id * 10_000_000
    done = 0
    t0 = time.time()
    while done < n_rounds:
        game = Game(random.Random(seed))
        seed += 1
        while not game.game_over and done < n_rounds:
            bot.decisions = []
            play_round(game, bots)
            rnd = game.round
            val = round_value(rnd.attacker_points)
            for d in bot.decisions:
                d.ret = val if rnd.is_attacker(d.seat) else -val
                writer.add(d)
            done += 1
            if worker_id == 0 and done % 50 == 0:
                rate = done / (time.time() - t0)
                print(f"worker0: {done}/{n_rounds} rounds "
                      f"({rate:.2f} r/s/worker)", flush=True)
    writer.flush()
    return done


def main() -> None:
    out_dir = sys.argv[1]
    n_rounds = int(sys.argv[2])
    n_workers = int(sys.argv[3]) if len(sys.argv) > 3 else 9
    per = n_rounds // n_workers
    t0 = time.time()
    with mp.get_context("spawn").Pool(n_workers) as pool:
        counts = pool.map(worker, [(i, per, out_dir) for i in range(n_workers)])
    dt = time.time() - t0
    print(f"done: {sum(counts)} rounds in {dt/60:.0f} min "
          f"({sum(counts)/dt:.1f} rounds/s aggregate) -> {out_dir}")


if __name__ == "__main__":
    main()
