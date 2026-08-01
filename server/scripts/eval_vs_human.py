"""Human-decision validation set: how often does each policy agree with the
humans across ALL logged games?

Every genuinely-human play (per-play bot flag, so watchdog takeovers are
excluded) is a validation item: reconstruct the position, ask the policy
what it would play, count agreement.

Usage:
  uv run python scripts/eval_vs_human.py ../logs/*.jsonl
  SHENGJI_RL_CKPT=ckpt_bc.pt uv run python scripts/eval_vs_human.py ../logs/*.jsonl
"""

import glob
import json
import os
import random
import sys

sys.path.insert(0, ".")
from shengji.ai.registry import REGISTRY  # noqa: E402
from shengji.engine.round import Round  # noqa: E402


def iter_human_decisions(paths):
    """Yield (rnd, seat, human_cards) at each genuine human decision."""
    for path in paths:
        events = [json.loads(l) for l in open(path)]
        by_round = {}
        for e in events:
            by_round.setdefault(e["round"], []).append(e)
        for rno, evs in sorted(by_round.items()):
            rs = next((e for e in evs if e["e"] == "round_start"), None)
            tr = next((e for e in evs if e["e"] == "trump"), None)
            bury = next((e for e in evs if e["e"] == "bury"), None)
            if not rs or not tr or not bury:
                continue
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
                for e in evs:
                    if e["e"] != "play" or rnd.phase != "play":
                        continue
                    if e.get("bot") is False and rnd.turn == e["seat"]:
                        yield rnd, e["seat"], e["cards"]
                    rnd.play(e["seat"], e["cards"])
            except Exception:
                continue  # partial/corrupt round


def main() -> None:
    paths = []
    for arg in sys.argv[1:]:
        paths.extend(glob.glob(arg))
    names = ["heuristic", "smart", "mc"]
    if os.environ.get("SHENGJI_RL_CKPT"):
        names.append("rl")
    for name in names:
        bot = REGISTRY[name]()
        agree = total = 0
        for rnd, seat, human_cards in iter_human_decisions(paths):
            try:
                pick = bot.decide_play(rnd, seat)
            except Exception:
                continue
            total += 1
            if sorted(pick) == sorted(human_cards):
                agree += 1
        print(f"{name:10s} agrees with human on {agree}/{total} "
              f"({agree/max(total,1):.0%})")


if __name__ == "__main__":
    main()
