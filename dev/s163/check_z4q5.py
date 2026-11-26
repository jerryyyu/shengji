"""Check a Standard candidate package's deterministic ranking at Z4Q5 round 8, trick 15.

Run with PYTHONPATH=server; supply the captured room JSONL, head NPZ and its SHA.
For a shared head, also pass --unified PATH SHA. Exit 1 means the model missed
the known preference; input and package errors produce an error message.
"""
import argparse
import json
import math
from pathlib import Path

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.unified_readout_numpy import load_unified_readout_numpy
from shengji.rl.replay_log import rebuild_round
from shengji.train.relaxed_play import build_casual


def check(room, package, digest, unified=None):
    with room.open() as stream:
        events = [e for line in stream if (e := json.loads(line)).get("round") == 8
                  and e.get("room") == "Z4Q5"]
    rnd = rebuild_round(events)
    if rnd is None:
        raise ValueError("missing Z4Q5 round 8 setup")
    base = HeuristicBot()
    if unified:
        base.unified_prior_model = load_unified_readout_numpy(*unified)
    player = build_casual(base, package, seed=21, sha256=digest).player
    for event in events:
        if event["e"] != "play":
            continue
        player.observe_public(rnd)
        if len(rnd.history) == 14 and len(rnd.trick.plays) == 3:
            if (rnd.turn != 1 or event["seat"] != 1 or event["cards"] != ["CK"]
                    or sorted(rnd.hands[1]) != ["C2", "CK"] or rnd.attacker_points != 70
                    or [p.cards for p in rnd.trick.plays] != [["HQ"], ["HA"], ["H9"]]
                    or (rnd.ordering.trump_suit, rnd.ordering.trump_rank) != ("C", "6")):
                raise ValueError("different endgame position")
            anchor = player._heuristic.decide_play(rnd, 1)
            proposal, _, logits = player._scored_proposal(rnd, 1, anchor, player._ledger.observe(rnd))
            if sorted(proposal["actions"]) != [["C2"], ["CK"]]:
                raise ValueError("candidate ballot differs from the two legal plays")
            scores = {card: float(logit) for (card,), logit in zip(proposal["actions"], logits, strict=True)}
            if not all(map(math.isfinite, scores.values())):
                raise ValueError("nonfinite candidate scores")
            return {"package": digest, "logits": scores, "prefers_C2": scores["C2"] > scores["CK"]}
        rnd.play(event["seat"], event.get("attempted_cards") or event["cards"])
    raise ValueError("missing endgame decision")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("sha256")
    parser.add_argument("--unified", nargs=2, metavar=("PATH", "SHA256"))
    args = parser.parse_args()
    try:
        result = check(args.room, args.package, args.sha256, args.unified)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(0 if result["prefers_C2"] else 1)
