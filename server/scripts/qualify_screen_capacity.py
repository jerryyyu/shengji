"""Bounded capacity wrapper for the real served-policy screen queue.

Dry-run by default. Host admission, policy environment, exposure and RELEASE
belong to the reviewed outer packet. This script confers no launch authority.
Outcomes stay in the queue output; only resource and completion metadata are
reported. A timeout preserves partial shards and never retries them.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def queue_command(args):
    return [sys.executable, '-B', '-m', 'shengji.train.cwv_screen_queue',
            '--arm-policy', args.policy, '--out', str(args.out / 'queue'),
            '--name', 'capacity', '--seeds', str(args.seed),
            '--clusters', str(args.clusters), '--workers', str(args.workers),
            '--decision-deadline', '300']


def group_sample(pgid):
    """Concurrent RSS sum, not max(single-worker RSS) or parent-only RSS."""
    rows = subprocess.check_output(['ps', '-axo', 'pgid=,rss='], text=True, timeout=5)
    members = [int(rss) for group, rss in (line.split() for line in rows.splitlines())
               if int(group) == pgid]
    return {'processes': len(members), 'rss_bytes': sum(members) * 1024}


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def measure(command, out, seconds, *, poll_seconds=.25):
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    reason, rc, peak, samples = 'error', None, 0, 0
    child = None
    try:
        with (out / 'producer.log').open('x') as log, (out / 'resources.jsonl').open('x') as trace:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            while True:
                sample = group_sample(child.pid)
                peak = max(peak, sample['rss_bytes'])
                samples += 1
                trace.write(json.dumps({'elapsed_seconds': time.monotonic() - start,
                                        **sample}) + '\n')
                trace.flush()
                rc = child.poll()
                if rc is not None:
                    reason = 'exit'
                    break
                if time.monotonic() - start >= seconds:
                    reason = 'timeout'
                    break
                time.sleep(poll_seconds)
    finally:
        if child is not None:
            # Also drain descendants after an unexpected parent-only exit.
            kill_group(child.pid)
            rc = child.wait()
        elapsed = time.monotonic() - start
        result = {'schema': 'screen-capacity-v1', 'command': command,
                  'reason': reason, 'returncode': rc, 'wall_seconds': elapsed,
                  'sampled_group_peak_rss_bytes': peak, 'samples': samples,
                  'sampling_interval_seconds': poll_seconds,
                  'complete': reason == 'exit' and rc == 0,
                  'note': 'Sampled concurrent RSS; can miss sub-interval peaks. '
                          'No strength inference. Queue enforces complete work on rc0.'}
        (out / 'capacity.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy', required=True)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--seed', required=True, type=int)
    p.add_argument('--clusters', type=int, default=1)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--seconds', type=int, default=900)
    p.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    if not (args.seed >= 0 and 1 <= args.workers <= args.clusters <= 28
            and 1 <= args.seconds <= 1800):
        p.error('require seed>=0, 1<=workers<=clusters<=28, 1<=seconds<=1800')
    args.out = args.out.resolve()
    command = queue_command(args)
    if not args.run:
        print(json.dumps({'command': command, 'seconds': args.seconds, 'launched': False}))
        return 0
    result = measure(command, args.out, args.seconds)
    print(json.dumps(result))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
