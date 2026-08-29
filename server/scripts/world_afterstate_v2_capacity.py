#!/usr/bin/env python3
"""Run and publish the score-free Value-Afterstate V2 capacity receipt.

This command has capacity authority only.  It does not train, open labels or
outcomes, run an audit, or authorize a consumer.  The output path is
single-writer and non-destructive.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 capacity requires Python -P -B")

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.world_afterstate_v2_capacity_runner import (  # noqa: E402
    CapacityRunnerError, publish_capacity_receipt_v2,
    reopen_capacity_receipt_v2, run_capacity_v2,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="bounded score-free Value-Afterstate V2 capacity measurement")
    value.add_argument("--out", type=Path, required=True,
                       help="new canonical receipt path")
    value.add_argument("--progress", action="store_true",
                       help="emit bounded score-free progress to stderr")
    return value


def _progress(row: dict[str, object]) -> None:
    print(json.dumps(row, sort_keys=True, separators=(",", ":")),
          file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        receipt = run_capacity_v2(progress=_progress if args.progress else None)
        # The publisher validates and canonicalizes the exact typed payload;
        # importing canonical_json_bytes here makes the output requirement
        # explicit without introducing a second serialization format.
        _ = canonical_json_bytes(receipt.payload())
        publish_capacity_receipt_v2(args.out, receipt)
        # Independent reopen is performed from the published bytes, not from
        # the in-memory object used by the writer.
        reopened = reopen_capacity_receipt_v2(
            json.loads(args.out.read_text(encoding="ascii")))
        if canonical_json_bytes(reopened.payload()) != args.out.read_bytes():
            raise CapacityRunnerError("published receipt independent reopen drift")
    except (CapacityRunnerError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
