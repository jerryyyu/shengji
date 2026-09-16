"""Bounded ABBA consumer comparison; local timing, not a strength screen.

Run with PYTHONPATH=server and single-threaded BLAS. Uses a synthetic heuristic
deal, never a holdout. Each pass has the same seed and a 300s process alarm.
"""
import argparse
import copy
import hashlib
import json
import random
import signal
import time

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import policy_prior as pp
from shengji.train.cwv_shortlist import make_shortlist_bot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--plies", type=int, default=4)
    parser.add_argument("--full-play", action="store_true")
    args = parser.parse_args()
    rnd = Game(random.Random(args.seed)).start_round()
    heuristic = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal": rnd.deal_next()
        elif rnd.phase == "declare": rnd.finalize_declare()
        else: rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    for _ in range(args.plies):
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    with open(args.package, "rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    static = pp.root_flat_input
    baseline = None
    try:
        for mode in ("reference", "static", "static", "reference"):
            pp.root_flat_input = static if mode == "static" else (
                lambda r, s: pp.flat_input(pp.root_tensors(r, s)))
            bot = make_shortlist_bot(
                args.package, seed=13, worlds=32, selection_worlds=30,
                report_worlds=300, encoding="mlp-static", reuse_successors=True,
                prior_checkpoint=args.package, prior_sha256=sha,
                prior_threshold=1000, prior_top=256)
            state = copy.deepcopy(rnd)
            signal.alarm(300)
            start = time.perf_counter()
            result = (bot.decide_play(state, state.turn) if args.full_play else
                      bot._candidates(state, state.turn))
            wall = time.perf_counter() - start
            signal.alarm(0)
            record = copy.deepcopy(bot.last_shortlist)
            ranking = record.pop("wall_seconds")
            prior = record["prior_admission"].pop("prior_seconds")
            assert record["prior_admission"]["triggered"]
            signature = (result, record, bot.rng.getstate())
            if baseline is None: baseline = signature
            assert signature == baseline, "decision/score/RNG mismatch"
            print(json.dumps(dict(mode=mode, full_play=args.full_play,
                seed=args.seed, plies=args.plies, model_sha256=sha,
                legal_count=record["legal_count"], wall_seconds=wall,
                ranking_seconds=ranking, prior_seconds=prior, exact=True)), flush=True)
    finally:
        signal.alarm(0)
        pp.root_flat_input = static


if __name__ == "__main__":
    main()
