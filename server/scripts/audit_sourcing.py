"""Sourcing audit: how many human plays are missing from the bot ballot?

Every human play in the logs is checked against the candidate enumerator.
A play the ballot lacks is a play no bot (search or net) can ever source —
the audit turns "what are we missing?" into a tracked coverage metric.

Usage:
  uv run python scripts/audit_sourcing.py "../logs/*.jsonl"        # v1 ballot
  uv run python scripts/audit_sourcing.py "../logs/*.jsonl" --v2   # widened

First run (2026-08-02, n=1052): v1 ballot missed 15.3% — lead throws 77%,
follow singles (discard selection) 21%, broken-structure follows 12-17%.
"""

import glob
import sys
from collections import Counter

sys.path.insert(0, ".")
from shengji.engine.combos import decompose  # noqa: E402
from shengji.rl.actions import enumerate_actions  # noqa: E402
from shengji.rl.replay_log import iter_human_decisions  # noqa: E402


def shape(cards, rnd) -> str:
    if len(cards) == 1:
        return "single"
    d = decompose(cards, rnd.ordering)
    if len(d.components) > 1:
        return f"throw({len(cards)})"
    pl = d.components[0].pair_len
    if pl >= 2:
        return f"tractor({len(cards)})"
    return "pair" if pl == 1 else f"multi({len(cards)})"


def main() -> None:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "../logs/*.jsonl"
    v2 = "--v2" in sys.argv
    miss: Counter = Counter()
    tot: Counter = Counter()
    for rnd, seat, cards in iter_human_decisions(glob.glob(pattern)):
        pos = "follow" if rnd.trick.plays else "lead"
        tot[(pos, shape(cards, rnd))] += 1
        ballot = enumerate_actions(rnd, seat,
                                   exhaustive_follows=v2, include_throws=v2)
        if sorted(cards) not in [sorted(a) for a in ballot]:
            miss[(pos, shape(cards, rnd))] += 1
    label = "v2 (exhaustive follows + lead throws)" if v2 else "v1 (play-time)"
    print(f"ballot {label} — human plays missing (miss/total):")
    for k in sorted(tot, key=lambda k: -miss[k]):
        if miss[k]:
            print(f"  {k[0]:6s} {k[1]:12s} {miss[k]}/{tot[k]}"
                  f" ({100 * miss[k] / tot[k]:.0f}%)")
    m, t = sum(miss.values()), sum(tot.values())
    print(f"  TOTAL missing: {m}/{t} ({100 * m / t:.1f}%)")


if __name__ == "__main__":
    main()
