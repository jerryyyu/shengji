"""Score human play decisions in a game log against the bot's choices.

For every human play, the position is reconstructed exactly (logs contain the
full deck), the current MCBot proposes its move, and both moves are valued
over the same sampled opponent-hand worlds. Reports agreement, average value
lost, and the biggest deviations.

Usage:  uv run python scripts/analyze_human.py ../logs/RCLX.jsonl [worlds]
"""

import json
import random
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine.round import Round  # noqa: E402

SYM = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}


def pretty(cards):
    return "+".join(SYM.get(c[0], "") + c[1:] if c not in ("BJ", "LJ") else c
                    for c in cards)


def rebuild_and_analyze(path: str, n_worlds: int) -> None:
    events = [json.loads(l) for l in open(path)]
    rounds = defaultdict(list)
    for e in events:
        rounds[e["round"]].append(e)
    mc = MCBot(seed=99)
    results = []

    for rno in sorted(rounds):
        evs = rounds[rno]
        rs = next((e for e in evs if e["e"] == "round_start"), None)
        tr = next((e for e in evs if e["e"] == "trump"), None)
        bury = next((e for e in evs if e["e"] == "bury"), None)
        if not rs or not tr or not bury:
            continue  # incomplete round
        humans = {p["seat"] for p in rs["players"] if not p["is_bot"]}
        names = {p["seat"]: p["name"] for p in rs["players"]}
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

        trick_no = 0
        for e in evs:
            if e["e"] != "play" or rnd.phase != "play":
                continue
            seat, cards = e["seat"], e["cards"]
            if rnd.trick is not None and not rnd.trick.plays:
                trick_no += 1
            if seat in humans and rnd.turn == seat:
                bot_play = mc.decide_play(rnd, seat)
                if sorted(bot_play) != sorted(cards):
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
                        for i, play in enumerate((cards, bot_play)):
                            v = mc._rollout(rnd, seat, hands, buried, list(play))
                            vals[i] += v if i_att else -v
                    if n:
                        delta = (vals[1] - vals[0]) / n  # >0: bot's was better
                        results.append((delta, rno, trick_no, names[seat],
                                        cards, bot_play))
                else:
                    results.append((0.0, rno, trick_no, names[seat], cards, cards))
            rnd.play(seat, cards)

    if not results:
        print("no completed human decisions found")
        return
    agree = sum(1 for r in results if r[0] == 0.0 and r[4] == r[5])
    deltas = [r[0] for r in results]
    print(f"human decisions analyzed: {len(results)}")
    print(f"agreement with bot: {agree}/{len(results)} ({agree/len(results):.0%})")
    print(f"avg value vs bot's choice: {-sum(deltas)/len(deltas):+.1f} pts/decision "
          f"(negative = bot's picks were better on average)")
    worst = sorted(results, key=lambda r: -r[0])[:5]
    print("\nbiggest deviations (bot advantage in pts):")
    for delta, rno, tno, name, human, bot in worst:
        if delta <= 0:
            break
        print(f"  round {rno} trick {tno} [{name}]: played {pretty(human)}, "
              f"bot prefers {pretty(bot)}  (+{delta:.0f})")
    best = sorted(results, key=lambda r: r[0])[:3]
    print("\nhuman's best finds (human beat the bot's pick by pts):")
    for delta, rno, tno, name, human, bot in best:
        if delta >= 0:
            break
        print(f"  round {rno} trick {tno} [{name}]: played {pretty(human)}, "
              f"bot preferred {pretty(bot)}  ({-delta:.0f} better)")


if __name__ == "__main__":
    path = sys.argv[1]
    n_worlds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    rebuild_and_analyze(path, n_worlds)
