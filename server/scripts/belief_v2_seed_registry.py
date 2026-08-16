#!/usr/bin/env python3
"""Emit the score-free V2 source seed-candidate scan to stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shengji.rl.belief_v2_seed_registry import (
    scan_seed_sources,
    seed_registry_bytes,
    seed_scan_bytes,
)
from shengji.rl.belief_v2_seed_registry_builder import (
    build_reviewed_seed_registry,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("expected_git")
    parser.add_argument(
        "--registry", action="store_true",
        help="emit the closed historical/V2 population registry")
    args = parser.parse_args()
    scan = scan_seed_sources(
        args.repo.resolve(), expected_git=args.expected_git)
    if args.registry:
        registry = build_reviewed_seed_registry(scan)
        sys.stdout.buffer.write(seed_registry_bytes(registry, scan=scan))
    else:
        sys.stdout.buffer.write(seed_scan_bytes(scan))


if __name__ == "__main__":
    main()
