#!/usr/bin/env python3
"""Generate stage_s68dev.sh from s67c's stage_s67c.sh (r2) by asserted replacements: the header, the packet dir, the test hooks, the tree,
the build script, the staged dir, the adapter, the reader helpers (+ compare_runs.py: 8 files in the tree phase) and the lane names.
Usage: python3 make_s68dev_stage.py (refuses to overwrite)"""
import hashlib
import sys
from pathlib import Path
H = Path(__file__).resolve().parent
sys.path.insert(0, str(H))
from s68dev_spec import HEAD, R, OUT  # noqa: E402
s = (H / 'src_stage_s67c.sh').read_text()
assert hashlib.sha256(s.encode()).hexdigest() == hashlib.sha256((Path('/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c/stage_s67c.sh')).read_bytes()).hexdigest()
a = s.index('# s67c staging'); b = s.index('set -u\n')
hdr = f'''# s68dev staging (run on THIS Mac by the operator), in two phases, each refusing if ANY of its targets exists or is a symlink on the host
# (nothing is overwritten or removed); every copied file's sha256 is verified ON perf against this Mac's and the copies are made
# read-only.  It does not arm, DRYRUN or release anything, and it does not run the build.
#
#   bash stage_s68dev.sh tree
#       copies $ROOT/claude_build_s68_perf.sh (the pinned perf build script) and $ROOT/claude-s68dev/ (the adapter s66_sc8_adapter.py,
#       the harness exploit_duel_s61.py and hypotheses.py BESIDE it -- the adapter imports both from its own directory -- and the four
#       pinned reader helpers incl. compare_runs.py), then prints the EXACT build command the operator runs ON perf, detached:
#         HEAD={HEAD} ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_s68_perf.sh        (preflight)
#         HEAD={HEAD} ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_s68_perf.sh > {R}-build.nohup 2>&1 &
#       Witness: {R}-build.log ends with BUILD_RC=0 after three 'ext <module> <sha256>' lines; then on the Mac
#       `ssh shengji-perf cat {R}-build.log > build.log && python3 make_s68dev_final.py build.log &&
#        python3 make_s68dev_reservation.py --force && python3 test_s68dev_packet.py` (ALL PASS).
#   bash stage_s68dev.sh lane <expected sha256 of claude_s68dev_perf.final.sh>
#       copies the FINAL launcher to $ROOT/claude_s68dev_perf.sh, the FINAL reader (its TRUSTED launcher sha = that sha) to
#       $ROOT/claude-s68dev/s68dev_read.py and the reservation to $ROOT/claude_reservations/s68dev.json.
#
# The fresh-only check runs the remote loop with `bash -s -- <paths>` and the script on stdin, so the paths are the remote shell's
# positional arguments (ssh joins its command words into ONE remote command line).
# = s67c's stage_s67c.sh (r2) with the lane, the tree, the adapter, the staged directory and the reader helper list changed
# (make_s68dev_stage.py).  Test hooks: S68_SSH / S68_SCP (default ssh / scp) and S68_ROOT (default /root) -- never set in production use.
'''
s = s[:a] + hdr + s[b:]
for o, n in [('H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c;', 'H=/Users/jerryyu/Projects/shengji-wt/claude-s68-combo/tools/s68dev;'),
             ('SSH=${S67_SSH:-ssh}; SCP=${S67_SCP:-scp}; ROOT=${S67_ROOT:-/root}', 'SSH=${S68_SSH:-ssh}; SCP=${S68_SCP:-scp}; ROOT=${S68_ROOT:-/root}'),
             ('claude-sc8p-src-8a50fe8a', R.split('/')[-1]),
             ('claude_build_sc8p_perf.sh', 'claude_build_s68_perf.sh'),
             ('claude-s67c', 'claude-s68dev'),
             ('s67_sc8p_adapter.py', 's66_sc8_adapter.py'),
             ('$LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py', '$LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py $LIB/compare_runs.py'),
             ('= 7 ] || { echo "REFUSING: expected 7 files"', '= 8 ] || { echo "REFUSING: expected 8 files"'),
             ('8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f', HEAD),
             ('at 8a50fe8a into', f'at {HEAD[:8]} into'),
             ('claude_s67c_perf', 'claude_s68dev_perf'), ('s67c_read', 's68dev_read'), ('reservation_s67c', 'reservation_s68dev'),
             ('make_s67c_', 'make_s68dev_'), ('test_s67c_packet', 'test_s68dev_packet'),
             ('claude_s67c_screen.status', 'claude_s68dev_screen.status'), ('claude_s67c.RELEASE', 'claude_s68dev.RELEASE'), ('claude_s67c.HOLD', 'claude_s68dev.HOLD'),
             ('claude_reservations/s67c.json', 'claude_reservations/s68dev.json'),
             ('stage_s67c.sh', 'stage_s68dev.sh')]:
    assert o in s, o
    s = s.replace(o, n)
body = s.split('set -u', 1)[1]
assert 's67c' not in body and '8a50fe8a' not in body and OUT.split('/')[-1] in body, [l for l in body.splitlines() if 's67c' in l or '8a50fe8a' in l]
(H / 'stage_s68dev.sh').open('x').write(s)
print('stage_s68dev.sh', hashlib.sha256(s.encode()).hexdigest())
