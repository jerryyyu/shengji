"""AV1 secondary estimator: population means of the seven pre-treatment deal features (AMENDMENT_AV1_1 item 4) over
N simulated deals of plan r2 (index i -> plan entry as exploit_duel_s61.round_plan, seed SEED0 + i; never a duel seed).

Usage: pop_features.py OUT.json [--n 200000] [--seed0 900000000]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SERVER = Path(os.environ.get("AV1_SERVER", HERE.parents[2]))
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402

from replay_values import deal_features  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.train.leaf_screen import RANKS, _game_factory_for  # noqa: E402

FIRST_INDICES = (0, 3, 5, 8)


def plan_entry(i):
    if i % 10 in FIRST_INDICES:
        return ("first", "2", None)
    return ("fixed_banker", tuple(RANKS)[i % 13], i % 4)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=200_000)
    ap.add_argument("--seed0", type=int, default=900_000_000)
    a = ap.parse_args(argv)
    feats = np.zeros((a.n, 7))
    for i in range(a.n):
        kind, rank, fixed = plan_entry(i)
        seed = a.seed0 + i
        game = Game(random.Random(seed)) if kind == "first" else _game_factory_for(rank, fixed)(random.Random(seed))
        rnd = game.start_round()
        while rnd.phase == "deal":
            rnd.deal_next()
        feats[i] = deal_features(rnd, kind, fixed)
    out = {"n": a.n, "seed0": a.seed0, "mean": feats.mean(0).tolist(),
           "se": (feats.std(0, ddof=1) / np.sqrt(a.n)).tolist(),
           "names": ["|dJ|", "|dR|", "|dP|", "(J+R)T0*(J+R)T1", "bankerJ+R", "kitty_pts", "first_round"]}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
