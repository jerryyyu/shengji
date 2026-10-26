#!/bin/bash
# s67c staging (run on THIS Mac by the operator, after Codex's PASS), in two phases, each refusing if ANY of its targets exists or is a
# symlink on the host (nothing is overwritten or removed); every copied file's sha256 is verified ON perf against this Mac's and the copies
# are made read-only.  It does not arm, DRYRUN or release anything, and it does not run the build.
#
#   bash stage_s67c.sh tree
#       copies $ROOT/claude_build_sc8p_perf.sh (the pinned perf build script) and $ROOT/claude-s67c/ (the adapter, the harness
#       exploit_duel_s61.py and hypotheses.py BESIDE it -- the adapter imports both from its own directory -- and the three pinned reader
#       helpers), then prints the EXACT build command the operator runs ON perf, detached:
#         HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_sc8p_perf.sh        (preflight)
#         HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_sc8p_perf.sh > /root/claude-sc8p-src-8a50fe8a-build.nohup 2>&1 &
#       Witness: /root/claude-sc8p-src-8a50fe8a-build.log ends with BUILD_RC=0 after three 'ext <module> <sha256>' lines; then on the Mac
#       `ssh shengji-perf cat /root/claude-sc8p-src-8a50fe8a-build.log > build.log && python3 make_s67c_final.py build.log &&
#        python3 make_s67c_reservation.py --force && python3 test_s67c_packet.py` (ALL PASS).
#   bash stage_s67c.sh lane <expected sha256 of claude_s67c_perf.final.sh>
#       copies the FINAL launcher to $ROOT/claude_s67c_perf.sh, the FINAL reader (its TRUSTED launcher sha = that sha) to
#       $ROOT/claude-s67c/s67c_read.py and the reservation to $ROOT/claude_reservations/s67c.json.
#
# The fresh-only check runs the remote loop with `bash -s -- <paths>` and the script on stdin, so the paths are the remote shell's
# positional arguments (ssh joins its command words into ONE remote command line).  Tested by test_s67c_stage.sh with an ssh shim that
# keeps that joining (absent / existing regular file / dangling symlink; no scp on a refusal; both phases).
# = s66dev's stage_s66dev.sh (r2, 57920d16) with the lane, the tree, the adapter and the staged directory changed.  r2 (Codex
# 1075/6405786268): r1 left the harness at /root/claude-s66dev/ and the staged adapter could not import it; the harness and hypotheses now
# stage beside the adapter, and test_s67c_stage.sh imports the staged adapter from the actually copied bytes.
# Test hooks: S67_SSH / S67_SCP (default ssh / scp) and S67_ROOT (default /root) -- never set in production use.
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c; LIB=$H/reader_lib; HOST=shengji-perf
SSH=${S67_SSH:-ssh}; SCP=${S67_SCP:-scp}; ROOT=${S67_ROOT:-/root}
PHASE=${1:-}; WANT=${2:-}
refuse_targets () {   # refuse_targets PATH...: ON the host, every path must be absent and not a symlink; the paths are bash -s positional arguments
  "$SSH" "$HOST" bash -s -- "$@" <<'REMOTE' || exit 3
set -u
[ "$#" -ge 1 ] || { echo "REFUSING: no target paths reached the host"; exit 3; }
for p in "$@"; do [ ! -e "$p" ] && [ ! -L "$p" ] || { echo "REFUSING: $p exists or is a symlink on the host"; exit 3; }; done
echo "targets clear ($# paths): $*"
REMOTE
}
case "$PHASE" in
  tree)
    refuse_targets "$ROOT/claude_build_sc8p_perf.sh" "$ROOT/claude-sc8p-src-8a50fe8a" "$ROOT/claude-sc8p-src-8a50fe8a.head" "$ROOT/claude-sc8p-src-8a50fe8a.clone-in-progress" "$ROOT/claude-sc8p-src-8a50fe8a-build.log" "$ROOT/claude-s67c"
    M=$(mktemp); trap 'rm -f $M' EXIT
    for f in $H/s67_sc8p_adapter.py $H/exploit_duel_s61.py $H/hypotheses.py $LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py; do echo "$(shasum -a 256 $f | cut -d' ' -f1)  $ROOT/claude-s67c/$(basename $f)"; done >> $M
    echo "$(shasum -a 256 $H/claude_build_sc8p_perf.sh | cut -d' ' -f1)  $ROOT/claude_build_sc8p_perf.sh" >> $M
    [ "$(wc -l < $M | tr -d ' ')" = 7 ] || { echo "REFUSING: expected 7 files"; cat $M; exit 3; }
    "$SSH" "$HOST" mkdir "$ROOT/claude-s67c" || exit 3
    "$SCP" -q $H/s67_sc8p_adapter.py $H/exploit_duel_s61.py $H/hypotheses.py $LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py "$HOST:$ROOT/claude-s67c/" || exit 3
    "$SCP" -q $H/claude_build_sc8p_perf.sh "$HOST:$ROOT/claude_build_sc8p_perf.sh" || exit 3
    "$SCP" -q $M "$HOST:$ROOT/claude-s67c/STAGED.tree.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s67c/STAGED.tree.sha256 && chmod a-w $ROOT/claude-s67c/* $ROOT/claude_build_sc8p_perf.sh && echo \"STAGED ok (tree phase): \$(wc -l < $ROOT/claude-s67c/STAGED.tree.sha256) files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON perf (detached, nice 19; clones https://github.com/jerryyyu/shengji.git at 8a50fe8a into /root/claude-sc8p-src-8a50fe8a and builds the three extensions):"
    echo "  HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_sc8p_perf.sh"
    echo "  HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_sc8p_perf.sh > /root/claude-sc8p-src-8a50fe8a-build.nohup 2>&1 &"
    ;;
  lane)
    [[ "$WANT" =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSING: pass the expected sha256 of claude_s67c_perf.final.sh"; exit 3; }
    [ -f $H/claude_s67c_perf.final.sh ] && [ "$(shasum -a 256 $H/claude_s67c_perf.final.sh | cut -d' ' -f1)" = "$WANT" ] || { echo "REFUSING: claude_s67c_perf.final.sh missing or not $WANT"; exit 3; }
    grep -q "TO_BE_PINNED;" $H/claude_s67c_perf.final.sh && { echo "REFUSING: the final launcher still holds a TO_BE_PINNED pin"; exit 3; }
    [ -f $H/s67c_read.final.py ] && grep -q "^TRUSTED_LAUNCHER_SHA256 = \"$WANT\"" $H/s67c_read.final.py || { echo "REFUSING: s67c_read.final.py missing or its TRUSTED_LAUNCHER_SHA256 is not $WANT"; exit 3; }
    python3 -c "import json,sys; r=json.load(open('$H/reservation_s67c.json')); sys.exit(0 if r['launcher_sha256']=='$WANT' and r['launcher']=='claude_s67c_perf.final.sh' and r['reader']=='Claude' else 3)" || { echo "REFUSING: reservation_s67c.json does not name the final launcher $WANT with reader Claude (run make_s67c_reservation.py --force and test_s67c_packet.py)"; exit 3; }
    refuse_targets "$ROOT/claude_s67c_perf.sh" "$ROOT/claude_s67c_screen.status" "$ROOT/claude_s67c.RELEASE" "$ROOT/claude_s67c.HOLD" "$ROOT/vol-dev-claude-s67c-r48-20261026" "$ROOT/claude_reservations/s67c.json" "$ROOT/claude-s67c/s67c_read.py" "$ROOT/claude-s67c/STAGED.lane.sha256"
    M=$(mktemp); trap 'rm -f $M' EXIT
    echo "$WANT  $ROOT/claude_s67c_perf.sh" >> $M
    echo "$(shasum -a 256 $H/s67c_read.final.py | cut -d' ' -f1)  $ROOT/claude-s67c/s67c_read.py" >> $M
    echo "$(shasum -a 256 $H/reservation_s67c.json | cut -d' ' -f1)  $ROOT/claude_reservations/s67c.json" >> $M
    "$SCP" -q $H/claude_s67c_perf.final.sh "$HOST:$ROOT/claude_s67c_perf.sh" || exit 3
    "$SCP" -q $H/s67c_read.final.py "$HOST:$ROOT/claude-s67c/s67c_read.py" || exit 3
    "$SCP" -q $H/reservation_s67c.json "$HOST:$ROOT/claude_reservations/s67c.json" || exit 3
    "$SCP" -q $M "$HOST:$ROOT/claude-s67c/STAGED.lane.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s67c/STAGED.lane.sha256 && chmod a-w $ROOT/claude_s67c_perf.sh $ROOT/claude-s67c/s67c_read.py $ROOT/claude_reservations/s67c.json $ROOT/claude-s67c/STAGED.lane.sha256 && echo \"STAGED ok (lane phase): 3 files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON perf: DRYRUN=1 bash /root/claude_s67c_perf.sh   (rc 0 and the names: line), then arm, then Claude's RELEASE (noclobber) after recomputing the sha on perf"
    ;;
  *) echo "usage: bash stage_s67c.sh tree | lane <sha256 of claude_s67c_perf.final.sh>"; exit 3;;
esac
