"""Phase 2 data generation: record SmartBot self-play as BC training shards.

Usage:  uv run python -m shengji.rl.bc_generate <out_dir> [n_rounds] [seed]
Requires the `rl` dependency group (numpy):  uv sync --group rl
"""

from __future__ import annotations

import random
import sys

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from .actions import enumerate_actions
from .dataset import Decision, TrajectoryWriter
from .encode import encode_action, encode_obs


def round_value(attacker_pts: int) -> float:
    """Terminal reward: level brackets ± deal, in level units."""
    p = attacker_pts
    if p >= 80:
        return min(3, (p - 80) // 40) + 0.5
    if p == 0:
        return -3.5
    return -(1 + (79 - p) // 40) - 0.5


class RecordingBot(SmartBot):
    def __init__(self):
        self.decisions: list[Decision] = []

    def decide_play(self, rnd, seat):
        play = super().decide_play(rnd, seat)
        actions = enumerate_actions(rnd, seat)
        key = sorted(play)
        chosen = next((i for i, a in enumerate(actions) if sorted(a) == key), None)
        if chosen is None:
            actions.append(play)
            chosen = len(actions) - 1
        self.decisions.append(Decision(
            obs=encode_obs(rnd, seat),
            actions=[encode_action(a, rnd) for a in actions],
            chosen=chosen, seat=seat))
        return play


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "rl_data/bc"
    n_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    writer = TrajectoryWriter(out_dir)
    bot = RecordingBot()
    bots = [bot] * 4
    done = 0
    rng_seed = seed
    while done < n_rounds:
        game = Game(random.Random(rng_seed))
        rng_seed += 1
        while not game.game_over and game.round_no < 200 and done < n_rounds:
            bot.decisions = []
            play_round(game, bots)
            rnd = game.round
            writer.stamp_returns(bot.decisions, round_value(
                rnd.attacker_points), rnd.is_attacker)
            for d in bot.decisions:
                writer.add(d)
            done += 1
            if done % 100 == 0:
                print(f"{done}/{n_rounds} rounds", flush=True)
    writer.flush()
    print(f"done: {done} rounds -> {out_dir}")


if __name__ == "__main__":
    main()
