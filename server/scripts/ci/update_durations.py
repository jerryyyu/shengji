#!/usr/bin/env python3
"""Regenerate ``test_durations.json`` from a CI run's recorded durations.

Every CI pytest session writes its modules' seconds under
``$SHENGJI_CI_DURATIONS_OUT`` (``pytest_session.py``) and each job uploads
them as a ``durations-*`` artifact.  This script downloads them (``gh run
download``) or reads local record directories, one directory per run.  Within
a run a module's time is its largest record per engine mode; across runs it is
the median of those, so one slow runner does not move the plan.  It writes the
table the shard planner reads.  Modules the records do not mention keep their
previous time; modules that no longer exist are dropped.

Usage::

    update_durations.py --run <run id> [<run id> ...]  # download and merge
    update_durations.py --records DIR [DIR ...]        # merge local record files
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shard_plan  # noqa: E402


def read_records(directories) -> dict[str, dict[str, float]]:
    found: dict[str, dict[str, float]] = {}
    for directory in directories:
        for path in sorted(Path(directory).rglob("*.json")):
            try:
                record = json.loads(path.read_text())
                engine, modules = record["engine"], record["modules"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            table = found.setdefault(str(engine), {})
            for module, seconds in modules.items():
                table[module] = max(table.get(module, 0.0), float(seconds))
    return found


def median_of_runs(runs) -> dict[str, dict[str, float]]:
    """Per engine and module, the median over the runs that recorded it."""
    seen: dict[str, dict[str, list[float]]] = {}
    for found in runs:
        for engine, modules in found.items():
            for module, seconds in modules.items():
                seen.setdefault(engine, {}).setdefault(module, []).append(seconds)
    return {engine: {m: statistics.median(v) for m, v in modules.items()}
            for engine, modules in seen.items()}


def merge(previous: dict[str, dict[str, float]], found: dict[str, dict[str, float]],
          root: Path = shard_plan.REPO) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for engine in sorted(set(previous) | set(found)):
        table = {**previous.get(engine, {}), **found.get(engine, {})}
        out[engine] = {m: round(s, 1) for m, s in sorted(table.items()) if (root / m).is_file()}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", nargs="+", help="GitHub Actions run ids whose durations-* artifacts to merge")
    source.add_argument("--records", nargs="+", help="local directories of record files, one per run")
    parser.add_argument("--repo", default="jerryyyu/shengji")
    parser.add_argument("--out", type=Path, default=shard_plan.DURATIONS)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        directories = args.records
        if args.run:
            directories = []
            for run in args.run:
                target = Path(scratch) / run
                subprocess.run(["gh", "run", "download", run, "--repo", args.repo,
                                "--pattern", "durations-*", "--dir", str(target)], check=True)
                directories.append(target)
        found = median_of_runs([read_records([d]) for d in directories])
    if not found:
        print("update_durations: no records found", file=sys.stderr)
        return 1
    table = merge(shard_plan.load_durations(args.out), found)
    source = f"median of runs {' '.join(args.run)}" if args.run else "local records"
    payload = {"source": source, "modes": table}
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    for engine, modules in table.items():
        print(f"{engine}: {len(modules)} modules, {sum(modules.values()):.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
