#!/usr/bin/env python3
"""Run independent per-deal W32 diagnostics; retain completed roots on failure."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import multiprocessing
from pathlib import Path
import time

from shengji.ai.cwv_policy import shared_evaluator
from shengji.train.cwv_decision_diagnostic import diagnose, digest
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


_EVALUATOR = None


def initialize(checkpoint):
    global _EVALUATOR
    _EVALUATOR = shared_evaluator(checkpoint, threads=1, max_batch=128, encoding="mlp-static")


def work(entry, config_sha256, seed, worlds, checkpoint_sha256):
    if _EVALUATOR.checkpoint_sha256 != checkpoint_sha256:
        raise ValueError("worker evaluation checkpoint SHA mismatch")
    row = diagnose(entry, _EVALUATOR, seed=seed, reference_worlds=worlds)
    row["config_sha256"] = config_sha256
    return row


def read_panel(path):
    panel = json.loads(Path(path).read_text())
    entries = panel.get("entries", [])
    if panel.get("schema") != "cwv-horizon-panel-v1" or not entries:
        raise ValueError("expected nonempty saved-root panel")
    if any(e.get("provenance", {}).get("split") != "fit" for e in entries):
        raise ValueError("every root must be explicitly fit-only")
    if len({e["deal_key"] for e in entries}) != len(entries):
        raise ValueError("panel must contain one root per independent deal")
    if len({e["id"] for e in entries}) != len(entries):
        raise ValueError("duplicate root id")
    for entry in entries:
        if len(entry["id"]) != 64 or any(c not in "0123456789abcdef" for c in entry["id"]):
            raise ValueError("invalid root id")
    return panel


def run(panel_path, checkpoint, output, *, checkpoint_sha256,
        workers=1, reference_worlds=1024, seed=20260909, max_new_roots=None):
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    if type(reference_worlds) is not int or reference_worlds < 4 or reference_worlds % 2:
        raise ValueError("reference worlds must be even and >=4")
    if max_new_roots is not None and (type(max_new_roots) is not int or max_new_roots < 1):
        raise ValueError("max_new_roots must be positive")
    panel = read_panel(panel_path)
    initialize(checkpoint)
    if _EVALUATOR.checkpoint_sha256 != checkpoint_sha256:
        raise ValueError("evaluation checkpoint SHA mismatch")
    config = {
        "schema": "cwv-decision-diagnostic-config-v1", "panel_sha256": digest(panel),
        "checkpoint_sha256": _EVALUATOR.checkpoint_sha256,
        "source_policy": panel.get("policy"),
        "seed": seed, "reference_worlds": reference_worlds,
        "recipe": {"W": 32, "K": 4, "N": 30, "R": 300, "batch": 128, "reuse": True},
        "source": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "runner_sha256": digest(Path(__file__).read_text()),
        "scope": "FIT diagnostic; no heldout opening, new gameplay or policy change",
    }
    output = Path(output)
    bind_output_config(output, config)
    config_sha = digest(config)
    completed, pending = [], []
    for entry in panel["entries"]:
        path = output / f"state-{entry['id']}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row.get("config_sha256") != config_sha or row.get("root_sha256") != digest(entry):
                raise ValueError("completed root/config mismatch")
            completed.append(row)
        else:
            pending.append(entry)
    if max_new_roots is not None:
        pending = pending[:max_new_roots]
    started = time.monotonic()
    failures = []

    def accept(entry, row):
        if row.get("config_sha256") != config_sha or row.get("root_sha256") != digest(entry):
            raise ValueError("worker root/config mismatch")
        if row.get("model", {}).get("checkpoint_sha256") != checkpoint_sha256:
            raise ValueError("worker result model SHA mismatch")
        _publish(output / f"state-{entry['id']}.json", row)
        completed.append(row)
        print(f"{len(completed)}/{len(panel['entries'])} roots complete; "
              f"last={row['wall_seconds']:.1f}s; elapsed={time.monotonic()-started:.1f}s", flush=True)

    try:
        if workers == 1:
            for entry in pending:
                accept(entry, work(entry, config_sha, seed, reference_worlds, checkpoint_sha256))
        else:
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                                     initializer=initialize, initargs=(checkpoint,)) as pool:
                futures = {pool.submit(work, e, config_sha, seed, reference_worlds,
                                       checkpoint_sha256): e for e in pending}
                while futures:
                    done, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
                    for future in done:
                        entry = futures.pop(future)
                        try:
                            accept(entry, future.result())
                        except Exception as exc:
                            # Drain other roots, publishing successes even if
                            # one root fails. Resume only missing roots.
                            failures.append({"root_id": entry["id"],
                                             "error_type": type(exc).__name__, "message": str(exc)})
                    if not done:
                        print(f"{len(completed)}/{len(panel['entries'])} complete; "
                              f"active <= {workers}; elapsed={time.monotonic()-started:.1f}s", flush=True)
            if failures:
                raise RuntimeError(f"{len(failures)} root(s) failed; completed roots retained")
    except Exception as exc:
        _publish(output / "failure.json", {"config_sha256": config_sha,
                  "error_type": type(exc).__name__, "message": str(exc),
                  "completed": len(completed), "expected": len(panel["entries"]),
                  "roots": failures})
        raise
    summary = {"config_sha256": config_sha,
               "complete": len(completed) == len(panel["entries"]),
               "expected_deals": len(panel["entries"]),
               "deals": len(completed), "workers": workers,
               "invocation_wall_seconds": time.monotonic()-started,
               "summed_root_wall_seconds": sum(r["wall_seconds"] for r in completed),
               "mean_metrics": {k: sum(r["metrics"][k] for r in completed)/len(completed)
                                for k in ("final_gain_vs_incumbent", "descriptive_coverage_regret",
                                          "descriptive_selection_regret", "model_action_gap_mae",
                                          "zero_action_gap_mae")},
               "scope": config["scope"]}
    _publish(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--checkpoint-sha256", required=True,
                        help="Expected evaluation model SHA; independent of the trajectory generator")
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--reference-worlds", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--max-new-roots", type=int,
                        help="Bound this invocation; completed roots remain reusable on resume")
    args = parser.parse_args()
    run(args.panel, args.checkpoint, args.out, checkpoint_sha256=args.checkpoint_sha256,
        workers=args.workers,
        reference_worlds=args.reference_worlds, seed=args.seed, max_new_roots=args.max_new_roots)


if __name__ == "__main__":
    main()
