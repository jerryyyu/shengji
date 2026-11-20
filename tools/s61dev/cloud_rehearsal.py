"""Bounded resource rehearsal on reserved smoke/bench deals; no outcome report."""
import concurrent.futures
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time


def worker(task):
    import exploit_duel_s61 as duel
    seed, index, env = task
    records = [duel.play_mirror("identity", seed, m, False, (), env,
                                duel.round_plan("r2", index)) for m in (0, 1)]
    result = {}
    for side, worlds in (("ex", 256), ("r45", 64)):
        hist = [h for r in records for h in r["dhist"][side]]
        secs = [s for r in records for s in r["dsecs"][side]]
        result[side] = dict(decisions=len(secs), max_seconds=max(secs),
                            play_fallbacks=sum(h[18] != worlds for h in hist),
                            belief_fallbacks=sum(bool(h[4]) for h in hist))
    return dict(seed=seed, metrics=result)


def main():
    launcher, output = map(Path, sys.argv[1:])
    text = launcher.read_text()
    env_line = next(s for s in text.splitlines() if s.startswith('EX_ENV="'))
    env = tuple(sorted(tuple(kv.split("=", 1)) for kv in env_line.split('"')[1].split()))
    seeds = [217960000, 217960001, *range(217960010, 217960022)]
    started = time.monotonic()
    peak = 0
    records = []
    with output.open("x") as fh:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=14, mp_context=multiprocessing.get_context("spawn")) as pool:
            pending = {pool.submit(worker, (seed, i, env)) for i, seed in enumerate(seeds)}
            while pending:
                done, pending = concurrent.futures.wait(pending, timeout=10,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                lines = subprocess.check_output(["ps", "-eo", "pgid=,rss="], text=True)
                rss = sum(int(rss) for group, rss in (s.split() for s in lines.splitlines())
                          if int(group) == os.getpgrp())
                peak = max(peak, rss)
                for future in done:
                    record = future.result()
                    records.append(record)
                    fh.write(json.dumps(record) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                print(json.dumps(dict(completed=len(records), total=14,
                    elapsed_seconds=round(time.monotonic()-started, 1),
                    aggregate_rss_kb=rss, peak_aggregate_rss_kb=peak)), flush=True)
        summary = dict(terminal="REHEARSAL_DONE", deals=len(records), workers=14,
                       wall_seconds=time.monotonic()-started, peak_aggregate_rss_kb=peak)
        fh.write(json.dumps(summary) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
