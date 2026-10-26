#!/usr/bin/env python3
"""test_s68dev_packet.py -- the packet's cross-file pins hold: the reservation is generated FROM the launcher and this test refuses the packet
when any pin is off.

  1. sha256(the launcher the reservation names: claude_s68dev_perf.final.sh when present, else the draft) == reservation_s68dev.json's;
     the reservation's reader is Claude; its lane / output_root / status / release / hold / tree / tree_head / seeds / count / arm_spec
     equal the launcher's LANE / OUT / S / RELEASE / HOLD / R / TREE_HEAD_FULL / arm_spec / arm_env / DEALS (sourced, never typed);
  2. the launcher's DUEL_SHA / HYP_SHA / ADAPTER_SHA are the sha256 of the packet's files (= s67c's final launcher's DUEL / HYP pins and
     s66b's ADAPTER pin); DUEL / HYP / ADAPTER all sit in /root/claude-s68dev/; CAND_SHA is the sha256 of singleton_challenger.py at
     TREE_HEAD_FULL (git show) and of the local candidate worktree's copy; the worktree is at TREE_HEAD_FULL, which contains claude/s68-bwc
     and #1156's 39d514cc; each arm's env words start with the adapter's SENTINEL; 14 workers, r2, DEALS 3920 = 14 x 280;
  3. the two arm blocks and the rehearsal block are disjoint from each other and from s67c / s66b / s66dev;
  4. the reader: DEF_NAME == COMBO_NAME == fly.toml's SHENGJI_BOT at the tree head (and FLY_SHA); ARM_SPEC seed0 / cand / env == arm_spec /
     arm_env; ARM_ORDER == ARMS; TERMINAL == the launcher's final say; the DEV start text the reader binds == the launcher's say form ==
     the fixture's START_OF; PLAY_WORLDS / EXPLOITER_BUDGET_S per arm == the arms' env; the bar (+0.030, CI lower > 0, zero ceilings, 3 s);
     PINNED == the packet's reader_lib copies == fl-pilot/reader_lib's (incl. compare_runs); TRUSTED == the launcher's paths; the s66b
     reference and the power note;
  5. the pins: the final launcher differs from the draft in the pin line only (or, before the build, the pin rehearsal shows it), and the
     final reader in its TRUSTED_LAUNCHER_SHA256 line only;
  6. staging: the remote form, the guards, the 8-file tree phase incl. compare_runs; the EXECUTED staged-layout test is ALL PASS.
= s67c's test_s67c_packet.py restructured for two arms (per-arm env, worlds and budgets) and the candidate tree.

Usage: python3 test_s68dev_packet.py"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from s68dev_spec import ARMS as SPEC_ARMS  # noqa: E402

LIB = os.path.join(HERE, 'reader_lib')
FL_LIB = '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/reader_lib'
REPO = '/Users/jerryyu/Projects/shengji'
WT = '/Users/jerryyu/Projects/shengji-wt/claude-s68-cand'
fails = 0


def check(ok, msg):
    global fails
    print(('PASS ' if ok else 'FAIL ') + msg)
    if not ok:
        fails += 1


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def launcher_vars(path, names):
    script = ('LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done; '
              'for a in $ARMS; do printf "ARM_SPEC_%s=%s\\n" "$a" "$(arm_spec $a)"; printf "ARM_ENV_%s=%s\\n" "$a" "$(arm_env $a)"; done')
    out = subprocess.run(['bash', '-c', script, 'x', path], capture_output=True, text=True, check=True, cwd=HERE).stdout
    return dict(line.split('=', 1) for line in out.strip().splitlines())


FINAL = os.path.join(HERE, 'claude_s68dev_perf.final.sh')
DRAFT = os.path.join(HERE, 'claude_s68dev_perf.sh')
L = FINAL if os.path.exists(FINAL) else DRAFT
print(f'launcher under test: {os.path.basename(L)} sha256 {sha(L)}')
v = launcher_vars(L, ['LANE', 'OUT', 'S', 'RELEASE', 'HOLD', 'DEALS', 'ARMS', 'TREE_HEAD_FULL', 'R', 'COMBO_NAME', 'FLY_SHA', 'DUEL_SHA', 'HYP_SHA', 'ADAPTER_SHA', 'CAND_SHA', 'CAND_REL',
                     'DUEL', 'HYP', 'ADAPTER', 'EXT_ENGINE_SHA', 'EXT_CWV_SHA', 'EXT_ENDGAME_SHA', 'KILL_AFTER', 'BACKSTOP', 'WORKERS', 'PLAN'])
arms = v['ARMS'].split()
spec = {a: dict(zip(('seed0', 'cand'), v[f'ARM_SPEC_{a}'].split()), env=v[f'ARM_ENV_{a}']) for a in arms}
res = json.load(open(os.path.join(HERE, 'reservation_s68dev.json')))
lt = open(L).read()

# 1. the reservation
check(res['launcher_sha256'] == sha(L) and res['launcher'] == os.path.basename(L), f"reservation launcher_sha256 == sha256({os.path.basename(L)}) = {sha(L)}")
check(res['reader'] == 'Claude' and res['host'] == 'shengji-perf' and res['reservation_path'] == '/root/claude_reservations/s68dev.json', "reservation reader Claude, host perf, path")
check(res['lane'] == v['LANE'] == 's68dev' and res['output_root'] == v['OUT'] == '/root/vol-dev-claude-s68dev-r48-20261026' and res['status'] == v['S'] and res['release'] == v['RELEASE'] and res['hold'] == v['HOLD'],
      f"reservation lane / output_root / status / release / hold equal the launcher's ({v['LANE']}, {v['OUT']})")
check(res['tree'] == v['R'] and res['tree_head'] == v['TREE_HEAD_FULL'], f"reservation tree / head equal the launcher's ({v['R']} @ {v['TREE_HEAD_FULL'][:8]})")
check(arms == ['b', 'a'] and res['arms'] == v['ARMS'] and res['seeds'] == [int(spec[a]['seed0']) for a in arms] and res['count'] == int(v['DEALS']) == 3920
      and all(res['arm_spec'][a] == dict(seed0=int(spec[a]['seed0']), exploiter=spec[a]['cand'], exploiter_env=spec[a]['env']) for a in arms),
      f"reservation arms (b, a), seeds, count and per-arm spec equal arm_spec / arm_env / DEALS")
check(res['launcher_state'].startswith('final') == (L == FINAL), f"reservation launcher_state matches the file under test: {res['launcher_state']}")
check(all((int(spec[a]['seed0']), spec[a]['cand'], spec[a]['env']) == SPEC_ARMS[a] for a in arms), "the launcher's arms equal s68dev_spec.ARMS (the one source)")

# 2. the launcher's pins
check(v['DUEL_SHA'] == sha(os.path.join(HERE, 'exploit_duel_s61.py')) == 'b15d292f564f2643e35d50e07584cecab839b1e61f9890bc31dc8363f495ceec', "DUEL_SHA is the packet's exploit_duel_s61.py (b15d292f)")
check(v['HYP_SHA'] == sha(os.path.join(HERE, 'hypotheses.py')) == '4365a15d6c868263eaa64fca0038168342f2ebd96689da36f46be4e2082e49ce', "HYP_SHA is the packet's hypotheses.py (4365a15d)")
s67c = open(os.path.join(HERE, 'src_claude_s67c_perf.final.sh')).read()
check(sha(os.path.join(HERE, 'src_claude_s67c_perf.final.sh')) == '2bc24cee41dd186e169e71cfe8463f2340280f0f8b6946d81833a51e924c5461' and f"DUEL_SHA={v['DUEL_SHA']}" in s67c and f"HYP_SHA={v['HYP_SHA']}" in s67c,
      "the harness and hypotheses shas are s67c's final launcher's (2bc24cee), unchanged")
check(v['ADAPTER_SHA'] == sha(os.path.join(HERE, 's66_sc8_adapter.py')) == '80e0e7f8b8e59612251858b7af22a61907141f5992cef0b6cdf0732024082477', "ADAPTER_SHA is s66b's s66_sc8_adapter.py (80e0e7f8), the packet's copy")
blob = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:{v['CAND_REL']}"], capture_output=True, check=True).stdout
check(v['CAND_REL'] == 'server/shengji/eval/singleton_challenger.py' and v['CAND_SHA'] == hashlib.sha256(blob).hexdigest(), f"CAND_SHA is sha256(git show {v['TREE_HEAD_FULL'][:8]}:{v['CAND_REL']})")
check(sha(os.path.join(WT, v['CAND_REL'])) == v['CAND_SHA'], "the local candidate worktree's singleton_challenger.py has CAND_SHA")
wt_head = subprocess.run(['git', '-C', WT, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
anc = lambda c: subprocess.run(['git', '-C', REPO, 'merge-base', '--is-ancestor', c, v['TREE_HEAD_FULL']]).returncode == 0
check(wt_head == v['TREE_HEAD_FULL'] and anc('39d514cc260d34b68c6ffb6949ed3d4d769e6d54') and anc('origin/claude/s68-bwc') and anc('d33bfd70bb2f434368b7e83cdb5732cc791bd0ab'),
      f"the candidate worktree is at the tree head {wt_head[:8]}, which contains #1156's 39d514cc, claude/s68-bwc and main d33bfd70")
check(v['DUEL'] == '/root/claude-s68dev/exploit_duel_s61.py' and v['HYP'] == '/root/claude-s68dev/hypotheses.py' and v['ADAPTER'] == '/root/claude-s68dev/s66_sc8_adapter.py'
      and '[ "$(dirname "$DUEL")" = "$(dirname "$ADAPTER")" ] && [ "$(dirname "$HYP")" = "$(dirname "$ADAPTER")" ] || die' in lt,
      "the harness, hypotheses and adapter are pinned in /root/claude-s68dev/ and check_toml guards the shared directory")
asrc = open(os.path.join(HERE, 's66_sc8_adapter.py')).read()
check('SENTINEL = ("S66_EXPLOITER", "sc8")' in asrc and all(spec[a]['env'].split()[0] == 'S66_EXPLOITER=sc8' and 'SHENGJI_PV_BELIEF_CAPACITY=1' in spec[a]['env'].split() for a in arms)
      and lt.count('"${eargs[@]}"') == 1 and '--exploiter-env "S66' not in lt,
      "each arm's env starts with the adapter's SENTINEL (S66_EXPLOITER=sc8) and carries bwc; run_dev passes the arm's words (one eargs expansion)")
check(v['WORKERS'] == '14' and v['PLAN'] == 'r2' and int(v['DEALS']) == 14 * 280 and int(v['BACKSTOP']) == int(v['KILL_AFTER']) + 10, f"14 workers, plan r2, DEALS 3920 = 14 x 280, stop / backstop {v['KILL_AFTER']} / {v['BACKSTOP']}")

# 3. the seed blocks
blocks = {'s68dev b': (int(spec['b']['seed0']), 3920), 's68dev a': (int(spec['a']['seed0']), 3920), 's68dev rehearsal': (243570000, 56),
          's67c sc8p': (243260910, 3920), 's67c smoke': (243160000, 2), 's67c rehearsal': (243170000, 56), 's66b sc8': (242860910, 3920),
          's66dev sc8': (242560910, 600)}
names = list(blocks)
over = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if blocks[a][0] < blocks[b][0] + blocks[b][1] and blocks[b][0] < blocks[a][0] + blocks[a][1]]
check(not over, f"the s68dev blocks are disjoint from each other and from s67c / s66b / s66dev ({over or 'no overlap'})")
reh = open(os.path.join(HERE, 'rehearsal', 'rehearse_s68dev.sh')).read()
check('SEED0=243570000; NDEALS=56;' in reh, "the rehearsal script plays the declared throwaway block 243570000 +56")

# 4. the reader
rd_spec = importlib.util.spec_from_file_location('s68dev_read_packet', os.path.join(HERE, 's68dev_read.py'))
rd = importlib.util.module_from_spec(rd_spec); rd_spec.loader.exec_module(rd)
fly = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:fly.toml"], capture_output=True, check=True).stdout
bot = re.search(r"^\s*SHENGJI_BOT\s*=\s*'([^']+)'", fly.decode(), re.M).group(1)
check(hashlib.sha256(fly).hexdigest() == v['FLY_SHA'], f"FLY_SHA is sha256(fly.toml at {v['TREE_HEAD_FULL'][:8]})")
check(rd.DEF_NAME == v['COMBO_NAME'] == bot, "reader DEF_NAME == launcher COMBO_NAME == fly.toml SHENGJI_BOT at the tree head")
check(list(rd.ARM_ORDER) == arms and all(rd.ARM_SPEC[a] == dict(seed0=int(spec[a]['seed0']), cand=spec[a]['cand'], env=spec[a]['env']) for a in arms) and rd.DEALS == int(v['DEALS']),
      "reader ARM_ORDER / ARM_SPEC (seed0, exploiter, env) == the launcher's ARMS / arm_spec / arm_env; DEALS")
check(rd.TERMINAL == f"{v['LANE']} DEV output sealed (arms {v['ARMS']}); rc/status only (strength qualification is reader-owned); LANE DONE" and 'say "$LANE DEV output sealed (arms $ARMS); rc/status only (strength qualification is reader-owned); LANE DONE"' in lt,
      "reader TERMINAL is the launcher's final say")
rsrc = open(os.path.join(HERE, 's68dev_read.py')).read()
fx = open(os.path.join(HERE, 'test_s68dev_read.py')).read()
check('vs exploiter $nm (exploiter env: $ew; defender at served budgets and widths); deals ' in lt and "(exploiter env: {a['env']}; defender at served budgets and widths); deals " in rsrc
      and "(exploiter env: {rd.ARM_SPEC[arm]['env']}; defender at served budgets and widths)" in fx, "the DEV start text is shared by the launcher's say, the reader's bind regex and the fixture")
envd = {a: dict(w.split('=', 1) for w in spec[a]['env'].split()) for a in arms}
check(rd.PLAY_WORLDS == {a: {'ex': int(envd[a].get('SHENGJI_PV_WORLDS', 64)), 'r45': 64} for a in arms} and rd.EXPLOITER_BUDGET_S == {a: float(envd[a].get('SHENGJI_PV_SERVING_BUDGET_SECONDS', 3)) for a in arms},
      f"reader per-arm play worlds {rd.PLAY_WORLDS} and exploiter budgets {rd.EXPLOITER_BUDGET_S} follow the arms' env")
check(rd.BUDGET_S == 3.0 and rd.BAR['pass_min_mean'] == 0.030 and rd.BAR['pass_ci_lower_above'] == 0.0 and rd.BAR['ceilings']['play_fallback'] == 0 and rd.BAR['ceilings']['belief_fallback'] == 0
      and rd.HALF_BIN == 0.00005 and 'x + HALF_BIN > budget' in rsrc, "reader: the +0.030 bar with CI lower > 0, zero play / belief ceilings, every exploiter decision <= 3 s on the 0.1 ms bin's upper bound")
check(all(sha(os.path.join(LIB, f'{k}.py')) == sha(os.path.join(FL_LIB, f'{k}.py')) == rd.PINNED[k] for k in ('row_schema', 'validity', 'reader_lib', 'compare_runs')),
      "reader PINNED == the packet's reader_lib copies == fl-pilot/reader_lib's row_schema / validity / reader_lib / compare_runs")
check(rd.TRUSTED['lane'] == v['LANE'] and rd.TRUSTED['root'] == v['OUT'] and rd.TRUSTED['status'] == v['S'] and rd.TRUSTED['reservation'] == res['reservation_path'] and rd.TRUSTED['host'] == 'shengji-perf'
      and rd.TREE == v['R'] and rd.TREE_HEAD == v['TREE_HEAD_FULL'], "reader TRUSTED / TREE == the launcher's paths and tree")
check(rd.S66B['levels'] == [0.0165, 0.0042, 0.0287] and rd.S66B['read'] == '1075/6395802322', "reader's s66b reference is the s66b readout (descriptive)")
pn = rd.power_note()
check(abs(pn['se'] - 0.00625) < 0.00001 and abs(pn['p_pass'][0.030] - 0.5) < 0.001 and abs(pn['p_pass'][0.024] - 0.168) < 0.01, f"power note: SE {pn['se']:.5f}; P(PASS) {pn['p_pass']}")
lines = rd.comparisons({'a': dict(levels=[0.031, 0.019, 0.043]), 'b': dict(levels=[0.022, 0.010, 0.034])})
check(len(lines) == 2 and all('independent runs, not a paired test' in x for x in lines), "the comparison lines go through compare_runs (a vs b, b vs s66b) and carry its caveat")
RF = os.path.join(HERE, 's68dev_read.final.py')
if L == FINAL:
    rf = open(RF).read(); rdr = rsrc.split('\n'); rfl = rf.split('\n')
    rdiff = [i for i in range(max(len(rdr), len(rfl))) if rdr[i:i + 1] != rfl[i:i + 1]]
    check(len(rdiff) == 1 and rfl[rdiff[0]].startswith(f'TRUSTED_LAUNCHER_SHA256 = "{sha(L)}"') and rd.TRUSTED_LAUNCHER_SHA256 == 'TO_BE_PINNED',
          f"the final reader differs from the draft in the TRUSTED_LAUNCHER_SHA256 line only and names the final launcher's sha256")
else:
    check(rd.TRUSTED_LAUNCHER_SHA256 == 'TO_BE_PINNED' and not os.path.exists(RF), "draft: the reader's TRUSTED launcher sha256 is TO_BE_PINNED and no final reader exists yet")

# 5. the pins
d = open(DRAFT).read()
if L == FINAL:
    f = open(FINAL).read()
    dl, fl = d.split('\n'), f.split('\n')
    diff = [i for i in range(max(len(dl), len(fl))) if (dl[i:i + 1] != fl[i:i + 1])]
    check(len(diff) == 1 and dl[diff[0]].startswith('EXT_ENGINE_SHA=TO_BE_PINNED;') and all(re.fullmatch(r'[0-9a-f]{64}', v[k]) for k in ('EXT_ENGINE_SHA', 'EXT_CWV_SHA', 'EXT_ENDGAME_SHA')) and len({v[k] for k in ('EXT_ENGINE_SHA', 'EXT_CWV_SHA', 'EXT_ENDGAME_SHA')}) == 3,
          f"the final launcher differs from the draft in the pin line only (line {diff[0] + 1 if diff else '?'}), three distinct 64-hex pins")
else:
    check(all(v[k] == 'TO_BE_PINNED' for k in ('EXT_ENGINE_SHA', 'EXT_CWV_SHA', 'EXT_ENDGAME_SHA')), "draft: the three pins are TO_BE_PINNED (the perf build has not run)")
with tempfile.TemporaryDirectory() as tmp:
    dest = os.path.join(tmp, 'final.sh')
    p = subprocess.run([sys.executable, os.path.join(HERE, 'make_s68dev_final.py'), '--rehearse', dest], capture_output=True, text=True)
    f = open(dest).read() if p.returncode == 0 else ''
    dl, fl = d.split('\n'), f.split('\n')
    diff = [i for i in range(max(len(dl), len(fl))) if (dl[i:i + 1] != fl[i:i + 1])]
    check(p.returncode == 0 and len(diff) == 1 and dl[diff[0]].startswith('EXT_ENGINE_SHA=TO_BE_PINNED;') and fl[diff[0]].count('TO_BE_PINNED') == 0 and f.count('TO_BE_PINNED') == d.count('TO_BE_PINNED') - 3,
          f"pin rehearsal: make_s68dev_final.py changes the pin line only (line {diff[0] + 1 if diff else '?'})")
    bad = subprocess.run([sys.executable, os.path.join(HERE, 'make_s68dev_final.py'), '-'], input='BUILD_RC=3\n', capture_output=True, text=True)
    check(bad.returncode != 0 and 'REFUSING' in (bad.stderr + bad.stdout), "make_s68dev_final.py refuses a build log without BUILD_RC=0")

# 6. staging
st = open(os.path.join(HERE, 'stage_s68dev.sh')).read()
check('bash -s -- "$@" <<' in st and '[ ! -e "$p" ] && [ ! -L "$p" ] ||' in st and 'no target paths reached the host' in st, "stage_s68dev.sh passes the paths as bash -s positional arguments and refuses an existing or symlinked target and a vacuous check")
check('claude_reservations/s68dev.json' in st and 'sha256sum -c' in st and 'chmod a-w' in st and '$LIB/compare_runs.py' in st and '= 8 ] || { echo "REFUSING: expected 8 files"' in st,
      "stage_s68dev.sh stages 8 tree-phase files (adapter, harness, hypotheses, four reader helpers incl. compare_runs, the build script) and the reservation, sha-verified, read-only")
so = os.path.join(HERE, 'test_s68dev_stage.out')
check(os.path.exists(so) and os.path.getmtime(so) >= os.path.getmtime(os.path.join(HERE, 'test_s68dev_stage.sh')) and 'ALL PASS\nrc=0' in open(so).read()
      and 'STAGED_LAYOUT_NEGATIVE_CONTROL' in open(os.path.join(HERE, 'test_s68dev_stage.sh')).read(), "the EXECUTED staged-layout test is ALL PASS and no older than the test")
print('ALL PASS' if not fails else f'{fails} FAILED')
sys.exit(int(bool(fails)))
