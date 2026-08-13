"""P1: feed-rate of the rollout policy inside MC worlds vs humans.
P2: points_left() at the DECLINE-END census states."""
import copy, sys
from collections import Counter
sys.path.insert(0, "server")
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.cards import points
from shengji.engine.legal import beats
from shengji.rl.replay_log import iter_human_decisions

LOGS = "logs/*.jsonl"  # run from repo root
tally = Counter()

class CountingHeuristic(HeuristicBot):
    def _follow(self, rnd, seat):
        action = super()._follow(rnd, seat)
        t = rnd.trick
        if t is not None and 0 < len(t.plays) < 3:
            win_seat, _, _ = self._current_winner(rnd)
            if win_seat % 2 == seat % 2 and any(points(c) for c in rnd.hands[seat]):
                tally["opportunities"] += 1
                if sum(points(c) for c in action) > 0:
                    tally["fed"] += 1
        return action

smart = make_bot("smart")
Base = type(make_bot("mc-s0-report-lcb", seed=0))
decline_pl, states_p1 = [], []
i = 0
for rnd, seat, human in iter_human_decisions([LOGS]):
    i += 1
    t = rnd.trick
    # P2 collection: DECLINE-END (opp winning, low pts, endgame, human declines win)
    if t is not None and t.plays and len(rnd.hands[seat]) <= 8:
        try:
            b = smart.decide_play(copy.deepcopy(rnd), seat)
        except Exception:
            continue
        if sorted(human) != sorted(b):
            o, lead = rnd.ordering, t.plays[0].cards
            win_seat, inc_suit, inc_top = smart._current_winner(rnd)
            if win_seat % 2 != seat % 2:
                tpts = sum(points(c) for tp in t.plays for c in tp.cards)
                hw = beats(human, lead, inc_suit, inc_top, o)[0]
                bw = beats(b, lead, inc_suit, inc_top, o)[0]
                if bw and not hw and tpts < 10:
                    mem = Memory(rnd, seat)
                    decline_pl.append(mem.points_left())
    # P1 collection: every ~150th contested mid-round state
    if i % 150 == 0 and t is not None and t.plays and len(states_p1) < 12:
        states_p1.append((copy.deepcopy(rnd), seat))

print(f"P2 DECLINE-END n={len(decline_pl)} points_left distribution:")
buckets = Counter("0" if p == 0 else "1-15" if p <= 15 else "16-40" if p <= 40 else ">40"
                  for p in decline_pl)
print("  ", dict(buckets), " median:", sorted(decline_pl)[len(decline_pl)//2] if decline_pl else None)

for k, (rnd, seat) in enumerate(states_p1):
    bot = Base(seed=7000 + k)
    bot.rollout_policy = CountingHeuristic()
    try:
        bot.decide_play(copy.deepcopy(rnd), seat)
    except Exception:
        continue
print(f"P1 rollout-policy feed rate inside MC worlds: fed={tally['fed']} / "
      f"opportunities={tally['opportunities']} "
      f"({100*tally['fed']/max(1,tally['opportunities']):.1f}%)  [human: 55% fed, 82% hold]")
