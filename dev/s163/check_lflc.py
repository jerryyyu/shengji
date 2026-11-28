"""Check a Standard package against the paired LFLC public-history fixture.

Run with PYTHONPATH=server. Supply the original room JSONL and digest-pinned
package, plus --unified PATH SHA256 for a shared head. Neither deal labels a move.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from shengji.ai.belief_numpy import decision_inputs
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.unified_readout_numpy import load_unified_readout_numpy
from shengji.engine.round import actual_play_after
from shengji.rl.replay_log import rebuild_round
from shengji.train.relaxed_play import RECORD_SCHEMA, build_casual


def replay(events, alternate, bot):
    setup = deepcopy([e for e in events if e["e"] in ("round_start", "trump", "declare", "bury")])
    deck, = [e["deck"] for e in setup if e["e"] == "round_start"]
    kitty, = [e["cards"] for e in setup if e["e"] == "bury"]
    if (deck[58], deck[102]) != ("HJ", "HK") or "HK" not in kitty:
        raise ValueError("different LFLC setup")
    if alternate:
        deck[58], deck[102] = deck[102], deck[58]
        kitty[kitty.index("HK")] = "HJ"
    rnd = rebuild_round(setup)
    plays = [e for e in events if e["e"] == "play"]
    if rnd is None or len(plays) < 49:
        raise ValueError("incomplete LFLC replay")
    for e in plays[:48]:
        bot.observe_public(rnd)
        seat = rnd.turn
        if e["seat"] != seat:
            raise ValueError("replay actor differs")
        previous = rnd.last_trick
        rnd.play(seat, e.get("attempted_cards") or e["cards"])
        if sorted(actual_play_after(rnd, seat, previous)) != sorted(e["cards"]):
            raise ValueError("replay committed different cards")
    if (rnd.turn != 1 or len(rnd.history) != 12 or rnd.trick.plays or rnd.attacker_points != 55
            or sorted(rnd.hands[1]) != ["C4", "H5", "H5"]
            or plays[48]["seat"] != 1 or plays[48]["cards"] != ["H5", "H5"]):
        raise ValueError("different LFLC lead")
    bot.observe_public(rnd)
    return rnd


def evaluate(events, alternate, package, digest, trunk):
    base = HeuristicBot()
    if trunk is not None:
        base.unified_prior_model = trunk
    bot = build_casual(base, package, seed=21, sha256=digest)
    rnd = replay(events, alternate, bot)
    player = bot.player
    refusals = player._ledger.observe(rnd)
    inputs = decision_inputs(rnd, 1, refusals)
    anchor = player._heuristic.decide_play(rnd, 1)
    proposal, values, logits = player._scored_proposal(rnd, 1, anchor, refusals)
    actions = [tuple(sorted(a)) for a in proposal["actions"]]
    if sorted(actions) != [("C4",), ("H5",), ("H5", "H5")]:
        raise ValueError("unexpected legal ballot")
    if (np.shape(logits) != (3,) or np.shape(values) != (3,)
            or not np.isfinite(logits).all() or not np.isfinite(values).all()):
        raise ValueError("invalid package scores")
    played = tuple(sorted(bot.decide_play(rnd, 1)))
    if bot.last_decision_record["schema"] != RECORD_SCHEMA or played not in actions:
        raise ValueError("Standard decision failed")
    return inputs, dict(actions=actions, values=values.tolist(), logits=logits.tolist(), played=played)


def check(room, package, digest, unified=None):
    with room.open() as stream:
        events = [e for line in stream if (e := json.loads(line)).get("room") == "LFLC"
                  and e.get("round") == 3]
    trunk = load_unified_readout_numpy(*unified) if unified else None
    original, first = evaluate(events, False, package, digest, trunk)
    alternate, second = evaluate(events, True, package, digest, trunk)
    if original.keys() != alternate.keys() or any(
            not np.array_equal(original[k], alternate[k]) for k in original):
        raise ValueError("hidden swap changed player-visible inputs")
    if first != second:
        raise ValueError("hidden swap changed Standard scoring or play")
    return dict(package=digest, **first)


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
