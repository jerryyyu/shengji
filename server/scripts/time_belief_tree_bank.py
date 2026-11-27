"""Time the bank scorer on fixed heuristic-game leads without opening the research cohort."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
from time import perf_counter

from y_trajectory import recipe_environment


R55_RECIPE_SHA = "aa3048fba371132c02704d629f0f2dbf3590458112f89058329b51b7bf4e5f29"
PLIES = (20, 36, 52)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fly", required=True, type=Path)
    parser.add_argument("--models", required=True, type=Path)
    args = parser.parse_args(argv)
    if hashlib.sha256(args.fly.read_bytes()).hexdigest() != R55_RECIPE_SHA:
        raise ValueError("expected the frozen R55 serving recipe")
    selected = recipe_environment(args.fly, args.models)
    for key in tuple(os.environ):
        if key.startswith("SHENGJI_"):
            del os.environ[key]
    os.environ.update(selected)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"

    started = perf_counter()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shengji.engine.fast import activate
    if not activate():
        raise RuntimeError("the timing pilot requires the compiled engine")
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.refusal import RefusalLedger
    from shengji.engine.game import Game
    from shengji.train.belief_labels import deal_key
    from shengji.train.belief_tree_bank import _offline_bot
    from shengji.train.belief_tree_bank_row import checked_gains
    from shengji.train.belief_tree_bank_score import score_bank_root
    from shengji.train.belief_tree_replay import RootTarget, TrancheRoot

    from shengji.train.belief_tree_bank_settings import pilot_settings

    settings = pilot_settings()
    policy = selected["SHENGJI_BOT"]
    players = [HeuristicBot() for _ in range(4)]
    rnd = prepare_round(Game(random.Random(14)), players)
    ledger = RefusalLedger()
    key = deal_key(rnd.deck)
    timings = []
    for ply in range(PLIES[-1] + 1):
        if rnd.phase != "play":
            raise ValueError("timing fixture ended before the last target")
        if ply in PLIES:
            root = TrancheRoot(RootTarget(ply, 0, ply, rnd.turn), key, rnd, tuple(ledger.refusals))
            begin = perf_counter()
            row = score_bank_root(root, make_bot=lambda seed: _offline_bot(policy, seed),
                                  policy=policy, **settings)
            if checked_gains(row) is None:
                raise ValueError("timing fixture must exercise the eligible scoring path")
            timings.append(dict(ply=ply, candidates=len(row["ballot"]), seconds=perf_counter() - begin))
        if ply < PLIES[-1]:
            rnd.play(rnd.turn, players[rnd.turn].decide_play(rnd, rnd.turn))
            ledger.observe(rnd)
    print(json.dumps(dict(schema="belief-tree-synthetic-timing-v1", policy=policy,
                          deal_seed=14, settings=settings, roots=timings,
                          elapsed_seconds=perf_counter() - started), allow_nan=False))


if __name__ == "__main__":
    main()
