#!/bin/bash
# S52 DEV paired implementation check. This launcher requires RELEASE, creates no RELEASE,
# reads no gameplay outcomes, and never preempts or resumes a predecessor lane.
# Claude writes the RELEASE after the independent review and Jerry's standing authorization.
set -u
SRC_EXCLUDE=':(exclude)server/runs/seed_windows.json'
SELF=$(readlink -f "${BASH_SOURCE[0]}")
SELF_SHA=$(sha256sum "$SELF" | cut -d" " -f1)

ARM=0
for arg in "$@"; do
  case "$arg" in --arm) [ "$ARM" -eq 0 ] || { echo "REFUSING: duplicate --arm"; exit 3; }; ARM=1 ;;
                 *) echo "REFUSING: unexpected argument $arg"; exit 3 ;; esac
done
DRY=${DRYRUN:-0}
[ "$DRY" = "1" ] || [ "$ARM" -eq 1 ] || { echo "REFUSING: run with DRYRUN=1 or --arm"; exit 3; }
[ "$DRY" = "1" ] && [ "$ARM" -eq 1 ] && { echo "REFUSING: DRYRUN=1 and --arm together"; exit 3; }
[ "$SELF" = /root/s52dev/launch_s52_dev.sh ] || { echo "REFUSING: unexpected launcher path $SELF"; exit 3; }
[ "$(hostname)" = ubuntu-32gb-hel1-2 ] || { echo "REFUSING: not the reviewed host (hostname $(hostname))"; exit 3; }

