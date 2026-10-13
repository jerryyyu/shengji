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


def group_drained(pgid):
    rows = subprocess.check_output(['ps', '-axo', 'pgid=,stat='], text=True, timeout=5)
    return not any(int(group) == pgid and not state.startswith('Z')
                   for group, state in (line.split() for line in rows.splitlines()))


def measure(command, out, seconds, *, poll_seconds=.25, holds=()):
    if any(os.path.lexists(path) for path in holds):
        raise RuntimeError('HOLD present before dispatch')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    reason, rc, peak, samples = 'error', None, 0, 0
    child = None
    stopped = []
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda signum, frame: stopped.append(signum))
    drained = False
    try:
        with (out / 'producer.log').open('x') as log, (out / 'resources.jsonl').open('x') as trace:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            while True:
                if stopped or any(os.path.lexists(path) for path in holds):
                    reason = 'signal' if stopped else 'hold'
                    break
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
            deadline = time.monotonic() + 10
            try:
                while not (drained := group_drained(child.pid)) and time.monotonic() < deadline:
                    time.sleep(.05)
            except (OSError, subprocess.SubprocessError, ValueError):
                drained = False  # Unknown census must not permit host release.
        else:
            drained = True
        elapsed = time.monotonic() - start
        result = {'schema': 'screen-capacity-v1', 'command': command,
                  'reason': reason, 'returncode': rc, 'wall_seconds': elapsed,
                  'sampled_group_peak_rss_bytes': peak, 'samples': samples,
                  'sampling_interval_seconds': poll_seconds,
                  'child_group_drained': drained,
                  'complete': reason == 'exit' and rc == 0 and drained,
                  'note': 'Sampled concurrent RSS; can miss sub-interval peaks. '
                          'No strength inference. Queue enforces complete work on rc0.'}
        try:
            (out / 'capacity.json').write_text(json.dumps(result, indent=2) + '\n')
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
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
    p.add_argument('--hold', type=Path, action='append', default=[])
    args = p.parse_args(argv)
    if not (args.seed >= 0 and 1 <= args.workers <= args.clusters <= 28
            and 1 <= args.seconds <= 1800):
        p.error('require seed>=0, 1<=workers<=clusters<=28, 1<=seconds<=1800')
    args.out = args.out.resolve()
    command = queue_command(args)
    if not args.run:
        print(json.dumps({'command': command, 'seconds': args.seconds, 'launched': False}))
        return 0
    result = measure(command, args.out, args.seconds, holds=args.hold)
    print(json.dumps(result))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
