#!/bin/bash
# lane-lib: required
# S160: the RT4 attribution rider (PREDECLARE_S160.md beside this file) on the M5 Ultra.  Arms B4 (belief-only swap into R54),
# U4 (heads-only swap into R54) and D4 (RT4 vs RT2), 1,000 paired seat-swapped rank-mixed deals each, under the RT2-attrib kit
# (kit/ut_mix_adapter.py, kit/ut_mix_read.py) on the claude-ut-retrain2 tree.  The launcher holds the shared host lock from the
# first pilot through the attribution; s160_run.sh co-runs under it.
#
# usage: s160.sh MODE      MODE = identity | check | run
#   identity: prints the launcher identity (lane_identity of LANE_FILES = the RELEASE token) and exits; runs nothing
#   check   : every arming check except the RELEASE (hostname, HOLD, pins, tree, clearance, seeds, saved results), no lock, no
#             producer; writes check.status only
#   run ID  : the arms in ARMS order, started by dispatch_s160.sh on the Mini only when the Ultra queue's next entry is this
#             lane released at this identity.  ID must equal the launcher identity.  Token: S160_RELEASE, first field = the
#             launcher identity, checked at entry (lane_arm) and again before every step (lane_admit).  Direct admission only:
#             a held host lock refuses (ABORT rc=5) instead of waiting.
# Steps per arm (each skipped only when its saved output validates; a reader never runs twice):
#   pilot (s160_run.sh pilot<ARM>, 20 deals) -> pilot check (s160_guard.py pilot-check: seal, mirror teams, the pinned
#   reader's validity; to .tmp, renamed only when VALID, else kept as .invalid.json) -> arm (s160_run.sh <ARM>) -> verify
#   (s160_guard.py verify-seal) -> read (a noclobber claim readout/<ARM>.read.claim, then s160_guard.py read: the seal and the
#   mirror-team check, then kit/ut_mix_read.py once, then the binding readout/<ARM>.read.bind.json; rc kept in
#   readout/<ARM>.read.rc; rc != 0 = ABORT).  A saved read is accepted only through its binding, never by re-parsing rows.
# A claim without a fully verified read (json, rc 0, verify-read), or any read output without a claim, stops the chain.
# A completed, bound arm is reused before any payload check: verify-read reads only metadata (DONE digest, SHA256SUMS,
# the binding's read, reader and recipe digests) and never opens a sealed payload; fresh arms keep the full seal check.
# After U4's read: the attribution (s160_attrib.py once, on the sealed B4 and U4 reads).  After the last arm: the readout seal
#   -> DONE.
# Completion: DONE only when every arm's reader exited 0 with a VALID read and the attribution exited 0.  Anything else is ABORT
#   with every file kept.  An unfinished arm (output or status without a verifying DONE) is never renamed or re-dealt: ABORT rc=7.
# Status ($S/<mode>.status, lane_lib): S160 START|ARMED|WAIT|LOCKED|CHECKED|PRODUCER|STEP|NOTE ...; one terminal:
#   S160 DONE claude-s160-run <utc> label=<LABEL> d4_mean=<x> attrib_sha256=<sha> sums_sha256=<sha> identity=<id> mode=run rc=0
#   S160 PAUSED <lane> <utc> reason=...   (HOLD, wall ceiling, disk floor, signal)
#   S160 ABORT <lane> <utc> rc=<n> reason=...
set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
MODE=${1:?usage: s160.sh identity|check|run IDENTITY}
W=$(cd "$(dirname "$0")" && pwd) && [ -n "$W" ] || { echo "REFUSING: cannot resolve the launcher directory" >&2; exit 6; }
. "$W/lanes/lane_lib.sh"
. "$W/s160.cfg"
case $MODE in
  run)      LANE_NAME=claude-s160-run;   LANE_RELEASE=$S160_RELEASE ;;
  check)    LANE_NAME=claude-s160-check; LANE_RELEASE="" ;;
  identity) ;;
  *) echo "MODE must be identity, check or run" >&2; exit 2 ;;
esac
LANE_FILES=("$W/s160.sh" "$W/lanes/lane_lib.sh" "$W/s160.cfg" "$W/PREDECLARE_S160.md" "$W/make_recipe_s160.py" "$W/s160_run.sh"
  "$W/s160_attrib.py" "$W/s160_guard.py" "$W/dispatch_s160.sh" "$RECIPE" "$W/clear/CLEARED")
