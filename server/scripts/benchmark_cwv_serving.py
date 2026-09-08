"""Bounded saved-state W32 serving measurement, never a strength screen.

Example (private state snapshots stay outside Git):
  OPENBLAS_NUM_THREADS=1 SHENGJI_FAST=1 PYTHONPATH=server python \
    server/scripts/benchmark_cwv_serving.py model.npz states.private.json
Run in a fresh process to measure serving RSS without a Torch import.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import resource
import signal
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("states")
    parser.add_argument("--indices", default="0,2,6")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--deadline-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.deadline_seconds < 1:
        parser.error("deadline must be positive")
    if Path(args.checkpoint).suffix == ".npz":
        class BlockTorch:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "torch" or fullname.startswith("torch."):
                    raise RuntimeError("NumPy serving imported Torch")
        sys.meta_path.insert(0, BlockTorch())
    def expired(*_):
        raise TimeoutError("bounded serving measurement expired")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.deadline_seconds)
    from shengji.ai.registry import register_cwv_shortlist_policies, make_bot
    from shengji.api.server import _fast_active
    from shengji.luna.game import _round_from_snapshot, _state_snapshot
    started = time.perf_counter()
    names = register_cwv_shortlist_policies(args.checkpoint, [32], batch_size=args.batch_size)
    raw = Path(args.states).read_bytes()
    states = json.loads(raw)
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    print(json.dumps({"kind": "start", "platform": platform.platform(),
                      "python": platform.python_version(), "native_engine": _fast_active(),
                      "states_sha256": hashlib.sha256(raw).hexdigest(),
                      "policy": names[0], "scope": "saved-state serving only"}), flush=True)
    for index in map(int, args.indices.split(",")):
        bot = make_bot(names[0], seed=89260904 + index)
        rnd = _round_from_snapshot(states[index])
        before = digest(_state_snapshot(rnd))
        clone_started = time.perf_counter()
        clone = copy.deepcopy(bot)
        snapshot_wall_seconds = time.perf_counter() - clone_started
        wall, cpu = time.perf_counter(), time.process_time()
        played = clone.decide_play(rnd, rnd.turn)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        row = {"kind": "decision", "index": index, "played": played,
               "snapshot_wall_seconds": snapshot_wall_seconds,
               "wall_seconds": time.perf_counter() - wall,
               "cpu_seconds": time.process_time() - cpu,
               "peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
               "legal_count": (clone.last_shortlist or {}).get("legal_count"),
               "ranking_seconds": clone.shortlist_wall_seconds,
               "input_unchanged": before == digest(_state_snapshot(rnd)),
               "rng_sha256": digest(repr(clone.rng.getstate())),
               "report": (clone.last_decision_record or {}).get("report_fold"),
               "evaluator": clone.evaluator.identity()}
        print(json.dumps(row, sort_keys=True), flush=True)
        if not row["input_unchanged"]:
            raise RuntimeError("serving mutated caller round")
    print(json.dumps({"kind": "complete", "wall_seconds": time.perf_counter() - started,
                      "torch_loaded": "torch" in sys.modules}), flush=True)
    signal.alarm(0)


if __name__ == "__main__":
    main()
