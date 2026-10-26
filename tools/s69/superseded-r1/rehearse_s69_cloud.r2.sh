#!/bin/bash
# s69 HOST REHEARSAL (non-scientific): runs the lane's OWN child form on shengji-cloud -- the staged launcher's run_child, byte for byte
# (setsid process group, timeout --signal=KILL, /usr/bin/time -v, all 12 workers, the nine --exploiter-env arguments, both arms as the lane
# builds them) -- after the lane's own dev_checks (packages, fly.toml + harness pins, compiled backend, check_names, MemAvailable) and under
# the shared mkdir host lock + legacy marker, on the throwaway window 311960000..311960035 (36 deals; not the lane's seeds), into its own
# output root.  It needs and writes no RELEASE: it is not the lane.  It refuses on a HOLD for the lane, an existing output / status, a
# launcher whose sha256 is not the one passed, or a busy host (the host-lock wait is bounded at 300 s).  A background sampler records the
# PEAK RSS of the child's whole process group every 5 s.  Terminal line: '<stamp> s69 REHEARSAL DONE rc=0 ...' (no LANE DONE).
# r2 (2026-10-26): r1's post-run cleanup check matched its own awk command line (the awk argv held the "--out <OUT>/duel.jsonl" text it
# searched for), so r1 REFUSED after a clean run; r2 passes the two halves of the pattern separately, so no process but the child's can hold
# it contiguously, and uses r2 paths.  r1 is kept in superseded-r1/ and its host output in rehearsal/host-r1/.
#   Usage ON shengji-cloud (detached):
#     nohup setsid bash /root/claude-s69/rehearse_s69_cloud.r2.sh <sha256 of /root/claude_s69_cloud.sh> > /root/claude_s69_rehearsal_r2.nohup 2>&1 < /dev/null &
set -u
LAUNCHER=${REHEARSAL_LAUNCHER:-/root/claude_s69_cloud.sh}
WANT=${1:-}
[[ "$WANT" =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSING: pass the expected sha256 of $LAUNCHER"; exit 3; }
[ -f "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ] && [ "$(sha256sum "$LAUNCHER" | cut -d' ' -f1)" = "$WANT" ] || { echo "REFUSING: $LAUNCHER missing, symlinked or not $WANT"; exit 3; }
LANE_FUNCTIONS_ONLY=1
source "$LAUNCHER" || { echo "REFUSING: could not source $LAUNCHER"; exit 3; }
unset LANE_FUNCTIONS_ONLY
[ "$SELF_SHA" = "$WANT" ] || { echo "REFUSING: the sourced launcher hashed itself as $SELF_SHA, not $WANT"; exit 3; }
# the rehearsal's own window, output root, status and stop (everything else is the lane's)
OUT=$LANE_ROOT/vol-rehearsal-claude-s69-r2-20261026
S=$LANE_ROOT/claude_s69_rehearsal_r2.status
PEAK=$LANE_ROOT/claude_s69_rehearsal_r2.peak_rss_kb
SEED0=311960000; DEALS=36; KILL_AFTER=5400; BACKSTOP=5410
WAIT_CEILING=300; LANE_SLEEP=10
placeholder_guard
verify_tree
hold_guard
[ "$(nproc)" -ge "$WORKERS" ] || { echo "REFUSING: fewer than $WORKERS cores on this host"; exit 3; }
[ ! -e "$OUT" ] && [ ! -L "$OUT" ] && [ ! -e "$PEAK" ] || { echo "REFUSING: rehearsal output $OUT or $PEAK already exists"; exit 3; }
(set -o noclobber; : > "$S") 2>/dev/null || { echo "REFUSING: cannot exclusively create status $S"; exit 3; }
STATUS_OWNED=1
trap 'lane_signal TERM 143' TERM; trap 'lane_signal INT 130' INT; trap 'lane_signal HUP 129' HUP
say "s69 REHEARSAL armed (pid $$, launcher $LAUNCHER sha256 $SELF_SHA): non-scientific window $SEED0+$DEALS, out $OUT, stop $KILL_AFTER s; no RELEASE involved"
WAIT_START=$SECONDS
take_host_lock
wait_legacy_peers
take_legacy_marker
install_lane_traps
dev_checks
mkdir "$OUT" || die "cannot create $OUT"
SAMPLER=
lane_exit () { [ -z "$SAMPLER" ] || kill "$SAMPLER" 2>/dev/null; release_locks; }   # the launcher's lane_exit plus: never leave the sampler behind
sample_group_rss () {   # the peak summed RSS (kB) of the child's process group (leader: pid == pgid, argv naming this OUT), every 5 s
  local peak=0 g t
  while kill -0 "$$" 2>/dev/null; do   # ends with the wrapper ($$ is the wrapper's pid in this subshell)
    g=$(ps -eo pid=,pgid=,args= | awk -v a="--out" -v b="$OUT/duel.jsonl" '$1 == $2 && index($0, a " " b) {print $1; exit}')
    if [ -n "$g" ]; then
      t=$(ps -eo pgid=,rss= | awk -v g="$g" '$1 == g {s += $2} END {print s + 0}')
      if [ "$t" -gt "$peak" ]; then peak=$t; echo "$peak" > "$PEAK.tmp" && mv "$PEAK.tmp" "$PEAK"; fi
    fi
    sleep 5
  done
}
sample_group_rss & SAMPLER=$!
say "s69 REHEARSAL start: defender $COMBO_NAME (R48 as served) vs exploiter $CAND_NAME ($EX_ENV); deals $DEALS seed0 $SEED0 plan $PLAN; workers $WORKERS; group KILL at $KILL_AFTER s (backstop $BACKSTOP s); group RSS sampler pid $SAMPLER"
RUN_RC=; RUN_WALL=; RUN_RSS=
run_child
kill "$SAMPLER" 2>/dev/null; wait "$SAMPLER" 2>/dev/null
say "s69 REHEARSAL peak process-group RSS $(cat "$PEAK" 2>/dev/null || echo '?') kB (5 s samples); largest single process (time -v) ${RUN_RSS:-?} kB"
[ "$RUN_RC" = 0 ] || die "rehearsal child rc $RUN_RC; no REHEARSAL DONE"
left=$(ps -eo pid=,args= | awk -v a="--out" -v b="$OUT/duel.jsonl" 'index($0, a " " b) {print $1}' | tr "\n" " ")   # the halves passed apart: this awk's own argv never holds them contiguously
[ -z "$left" ] || die "processes naming $OUT/duel.jsonl still alive after the run: $left"
say "s69 REHEARSAL cleanup: no process names $OUT/duel.jsonl; run group reaped (run_child's sweep found no live member)"
say "s69 REHEARSAL DONE rc=0 wall_s=$RUN_WALL deals=$DEALS workers=$WORKERS"
exit 0