if [ "$MODE" = identity ]; then lane_identity "${LANE_FILES[@]}"; exit $?; fi
[ "$W" = "$S" ] || { echo "REFUSING: launcher directory $W is not the lane $S" >&2; exit 6; }
LANE_STATUS=$S/$MODE.status
LANE_PINS="$(echo "$S160_PINS" | awk 'NF {print $2"  "$1}')"
s160_pin_hook() {   # the lane tree clean at its HEAD; the clearance recorded
  [ "$(git -C "$T" rev-parse HEAD 2>/dev/null)" = "$TREE_HEAD" ] || { echo "tree $T is not at $TREE_HEAD"; return 1; }
  [ -z "$(git -C "$T" status --porcelain 2>&1)" ] || { echo "tree $T is dirty"; return 1; }
  grep -q "^CLEAR " "$S/clear/CLEARED" || { echo "no CLEAR line in $S/clear/CLEARED"; return 1; }
}
LANE_PIN_HOOK=s160_pin_hook
last=$(lane_last_state "$LANE_STATUS")
if [ "$MODE" = run ]; then   # a finished run is never run again; check is repeatable
  case "$last" in "S160 DONE "*) echo "refusing: $LANE_STATUS already ends DONE: $last" >&2; exit 2;; esac
fi
GD=$W/s160_guard.py; AT=$W/s160_attrib.py; REF=$S/ref/R4H.read.json
AJ=$S/readout/ATTRIB.json; AO=$S/readout/ATTRIB.out; AE=$S/readout/ATTRIB.err; ARC=$S/readout/ATTRIB.rc; ACL=$S/readout/ATTRIB.claim

guard() {   # s160_guard.py SUBCOMMAND ARGS... in the tree's environment; its last output line is in LANE_MSG on failure
  local o
  o=$({ cd "$T/server" && PYTHONPATH="$T/server" "$PY" -B "$GD" "$@"; } 2>&1) && return 0
  LANE_MSG="$(echo "$o" | tail -1 | cut -c1-300)"; return 1
}
arm_paths() {   # ARM: sets the per-arm paths
  OUT=$S/out/$1; ST=$S/$1.status; POUT=$S/pilot$1; PST=$S/pilot$1.status
  PCHK=$S/pilot$1.check.json; PINV=$S/pilot$1.check.invalid.json
  RJ=$S/readout/$1.read.json; RO=$S/readout/$1.read.out; RE=$S/readout/$1.read.err; RRC=$S/readout/$1.read.rc
  RCL=$S/readout/$1.read.claim; RBD=$S/readout/$1.read.bind.json
}
claim() {   # FILE: a noclobber attempt claim; fails if any claim (or file) is already there
  ( set -C; printf '%s\n' "claude s160 pid=$$ identity=${LANE_ARMED_ID:-none} $(lane_now)" > "$1" ) 2>/dev/null
}
read_state() {   # CLAIM JSON RC OUT ERR BIND VERIFY...: 0 = no attempt; 1 = a fully verified saved result; 2 = partial (LANE_MSG)
  local cl=$1 js=$2 rcf=$3 ou=$4 er=$5 bd=$6; shift 6
  LANE_MSG=""
  if [ -e "$cl" ] || [ -L "$cl" ]; then
    [ -f "$js" ] && [ -f "$rcf" ] && [ "$(head -1 "$rcf")" = 0 ] && [ -e "$ou" ] && [ -e "$er" ] && guard "$@" "$js" && return 1
    LANE_MSG="a claimed attempt ($cl) has no fully verified result: ${LANE_MSG:-files missing}"; return 2
  fi
  for f in "$js" "$rcf" "$ou" "$er" "$bd"; do
    [ -e "$f" ] || [ -L "$f" ] && { LANE_MSG="$f exists without an attempt claim"; return 2; }
  done
  return 0
}
preflight() {   # every saved result is verified before anything is dispatched; a failed or partial one stops the chain, kept
  local arm r
  for arm in $ARMS; do
    arm_paths "$arm"
    { [ -e "$PINV" ] || [ -e "$PCHK.tmp" ]; } && { LANE_MSG="pilot$arm has a failed or partial check recorded ($PINV / $PCHK.tmp)"; return 1; }
    if [ -e "$PCHK" ] || [ -L "$PCHK" ]; then
      guard verify-pilot "$RECIPE" "$arm" "$PCHK" || { LANE_MSG="saved pilot check $PCHK: $LANE_MSG; kept"; return 1; }
    fi
    read_state "$RCL" "$RJ" "$RRC" "$RO" "$RE" "$RBD" verify-read "$RECIPE" "$arm"; r=$?
    [ "$r" = 2 ] && return 1
  done
  read_state "$ACL" "$AJ" "$ARC" "$AO" "$AE" "$ACL.none" verify-attrib "$RECIPE"; r=$?
  [ "$r" = 2 ] && return 1
  return 0
}

