"""THE evaluator CLI. Every strength claim goes through this and no other path.

The protocol itself lives in `shengji.evaluation`, which is the whole point of
this file being short: six duel runners had each grown a private copy of seed
handling and interval arithmetic, and a seed-dropping lambda survived in five
of them simultaneously. Read that module for what is enforced and why.

    uv run python scripts/evaluate.py ARM OPPONENT --clusters 250 \\
        --bar "paired_utility > 0" [--control ARM] [--seed0 N] [--ckpt PATH]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.evaluation import ProtocolFailure, evaluate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm")
    ap.add_argument("opponent")
    ap.add_argument("--clusters", type=int, default=250)
    ap.add_argument("--seed0", type=int, default=None)
    ap.add_argument("--control", default=None,
                    help="an arm that SHOULD NOT work; without one, a positive "
                         "result cannot be attributed to the thing you changed")
    ap.add_argument("--bar", required=True,
                    help="ENFORCED, not decorative: '<metric> > <value>' with "
                         "metric in {paired_utility, win_rate}. The clustered "
                         "interval must exclude the value to CONFIRM.")
    ap.add_argument("--allow-no-control", action="store_true")
    ap.add_argument("--allow-lenient-voids", action="store_true")
    ap.add_argument("--ckpt", action="append", default=[],
                    help="checkpoint paths to digest into the manifest")
    args = ap.parse_args()

    try:
        res = evaluate(
            args.arm, args.opponent, clusters=args.clusters, seed0=args.seed0,
            control=args.control, bar=args.bar, ckpts=args.ckpt,
            allow_no_control=args.allow_no_control,
            allow_lenient_voids=args.allow_lenient_voids,
            cli_path=os.path.abspath(__file__))
    except ProtocolFailure as exc:
        print(f"REFUSING: {exc}")
        sys.exit(3)
    sys.exit(0 if res.confirmed else 1)


if __name__ == "__main__":
    main()
