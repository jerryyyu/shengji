"""E1: human-vs-SmartBot disagreement census with a point taxonomy."""
import copy, json, sys
from collections import Counter, defaultdict
sys.path.insert(0, "server")
from shengji.ai.registry import make_bot
from shengji.engine.cards import points, total_points
from shengji.engine.legal import beats
from shengji.rl.replay_log import iter_human_decisions

LOGS = "logs/*.jsonl"  # run from repo root
bot = make_bot("smart")

n = agree = 0
cls = Counter()
ctx_all = Counter()
examples = defaultdict(list)
for rnd, seat, human in iter_human_decisions([LOGS]):
    t = rnd.trick
    is_lead = t is None or not t.plays
    try:
        b = bot.decide_play(copy.deepcopy(rnd), seat)
    except Exception:
        continue
    n += 1
    hpts, bpts = sum(points(c) for c in human), sum(points(c) for c in b)
    same = sorted(human) == sorted(b)
    if same:
        agree += 1
    ap = rnd.attacker_points
    hand_n = len(rnd.hands[seat])
    phase = "end" if hand_n <= 8 else ("mid" if hand_n <= 17 else "early")
    key = None
    if is_lead:
        ctx_all["lead"] += 1
        if (hpts > 0) != (bpts > 0):
            key = f"LEAD point-card human={hpts>0}"
    else:
        o = rnd.ordering
        lead = t.plays[0].cards
        win_seat, inc_suit, inc_top = bot._current_winner(rnd)
        partner = win_seat % 2 == seat % 2
        tpts = sum(points(c) for tp in t.plays for c in tp.cards)
        is_last = len(t.plays) == 3
        ctx_all["follow-partner" if partner else "follow-opp"] += 1
        if partner:
            if hpts != bpts:
                key = (f"FEED h{'>' if hpts>bpts else '<'}b "
                       f"last={is_last}")
        else:
            hw = beats(human, lead, inc_suit, inc_top, o)[0]
            bw = beats(b, lead, inc_suit, inc_top, o)[0]
            if hw != bw:
                key = f"CONTEST human_win={hw} tpts{'>=10' if tpts>=10 else '<10'} last={is_last}"
            elif not hw and hpts != bpts:
                key = f"LOSING-DISCARD h{'>' if hpts>bpts else '<'}b"
    if key and not same:
        cls[(key, phase)] += 1
        if len(examples[key]) < 4:
            examples[key].append({"seat": seat, "human": human, "bot": b,
                                  "ap": ap, "hand_n": hand_n})
print(f"decisions={n} exact-agree={agree} ({100*agree/n:.1f}%)  contexts={dict(ctx_all)}")
merged = Counter()
for (k, ph), v in cls.items():
    merged[k] += v
for k, v in merged.most_common(14):
    by_ph = {ph: c for (kk, ph), c in cls.items() if kk == k}
    print(f"{v:5d}  {k}   phases={by_ph}")
json.dump({k: examples[k] for k in examples}, open(
    "point_census_e1_examples.json", "w"), indent=1)
