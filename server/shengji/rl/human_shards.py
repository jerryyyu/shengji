"""Convert logged human game decisions into RL training shards.

Every genuinely-human play (per-play bot flag; test-script seats excluded)
becomes a (obs, actions, chosen, return) sample in the standard .npz
format — usable for fine-tuning or replay mixing. The pool grows with
every game played on the site.

Usage:  uv run python -m shengji.rl.human_shards "../logs/*.jsonl" rl_data/human
"""

from __future__ import annotations

import glob
import sys

from .actions import enumerate_actions
from .bc_generate import round_value
from .dataset import Decision, TrajectoryWriter
from .encode import encode_action, encode_obs
from .replay_log import EXCLUDE_PLAYERS, group_rounds, rebuild_round


def main() -> None:
    paths = []
    for arg in sys.argv[1:-1]:
        paths.extend(glob.glob(arg))
    out_dir = sys.argv[-1]
    writer = TrajectoryWriter(out_dir)
    n_dec = n_rounds = 0
    for path in paths:
        for rno, evs in sorted(group_rounds(path).items()):
            end = next((e for e in evs if e["e"] == "round_end"), None)
            if end is None:
                continue  # need the outcome to label returns
            try:
                rnd = rebuild_round(evs)
                if rnd is None:
                    continue
                rs = next(e for e in evs if e["e"] == "round_start")
                excluded = {p["seat"] for p in rs["players"]
                            if p["name"] in EXCLUDE_PLAYERS}
                val = round_value(end["attacker_points"])
                decisions = []
                for e in evs:
                    if e["e"] != "play" or rnd.phase != "play":
                        continue
                    seat, cards = e["seat"], e["cards"]
                    if (e.get("bot") is False and rnd.turn == seat
                            and seat not in excluded):
                        actions = enumerate_actions(rnd, seat,
                                                    exhaustive_follows=True)
                        key = sorted(cards)
                        chosen = next((i for i, a in enumerate(actions)
                                       if sorted(a) == key), None)
                        if chosen is None:
                            actions.append(cards)
                            chosen = len(actions) - 1
                        decisions.append(Decision(
                            obs=encode_obs(rnd, seat),
                            actions=[encode_action(a, rnd) for a in actions],
                            chosen=chosen, seat=seat,
                            ret=val if rnd.is_attacker(seat) else -val))
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
