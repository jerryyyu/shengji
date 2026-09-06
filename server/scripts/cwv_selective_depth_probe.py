#!/usr/bin/env python3
"""Small fixed-fit-state timing check, not a capacity census or strength result."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import signal
import time

from scripts.cwv_double_shortlist_cost import digest, timeout
from shengji.ai.cwv_policy import shared_evaluator
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train.cwv_shortlist_screen import make_side
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.panel.read_bytes()
    panel = json.loads(raw)
    if panel["split"] != "fit":
        raise ValueError("timing check requires fit-only states")
    # Fixed temporal spacing, no search for a favorable runtime or gate outcome.
    ordinals = (0, 12, 24)
    snapshots = {row["decision_ordinal"]: row["snapshot"] for row in panel["stages"]}
    snapshots = {key: snapshots[key] for key in ordinals}
    evaluator = shared_evaluator(args.checkpoint, threads=1, max_batch=128,
                                 encoding="mlp-static")
    recipe = {
        "arm": "learned", "checkpoint": args.checkpoint,
        "checkpoint_sha256": evaluator.checkpoint_sha256,
        "encoding": "mlp-static", "batch_size": 128, "reuse_successors": True,
        "shortlist": {"worlds": 32, "selection_worlds": 30,
                      "alternatives": 4, "batch_size": 128, "uniform": False},
        "report_worlds": 300, "baseline": "flat-shortlist",
        "double_shortlist": {"guidance": "selection-fraction-ceil-v2",
                             "mode": "learned", "worlds": 4,
                             "batch_size": 128, "reuse_successors": True},
        "selective_depth": {"gate": "paired-flat-gap-v1", "z": 1.7,
                            "inner_legal_limit": 128, "raw_follow_limit": 4096},
    }
    config = {
        "schema": "cwv-selective-depth-probe-v1", "recipe": recipe,
        "panel_sha256": hashlib.sha256(raw).hexdigest(),
        "coordinate": panel["coordinate"], "ordinals": list(ordinals),
        "per_decision_wall_seconds": 120, "seed": 93520906,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "host": platform.node(), "python": platform.python_version(),
        "scope": "contended-host fixed-state timing only; no new games or provider calls",
    }
    bind_output_config(args.out, config)
    previous = signal.signal(signal.SIGALRM, timeout)
    rows = []
    try:
        for index, ordinal in enumerate(ordinals):
            for side in (("baseline", "arm") if index % 2 == 0 else ("arm", "baseline")):
                path = args.out / f"ordinal-{ordinal:04}-{side}.json"
                if path.exists():
                    row = json.loads(path.read_text())
                    if row["ordinal"] != ordinal or row["side"] != side:
                        raise ValueError("timing case identity drift")
                    rows.append(row)
                    if row["error"] is not None:
                        return 1
                    continue
                bot = make_side(recipe, side, 93520906 + index)
                rnd = _round_from_snapshot(snapshots[ordinal])
                before = digest(_state_snapshot(rnd))
                start, cpu = time.perf_counter(), time.process_time()
                error = None
                signal.setitimer(signal.ITIMER_REAL, 120)
                try:
                    bot.decide_play(rnd, rnd.turn)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                if digest(_state_snapshot(rnd)) != before:
                    raise ValueError("timed policy mutated the input round")
                row = {
                    "ordinal": ordinal, "side": side, "error": error,
                    "wall_seconds": time.perf_counter() - start,
                    "cpu_seconds": time.process_time() - cpu,
                    "input_sha256": before, "record": bot.last_decision_record,
                    "selective_counts": getattr(bot, "selective_depth_counts", None),
                }
                _publish(path, row)
                rows.append(row)
                print(json.dumps({key: row[key] for key in (
                    "ordinal", "side", "error", "wall_seconds", "cpu_seconds")}), flush=True)
                if error is not None:
                    return 1  # keep prior decisions; no replacement or retry
        _publish(args.out / "summary.json", {"complete": True, "cases": len(rows),
                 "scope": config["scope"]})
        return 0
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
