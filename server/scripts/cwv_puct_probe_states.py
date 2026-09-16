"""Outcome-blind diagnostic roots, not a gameplay/held-out evaluation population."""
import argparse
import json
import random
from pathlib import Path

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.luna.game import _state_snapshot


def snapshots(seeds=(19, 41, 65), hand_limits=(25, 12, 6, 3)):
    if not seeds or not hand_limits or any(not 1 <= n <= 25 for n in hand_limits):
        raise ValueError("seeds and hand limits 1..25 required")
    if list(hand_limits) != sorted(set(hand_limits), reverse=True):
        raise ValueError("hand limits must be unique and descending")
    rows = []
    for seed in seeds:
        rnd = Game(random.Random(seed)).start_round()
        smart, heuristic = SmartBot(), HeuristicBot()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = smart.decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
        for seat in range(4):
            cards = smart.decide_declare(rnd, seat, final=True)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))
        for limit in hand_limits:
            while rnd.phase == "play" and max(map(len, rnd.hands)) > limit:
                rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
            if rnd.phase != "play":
                break
            rows.append(_state_snapshot(rnd))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[19, 41, 65])
    args = parser.parse_args()
    rows = snapshots(args.seeds)
    # Exclusive creation prevents silently changing a frozen diagnostic set.
    with args.out.open("x") as stream:
        json.dump(rows, stream, sort_keys=True)
    print(f"saved {len(rows)} roots; heuristic paths, diagnostic only")


if __name__ == "__main__":
    main()
