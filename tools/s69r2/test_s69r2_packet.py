#!/usr/bin/env python3
"""s69r2 packet consistency (= test_s69_packet.py with the s69r2 names; no rehearsal wrapper; the windows: the s69r2 block disjoint from
the consumed s69 block and from s69's rehearsal / smoke windows).  s69's text:
s69 packet consistency (this Mac; reads only): the launcher, the reader, the reservation, the staged-file pins and the packet's own
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
Usage: python3 test_s69r2_packet.py > test_s69r2_packet.out"""
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
    out = subprocess.run(['bash', '-c', script, 'x', os.path.join(H, 'claude_s69r2_cloud.sh')], capture_output=True, text=True, check=True, cwd=H).stdout
    return dict(line.split('=', 1) for line in out.strip().split('\n'))


L = os.path.join(H, 'claude_s69r2_cloud.sh')
v = launcher_vars(['LANE', 'OUT', 'S', 'RELEASE', 'SEED0', 'DEALS', 'WORKERS', 'KILL_AFTER', 'BACKSTOP', 'COMBO_NAME', 'CAND_NAME', 'EX_ENV', 'DUEL', 'DUEL_SHA',
                   'HYP', 'HYP_SHA', 'TREE_HEAD_FULL', 'FLY_SHA', 'R'])
check('the launcher runs the producer with --history (r2)', '--round-plan "$PLAN" --history --out' in open(L).read())
lsha = sha(L)
res = json.load(open(os.path.join(H, 'reservation_s69r2.json')))
check('reservation = the launcher (sha, lane, OUT, S, RELEASE, SEED0, DEALS) with reader Claude, path s69r2.json, the consumed s69 block named',
      res['launcher_sha256'] == lsha and res['lane'] == v['LANE'] == 's69r2' and res['output_root'] == v['OUT'] and res['status'] == v['S'] and res['release'] == v['RELEASE']
      and res['seed0'] == int(v['SEED0']) and res['count'] == int(v['DEALS']) and res['reader'] == 'Claude' and res['reservation_path'] == '/root/claude_reservations/s69r2.json'
      and res['consumed_predecessor'] == {'lane': 's69', 'seed0': 311060910, 'count': 600, 'verdict': 'DEV_INVALID'}, res)
spec = importlib.util.spec_from_file_location('s69r2_read', os.path.join(H, 's69r2_read.py')); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
check("the reader's TRUSTED = the launcher's sha / OUT / S and the reservation path; host shengji-cloud",
      rd.TRUSTED == dict(lane='s69r2', launcher_sha256=lsha, host='shengji-cloud', root=v['OUT'], status=v['S'], reservation=res['reservation_path']), rd.TRUSTED)
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
wins = [(int(v['SEED0']), int(v['DEALS'])), (311060910, 600), (311960000, 36), (311970000, 4)]   # s69r2's block; s69's consumed block, rehearsal and smoke windows
check("the s69r2 block is disjoint from the consumed s69 block and s69's rehearsal / smoke windows", all(a + n <= b or b + k <= a for (b, k) in wins[1:] for (a, n) in wins[:1]), wins)
check('the ceilings: ONE mapping, play 0.1% / belief 0 / bury 1% / declare 1%', rd.BAR['ceilings'] == dict(play_fallback=0.001, belief_fallback=0, bury_fallback=0.01, declare_abandon=0.01), rd.BAR['ceilings'])
fly = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:fly.toml"], capture_output=True, check=True).stdout
main = subprocess.run(['git', '-C', REPO, 'merge-base', '--is-ancestor', v['TREE_HEAD_FULL'], 'origin/main'], capture_output=True).returncode
bot = re.search(rb"^ *SHENGJI_BOT *= *'([^']*)'", fly, re.M).group(1).decode()
check("the tree head is on origin/main and its fly.toml is the launcher's FLY_SHA serving COMBO_NAME", main == 0 and hashlib.sha256(fly).hexdigest() == v['FLY_SHA'] and bot == v['COMBO_NAME'], (main, bot))
for out, test, want in (('test_s69r2_stage.out', 'test_s69r2_stage.sh', 'ALL PASS'), ('test_s69r2_read.out', 'test_s69r2_read.py', 'ALL PASS'),
                        ('test_s69r2_launcher.out', 'test_s69r2_launcher.sh', 'ALL PASS'), ('battery_s69r2.out', 'battery_s69r2_adapter.py', 'BATTERY PASS: 28 of 28')):
    o, t = os.path.join(H, out), os.path.join(H, test)
    text = open(o).read() if os.path.isfile(o) else ''
    lines = text.splitlines()
    ok = want in text and not any(re.match(r'\s*FAIL\b', x) for x in lines) and os.path.getmtime(o) >= os.path.getmtime(t)
    if out != 'battery_s69r2.out':
        ok = ok and lines and lines[-1] == 'rc=0'
    check(f'{out}: a passing saved run, newer than {test}', ok, (lines[-1] if lines else 'missing'))
bat = open(os.path.join(H, 'battery_s69r2.out')).read()
check("the battery ran on the reader and fixture as they are now (its header shas)", f"sha256 {sha(os.path.join(H, 's69r2_read.py'))}" in bat and f"sha256 {sha(os.path.join(H, 'test_s69r2_read.py'))}" in bat)
print('ALL PASS' if not fails else f'{fails} FAILED')
sys.exit(int(bool(fails)))
