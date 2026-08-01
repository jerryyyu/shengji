"""Pretty-print a room's game log (logs/<ROOM>.jsonl) as a readable transcript.

Usage:
    uv run python scripts/replay.py ../logs/ABCD.jsonl [round_no]
"""

import json
import sys

SYM = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}


def pretty(code: str) -> str:
    if code == "BJ":
        return "BJo"
    if code == "LJ":
        return "LJo"
    return SYM.get(code[0], code[0]) + code[1:]


def cards(cs) -> str:
    return " ".join(pretty(c) for c in cs)


def main() -> None:
    path = sys.argv[1]
    only_round = int(sys.argv[2]) if len(sys.argv) > 2 else None
    names = {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if only_round is not None and rec.get("round") != only_round:
                continue
            e = rec["e"]
            if e == "round_start":
                names = {p["seat"]: p["name"] + (" [bot]" if p["is_bot"] else "")
                         for p in rec["players"]}
                deck = rec["deck"]
                print(f"\n=== Round {rec['round']} — levels {rec['levels']}, "
                      f"trump rank {rec['trump_rank']}, "
                      f"banker {rec['banker']} ===")
                for s in range(4):
                    hand = sorted(deck[s:100:4])
                    print(f"  {names.get(s, s)}: {cards(hand)}")
                print(f"  kitty: {cards(deck[100:])}")
            elif e == "declare":
                who = "bot" if rec.get("bot") else "human"
                print(f"  DECLARE {names.get(rec['seat'], rec['seat'])} "
                      f"({who}): {cards(rec['cards'])}")
            elif e == "trump":
                print(f"  TRUMP: {rec['suit']}{rec['rank']} "
                      f"(banker {rec['banker']}, "
                      f"{'declared' if rec['declared'] else 'flipped'})")
            elif e == "bury":
                print(f"  BURY {names.get(rec['seat'], rec['seat'])}: "
                      f"{cards(rec['cards'])}")
            elif e == "trick":
                plays = "  |  ".join(
                    f"{names.get(p['seat'], p['seat'])}: {cards(p['cards'])}"
                    for p in rec["plays"])
                print(f"  {plays}   -> {names.get(rec['winner'], rec['winner'])}"
                      f" (+{rec['points']})")
            elif e == "round_end":
                print(f"  RESULT: attackers {rec['attacker_points']} "
                      f"(kitty {cards(rec['kitty'])} = +{rec['kitty_points']}), "
                      f"team {rec['winner_team']} wins +{rec['level_change']}, "
                      f"levels {rec['new_levels']}, next banker "
                      f"{rec['next_banker']}"
                      + (", GAME OVER" if rec["game_over"] else ""))


if __name__ == "__main__":
    main()
