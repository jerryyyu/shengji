#!/usr/bin/env python3
"""Publish one bounded, non-scientific Value-Afterstate V2 rehearsal."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 rehearsal requires Python -P -B")
SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 rehearsal refuses PYTHONPATH")
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.world_afterstate_v2_rehearsal import (  # noqa: E402
    SOURCE_IDENTITY, run_non_scientific_rehearsal_v2,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--source-identity", default=SOURCE_IDENTITY)
    args = parser.parse_args(argv)

    def progress(value: dict[str, object]) -> None:
        print(json.dumps(value, sort_keys=True, separators=(",", ":")),
              flush=True)

    receipt = run_non_scientific_rehearsal_v2(
        args.output, args.receipt, source_identity=args.source_identity,
        progress=progress)
    print(json.dumps(receipt.payload, sort_keys=True, separators=(",", ":")),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
