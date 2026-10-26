#!/bin/bash
# s69r2 launcher witnesses (= test_s69_launcher.sh with the s69r2 names; the rehearsal-wrapper sections 6-7 are dropped: s69r2 stages
# no wrapper and runs no rehearsal; section 10 shows the child form is s69's byte for byte).  s69's text:
# s69 launcher + rehearsal-wrapper witnesses (this Mac; writes nothing outside a temp dir).  The launcher is sourced with
# LANE_FUNCTIONS_ONLY=1 and LANE_ROOT / OUT pointed at a temp dir; host-only checks are stubbed where named.
#   1. run_dev refuses planted output (duel.jsonl, duel.stdout) with rc 3 and leaves it unchanged;
#   2. hold_guard refuses a HOLD file and a dangling HOLD symlink; release_ok refuses an absent, symlinked or wrong-sha RELEASE and accepts
#      the launcher's own sha; predispatch_guard refuses a removed RELEASE;
#   3. take_host_lock takes the mkdir lock with an owner line and release_locks removes only its own lock (a foreign owner is kept);
#   4. the main flow refuses an existing output root before it creates the status, and the file has no recovery / resume mode;
#   5. run_child's nine --exploiter-env arguments are exactly EX_ENV's words, and the DEV start line run_dev says (rendered by the real
#      run_dev with run_child stubbed) is the reader's START;
#   6. rehearse_s69_cloud.sh refuses a launcher sha that is not the one passed (before any lock), references no RELEASE file, does not
#      redefine run_child / dev_checks, and overrides only its window / paths / stop / wait knobs and lane_exit.
# Usage: bash test_s69_launcher.sh [launcher] > test_s69_launcher.out 2>&1; echo rc=$? >> test_s69_launcher.out
set -u
H=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
L=${1:-$H/claude_s69r2_cloud.sh}; RD=$H/s69r2_read.py; S69L=$H/../s69/claude_s69_cloud.sh
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
echo "launcher $(shasum -a 256 "$L" | cut -c1-64); s69 launcher $(shasum -a 256 "$S69L" | cut -c1-64)"
fails=0
pass () { echo "PASS $1"; }
fail () { echo "FAIL $1"; fails=$((fails + 1)); }
T=$(mktemp -d /private/tmp/s69launch.XXXX); trap 'rm -rf "$T"' EXIT
src () { printf 'LANE_FUNCTIONS_ONLY=1; LANE_ROOT=%q; OUT=%q; source %q\n' "$T" "$T/out" "$L"; }
# 1
for f in duel.jsonl duel.stdout; do
  rm -rf "$T/out"; mkdir -p "$T/out"; printf 'planted\n' > "$T/out/$f"; before=$(shasum -a 256 "$T/out/$f")
  out=$(bash -c "$(src); predispatch_guard () { :; }; dev_checks () { :; }; run_child () { echo CHILD-RAN; }; run_dev" 2>&1); rc=$?
  if [ "$rc" -eq 3 ] && grep -q "REFUSING: DEV output already exists in $T/out" <<< "$out" && ! grep -q CHILD-RAN <<< "$out" && [ "$(shasum -a 256 "$T/out/$f")" = "$before" ]; then
    pass "run_dev refuses a planted $f (rc 3), the child never starts, the file unchanged"
  else fail "run_dev with a planted $f: rc=$rc out=$(tail -2 <<< "$out")"; fi
