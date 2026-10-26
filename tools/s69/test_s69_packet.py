#!/usr/bin/env python3
"""s69 packet consistency (this Mac; reads only): the launcher, the reader, the reservation, the staged-file pins and the packet's own
records agree, each value read from its source (the launcher by sourcing it with LANE_FUNCTIONS_ONLY=1, never typed here).
  - the reservation names the launcher's sha256, lane, OUT, S, RELEASE, SEED0, DEALS, reader Claude, the rehearsal window read from the
    wrapper; the reader's TRUSTED names the same sha, root, status and reservation path; the reader's names / EX_ENV / seed0 / deals /
    workers / stop equal the launcher's;
  - DUEL_SHA / HYP_SHA are the packet files' shas, and the reader's PINNED shas are the packet helper copies' shas (each = fl-pilot's
    reader_lib copy, so the copies are the reviewed bytes), the S61 reference's sha is S61_REFERENCE_SHA256 and its source is the archived
    S61 result.json at the receipt's result_sha256;
  - the windows: the lane, the rehearsal and the smoke are disjoint, and the launcher's tree head is origin/main's commit d33bfd70 whose
    fly.toml has the launcher's FLY_SHA and SHENGJI_BOT;
  - the staged-layout test's saved run passed and is newer than the test; the reader / launcher / battery saved runs passed.
Usage: python3 test_s69_packet.py > test_s69_packet.out"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

H = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(H))
LIB = '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/reader_lib'
S61_RESULT = os.path.expanduser('~/shengji-archive/2026-09-13/readouts/s61dev/result.json')
S61_RECEIPT = os.path.expanduser('~/shengji-archive/2026-09-13/readouts/s61dev/receipt.json')
fails = 0


def check(label, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), label, str(detail)[:240])
    fails += int(not ok)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def launcher_vars(names):
    script = 'LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done'
    out = subprocess.run(['bash', '-c', script, 'x', os.path.join(H, 'claude_s69_cloud.sh')], capture_output=True, text=True, check=True, cwd=H).stdout
    return dict(line.split('=', 1) for line in out.strip().split('\n'))


L = os.path.join(H, 'claude_s69_cloud.sh')
v = launcher_vars(['LANE', 'OUT', 'S', 'RELEASE', 'SEED0', 'DEALS', 'WORKERS', 'KILL_AFTER', 'BACKSTOP', 'COMBO_NAME', 'CAND_NAME', 'EX_ENV', 'DUEL', 'DUEL_SHA',
                   'HYP', 'HYP_SHA', 'TREE_HEAD_FULL', 'FLY_SHA', 'R'])
check('the launcher runs the producer with --history (r2)', '--round-plan "$PLAN" --history --out' in open(L).read())
lsha = sha(L)
res = json.load(open(os.path.join(H, 'reservation_s69.json')))
reh = open(os.path.join(H, 'rehearse_s69_cloud.sh')).read()
m = re.search(r'^SEED0=(\d+); DEALS=(\d+);', reh, re.M)
check('reservation = the launcher (sha, lane, OUT, S, RELEASE, SEED0, DEALS) with reader Claude and the rehearsal window read from the wrapper',
      res['launcher_sha256'] == lsha and res['lane'] == v['LANE'] == 's69' and res['output_root'] == v['OUT'] and res['status'] == v['S'] and res['release'] == v['RELEASE']
      and res['seed0'] == int(v['SEED0']) and res['count'] == int(v['DEALS']) and res['reader'] == 'Claude' and res['reservation_path'] == '/root/claude_reservations/s69_r2.json' and res['revision'] == 'r2'
      and m and res['auxiliary_windows'][1]['seed0'] == int(m.group(1)) and res['auxiliary_windows'][1]['count'] == int(m.group(2))
      and res['auxiliary_windows'][0] == {'purpose': 'host rehearsal r1/r2 (non-scientific)', 'seed0': 311960000, 'count': 36}, res)
spec = importlib.util.spec_from_file_location('s69_read', os.path.join(H, 's69_read.py')); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
check("the reader's TRUSTED = the launcher's sha / OUT / S and the reservation path; host shengji-cloud",
      rd.TRUSTED == dict(lane='s69', launcher_sha256=lsha, host='shengji-cloud', root=v['OUT'], status=v['S'], reservation=res['reservation_path']), rd.TRUSTED)
check("the reader's names, EX_ENV, seed0, deals, workers and stop = the launcher's",
      (rd.R48, rd.CAND, rd.EX_ENV, rd.SEED0, rd.DEALS, rd.WORKERS, rd.KILL_AFTER, rd.BACKSTOP)
      == (v['COMBO_NAME'], v['CAND_NAME'], v['EX_ENV'], int(v['SEED0']), int(v['DEALS']), int(v['WORKERS']), int(v['KILL_AFTER']), int(v['BACKSTOP'])))
check('DUEL / HYP pins = the packet files (staged to /root/claude-s69/)',
      v['DUEL'] == '/root/claude-s69/exploit_duel_s61.py' and v['DUEL_SHA'] == sha(os.path.join(H, 'exploit_duel_s61.py'))
      and v['HYP'] == '/root/claude-s69/hypotheses.py' and v['HYP_SHA'] == sha(os.path.join(H, 'hypotheses.py')), (v['DUEL_SHA'], v['HYP_SHA']))
pins = {n: sha(os.path.join(H, f'{n}.py')) for n in rd.PINNED}
lib = {n: sha(os.path.join(LIB, f'{n}.py')) for n in rd.PINNED}
check("the reader's PINNED shas = the packet helper copies = fl-pilot/reader_lib's files", pins == rd.PINNED == lib, (pins, lib))
check('the battery and the validity copy = fl-pilot/reader_lib', sha(os.path.join(H, 'adversarial_battery.py')) == sha(os.path.join(LIB, 'adversarial_battery.py'))
      and sha(os.path.join(H, 'validity.py')) == sha(os.path.join(LIB, 'validity.py')))
ref = json.load(open(os.path.join(H, 's61_reference.json')))
rec = json.load(open(S61_RECEIPT))
check("the S61 reference: its sha is the reader's S61_REFERENCE_SHA256; its source is the archived S61 result.json at the receipt's result_sha256",
      sha(os.path.join(H, 's61_reference.json')) == rd.S61_REFERENCE_SHA256 and ref['source']['sha256'] == sha(S61_RESULT) == rec['result_sha256']
      and ref['levels'] == json.load(open(S61_RESULT))['levels'], (ref['source'], rec['result_sha256']))
wins = [(int(v['SEED0']), int(v['DEALS'])), (311960000, 36), (311970000, 4)]   # r3's 12 deals lie inside the 36-deal rehearsal window
check('the r3 rehearsal window lies inside the r1/r2 rehearsal window', 311960000 <= int(m.group(1)) and int(m.group(1)) + int(m.group(2)) <= 311960036, m.groups())
check('the lane, rehearsal and smoke windows are pairwise disjoint', all(a + n <= b or b + k <= a for i, (a, n) in enumerate(wins) for (b, k) in wins[i + 1:]), wins)
fly = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:fly.toml"], capture_output=True, check=True).stdout
main = subprocess.run(['git', '-C', REPO, 'merge-base', '--is-ancestor', v['TREE_HEAD_FULL'], 'origin/main'], capture_output=True).returncode
bot = re.search(rb"^ *SHENGJI_BOT *= *'([^']*)'", fly, re.M).group(1).decode()
check("the tree head is on origin/main and its fly.toml is the launcher's FLY_SHA serving COMBO_NAME", main == 0 and hashlib.sha256(fly).hexdigest() == v['FLY_SHA'] and bot == v['COMBO_NAME'], (main, bot))
for out, test, want in (('test_s69_stage.out', 'test_s69_stage.sh', 'ALL PASS'), ('test_s69_read.out', 'test_s69_read.py', 'ALL PASS'),
                        ('test_s69_launcher.out', 'test_s69_launcher.sh', 'ALL PASS'), ('battery_s69.out', 'battery_s69_adapter.py', 'BATTERY PASS: 28 of 28')):
    o, t = os.path.join(H, out), os.path.join(H, test)
    text = open(o).read() if os.path.isfile(o) else ''
    lines = text.splitlines()
    ok = want in text and not any(re.match(r'\s*FAIL\b', x) for x in lines) and os.path.getmtime(o) >= os.path.getmtime(t)
    if out != 'battery_s69.out':
        ok = ok and lines and lines[-1] == 'rc=0'
    check(f'{out}: a passing saved run, newer than {test}', ok, (lines[-1] if lines else 'missing'))
bat = open(os.path.join(H, 'battery_s69.out')).read()
check("the battery ran on the reader and fixture as they are now (its header shas)", f"sha256 {sha(os.path.join(H, 's69_read.py'))}" in bat and f"sha256 {sha(os.path.join(H, 'test_s69_read.py'))}" in bat)
print('ALL PASS' if not fails else f'{fails} FAILED')
sys.exit(int(bool(fails)))
