#!/usr/bin/env python3
"""make_s67c_reservation.py -- writes reservation_s67c.json FROM the launcher: the launcher's own sha256 and its LANE / OUT / status / RELEASE /
HOLD and the arm's seed0 / DEALS (read by sourcing it with LANE_FUNCTIONS_ONLY=1 and calling arm_spec, never typed), the reader Claude, the
host, the reservation path.  The launcher is claude_s67c_perf.final.sh when it exists (the pinned file whose sha256 is the RELEASE token),
else the draft claude_s67c_perf.sh (the pre-build packet; the record then names the draft and says so).  Refuses an existing output unless
--force.  test_s67c_packet.py checks the written record against the launcher and the reader.  Staging copies it to the host's
/root/claude_reservations/s67c.json (the reservation scans read 'seed0' and 'count').
= s66dev's make_s66dev_reservation.py with the lane, the arm (sc8p) and the authority changed.

Usage: python3 make_s67c_reservation.py [--force]"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FINAL = os.path.join(HERE, 'claude_s67c_perf.final.sh')
DRAFT = os.path.join(HERE, 'claude_s67c_perf.sh')
OUT = os.path.join(HERE, 'reservation_s67c.json')
AUTHORITY = ('https://github.com/jerryyyu/shengji/issues/1075 (board row S67c; Jerry 2026-10-25 in session: "What about trying all the non throws, '
             'I don\'t think win is enough to deploy"; the standing run authorization 2026-09-30 / 2026-10-14; no deploy authority)')


def launcher_vars(path, names):
    script = 'LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done; printf "ARM_SPEC=%s\\n" "$(arm_spec sc8p)"'
    out = subprocess.run(['bash', '-c', script, 'x', path], capture_output=True, text=True, check=True, cwd=HERE).stdout
    return dict(line.split('=', 1) for line in out.strip().splitlines())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    launcher = FINAL if os.path.exists(FINAL) else DRAFT
    v = launcher_vars(launcher, ['LANE', 'OUT', 'S', 'RELEASE', 'HOLD', 'DEALS', 'ARMS', 'TREE_HEAD_FULL', 'R', 'EXT_ENGINE_SHA'])
    seed0, cand = v['ARM_SPEC'].split()
    sha = hashlib.sha256(open(launcher, 'rb').read()).hexdigest()
    rec = {'schema': 'claude-reservation-v1', 'lane': v['LANE'], 'revision': 'r1', 'launcher': os.path.basename(launcher), 'launcher_sha256': sha,
           'launcher_state': 'final (pins filled; this sha256 is the RELEASE token)' if launcher == FINAL else 'draft (extension pins TO_BE_PINNED; regenerate after make_s67c_final.py)',
           'host': 'shengji-perf', 'tree': v['R'], 'tree_head': v['TREE_HEAD_FULL'], 'output_root': v['OUT'], 'status': v['S'], 'release': v['RELEASE'], 'hold': v['HOLD'],
           'reservation_path': f"/root/claude_reservations/{v['LANE']}.json", 'arms': v['ARMS'], 'exploiter': cand,
           'seed0': int(seed0), 'count': int(v['DEALS']), 'reader': 'Claude', 'authority_ref': AUTHORITY}
    if os.path.exists(OUT) and '--force' not in argv:
        raise SystemExit(f'REFUSING: {OUT} exists (pass --force to regenerate from the current launcher)')
    with open(OUT, 'w') as fh:
        json.dump(rec, fh, sort_keys=True)
        fh.write('\n')
    print(f'reservation_s67c.json written from {os.path.basename(launcher)} sha256 {sha} ({rec["launcher_state"]}): {json.dumps(rec, sort_keys=True)}')


if __name__ == '__main__':
    main()