done
rm -rf "$T/out"
# 2
touch "$T/claude_s69r2.HOLD"
out=$(bash -c "$(src); hold_guard" 2>&1); rc=$?
[ "$rc" -eq 3 ] && grep -q "REFUSING: HOLD file $T/claude_s69r2.HOLD exists" <<< "$out" && pass "hold_guard refuses a HOLD file (rc 3)" || fail "hold_guard HOLD file rc=$rc $out"
rm -f "$T/claude_s69r2.HOLD"; ln -s "$T/nowhere" "$T/claude_s69r2.HOLD"
out=$(bash -c "$(src); hold_guard" 2>&1); rc=$?
[ "$rc" -eq 3 ] && pass "hold_guard refuses a dangling HOLD symlink (rc 3)" || fail "hold_guard dangling symlink rc=$rc $out"
rm -f "$T/claude_s69r2.HOLD"
out=$(bash -c "$(src); release_ok" 2>&1); rc=$?
[ "$rc" -eq 3 ] && grep -q "absent or symlinked" <<< "$out" && pass "release_ok refuses an absent RELEASE" || fail "release_ok absent rc=$rc $out"
printf '%s\n' "$(printf '0%.0s' {1..64})" > "$T/claude_s69r2.RELEASE"
out=$(bash -c "$(src); release_ok" 2>&1); rc=$?
[ "$rc" -eq 3 ] && grep -q "RELEASE does not hold this launcher's sha256" <<< "$out" && pass "release_ok refuses a wrong-sha RELEASE" || fail "release_ok wrong sha rc=$rc $out"
shasum -a 256 "$L" | cut -c1-64 > "$T/real.RELEASE"; rm -f "$T/claude_s69r2.RELEASE"; ln -s "$T/real.RELEASE" "$T/claude_s69r2.RELEASE"
out=$(bash -c "$(src); release_ok" 2>&1); rc=$?
[ "$rc" -eq 3 ] && pass "release_ok refuses a symlinked RELEASE even with the right sha" || fail "release_ok symlink rc=$rc $out"
rm -f "$T/claude_s69r2.RELEASE"; cp "$T/real.RELEASE" "$T/claude_s69r2.RELEASE"
out=$(bash -c "$(src); release_ok && echo RELEASE-OK" 2>&1); rc=$?
[ "$rc" -eq 0 ] && grep -q RELEASE-OK <<< "$out" && pass "release_ok accepts the launcher's own sha256" || fail "release_ok own sha rc=$rc $out"
rm -f "$T/claude_s69r2.RELEASE"
out=$(bash -c "$(src); verify_tree () { :; }; FIRST_DISPATCH_DONE=1; predispatch_guard" 2>&1); rc=$?
[ "$rc" -eq 3 ] && grep -q "removed before dispatch" <<< "$out" && pass "predispatch_guard refuses a RELEASE removed before dispatch" || fail "predispatch removed rc=$rc $out"
# 3
out=$(bash -c "$(src); WAIT_START=\$SECONDS; take_host_lock; cat $T/.claude-host.lock/owner; release_locks; [ ! -e $T/.claude-host.lock ] && echo LOCK-GONE" 2>&1); rc=$?
[ "$rc" -eq 0 ] && grep -q " s69r2 " <<< "$out" && grep -q LOCK-GONE <<< "$out" && pass "take_host_lock takes the mkdir lock with an owner line; release_locks removes it" || fail "host lock rc=$rc $out"
mkdir "$T/.claude-host.lock"; echo "99999 other $(date -u +%FT%TZ)" > "$T/.claude-host.lock/owner"
out=$(bash -c "$(src); HOST_OWNED=1; release_locks; cat $T/.claude-host.lock/owner" 2>&1); rc=$?
grep -q "99999 other" <<< "$out" && [ -d "$T/.claude-host.lock" ] && pass "release_locks keeps a lock whose owner is another pid" || fail "foreign lock rc=$rc $out"
rm -rf "$T/.claude-host.lock"
# 4
a=$(grep -n '\[ ! -e "$OUT" \] || { echo "REFUSING: output root $OUT already exists"; exit 3; }' "$L" | cut -d: -f1); b=$(grep -n '(set -o noclobber; : > "$S")' "$L" | cut -d: -f1)
k=$(grep -n '^  mkdir -p "$OUT"' "$L" | cut -d: -f1); r=$(grep -n '^  run_dev$' "$L" | cut -d: -f1)
if [ -n "$a" ] && [ -n "$b" ] && [ -n "$k" ] && [ -n "$r" ] && [ "$a" -lt "$b" ] && [ "$b" -lt "$k" ] && [ "$k" -lt "$r" ]; then pass "main flow: output-root refusal (line $a) before the status (line $b), mkdir (line $k) and run_dev (line $r)"; else fail "main-flow order ($a $b $k $r)"; fi
grep -qE 'RECOVERY|ATTEMPT_ID|--resume' "$L" && fail "a recovery/resume mode is present" || pass "no recovery or resume mode in the launcher (fresh runs only)"
# 5
child=$(awk '/^run_child \(\) \{/,/^\}/' "$L" | grep -o -- '--exploiter-env [^ ]*' | sed 's/--exploiter-env //' | tr '\n' ' ' | sed 's/ $//')
exenv=$(bash -c "$(src); printf '%s' \"\$EX_ENV\"")
[ -n "$child" ] && [ "$child" = "$exenv" ] && [ "$(wc -w <<< "$child" | tr -d ' ')" = 9 ] && pass "run_child's nine --exploiter-env arguments are EX_ENV's words in order" || fail "child args '$child' vs EX_ENV '$exenv'"
mkdir -p "$T/out"
said=$(bash -c "$(src); predispatch_guard () { :; }; dev_checks () { :; }; install_lane_traps () { :; }; run_child () { :; }; say () { echo \"\$*\"; }; run_dev" 2>&1)
start=$(cd "$H" && "$PY" -B -c "import importlib.util; s = importlib.util.spec_from_file_location('r', '$RD'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.START)")
[ -n "$start" ] && [ "$said" = "$start" ] && pass "the DEV start line run_dev says is the reader's START (exact text)" || fail "start line differs: said '$said' reader '$start'"
rm -rf "$T/out"
# 8. stage_s69r2.sh semantics through ssh / scp shims on a temp host: a target already holding the SAME bytes is accepted as identical
#    and left as it is; a target with OTHER bytes refuses before any copy; an existing run path (a status) refuses before any copy
SH=$T/stagebin; mkdir -p "$SH"
printf '#!/bin/bash\nshift\nexec bash -c "$*"\n' > "$SH/ssh"
printf '#!/bin/bash\nargs=(); for a in "$@"; do [ "$a" = -q ] || args+=("$a"); done; n=${#args[@]}; d=${args[$((n-1))]}; d=${d#*:}; echo "scp $d" >> %q; exec cp "${args[@]:0:$((n-1))}" "$d"\n' "$T/scp.log" > "$SH/scp"
chmod +x "$SH/ssh" "$SH/scp"
LS=$(shasum -a 256 "$L" | cut -c1-64)
stage () { PATH="$SH:$PATH" S69_ROOT="$1" S69_SSH=ssh S69_SCP=scp bash "$H/stage_s69r2.sh" "$2" "$LS" 2>&1; }
HR=$T/hostA; mkdir -p "$HR/claude-s69"; cp "$H/exploit_duel_s61.py" "$HR/claude-s69/"; chmod a-w "$HR/claude-s69/exploit_duel_s61.py"; : > "$T/scp.log"
out=$(stage "$HR" lane); rc=$?
if [ "$rc" -eq 0 ] && grep -q "identical $HR/claude-s69/exploit_duel_s61.py" <<< "$out" && ! grep -q "exploit_duel_s61.py" "$T/scp.log" && grep -qE "STAGED ok \(s69r2-lane\): +3 files" <<< "$out"; then
  pass "stage lane: an already-staged identical harness is accepted as identical and not copied again; the other files copied and verified"
