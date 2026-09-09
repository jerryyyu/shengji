"""Resumable DEV diagnostic panel. No gameplay or production registration.

Run --limit 1 first to measure the exact path; resume the SAME panel without
that limit. Completed state results are retained; failures are saved separately.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from .cwv_bury_diagnostic import capture_state, diagnose


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def run_state(config, row):
    from ..ai.cwv_policy import shared_evaluator
    evaluator = shared_evaluator(config["checkpoint"], threads=1,
                                 max_batch=128, encoding="mlp-static")
    if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
        raise ValueError("checkpoint changed after panel admission")
    cpu_start = time.process_time()
    result = diagnose(row, evaluator, **config["dose"])
    result["cpu_seconds"] = time.process_time() - cpu_start
    result["config_sha256"] = config["config_sha256"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--states", type=int, default=64)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, help="process only this many pending states; panel unchanged")
    parser.add_argument("--model-worlds", type=int, default=32)
    parser.add_argument("--reference-worlds", type=int, default=256)
    parser.add_argument("--selection-worlds", type=int, default=32)
    args = parser.parse_args(argv)
    if min(args.states, args.workers, args.model_worlds, args.selection_worlds) < 1:
        parser.error("positive states/workers/worlds required")
    if args.reference_worlds <= args.selection_worlds or (args.limit is not None and args.limit < 1):
        parser.error("need independent reference tail and positive limit")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
    from ..ai.cwv_policy import shared_evaluator
    evaluator = shared_evaluator(args.checkpoint, threads=1, max_batch=128, encoding="mlp-static")
    config = {"schema": "cwv-bury-panel-v1", "states": args.states,
              "checkpoint": str(Path(args.checkpoint).resolve()),
              "checkpoint_sha256": evaluator.checkpoint_sha256,
              "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ("cwv_bury.py", "cwv_bury_diagnostic.py", "cwv_bury_panel.py")},
              "dose": {"model_worlds": args.model_worlds, "reference_worlds": args.reference_worlds,
                       "selection_worlds": args.selection_worlds, "alternatives": 4}}
    config["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    args.out.mkdir(parents=True, exist_ok=True)
    config_path = args.out / "config.json"
    if config_path.exists():
        if json.loads(config_path.read_text()) != config:
            raise ValueError("panel configuration changed; preserve old results in their original panel")
    else:
        atomic_json(config_path, config)
    panel_path = args.out / "states.json"
    if panel_path.exists():
        rows = json.loads(panel_path.read_text())
    else:
        rows = [capture_state(i) for i in range(args.states)]
        atomic_json(panel_path, rows)
    if [r["index"] for r in rows] != list(range(args.states)):
        raise ValueError("panel state population mismatch")
    pending = []
    for row in rows:
        path = args.out / f"state-{row['index']:04d}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["config_sha256"] != config["config_sha256"] or saved["state"] != row:
                raise ValueError("completed state binding mismatch")
        else:
            pending.append(row)
    complete = args.states - len(pending)
    if args.limit:
        pending = pending[:args.limit]
    started = time.monotonic()
    times = []
    failures = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(run_state, config, row): row["index"] for row in pending}
        while tasks:
            done, _ = wait(tasks, timeout=30, return_when=FIRST_COMPLETED)
            for future in done:
                index = tasks.pop(future)
                try:
                    result = future.result()
                except Exception:
                    failures += 1
                    atomic_json(args.out / f"error-{index:04d}.json",
                                {"index": index, "traceback": traceback.format_exc(),
                                 "config_sha256": config["config_sha256"]})
                else:
                    atomic_json(args.out / f"state-{index:04d}.json", result)
                    complete += 1
                    times.append(result["wall_seconds"])
            progress = {"completed": complete, "total": args.states,
                        "percent": round(100 * complete / args.states, 2),
                        "active_workers_max": min(args.workers, len(tasks)),
                        "failures_this_invocation": failures,
                        "elapsed_seconds": time.monotonic() - started,
                        "mean_state_seconds": sum(times) / len(times) if times else None}
            atomic_json(args.out / "progress.json", progress)
            print(json.dumps(progress), flush=True)
    if failures:
        raise SystemExit(f"{failures} states failed; completed states retained")


if __name__ == "__main__":
    main()