if [ "$MODE" = check ]; then
  lane_init "mode=check arms=$ARMS"
  id=$(lane_identity "${LANE_FILES[@]}") || lane_abort 6 "identity"
  [ "$(hostname)" = "$LANE_HOSTNAME" ] || lane_abort 6 "hostname $(hostname)"
  if lane_hold_present; then lane_pause "$LANE_MSG"; fi
  lane_check_pins || lane_abort 6 "$LANE_MSG"
  lane_say CHECKED "identity=$id pins ok"
  if lane_require_registered_seeds "$BLOCK_SEED0" "$BLOCK_CLUSTERS"; then lane_say CHECKED "block: $LANE_MSG"
  else lane_say NOTE "not yet admissible for run: $LANE_MSG"; fi
  if preflight; then
    lane_say CHECKED "saved results: none or valid"
    for arm in $ARMS; do   # the run loop's reuse decision, by the same read_state call
      arm_paths "$arm"; read_state "$RCL" "$RJ" "$RRC" "$RO" "$RE" "$RBD" verify-read "$RECIPE" "$arm"; r=$?
      [ "$r" = 1 ] && lane_say CHECKED "arm $arm: bound read reused from metadata"
    done
    read_state "$ACL" "$AJ" "$ARC" "$AO" "$AE" "$ACL.none" verify-attrib "$RECIPE"; r=$?
    [ "$r" = 1 ] && lane_say CHECKED "attribution: bound result reused from metadata"
  else lane_say NOTE "saved results: $LANE_MSG"; fi
  lane_done "identity=$id mode=check"
  exit 0
fi