for key in ${!SHENGJI_@}; do unset "$key"; done
unset RUNPVC1_CONTAIN
export SHENGJI_FAST=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
R=/root/codex-s52dev-src-3464a1b1; PY=/root/gen-hybrid/server/.venv/bin/python
PIN_FULL=3464a1b19451f5e9276e463f1b59894ad77b6909
TREE_NATIVE='99472ae0396967ea02bc7fcb1d7c6bee5438a5549f7d3b405061862d3de4299a  server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so
52759fde0b3e0c080fce7db19180ee53ae1f1b77657143a3d2c88e8f9bef73ec  server/shengji/ai/_endgame_fast.cpython-314-x86_64-linux-gnu.so
1da16497b194f965d9b0a289c3c6b00ddc346490a33f2c4d1da288058ad50606  server/shengji/ai/_cwv_math.cpython-314-x86_64-linux-gnu.so'
RUN=s52dev
LANE_DIR=/root/s52dev
RUNNER=$LANE_DIR/run_s52_dev.py
RUNNER_SHA=265271e06fd00b6db36c216529c144101819685bf787d81c9325c73e905a24b5
OUT=$LANE_DIR/output; S=/root/s52dev.status
SEED0=184060910; PAIRS=624; WORKERS=14
RELEASE=/root/claude_s52dev.RELEASE
HOLDS="/root/claude_s52dev.HOLD /root/claude_screen.HOLD"
RESERVATION=/root/claude_reservations/s52dev.json
PVCKPT=/root/models/smv3out-491ee4bf.npz; PVSHA=491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670
BELIEFCKPT=/root/models/s17long-e2-763b5e05.npz; BELIEFSHA=763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343
CONTROL_EXPECT=pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0
CAND_EXPECT=pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-lar-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r250a42e1-bury-hybrid-bwv-ef1b87579f4c
WAIT_CEILING=10800
HOSTLOCK=/root/.claude-host.lock
LEGACY_SCREEN_LOCK=/root/.claude-screen.lock
LEGACY_RE="cwv_screen[_]queue|shengji.harvest.trajector[y]|policy_world[_]duel|policy_abc[_]launche[r]|cwv_shortlist[_]screen"
CHILD_LOG=$LANE_DIR/runner.log
POLL_PRED_S=120; POLL_RELEASE_S=30; POLL_LOCK_S=30; POLL_LEGACY_S=30
DRAIN_TERM_S=120; DRAIN_KILL_S=60
STATUS_OWNED=0
# >>> LOCKLIB (r2: signal/drain/HOLD-safe supervision; fl-pilot/runpvc1/test_runpvc1_locks.sh sources this block VERBATIM,
#     extracted between the two marker lines, with synthetic children and temp paths; the lane sets the paths/bounds).
say () { if [ "$STATUS_OWNED" -eq 1 ]; then echo "$(date -u +%FT%TZ) $*" >> "$S"; else echo "$(date -u +%FT%TZ) $*"; fi; }
die () { say "REFUSING: $*"; exit 3; }
hold_release_guard () {   # $1 = need_release
  for h in $HOLDS; do [ ! -e "$h" ] && [ ! -L "$h" ] || die "HOLD file $h exists"; done
  [ "$1" = "1" ] || return 0
  [ -f "$RELEASE" ] && [ ! -L "$RELEASE" ] || die "RELEASE $RELEASE absent or symlinked"
  [ "$(tr -d " \n" < "$RELEASE")" = "$SELF_SHA" ] || die "RELEASE does not hold this launcher's sha256 ($SELF_SHA)"
  [ "$(sha256sum "$SELF" | cut -d" " -f1)" = "$SELF_SHA" ] || die "launcher file changed since arming"
}
HOST_OWNED=0; HOST_ID=''; OWNER=''; CHILD_PID=''; CHILD_PGID=''; CHILD_REAPED=0; CHILD_RC=''; SLEEP_PID=''; PENDING_SIG=''
CONTAINMENT_FAILED=0
# r4: OWNERSHIP TOKEN.  Each launch gets a fresh 128-bit token in RUNPVC1_CONTAIN, set ONLY in the child's exec
# environment (never in this supervisor's), inherited by every descendant.  A process is "owned" only if, read at signal
# time, /proc/<pid>/environ holds exactly RUNPVC1_CONTAIN=<token> AND /proc/<pid>/stat puts it in the owned group (or it
# is the published leader).  Only owned pids are ever signalled, one by one, re-verified immediately before each kill;
# never the numeric -PGID.  The variable is not SHENGJI_*, and the harvest records only fixed env keys (verified).
CONTAIN_VAR=RUNPVC1_CONTAIN; CONTAIN_TOKEN=''
CENSUS=unknown; OWNED_PIDS=''; CENSUS_WHY=''
# every wait sleeps in the background so a signal is handled at once, not after the sleep
nap () { sleep "$1" & SLEEP_PID=$!; wait "$SLEEP_PID" 2>/dev/null; SLEEP_PID=''; }
new_contain_token () {
  CONTAIN_TOKEN=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')
  [[ $CONTAIN_TOKEN =~ ^[0-9a-f]{32}$ ]] || die "cannot generate the containment token"
}
# 0 owned | 1 alive but NOT ours (no/other token, or outside the owned group) | 2 unverifiable | 3 gone or zombie
owned_pid () {
  local p=$1 st rest envs
  [[ $p =~ ^[0-9]+$ ]] || return 2
  [ -n "$CONTAIN_TOKEN" ] && [ -n "$CHILD_PGID" ] || return 2
  if ! st=$(cat "/proc/$p/stat" 2>/dev/null) || [ -z "$st" ]; then [ -e "/proc/$p" ] && return 2; return 3; fi
  rest=${st##*) }; set -- $rest                      # state ppid pgrp ...
  [ "$#" -ge 3 ] && [[ $3 =~ ^[0-9]+$ ]] || return 2
  [ "$1" = Z ] && return 3
  if ! envs=$(tr '\0' '\n' 2>/dev/null < "/proc/$p/environ"); then [ -e "/proc/$p" ] && return 2; return 3; fi
  grep -qxF "$CONTAIN_VAR=$CONTAIN_TOKEN" <<< "$envs" || return 1
  [ "$3" = "$CHILD_PGID" ] || [ "$p" = "$CHILD_PID" ] || return 1
  return 0
}
# r4 census: a VALIDATED ps snapshot (rc 0, non-empty, every line parses, contains this supervisor) lists the live members
# of the owned group (plus the published leader until reaped); each member is then verified by owned_pid.
#   CENSUS=gone     validated snapshot, no live member
#   CENSUS=owned    every live member verified owned (OWNED_PIDS)
#   CENSUS=unknown  anything else: census failed/empty/self-less/malformed, a member is not ours or unverifiable, or a
#                   member vanished mid-verification (OWNED_PIDS may still list verified-owned members)
census () {
  CENSUS=unknown; OWNED_PIDS=''; CENSUS_WHY=''
  local out members p r foreign=0 unver=0 gone=0
  if ! out=$(ps -eo pid=,pgid=,stat= 2>/dev/null); then CENSUS_WHY='ps failed'; return 0; fi
  [ -n "$out" ] || { CENSUS_WHY='ps printed nothing'; return 0; }
  if ! members=$(awk -v me="$$" -v g="$CHILD_PGID" -v l="$CHILD_PID" -v reaped="$CHILD_REAPED" '
        NF != 3 || $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9]+$/ { bad = 1; next }
        $1 == me { self = 1 }
        $3 ~ /^Z/ { next }
        g != "" && $2 == g { print $1; next }
        reaped != 1 && l != "" && $1 == l { print $1 }
        END { if (bad || !self) exit 3 }' <<< "$out"); then
    CENSUS_WHY='census malformed or without this supervisor'; return 0
  fi
  [ -n "$members" ] || { CENSUS=gone; return 0; }
  for p in $members; do
    owned_pid "$p"; r=$?
    case $r in 0) OWNED_PIDS="$OWNED_PIDS $p" ;; 1) foreign=$((foreign + 1)) ;; 3) gone=$((gone + 1)) ;; *) unver=$((unver + 1)) ;; esac
  done
  OWNED_PIDS=${OWNED_PIDS# }
  if [ $foreign -eq 0 ] && [ $unver -eq 0 ] && [ $gone -eq 0 ]; then CENSUS=owned; return 0; fi
  CENSUS_WHY="$foreign live member(s) not carrying this arm's token or outside the group, $unver unverifiable, $gone vanished mid-verification"
}
census_summary () { echo "$CENSUS; owned [${OWNED_PIDS}]${CENSUS_WHY:+; $CENSUS_WHY}"; }
group_members () { census; case $CENSUS in gone) echo 0 ;; owned) echo $OWNED_PIDS | wc -w ;; *) echo unresolved; return 2 ;; esac; }
signal_owned () {         # $1 = TERM|KILL; each pid re-verified immediately before its own kill; nothing else is signalled
  local p
  for p in $OWNED_PIDS; do owned_pid "$p" && kill -"$1" "$p" 2>/dev/null; done
}
drain_phase () {          # $1 signal, $2 seconds: census -> signal verified owned pids -> wait, until gone or the bound
  local t=0
  while :; do
    census; [ "$CENSUS" = gone ] && return 0
    signal_owned "$1"
    [ $t -lt "$2" ] || return 0
    sleep 1; t=$((t + 1))
  done
}
# returns 0 only when a validated census shows the owned group gone; an unknown census sends NO signal to anything unverified
drain_child () {
  [ -n "$CHILD_PID" ] || return 0
  census
  if [ "$CENSUS" != gone ]; then
    [ "$CENSUS" = unknown ] && say "STOP: containment unknown for group $CHILD_PGID ($(census_summary)); unverified processes are never signalled"
    say "STOP: draining group $CHILD_PGID: TERM to verified owned pids only, up to ${DRAIN_TERM_S}s"
    drain_phase TERM "$DRAIN_TERM_S"
    if [ "$CENSUS" != gone ]; then
      say "STOP: group $CHILD_PGID not proven gone after TERM ($(census_summary)); KILL to verified owned pids only, up to ${DRAIN_KILL_S}s"
      drain_phase KILL "$DRAIN_KILL_S"
    fi
    census
    if [ "$CENSUS" != gone ]; then
      say "STOP: containment unknown: group $CHILD_PGID NOT proven gone ($(census_summary))"
      return 1
    fi
    say "STOP: owned child group $CHILD_PGID drained (validated census: no live members)"
  fi
  [ "$CHILD_REAPED" = 1 ] || wait "$CHILD_PID" 2>/dev/null
  CHILD_PID=''; CHILD_PGID=''
  return 0
}
# removes the host lock ONLY if this process created it (HOST_OWNED, set right after a successful mkdir), it is still the
# same inode, and its owner is ours or not yet published; a foreign/changed lock is never touched
release_host_lock () {
  [ "$HOST_OWNED" -eq 1 ] || return 0
  if [ -d "$HOSTLOCK" ] && [ ! -L "$HOSTLOCK" ] && [ -n "$HOST_ID" ] && [ "$(stat -c '%d:%i' "$HOSTLOCK" 2>/dev/null)" = "$HOST_ID" ] \
     && [ ! -L "$HOSTLOCK/owner" ] && { [ ! -e "$HOSTLOCK/owner" ] || [ "$(cat "$HOSTLOCK/owner" 2>/dev/null)" = "$OWNER" ]; }; then
    rm -f "$HOSTLOCK/owner" "$HOSTLOCK/.owner.$$"
    if rmdir "$HOSTLOCK" 2>/dev/null; then HOST_OWNED=0; say "host lock $HOSTLOCK released (pid $$)"
    else say "WARNING: preserving nonempty host lock $HOSTLOCK: $(ls -A "$HOSTLOCK" 2>/dev/null | tr "\n" " ")"; fi
  else
    say "WARNING: preserving foreign, changed or unverifiable host lock $HOSTLOCK"
  fi
}
retain_lock_line () { say "STOP: host lock $HOSTLOCK RETAINED: containment unknown for group $CHILD_PGID after TERM ${DRAIN_TERM_S}s + KILL ${DRAIN_KILL_S}s ($(census_summary)); the host is NOT free (remove the lock by hand only once that group is gone)"; }
cleanup () {              # EXIT trap: drain first; release the host lock only after the drain is proven
  trap '' INT TERM HUP
  [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null
  [ "$CONTAINMENT_FAILED" = 1 ] && return 0      # already reported; keep the lock and the diagnostics exactly as they are
  if drain_child; then release_host_lock; else retain_lock_line; fi
}
on_signal () { trap '' INT TERM HUP; say "STOP: signal $1 received; no further dispatch"; exit 143; }
install_signal_traps () { trap 'on_signal TERM' TERM; trap 'on_signal INT' INT; trap 'on_signal HUP' HUP; }
defer_signals () { PENDING_SIG=''; trap 'PENDING_SIG=TERM' TERM; trap 'PENDING_SIG=INT' INT; trap 'PENDING_SIG=HUP' HUP; }
service_pending () { install_signal_traps; [ -z "$PENDING_SIG" ] || on_signal "$PENDING_SIG"; }
wait_predecessor () {
  while ! grep -q "=== $PRED DONE ===" "$PRED_STATUS" 2>/dev/null; do
    grep -q "=== $PRED STOPPED" "$PRED_STATUS" 2>/dev/null && { say "REFUSING: predecessor $PRED stopped without completing; re-arm it first"; exit 11; }
    hold_release_guard 0
    nap "$POLL_PRED_S"
  done
}
wait_release () {         # ceiling WAIT_CEILING
  local start=$SECONDS
  until [ -e "$RELEASE" ] || [ -L "$RELEASE" ]; do
    hold_release_guard 0
    [ $(( SECONDS - start )) -lt "$WAIT_CEILING" ] || die "wait ceiling reached without RELEASE; nothing started"
    nap "$POLL_RELEASE_S"
  done
  nap 5
  hold_release_guard 1
}
acquire_host_lock () {    # signals are DEFERRED across mkdir + owner publication, then handled
  while :; do
    hold_release_guard 1
    defer_signals
    if mkdir "$HOSTLOCK" 2>/dev/null; then
      HOST_OWNED=1
      HOST_ID=$(stat -c '%d:%i' "$HOSTLOCK" 2>/dev/null)
      OWNER="$$ $RUN $(date -u +%FT%TZ)"
      { echo "$OWNER" > "$HOSTLOCK/.owner.$$" && mv -f "$HOSTLOCK/.owner.$$" "$HOSTLOCK/owner"; } 2>/dev/null
    fi
    service_pending
    [ "$HOST_OWNED" -eq 1 ] && break
    nap "$POLL_LOCK_S"
  done
  [ -n "$HOST_ID" ] && [ "$(cat "$HOSTLOCK/owner" 2>/dev/null)" = "$OWNER" ] || die "could not publish the owner of $HOSTLOCK"
  say "$RUN holds the host lock $HOSTLOCK (pid $$)"
}
# r3: the legacy-process scan is a validated observation too: a failed/empty/self-less ps is "not clear", never "clear"
legacy_clear () {
  local out
  if ! out=$(ps -eo pid=,stat=,args= 2>/dev/null) || [ -z "$out" ] \
     || ! awk -v me="$$" '$1 == me { f = 1 } END { exit !f }' <<< "$out"; then
    say "legacy-peer census unresolved (ps failed or incomplete); treating as NOT clear"; return 1
  fi
  ! awk '$2 !~ /^T/' <<< "$out" | grep -qE "$LEGACY_RE"
}
legacy_peer_waits () {    # the template's legacy gate, with HOLD/RELEASE checked on every poll
  while [ -e "$LEGACY_SCREEN_LOCK" ] || [ -L "$LEGACY_SCREEN_LOCK" ]; do hold_release_guard 1; nap "$POLL_LEGACY_S"; done
  until legacy_clear; do hold_release_guard 1; nap "$POLL_LEGACY_S"; done
}
confirm_launch () {       # still under deferral: bounded wait until the leader is verifiably ours (or already gone)
  local i=0 r
  while [ $i -lt 100 ]; do
    owned_pid "$CHILD_PID"; r=$?
    { [ $r -eq 0 ] || [ $r -eq 3 ]; } && return 0
    sleep 0.1; i=$((i + 1))
  done
  say "WARNING: child $CHILD_PID not verified as owned within 10 s of launch; containment would be unknown"
}
run_child () {            # "$@" = the job; its OWN process group (setsid) and a fresh ownership token
  hold_release_guard 1
  new_contain_token
  defer_signals           # no signal is serviced between the launch and the publication of BOTH identities
  RUNPVC1_CONTAIN="$CONTAIN_TOKEN" setsid "$@" >> "$CHILD_LOG" 2>&1 < /dev/null &
  CHILD_PID=$!
  CHILD_PGID=$CHILD_PID
  CHILD_REAPED=0
  confirm_launch
  service_pending         # a signal that arrived in the window is handled now: cleanup drains the published child
  say "child pid $CHILD_PID (own process group $CHILD_PGID; ownership token set in its environment, not logged)"
  wait "$CHILD_PID"; CHILD_RC=$?; CHILD_REAPED=1
}
# the whole armed sequence; the lane supplies post_release_checks / dispatch_checks / announce_start / finish
supervise () {
  trap cleanup EXIT
  install_signal_traps
  wait_predecessor
  wait_release
  post_release_checks
  acquire_host_lock
  legacy_peer_waits
  hold_release_guard 1
  dispatch_checks
  announce_start
  run_child "$@"
  if drain_child; then
    release_host_lock
    finish "$CHILD_RC"
  else                    # no finish/terminal success line; explicit non-success terminal line, lock kept, rc 4
    retain_lock_line
    CONTAINMENT_FAILED=1
    say "=== $RUN CONTAINMENT FAILED rc=$CHILD_RC (leader exited; containment unknown, group not proven gone; host lock retained; no completion claimed) ==="
    exit 4
  fi
}
# <<< LOCKLIB

# The LOCKLIB and token-drain functions above are carried forward unchanged.
# Lane-specific admission and terminal checks follow.
ARM_START=$SECONDS; FIRST_DISPATCH_DONE=0
eval "locklib_hold_release_guard () $(declare -f hold_release_guard | tail -n +2)"
hold_release_guard () {
  locklib_hold_release_guard "$@"
  if [ "$FIRST_DISPATCH_DONE" -eq 0 ] && [ $(( SECONDS - ARM_START )) -ge "$WAIT_CEILING" ]; then
    die "wait ceiling ${WAIT_CEILING}s reached before dispatch; nothing started"
  fi
}
PROC=/proc
read_environ () { tr '\0' '\n' < "$PROC/$1/environ"; }   # one pid's environ, one entry per line; nonzero on a failed read
# VALIDATED token enumeration.  Prints the pids whose environ holds exactly RUNPVC1_CONTAIN=<token> (never this shell)
# and returns 0 only if every live pid's environ was read and this shell was among the pids seen.  A failed read is
# fine only for a pid that cannot carry the token: one that has vanished (no $PROC/<pid>), a zombie or dead task (stat
# state Z/X), or a kernel thread (stat flags PF_KTHREAD 0x00200000; its environ open fails with ESRCH).  Any other
# failed read (EACCES, ESRCH on a user process, an unparsable stat) makes the enumeration UNKNOWN: it returns 2 and
# prints a last line "WHY <reason>".  Callers run it in a
# command substitution, so the reason travels on stdout, not in a variable.
cannot_carry () {         # 0 iff $PROC/<pid>/stat proves a zombie/dead task or a kernel thread (or the pid is gone)
  local st rest
  if ! st=$(cat "$PROC/$1/stat" 2>/dev/null) || [ -z "$st" ]; then [ -e "$PROC/$1" ] && return 1; return 0; fi
  rest=${st##*) }; set -- $rest               # state ppid pgrp session tty tpgid flags ...
  [ "$#" -ge 7 ] && [[ $7 =~ ^[0-9]+$ ]] || return 1
  case $1 in Z|X|x) return 0 ;; esac
  (( $7 & 0x00200000 )) && return 0
  return 1
}
token_pids () {
  local f p envs self=0 unreadable=''
  for f in "$PROC"/[0-9]*/environ; do
    [ -e "$f" ] || [ -e "${f%/environ}" ] || continue
    p=${f#"$PROC"/}; p=${p%/environ}
    [[ $p =~ ^[0-9]+$ ]] || { echo "WHY malformed entry $f"; return 2; }
    if [ "$p" = "$$" ]; then self=1; continue; fi
    if ! envs=$(read_environ "$p" 2>/dev/null); then
      [ -e "$PROC/$p" ] || continue
      cannot_carry "$p" || unreadable="$unreadable $p"
      continue
    fi
    grep -qxF "$CONTAIN_VAR=$CONTAIN_TOKEN" <<< "$envs" && echo "$p"
  done
  [ -z "$unreadable" ] || { echo "WHY environ unreadable for live pid(s)$unreadable"; return 2; }
  [ $self -eq 1 ] || { echo "WHY enumeration of $PROC did not include this shell ($$)"; return 2; }
  return 0
}
token_signal () {         # $1 TERM|KILL, $2 the pids of a validated enumeration; each re-verified just before its own signal
  local p envs
  for p in $2; do
    envs=$(read_environ "$p" 2>/dev/null) && grep -qxF "$CONTAIN_VAR=$CONTAIN_TOKEN" <<< "$envs" && kill -"$1" "$p" 2>/dev/null
  done
}
# 0 only after a validated enumeration finds no token carrier (then the token is retired, so a later drain is a no-op);
# 1 if a carrier survives TERM + KILL or the enumeration never validates (nothing unverified is signalled).
token_sweep () {
  [ -n "$CONTAIN_TOKEN" ] || return 0
  local t phase out pids rc bound last=''
  for phase in TERM KILL; do
    t=0; [ $phase = TERM ] && bound=$DRAIN_TERM_S || bound=$DRAIN_KILL_S
    while :; do
      out=$(token_pids); rc=$?
      pids=$(grep -v '^WHY ' <<< "$out")
      if [ $rc -ne 0 ]; then
        last="enumeration UNKNOWN ($(sed -n 's/^WHY //p' <<< "$out"))"
        [ $t -eq 0 ] && say "STOP: token sweep: $last; nothing signalled, retrying"
      elif [ -z "$pids" ]; then
        say "STOP: token sweep: validated enumeration, no process carries this arm's token"
        CONTAIN_TOKEN=''; return 0
      else
        last="$(echo $pids) still carry this arm's token"
        [ $t -eq 0 ] && say "STOP: token sweep: $(echo $pids | wc -w) token-carrying process(es) outside the group census; $phase"
        token_signal "$phase" "$pids"
      fi
      [ $t -lt "$bound" ] || break
      sleep 1; t=$((t + 1))
    done
  done
  say "STOP: token sweep FAILED: not proven clean after TERM ${DRAIN_TERM_S}s + KILL ${DRAIN_KILL_S}s: $last"
  return 1
}
eval "locklib_drain_child () $(declare -f drain_child | tail -n +2)"
drain_child () { locklib_drain_child || return 1; token_sweep; }
PRED=none
wait_predecessor () { say "$RUN: no predecessor lane; waiting for the RELEASE token"; }

verify_tree () {
  [ -d "$R/.git" ] || die "tree $R missing"
  [ "$(git -C "$R" rev-parse HEAD)" = "$PIN_FULL" ] || die "tree $R is $(git -C "$R" rev-parse HEAD), not $PIN_FULL"
  git -C "$R" diff --quiet -- server fly.toml "$SRC_EXCLUDE" || die "dirty tracked source in $R"
  git -C "$R" diff --cached --quiet -- server fly.toml "$SRC_EXCLUDE" || die "staged source in $R"
  local u; u=$(git -C "$R" ls-files --others --exclude-standard -- server) || die "cannot inspect untracked source"
  [ -z "$u" ] || die "untracked server source in $R"
  ( cd "$R" && sha256sum --quiet -c <<< "$TREE_NATIVE" ) >/dev/null 2>&1 || die "native extension drift in $R"
}
model_stamp () { stat -c '%d:%i:%s:%y:%z' "$1"; }
pin_models () {
  [ -f "$PVCKPT" ] && [ ! -L "$PVCKPT" ] || die "package $PVCKPT missing or symlinked"
  [ -f "$BELIEFCKPT" ] && [ ! -L "$BELIEFCKPT" ] || die "belief package $BELIEFCKPT missing or symlinked"
  PV_STAMP=$(model_stamp "$PVCKPT"); BELIEF_STAMP=$(model_stamp "$BELIEFCKPT")
  [ "$(sha256sum "$PVCKPT" | cut -d" " -f1)" = "$PVSHA" ] || die "package sha256 mismatch"
  [ "$(sha256sum "$BELIEFCKPT" | cut -d" " -f1)" = "$BELIEFSHA" ] || die "belief package sha256 mismatch"
}
verify_models () {
  [ ! -L "$PVCKPT" ] && [ "$(model_stamp "$PVCKPT")" = "$PV_STAMP" ] || die "package identity changed since pinning"
  [ ! -L "$BELIEFCKPT" ] && [ "$(model_stamp "$BELIEFCKPT")" = "$BELIEF_STAMP" ] || die "belief package identity changed since pinning"
}

all_shards_done () {
  local i n dir
  for ((i=0; i<WORKERS; i++)); do
    dir="$OUT/shard-$(printf '%03d' "$i")"
    n=$((PAIRS / WORKERS))
    [ "$i" -lt "$((PAIRS % WORKERS))" ] && n=$((n + 1))
    [ -s "$dir/health.json" ] || return 1
    [ -f "$dir/DONE" ] && [ "$(cat "$dir/DONE" 2>/dev/null)" = "$n complete pairs" ] || return 1
  done
  return 0
}

verify_runner () {
  [ -d "$LANE_DIR" ] && [ ! -L "$LANE_DIR" ] || die "$LANE_DIR missing or symlinked"
  [ -f "$RUNNER" ] && [ ! -L "$RUNNER" ] || die "runner $RUNNER missing or symlinked"
  [ "$(sha256sum "$RUNNER" | cut -d" " -f1)" = "$RUNNER_SHA" ] || die "runner sha256 is not $RUNNER_SHA"
}
no_prior_output () {
  local f
  for f in "$OUT" "$LANE_DIR/CLAIM" "$LANE_DIR/worker.log"; do
    [ ! -e "$f" ] && [ ! -L "$f" ] || die "$f exists: a previous attempt ran; one shot, no retry"
  done
}
host_state () {
  echo "host lock $([ -e $HOSTLOCK ] && echo "held by '$(head -1 $HOSTLOCK/owner 2>/dev/null)'" || echo absent); screen lock $([ -e $LEGACY_SCREEN_LOCK ] && echo PRESENT || echo absent); MemAvailable $(awk '/MemAvailable/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo); load $(cut -d' ' -f1-3 /proc/loadavg)"
}

# --- arming-time checks (also the whole DRYRUN) ---------------------------------------------------
verify_tree
pin_models
verify_runner
hold_release_guard 0
if [ "$DRY" = "1" ]; then
  no_prior_output
  [ ! -e "$S" ] && [ ! -e "$RESERVATION" ] || echo "DRYRUN note: status/reservation already exist (a previous arm)"
  t0=$(date +%s.%N)
  out=$(cd "$LANE_DIR" && nice -n 19 "$PY" -B "$RUNNER" --dry 2>&1); rc=$?
  t1=$(date +%s.%N)
  echo "$out" | tail -3
  [ $rc -eq 0 ] || { echo "DRYRUN FAILED: runner --dry rc=$rc"; exit 4; }
  "$PY" -B -c "
import json, sys
d = json.loads(sys.argv[1].strip().splitlines()[-1])
assert d['dry'] == 'S52DEV DRY OK', d
assert d['control'] == '$CONTROL_EXPECT', d['control']
assert d['candidate'] == '$CAND_EXPECT', d['candidate']
assert not d['output_exists'] and not d['claim_exists'], d
print('DRYRUN ok: both arms built from the pinned source on the guarded host; control', d['control'][-20:], 'candidate', d['candidate'][-20:],
      '; construct', d['construct_seconds'], 's; peak RSS', round(d['ru_maxrss_kib'] / 1048576, 2), 'GiB')
" "$out" || { echo "DRYRUN FAILED: identities differ from the expected names"; exit 4; }
  no_prior_output
  [ ! -e "$LANE_DIR/__pycache__" ] || echo "DRYRUN note: $LANE_DIR/__pycache__ exists"
  echo "DRYRUN ok: launcher sha256 $SELF_SHA; runner $RUNNER sha256 $RUNNER_SHA; tree $PIN_FULL (natives pinned); packages pinned; wall $(awk -v a=$t0 -v b=$t1 'BEGIN{printf "%.1f", b-a}') s"
  echo "DRYRUN ok: $(host_state)"
  echo "DRYRUN ok: RELEASE $([ -e "$RELEASE" ] && echo present || echo absent); HOLD $(for h in $HOLDS; do [ -e "$h" ] && echo present && break; done | head -1); status $([ -e "$S" ] && echo exists || echo absent); reservation $([ -e "$RESERVATION" ] && echo exists || echo absent); no lane state created"
  exit 0
fi

# --- ARMED: one lane process; status (append), reservation exclusive or re-verified ----
PSOUT=$(ps -eo pid=,ppid=,args=) && [ -n "$PSOUT" ] && awk -v me=$$ '$1==me {f=1} END {exit !f}' <<< "$PSOUT" \
  || die "cannot take a validated process census for the single-lane check"
others=$(awk -v me=$$ -v self="$SELF" '$1!=me && $2!=me && $3=="bash" && $4==self && $5=="--arm" && NF==5 {print $1}' <<< "$PSOUT" | tr "\n" " ")
[ -z "$others" ] || die "another $RUN lane is alive (pid $others)"
[ ! -L "$S" ] || die "status $S is a symlink"
STATUS_OWNED=1
no_prior_output
mkdir -p /root/claude_reservations && [ -d /root/claude_reservations ] && [ ! -L /root/claude_reservations ] || die "cannot create /root/claude_reservations"
if [ -e "$RESERVATION" ] || [ -L "$RESERVATION" ]; then
  "$PY" -B -c "
import json; r = json.load(open('$RESERVATION'))
assert r['lane'] == '$RUN' and r['launcher_sha256'] == '$SELF_SHA' and r['seeds'] == [$SEED0] and r['count'] == $PAIRS, r" \
    || die "existing reservation $RESERVATION is not this launcher's"
  say "$RUN re-arm: reservation $RESERVATION re-verified (no prior output, CLAIM or worker log)"
else
  "$PY" -B -c "
import json, datetime
json.dump({'schema':'claude-reservation-v1','lane':'$RUN','seeds':[$SEED0],'count':$PAIRS,'launcher':'$SELF','launcher_sha256':'$SELF_SHA',
 'runner':'$RUNNER','runner_sha256':'$RUNNER_SHA','tree':'$R','tree_head':'$PIN_FULL',
 'pairing':'S52 DEV: 624 seat-mirrored fixed-banker pairs, ranks 2 through A cycled by cluster, banker=seed%4, seeds [$SEED0, $((SEED0 + PAIRS))); candidate $CAND_EXPECT vs control $CONTROL_EXPECT',
 'status':'$S','output_root':'$OUT','terminal_line':'=== $RUN DONE ===',
 'created_at':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
 open('$RESERVATION','x'), indent=1, sort_keys=True)" || die "could not exclusively write the reservation record $RESERVATION"
  say "$RUN reservation record $RESERVATION sha256 $(sha256sum $RESERVATION | cut -d' ' -f1)"
fi
say "armed: $RUN launcher sha256 $SELF_SHA; runner sha256 $RUNNER_SHA; tree ${PIN_FULL:0:8}; seeds [$SEED0, $((SEED0 + PAIRS))) x 624 pairs; waits for the RELEASE, then the shared host lock (no predecessor is stopped or resumed by this launcher); $(host_state)"

post_release_checks () {
  verify_tree; verify_models; verify_runner; no_prior_output
  say "$RUN: RELEASE verified (launcher sha256 $SELF_SHA); waiting for the shared host lock"
}
dispatch_checks () {
  verify_tree; verify_models; verify_runner; no_prior_output
  [ $(( SECONDS - ARM_START )) -lt "$WAIT_CEILING" ] || die "wait ceiling ${WAIT_CEILING}s reached before dispatch; nothing started"
}
announce_start () {
  say "start pid $$ (RELEASE verified; holding $HOSTLOCK; $(host_state))"
  cd "$LANE_DIR" || die "cannot cd to $LANE_DIR"
  FIRST_DISPATCH_DONE=1
}
finish () {
  local ok=0
  if [ "$1" -eq 0 ] && grep -qF '"terminal": "DEV DONE"' "$CHILD_LOG" 2>/dev/null \
     && [ "$(cat "$OUT/DONE" 2>/dev/null)" = "$PAIRS complete pairs in $WORKERS shards" ] && all_shards_done; then ok=1; fi
  say "rc=$1 $RUN: parent DONE $([ -e "$OUT/DONE" ] && echo present || echo absent); 14 shard seals $([ "$ok" -eq 1 ] && echo complete || echo incomplete)"
  if [ $ok -eq 1 ]; then say "=== $RUN DONE ==="; return 0; fi
  say "=== $RUN FAILED rc=$1 (DEV terminal or complete shard seals absent; output, CLAIM and logs preserved; one shot, no retry) ==="
  [ "$1" -ne 0 ] && return "$1"
  return 5                # child rc 0 without the success witness
}
supervise "$PY" -B "$RUNNER"

