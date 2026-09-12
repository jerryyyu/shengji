"""Small completed-work bury timing probe; run unchanged in both source trees.

Compare semantic_sha256 across runs, not timing or source identity fields.
No serving deadline: this qualifies completed decisions, not fallback rates.
"""
import argparse
import copy
import hashlib
import json
import platform
import random
import resource
import subprocess
import time
from pathlib import Path

from shengji.ai.cwv_policy import shared_evaluator
from shengji.ai.smart import SmartBot
from shengji.engine import fast
from shengji.engine.game import Game
from shengji.train.cwv_bury_policy import make_cwv_bury_bot


def root(seed):
    rnd = Game(random.Random(seed)).start_round()
    bots = [SmartBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    return rnd


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seeds", type=int, nargs="+", default=[7, 13, 31])
    p.add_argument("--repeats", type=int, default=3)
    a = p.parse_args()
    if a.repeats < 1 or a.out.exists():
        p.error("positive repeats and fresh output required")
    if not fast.activate():
        raise RuntimeError("native engine required for serving-path probe")
    evaluator = shared_evaluator(a.checkpoint, threads=1, max_batch=128,
                                 encoding="mlp-static")
    states = {seed: root(seed) for seed in a.seeds}
    keys = ("candidates", "shortlist", "picked_index", "model_means",
            "mc_evidence", "world_counts", "counters")
    rows, hashes = [], {}
    # Warm model/runtime once; exclude that call from reported measurements.
    warm = copy.deepcopy(states[a.seeds[0]])
    make_cwv_bury_bot(evaluator, seed=123, arm="hybrid").decide_bury(warm, warm.banker)
    for rep in range(a.repeats):
        for seed, state in states.items():
            rnd = copy.deepcopy(state)
            bot = make_cwv_bury_bot(evaluator, seed=123, arm="hybrid")
            w, c = time.perf_counter(), time.process_time()
            choice = bot.decide_bury(rnd, rnd.banker)
            wall, cpu = time.perf_counter() - w, time.process_time() - c
            rec = bot.last_bury_record
            evidence = {"choice": choice, "rng": bot.rng.getstate(),
                        **{k: rec[k] for k in keys}}
            digest = hashlib.sha256(json.dumps(evidence, sort_keys=True,
                                               allow_nan=False).encode()).hexdigest()
            if hashes.setdefault(seed, digest) != digest:
                raise RuntimeError("repeated bury evidence changed")
            rows.append(dict(seed=seed, repeat=rep, semantic_sha256=digest,
                             wall=wall, cpu=cpu, model=rec["model_seconds"],
                             rollout=rec["rollout_seconds"]))
    with a.checkpoint.open("rb") as f:
        checkpoint_sha = hashlib.file_digest(f, "sha256").hexdigest()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    server = Path(__file__).resolve().parents[1]
    source_files = ("shengji/ai/mcbot.py", "shengji/train/cwv_bury.py",
                    "shengji/train/cwv_bury_policy.py", "shengji/ai/cwv_policy.py",
                    "shengji/ai/cwv_static_encoding.py", "shengji/ai/cwv_numpy.py",
                    "shengji/engine/_fast.pyx", "scripts/cwv_bury_cost.py")
    source_hashes = {name: hashlib.sha256((server / name).read_bytes()).hexdigest()
                     for name in source_files}
    result = dict(schema="cwv-bury-cost-v1", checkpoint_sha256=checkpoint_sha,
                  source_files_sha256=source_hashes,
                  native=True, serving_deadline=False, platform=platform.platform(),
                  peak_rss_bytes=rss if platform.system() == "Darwin" else rss * 1024,
                  rows=rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(json.dumps({"out": str(a.out), "rows": len(rows), "hashes": hashes}), flush=True)


if __name__ == "__main__":
    main()
