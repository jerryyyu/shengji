#!/bin/bash
# s67c r2: EXECUTED test of stage_s67c.sh: the fresh-only check, and the STAGED LAYOUT the lane consumes (Codex 1075/6405786268).  An `ssh`
# shim that keeps ssh's joining of the command words (every word after the host is joined with spaces into ONE remote command line, run
# by a local bash with the caller's stdin) and an `scp` shim that logs every call AND performs the copy into the temp host dir are put
# first on PATH; S67_ROOT points the host paths at a temp dir.
#   1. the refuse_targets function refuses an existing regular file (rc 3) and a dangling symlink (rc 3), passes absent paths (rc 0,
#      naming the count); with ZERO paths reaching the host it refuses;
#   2. phase `tree` with one target present: rc 3 before any mkdir / scp (the scp log stays empty, no build script copied);
#   3. phase `lane` with the local prerequisites present (a stand-in final launcher / reader / reservation) and one host target present:
#      rc 3, scp log empty; a wrong expected sha: rc 3 before any host contact;
#   4. phase `tree` on a clean host dir runs to "STAGED ok (tree phase): 7 files" (the copies verified by sha256sum -c and made
#      read-only in the temp host dir; macOS wc pads the count with spaces, hence the ' +' in the match);
#   5. the staged layout, from the bytes actually copied in 4: the launcher's DUEL / HYP / ADAPTER (sourced, /root mapped to the temp host
#      dir) exist there at their pinned shas, all in one directory; the COPIED adapter runs --help (rc 0: it imports the copied harness,
#      which imports the copied hypotheses, on the local 8a50fe8a tree); the launcher's check_names python block (cut byte for byte) runs
#      rc 0 through the COPIED adapter (the launcher preflight import: names, classes, config diff);
#   6. the r1 layout (the adapter and helpers in claude-s67c/, the harness only in the sibling claude-s66dev/) reproduces the finding:
#      the copied adapter's --help exits non-zero with FileNotFoundError for claude-s67c/exploit_duel_s61.py.
# = s66dev's test_s66dev_stage.sh (r2) with the lane names changed, its r1-staging case dropped and the staged-layout cases 4-6 added.
# Writes nothing outside a temp dir (the local tree is only read).  Usage: bash test_s67c_stage.sh
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c
W=/Users/jerryyu/Projects/shengji-wt/claude-s67/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz
S58=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/r47_redteam/pkg/s58-e6-42444515.npz
[ "$(git -C $W rev-parse HEAD)" = "8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f" ] || { echo "FAIL tree $W is not 8a50fe8a"; exit 1; }
T=$(mktemp -d /private/tmp/s67cstage.XXXX); trap 'chmod -R u+w "$T" 2>/dev/null; rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/host/claude_reservations" "$T/pkt"
cat > "$T/bin/ssh" <<'EOF'
#!/bin/bash
# ssh shim: drop the host, join the remaining words with spaces into one command line (ssh's joining), run it with the caller's stdin
shift
exec bash -c "$*"
EOF
cat > "$T/bin/scp" <<EOF
#!/bin/bash
# scp shim: log the call, then copy the sources to the HOST:dest path (the host prefix dropped) as scp would
echo "scp \$*" >> "$T/scp.log"
args=(); for a in "\$@"; do [ "\$a" = -q ] || args+=("\$a"); done
n=\${#args[@]}; dest=\${args[\$((n - 1))]}; dest=\${dest#*:}
cp "\${args[@]:0:\$((n - 1))}" "\$dest"
EOF
chmod +x "$T/bin/ssh" "$T/bin/scp"
export PATH="$T/bin:$PATH" S67_SSH=ssh S67_SCP=scp S67_ROOT="$T/host"
fails=0
pass () { echo "PASS $1"; }
fail () { echo "FAIL $1"; fails=$((fails + 1)); }
fn=$(awk '/^refuse_targets \(\) \{/,/^\}/' "$H/stage_s67c.sh")
[ -n "$fn" ] || { echo "FAIL could not extract refuse_targets"; exit 1; }
touch "$T/host/existing"; ln -s "$T/host/nowhere" "$T/host/dangling"
# 1. the function
run_fn () { ( HOST=h; SSH=ssh; eval "$fn"; refuse_targets "$@" ) 2>&1; }
out=$(run_fn "$T/host/absent1" "$T/host/absent2"); rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "targets clear (2 paths)"; then pass "two absent paths -> rc 0, the host saw 2 paths"; else fail "absent rc=$rc out=$out"; fi
out=$(run_fn "$T/host/absent1" "$T/host/existing"); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: $T/host/existing exists"; then pass "an existing regular file -> rc 3 REFUSING"; else fail "existing rc=$rc out=$out"; fi
out=$(run_fn "$T/host/dangling"); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: $T/host/dangling exists or is a symlink"; then pass "a dangling symlink -> rc 3 REFUSING"; else fail "symlink rc=$rc out=$out"; fi
out=$( ( HOST=h; SSH=ssh; eval "$fn"; refuse_targets ) 2>&1 ); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: no target paths reached the host"; then pass "zero paths -> rc 3 (a vacuous check is refused)"; else fail "zero rc=$rc out=$out"; fi
rm -f "$T/host/existing" "$T/host/dangling"
# 2. phase tree with a target present: no mkdir, no scp
rm -f "$T/scp.log"; mkdir "$T/host/claude-s67c"
out=$(bash "$H/stage_s67c.sh" tree 2>&1); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: $T/host/claude-s67c exists" && [ ! -e "$T/scp.log" ] && [ ! -e "$T/host/claude_build_sc8p_perf.sh" ]; then pass "phase tree with /claude-s67c present -> rc 3, no scp, no build script copied"; else fail "tree refusal rc=$rc scp=$(cat "$T/scp.log" 2>/dev/null) out=$out"; fi
rmdir "$T/host/claude-s67c"
# 3. phase lane: local prerequisites as stand-ins (the real ones exist only after the perf build), one host target present
mkdir -p "$T/pkt/s67c"; cp "$H/stage_s67c.sh" "$T/pkt/s67c/"; sed -i '' "s#^H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c;#H=$T/pkt/s67c;#" "$T/pkt/s67c/stage_s67c.sh"
grep -q "^H=$T/pkt/s67c;" "$T/pkt/s67c/stage_s67c.sh" || { echo "FAIL could not repoint the staging copy"; exit 1; }
printf 'EXT_ENGINE_SHA=a\n' > "$T/pkt/s67c/claude_s67c_perf.final.sh"; WS=$(shasum -a 256 "$T/pkt/s67c/claude_s67c_perf.final.sh" | cut -d' ' -f1)
printf 'TRUSTED_LAUNCHER_SHA256 = "%s"\n' "$WS" > "$T/pkt/s67c/s67c_read.final.py"
printf '{"launcher_sha256": "%s", "launcher": "claude_s67c_perf.final.sh", "reader": "Claude"}\n' "$WS" > "$T/pkt/s67c/reservation_s67c.json"
rm -f "$T/scp.log"; ln -s "$T/host/nowhere" "$T/host/claude_s67c.RELEASE" || { echo "FAIL could not plant the RELEASE symlink"; exit 1; }
out=$(bash "$T/pkt/s67c/stage_s67c.sh" lane "$WS" 2>&1); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: $T/host/claude_s67c.RELEASE exists or is a symlink" && [ ! -e "$T/scp.log" ]; then pass "phase lane with a dangling RELEASE symlink present -> rc 3, no scp"; else fail "lane refusal rc=$rc scp=$(cat "$T/scp.log" 2>/dev/null) out=$out"; fi
rm -f "$T/host/claude_s67c.RELEASE"
out=$(bash "$T/pkt/s67c/stage_s67c.sh" lane "0000000000000000000000000000000000000000000000000000000000000000" 2>&1); rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: claude_s67c_perf.final.sh missing or not" && [ ! -e "$T/scp.log" ]; then pass "phase lane with a wrong expected sha -> rc 3 before any host contact"; else fail "lane wrong-sha rc=$rc out=$out"; fi
# 4. phase tree on a clean host dir: the real copies, verified and made read-only
rm -f "$T/scp.log"
bash "$H/stage_s67c.sh" tree > "$T/tree.out" 2>&1; rc=$?
if [ "$rc" -eq 0 ] && grep -Eq "STAGED ok \(tree phase\): +7 files verified on the host, read-only" "$T/tree.out" && [ "$(grep -c '^scp ' "$T/scp.log")" = 3 ] && [ ! -w "$T/host/claude-s67c/exploit_duel_s61.py" ]; then
  pass "phase tree on a clean host: targets clear, mkdir, 3 scp calls, 'STAGED ok (tree phase): 7 files' (sha256sum -c on the copies), read-only"
else fail "tree staging rc=$rc out=$(cat "$T/tree.out") log=$(cat "$T/scp.log" 2>/dev/null)"; fi
# 5. the staged layout the lane consumes, from the copied bytes
L=$H/claude_s67c_perf.sh
lv=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1"; printf "%s %s %s %s %s %s\n" "$DUEL" "$DUEL_SHA" "$HYP" "$HYP_SHA" "$ADAPTER" "$ADAPTER_SHA"' x "$L")
read -r DUEL DUEL_SHA HYP HYP_SHA ADAPTER ADAPTER_SHA <<< "$lv"
ok=1; for pair in "$DUEL $DUEL_SHA" "$HYP $HYP_SHA" "$ADAPTER $ADAPTER_SHA"; do set -- $pair; f=$T/host${1#/root}; { [ -f "$f" ] && [ ! -L "$f" ] && [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$2" ]; } || { ok=0; echo "  missing or wrong sha: $f"; }; done
if [ "$ok" = 1 ] && [ "$(dirname "$DUEL")" = "$(dirname "$ADAPTER")" ] && [ "$(dirname "$HYP")" = "$(dirname "$ADAPTER")" ] && [ "$(dirname "$ADAPTER")" = /root/claude-s67c ]; then
  pass "the launcher's DUEL / HYP / ADAPTER ($DUEL, $HYP, $ADAPTER) are the staged copies at their pinned shas, all in /root/claude-s67c"
else fail "launcher pins vs the staged layout: $lv"; fi
SA=$T/host/claude-s67c/s67_sc8p_adapter.py
envrun () { env -i HOME="$HOME" PATH=/usr/bin:/bin FIND_GAPS_SERVER=$W FIND_GAPS_PKG=$PKG FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=$W "$@"; }
out=$(cd /private/tmp && envrun $PY -B "$SA" --help 2>&1); rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q -- "--exploiter-env"; then pass "the COPIED adapter --help runs rc 0 from the staged dir (imports the copied harness and hypotheses)"; else fail "staged adapter --help rc=$rc: $(echo "$out" | tail -3)"; fi
BLOCK=$(awk "/<<'PY'\$/{f=1;next} /^PY\$/{f=0} f" "$L")
specs=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1"; for a in $ARMS; do read -r s0 nm <<< "$(arm_spec "$a")"; printf "%s %s;" "$a" "$nm"; done' x "$L")
combo=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1"; printf "%s" "$COMBO_NAME"' x "$L")
cand=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1"; printf "%s %s" "$CAND_SHA" "$BASE_SHA"' x "$L")
out=$(cd $W && envrun $PY -B - "$SA" "$combo" "$S58" "$specs" $cand <<< "$(printf '%s\n' "$BLOCK" | sed "s#'/root/models/smv3out-491ee4bf.npz'#'$PKG'#")" 2>&1); rc=$?
if [ "$rc" -eq 0 ] && echo "$out" | grep -q "exploiter sc8p PairChallengerBuryBot .*-sc8p diff \[\]"; then pass "the launcher's check_names block (byte for byte) runs rc 0 through the COPIED adapter: $(echo "$out" | grep -o 'exploiter sc8p PairChallengerBuryBot [^|]*')"; else fail "check_names through the staged adapter rc=$rc: $(echo "$out" | tail -3)"; fi
# 6. the r1 layout reproduces the finding
mkdir -p "$T/r1/claude-s67c" "$T/r1/claude-s66dev"; cp "$H/s67_sc8p_adapter.py" "$H/reader_lib/"*.py "$T/r1/claude-s67c/"; cp "$H/exploit_duel_s61.py" "$H/hypotheses.py" "$T/r1/claude-s66dev/"
out=$(cd /private/tmp && envrun $PY -B "$T/r1/claude-s67c/s67_sc8p_adapter.py" --help 2>&1); rc=$?
if [ "$rc" -ne 0 ] && echo "$out" | grep -q "FileNotFoundError" && echo "$out" | grep -q "claude-s67c/exploit_duel_s61.py"; then pass "r1 layout (harness only in the sibling claude-s66dev/) reproduces 6405786268: the adapter --help exits $rc with FileNotFoundError for claude-s67c/exploit_duel_s61.py"; else fail "r1 reproduction rc=$rc: $(echo "$out" | tail -2)"; fi
[ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILED"
exit "$fails"
