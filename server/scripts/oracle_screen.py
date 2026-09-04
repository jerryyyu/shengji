#!/usr/bin/env python3
"""Oracle CEILING screen: production search vs. oracle-leaf / oracle-prior arms.

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/oracle_screen.py \
        --arm both --rounds 64 --seed 145000000 --workers 16 --out runs/oracle/both

Arms (see shengji/oracle/screen.py for the exact semantics and knobs):

  value   identical worlds/ballot; every leaf continuation deepened with
          --leaf-multiplier plain rollouts of greedy one-ply rollout
          improvement, plus the S3b exact solver when --exact-endgame-cards > 0
  prior   production work; ballot ranked/pruned per decision by a
          --prior-worlds high-N paired evaluation, keeping --prior-keep-top
  both    value + prior
  wide    production work at N unchanged; the ballot is replaced by the best
          of the EXHAUSTIVE legal set (--wide-cap): every legal action screened
          on --wide-screen-worlds shared worlds, the top --wide-keep-stage1
          ranked on --prior-worlds worlds, --wide-keep-top handed to the search
          (--prior-anchor lets the ranking replace the incumbent)
  wide-value  wide + value
  none    production on both sides (identity control for neutral knobs)
  null    production vs its champion-matched null (noise floor on these deals)

The baseline is always the registered production class (--base-policy,
default mc-s0-report-lcb) at its registered work.  --select-worlds and
--report-worlds override BOTH sides' work for smoke tests only; the summary
then says so.  --rounds is the total number of rounds: rounds/2 seeded deal
clusters, each played in both mirrors.  Fixed seeds reproduce rounds.jsonl and
summary.json byte for byte at any worker count; wall-clock lives in
timing.jsonl and runtime.json.

This is a tier-i ceiling screen: non-promotable, verdict-free, and the arms
are not candidate policies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.oracle import screen as S  # noqa: E402


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=S.ARMS)
    ap.add_argument("--rounds", type=int, required=True,
                    help="total rounds (even): rounds/2 clusters x 2 mirrors")
    ap.add_argument("--seed", type=int, required=True,
                    help="seed0; cluster c deals from seed0 + c")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", required=True, help="fresh output directory")
    ap.add_argument("--base-policy", default=S.DEFAULT_BASE_POLICY)
    d = S.knob_defaults()
    ap.add_argument("--leaf-multiplier", type=int, default=d["leaf_multiplier"],
                    help="continuation rollouts per leaf (1 = production)")
    ap.add_argument("--exact-endgame-cards", type=int,
                    default=d["exact_endgame_cards"],
                    help="exact solver once every hand is within this many "
                         "cards (0 = off; S3b proved 4)")
    ap.add_argument("--exact-endgame-nodes", type=int,
                    default=d["exact_endgame_nodes"])
    ap.add_argument("--prior-worlds", type=int, default=d["prior_worlds"])
    ap.add_argument("--prior-keep-top", type=int, default=d["prior_keep_top"],
                    help="ballot entries kept incl. the incumbent (0 = no prior)")
    ap.add_argument("--prior-fixed-n", action="store_true",
                    help="keep N per candidate instead of scaling to equal "
                         "total selection work")
    ap.add_argument("--prior-anchor", action="store_true",
                    help="let the ranking choose the incumbent too "
                         "(prior and wide arms)")
    ap.add_argument("--wide-cap", type=int, default=d["wide_cap"],
                    help="legal actions enumerated per decision (the "
                         "production ballot is always included)")
    ap.add_argument("--wide-screen-worlds", type=int,
                    default=d["wide_screen_worlds"],
                    help="stage-1 shared worlds scoring EVERY legal action")
    ap.add_argument("--wide-keep-stage1", type=int,
                    default=d["wide_keep_stage1"],
                    help="stage-1 survivors ranked on --prior-worlds worlds")
    ap.add_argument("--wide-keep-top", type=int, default=d["wide_keep_top"],
                    help="ballot entries handed to the search incl. the "
                         "incumbent (0 = no oracle)")
    ap.add_argument("--select-worlds", type=int, default=None,
                    help="SMOKE ONLY: override N on both sides")
    ap.add_argument("--report-worlds", type=int, default=None,
                    help="SMOKE ONLY: override R on both sides (LCB needs >= 30)")
    ap.add_argument("--bootstrap-replicates", type=int,
                    default=S.DEFAULT_BOOTSTRAP_REPLICATES)
    ap.add_argument("--bootstrap-seed", type=int,
                    default=S.DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--progress", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    knobs = {
        "leaf_multiplier": args.leaf_multiplier,
        "exact_endgame_cards": args.exact_endgame_cards,
        "exact_endgame_nodes": args.exact_endgame_nodes,
        "prior_worlds": args.prior_worlds,
        "prior_keep_top": args.prior_keep_top,
        "prior_equal_work": not args.prior_fixed_n,
        "prior_anchor": args.prior_anchor,
        "wide_cap": args.wide_cap,
        "wide_screen_worlds": args.wide_screen_worlds,
        "wide_keep_stage1": args.wide_keep_stage1,
        "wide_keep_top": args.wide_keep_top,
        "wide_fixed_n": True,
    }
    try:
        summary = S.run_screen(
            arm=args.arm, rounds=args.rounds, seed0=args.seed,
            out_dir=args.out, workers=args.workers,
            base_policy=args.base_policy, knobs=knobs,
            select_worlds=args.select_worlds, report_worlds=args.report_worlds,
            replicates=args.bootstrap_replicates,
            bootstrap_seed=args.bootstrap_seed, script_path=str(SCRIPT),
            argv=sys.argv if argv is None else [str(SCRIPT), *argv],
            progress=args.progress)
    except S.OracleScreenError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    util = summary["arm_signed_level_utility"]["per_round"]
    win = summary["arm_win_rate"]
    print(json.dumps({
        "arm": summary["arm"],
        "description": summary["arm_description"],
        "rounds": summary["rounds"],
        "clusters": summary["clusters"],
        "arm_signed_level_utility_per_round": util["mean"],
        "ci95_cluster_bootstrap": util["ci95"],
        "arm_win_rate": win["mean"],
        "win_rate_ci95": win["ci95"],
        "arm_over_baseline_continuation_rollouts":
            summary["arm_over_baseline_continuation_rollouts"],
        "arm_over_baseline_total_rollouts":
            summary["arm_over_baseline_total_rollouts"],
        "problems": summary["problems"],
        "paths": summary["paths"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
