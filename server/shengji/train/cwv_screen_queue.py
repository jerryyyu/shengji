"""Opt-in static-Torch W32 screen queue; resume pairs instead of deleting windows.

The legacy screen's defaults stay unchanged. This entry point pins its fast
recipe explicitly and calls the existing runner even when summary.json exists:
that file can describe a partial result, and is never a completion certificate.
No automatic retry, seed allocation, model selection or deployment is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from . import cwv_shortlist_screen as screen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="fresh queue root, distinct from any reference-encoding run")
    parser.add_argument("--name", required=True, help="window directory prefix")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--clusters", type=int, default=520)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--encoding", choices=("reference", "mlp-static"),
                        default="mlp-static")
    parser.add_argument("--trump-ranks", default="2,3,4,5,6,7,8,9,10,J,Q,K,A")
    parser.add_argument("--cost-order-root", type=Path,
                        help="optional completed prior windows, named NAME-SEED")
    parser.add_argument("--cost-order-name",
                        help="prior window prefix; defaults to --name")
    args = parser.parse_args(argv)
    if min(args.clusters, args.workers) < 1 or min(args.seeds) < 0:
        parser.error("positive clusters/workers and nonnegative seeds required")
    ordered = sorted(args.seeds)
    if any(right < left + args.clusters for left, right in zip(ordered, ordered[1:])):
        parser.error("queue seed windows overlap")
    for name in (args.name, args.cost_order_name or args.name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            parser.error("window names must be simple alphanumeric prefixes")
    if not re.fullmatch(r"[0-9a-f]{64}", args.checkpoint_sha256):
        parser.error("checkpoint-sha256 must be a full lowercase SHA256")
    if args.checkpoint.suffix != ".pt":
        parser.error("this path requires a .pt checkpoint and the Torch backend")
    if args.cost_order_name and args.cost_order_root is None:
        parser.error("cost-order-name requires cost-order-root")

    # Both queue and direct single-window callers use the same OS output lock.
    # A source/recipe change is refused by the existing per-window config binding.
    with screen.screen_output_lock(args.out):
        for index, seed in enumerate(args.seeds):
            with args.checkpoint.open("rb") as handle:
                actual_sha = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual_sha != args.checkpoint_sha256:
                raise ValueError("queue checkpoint SHA256 mismatch")
            output = args.out / f"{args.name}-{seed}"
            command = [
                "--arm", "learned", "--checkpoint", str(args.checkpoint.resolve()),
                "--worlds", "32", "--selection-worlds", "30",
                "--alternatives", "4", "--report-worlds", "300",
                "--batch-size", "128", "--encoding", args.encoding,
                "--reuse-successors", "--baseline", "production",
                "--trump-ranks", args.trump_ranks,
                "--clusters", str(args.clusters), "--workers", str(args.workers),
                "--seed0", str(seed), "--out", str(output),
            ]
            if args.cost_order_root is not None:
                prior = args.cost_order_root / f"{args.cost_order_name or args.name}-{seed}"
                command += ["--cost-order-from", str(prior)]
            print(f"window {index + 1}/{len(args.seeds)} seed={seed}: open/resume",
                  flush=True)
            result = screen.main(command)
            if result != 0:
                raise RuntimeError(f"screen returned nonzero status: {result}")
            summary = json.loads((output / "summary.json").read_text())
            if (summary.get("complete") is not True
                    or summary.get("completed_clusters") != args.clusters
                    or summary.get("requested_clusters") != args.clusters):
                raise ValueError("screen returned without a complete window")
            print(f"window {index + 1}/{len(args.seeds)} seed={seed}: complete",
                  flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
