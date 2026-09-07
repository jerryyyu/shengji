#!/usr/bin/env python3
"""Fixed-state W32 A/B of inference optimizations; no new games or labels.

The historical default compares prepared lead validation. ``--optimization
fused-static`` compares fused tensor construction with the prior static path,
keeping prepared lead validation enabled in both arms. Patches are restricted
to this single-thread diagnostic process, never live workers or engine globals.
Keep every scoring row, batch, shortlist, report, action, work count and RNG
state identical. Timings on a contended host are diagnostic, not speed claims.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import time
from unittest.mock import patch

from scripts.cwv_shortlist_cost import ScoreTrace
from shengji.ai import cwv_static_encoding
from shengji.ai.cwv_policy import CompleteWorldEvaluator, file_sha256
from shengji.ai.cwv_successor_reuse import WorldSuccessorCache
from shengji.engine import fast
from shengji.engine.round import Round
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train import cwv_shortlist
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _expired(_signum, _frame):
    raise TimeoutError("per-decision inference diagnostic deadline")


def _optimization_context(optimization, enabled):
    if optimization == "prepared-lead":
        return patch.object(cwv_shortlist, "WorldSuccessorCache",
                            partial(WorldSuccessorCache, prepare_leads=enabled))
    if optimization == "fused-static":
        return (nullcontext() if enabled else patch.object(
            cwv_static_encoding, "_fused_static_tensors", lambda *_: None))
    raise ValueError("unknown inference optimization")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states-json", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--decision-seconds", type=int, default=60)
    parser.add_argument("--seed0", type=int, default=89260904)
    parser.add_argument("--optimization", choices=("prepared-lead", "fused-static"),
                        default="prepared-lead")
    args = parser.parse_args(argv)
    if min(args.repetitions, args.decision_seconds) < 1:
        parser.error("positive repetitions and per-decision deadline required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    snapshots = json.loads(args.states_json.read_bytes())
    if not isinstance(snapshots, list) or not snapshots:
        parser.error("states-json must contain a nonempty ordered snapshot list")
    evaluator = CompleteWorldEvaluator(str(args.checkpoint.resolve()), threads=1,
                                       max_batch=128, encoding="mlp-static")
    native_active = bool(fast.HAVE_FAST and Round.play is fast._fast.round_play)
    if os.environ.get("SHENGJI_FAST") == "1" and not native_active:
        raise RuntimeError("compiled play route requested but not active")
    recipe = CWVShortlistConfig(worlds=32)
    arm_key = "prepared" if args.optimization == "prepared-lead" else "fused"
    config = {
        "schema": "cwv-inference-probe-v2", "seed0": args.seed0,
        "optimization": args.optimization, "arm_key": arm_key,
        "states_sha256": file_sha256(args.states_json), "states": len(snapshots),
        "checkpoint_sha256": evaluator.checkpoint_sha256,
        "repetitions": args.repetitions, "decision_seconds": args.decision_seconds,
        "recipe": asdict(recipe), "encoding": "mlp-static", "batch_size": 128,
        "source": execution_source_identity(Path(cwv_shortlist.__file__).parents[1]),
        "script_sha256": file_sha256(__file__), "python": platform.python_version(),
        "platform": platform.platform(), "host": platform.node(),
        "fast_env": os.environ.get("SHENGJI_FAST"),
        "native_play_active": native_active,
        "order": "counterbalanced by (state index + repetition) parity",
        "population": "all caller-supplied saved states; no outcome selection or recapture",
    }
    bind_output_config(args.out, config)
    rows = []
    previous_handler = signal.signal(signal.SIGALRM, _expired)
    try:
        for repetition in range(args.repetitions):
            for index, snapshot in enumerate(snapshots):
                pair = []
                order = (False, True) if (index + repetition) % 2 == 0 else (True, False)
                for enabled in order:
                    path = args.out / f"r{repetition:02}-state-{index:04}-{int(enabled)}.json"
                    if path.exists():
                        row = json.loads(path.read_bytes())
                        if (row["state"], row["repetition"], row[arm_key]) != (index, repetition, enabled):
                            raise ValueError("saved diagnostic row identity drift")
                    else:
                        rnd = _round_from_snapshot(snapshot)
                        before = _digest(_state_snapshot(rnd))
                        trace = ScoreTrace(evaluator)
                        bot = CWVShortlistBot(trace, seed=args.seed0 + index,
                                             config=recipe, reuse_successors=True)
                        start, cpu = time.perf_counter(), time.process_time()
                        error = None
                        signal.alarm(args.decision_seconds)
                        try:
                            with _optimization_context(args.optimization, enabled):
                                played = bot.decide_play(rnd, rnd.turn)
                        except Exception as exc:
                            error = f"{type(exc).__name__}: {exc}"
                            played = None
                        finally:
                            signal.alarm(0)
                        wall_elapsed = time.perf_counter() - start
                        cpu_elapsed = time.process_time() - cpu
                        record = bot.last_decision_record
                        detail = getattr(bot, "last_shortlist", None)
                        row = {
                            "state": index, "repetition": repetition, arm_key: enabled,
                            "error": error, "wall_seconds": wall_elapsed, "cpu_seconds": cpu_elapsed,
                            "semantic": {
                                "input_sha256": before,
                                "input_unchanged": before == _digest(_state_snapshot(rnd)),
                                "played": played, "score_sha256": trace.digest.hexdigest(),
                                "batches": dict(trace.batches),
                                "shortlist": None if detail is None else {
                                    k: v for k, v in detail.items() if k != "wall_seconds"},
                                "report": None if record is None else record.get("report_fold"),
                                "means": None if record is None else record.get("means"),
                                "work": None if record is None else record.get("work"),
                                "allocation": None if record is None else record.get("alloc"),
                                "rng_sha256": _digest(repr(bot.rng.getstate())),
                                "reuse": bot.last_successor_reuse,
                            },
                        }
                        row = json.loads(json.dumps(row, allow_nan=False))
                        _publish(path, row)
                    rows.append(row)
                    pair.append(row)
                    print(json.dumps({k: row[k] for k in (
                        "state", "repetition", arm_key, "error", "wall_seconds")}), flush=True)
                    if row["error"] is not None:
                        raise RuntimeError("saved failed diagnostic; no automatic repeat: " + row["error"])
                if pair[0]["semantic"] != pair[1]["semantic"] or not pair[0]["semantic"]["input_unchanged"]:
                    raise ValueError(f"actual W32 consumer parity failed at state {index}, repetition {repetition}")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
    totals = {str(enabled): sum(row["wall_seconds"] for row in rows if row[arm_key] == enabled)
              for enabled in (False, True)}
    result = {"pairs_identical": len(rows) // 2, "wall_seconds": totals,
              "observed_wall_ratio": totals["False"] / totals["True"],
              "qualification": "Fixed-state consumer A/B, not gameplay; host isolation must be documented separately."}
    _publish(args.out / "summary.json", result)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
