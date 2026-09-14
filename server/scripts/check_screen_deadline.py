"""Bounded saved-state parity/overhead and wide-tail cancellation qualification."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import time

from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.luna.game import _round_from_snapshot
from shengji.train.cwv_shortlist_screen import _deadline_side
from shengji.train.screen_deadline import DeadlineSession
from shengji.train.search_screen import _publish


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if "secs" not in k and "seconds" not in k}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--wide-snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("qualification output already exists")
    config = {"arm": "learned", "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        "encoding": "mlp-static", "reuse_successors": True, "report_worlds": 300,
        "shortlist": {"worlds": 32, "selection_worlds": 30, "alternatives": 4,
                      "batch_size": 128, "uniform": False}}
    rnd = prepare_round(Game(random.Random(431)), [HeuristicBot() for _ in range(4)])
    session = DeadlineSession(_deadline_side)
    result = {"config": config, "pairs": []}
    try:
        started = time.monotonic()
        remote = session.register(config, "arm", 713)
        result["worker_startup_seconds"] = time.monotonic() - started
        direct = _deadline_side(config, "arm", 713)
        for index in range(4):  # first pair warmup, then alternating A/B order
            values, walls = {}, {}
            for name, bot in (("direct", direct), ("supervised", remote))[::1 if index % 2 == 0 else -1]:
                started = time.monotonic()
                values[name] = bot.decide_play(copy.deepcopy(rnd), rnd.turn)
                walls[name] = time.monotonic() - started
            assert values["direct"] == values["supervised"]
            assert direct.rng.getstate() == remote.rng.getstate()
            assert stable(direct.last_decision_record) == stable(remote.last_decision_record)
            assert direct.rollouts == remote.rollouts
            result["pairs"].append({"warmup": index == 0, "wall_seconds": walls,
                                    "action": values["direct"], "parity": True})
        snapshot = json.loads(args.wide_snapshot.read_text())["snapshot"]
        wide = _round_from_snapshot(snapshot["state"])
        session.seconds = 2  # short deliberate timeout, not a scientific result
        started = time.monotonic()
        action = remote.decide_play(wide, wide.turn)
        result["wide_cancellation"] = {"elapsed_seconds": time.monotonic() - started,
            "seed": snapshot["seed"], "receipt": remote.decisions[-1]}
        assert remote.decisions[-1]["deadline"]["timed_out"]
        assert session.process is None
        wide.play(wide.turn, action)
        result["wide_cancellation"]["fallback_accepted"] = True
        session.seconds = 300
        remote.decide_play(copy.deepcopy(rnd), rnd.turn)
        assert not remote.decisions[-1]["deadline"]["timed_out"]
        result["restart_completed"] = True
        _publish(args.out, result)
        print(json.dumps(result, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
