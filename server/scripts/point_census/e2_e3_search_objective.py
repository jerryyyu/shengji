"""E2: production MC vs human on E1's disagreement classes.
E3: LEVEL_OBJECTIVE flip census on the same states (same seed => same worlds)."""
import copy, json, sys
from collections import Counter, defaultdict
sys.path.insert(0, "server")
from shengji.ai.registry import make_bot
from shengji.engine.cards import points
from shengji.engine.legal import beats
from shengji.rl.replay_log import iter_human_decisions

LOGS = "logs/*.jsonl"  # run from repo root
smart = make_bot("smart")
CAP = 40

def classify(rnd, seat, human, b):
    t = rnd.trick
    hpts, bpts = sum(points(c) for c in human), sum(points(c) for c in b)
    if t is None or not t.plays:
        if (hpts > 0) != (bpts > 0):
            return "LEAD-POINT-SPLIT"
        return None
    o, lead = rnd.ordering, t.plays[0].cards
    win_seat, inc_suit, inc_top = smart._current_winner(rnd)
    partner = win_seat % 2 == seat % 2
    tpts = sum(points(c) for tp in t.plays for c in tp.cards)
    is_last = len(t.plays) == 3
    if partner:
        if hpts > bpts and not is_last: return "FEED-EARLIER"
        if hpts < bpts and is_last: return "BANK-AT-LAST"
        return None
    hw = beats(human, lead, inc_suit, inc_top, o)[0]
    bw = beats(b, lead, inc_suit, inc_top, o)[0]
    if hw and not bw and tpts < 10: return "CONTEST-LOW"
    if bw and not hw and tpts < 10 and len(rnd.hands[seat]) <= 8:
        return "DECLINE-END"
    return None

# pass 1: collect
per = defaultdict(list); control = []; endgame = []
i = 0
for rnd, seat, human in iter_human_decisions([LOGS]):
    i += 1
    try:
        b = smart.decide_play(copy.deepcopy(rnd), seat)
    except Exception:
        continue
    same = sorted(human) == sorted(b)
    cls = None if same else classify(rnd, seat, human, b)
    if cls and len(per[cls]) < CAP:
        per[cls].append((copy.deepcopy(rnd), seat, human, b))
    if i % 60 == 0 and len(control) < 30:
        control.append((copy.deepcopy(rnd), seat, human, b))
    if len(rnd.hands[seat]) <= 8 and i % 7 == 0 and len(endgame) < CAP:
        endgame.append((copy.deepcopy(rnd), seat, human, b))
per["CONTROL"] = control
per["ENDGAME-ALL"] = endgame
print({k: len(v) for k, v in per.items()}, flush=True)

Base = type(make_bot("mc-s0-report-lcb", seed=0))
Level = type("Level", (Base,), {"LEVEL_OBJECTIVE": True})

out = {}
k_i = 0
for cls, states in per.items():
    mc_h = mc_s = mc_other = flips = flip_to_h = n = 0
    for j, (rnd, seat, human, b) in enumerate(states):
        k_i += 1
        seed = 90_000 + k_i
        try:
            a_mc = Base(seed=seed).decide_play(copy.deepcopy(rnd), seat)
            a_lv = Level(seed=seed).decide_play(copy.deepcopy(rnd), seat)
        except Exception:
            continue
        n += 1
        if sorted(a_mc) == sorted(human): mc_h += 1
        elif sorted(a_mc) == sorted(b): mc_s += 1
        else: mc_other += 1
        if sorted(a_lv) != sorted(a_mc):
            flips += 1
            if sorted(a_lv) == sorted(human): flip_to_h += 1
    out[cls] = dict(n=n, mc_matches_human=mc_h, mc_matches_smart=mc_s,
                    mc_other=mc_other, level_flips=flips, flips_to_human=flip_to_h)
    print(cls, out[cls], flush=True)
json.dump(out, open("point_census_e2e3.json", "w"), indent=1)