else fail "stage lane identical rc=$rc $(tail -3 <<< "$out")"; fi
HR=$T/hostB; mkdir -p "$HR/claude-s69"; echo different > "$HR/claude-s69/hypotheses.py"; : > "$T/scp.log"
out=$(stage "$HR" lane); rc=$?
[ "$rc" -eq 3 ] && grep -q "REFUSING: $HR/claude-s69/hypotheses.py exists on the host with other bytes" <<< "$out" && [ ! -s "$T/scp.log" ] && [ "$(cat "$HR/claude-s69/hypotheses.py")" = different ] \
  && pass "stage lane: a target with other bytes refuses (rc 3) before any copy, left unchanged" || fail "stage lane differ rc=$rc $(tail -3 <<< "$out")"
HR=$T/hostC; mkdir -p "$HR"; touch "$HR/claude_s69r2_screen.status"; : > "$T/scp.log"
out=$(stage "$HR" lane); rc=$?
[ "$rc" -eq 3 ] && grep -q "REFUSING: $HR/claude_s69r2_screen.status exists" <<< "$out" && [ ! -s "$T/scp.log" ] && pass "stage lane: an existing run path (status) refuses before any copy" || fail "stage lane run path rc=$rc $(tail -3 <<< "$out")"
# 9. the child runs with --history (r2), and the reader's START names it
awk '/^run_child \(\) \{/,/^\}/' "$L" | grep -q -- '--round-plan "$PLAN" --history --out' && pass "run_child passes --history to the producer" || fail "run_child has no --history"
# 10. the s69r2 launcher = s69's reviewed launcher 726a8af0 except the lane name, the output root, the seed block and header comments;
#     run_child (the child form the s69 host rehearsal and the s69 full run executed) is byte-identical
[ "$(shasum -a 256 "$S69L" | cut -c1-64)" = 726a8af097551ff77b996e741ce070605bf50838b4d045f72fc6cab8b9cac802 ] && pass "the s69 reference copy is the reviewed launcher 726a8af0" || fail "s69 reference launcher sha"
cmp -s <(awk '/^run_child \(\) \{/,/^\}/' "$S69L") <(awk '/^run_child \(\) \{/,/^\}/' "$L") && pass "run_child is byte-identical to s69's (the rehearsed and fully run child form)" || fail "run_child differs from s69's"
chg=$(diff <(grep -v '^#' "$S69L") <(grep -v '^#' "$L") | grep -E '^[<>]' | sed -E 's/^[<>] //' | sort -u | tr '\n' '|')
want='DEALS=600; SEED0=311060910; WORKERS=12; PLAN=r2; KILL_AFTER=28800; BACKSTOP=28810; MEM_MIN_KB=12582912   # 600 deals x 2 mirrors on the r2 rank-mixed plan per deal; the stop covers >= 2x the rehearsal projection (predeclare_s69.md); no predecessor gate (host-lock order)|DEALS=600; SEED0=312060910; WORKERS=12; PLAN=r2; KILL_AFTER=28800; BACKSTOP=28810; MEM_MIN_KB=12582912   # 600 deals x 2 mirrors on the r2 rank-mixed plan per deal; the stop covers >= 2x the rehearsal projection (predeclare_s69.md); no predecessor gate (host-lock order)|LANE=s69|LANE=s69r2|OUT=${OUT:-/root/vol-dev-claude-s69-r48-20261026}|OUT=${OUT:-/root/vol-dev-claude-s69r2-r48-20261026}|'
[ "$chg" = "$want" ] && pass "the only non-comment changes vs s69's launcher are LANE, OUT and SEED0" || fail "non-comment changes vs s69: $chg"
[ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILED"
exit "$fails"