[ "${2:-}" = "$(lane_identity "${LANE_FILES[@]}" 2>/dev/null)" ] || { echo "REFUSING: run needs the launcher identity as its argument" >&2; exit 6; }
lane_init "mode=$MODE arms=$ARMS"
lane_arm; g=$?; [ "$g" = 3 ] && lane_pause "$LANE_MSG"; [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"
lane_say ARMED "identity=$LANE_ARMED_ID"
[ -e "$LANE_LOCK" ] && lane_abort 5 "host lock held by: $(head -1 "$LANE_LOCK/owner" 2>/dev/null); direct admission only, no wait"
git -C "$LANE_SEED_TREE" fetch -q origin main 2>/dev/null && git -C "$LANE_SEED_TREE" checkout -q --detach origin/main 2>/dev/null \
  || lane_abort 6 "seed tree fetch of origin/main failed ($LANE_SEED_TREE)"
lane_require_registered_seeds "$BLOCK_SEED0" "$BLOCK_CLUSTERS" || lane_abort 6 "$LANE_MSG"
lane_say CHECKED "$LANE_MSG"
preflight || lane_abort 6 "preflight: $LANE_MSG; nothing dispatched"
lane_lock_acquire; g=$?; case $g in 0) ;; 3) lane_pause "$LANE_MSG" ;; 5) lane_abort 5 "$LANE_MSG" ;; *) lane_abort 6 "$LANE_MSG" ;; esac
lane_admit after-wait; g=$?; [ "$g" = 3 ] && lane_pause "$LANE_MSG"; [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"
lane_say CHECKED "$LANE_MSG"
preflight || lane_abort 6 "preflight after the wait: $LANE_MSG; nothing dispatched"

export S160_LANE_PID=$$
mkdir -p "$S/logs" "$S/readout"
readmit() { lane_admit "pre-$1"; g=$?; [ "$g" = 3 ] && lane_pause "$LANE_MSG"; [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"; }
aside() {   # PATH...: an unfinished pilot output is renamed (never deleted) so the runner starts clean
  local p to
  for p in "$@"; do
    [ -e "$p" ] || continue
    to="$p.partial-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$p" "$to" || lane_abort 6 "cannot move aside $p"
    lane_say NOTE "moved aside unfinished $p -> $to"
  done
}

do_attrib() {   # once, on the sealed B4 and U4 reads (D4 is not an input), under a noclobber attempt claim
  local r
  read_state "$ACL" "$AJ" "$ARC" "$AO" "$AE" "$ACL.none" verify-attrib "$RECIPE"; r=$?
  [ "$r" = 2 ] && lane_abort 4 "attribution: $LANE_MSG; kept"
  if [ "$r" = 0 ]; then
    readmit attrib
    claim "$ACL" || lane_abort 4 "attribution: cannot claim $ACL (an attempt exists)"
    LANE_LOG=$S/logs/attrib.log; LANE_MAX_SECONDS=$ATTRIB_MAX; LANE_PAUSE_NOTE="step attrib"
    lane_supervise /bin/bash -c 'exec "$1" -I -B "$2" --recipe "$3" --readout "$4" --ref-joint "$5" --out "$6" > "$7" 2> "$8"' attrib \
      "$PY" "$AT" "$RECIPE" "$S/readout" "$REF" "$AJ" "$AO" "$AE"; arc=$?
    echo "$arc" > "$ARC" || lane_abort 4 "cannot record the attribution rc"
    [ "$arc" = 0 ] || lane_abort 4 "attribution rc=$arc ($(cut -c1-200 "$AE" 2>/dev/null)); kept"
  fi
  guard verify-attrib "$RECIPE" "$AJ" || lane_abort 4 "the attribution does not verify ($LANE_MSG); kept"
  lane_say STEP "attrib $(cut -c1-200 "$AO" 2>/dev/null)"
}

for ARM in $ARMS; do
  arm_paths "$ARM"
  DEALS=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["arms"][sys.argv[2]]["deals"])' "$RECIPE" "$ARM") \
    || lane_abort 6 "recipe has no arm $ARM"
  [ "$DEALS" = "$ARM_DEALS" ] || lane_abort 6 "recipe arm $ARM has $DEALS deals, the cfg $ARM_DEALS"
  # a completed, bound arm is reused from metadata only, before any fresh-arm payload check
  read_state "$RCL" "$RJ" "$RRC" "$RO" "$RE" "$RBD" verify-read "$RECIPE" "$ARM"; r=$?
  [ "$r" = 2 ] && lane_abort 4 "read $ARM: $LANE_MSG; kept"
  if [ "$r" = 1 ]; then
    lane_say STEP "arm $ARM reused: bound read verified from metadata ($(lane_sha "$RBD"))"
    [ "$ARM" = U4 ] && do_attrib
    continue
  fi
  # pilot: 20 deals + the validity check (no outcome computed)
  if [ ! -e "$PCHK" ]; then
    if ! guard verify-seal "$RECIPE" "$ARM" pilot; then
      aside "$POUT" "$PST"; readmit "pilot-$ARM"
      LANE_LOG=$S/logs/pilot$ARM.log; LANE_MAX_SECONDS=$PILOT_MAX; LANE_PAUSE_NOTE="step pilot $ARM"
      lane_supervise /bin/bash "$W/s160_run.sh" "pilot$ARM" "$PILOT_DEALS" "$RECIPE"; rc=$?
      [ "$rc" = 0 ] || lane_abort "$rc" "pilot runner rc=$rc (status $PST)"
      guard verify-seal "$RECIPE" "$ARM" pilot || lane_abort 4 "pilot output does not verify ($LANE_MSG)"
    fi
    readmit "pilot-check-$ARM"
    ( cd "$T/server" && PYTHONPATH="$T/server" "$PY" -B "$GD" pilot-check "$RECIPE" "$ARM" ) > "$PCHK.tmp" 2> "$S/logs/pilot$ARM.check.err"; prc=$?
    if [ "$prc" = 0 ] && mv "$PCHK.tmp" "$PCHK" && guard verify-pilot "$RECIPE" "$ARM" "$PCHK"; then :
    else
      if [ -e "$PCHK.tmp" ]; then mv "$PCHK.tmp" "$PINV" || lane_abort 4 "pilot: cannot keep the failed check"
      elif [ -e "$PCHK" ]; then mv "$PCHK" "$PINV" || lane_abort 4 "pilot: cannot keep the failed check"; fi
      lane_abort 4 "pilot $ARM validity rc=$prc ($(cut -c1-300 "$PINV")); kept as $PINV; no arm dispatched"
    fi
  fi
  guard verify-pilot "$RECIPE" "$ARM" "$PCHK" || lane_abort 4 "pilot check of $ARM does not verify ($LANE_MSG); no arm dispatched"
  lane_say STEP "pilot $ARM VALID ($(lane_sha "$PCHK"))"
  # arm: a fresh start only; an unfinished one is kept as is for a decision
  if ! guard verify-seal "$RECIPE" "$ARM" duel; then
    { [ -e "$RCL" ] || [ -e "$RJ" ]; } && lane_abort 6 "a read attempt exists for an arm that does not verify"
    { [ -e "$OUT" ] || [ -e "$ST" ]; } && lane_abort 7 "unfinished arm kept as is ($OUT, $ST): it needs a decision, never a re-deal"
    readmit "arm-$ARM"
    LANE_LOG=$S/logs/$ARM.log; LANE_MAX_SECONDS=$ARM_MAX; LANE_PAUSE_NOTE="step arm $ARM"
    lane_supervise /bin/bash "$W/s160_run.sh" "$ARM" "$WORKERS" "$RECIPE"; rc=$?
    [ "$rc" = 0 ] || lane_abort "$rc" "arm runner rc=$rc (status $ST)"
    guard verify-seal "$RECIPE" "$ARM" duel || lane_abort 4 "arm output does not verify ($LANE_MSG)"
  fi
  lane_say STEP "arm $ARM rows=$((2 * DEALS)) sums=$(lane_sha "$OUT/SHA256SUMS")"
  # read: once, under a noclobber claim made before any raw output is opened (no attempt exists here: checked above)
  if true; then
    readmit "read-$ARM"
    claim "$RCL" || lane_abort 4 "read $ARM: cannot claim $RCL (an attempt exists)"
    LANE_LOG=$S/logs/$ARM.read.log; LANE_MAX_SECONDS=$READ_MAX; LANE_PAUSE_NOTE="step read $ARM"
    lane_supervise /bin/bash -c 'cd "$1" && PYTHONPATH="$1" exec "$2" -B "$3" read "$4" "$5" "$6" > "$7" 2> "$8"' read \
      "$T/server" "$PY" "$GD" "$RECIPE" "$ARM" "$RJ" "$RO" "$RE"; rc=$?
    echo "$rc" > "$RRC" || lane_abort 4 "cannot record the reader rc"
    lane_say STEP "read $ARM rc=$rc $(cut -c1-200 "$RO" 2>/dev/null)"
    [ "$rc" = 0 ] || lane_abort 4 "reader rc=$rc on $ARM: not a completed read (diagnostics kept in $S/readout)"
  fi
  guard verify-read "$RECIPE" "$ARM" "$RJ" || lane_abort 4 "the $ARM read does not verify ($LANE_MSG); kept"
  [ "$ARM" = U4 ] && do_attrib
done

LABEL=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["label"])' "$AJ") || lane_abort 4 "attribution label"
D4M=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["outcome"]["levels"]["mean"])' "$S/readout/D4.read.json") || lane_abort 4 "D4 mean"
(cd "$S/readout" || exit 1; set --; for f in *.read.claim *.read.bind.json *.read.json *.read.out *.read.err *.read.rc ATTRIB.claim ATTRIB.json ATTRIB.out ATTRIB.err ATTRIB.rc; do
   [ -e "$f" ] && set -- "$@" "$f"; done; shasum -a 256 "$@" > SHA256SUMS) || lane_abort 4 "readout seal failed"
lane_done "label=$LABEL d4_mean=$D4M attrib_sha256=$(lane_sha "$AJ") sums_sha256=$(lane_sha "$S/readout/SHA256SUMS") identity=$LANE_ARMED_ID mode=$MODE"
