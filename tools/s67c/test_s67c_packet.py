#!/usr/bin/env python3
"""test_s67c_packet.py -- the packet's cross-file pins hold: the reservation is generated FROM the launcher and this test refuses the packet
when any pin is off.

  1. sha256(the launcher the reservation names: claude_s67c_perf.final.sh when present, else the draft) == reservation_s67c.json.launcher_sha256;
     the reservation's reader is Claude; its lane / output_root / status / release / hold / tree / tree_head / seed0 / count / exploiter equal
     the launcher's LANE / OUT / S / RELEASE / HOLD / R / TREE_HEAD_FULL / arm_spec / DEALS (sourced, never typed); its reservation_path
     is /root/claude_reservations/s67c.json;
  2. the launcher's DUEL_SHA / HYP_SHA / ADAPTER_SHA are the sha256 of the packet's files (DUEL / HYP shas = s66b's final launcher's pins);
     DUEL / HYP / ADAPTER all sit in /root/claude-s67c/ (the adapter imports the harness and hypotheses from its own directory: r2, Codex
     1075/6405786268) and the launcher's check_toml guards that; CAND_SHA / BASE_SHA are the sha256 of server/shengji/eval/pair_challenger.py / singleton_challenger.py at
     TREE_HEAD_FULL (git show from the shared repo) and of the local 8a50fe8a worktree's copies; TREE_HEAD_FULL is 8a50fe8a...; the
     adapter's SENTINEL is the launcher's one --exploiter-env argument; 14 workers, r2, DEALS 3920 = 14 x 280, KILL 18000 / BACKSTOP 18010;
  3. the seed block [243260910, +3920) and the smoke [243160000, +2) are disjoint from s66dev's, s66b's, s66dev's smoke / bench and from
     each other;
  4. the reader's DEF_NAME == the launcher's COMBO_NAME == fly.toml's SHENGJI_BOT at TREE_HEAD_FULL; the reader's ARM_SPEC seed0 / cand ==
     arm_spec's; the reader's TERMINAL is the launcher's final say; the DEV start text the reader matches is the launcher's say text and
     the fixture's START; the reader's PINNED helper shas are the packet's reader_lib copies and fl-pilot/reader_lib's; the reader's
     TRUSTED identities equal the launcher's; its latency rule; its KINDS; its s66b reference equals the s66b readout and the power note;
  5. when the final launcher exists: it differs from the draft in the pin line only, and holds no TO_BE_PINNED pin, and the final reader
     differs from the draft in its TRUSTED_LAUNCHER_SHA256 line only; otherwise the pin rehearsal (make_s67c_final.py --rehearse) proves
     both transformations change that one line only, and a build log without BUILD_RC=0 is refused;
  6. the staging script's remote form (bash -s -- with the paths as positional arguments), its guards and its harness-pin check; the
     EXECUTED staging test's ALL PASS.
= s66dev's test_s66dev_packet.py (r2) with the lane names changed and the base-module, seed-disjointness, KINDS and s66b-reference checks
added.

Usage: python3 test_s67c_packet.py"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.join(HERE, 'reader_lib')
FL_LIB = '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/reader_lib'
REPO = '/Users/jerryyu/Projects/shengji'
WT = '/Users/jerryyu/Projects/shengji-wt/claude-s67'
fails = 0


def check(ok, msg):
    global fails
    print(('PASS ' if ok else 'FAIL ') + msg)
    if not ok:
        fails += 1


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def launcher_vars(path, names):
    script = 'LANE_FUNCTIONS_ONLY=1; source "$1"; for n in ' + ' '.join(names) + '; do printf "%s=%s\\n" "$n" "${!n}"; done; printf "ARM_SPEC=%s\\n" "$(arm_spec sc8p)"'
    out = subprocess.run(['bash', '-c', script, 'x', path], capture_output=True, text=True, check=True, cwd=HERE).stdout
    return dict(line.split('=', 1) for line in out.strip().splitlines())


FINAL = os.path.join(HERE, 'claude_s67c_perf.final.sh')
DRAFT = os.path.join(HERE, 'claude_s67c_perf.sh')
L = FINAL if os.path.exists(FINAL) else DRAFT
print(f'launcher under test: {os.path.basename(L)} sha256 {sha(L)}')
v = launcher_vars(L, ['LANE', 'OUT', 'S', 'RELEASE', 'HOLD', 'DEALS', 'ARMS', 'TREE_HEAD_FULL', 'R', 'COMBO_NAME', 'FLY_SHA', 'DUEL_SHA', 'HYP_SHA', 'ADAPTER_SHA', 'CAND_SHA', 'CAND_REL',
                     'BASE_SHA', 'BASE_REL', 'DUEL', 'HYP', 'ADAPTER', 'EXT_ENGINE_SHA', 'EXT_CWV_SHA', 'EXT_ENDGAME_SHA', 'KILL_AFTER', 'BACKSTOP', 'WORKERS', 'PLAN'])
seed0, cand = v['ARM_SPEC'].split()
res = json.load(open(os.path.join(HERE, 'reservation_s67c.json')))
lt = open(L).read()

# 1. the reservation
check(res['launcher_sha256'] == sha(L) and res['launcher'] == os.path.basename(L), f"reservation launcher_sha256 == sha256({os.path.basename(L)}) = {sha(L)}")
check(res['reader'] == 'Claude', "reservation reader is Claude")
check(res['lane'] == v['LANE'] == 's67c' and res['output_root'] == v['OUT'] == '/root/vol-dev-claude-s67c-r48-20261026' and res['status'] == v['S'] and res['release'] == v['RELEASE'] and res['hold'] == v['HOLD'],
      f"reservation lane / output_root / status / release / hold equal the launcher's ({v['LANE']}, {v['OUT']}, {v['S']})")
check(res['tree'] == v['R'] == '/root/claude-sc8p-src-8a50fe8a' and res['tree_head'] == v['TREE_HEAD_FULL'], f"reservation tree / head equal the launcher's ({v['R']} @ {v['TREE_HEAD_FULL'][:8]})")
check(res['seed0'] == int(seed0) == 243260910 and res['count'] == int(v['DEALS']) == 3920 and res['arms'] == v['ARMS'] == 'sc8p' and res['exploiter'] == cand,
      f"reservation seed0 / count / arms / exploiter equal arm_spec and DEALS ({seed0}, {v['DEALS']}, {v['ARMS']})")
check(res['reservation_path'] == '/root/claude_reservations/s67c.json' and res['host'] == 'shengji-perf', "reservation path and host")
check(res['launcher_state'].startswith('final') == (L == FINAL), f"reservation launcher_state matches the file under test: {res['launcher_state']}")

# 2. the launcher's pins
check(v['TREE_HEAD_FULL'] == '8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f', "TREE_HEAD_FULL is 8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f")
check(v['DUEL_SHA'] == sha(os.path.join(HERE, 'exploit_duel_s61.py')) == 'b15d292f564f2643e35d50e07584cecab839b1e61f9890bc31dc8363f495ceec', "DUEL_SHA is the packet's exploit_duel_s61.py (b15d292f, the reviewed producer)")
check(v['HYP_SHA'] == sha(os.path.join(HERE, 'hypotheses.py')) == '4365a15d6c868263eaa64fca0038168342f2ebd96689da36f46be4e2082e49ce', "HYP_SHA is the packet's hypotheses.py (4365a15d)")
s66b = open(os.path.join(HERE, 'src_claude_s66b_perf.final.sh')).read()
check(sha(os.path.join(HERE, 'src_claude_s66b_perf.final.sh')) == 'aa078dde97b88f5c490d8cae4beb9b32cd2be02837fa19fb1d5f0ef6264f4eb2'
      and f"DUEL_SHA={v['DUEL_SHA']}" in s66b and f"HYP_SHA={v['HYP_SHA']}" in s66b,
      "the harness and hypotheses shas are s66b's final launcher's (aa078dde), unchanged")
check(v['ADAPTER_SHA'] == sha(os.path.join(HERE, 's67_sc8p_adapter.py')), f"ADAPTER_SHA is the packet's s67_sc8p_adapter.py ({v['ADAPTER_SHA'][:8]})")
for key, rel, name in (('CAND_SHA', 'CAND_REL', 'pair_challenger.py'), ('BASE_SHA', 'BASE_REL', 'singleton_challenger.py')):
    blob = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:{v[rel]}"], capture_output=True, check=True).stdout
    check(v[rel] == f'server/shengji/eval/{name}' and v[key] == hashlib.sha256(blob).hexdigest(), f"{key} is sha256(git show {v['TREE_HEAD_FULL'][:8]}:{v[rel]}) = {v[key][:8]}")
    check(os.path.isfile(os.path.join(WT, v[rel])) and sha(os.path.join(WT, v[rel])) == v[key], f"the local 8a50fe8a worktree's {name} has {key}")
wt_head = subprocess.run(['git', '-C', WT, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
check(wt_head == v['TREE_HEAD_FULL'], f"the local worktree {WT} is at the tree head ({wt_head[:8]})")
check(v['DUEL'] == '/root/claude-s67c/exploit_duel_s61.py' and v['HYP'] == '/root/claude-s67c/hypotheses.py' and v['ADAPTER'] == '/root/claude-s67c/s67_sc8p_adapter.py'
      and 'HERE.with_name("exploit_duel_s61.py")' in open(os.path.join(HERE, 's67_sc8p_adapter.py')).read()
      and '[ "$(dirname "$DUEL")" = "$(dirname "$ADAPTER")" ] && [ "$(dirname "$HYP")" = "$(dirname "$ADAPTER")" ] || die' in lt,
      "the harness, hypotheses and adapter are all pinned in /root/claude-s67c/, where the adapter imports them (HERE.with_name), and check_toml guards the shared directory")
src = open(os.path.join(HERE, 's67_sc8p_adapter.py')).read()
check('SENTINEL = ("S66_EXPLOITER", "sc8p")' in src and 'SUFFIX = "-sc8p"' in src and lt.count('--exploiter-env "S66_EXPLOITER=sc8p"') == 1 and lt.count('--exploiter-env "') == 1,
      "the adapter's SENTINEL is the launcher's one --exploiter-env argument (S66_EXPLOITER=sc8p)")
check(v['WORKERS'] == '14' and v['PLAN'] == 'r2' and int(v['DEALS']) == 14 * 280 and v['KILL_AFTER'] == '18000' and v['BACKSTOP'] == '18010',
      f"14 workers, plan r2, DEALS 3920 = 14 x 280, stop / backstop {v['KILL_AFTER']} / {v['BACKSTOP']} (s66b's)")

# 3. the seed blocks
blocks = {'s67c sc8p': (243260910, 3920), 's67c smoke': (243160000, 2), 's66b sc8': (242860910, 3920), 's66dev sc8': (242560910, 600),
          's66dev smoke': (242760000, 2), 's66dev bench': (242770000, 40)}
names = list(blocks)
over = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if blocks[a][0] < blocks[b][0] + blocks[b][1] and blocks[b][0] < blocks[a][0] + blocks[a][1]]
check(not over and blocks['s67c sc8p'][0] == int(seed0), f"the s67c block and smoke are disjoint from s66dev / s66b blocks, smoke and bench ({over or 'no overlap'})")

# 4. the reader
rd_spec = importlib.util.spec_from_file_location('s67c_read_packet', os.path.join(HERE, 's67c_read.py'))
rd = importlib.util.module_from_spec(rd_spec); rd_spec.loader.exec_module(rd)
fly = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:fly.toml"], capture_output=True, check=True).stdout
bot = re.search(r"^\s*SHENGJI_BOT\s*=\s*'([^']+)'", fly.decode(), re.M).group(1)
check(hashlib.sha256(fly).hexdigest() == v['FLY_SHA'], f"FLY_SHA is sha256(fly.toml at {v['TREE_HEAD_FULL'][:8]})")
check(rd.DEF_NAME == v['COMBO_NAME'] == bot, "reader DEF_NAME == launcher COMBO_NAME == fly.toml SHENGJI_BOT at the tree head")
check(rd.ARM_ORDER == ('sc8p',) and rd.ARM_SPEC['sc8p']['seed0'] == int(seed0) and rd.ARM_SPEC['sc8p']['cand'] == cand == bot + '-sc8p' and rd.DEALS == int(v['DEALS']),
      "reader ARM_SPEC (seed0, exploiter = SHENGJI_BOT + '-sc8p') == arm_spec; reader DEALS == DEALS")
check(rd.TERMINAL == f"{v['LANE']} DEV output sealed (arms {v['ARMS']}); rc/status only (strength qualification is reader-owned); LANE DONE" and 'say "$LANE DEV output sealed (arms $ARMS); rc/status only (strength qualification is reader-owned); LANE DONE"' in lt,
      "reader TERMINAL is the launcher's final say")
START = '(S66_EXPLOITER=sc8p: the pair/tractor challenger, claude/s67-pair-challenger at 8a50fe8a; served budgets and widths on both sides); deals '
fx = open(os.path.join(HERE, 'test_s67c_read.py')).read()
rsrc = open(os.path.join(HERE, 's67c_read.py')).read()
check(f'vs exploiter $nm {START}' in lt and START in rsrc and START.rstrip('; deals ').rstrip(';') in fx, "the DEV start text is shared by the launcher's say, the reader's bind regex and the fixture")
check(rd.PLAY_WORLDS == {'ex': 64, 'r45': 64} and rd.BUDGET_S == 3.0 and rd.BAR['pass_min_mean'] == 0.015 and rd.BAR['pass_ci_lower_above'] == 0.0 and rd.BAR['ceilings']['play_fallback'] == 0 and rd.BAR['ceilings']['belief_fallback'] == 0,
      "reader: 64 / 64 worlds, 3 s latency ceiling, the +0.015 bar with CI lower > 0, zero play / belief ceilings")
check(all(sha(os.path.join(LIB, f'{k}.py')) == sha(os.path.join(FL_LIB, f'{k}.py')) == rd.PINNED[k] for k in ('row_schema', 'validity', 'reader_lib')),
      "reader PINNED == the packet's reader_lib copies == fl-pilot/reader_lib's row_schema / validity / reader_lib")
check(rd.TRUSTED['lane'] == v['LANE'] and rd.TRUSTED['root'] == v['OUT'] and rd.TRUSTED['status'] == v['S'] and rd.TRUSTED['reservation'] == res['reservation_path'] == '/root/claude_reservations/s67c.json' and rd.TRUSTED['host'] == 'shengji-perf',
      "reader TRUSTED lane / root / status / reservation / host == the launcher's LANE / OUT / S and the reservation path")
check(rd.TREE == v['R'] and rd.TREE_HEAD == v['TREE_HEAD_FULL'], "reader TREE / TREE_HEAD == the launcher's R / TREE_HEAD_FULL (the armed line binds them)")
check(rd.HALF_BIN == 0.00005 and 'x + HALF_BIN > budget' in rsrc, "reader latency ceiling on the 0.1 ms bin's upper bound (HALF_BIN 0.00005)")
pc = subprocess.run(['git', '-C', REPO, 'show', f"{v['TREE_HEAD_FULL']}:server/shengji/eval/pair_challenger.py"], capture_output=True, text=True, check=True).stdout
check(rd.KINDS == ('single', 'pair', 'tractor') and rd.KINDS_PLAYED == rd.KINDS + ('throw',) and f"POOL_KINDS = {rd.KINDS!r}" in pc and "return 'throw'" in pc,
      "reader KINDS (single / pair / tractor, + throw on a played lead) are pair_challenger.py's POOL_KINDS and lead_kind names at the tree head")
check(rd.S66B['levels'] == [0.0165, 0.0042, 0.0287] and rd.S66B['deals'] == 3920 and rd.S66B['read'] == '1075/6395802322',
      "reader's s66b reference is the s66b readout (+0.0165 [+0.0042, +0.0287], 3,920 deals, 1075/6395802322): descriptive only")
pn = rd.power_note()
check(abs(pn['se_reference'] - 0.00625) < 0.00001 and abs(pn['at']['+0.017']['p_pass'] - 0.626) < 0.002, f"power note: SE {pn['se_reference']:.5f} from s66b's half-width; PASS at a true +0.017 = {pn['at']['+0.017']['p_pass']}")
RF = os.path.join(HERE, 's67c_read.final.py')
if L == FINAL:
    rf = open(RF).read(); rdr = rsrc.split('\n'); rfl = rf.split('\n')
    rdiff = [i for i in range(max(len(rdr), len(rfl))) if rdr[i:i + 1] != rfl[i:i + 1]]
    check(os.path.exists(RF) and len(rdiff) == 1 and rfl[rdiff[0]].startswith(f'TRUSTED_LAUNCHER_SHA256 = "{sha(L)}"') and rd.TRUSTED_LAUNCHER_SHA256 == 'TO_BE_PINNED',
          f"the final reader differs from the draft in the TRUSTED_LAUNCHER_SHA256 line only and names the final launcher's sha256 (line {rdiff[0] + 1 if rdiff else '?'})")
    rs_spec = importlib.util.spec_from_file_location('s67c_read_final_packet', RF); rdf = importlib.util.module_from_spec(rs_spec); rs_spec.loader.exec_module(rdf)
    check(rdf.TRUSTED['launcher_sha256'] == sha(L) == res['launcher_sha256'], "the final reader's TRUSTED launcher sha256 == sha256(final launcher) == the reservation's")
else:
    check(rd.TRUSTED_LAUNCHER_SHA256 == 'TO_BE_PINNED' and rd.TRUSTED['launcher_sha256'] == 'TO_BE_PINNED' and not os.path.exists(RF), "draft: the reader's TRUSTED launcher sha256 is TO_BE_PINNED and no final reader exists yet")
    with tempfile.TemporaryDirectory() as tmp2:
        dest = os.path.join(tmp2, 'final.sh')
        p2 = subprocess.run([sys.executable, os.path.join(HERE, 'make_s67c_final.py'), '--rehearse', dest], capture_output=True, text=True)
        rf = open(dest + '.reader.py').read() if p2.returncode == 0 else ''
        rdr = rsrc.split('\n'); rfl = rf.split('\n')
        rdiff = [i for i in range(max(len(rdr), len(rfl))) if rdr[i:i + 1] != rfl[i:i + 1]]
        check(p2.returncode == 0 and len(rdiff) == 1 and rfl[rdiff[0]].startswith(f'TRUSTED_LAUNCHER_SHA256 = "{sha(dest)}"'), f"pin rehearsal: the pinned reader differs from the draft in the TRUSTED_LAUNCHER_SHA256 line only, naming the rehearsal launcher's sha256 (line {rdiff[0] + 1 if rdiff else '?'})")
st_out = os.path.join(HERE, 'test_s67c_stage.out')
check(os.path.exists(st_out) and 'ALL PASS\nrc=0' in open(st_out).read(), "the EXECUTED staging test (test_s67c_stage.sh: ssh-joining shim; absent / existing / symlink; no scp on refusal; both phases; the staged layout from the copied bytes: pins, adapter --help, check_names through the copied adapter; the r1 layout's FileNotFoundError) is ALL PASS")

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
        p = subprocess.run([sys.executable, os.path.join(HERE, 'make_s67c_final.py'), '--rehearse', dest], capture_output=True, text=True)
        f = open(dest).read() if p.returncode == 0 else ''
        dl, fl = d.split('\n'), f.split('\n')
        diff = [i for i in range(max(len(dl), len(fl))) if (dl[i:i + 1] != fl[i:i + 1])]
        check(p.returncode == 0 and len(diff) == 1 and dl[diff[0]].startswith('EXT_ENGINE_SHA=TO_BE_PINNED;') and fl[diff[0]].count('TO_BE_PINNED') == 0 and f.count('TO_BE_PINNED') == d.count('TO_BE_PINNED') - 3,
              f"pin rehearsal: make_s67c_final.py changes the pin line only (line {diff[0] + 1 if diff else '?'}); the guard's and header's mentions remain")
        bad = subprocess.run([sys.executable, os.path.join(HERE, 'make_s67c_final.py'), '-'], input='BUILD_RC=3\n', capture_output=True, text=True)
        check(bad.returncode != 0 and 'REFUSING' in (bad.stderr + bad.stdout), "make_s67c_final.py refuses a build log without BUILD_RC=0")

# 6. staging
st = open(os.path.join(HERE, 'stage_s67c.sh')).read()
check('bash -s -- "$@" <<' in st and '[ ! -e "$p" ] && [ ! -L "$p" ] ||' in st and 'REFUSING: $p exists or is a symlink on the host' in st and 'no target paths reached the host' in st, "stage_s67c.sh passes the paths as bash -s positional arguments with the script on stdin, refuses an existing (-e) or symlinked (-L) target and a vacuous check")
check('claude_reservations/s67c.json' in st and 'sha256sum -c' in st and 'chmod a-w' in st, "stage_s67c.sh copies the reservation, verifies every copy by sha256 on the host and makes it read-only")
check('$H/s67_sc8p_adapter.py $H/exploit_duel_s61.py $H/hypotheses.py $LIB/row_schema.py' in st and '= 7 ] || { echo "REFUSING: expected 7 files"' in st and 'claude-s66dev' not in st.split('set -u', 1)[1],
      "stage_s67c.sh's tree phase stages the adapter WITH the harness and hypotheses into /root/claude-s67c/ (7 files with the build script and helpers) and consumes nothing from claude-s66dev/")
print('ALL PASS' if not fails else f'{fails} FAILED')
sys.exit(int(bool(fails)))
