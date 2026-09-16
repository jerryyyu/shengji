"""Synthetic, bounded joint-model consumer qualification (not a strength screen).

Single-thread BLAS and SHENGJI_FAST=1 are recommended. Each measured decision
has a 300-second process alarm. Batch-shape changes are NOT byte-exact claims.
"""
import argparse
import copy
import hashlib
import json
import random
import signal
import time

import numpy as np

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine import fast
from shengji.train.cwv_shortlist import make_shortlist_bot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    args = parser.parse_args()
    with open(args.package, "rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    for seed, plies in ((41, 4), (65, 4), (19, 5), (3, 24), (19, 48), (3, 64)):
        rnd = Game(random.Random(seed)).start_round()
        heuristic = HeuristicBot()
        while rnd.phase != "play":
            if rnd.phase == "deal": rnd.deal_next()
            elif rnd.phase == "declare": rnd.finalize_declare()
            else: rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
        for _ in range(plies):
            if rnd.phase != "play": break
            rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
        if rnd.phase != "play":
            print(json.dumps(dict(seed=seed, plies=plies, skipped="terminal")), flush=True)
            continue
        baseline = None
        for enabled in (False, True, True, False):
            bot = make_shortlist_bot(args.package, seed=13, worlds=32,
                selection_worlds=30, report_worlds=300, encoding="mlp-static",
                reuse_successors=True, reuse_values=enabled,
                prior_checkpoint=args.package, prior_sha256=sha,
                prior_threshold=1000, prior_top=256)
            state = copy.deepcopy(rnd)
            signal.alarm(300)
            try:
                start = time.perf_counter()
                action = bot.decide_play(state, state.turn)
                wall = time.perf_counter() - start
            finally:
                signal.alarm(0)
            record = bot.last_shortlist or {}
            means = np.asarray(record.get("shortlist_means", []))
            signature = (action, bot.rng.getstate())
            if baseline is None: baseline = (signature, means.copy())
            delta = float(np.max(np.abs(means - baseline[1]))) if means.size else 0.
            result = dict(seed=seed, plies=plies, reuse_values=enabled,
                model_sha256=sha, fast_available=fast.HAVE_FAST,
                action_rng_equal=signature == baseline[0], max_mean_delta=delta,
                wall_seconds=wall, legal_count=record.get("legal_count"),
                ranking_seconds=record.get("wall_seconds"), reuse=bot.last_value_reuse)
            print(json.dumps(result), flush=True)
            assert signature == baseline[0], "action/RNG changed"
            np.testing.assert_allclose(means, baseline[1], rtol=0, atol=1e-12)


if __name__ == "__main__":
    main()
