"""Single-method A/B: both arms use the same compiled production MC.

Run only on an idle host. The first two batches trace sampled worlds and
decisions; timed batches have no tracing. A/B order alternates. The reference
is the named Git method, not the whole pure-Python engine. JSON retains every
timing and equality check; it is a DEV benchmark, not a strength experiment.

Example, from server/ with the native extension built:
  SHENGJI_FAST=1 python scripts/bench_mc_hotpath.py --reference-ref HEAD^ \
    --method _report_fold_gap --workers 16 --seeds 7 19 31 43 --repeats 3 \
    --out /path/to/fresh-report.json

Only the named method is replaced; other candidate methods remain installed
in both arms. Use bench_mc_builds for an identical-source native compiler A/B.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import dataclasses
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import types

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

COUNTERS = ("search_calls", "rollouts", "sample_attempts", "accepted_worlds",
            "failed_worlds", "rejected_worlds", "impossible_worlds",
            "short_search_decisions")


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def normalized(value, *, ignore_ballot_build_identity=False):
    if isinstance(value, dict):
        result = {k: normalized(v, ignore_ballot_build_identity=ignore_ballot_build_identity)
                  for k, v in value.items() if k != "search_secs"}
        if ignore_ballot_build_identity and value.get("schema") == "mc-decision-v2":
            # Different compiled binaries intentionally have different ballot
            # fingerprints. Preserve configs and compare the actual candidate
            # lists/scores; retain the original provenance separately below.
            result["ballot"] = {k: v for k, v in result["ballot"].items()
                                if k not in {"source_digest", "digest", "display"}}
        return result
    if isinstance(value, (list, tuple)):
        return [normalized(v, ignore_ballot_build_identity=ignore_ballot_build_identity)
                for v in value]
    return value


def initialize(reference_source, method_name, ignore_ballot_build_identity=False):
    from shengji.engine import fast
    import shengji.ai.mcbot as mc
    assert fast.activate(), "build the native extension before benchmarking"
    tree = ast.parse(reference_source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MCBot")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == method_name)
    namespace = dict(vars(mc))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "reference-deal", "exec"), namespace)
    global REFERENCE, CANDIDATE, METHOD, IGNORE_BALLOT_BUILD_IDENTITY
    METHOD = method_name
    IGNORE_BALLOT_BUILD_IDENTITY = ignore_ballot_build_identity
    REFERENCE, CANDIDATE = namespace[method_name], getattr(mc.MCBot, method_name)


def one_round(task):
    seed, rank_index, mode, trace = task
    from shengji.ai.env import play_round
    from shengji.ai.mcbot import MCBot
    from shengji.ai.registry import make_bot
    from shengji.engine.game import Game
    setattr(MCBot, METHOD, REFERENCE if mode == "reference" else CANDIDATE)
    bots = [make_bot("mc-s0-report-lcb", seed=seed * 4 + seat) for seat in range(4)]
    samples, decisions = hashlib.sha256(), hashlib.sha256()
    raw_decisions = hashlib.sha256()
    decision_provenance = None
    sample_count = 0
    if trace:
        def wrap(bot):
            sample, decide = bot._sample_hands, bot.decide_play
            def sample_trace(self, *args, **kwargs):
                nonlocal sample_count
                result = sample(*args, **kwargs)
                samples.update(packed(result) + b"\n")
                sample_count += 1
                return result
            def decision_trace(self, *args, **kwargs):
                nonlocal decision_provenance
                result = decide(*args, **kwargs)
                raw = normalized([result, self.last_decision_record])
                raw_decisions.update(packed(raw) + b"\n")
                semantic = normalized(raw,
                    ignore_ballot_build_identity=IGNORE_BALLOT_BUILD_IDENTITY)
                decisions.update(packed(semantic) + b"\n")
                if self.last_decision_record is not None and decision_provenance is None:
                    decision_provenance = {key: self.last_decision_record[key]
                                           for key in ("code", "ballot")}
                return result
            bot._sample_hands = types.MethodType(sample_trace, bot)
            bot.decide_play = types.MethodType(decision_trace, bot)
        for bot in bots:
            wrap(bot)
    game = Game(random.Random(seed))
    game.level_idx = [rank_index, rank_index]
    game.banker = seed % 4
    started = time.perf_counter()
    try:
        log = play_round(game, bots, record=True)
    finally:
        setattr(MCBot, METHOD, CANDIDATE)
    elapsed = time.perf_counter() - started
    evidence = {
        "history_and_result": [dataclasses.asdict(log), dataclasses.asdict(game.result)],
        "rng_states": [bot.rng.getstate() for bot in bots],
        "counters": [{key: getattr(bot, key) for key in COUNTERS} for bot in bots],
        "sample_sha256": samples.hexdigest() if trace else None,
        "decision_sha256": decisions.hexdigest() if trace else None,
        "sample_count": sample_count,
    }
    return {"seed": seed, "rank_index": rank_index, "mode": mode,
            "seconds": elapsed, "pid": os.getpid(),
            "evidence_sha256": hashlib.sha256(packed(evidence)).hexdigest(),
            "raw_decision_sha256": raw_decisions.hexdigest() if trace else None,
            "decision_provenance": decision_provenance,
            "sample_count": sample_count,
            "rollouts": sum(bot.rollouts for bot in bots)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="HEAD")
    parser.add_argument("--method", choices=("_deal_suit", "_report_fold_gap"),
                        default="_report_fold_gap")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19, 31, 43])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    journal = args.out.with_suffix(".jsonl")
    if args.out.exists() or journal.exists() or args.workers < 1 or args.repeats < 1:
        parser.error("fresh output, positive workers and repeats required")
    reference_sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", args.reference_ref + "^{commit}"], cwd=SERVER, text=True).strip()
    source = subprocess.check_output(
        ["git", "show", reference_sha + ":server/shengji/ai/mcbot.py"], cwd=SERVER, text=True)
    batches = []
    with journal.open("x") as progress, concurrent.futures.ProcessPoolExecutor(
            max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize, initargs=(source, args.method)) as pool:
        for repeat in range(-1, args.repeats):
            trace = repeat == -1
            order = ("reference", "candidate") if repeat % 2 else ("candidate", "reference")
            paired = {}
            for mode in order:
                started = time.perf_counter()
                rows = list(pool.map(one_round, [(s, i % 13, mode, trace)
                                                for i, s in enumerate(args.seeds)]))
                batch = {"repeat": repeat, "trace": trace, "mode": mode,
                         "wall_seconds": time.perf_counter() - started, "rows": rows}
                batches.append(batch)
                paired[mode] = rows
                progress.write(json.dumps(batch, allow_nan=False) + "\n")
                progress.flush()
                print(json.dumps({k: v for k, v in batch.items() if k != "rows"}), flush=True)
            if [r["evidence_sha256"] for r in paired["reference"]] != [
                    r["evidence_sha256"] for r in paired["candidate"]]:
                raise AssertionError(f"full-round parity failed at repeat {repeat}")
            if trace and not all(row["sample_count"] > 0 for row in paired["reference"]):
                raise AssertionError("empty sampler witness")
    medians = {mode: statistics.median(b["wall_seconds"] for b in batches
               if not b["trace"] and b["mode"] == mode) for mode in ("reference", "candidate")}
    from shengji.engine import _fast
    report = {"reference_commit": reference_sha, "method": args.method,
              "reference_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "native_sha256": hashlib.sha256(Path(_fast.__file__).read_bytes()).hexdigest(),
              "platform": platform.platform(),
              "python": sys.version, "workers": args.workers, "seeds": args.seeds,
              "candidate_source_sha256": hashlib.sha256(
                  (SERVER / "shengji/ai/mcbot.py").read_bytes()).hexdigest(),
              "environment": {k: v for k, v in os.environ.items() if k.startswith("SHENGJI_")},
              "all_pairs_identical": True, "median_batch_wall_seconds": medians,
              "speedup": medians["reference"] / medians["candidate"], "batches": batches}
    with args.out.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({"out": str(args.out), "speedup": report["speedup"]}), flush=True)


if __name__ == "__main__":
    main()
