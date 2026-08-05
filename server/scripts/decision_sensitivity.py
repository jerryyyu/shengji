"""Does the sampler's posterior bias change WHICH ACTION gets chosen?

Codex's condition for unblocking pilot scoring: residual excess TV `0.046` is
"not accepted as harmless without action-decision sensitivity evidence". TV is a
distributional distance; the pilot only cares whether the bias moves the argmax.
A large TV concentrated on worlds that all rank actions the same way is
harmless; a small TV sitting exactly where two candidates cross is not.

Design, on states small enough to enumerate every legal world:

  1. Score every candidate action on EVERY legal world once, giving a fixed
     table `V[action][world]`. Fixing it removes rollout noise from the
     comparison entirely — the only thing that varies below is WHICH WORLDS
     get averaged, which is precisely the quantity under test.
  2. EXACT decision: argmax over the physical-deal posterior, all worlds.
  3. BIASED arm: draw N worlds from the real sampler, argmax the empirical mean.
  4. CONTROL arm: draw N worlds from the EXACT posterior, same N, same rule.

**The control is what makes this interpretable.** At finite N even a perfect
sampler disagrees with the exact argmax sometimes, purely from Monte Carlo
noise. Without arm 4, that noise reads as bias and every result overstates the
problem. What matters is BIASED minus CONTROL.

Regret is reported in the exact measure — the expected value given up by playing
the arm's action instead of the exact-posterior action — because a disagreement
between two near-tied candidates costs nothing and should not count the same as
a disagreement that drops real value.

LIMITATION, stated up front: the decision rule here is a plain argmax of mean
return. It does NOT reproduce `choose_action`'s `MARGIN`, `POINT_SHY_EPS` or
candidate-0 protection, which make the deployed policy STICKIER than argmax.
A stickier rule can only flip on larger disagreements, so this measures the
mechanism directly and is not a substitute for the deployed-semantics run.

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \\
    uv run python scripts/decision_sensitivity.py --states 12 --draws 30
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from certify_sampler import constraints, enumerate_legal, toy_states  # noqa: E402
from reweight_posterior import physical_weight                        # noqa: E402
from shengji.ai.memory import Memory                                  # noqa: E402
from shengji.ai.mcbot import MCBot                                    # noqa: E402
from shengji.pilot_folds import world_key                             # noqa: E402
from shengji.pilot_score import score_action                          # noqa: E402


def worlds_from_keys(keys):
    """Rebuild (hands, buried) from the canonical key."""
    out = []
    for k in keys:
        hands = {seat: list(cards) for seat, cards in k[0]}
        buried = list(k[1]) if len(k) > 1 else []
        out.append((hands, buried))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", type=int, default=12)
    ap.add_argument("--draws", type=int, default=30,
                    help="worlds per decision; production MC uses N=30")
    ap.add_argument("--reps", type=int, default=400)
    ap.add_argument("--max-worlds", type=int, default=120)
    ap.add_argument("--out", default="runs/logs/decision_sensitivity.json")
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — the lenient sampler is "
              "not what the pilot would score on.")
        sys.exit(3)

    bot = MCBot(seed=99991)
    rows = []
    degenerate = live = 0
    for seed, rnd, seat in toy_states(args.states * 4):
        try:
            legal_keys = enumerate_legal(rnd, seat, constraints(rnd))
        except RuntimeError:
            continue
        if not legal_keys or len(legal_keys) > args.max_worlds:
            continue
        legal_keys = sorted(legal_keys)
        cands = bot._candidates(rnd, seat)
        if len(cands) < 2:
            continue          # nothing to get wrong

        worlds = worlds_from_keys(legal_keys)
        w = [physical_weight(k) for k in legal_keys]
        tot = sum(w)
        p = [x / tot for x in w]
        idx = {k: i for i, k in enumerate(legal_keys)}

        # fixed value table: one rollout per (action, world), reused everywhere
        V = [score_action(bot, rnd, seat, worlds, a,
                          state_key=str(seed), fold="exact").returns
             for a in cands]

        # DECISION-DEGENERATE states must be excluded, not scored. Most
        # enumerable states are deep endgames where every candidate has an
        # IDENTICAL return on every world — `C2` and `H2` with two cards left
        # are the same move. There `argmax` returns index 0 for any input, so
        # disagreement is 0.000 no matter how biased the sampler is. Including
        # them would let a broken harness and a clean sampler print the same
        # answer, which is how a zero gets mistaken for evidence.
        if len({tuple(v) for v in V}) < 2:
            degenerate += 1
            continue
        live += 1

        def argmax(weights):
            best, bi = None, 0
            for ai in range(len(cands)):
                m = sum(weights[i] * V[ai][i] for i in range(len(worlds)))
                if best is None or m > best:
                    best, bi = m, ai
            return bi

        exact_w = p
        exact_a = argmax(exact_w)
        exact_val = [sum(p[i] * V[ai][i] for i in range(len(worlds)))
                     for ai in range(len(cands))]

        rng = random.Random(seed ^ 0xA5A5)

        def empirical(sample_idx):
            c = [0.0] * len(worlds)
            for i in sample_idx:
                c[i] += 1.0 / len(sample_idx)
            return c

        dis = {"biased": 0, "control": 0}
        reg = {"biased": 0.0, "control": 0.0}
        attempts = fails = offsupport = zero_world = 0
        bot.reject_cause.clear()
        for _ in range(args.reps):
            # BIASED: the real sampler, with PRODUCTION semantics.
            # `MCBot._decide` runs `for _ in range(N_DETERMINIZATIONS)` and
            # SKIPS failed draws, so a search that fails often silently uses
            # fewer worlds. Looping until N successes instead — which this
            # script did — measures a different and strictly better-informed
            # estimator than the one that ships (Codex).
            got = []
            for _ in range(args.draws):
                attempts += 1
                s = bot._sample_hands(rnd, seat, Memory(rnd, seat))
                if s is None:
                    fails += 1
                    continue
                k = world_key(s[0], s[1])
                if k not in idx:
                    offsupport += 1
                    continue
                got.append(idx[k])
            if not got:
                # production falls back to candidate 0 on a zero-world search
                zero_world += 1
                a_b = 0
            else:
                a_b = argmax(empirical(got))
            # CONTROL: exact posterior, same N
            ctl = rng.choices(range(len(worlds)), weights=p, k=args.draws)
            a_c = argmax(empirical(ctl))
            for tag, a in (("biased", a_b), ("control", a_c)):
                if a != exact_a:
                    dis[tag] += 1
                reg[tag] += exact_val[exact_a] - exact_val[a]

        import hashlib
        vdig = hashlib.sha256(
            repr([[round(x, 9) for x in v] for v in V]).encode()).hexdigest()
        r = {"seed": seed, "n_legal": len(worlds), "n_cands": len(cands),
             "candidates": [list(a) for a in cands],
             "exact_action": exact_a,
             "exact_values": exact_val,
             "value_digest": vdig,
             "value_table": [list(v) for v in V] if len(worlds) <= 300 else None,
             "attempts": attempts, "failed_draws": fails,
             "off_support_draws": offsupport,
             "zero_world_decisions": zero_world,
             "reject_cause": dict(bot.reject_cause),
             "disagree_biased": dis["biased"] / args.reps,
             "disagree_control": dis["control"] / args.reps,
             "regret_biased": reg["biased"] / args.reps,
             "regret_control": reg["control"] / args.reps}
        r["disagree_excess"] = r["disagree_biased"] - r["disagree_control"]
        r["regret_excess"] = r["regret_biased"] - r["regret_control"]
        rows.append(r)
        print(f"  seed {seed}: {len(worlds):3d} worlds, {len(cands)} cands | "
              f"disagree biased {r['disagree_biased']:.3f} vs control "
              f"{r['disagree_control']:.3f} (excess {r['disagree_excess']:+.3f})"
              f" | regret excess {r['regret_excess']:+.4f}", flush=True)
        if len(rows) >= args.states:
            break

    print(f"\n  state census: {live} decision-LIVE, {degenerate} "
          f"decision-DEGENERATE (excluded)")
    if not rows:
        print("REFUSING: no decision-live enumerable states. A zero here would "
              "mean the probe found nothing to measure, NOT that the sampler "
              "bias is harmless.")
        sys.exit(2)
    n = len(rows)
    import math
    de = [r["disagree_excess"] for r in rows]
    re_ = [r["regret_excess"] for r in rows]

    def ci(v):
        m = sum(v) / len(v)
        if len(v) < 2:
            return m, float("inf")
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
        return m, 1.96 * sd / math.sqrt(len(v))

    dm, dci = ci(de)
    rm, rci = ci(re_)
    print(f"\n  states {n}   N={args.draws} worlds/decision   {args.reps} reps")
    print(f"  EXCESS disagreement (biased - control): {dm:+.4f} +/- {dci:.4f}")
    print(f"  EXCESS regret       (biased - control): {rm:+.4f} +/- {rci:.4f}")
    print("\n  Excess is the bias-attributable part; the control absorbs the "
          "Monte Carlo noise a perfect sampler shows at the same N.")
    print("  Decision rule is plain argmax, NOT the deployed `choose_action` "
          "semantics, which are stickier and would flip less often.")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        import subprocess
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"],
                                    capture_output=True, text=True,
                                    cwd=os.path.dirname(os.path.dirname(
                                        os.path.abspath(__file__)))
                                    ).stdout.strip()
            dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                        capture_output=True, text=True
                                        ).stdout.strip())
        except Exception:
            commit, dirty = "unknown", True
        import hashlib as _h
        mc_src = _h.sha256(open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "shengji", "ai",
            "mcbot.py"), "rb").read()).hexdigest()[:16]
        json.dump({"states": n, "draws": args.draws, "reps": args.reps,
                   "mode": {"weighted_splits": bool(os.environ.get(
                                "SHENGJI_WEIGHTED_SPLITS")),
                            "uniform_deal": bool(os.environ.get(
                                "SHENGJI_UNIFORM_DEAL")),
                            "physical_fills": bool(os.environ.get(
                                "SHENGJI_PHYSICAL_FILLS")),
                            "require_voids": bool(os.environ.get(
                                "SHENGJI_REQUIRE_VOIDS")),
                            "fast": bool(os.environ.get("SHENGJI_FAST"))},
                   "commit": commit, "tree_dirty": dirty,
                   "mcbot_sha256_16": mc_src,
                   "draw_semantics": "N ATTEMPTS with failures skipped, "
                                     "matching MCBot._decide; NOT N successes",
                   "reference": "uniform-over-PHYSICAL-DEALS",
                   "decision_rule": "plain argmax; NOT choose_action "
                                    "MARGIN/POINT_SHY_EPS/candidate-0",
                   "mean_disagree_excess": dm, "disagree_ci": dci,
                   "mean_regret_excess": rm, "regret_ci": rci,
                   "decision_live": live, "decision_degenerate": degenerate,
                   "rows": rows}, fh, indent=1)
    print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
