#!/usr/bin/env python3
"""Regenerate ``test_durations.json`` from a CI run's recorded durations.

Every CI pytest session writes its modules' seconds under
``$SHENGJI_CI_DURATIONS_OUT`` (``pytest_session.py``) and each job uploads
them as a ``durations-*`` artifact.  This script downloads them (``gh run
download``) or reads local record directories, takes each module's largest
time per engine mode, and writes the table the shard planner reads.  Modules
the records do not mention keep their previous time; modules that no longer
exist are dropped.

Usage::

    update_durations.py --run <run id>          # download and merge
    update_durations.py --records DIR [DIR ...] # merge local record files
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
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
    source.add_argument("--run", help="GitHub Actions run id whose durations-* artifacts to merge")
    source.add_argument("--records", nargs="+", help="local directories of record files")
    parser.add_argument("--repo", default="jerryyyu/shengji")
    parser.add_argument("--out", type=Path, default=shard_plan.DURATIONS)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        directories = args.records
        if args.run:
            subprocess.run(["gh", "run", "download", args.run, "--repo", args.repo,
                            "--pattern", "durations-*", "--dir", scratch], check=True)
            directories = [scratch]
        found = read_records(directories)
    if not found:
        print("update_durations: no records found", file=sys.stderr)
        return 1
    table = merge(shard_plan.load_durations(args.out), found)
    payload = {"source": f"run {args.run}" if args.run else "local records", "modes": table}
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    for engine, modules in table.items():
        print(f"{engine}: {len(modules)} modules, {sum(modules.values()):.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
