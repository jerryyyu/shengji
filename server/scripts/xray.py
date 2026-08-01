"""Bot X-ray: reconstruct a logged position and dump the bot's view of it.

Shows the acting seat's hand, everything Memory knows (voids, unseen cards,
boss status, ruff risks), every candidate play with its Monte Carlo value,
and which one the bot picks (with margin/point-shy reasoning) — next to what
was actually played in the log.

Usage:
  uv run python scripts/inspect.py ../logs/RCLX.jsonl <round> <trick> [play_idx] [worlds]
  play_idx: 0=lead (default) .. 3=last to act
"""

import json
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine.cards import SUITS, TRUMP  # noqa: E402
from shengji.engine.legal import suit_cards  # noqa: E402
from shengji.engine.round import Round  # noqa: E402

SYM = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", TRUMP: "T"}


def pretty(cards):
    return " ".join(SYM.get(c[0], "") + c[1:] if c not in ("BJ", "LJ") else c
                    for c in cards)


def main() -> None:
    path, rno, tno = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    play_idx = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    n_worlds = int(sys.argv[5]) if len(sys.argv) > 5 else 60

    events = [json.loads(l) for l in open(path)]
    evs = [e for e in events if e["round"] == rno]
    rs = next(e for e in evs if e["e"] == "round_start")
    tr = next(e for e in evs if e["e"] == "trump")
    bury = next(e for e in evs if e["e"] == "bury")
    names = {p["seat"]: p["name"] + (" [bot]" if p["is_bot"] else "")
             for p in rs["players"]}

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
    logged_play = None
    for e in evs:
        if e["e"] != "play" or rnd.phase != "play":
            continue
        if rnd.trick is not None and not rnd.trick.plays:
            trick_no += 1
        in_trick = len(rnd.trick.plays) if rnd.trick else 0
        if trick_no == tno and in_trick == play_idx:
            logged_play = e
            break
        rnd.play(e["seat"], e["cards"])

    seat = rnd.turn
    assert seat is not None
    o = rnd.ordering
    mem = Memory(rnd, seat)

    label = "NT" if rnd.trump_is_nt else rnd.trump_suit
    print(f"=== {path.split('/')[-1]} round {rno}, trick {tno}, "
          f"play {play_idx}: {names[seat]} to act ===")
    print(f"trump {label}{rnd.trump_rank}  banker {names[tr['banker']]}  "
          f"attacker pts {rnd.attacker_points}  "
          f"{'ATTACKER' if rnd.is_attacker(seat) else 'BANKER TEAM'}")
    if rnd.trick and rnd.trick.plays:
        print("trick so far: " + "  |  ".join(
            f"{names[p.seat]}: {pretty(p.cards)}" for p in rnd.trick.plays))
    hand = sorted(rnd.hands[seat], key=o.sort_key)
    print(f"\nhand ({len(hand)}): {pretty(hand)}")

    print("\n--- memory ---")
    for s in range(4):
        if s == seat:
            continue
        v = sorted(mem.voids[s])
        print(f"  {names[s]:16s} voids: "
              f"{' '.join(SYM.get(x, x) for x in v) if v else '(none shown)'}")
    print(f"  unseen trumps: {mem.unseen_trumps()}")
    for eff in list(SUITS) + [TRUMP]:
        left = sorted((c for c in mem.unseen.elements()
                       if o.eff_suit(c) == eff), key=o.level, reverse=True)
        if left:
            print(f"  unseen {SYM[eff]}: {pretty(left[:8])}"
                  f"{' …' if len(left) > 8 else ''}")
    boss = [c for c in dict.fromkeys(hand) if mem.is_boss(c)]
    print(f"  my BOSS cards: {pretty(boss) if boss else '(none)'}")
    opps = [s for s in range(4) if s % 2 != seat % 2]
    risky = [s for s in SUITS if suit_cards(hand, s, o) and mem.ruff_risk(s, opps)]
    print(f"  ruff-risky suits to lead: "
          f"{' '.join(SYM[s] for s in risky) if risky else '(none)'}")

    print(f"\n--- candidates ({n_worlds} sampled worlds; "
          f"{'higher' if rnd.is_attacker(seat) else 'lower'} attacker-pts is "
          f"better for this seat) ---")
    mc = MCBot(seed=42)
    cands = mc._candidates(rnd, seat)
    totals = [0.0] * len(cands)
    n = 0
    for _ in range(n_worlds):
        smp = mc._sample_hands(rnd, seat, mem)
        if smp is None:
            continue
        n += 1
        hands_s, buried = smp
        for i, c in enumerate(cands):
            totals[i] += mc._rollout(rnd, seat, hands_s, buried, list(c))
    pick = mc.decide_play(rnd, seat)
    order = sorted(range(len(cands)),
                   key=lambda i: totals[i], reverse=rnd.is_attacker(seat))
    for i in order:
        tags = []
        if i == 0:
            tags.append("heuristic pick")
        if sorted(cands[i]) == sorted(pick):
            tags.append("BOT PLAYS")
        print(f"  {pretty(cands[i]):22s} attackers avg {totals[i]/n:6.1f}"
              f"   {' '.join(tags)}")
    if logged_play:
        print(f"\nactually played in log: {pretty(logged_play['cards'])} "
              f"({'bot' if logged_play.get('bot') else 'human'})")


if __name__ == "__main__":
    main()
