"""Read the S156 matched-prefix reports. Return 0 to continue, 3 for FAIL-OFFLINE, 2 for invalid input."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import sys


def load_arm(directory, checkpoint_sha, boundary):
    run = json.loads((directory / "run.json").read_text())
    if not re.fullmatch(r"[0-9a-f]{64}", checkpoint_sha):
        raise ValueError("expected the full initial checkpoint sha256")
    starts = [line.split() for line in (directory / "status.log").read_text().splitlines()
              if " UTR START " in line]
    if len(starts) != 1 or f"init=readout-ckpt:{checkpoint_sha}" not in starts[0]:
        raise ValueError(f"{directory}: trainer start does not match the expected warm start")
    if not run.pop("init_readout_ckpt") or run["report_buffer"] != boundary or not run["data"]:
        raise ValueError(f"{directory}: missing or incompatible training identity")
    required = {"seed", "buffer_chunks", "rounds_per_batch", "max_train_rows", "exclude_seed_window", "store_map"}
    if not required.issubset(run):
        raise ValueError(f"{directory}: incomplete data selection settings")
    run.pop("device", None)
    report = json.loads((directory / f"epoch-1-buffer-{boundary}.json").read_text(), parse_float=Decimal)
    if report["epoch"] != 1 or report["completed_buffers"] != boundary:
        raise ValueError(f"{directory}: report covers a different prefix")
    counts = (report["rows"], report["leaves"])
    if any(type(n) is not int or n <= 0 for n in counts):
        raise ValueError(f"{directory}: expected positive row and leaf counts")
    losses = []
    for field in ("leaf_value", "policy"):
        value = report["train"][field]
        if type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
            raise ValueError(f"{directory}: invalid {field} loss")
        losses.append(Decimal(value))
    return run, counts, losses


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("small", "medium"):
        parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument(f"--{name}-init-sha", required=True)
    parser.add_argument("--buffer", type=int, default=400, help="matched boundary (S156 uses 400)")
    args = parser.parse_args(argv)
    try:
        if args.buffer <= 0 or args.small_init_sha == args.medium_init_sha:
            raise ValueError("expected a positive boundary and two distinct warm starts")
        small, ns, s = load_arm(args.small, args.small_init_sha, args.buffer)
        medium, nm, m = load_arm(args.medium, args.medium_init_sha, args.buffer)
        if small != medium or ns != nm:
            raise ValueError("the training settings or prefix counts differ")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    leaf, policy = (a - b for a, b in zip(s, m))
    proceed = leaf >= Decimal("0.002") or policy >= Decimal("0.015")
    print(f"{'CONTINUE' if proceed else 'FAIL-OFFLINE'} buffer={args.buffer} rows={ns[0]} "
          f"leaves={ns[1]} leaf_value_S_minus_M={leaf} policy_S_minus_M={policy}")
    return 0 if proceed else 3


if __name__ == "__main__":
    sys.exit(main())
