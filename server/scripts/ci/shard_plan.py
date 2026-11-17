#!/usr/bin/env python3
"""Split a suite's test modules into balanced pieces by recorded time.

Every CI pytest session of a sharded suite runs the same command line (the
whole suite) with ``SHENGJI_CI_SHARD=i/N``; each session plans the same
assignment from the same inputs and keeps piece ``i``.  The plan is a greedy
longest-processing-time packing: modules in descending recorded time, each
into the currently lightest piece (ties to the lower index), so every module
lands in exactly one piece.

Recorded times live in ``test_durations.json`` next to this file, keyed by
engine mode (``pure``/``compiled``) and repo-relative module path.  A module
with no record costs the median of the recorded modules of that mode.

Usage::

    shard_plan.py --engine pure --pieces 3 server/tests/test_a.py ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DURATIONS = HERE / "test_durations.json"
FALLBACK_SECONDS = 5.0


def load_durations(path: Path = DURATIONS) -> dict[str, dict[str, float]]:
    """``{engine: {module: seconds}}``; empty when the file is missing or unreadable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    modes = data.get("modes", {}) if isinstance(data, dict) else {}
    return {
        engine: {str(k): float(v) for k, v in table.items()}
        for engine, table in modes.items()
        if isinstance(table, dict)
    }


def module_costs(modules, engine: str, durations: dict[str, dict[str, float]]) -> dict[str, float]:
    table = durations.get(engine, {})
    default = statistics.median(table.values()) if table else FALLBACK_SECONDS
    return {module: table.get(module, default) for module in modules}


def plan(modules, pieces: int, costs: dict[str, float]) -> list[list[str]]:
    """``pieces`` disjoint lists whose union is ``modules`` (deduplicated)."""
    if pieces < 1:
        raise ValueError("pieces must be at least 1")
    bins: list[list[str]] = [[] for _ in range(pieces)]
    loads = [0.0] * pieces
    for module in sorted(set(modules), key=lambda m: (-costs.get(m, FALLBACK_SECONDS), m)):
        k = min(range(pieces), key=lambda j: (loads[j], j))
        bins[k].append(module)
        loads[k] += costs.get(module, FALLBACK_SECONDS)
    return [sorted(b) for b in bins]


def parse_shard(value: str) -> tuple[int, int]:
    """``"i/N"`` -> ``(i, N)`` with ``1 <= i <= N``."""
    left, sep, right = value.partition("/")
    if not sep:
        raise ValueError(f"shard {value!r} is not i/N")
    index, total = int(left), int(right)
    if not 1 <= index <= total:
        raise ValueError(f"shard {value!r} out of range")
    return index, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", choices=("pure", "compiled"), required=True)
    parser.add_argument("--pieces", type=int, required=True)
    parser.add_argument("modules", nargs="+", help="repo-relative test module paths")
    args = parser.parse_args(argv)
    costs = module_costs(args.modules, args.engine, load_durations())
    for k, piece in enumerate(plan(args.modules, args.pieces, costs), 1):
        total = sum(costs[m] for m in piece)
        print(f"piece {k}/{args.pieces}: {len(piece)} modules, {total:.0f} s")
        for module in piece:
            print(f"  {costs[module]:7.1f}  {module}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
