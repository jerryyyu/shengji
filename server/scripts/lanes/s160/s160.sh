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
#   run     : the arms in ARMS order.  Token: S160_RELEASE, first field = the launcher identity, checked at entry (lane_arm) and
#             again before every step (lane_admit: identity unchanged since arming, RELEASE, pins).
# Steps per arm (each skipped only when its saved output validates; a reader never runs twice):
#   pilot (s160_run.sh pilot<ARM>, 20 deals) -> pilot check (kit/mix_pilot_check.py: validity only; to .tmp, renamed only when
#   VALID, else kept as .invalid.json) -> arm (s160_run.sh <ARM>) -> verify (DONE line, rows, SHA256SUMS) -> read
#   (kit/ut_mix_read.py once; rc kept in readout/<ARM>.read.rc; rc != 0 = ABORT).
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
MODE=${1:?usage: s160.sh identity|check|run}
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
  "$W/s160_attrib.py" "$RECIPE" "$W/clear/CLEARED")
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
RD=$W/kit/ut_mix_read.py; PC=$W/kit/mix_pilot_check.py; AT=$W/s160_attrib.py; REF=$S/ref/R4H.read.json
AJ=$S/readout/ATTRIB.json; AO=$S/readout/ATTRIB.out; AE=$S/readout/ATTRIB.err; ARC=$S/readout/ATTRIB.rc

