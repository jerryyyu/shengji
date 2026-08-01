"""Convert logged human game decisions into RL training shards.

Every genuinely-human play (per-play bot flag) becomes a (obs, actions,
chosen, return) sample in the same .npz format as bc_generate — usable as
BC/fine-tuning data or mixed into a replay buffer. The pool grows with
every game played on the site.

Usage:  uv run python -m shengji.rl.human_shards "../logs/*.jsonl" rl_data/human
"""

from __future__ import annotations

import glob
import json
import random
import sys
from collections import defaultdict

from ..engine.round import Round
from .actions import enumerate_actions
from .bc_generate import round_value
from .dataset import Decision, TrajectoryWriter
from .encode import encode_action, encode_obs


def main() -> None:
    paths = []
    for arg in sys.argv[1:-1]:
        paths.extend(glob.glob(arg))
    out_dir = sys.argv[-1]
    writer = TrajectoryWriter(out_dir)
    n_dec = n_rounds = 0
    for path in paths:
        events = [json.loads(l) for l in open(path)]
        by_round = defaultdict(list)
        for e in events:
            by_round[e["round"]].append(e)
        for rno, evs in sorted(by_round.items()):
            rs = next((e for e in evs if e["e"] == "round_start"), None)
            tr = next((e for e in evs if e["e"] == "trump"), None)
            bury = next((e for e in evs if e["e"] == "bury"), None)
            end = next((e for e in evs if e["e"] == "round_end"), None)
            if not rs or not tr or not bury or not end:
                continue  # need the outcome to label returns
            try:
                rnd = Round(rs["trump_rank"], rs["banker"], random.Random(0))
                rnd.deck = rs["deck"]
                rnd.hands = [[], [], [], []]
                rnd._deal_pos = 0
                rnd.phase = "deal"
                rnd.kitty = rs["deck"][100:]
                while rnd.phase == "deal":
                    rnd.deal_next()
                for e in evs:
                    if e["e"] == "declare":
                        rnd.declare(e["seat"], e["cards"])
                rnd.finalize_declare()
                rnd.bury(tr["banker"], bury["cards"])
                val = round_value(end["attacker_points"])
                decisions = []
                for e in evs:
                    if e["e"] != "play" or rnd.phase != "play":
                        continue
                    seat, cards = e["seat"], e["cards"]
                    if e.get("bot") is False and rnd.turn == seat:
                        actions = enumerate_actions(rnd, seat)
                        key = sorted(cards)
                        chosen = next((i for i, a in enumerate(actions)
                                       if sorted(a) == key), None)
                        if chosen is None:
                            actions.append(cards)
                            chosen = len(actions) - 1
                        d = Decision(
                            obs=encode_obs(rnd, seat),
                            actions=[encode_action(a, rnd) for a in actions],
                            chosen=chosen, seat=seat,
                            ret=val if rnd.is_attacker(seat) else -val)
                        decisions.append(d)
                    rnd.play(seat, cards)
                for d in decisions:
                    writer.add(d)
                n_dec += len(decisions)
                n_rounds += 1
            except Exception:
                continue
    writer.flush()
    print(f"{n_dec} human decisions from {n_rounds} completed rounds -> {out_dir}")


if __name__ == "__main__":
    main()
