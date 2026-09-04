"""Compare two native builds with identical Python source on an idle host.

Each arm has a separate spawned pool, so an extension is never hot-swapped.
Only one pool runs a batch at a time. Both arms use exact production MC;
trace warmups and timed full-round evidence must match, just as in
bench_mc_hotpath. All batch timings are retained, not only the best run.

Example, from server/ after building each isolated checkout:
  SHENGJI_FAST=1 python scripts/bench_mc_builds.py \
    --reference-server /path/to/reference/server \
    --candidate-server /path/to/candidate/server --workers 16 \
    --seeds 7 19 31 43 --repeats 3 --out /path/to/fresh-report.json

The two builds intentionally have different ballot fingerprints. These three
identity fields are excluded from semantic equality, but the raw record digest,
ballot provenance and each loaded extension digest are retained in the report.
No scores, candidates, counters or RNG state are exempted from comparison.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import multiprocessing
from pathlib import Path
import statistics
import sys
import time

import bench_mc_hotpath as hotpath


def source_identity(root):
    files = sorted(path for pattern in ("*.py", "*.pyx")
                   for path in (root / "shengji").rglob(pattern))
    if not files:
        raise ValueError("source tree is absent")
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def initialize(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    hotpath.initialize((root / "shengji/ai/mcbot.py").read_text(),
                       "_report_fold_gap", ignore_ballot_build_identity=True)
    from shengji.engine import _fast
    import shengji.ai.mcbot as mc
    if Path(mc.__file__).resolve() != root / "shengji/ai/mcbot.py":
        raise RuntimeError("worker imported the wrong source tree")
    global NATIVE_SHA
    NATIVE_SHA = hashlib.sha256(Path(_fast.__file__).read_bytes()).hexdigest()


def one_round(task):
    row = hotpath.one_round(task)
    row["native_sha256"] = NATIVE_SHA
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-server", type=Path, required=True)
    parser.add_argument("--candidate-server", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    journal = args.out.with_suffix(".jsonl")
    if args.out.exists() or journal.exists() or args.workers < 1 or args.repeats < 1:
        parser.error("fresh output and positive workers/repeats required")
    roots = {"reference": args.reference_server.resolve(),
             "candidate": args.candidate_server.resolve()}
    sources = {mode: source_identity(root) for mode, root in roots.items()}
    if sources["reference"] != sources["candidate"]:
        parser.error("compiler A/B requires identical Python source trees")
    batches = []
    with ExitStack() as stack:
        progress = stack.enter_context(journal.open("x"))
        pools = {mode: stack.enter_context(ProcessPoolExecutor(
            max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize, initargs=(str(root),)))
            for mode, root in roots.items()}
        for repeat in range(-1, args.repeats):
            trace = repeat == -1
            order = ("reference", "candidate") if repeat % 2 else ("candidate", "reference")
            paired = {}
            for mode in order:
                started = time.perf_counter()
                # Both are the same Python candidate; only their native build differs.
                rows = list(pools[mode].map(one_round,
                    [(seed, index % 13, "candidate", trace)
                     for index, seed in enumerate(args.seeds)]))
                batch = {"repeat": repeat, "trace": trace, "mode": mode,
                         "wall_seconds": time.perf_counter() - started, "rows": rows}
                paired[mode] = rows
                batches.append(batch)
                progress.write(json.dumps(batch, allow_nan=False) + "\n")
                progress.flush()
                print(json.dumps({key: value for key, value in batch.items()
                                  if key != "rows"}), flush=True)
            if [row["evidence_sha256"] for row in paired["reference"]] != [
                    row["evidence_sha256"] for row in paired["candidate"]]:
                raise AssertionError(f"native full-round parity failed at repeat {repeat}")
            if trace and not all(row["sample_count"] > 0 for row in paired["reference"]):
                raise AssertionError("empty sampler trace")
    native = {mode: {row["native_sha256"] for batch in batches if batch["mode"] == mode
                     for row in batch["rows"]} for mode in roots}
    if any(len(values) != 1 for values in native.values()):
        raise AssertionError("mixed native builds within one arm")
    if native["reference"] == native["candidate"]:
        raise AssertionError("compiler A/B used the same extension in both arms")
    medians = {mode: statistics.median(batch["wall_seconds"] for batch in batches
               if not batch["trace"] and batch["mode"] == mode) for mode in roots}
    report = {"schema": "mc-native-build-ab-v1", "source_sha256": sources["reference"],
              "native_sha256": {mode: next(iter(values)) for mode, values in native.items()},
              "roots": {mode: str(root) for mode, root in roots.items()},
              "python": sys.version, "workers": args.workers, "seeds": args.seeds,
              "ignored_decision_fields": ["search_secs", "ballot.source_digest",
                                          "ballot.digest", "ballot.display"],
              "all_pairs_identical": True, "median_batch_wall_seconds": medians,
              "speedup": medians["reference"] / medians["candidate"], "batches": batches}
    with args.out.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({"out": str(args.out), "speedup": report["speedup"]}), flush=True)


if __name__ == "__main__":
    main()
