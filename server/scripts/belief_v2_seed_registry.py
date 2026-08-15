#!/usr/bin/env python3
"""Emit the score-free V2 source seed-candidate scan to stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shengji.rl.belief_v2_seed_registry import (
    scan_seed_sources,
    seed_scan_bytes,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("expected_git")
    args = parser.parse_args()
    sys.stdout.buffer.write(seed_scan_bytes(scan_seed_sources(
        args.repo.resolve(), expected_git=args.expected_git)))


if __name__ == "__main__":
    main()

