"""Capture one reopened DEV position through current W32's actual ranker.

The saved hybrid-bury trajectory supplies a fixed public prefix. Its outcome
is never used to select a position. Full worlds stay in a private diagnostic
file; only the separate actor.json is sent to archived R4 inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np

from ..ai.cwv_policy import sample_worlds, shared_evaluator
from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from ..harvest.legal import enumerate_legal
from .cwv_bury_diagnostic import reopen_state, derived_seed
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from .search_screen import _publish


class RecordingEvaluator:
    """Retain real consumer outputs without altering its batches or arithmetic."""
    def __init__(self, delegate):
        self.delegate = delegate
        self.values = []

    def score(self, *args, **kwargs):
        values = self.delegate.score(*args, **kwargs)
        self.values.extend(float(x) for x in values)
        return values


def replay_consumer_means(matrix):
    """Match W32's sequential np.add.at, not NumPy's pairwise sum kernel."""
    values = np.asarray(matrix, dtype=np.float64)
    if values.ndim != 2 or not all(values.shape):
        raise ValueError("nonempty world/action matrix required")
    sums = np.zeros(values.shape[1], dtype=np.float64)
    np.add.at(sums, np.tile(np.arange(values.shape[1]), values.shape[0]), values.ravel())
    return sums / values.shape[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--archive-server", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--decision", type=int, default=1,
                        help="fixed prefix length, chosen before reading outcomes")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.decision < 0:
        parser.error("fresh output directory and nonnegative decision required")
    # Only the contract comes from archived source. Its Round and Memory imports
    # resolve to CURRENT engine classes. This process does not load R4 models.
    import shengji.rl
    shengji.rl.__path__.append(str(args.archive_server.resolve() / "shengji/rl"))
    from shengji.rl.belief_contract import build_actor_observation
    raw = args.record.read_bytes()
    row = json.loads(raw)
    rnd = reopen_state(row["state"])
    rnd.bury(rnd.banker, row["buried"])
    if args.decision >= len(row["transcript"]):
        parser.error("prefix must end at a live decision")
    for play in row["transcript"][:args.decision]:
        rnd.play(play["seat"], play["attempted"])
    seat = rnd.turn
    actor = build_actor_observation(rnd, seat)
    seed = derived_seed("r4-w32-shared-dev-20260910-v1", row["state"]["index"])
    evaluator = RecordingEvaluator(shared_evaluator(args.checkpoint, threads=1))
    bot = CWVShortlistBot(evaluator, seed=seed,
                         config=CWVShortlistConfig(worlds=32), reuse_successors=True)
    production = REGISTRY["mc-s0-report-lcb"](seed=seed)._candidates(rnd, seat)
    actions = enumerate_legal(rnd, seat, cap=None, must_include=production).actions
    incumbent = tuple(sorted(production[0]))
    world_seed = _child_seed(bot.rng.getstate(), "cwv-full-legal-worlds-v1")
    bot.rng = random.Random(world_seed)
    worlds, attempts = sample_worlds(bot, rnd, seat, 32)
    reference_bot = REGISTRY["mc-s0-report-lcb"](
        seed=derived_seed("r4-w32-independent-reference-v1", seed))
    reference, reference_attempts = sample_worlds(reference_bot, rnd, seat, 256)
    if len(worlds) != 32 or len(reference) != 256:
        raise ValueError("shared-world/reference sampling underfilled")
    started = time.monotonic()
    means = bot._means(rnd, seat, actions, worlds)
    matrix = np.asarray(evaluator.values).reshape(32, len(actions))
    if not np.array_equal(means, replay_consumer_means(matrix)):
        raise ValueError("captured matrix does not reproduce actual W32 means")
    result = {"schema": "r4-w32-rank-capture-dev-v1", "record_sha256": hashlib.sha256(raw).hexdigest(),
              "record_path": str(args.record.resolve()), "decision": args.decision,
              "actor_sha256": hashlib.sha256(actor.canonical_bytes()).hexdigest(),
              "seat": seat, "incumbent": list(incumbent), "world_seed": world_seed,
              "checkpoint_sha256": evaluator.delegate.checkpoint_sha256,
              "actions": [list(x) for x in actions], "means": means.tolist(),
              "values_world_major": matrix.tolist(), "worlds": worlds,
              "reference_worlds": reference, "sampling_attempts": attempts,
              "reference_attempts": reference_attempts,
              "ranking_wall_s": time.monotonic() - started,
              "contains_hidden_worlds": True, "contains_gameplay_outcome": False,
              "sampler": "unchanged-production", "scope": "DEV ranking diagnostic, not strength"}
    args.out.mkdir(parents=True)
    _publish(args.out / "actor.json", actor.to_dict())
    _publish(args.out / "private-world-values.json", result)
    print(json.dumps({k: result[k] for k in ("decision", "seat", "ranking_wall_s", "actor_sha256")}
                     | {"actions": len(actions)}, sort_keys=True))


if __name__ == "__main__":
    main()
