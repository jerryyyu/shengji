"""The lead-ballot pilot runner. Produces one record per STATE, never per arm.

Sharding is by state because the comparison is paired: every arm must be scored
on the SAME report worlds, and one record must own the whole comparison for a
state. Sharding by arm would put the arms in different files with different
worlds and leave nothing that could be paired afterwards (Codex).

Fold roles, and why they differ in size:

  * **report** — COMMON across arms, identical worlds in identical order. This
    is where the paired contrast is computed, so it cannot vary by arm.
  * **oracle** — common. The reference is chosen here from the union ballot and
    frozen; re-choosing it on report worlds would make it the maximum of the
    same noise the arms are measured against.
  * **proposal** — SIZED PER ARM, because equal work means equal
    (candidate x world) rollouts, not equal worlds. Arms differ in ballot size
    (current ~10.8 candidates, quota 14, full_universe ~39), so a flat world
    count would hand the narrow arms a compute advantage dressed as a control.

`full_universe` is deliberately NOT equal-worked. It is the named
high-compute/upper-bound arm and keeps its own per-candidate world dose; making
it equal-work would answer a different question.

Realised work is recorded per state and per arm, and a run FAILS if any
equal-work arm leaves the preregistered band — a control that quietly drifts
out of its budget is not a control.

    uv run python scripts/pilot_run.py --states rl_data/pilot_states.v3.json \\
        --limit 8 --out runs/logs/pilot_smoke.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                 # noqa: E402
from shengji.ai.registry import make_bot             # noqa: E402
from shengji.pilot_arms import ARMS, propose         # noqa: E402
from shengji.pilot_folds import draw_folds           # noqa: E402
from shengji.pilot_score import (choose_action, oracle_reference,  # noqa: E402
                                 report_regret, union_ballot,
                                 worlds_for_equal_work)

SOURCES = {"original": "rl_data/highn_corpus_all.jsonl",
           "late": "rl_data/highn_late_air.jsonl",
           "deep": "rl_data/deep_leads.v1.jsonl"}
#: arms held to the equal-work band. `full_universe` is exempt by design (it is
#: the upper-bound arm) and `mc_more` is budgeted against full_universe's work
#: instead, since at the band it degenerates into `current`.
EQUAL_WORK_ARMS = tuple(a for a in ARMS
                        if a not in ("full_universe", "mc_more_full_work"))


def digest(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="rl_data/pilot_states.v3.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--budget", type=int, default=14, help="lead ballot slots")
    ap.add_argument("--work", type=int, default=168,
                    help="preregistered candidate-world rollouts per state")
    ap.add_argument("--band", type=float, default=0.05,
                    help="fractional tolerance on realised work")
    ap.add_argument("--report-worlds", type=int, default=12)
    ap.add_argument("--full-proposal-worlds", type=int, default=12,
                    help="PREREGISTERED proposal dose for full_universe. "
                         "Separate from --report-worlds: reusing that value "
                         "silently coupled two independent budgets (Codex).")
    ap.add_argument("--oracle-worlds", type=int, default=12)
    ap.add_argument("--salt", default="pilot-run-v1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — scoring on worlds that "
              "may violate observed voids measures nothing.")
        sys.exit(3)
    if os.path.exists(args.out):
        print(f"REFUSING: {args.out} exists; results are never overwritten.")
        sys.exit(3)

    spec = json.load(open(args.states))
    states = spec["states"][:args.limit] if args.limit else spec["states"]
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    bot = make_bot("mc", seed=1)
    from shengji.engine.ballot import mc_ballot
    manifest = {
        "git": sha, "tree_dirty": bool(dirty),
        "script_sha256_16": digest(os.path.abspath(__file__)),
        "states_artifact": args.states,
        "states_sha256_16": digest(args.states),
        "ballot": str(mc_ballot(bot)),
        "budget": args.budget, "work_target": args.work, "band": args.band,
        "report_worlds": args.report_worlds,
        "oracle_worlds": args.oracle_worlds,
        "full_proposal_worlds": args.full_proposal_worlds,
        "salt": args.salt, "n_states": len(states),
        "equal_work_arms": list(EQUAL_WORK_ARMS),
        "require_voids": True,
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print(json.dumps(manifest, indent=2), flush=True)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pilot_states import replay

    records, work_violations, errors = [], [], 0
    t0 = time.time()
    for i, st in enumerate(states):
        key = f'{st["source"]}:{st["seed"]}:{st["ply"]}'
        src = SOURCES.get(st["source"])
        try:
            row = next(json.loads(l) for l in open(src)
                       if json.loads(l)["seed"] == st["seed"]
                       and json.loads(l)["ply"] == st["ply"])
            rnd = replay(row)
        except Exception as exc:
            errors += 1
            print(f"  REPLAY FAILED {key}: {type(exc).__name__}", flush=True)
            continue
        seat = st["seat"]
        mem = Memory(rnd, seat)

        # sha256, NOT builtin hash(): str hashing is randomised per process,
        # so the arm seed — and therefore random_fill's ballot, the realised
        # work and every downstream number — differed between two runs of the
        # same command. The determinism check caught it; this is the same
        # per-process-hash class that once made "fixed-seed" MC runs differ.
        arm_seed = int(hashlib.sha256(args.salt.encode()).hexdigest()[:8], 16)
        ballots = {a: propose(a, bot, rnd, seat, budget=args.budget,
                              seed=arm_seed, state_key=key)
                   for a in ARMS}
        # proposal worlds sized per arm for EQUAL WORK; report/oracle common.
        #
        # `mc_more` is the exception in the OTHER direction. At equal work with
        # the deployed ballot it IS `current` — the smoke run reported
        # mc_more - current = +0.000 +/- 0.000, which is proof the control was
        # degenerate rather than evidence of a tie. Its question is "if the
        # deployed ballot were given the compute the WIDE arm spends, would it
        # do as well?", so it is budgeted against full_universe's work, not the
        # band. BALLOT_PLAN: "all extra proposal compute moved into more
        # worlds".
        prop_worlds = {a: (args.full_proposal_worlds if a == "full_universe"
                           else worlds_for_equal_work(args.work, len(ballots[a])))
                       for a in ARMS}
        wide_work = len(ballots["full_universe"]) * prop_worlds["full_universe"]
        prop_worlds["mc_more_full_work"] = worlds_for_equal_work(
            wide_work, len(ballots["mc_more_full_work"]))
        counts = {"proposal": max(prop_worlds.values()),
                  "oracle": args.oracle_worlds, "report": args.report_worlds}
        fw = draw_folds(bot, rnd, seat, mem, counts, salt=args.salt,
                        state_key=key)

        rec = {"state": key, "seat": seat, "tricks": len(rnd.history),
               "band": st.get("band"), "stratum": st.get("stratum"),
               "arms": {}}
        chosen = {}
        for a in ARMS:
            # each arm sees a PREFIX of the common proposal draw, sized to its
            # own work budget; the report fold is identical for every arm
            worlds = fw.worlds["proposal"][:prop_worlds[a]]
            got = choose_action(bot, rnd, seat, worlds, ballots[a],
                                state_key=key, expect=len(worlds))
            chosen[a] = got["action"]
            rec["arms"][a] = {"n_candidates": got["n_candidates"],
                              "action": got["action"],
                              "kept_heuristic": got["kept_heuristic"],
                              "tractor_locked": got["tractor_locked"],
                              "work": got["candidate_world_rollouts"],
                              "proposal_worlds": len(worlds)}
            if a == "mc_more_full_work" and not got["tractor_locked"]:
                w = got["candidate_world_rollouts"]
                if abs(w - wide_work) > args.band * wide_work:
                    work_violations.append((key, a, w))
            elif a in EQUAL_WORK_ARMS and not got["tractor_locked"]:
                w = got["candidate_world_rollouts"]
                if abs(w - args.work) > args.band * args.work:
                    work_violations.append((key, a, w))

        ref = oracle_reference(bot, rnd, seat, fw.worlds["oracle"],
                               union_ballot(ballots), state_key=key,
                               expect=args.oracle_worlds)
        rec["oracle_action"] = list(ref.action)
        for a in ARMS:
            out = report_regret(bot, rnd, seat, fw.worlds["report"], chosen[a],
                                list(ref.action), state_key=key,
                                expect=args.report_worlds)
            rec["arms"][a].update({
                "regret": out["regret"],
                "arm_mean": out["arm_mean"],
                "arm_returns": out["arm_returns"],
                "arm_raw_points": out["arm_raw_points"],
                "arm_brackets": out["arm_brackets"],
                "matched_oracle": chosen[a] == list(ref.action)})
        rec["reference_returns"] = out["reference_returns"]
        rec["reference_raw_points"] = out["reference_raw_points"]
        records.append(rec)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(states)} states, {time.time()-t0:.0f}s",
                  flush=True)

    if work_violations:
        print(f"\nWORK BAND VIOLATIONS: {len(work_violations)}")
        for k, a, w in work_violations[:8]:
            print(f"  {k} {a}: {w} rollouts, target {args.work} "
                  f"+/- {args.band*args.work:.0f}")
        print("A control that drifts out of its budget is not a control.")

    print(f"\n{len(records)} states scored, {errors} replay errors, "
          f"{time.time()-t0:.0f}s")
    print(f"\n{'arm':16} {'mean regret':>12} {'oracle match':>13} {'work':>8}")
    for a in ARMS:
        rs = [r["arms"][a]["regret"] for r in records]
        mo = [r["arms"][a]["matched_oracle"] for r in records]
        wk = [r["arms"][a]["work"] for r in records]
        if rs:
            print(f"{a:16} {sum(rs)/len(rs):12.3f} "
                  f"{100*sum(mo)/len(mo):12.1f}% {sum(wk)/len(wk):8.0f}")
    print("\nPer-state means above are DESCRIPTIVE. The experiment interval "
          "must be a paired per-state contrast clustered by deal, computed "
          "from `records`, never from states x worlds.")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "x") as fh:
        json.dump({**manifest, "work_violations": work_violations,
                   "replay_errors": errors, "records": records}, fh, indent=1)
    print(f"\nwrote {args.out}")
    sys.exit(1 if (work_violations or errors) else 0)


if __name__ == "__main__":
    main()
