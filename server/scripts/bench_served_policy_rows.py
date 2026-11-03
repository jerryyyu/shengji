#!/usr/bin/env python3
"""Measure one ``served_policy_rows`` build (or one partition of it) as it runs.

Takes exactly the producer's arguments plus ``--report FILE`` and runs the real
``produce`` in this process, recording wall time, rows and records per second,
every chunk flush (rows, bytes on disk, seconds to encode and write), the
parent's peak RSS and the peak of the summed RSS of the parent and all its
worker processes (sampled through the portable host census every
``--sample-seconds``; the sum is an upper bound: a page shared by several
processes counts once per process, and the macOS census includes its own probe).

    python scripts/bench_served_policy_rows.py --data STORE --out DIR \
        --encoder-version 2 --workers 8 [--partition I/N] --report bench.json
"""
from __future__ import annotations

import json
import os
import platform
import resource
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.ops import hostinfo
from shengji.train import served_policy_rows as spr  # noqa: E402


def _tree_rss_kib(root: int) -> tuple[int, int, int]:
    """``(parent KiB, summed KiB of root and descendants, descendant count)``."""
    table = hostinfo.process_table()
    if root not in table or table[root].rss_bytes <= 0:
        raise hostinfo.HostProbeError("RSS census lacks a live benchmark root")
    children: dict[int, list[int]] = {}
    for row in table.values():
        children.setdefault(row.ppid, []).append(row.pid)
    total, seen, stack = 0, set(), [root]
    while stack:
        pid = stack.pop()
        if pid in seen:
            raise hostinfo.HostProbeError("RSS census contains a parent cycle")
        seen.add(pid)
        total += table[pid].rss_bytes
        stack.extend(children.get(pid, []))
    return table[root].rss_bytes // 1024, total // 1024, len(seen) - 1


class Sampler(threading.Thread):
    def __init__(self, interval: float):
        super().__init__(daemon=True)
        self.interval = float(interval)
        if not 0 < self.interval < float("inf"):
            raise ValueError("sample interval must be positive and finite")
        self.stop = threading.Event()
        self.error: Exception | None = None
        self.peak_parent = self.peak_tree = self.peak_workers = self.samples = 0

    def run(self) -> None:
        pid = os.getpid()
        try:
            while True:
                parent, tree, workers = _tree_rss_kib(pid)
                self.peak_parent = max(self.peak_parent, parent)
                self.peak_tree = max(self.peak_tree, tree)
                self.peak_workers = max(self.peak_workers, workers)
                self.samples += 1
                if self.stop.wait(self.interval):
                    break
        except Exception as exc:
            self.error = exc

    def join(self, timeout=None) -> None:
        super().join(timeout)
        if not self.is_alive() and self.error is not None:
            raise hostinfo.HostProbeError("RSS sampling failed; measurement incomplete") from self.error


def _maxrss_mib(who: int) -> float:
    raw = resource.getrusage(who).ru_maxrss
    return raw / 2 ** 20 if sys.platform == "darwin" else raw / 2 ** 10   # bytes on macOS, KiB on Linux


def main(argv: list[str] | None = None) -> int:
    parser = spr.build_parser()
    parser.prog = "bench_served_policy_rows"
    parser.add_argument("--report", default=None, help="also write the JSON report here")
    parser.add_argument("--sample-seconds", type=float, default=0.25)
    a = parser.parse_args(argv)
    flushes: list[dict] = []
    real_write = spr.write_chunk

    def timed_write(out_dir, index, X, Y, meta):
        t0 = time.perf_counter()
        entry = real_write(out_dir, index, X, Y, meta)
        flushes.append({"index": index, "rows": entry["rows"], "seconds": round(time.perf_counter() - t0, 3),
                        "bytes": (Path(out_dir) / entry["file"]).stat().st_size})
        return entry

    sampler = Sampler(a.sample_seconds)
    spr.write_chunk = timed_write
    sampler.start()
    t0 = time.perf_counter()
    try:
        summary = spr.produce(a.out, a.data, version=a.encoder_version,
                              exclude_seeds=[spr.parse_seed_interval(s) for s in a.exclude_seeds],
                              exclude_deal_keys=a.exclude_deal_keys, chunk_rows=a.chunk_rows,
                              max_rows=a.max_rows, workers=a.workers, seed=a.seed,
                              partition=None if a.partition is None else spr.parse_partition(a.partition),
                              replace_incomplete=a.replace_incomplete, lead_types=a.lead_types,
                              hard_lead_types=a.hard_lead_types,
                              drop_hard_lcc_lead_types=a.drop_hard_lcc_lead_types)
    except spr.ServedPolicyRowsError as exc:
        print(f"bench_served_policy_rows: {exc}", file=sys.stderr)
        return 2
    finally:
        wall = time.perf_counter() - t0
        sampler.stop.set()
        try:
            sampler.join()
        finally:
            spr.write_chunk = real_write
    report = {
        "host": platform.node(), "platform": platform.platform(), "cpus": os.cpu_count(),
        "argv": list(sys.argv[1:] if argv is None else argv),
        "workers": a.workers, "chunk_rows": a.chunk_rows, "partition": a.partition,
        "wall_seconds": round(wall, 3), "rows": summary["rows"], "records": summary["records"],
        "play_records": summary["play_records"],
        "rows_per_second": round(summary["rows"] / wall, 2) if wall > 0 else None,
        "records_per_second": round(summary["records"] / wall, 2) if wall > 0 else None,
        "chunks": len(flushes), "flushes": flushes,
        "flush_seconds_total": round(sum(f["seconds"] for f in flushes), 3),
        "chunk_bytes_total": sum(f["bytes"] for f in flushes),
        "peak_rss_mib": {
            "parent_sampled": round(sampler.peak_parent / 1024, 1),
            "parent_plus_workers_sampled": round(sampler.peak_tree / 1024, 1),
            "parent_getrusage": round(_maxrss_mib(resource.RUSAGE_SELF), 1),
            "largest_reaped_child_getrusage": round(_maxrss_mib(resource.RUSAGE_CHILDREN), 1)},
        "peak_worker_processes": sampler.peak_workers, "rss_samples": sampler.samples,
        "excluded_rows": summary["excluded_rows"], "target_rows": summary["target_rows"],
    }
    text = json.dumps(report, indent=1, sort_keys=True)
    if a.report:
        Path(a.report).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
