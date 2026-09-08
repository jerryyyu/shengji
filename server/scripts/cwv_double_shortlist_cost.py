#!/usr/bin/env python3
"""Bounded real-consumer cache A/B on fixed, existing fit-panel positions.

No provider calls or game outcomes. Every decision's receipt survives a later
timeout. Compare exact score streams, batches, MC decisions and RNG, not just
the final action. Timing is observational, never a CI pass/fail threshold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import signal
import sys
import time

import numpy as np

from shengji.ai.cwv_policy import shared_evaluator
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train.cwv_shortlist_screen import make_side
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def semantic_record(value):
    """Exclude only named timing/cache telemetry; retain every policy field."""
    if isinstance(value, dict):
        return {key: semantic_record(item) for key, item in value.items()
                if key not in {"search_secs", "wall_seconds", "successor_reuse",
                               "inner_successor_reuse"}}
    if isinstance(value, (list, tuple)):
        return [semantic_record(item) for item in value]
    return value


def compare_pairs(rows):
    pairs = {}
    for row in rows:
        key = row["ordinal"], row["reuse"]
        if key in pairs:
            raise ValueError("duplicate cost case")
        pairs[key] = row
    checks = []
    for ordinal in sorted({key[0] for key in pairs}):
        pair = [pairs.get((ordinal, reuse)) for reuse in (False, True)]
        if not all(row is not None and row["complete"] for row in pair):
            checks.append({"ordinal": ordinal, "status": "incomplete"})
            continue
        if pair[0]["semantic"] != pair[1]["semantic"]:
            raise ValueError("inner reuse changed scores, batches, MC decision, input or RNG")
        checks.append({"ordinal": ordinal, "status": "identical",
                       "reference_wall_seconds": pair[0]["wall_seconds"],
                       "reuse_wall_seconds": pair[1]["wall_seconds"],
                       "speedup": pair[0]["wall_seconds"] / pair[1]["wall_seconds"]})
    return checks


class ProbeTimeout(RuntimeError):
    pass


def timeout(signum, frame):
    raise ProbeTimeout("per-decision wall limit")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ordinals", default="0,12")
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--inner-worlds", type=int, default=4)
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 600:
        parser.error("seconds must be finite and within [1,600]")
    if not 1 <= args.inner_worlds <= 30:
        parser.error("inner worlds must be within [1,30]")
    try:
        ordinals = [int(value) for value in args.ordinals.split(",")]
    except ValueError:
        parser.error("ordinals must be distinct nonnegative integers")
    if not ordinals or len(set(ordinals)) != len(ordinals) or min(ordinals) < 0:
        parser.error("ordinals must be distinct nonnegative integers")
    raw = args.panel.read_bytes()
    panel = json.loads(raw)
    if panel["split"] != "fit":
        raise ValueError("cost probe requires fit-only states")
    stages = {row["decision_ordinal"]: row["snapshot"] for row in panel["stages"]}
    snapshots = {ordinal: stages[ordinal] for ordinal in ordinals}
    evaluator = shared_evaluator(args.checkpoint, threads=1, max_batch=128,
                                 encoding="mlp-static")
    config = {
        "schema": "cwv-double-cache-cost-v1", "panel_sha256": hashlib.sha256(raw).hexdigest(),
        "coordinate": panel["coordinate"], "ordinals": ordinals,
        "states_sha256": {str(key): digest(value) for key, value in snapshots.items()},
        "checkpoint_sha256": evaluator.checkpoint_sha256,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "host": platform.node(),
        "seconds": args.seconds, "inner_worlds": args.inner_worlds,
        "ranking_worlds": 32, "selection_worlds": 30, "report_worlds": 300,
        "guidance": "selection-fraction-ceil-v2", "batch_size": 128,
        "selection": "caller-fixed fit ordinals; not selected by model score/outcome",
    }
    bind_output_config(args.out, config)
    previous_handler = signal.signal(signal.SIGALRM, timeout)
    rows = []
    try:
        for state_index, ordinal in enumerate(ordinals):
            # Counterbalance without looking at scores or runtimes.
            for reuse in ((False, True) if state_index % 2 == 0 else (True, False)):
                path = args.out / f"ordinal-{ordinal:04}-reuse-{int(reuse)}.json"
                if path.exists():
                    row = json.loads(path.read_text())
                    if row["ordinal"] != ordinal or row["reuse"] != reuse:
                        raise ValueError("cost case identity drift")
                    rows.append(row)
                    continue
                recipe = {
                    "arm": "learned", "checkpoint": args.checkpoint,
                    "checkpoint_sha256": evaluator.checkpoint_sha256,
                    "encoding": "mlp-static", "batch_size": 128, "reuse_successors": True,
                    "shortlist": {"worlds": 32, "selection_worlds": 30,
                                  "alternatives": 4, "batch_size": 128, "uniform": False},
                    "report_worlds": 300,
                    "double_shortlist": {"guidance": "selection-fraction-ceil-v2",
                                         "mode": "learned", "worlds": args.inner_worlds,
                                         "batch_size": 128, "reuse_successors": reuse},
                }
                # Fixed per ordinal, unaffected by the selected ordinal order.
                bot = make_side(recipe, "arm", 93520906 + ordinal // 12)
                if bot.evaluator is not evaluator or bot.inner_reuse_successors != reuse:
                    raise ValueError("cost probe factory did not bind reuse setting")
                trace, batches = hashlib.sha256(), []
                score_many = evaluator.score_many

                def traced(positions, seats, **kwargs):
                    values = score_many(positions, seats, **kwargs)
                    batches.append(len(positions))
                    trace.update(len(positions).to_bytes(8, "little"))
                    trace.update(np.asarray(seats, dtype="<i8").tobytes())
                    trace.update(np.asarray(values, dtype="<f8").tobytes())
                    return values

                evaluator.score_many = traced
                rnd = _round_from_snapshot(snapshots[ordinal])
                before = digest(_state_snapshot(rnd))
                start, cpu = time.perf_counter(), time.process_time()
                error, played = None, None
                signal.setitimer(signal.ITIMER_REAL, args.seconds)
                try:
                    played = bot.decide_play(rnd, rnd.turn)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    wall, cpu_used = time.perf_counter() - start, time.process_time() - cpu
                    evaluator.score_many = score_many
                after = digest(_state_snapshot(rnd))
                if before != after:
                    raise ValueError("cost probe policy mutated its input round")
                row = {
                    "ordinal": ordinal, "reuse": reuse, "complete": error is None,
                    "error": error, "wall_seconds": wall, "cpu_seconds": cpu_used,
                    "semantic": {"record": semantic_record(bot.last_decision_record),
                                 "played": played, "scores_sha256": trace.hexdigest(),
                                 "batches": batches, "input_sha256": before,
                                 "rng_sha256": digest(repr(bot.rng.getstate()))},
                    "cache": getattr(bot, "last_inner_successor_reuse", None),
                    "inner_counts": bot.double_shortlist_counts,
                    "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                        (1 if sys.platform == "darwin" else 1024),
                }
                _publish(path, row)
                rows.append(json.loads(json.dumps(row)))
                print(json.dumps({key: row[key] for key in (
                    "ordinal", "reuse", "complete", "error", "wall_seconds")}), flush=True)
        checks = compare_pairs(rows)
        _publish(args.out / "summary.json", {"config": config, "checks": checks,
                 "complete": all(row["complete"] for row in rows),
                 "note": "Two-position diagnostic is not a representative game speedup."})
        return 0 if all(row["complete"] for row in rows) else 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
