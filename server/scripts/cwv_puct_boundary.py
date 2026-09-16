#!/usr/bin/env python3
"""Bounded fixed-state PUCT diagnostic; never a gameplay or strength claim.

One fresh spawned child owns each saved state.  The child loads immutable model
assets, samples one canonical world pool, and runs the DEV PUCT kernel.  The
parent publishes each row as it finishes, including failures and timeouts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import platform
import queue
import resource
import sys
import threading
import time
from typing import Any, Mapping

from shengji.ai.cwv_policy import file_sha256, shared_evaluator, sample_worlds
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train.cwv_bounded_puct import (
    CWVBoundedPuctBot, PuctConfig, root_clone, search_worlds,
)
from shengji.train.cwv_prior_admission import CWVPriorAdmissionConfig
from shengji.train.cwv_shortlist import CWVShortlistConfig
from shengji.train.search_screen import (
    _publish, bind_output_config, execution_source_identity,
)


SCHEMA = "cwv-puct-boundary-v1"
DECISION_TIMEOUT_SECONDS = 300.0


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def json_safe(value: Any) -> Any:
    """JSON-normalize nested results, retaining tuple-key maps as row lists."""
    if isinstance(value, Mapping):
        if any(isinstance(key, tuple) for key in value):
            if not all(isinstance(key, tuple) for key in value):
                raise TypeError("mixed tuple and non-tuple mapping keys")
            return [{"key": json_safe(list(key)), "value": json_safe(item)}
                    for key, item in value.items()]
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    # Numpy scalars are deliberately handled without making the publication
    # contract depend on numpy's JSON encoder.
    if hasattr(value, "item") and callable(value.item):
        return json_safe(value.item())
    if hasattr(value, "tolist") and callable(value.tolist):
        return json_safe(value.tolist())
    return value


def _world_digest(worlds) -> str:
    return _digest([{"hands": [list(hand) for hand in hands],
                     "buried": list(buried)} for hands, buried in worlds])


def _prior_identity(bot, prior_checkpoint: str | None,
                    prior_sha256: str | None) -> dict[str, Any]:
    if prior_checkpoint is None:
        return {"mode": "uniform"}
    return {"mode": "head", "checkpoint": str(Path(prior_checkpoint).resolve()),
            "checkpoint_sha256": prior_sha256,
            "kind": getattr(bot, "_prior_kind", None),
            "schema": getattr(getattr(bot, "prior_config", None), "schema", None)}


def _uniform_prior(_world, _seat, actions):
    import numpy as np
    return np.zeros(len(actions), dtype=np.float64)


def _outcome_evaluator(checkpoint):
    kwargs = {} if Path(checkpoint).suffix.lower() == '.npz' else {'value_head': 'outcome'}
    evaluator = shared_evaluator(checkpoint, threads=1, **kwargs)
    if evaluator.value_head != 'outcome':
        raise ValueError('boundary PUCT requires an outcome-head value evaluator')
    return evaluator


def _child_run(spec: dict[str, Any], send) -> None:
    """Load and run exactly one state.  Never called in the parent process."""
    process_started = time.perf_counter()
    process_cpu_started = time.process_time()
    try:
        # Loading is intentionally before decision timing.  The parent still
        # applies the documented 300-second total child cap, including load.
        evaluator = _outcome_evaluator(spec["checkpoint"])
        prior_sha = spec.get("prior_checkpoint_sha256")
        prior_config = None
        if spec.get("prior_checkpoint") is not None:
            prior_config = CWVPriorAdmissionConfig(
                checkpoint=spec["prior_checkpoint"], checkpoint_sha256=prior_sha)
        shortlist_config = CWVShortlistConfig(worlds=spec["worlds"])
        bot = CWVBoundedPuctBot(
            evaluator, seed=spec["seed"], config=shortlist_config,
            prior=prior_config,
            puct_config=PuctConfig(sweeps=spec["sweeps"], depth=spec["depth"],
                                   batch_size=spec["worlds"]))
        loaded_seconds = time.perf_counter() - process_started
        rnd = _round_from_snapshot(spec["snapshot"])
        seat = int(rnd.turn)
        state_digest = _digest(_state_snapshot(rnd))
        decision_started = time.perf_counter()
        decision_cpu_started = time.process_time()
        worlds, attempts = sample_worlds(bot, rnd, seat, spec["worlds"])
        if len(worlds) != spec["worlds"]:
            raise RuntimeError("sampled-world pool underfilled")
        world_digest = _world_digest(worlds)
        roots = [root_clone(rnd, hands, buried) for hands, buried in worlds]
        prior = bot._tree_prior if prior_config is not None else _uniform_prior
        result = search_worlds(
            roots, seat, prior_logits=prior, evaluator=evaluator,
            config=PuctConfig(sweeps=spec["sweeps"], depth=spec["depth"],
                              batch_size=spec["worlds"]), profile=True)
        decision_wall = time.perf_counter() - decision_started
        decision_cpu = time.process_time() - decision_cpu_started
        result = json_safe(result)
        diagnostics = result.get("diagnostics", {})
        row = {
            "schema": SCHEMA, "state": spec["state"], "seed": spec["seed"],
            "status": "ok", "seat": seat, "state_sha256": state_digest,
            "sampled_worlds_sha256": world_digest, "worlds": len(worlds),
            "sampling_attempts": attempts,
            "model_identity": json_safe(evaluator.identity()),
            "prior_identity": _prior_identity(bot, spec.get("prior_checkpoint"), prior_sha),
            "source_identity": spec["source_identity"],
            "config_sha256": spec["config_sha256"],
            "action": result.get("action"),
            "result": result,
            "counts": result.get("counts"),
            "depth": {"max": max((int(x) for x in diagnostics.get(
                                  "depth_histogram", {})), default=0),
                      "histogram": diagnostics.get("depth_histogram", {})},
            "timings": result.get("timings", {}),
            "coverage": {key: diagnostics.get(key) for key in (
                "root_legal_counts", "root_visited_actions",
                "root_visited_prior_mass")},
            "wall_seconds": decision_wall, "cpu_seconds": decision_cpu,
            "load_wall_seconds": loaded_seconds,
            "total_child_wall_seconds": time.perf_counter() - process_started,
            "peak_rss_bytes": _rss_bytes(),
            "timeout_seconds": DECISION_TIMEOUT_SECONDS,
            "timeout_scope": "total child task including model/prior load",
        }
    except BaseException as exc:  # child must always return a durable error row
        row = {
            "schema": SCHEMA, "state": spec["state"], "seed": spec["seed"],
            "status": "error", "action": None,
            "error": f"{type(exc).__name__}: {exc}",
            "source_identity": spec["source_identity"],
            "config_sha256": spec["config_sha256"],
            "wall_seconds": time.perf_counter() - process_started,
            "cpu_seconds": time.process_time() - process_cpu_started,
            "peak_rss_bytes": _rss_bytes(),
            "timeout_seconds": DECISION_TIMEOUT_SECONDS,
            "timeout_scope": "total child task including model/prior load",
        }
    try:
        send.send(row)
    finally:
        send.close()


def run_child(spec: dict[str, Any], *, timeout_seconds: float = DECISION_TIMEOUT_SECONDS,
              context=None) -> dict[str, Any]:
    """Supervise one fresh spawn and return an OK, error, or timeout row."""
    ctx = context or mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_run, args=(spec, send))
    process.daemon = False
    started = time.perf_counter()
    process.start()
    send.close()
    # Drain concurrently: a result larger than the pipe buffer otherwise blocks
    # send(), so joining the child first manufactures a search timeout.
    received = queue.Queue(maxsize=1)

    def drain():
        try:
            received.put((True, recv.recv()))
        except (EOFError, OSError) as exc:
            received.put((False, str(exc)))

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    payload = None
    try:
        payload = received.get(timeout=max(0.0, timeout_seconds -
                                          (time.perf_counter() - started)))
    except queue.Empty:
        pass
    process.join(max(0.0, timeout_seconds - (time.perf_counter() - started)))
    if process.is_alive():
        process.terminate()
        process.join(5.0)
        if process.is_alive():
            process.kill()
            process.join(5.0)
        row = {"schema": SCHEMA, "state": spec["state"], "seed": spec["seed"],
               "status": "timeout", "action": None,
               "error": f"child exceeded {timeout_seconds:g}s",
               "source_identity": spec["source_identity"],
               "config_sha256": spec["config_sha256"],
               "wall_seconds": time.perf_counter() - started,
               "cpu_seconds": None, "peak_rss_bytes": None,
               "timeout_seconds": timeout_seconds,
               "timeout_scope": "total child task including model/prior load"}
        recv.close()
        reader.join(1.0)
        return row
    try:
        if payload is not None and payload[0]:
            row = payload[1]
        else:
            row = {"schema": SCHEMA, "state": spec["state"], "seed": spec["seed"],
                   "status": "error", "action": None,
                   "error": f"child exited without result (exit {process.exitcode})",
                   "source_identity": spec["source_identity"],
                   "config_sha256": spec["config_sha256"],
                   "wall_seconds": time.perf_counter() - started,
                   "cpu_seconds": None, "peak_rss_bytes": None,
                   "timeout_seconds": timeout_seconds,
                   "timeout_scope": "total child task including model/prior load"}
    finally:
        recv.close()
        reader.join(1.0)
        process.join()
    return row


def _validate_row(path: Path, index: int, config_sha256: str) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if (row.get("schema") != SCHEMA or row.get("state") != index
            or row.get("config_sha256") != config_sha256
            or row.get("status") not in ("ok", "error", "timeout")):
        raise ValueError(f"saved state row {path.name} is incompatible")
    return row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states-json", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--prior-checkpoint", required=True, type=Path)
    parser.add_argument("--output", "--out", dest="output", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--worlds", type=int, default=32)
    parser.add_argument("--sweeps", type=int, default=8)
    parser.add_argument("--depth", type=int, default=8)
    args = parser.parse_args(argv)
    if min(args.worlds, args.sweeps, args.depth) < 1:
        parser.error("worlds, sweeps, and depth must be positive")
    snapshots_raw = args.states_json.read_bytes()
    snapshots = json.loads(snapshots_raw)
    if type(snapshots) is not list or not snapshots:
        parser.error("states-json must contain a nonempty snapshot list")
    checkpoint = args.checkpoint.resolve()
    if not checkpoint.is_file():
        parser.error(f"checkpoint not found: {checkpoint}")
    prior = None if args.prior_checkpoint is None else args.prior_checkpoint.resolve()
    if prior is not None and not prior.is_file():
        parser.error(f"prior checkpoint not found: {prior}")
    # Validate snapshots in the parent before any child is launched.
    for snapshot in snapshots:
        _round_from_snapshot(snapshot)
    model_sha = file_sha256(checkpoint)
    prior_sha = None if prior is None else file_sha256(prior)
    source = execution_source_identity(Path(__file__).resolve().parents[1] / "shengji")
    config = {
        "schema": SCHEMA, "states_sha256": hashlib.sha256(snapshots_raw).hexdigest(),
        "checkpoint": str(checkpoint), "checkpoint_sha256": model_sha,
        "prior_checkpoint": None if prior is None else str(prior),
        "prior_checkpoint_sha256": prior_sha, "seed": args.seed,
        "worlds": args.worlds, "sweeps": args.sweeps, "depth": args.depth,
        "timeout_seconds": DECISION_TIMEOUT_SECONDS,
        "timeout_scope": "total child task including model/prior load",
        "source_identity": source,
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "python": platform.python_version(), "platform": platform.platform(),
        "claim": "diagnostic search telemetry only; no strength claim",
    }
    config_sha = _digest(config)
    bind_output_config(args.output, config)
    for index, snapshot in enumerate(snapshots):
        path = args.output / f"state-{index:04d}.json"
        if path.exists():
            _validate_row(path, index, config_sha)
            continue
        spec = {"state": index, "snapshot": snapshot, "checkpoint": str(checkpoint),
                "prior_checkpoint": None if prior is None else str(prior),
                "prior_checkpoint_sha256": prior_sha, "seed": args.seed + index,
                "worlds": args.worlds, "sweeps": args.sweeps, "depth": args.depth,
                "source_identity": source, "config_sha256": config_sha}
        row = run_child(spec)
        _publish(path, json_safe(row))
        print(json.dumps({"state": index, "status": row["status"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
