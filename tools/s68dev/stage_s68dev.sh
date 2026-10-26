#!/bin/bash
# s68dev staging (run on THIS Mac by the operator), in two phases, each refusing if ANY of its targets exists or is a symlink on the host
# (nothing is overwritten or removed); every copied file's sha256 is verified ON perf against this Mac's and the copies are made
# read-only.  It does not arm, DRYRUN or release anything, and it does not run the build.
#
#   bash stage_s68dev.sh tree
#       copies $ROOT/claude_build_s68_perf.sh (the pinned perf build script) and $ROOT/claude-s68dev/ (the adapter s66_sc8_adapter.py,
#       the harness exploit_duel_s61.py and hypotheses.py BESIDE it -- the adapter imports both from its own directory -- and the four
#       pinned reader helpers incl. compare_runs.py), then prints the EXACT build command the operator runs ON perf, detached:
#         HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_s68_perf.sh        (preflight)
#         HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_s68_perf.sh > /root/claude-s68-src-8b6ead10-build.nohup 2>&1 &
#       Witness: /root/claude-s68-src-8b6ead10-build.log ends with BUILD_RC=0 after three 'ext <module> <sha256>' lines; then on the Mac
#       `ssh shengji-perf cat /root/claude-s68-src-8b6ead10-build.log > build.log && python3 make_s68dev_final.py build.log &&
#        python3 make_s68dev_reservation.py --force && python3 test_s68dev_packet.py` (ALL PASS).
#   bash stage_s68dev.sh lane <expected sha256 of claude_s68dev_perf.final.sh>
#       copies the FINAL launcher to $ROOT/claude_s68dev_perf.sh, the FINAL reader (its TRUSTED launcher sha = that sha) to
#       $ROOT/claude-s68dev/s68dev_read.py and the reservation to $ROOT/claude_reservations/s68dev.json.
#
# The fresh-only check runs the remote loop with `bash -s -- <paths>` and the script on stdin, so the paths are the remote shell's
# positional arguments (ssh joins its command words into ONE remote command line).
# = s67c's stage_s68dev.sh (r2) with the lane, the tree, the adapter, the staged directory and the reader helper list changed
# (make_s68dev_stage.py).  Test hooks: S68_SSH / S68_SCP (default ssh / scp) and S68_ROOT (default /root) -- never set in production use.
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s68-combo/tools/s68dev; LIB=$H/reader_lib; HOST=shengji-perf
SSH=${S68_SSH:-ssh}; SCP=${S68_SCP:-scp}; ROOT=${S68_ROOT:-/root}
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
    refuse_targets "$ROOT/claude_build_s68_perf.sh" "$ROOT/claude-s68-src-8b6ead10" "$ROOT/claude-s68-src-8b6ead10.head" "$ROOT/claude-s68-src-8b6ead10.clone-in-progress" "$ROOT/claude-s68-src-8b6ead10-build.log" "$ROOT/claude-s68dev"
    M=$(mktemp); trap 'rm -f $M' EXIT
    for f in $H/s66_sc8_adapter.py $H/exploit_duel_s61.py $H/hypotheses.py $LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py $LIB/compare_runs.py; do echo "$(shasum -a 256 $f | cut -d' ' -f1)  $ROOT/claude-s68dev/$(basename $f)"; done >> $M
    echo "$(shasum -a 256 $H/claude_build_s68_perf.sh | cut -d' ' -f1)  $ROOT/claude_build_s68_perf.sh" >> $M
    [ "$(wc -l < $M | tr -d ' ')" = 8 ] || { echo "REFUSING: expected 8 files"; cat $M; exit 3; }
    "$SSH" "$HOST" mkdir "$ROOT/claude-s68dev" || exit 3
    "$SCP" -q $H/s66_sc8_adapter.py $H/exploit_duel_s61.py $H/hypotheses.py $LIB/row_schema.py $LIB/validity.py $LIB/reader_lib.py $LIB/compare_runs.py "$HOST:$ROOT/claude-s68dev/" || exit 3
    "$SCP" -q $H/claude_build_s68_perf.sh "$HOST:$ROOT/claude_build_s68_perf.sh" || exit 3
    "$SCP" -q $M "$HOST:$ROOT/claude-s68dev/STAGED.tree.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s68dev/STAGED.tree.sha256 && chmod a-w $ROOT/claude-s68dev/* $ROOT/claude_build_s68_perf.sh && echo \"STAGED ok (tree phase): \$(wc -l < $ROOT/claude-s68dev/STAGED.tree.sha256) files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON perf (detached, nice 19; clones https://github.com/jerryyyu/shengji.git at 8b6ead10 into /root/claude-s68-src-8b6ead10 and builds the three extensions):"
    echo "  HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_s68_perf.sh"
    echo "  HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_s68_perf.sh > /root/claude-s68-src-8b6ead10-build.nohup 2>&1 &"
    ;;
  lane)
    [[ "$WANT" =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSING: pass the expected sha256 of claude_s68dev_perf.final.sh"; exit 3; }
    [ -f $H/claude_s68dev_perf.final.sh ] && [ "$(shasum -a 256 $H/claude_s68dev_perf.final.sh | cut -d' ' -f1)" = "$WANT" ] || { echo "REFUSING: claude_s68dev_perf.final.sh missing or not $WANT"; exit 3; }
    grep -q "TO_BE_PINNED;" $H/claude_s68dev_perf.final.sh && { echo "REFUSING: the final launcher still holds a TO_BE_PINNED pin"; exit 3; }
    [ -f $H/s68dev_read.final.py ] && grep -q "^TRUSTED_LAUNCHER_SHA256 = \"$WANT\"" $H/s68dev_read.final.py || { echo "REFUSING: s68dev_read.final.py missing or its TRUSTED_LAUNCHER_SHA256 is not $WANT"; exit 3; }
    python3 -c "import json,sys; r=json.load(open('$H/reservation_s68dev.json')); sys.exit(0 if r['launcher_sha256']=='$WANT' and r['launcher']=='claude_s68dev_perf.final.sh' and r['reader']=='Claude' else 3)" || { echo "REFUSING: reservation_s68dev.json does not name the final launcher $WANT with reader Claude (run make_s68dev_reservation.py --force and test_s68dev_packet.py)"; exit 3; }
    refuse_targets "$ROOT/claude_s68dev_perf.sh" "$ROOT/claude_s68dev_screen.status" "$ROOT/claude_s68dev.RELEASE" "$ROOT/claude_s68dev.HOLD" "$ROOT/vol-dev-claude-s68dev-r48-20261026" "$ROOT/claude_reservations/s68dev.json" "$ROOT/claude-s68dev/s68dev_read.py" "$ROOT/claude-s68dev/STAGED.lane.sha256"
    M=$(mktemp); trap 'rm -f $M' EXIT
    echo "$WANT  $ROOT/claude_s68dev_perf.sh" >> $M
    echo "$(shasum -a 256 $H/s68dev_read.final.py | cut -d' ' -f1)  $ROOT/claude-s68dev/s68dev_read.py" >> $M
    echo "$(shasum -a 256 $H/reservation_s68dev.json | cut -d' ' -f1)  $ROOT/claude_reservations/s68dev.json" >> $M
    "$SCP" -q $H/claude_s68dev_perf.final.sh "$HOST:$ROOT/claude_s68dev_perf.sh" || exit 3
    "$SCP" -q $H/s68dev_read.final.py "$HOST:$ROOT/claude-s68dev/s68dev_read.py" || exit 3
    "$SCP" -q $H/reservation_s68dev.json "$HOST:$ROOT/claude_reservations/s68dev.json" || exit 3
    "$SCP" -q $M "$HOST:$ROOT/claude-s68dev/STAGED.lane.sha256" || exit 3
    "$SSH" "$HOST" "sha256sum -c $ROOT/claude-s68dev/STAGED.lane.sha256 && chmod a-w $ROOT/claude_s68dev_perf.sh $ROOT/claude-s68dev/s68dev_read.py $ROOT/claude_reservations/s68dev.json $ROOT/claude-s68dev/STAGED.lane.sha256 && echo \"STAGED ok (lane phase): 3 files verified on the host, read-only\"" || exit 3
    echo "NEXT, ON perf: DRYRUN=1 bash /root/claude_s68dev_perf.sh   (rc 0 and the names: line), then arm, then Claude's RELEASE (noclobber) after recomputing the sha on perf"
    ;;
  *) echo "usage: bash stage_s68dev.sh tree | lane <sha256 of claude_s68dev_perf.final.sh>"; exit 3;;
esac
