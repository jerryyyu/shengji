#!/usr/bin/env python3
"""make_reservation.py -- writes reservation_s69.json FROM the launcher: its own sha256 and its LANE / OUT / S / SEED0 / DEALS / RELEASE,
read by sourcing it with LANE_FUNCTIONS_ONLY=1 (never typed), the reader Claude, the reservation path, and the auxiliary (non-scientific)
windows the packet plays: the host rehearsal (rehearse_s69_cloud.sh's SEED0 / DEALS, read from it) and the local smoke.  Refuses an existing
output unless --force.  test_s69_packet.py checks the written record against the launcher and the reader.   (= h1a's generator.)
Usage: python3 make_reservation.py [--force]"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
LAUNCHER = os.path.join(HERE, 'claude_s69_cloud.sh')
REHEARSAL = os.path.join(HERE, 'rehearse_s69_cloud.sh')
OUT = os.path.join(HERE, 'reservation_s69.json')
AUTHORITY = ('https://github.com/jerryyyu/shengji/issues/1075 (board row S69; Jerry 2026-10-26 in Claude\'s session: "The combo and red team sound '
             'good to test" -- tests only, no deploy)')


def launcher_vars(path, names):
    script = 'LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done'
    out = subprocess.run(['bash', '-c', script, 'x', path], capture_output=True, text=True, check=True, cwd=HERE).stdout
    return dict(line.split('=', 1) for line in out.strip().splitlines())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    v = launcher_vars(LAUNCHER, ['LANE', 'OUT', 'S', 'SEED0', 'DEALS', 'RELEASE'])
    sha = hashlib.sha256(open(LAUNCHER, 'rb').read()).hexdigest()
    reh = open(REHEARSAL).read()
    m = re.search(r'^SEED0=(\d+); DEALS=(\d+);', reh, re.M)
    assert m, 'rehearse_s69_cloud.sh: no SEED0= / DEALS= line'
    rec = {'schema': 'claude-reservation-v1', 'lane': v['LANE'], 'launcher_sha256': sha, 'host': 'shengji-cloud',
           'output_root': v['OUT'], 'status': v['S'], 'release': v['RELEASE'], 'reservation_path': f"/root/claude_reservations/{v['LANE']}_r2.json", 'revision': 'r2',
           'seed0': int(v['SEED0']), 'count': int(v['DEALS']), 'reader': 'Claude', 'authority_ref': AUTHORITY,
           'auxiliary_windows': [{'purpose': 'host rehearsal r1/r2 (non-scientific)', 'seed0': 311960000, 'count': 36},
                                 {'purpose': 'host rehearsal r3, --history (non-scientific)', 'seed0': int(m.group(1)), 'count': int(m.group(2))},
                                 {'purpose': 'local smoke (non-scientific)', 'seed0': 311970000, 'count': 4}]}
    if os.path.exists(OUT) and '--force' not in argv:
        raise SystemExit(f'REFUSING: {OUT} exists (pass --force to regenerate from the current launcher)')
    with open(OUT, 'w') as fh:
        json.dump(rec, fh, sort_keys=True)
        fh.write('\n')
    print(f'reservation_s69.json written from launcher sha256 {sha}: {json.dumps(rec, sort_keys=True)}')


if __name__ == '__main__':
    main()
