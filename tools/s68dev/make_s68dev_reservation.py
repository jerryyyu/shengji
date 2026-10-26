#!/usr/bin/env python3
"""make_s68dev_reservation.py -- writes reservation_s68dev.json FROM the launcher: the launcher's own sha256 and its LANE / OUT / status / RELEASE /
HOLD and each arm's seed0 / exploiter / env with DEALS (read by sourcing it with LANE_FUNCTIONS_ONLY=1 and calling arm_spec / arm_env, never typed), the reader Claude, the
host, the reservation path.  The launcher is claude_s68dev_perf.final.sh when it exists (the pinned file whose sha256 is the RELEASE token),
else the draft claude_s68dev_perf.sh (the pre-build packet; the record then names the draft and says so).  Refuses an existing output unless
--force.  test_s68dev_packet.py checks the written record against the launcher and the reader.  Staging copies it to the host's
/root/claude_reservations/s68dev.json (the reservation scans read 'seeds' and 'count', the count per seed block).
= s67c's make_s67c_reservation.py with the lane, the two arms ('seeds' = both blocks) and the authority changed.

Usage: python3 make_s68dev_reservation.py [--force]"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FINAL = os.path.join(HERE, 'claude_s68dev_perf.final.sh')
DRAFT = os.path.join(HERE, 'claude_s68dev_perf.sh')
OUT = os.path.join(HERE, 'reservation_s68dev.json')
AUTHORITY = ('https://github.com/jerryyyu/shengji/issues/1075 (board row S68; Jerry 2026-10-26 in Claude\'s session: "The combo and red team sound good to test"; '
             'testing only; the standing run authorization 2026-09-30 / 2026-10-14; no release or deploy authority)')


def launcher_vars(path, names):
    script = 'LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done; for a in $ARMS; do printf "ARM_SPEC_%s=%s\\n" "$a" "$(arm_spec $a)"; printf "ARM_ENV_%s=%s\\n" "$a" "$(arm_env $a)"; done'
    out = subprocess.run(['bash', '-c', script, 'x', path], capture_output=True, text=True, check=True, cwd=HERE).stdout
    return dict(line.split('=', 1) for line in out.strip().splitlines())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    launcher = FINAL if os.path.exists(FINAL) else DRAFT
    v = launcher_vars(launcher, ['LANE', 'OUT', 'S', 'RELEASE', 'HOLD', 'DEALS', 'ARMS', 'TREE_HEAD_FULL', 'R', 'EXT_ENGINE_SHA'])
    arms = v['ARMS'].split()
    spec = {a: dict(zip(('seed0', 'exploiter'), v[f'ARM_SPEC_{a}'].split()), env=v[f'ARM_ENV_{a}']) for a in arms}
    sha = hashlib.sha256(open(launcher, 'rb').read()).hexdigest()
    rec = {'schema': 'claude-reservation-v1', 'lane': v['LANE'], 'revision': 'r1', 'launcher': os.path.basename(launcher), 'launcher_sha256': sha,
           'launcher_state': 'final (pins filled; this sha256 is the RELEASE token)' if launcher == FINAL else 'draft (extension pins TO_BE_PINNED; regenerate after make_s68dev_final.py)',
           'host': 'shengji-perf', 'tree': v['R'], 'tree_head': v['TREE_HEAD_FULL'], 'output_root': v['OUT'], 'status': v['S'], 'release': v['RELEASE'], 'hold': v['HOLD'],
           'reservation_path': f"/root/claude_reservations/{v['LANE']}.json", 'arms': v['ARMS'],
           'arm_spec': {a: dict(seed0=int(spec[a]['seed0']), exploiter=spec[a]['exploiter'], exploiter_env=spec[a]['env']) for a in arms},
           'seeds': [int(spec[a]['seed0']) for a in arms], 'count': int(v['DEALS']), 'reader': 'Claude', 'authority_ref': AUTHORITY}
    if os.path.exists(OUT) and '--force' not in argv:
        raise SystemExit(f'REFUSING: {OUT} exists (pass --force to regenerate from the current launcher)')
    with open(OUT, 'w') as fh:
        json.dump(rec, fh, sort_keys=True)
        fh.write('\n')
    print(f'reservation_s68dev.json written from {os.path.basename(launcher)} sha256 {sha} ({rec["launcher_state"]}): {json.dumps(rec, sort_keys=True)}')


if __name__ == '__main__':
    main()
