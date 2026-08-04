"""What does the high-N reference say about the gap between mc and the goal?

Rebuilds every state in the diagnostic set and asks each policy for its move,
then scores that move against the N=240 paired reference. Because the states
are stored REBUILDABLE rather than encoded, this can be asked of any policy,
at any time, without regenerating anything.

The question that matters for the goal: **how much does the deployed
mc(N=10) leave on the table?** That difference is the entire prize. If
mc(N=10) is already near the high-N optimum on these states, no amount of
distillation from it can beat it, and the ceiling is the search budget rather
than the learner. If it leaves a lot, the headroom is real and a policy
trained toward high-N labels could exceed it.

Regret is measured only on states where the reference gap clears 2 paired SE,
because on the rest the "best" candidate is not distinguishable from the
baseline and any ranking of policies there is noise.

    uv run python scripts/highn_analyze.py [file] [max_states]
"""
from __future__ import annotations

import json
import random
import sys

sys.path.insert(0, ".")

from shengji.ai.heuristic import HeuristicBot   # noqa: E402
from shengji.ai.mcbot import MCBot              # noqa: E402
from shengji.ai.smart import SmartBot           # noqa: E402
from shengji.engine.round import Round          # noqa: E402


def rebuild(rec) -> tuple:
    """Restore the exact state: deal, declarations, burial, then the plays."""
    st = rec["setup"]
    rnd = Round(st["trump_rank"], st["banker"], random.Random(0))
    rnd.deck = list(st["deck"])
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = list(st["deck"][100:])
    while rnd.phase == "deal":
        rnd.deal_next()
    for d in st["declarations"]:
        try:
            rnd.declare(d["seat"], d["cards"])
        except Exception:
            pass          # a later declaration may have overcalled this one
    rnd.finalize_declare()
    rnd.bury(st["banker"], st["buried"])
    for p in rec["plays"]:
        rnd.play(p["seat"], p["cards"])
    return rnd, rec["seat"]


class MC10(MCBot):
    N_DETERMINIZATIONS = 10       # the DEPLOYED default


class MC30(MCBot):
    N_DETERMINIZATIONS = 30       # what generated the training labels


def score_of(rec, cards) -> float:
    """Reference value of a chosen action (its N=240 paired mean)."""
    key = sorted(cards)
    for i, c in enumerate(rec["candidates"]):
        if sorted(c) == key:
            return rec["mean"][i]
    return float("nan")


def main() -> None:
    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = _args[0] if _args else "rl_data/highn_diag.jsonl"
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cap = int(args[1]) if len(args) > 1 else 10_000

    recs = [json.loads(l) for l in open(path)][:cap]
    only_sig = "--all" not in sys.argv
    sig = [r for r in recs if r["significant"]] if only_sig else recs
    print(f"{len(recs)} states; scoring on "
          + (f"{len(sig)} with a reference gap > 2 paired SE"
             if only_sig else f"ALL {len(sig)} states"))
    print("regret = reference value of the BEST candidate minus the value of "
          "the one chosen (points; lower is better)\n")

    policies = {
        "smart (candidate 0)": lambda seed: SmartBot(),
        "heuristic": lambda seed: HeuristicBot(),
        "mc N=10 (deployed)": lambda seed: MC10(seed=seed),
        "mc N=30 (teacher)": lambda seed: MC30(seed=seed),
    }
    try:
        from shengji.ai.registry import make_bot
        policies["v11 override"] = lambda seed: make_bot("rl-override-v11pair")
    except Exception as e:                      # missing checkpoint
        print(f"  (v11 override unavailable: {e})")

    rows = {}
    for name, mk in policies.items():
        tot = n = 0.0, 0
        total, count, exact = 0.0, 0, 0
        for i, rec in enumerate(sig):
            rnd, seat = rebuild(rec)
            bot = mk(1_000 + i)
            try:
                mv = bot.decide_play(rnd, seat)
            except Exception:
                continue
            v = score_of(rec, mv)
            if v != v:                          # NaN: off-ballot choice
                continue
            best = max(rec["mean"])
            total += best - v
            exact += int(abs(best - v) < 1e-9)
            count += 1
        rows[name] = (total / max(count, 1), 100 * exact / max(count, 1), count)
        print(f"  {name:22} mean regret {rows[name][0]:6.3f}   "
              f"picks the reference best {rows[name][1]:5.1f}%  (n={count})")
        del tot, n

    if "mc N=10 (deployed)" in rows and "smart (candidate 0)" in rows:
        mc10 = rows["mc N=10 (deployed)"][0]
        smart = rows["smart (candidate 0)"][0]
        print(f"\nHEADROOM ABOVE THE INCUMBENT: mc(N=10) still forfeits "
              f"{mc10:.3f} points per decision against the N=240 reference.")
        print(f"  For scale, SmartBot forfeits {smart:.3f}. The prize for a "
              f"policy that matches the reference is therefore {mc10:.3f} "
              f"points/decision,")
        print("  and any distillation FROM mc(N=10) inherits its forfeit "
              "rather than removing it.")


if __name__ == "__main__":
    main()
