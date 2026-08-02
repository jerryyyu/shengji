"""Mine human-vs-bot disagreements for learnable patterns.

For every logged human decision where current SmartBot disagrees:
categorize (lead/follow, role, round stage, play shapes chosen by each
side), value both choices over shared sampled worlds, and aggregate per
category: who's right, by how much, how often. Categories where humans
systematically win = candidate heuristics (the data-driven version of
the AKK/control-leads finds).

Usage: uv run python scripts/mine_disagreements.py "../logs/*.jsonl" [worlds]
"""

import glob
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
from eval_vs_human import iter_human_decisions  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.cards import TRUMP, points  # noqa: E402

EXCLUDE_PLAYERS = {"Smoke"}  # test scripts are not humans


def play_shape(cards, rnd):
    o = rnd.ordering
    n = len(cards)
    cnt = Counter(cards)
    all_trump = all(o.eff_suit(c) == TRUMP for c in cards)
    pairs = sum(v // 2 for v in cnt.values())
    pts = sum(points(c) for c in cards)
    if n == 1:
        c = cards[0]
        base = "trump" if all_trump else (
            "high" if o.level(c) >= len(o.plain_ranks) - 4 else "low")
        return f"single-{base}" + ("-pts" if pts else "")
    if pairs * 2 == n:
        kind = "tractor" if pairs >= 2 else "pair"
        return kind + ("-trump" if all_trump else "")
    return "throw/mixed" + ("-trump" if all_trump else "")


def main():
    paths = []
    for a in sys.argv[1:-1] or sys.argv[1:]:
        paths.extend(glob.glob(a))
    n_worlds = int(sys.argv[-1]) if sys.argv[-1].isdigit() else 24

    smart = SmartBot()
    mc = MCBot(seed=77)
    cats = defaultdict(lambda: [0, 0.0, 0])  # count, sum_delta, human_better
    examples = defaultdict(list)
    n_seen = n_dis = 0
    for rnd, seat, human in iter_human_decisions(paths):
        n_seen += 1
        try:
            bot = smart.decide_play(rnd, seat)
        except Exception:
            continue
        if sorted(bot) == sorted(human):
            continue
        n_dis += 1
        is_lead = not rnd.trick.plays
        stage = "early" if sum(len(h) for h in rnd.hands) > 60 else "late"
        cat = (f"{'lead' if is_lead else 'follow'}/{stage}: "
               f"human={play_shape(human, rnd)} bot={play_shape(bot, rnd)}")
        # value both over shared worlds
        mem = Memory(rnd, seat)
        i_att = rnd.is_attacker(seat)
        vals = [0.0, 0.0]
        n = 0
        for _ in range(n_worlds):
            s = mc._sample_hands(rnd, seat, mem)
            if s is None:
                continue
            n += 1
            hands, buried = s
            for i, play in enumerate((human, bot)):
                v = mc._rollout(rnd, seat, hands, buried, list(play))
                vals[i] += v if i_att else -v
        if not n:
            continue
        delta = (vals[0] - vals[1]) / n  # >0 = human better
        c = cats[cat]
        c[0] += 1
        c[1] += delta
        c[2] += int(delta > 2)
        if len(examples[cat]) < 2 and abs(delta) > 4:
            examples[cat].append((human, bot, round(delta, 1)))

    print(f"{n_seen} human decisions, {n_dis} disagreements with SmartBot\n")
    rows = [(c, v[0], v[1] / v[0], v[2] / v[0]) for c, v in cats.items()
            if v[0] >= 5]
    print("=== categories where HUMANS beat the bot (mean pts/decision) ===")
    for cat, cnt, mean, share in sorted(rows, key=lambda r: -r[2])[:10]:
        print(f"  {mean:+5.1f}  n={cnt:3d}  human-better {share:.0%}  {cat}")
        for h, b, d in examples[cat]:
            print(f"          e.g. human={h} bot={b} ({d:+.1f})")
    print("\n=== categories where the BOT beats humans ===")
    for cat, cnt, mean, share in sorted(rows, key=lambda r: r[2])[:6]:
        print(f"  {mean:+5.1f}  n={cnt:3d}  human-better {share:.0%}  {cat}")


if __name__ == "__main__":
    main()
