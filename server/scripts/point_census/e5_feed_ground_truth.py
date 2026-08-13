"""E5: ground truth for human mid-trick feed decisions (partner currently winning)."""
import glob, json, sys
from collections import defaultdict
sys.path.insert(0, "server")
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import points
from shengji.rl.replay_log import group_rounds, rebuild_round, EXCLUDE_PLAYERS

hb = HeuristicBot()
agg = defaultdict(lambda: dict(n=0, held=0, pts_kept=0, pts_lost=0))
for path in glob.glob("logs/*.jsonl"):
    try:
        first = next((json.loads(l) for l in open(path)
                      if json.loads(l).get("e") == "round_start"), None)
    except Exception:
        continue
    if not first:
        continue
    excluded = {p["seat"] for p in first["players"]
                if p["name"] in EXCLUDE_PLAYERS}
    for rno, evs in sorted(group_rounds(path).items()):
        rnd = rebuild_round(evs)
        if rnd is None:
            continue
        plays = [e for e in evs if e["e"] == "play"]
        tricks = [e for e in evs if e["e"] == "trick"]
        in_trick, ti, pending = 0, 0, []
        for e in plays:
            seat, cards = e["seat"], e["cards"]
            if (0 < in_trick < 3 and not e.get("bot")
                    and seat not in excluded and rnd.trick and rnd.trick.plays):
                try:
                    win_seat, _, _ = hb._current_winner(rnd)
                except Exception:
                    win_seat = None
                if win_seat is not None and win_seat % 2 == seat % 2:
                    if any(points(c) for c in rnd.hands[seat]):
                        fed = sum(points(c) for c in cards) > 0
                        pending.append(("FED" if fed else "HELD", seat, ti))
            try:
                rnd.play(seat, list(cards))
            except Exception:
                pending = []
                break
            in_trick += 1
            if in_trick == 4:
                in_trick = 0
                ti += 1
        for grp, s, k in pending:
            if k >= len(tricks):
                continue
            tk = tricks[k]
            held = tk["winner"] % 2 == s % 2
            a = agg[grp]
            a["n"] += 1
            a["held"] += held
            (a.__setitem__("pts_kept", a["pts_kept"] + tk["points"]) if held
             else a.__setitem__("pts_lost", a["pts_lost"] + tk["points"]))
for g in ("FED", "HELD"):
    a = agg[g]
    n = a["n"] or 1
    print(f"{g}: n={a['n']} partner_held={a['held']} ({100*a['held']/n:.0f}%) "
          f"pts_kept_total={a['pts_kept']} pts_lost_total={a['pts_lost']}")
