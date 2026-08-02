"""Human-decision validation set: how often does each policy agree with the
humans across ALL logged games?

Usage:
  uv run python scripts/eval_vs_human.py ../logs/*.jsonl
  SHENGJI_RL_CKPT=ckpt.pt uv run python scripts/eval_vs_human.py ../logs/*.jsonl
"""

import os
import sys

sys.path.insert(0, ".")
from shengji.ai.registry import REGISTRY  # noqa: E402
from shengji.rl.replay_log import iter_human_decisions  # noqa: E402


def main() -> None:
    names = ["heuristic", "smart", "mc"]
    if os.environ.get("SHENGJI_RL_CKPT"):
        names.append("rl")
    for name in names:
        bot = REGISTRY[name]()
        agree = total = 0
        for rnd, seat, human_cards in iter_human_decisions(sys.argv[1:]):
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