run_done() {   # STATUS DEALS OUT: the runner's own DONE line for this recipe with 2*DEALS rows, and its sums verify
  local st=$1 n=$2 out=$3 rsha
  rsha=$(lane_sha "$RECIPE") || return 1
  grep -qE '^UTD (ABORT|PAUSED|WARNING|REFUSING|FAILED) ' "$st" 2>/dev/null && return 1
  grep -v '^UTD UNLOCKED ' "$st" 2>/dev/null | tail -1 | grep -qE "^UTD DONE [^ ]+ recipe=$rsha rows=$((2 * n)) sums=[0-9a-f]{64} rc=0\$" || return 1
  (cd "$out" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1) || return 1
}
ok_json() {   # ok_json pilot|read|attrib FILE ARM: rc 0 only if FILE is this arm's VALID result for the current recipe and reader
  "$PY" -I -B - "$1" "$2" "$3" "$RECIPE" "$RD" "$AT" <<'PYEOF'
import hashlib, json, sys
kind, f, arm, rp, rd, at = sys.argv[1:7]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
try:
    d = json.load(open(f))
except Exception as exc:
    print(f"{f} does not parse ({type(exc).__name__})"); sys.exit(1)
if not isinstance(d, dict):
    print(f"{f} is not an object"); sys.exit(1)
bad = []
if kind == "pilot":
    if d.get("validity") != "VALID" or d.get("failing") != []:
        bad.append(f"pilot verdict {d.get('validity')!r} failing {d.get('failing')!r}")
elif kind == "read":
    v = d.get("validity") if isinstance(d.get("validity"), dict) else {}
    b = d.get("binding") if isinstance(d.get("binding"), dict) else {}
    for ok, m in ((d.get("schema") == "utx-read-r1", "schema"), (d.get("arm") == arm, "arm"), (d.get("reader_sha256") == sha(rd), "reader"),
                  (b.get("recipe_sha256") == sha(rp), "recipe"), (v.get("verdict") == "VALID", "validity"), (isinstance(d.get("outcome"), dict), "outcome")):
        if not ok:
            bad.append(m)
else:
    for ok, m in ((d.get("schema") == "s160-attrib-r1", "schema"), (d.get("attrib_sha256") == sha(at), "attrib"),
                  (d.get("recipe_sha256") == sha(rp), "recipe"), (isinstance(d.get("label"), str), "label")):
        if not ok:
            bad.append(m)
print("; ".join(bad) or "ok")
sys.exit(1 if bad else 0)
PYEOF
}
arm_paths() {   # ARM: sets the per-arm paths
  OUT=$S/out/$1; ST=$S/$1.status; POUT=$S/pilot$1; PST=$S/pilot$1.status
  PCHK=$S/pilot$1.check.json; PINV=$S/pilot$1.check.invalid.json
  RJ=$S/readout/$1.read.json; RO=$S/readout/$1.read.out; RE=$S/readout/$1.read.err; RRC=$S/readout/$1.read.rc
}
preflight() {   # every saved result is validated before anything is dispatched; a failed or partial one stops the chain, kept
  local o arm
  for arm in $ARMS; do
    arm_paths "$arm"
    { [ -e "$PINV" ] || [ -e "$PCHK.tmp" ]; } && { LANE_MSG="pilot$arm has a failed or partial check recorded ($PINV / $PCHK.tmp)"; return 1; }
    if [ -e "$PCHK" ] || [ -L "$PCHK" ]; then
      o=$(ok_json pilot "$PCHK" "$arm") || { LANE_MSG="saved pilot check $PCHK is not VALID ($o); kept"; return 1; }
      run_done "$PST" "$PILOT_DEALS" "$POUT" || { LANE_MSG="saved pilot check $PCHK has no verifying sealed pilot"; return 1; }
    fi
    if [ -e "$RJ" ] || [ -L "$RJ" ]; then
      [ "$(head -1 "$RRC" 2>/dev/null)" = 0 ] || { LANE_MSG="saved read $RJ has reader rc '$(head -1 "$RRC" 2>/dev/null)' (want 0); kept"; return 1; }
      o=$(ok_json read "$RJ" "$arm") || { LANE_MSG="saved read $RJ is not a VALID read of this recipe ($o); kept"; return 1; }
      run_done "$ST" "$ARM_DEALS" "$OUT" || { LANE_MSG="saved read $RJ has no verifying sealed arm"; return 1; }
    elif [ -e "$RRC" ]; then LANE_MSG="a reader rc record ($RRC) exists without its read JSON"; return 1; fi
  done
  if [ -e "$AJ" ]; then
    [ "$(head -1 "$ARC" 2>/dev/null)" = 0 ] && o=$(ok_json attrib "$AJ" -) || { LANE_MSG="saved attribution $AJ does not validate; kept"; return 1; }
  else
    for f in "$AO" "$AE" "$ARC"; do [ -e "$f" ] && { LANE_MSG="an attribution output ($f) exists without $AJ: it runs once"; return 1; }; done
  fi
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
  if preflight; then lane_say CHECKED "saved results: none or valid"; else lane_say NOTE "saved results: $LANE_MSG"; fi
  lane_done "identity=$id mode=check"
  exit 0
fi

lane_init "mode=$MODE arms=$ARMS"
lane_arm; g=$?; [ "$g" = 3 ] && lane_pause "$LANE_MSG"; [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"
lane_say ARMED "identity=$LANE_ARMED_ID"
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

do_attrib() {   # once, on the sealed B4 and U4 reads (D4 is not an input)
  if [ ! -e "$AJ" ]; then
    readmit attrib
    LANE_LOG=$S/logs/attrib.log; LANE_MAX_SECONDS=$ATTRIB_MAX; LANE_PAUSE_NOTE="step attrib"
    lane_supervise /bin/bash -c 'exec "$1" -I -B "$2" --recipe "$3" --readout "$4" --ref-joint "$5" --out "$6" > "$7" 2> "$8"' attrib \
      "$PY" "$AT" "$RECIPE" "$S/readout" "$REF" "$AJ" "$AO" "$AE"; arc=$?
    echo "$arc" > "$ARC" || lane_abort 4 "cannot record the attribution rc"
    [ "$arc" = 0 ] || lane_abort 4 "attribution rc=$arc ($(cut -c1-200 "$AE" 2>/dev/null)); kept"
  fi
  o=$(ok_json attrib "$AJ" -) || lane_abort 4 "the attribution does not validate ($o); kept"
  lane_say STEP "attrib $(cut -c1-200 "$AO" 2>/dev/null)"
}

for ARM in $ARMS; do
  arm_paths "$ARM"
  DEALS=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["arms"][sys.argv[2]]["deals"])' "$RECIPE" "$ARM") \
    || lane_abort 6 "recipe has no arm $ARM"
  [ "$DEALS" = "$ARM_DEALS" ] || lane_abort 6 "recipe arm $ARM has $DEALS deals, the cfg $ARM_DEALS"
  # pilot: 20 deals + the validity check (no outcome computed)
  if [ ! -e "$PCHK" ]; then
    if ! run_done "$PST" "$PILOT_DEALS" "$POUT"; then
      aside "$POUT" "$PST"; readmit "pilot-$ARM"
      LANE_LOG=$S/logs/pilot$ARM.log; LANE_MAX_SECONDS=$PILOT_MAX; LANE_PAUSE_NOTE="step pilot $ARM"
      lane_supervise /bin/bash "$W/s160_run.sh" "pilot$ARM" "$PILOT_DEALS" "$RECIPE"; rc=$?
      [ "$rc" = 0 ] || lane_abort "$rc" "pilot runner rc=$rc (status $PST)"
      run_done "$PST" "$PILOT_DEALS" "$POUT" || lane_abort 4 "pilot output does not verify ($PST)"
    fi
    readmit "pilot-check-$ARM"
    ( cd "$T/server" && PYTHONPATH="$T/server" "$PY" -B "$PC" "$RECIPE" "$ARM" "$POUT" ) > "$PCHK.tmp" 2> "$S/logs/pilot$ARM.check.err"; prc=$?
    if [ "$prc" = 0 ] && o=$(ok_json pilot "$PCHK.tmp" "$ARM"); then mv "$PCHK.tmp" "$PCHK" || lane_abort 4 "pilot: rename of the VALID check failed"
    else
      mv "$PCHK.tmp" "$PINV" || lane_abort 4 "pilot: cannot keep the failed check"
      lane_abort 4 "pilot $ARM validity rc=$prc ($(cut -c1-300 "$PINV")); kept as $PINV; no arm dispatched"
    fi
  fi
  lane_say STEP "pilot $ARM VALID ($(lane_sha "$PCHK"))"
  # arm: a fresh start only; an unfinished one is kept as is for a decision
  if ! run_done "$ST" "$DEALS" "$OUT"; then
    [ -e "$RJ" ] && lane_abort 6 "a read exists ($RJ) for an arm that does not verify"
    { [ -e "$OUT" ] || [ -e "$ST" ]; } && lane_abort 7 "unfinished arm kept as is ($OUT, $ST): it needs a decision, never a re-deal"
    readmit "arm-$ARM"
    LANE_LOG=$S/logs/$ARM.log; LANE_MAX_SECONDS=$ARM_MAX; LANE_PAUSE_NOTE="step arm $ARM"
    lane_supervise /bin/bash "$W/s160_run.sh" "$ARM" "$WORKERS" "$RECIPE"; rc=$?
    [ "$rc" = 0 ] || lane_abort "$rc" "arm runner rc=$rc (status $ST)"
    run_done "$ST" "$DEALS" "$OUT" || lane_abort 4 "arm output does not verify ($ST)"
  fi
  lane_say STEP "arm $ARM rows=$((2 * DEALS)) sums=$(lane_sha "$OUT/SHA256SUMS")"
  # read: once, on the sealed output; its rc is recorded beside it and must be 0, and the file must validate
  if [ ! -e "$RJ" ]; then
    readmit "read-$ARM"
    LANE_LOG=$S/logs/$ARM.read.log; LANE_MAX_SECONDS=$READ_MAX; LANE_PAUSE_NOTE="step read $ARM"
    lane_supervise /bin/bash -c 'cd "$1" && PYTHONPATH="$1" exec "$2" -B "$3" --recipe "$4" --arm "$5" --out "$6" > "$7" 2> "$8"' read \
      "$T/server" "$PY" "$RD" "$RECIPE" "$ARM" "$RJ" "$RO" "$RE"; rc=$?
    echo "$rc" > "$RRC" || lane_abort 4 "cannot record the reader rc"
    lane_say STEP "read $ARM rc=$rc $(cut -c1-200 "$RO" 2>/dev/null)"
    [ "$rc" = 0 ] || lane_abort 4 "reader rc=$rc on $ARM: not a completed read (diagnostics kept in $S/readout)"
  fi
  [ "$(head -1 "$RRC" 2>/dev/null)" = 0 ] || lane_abort 4 "reader rc record of $ARM is not 0"
  o=$(ok_json read "$RJ" "$ARM") || lane_abort 4 "the $ARM read is not a VALID read ($o); kept"
  [ "$ARM" = U4 ] && do_attrib
done

LABEL=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["label"])' "$AJ") || lane_abort 4 "attribution label"
D4M=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["outcome"]["levels"]["mean"])' "$S/readout/D4.read.json") || lane_abort 4 "D4 mean"
(cd "$S/readout" || exit 1; set --; for f in *.read.json *.read.out *.read.err *.read.rc ATTRIB.json ATTRIB.out ATTRIB.err ATTRIB.rc; do
   [ -e "$f" ] && set -- "$@" "$f"; done; shasum -a 256 "$@" > SHA256SUMS) || lane_abort 4 "readout seal failed"
lane_done "label=$LABEL d4_mean=$D4M attrib_sha256=$(lane_sha "$AJ") sums_sha256=$(lane_sha "$S/readout/SHA256SUMS") identity=$LANE_ARMED_ID mode=$MODE"
