#!/usr/bin/env python3
"""Collect a fresh matched production decision panel (no LLM calls)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-secret-hex", required=True,
                        help="64 hexadecimal characters (exactly 32 secret bytes)")
    parser.add_argument("--out", required=True, type=Path,
                        help="private output directory")
    parser.add_argument("--workers", type=int, default=1,
                        help="coordinate workers, 1 through 16 (default: 1)")
    args = parser.parse_args(argv)
    try:
        secret = bytes.fromhex(args.seed_secret_hex)
    except ValueError as exc:
        parser.error(f"--seed-secret-hex must be hexadecimal: {exc}")
    if len(secret) != 32:
        parser.error("--seed-secret-hex must decode to exactly 32 bytes")
    # Import after argument validation so a malformed invocation cannot load
    # or initialize any production engine state.
    from shengji.luna.quality_panel import run_panel
    try:
        manifest = run_panel(secret, args.out, workers=args.workers)
    except Exception as exc:
        parser.error(str(exc))
    print(manifest["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
