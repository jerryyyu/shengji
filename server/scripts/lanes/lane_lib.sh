# shellcheck shell=bash
# lane_lib.sh: the admission, lock, gate and supervision guards every fleet lane builds on.
# Source it from a launcher; it defines functions and variables only and runs nothing.  bash 3.2 compatible.
#
# Calling order (README.md beside this file has the full contract):
#   set the LANE_* configuration, then
#   lane_init                       traps TERM/INT/HUP/EXIT, writes "<P> START"
#   lane_arm                        LANE_ARMED_ID = lane_identity LANE_FILES; lane_admit arming
#   lane_require_registered_seeds   for every producer that deals from a reserved seed block
#   lane_lock_acquire               bounded wait: HOLD pauses, gates and the mkdir lock must both admit
#   lane_admit after-wait           every check again, immediately before the producer
#   lane_supervise CMD...           the producer in its own process group under LANE_MAX_SECONDS
#   lane_done "<summary>"           the DONE terminal, then the lock is released
#   lane_hold_check_before_delete   before any deletion of a verified output
#
# Status lines go to LANE_STATUS as "<LANE_PREFIX> <WORD> <LANE_NAME> <utc> ...".  Each attempt ends in exactly one
# terminal line: DONE (rc 0), PAUSED (HOLD, wall ceiling, disk floor or a signal; resumable) or ABORT (a refusal or a
# producer failure).  The lock is always released after the terminal line is written, never before.
#
# Return codes of the guards: 0 admitted, 3 HOLD, 5 wait ceiling, 6 refusal.

LANE_PREFIX=${LANE_PREFIX:-LANE}
LANE_MSG=""
LANE_LOCKED=0
LANE_GPID=""
LANE_TERMINAL=0

lane_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

lane_sha() {   # sha256 of one file; empty output and rc 1 when it cannot be read
  local s
  [ -f "$1" ] && [ -r "$1" ] || return 1
  if command -v shasum >/dev/null 2>&1; then s=$(shasum -a 256 < "$1") || return 1
  else s=$(sha256sum < "$1") || return 1; fi
  echo "${s%% *}"
}

lane_say() { [ -n "${LANE_STATUS:-}" ] && echo "$LANE_PREFIX $1 ${LANE_NAME:-lane} $(lane_now) $2" >> "$LANE_STATUS"; return 0; }

lane_count_files() {   # DIR PATTERN: regular files under DIR whose name matches PATTERN (find -name); 0 for no DIR
  if [ ! -d "$1" ]; then echo 0; return 0; fi
  find "$1" -type f -name "$2" | wc -l | tr -d ' '
}

# The manifest names every file by basename with its sha256, one per line, in argument order.  Basenames keep the
# identity equal between the staging copy and the host copy; a repeated basename or an unreadable file refuses.
lane_manifest() {
  local f s seen=" " b
  for f in "$@"; do
    b=$(basename "$f")
    case "$seen" in *" $b "*) echo "lane_manifest: basename $b repeated" >&2; return 1;; esac
    seen="$seen$b "
    s=$(lane_sha "$f") || { echo "lane_manifest: cannot read $f" >&2; return 1; }
    echo "$s  $b"
  done
}

lane_identity() {   # FILES...: sha256 of the manifest of their sha256s
  local m
  [ "$#" -gt 0 ] || { echo "lane_identity: no files" >&2; return 1; }
  m=$(lane_manifest "$@") || return 1
  if command -v shasum >/dev/null 2>&1; then m=$(echo "$m" | shasum -a 256); else m=$(echo "$m" | sha256sum); fi
  echo "${m%% *}"
}

lane_hold_present() {   # sets LANE_MSG to the first HOLD found among LANE_HOLDS (space separated)
  local h
  for h in ${LANE_HOLDS:-}; do
    if [ -e "$h" ] || [ -L "$h" ]; then LANE_MSG="HOLD present ($h)"; return 0; fi
  done
  return 1
}

lane_check_pins() {   # LANE_PINS lines "<sha256>  <path>"; then the optional LANE_PIN_HOOK function
  local line want path got out
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    want=${line%%  *}; path=${line#*  }
    got=$(lane_sha "$path") || { LANE_MSG="pin $path unreadable"; return 1; }
    [ "$got" = "$want" ] || { LANE_MSG="pin $path is $got, not $want"; return 1; }
  done <<EOF
${LANE_PINS:-}
EOF
  if [ -n "${LANE_PIN_HOOK:-}" ]; then
    out=$("$LANE_PIN_HOOK" 2>&1) || { LANE_MSG="pin hook $LANE_PIN_HOOK: $out"; return 1; }
  fi
  return 0
}

# hostname, no HOLD, the launcher identity unchanged since arming, RELEASE a regular file whose first field is that
# identity, every pin.  $1 names the moment for the status line.  rc 0 / 3 HOLD / 6 refusal; LANE_MSG says why.
lane_admit() {
  local moment=${1:-admit} id tok
  if [ -z "${LANE_HOSTNAME:-}" ] || [ "$(hostname)" != "$LANE_HOSTNAME" ]; then
    LANE_MSG="$moment: hostname $(hostname) is not '${LANE_HOSTNAME:-}'"; return 6
  fi
  if lane_hold_present; then LANE_MSG="$moment: $LANE_MSG"; return 3; fi
  id=$(lane_identity ${LANE_FILES+"${LANE_FILES[@]}"} 2>&1) || { LANE_MSG="$moment: identity: $id"; return 6; }
  if [ -n "${LANE_ARMED_ID:-}" ] && [ "$id" != "$LANE_ARMED_ID" ]; then
    LANE_MSG="$moment: launcher identity changed since arming: $id != $LANE_ARMED_ID"; return 6
  fi
  if [ -z "${LANE_RELEASE:-}" ] || [ ! -f "$LANE_RELEASE" ] || [ -L "$LANE_RELEASE" ]; then
    LANE_MSG="$moment: RELEASE ${LANE_RELEASE:-<unset>} missing or not a regular file"; return 6
  fi
  tok=$(head -1 "$LANE_RELEASE" | awk '{print $1}')
  [ "$tok" = "$id" ] || { LANE_MSG="$moment: RELEASE token '$tok' is not the launcher identity $id"; return 6; }
  lane_check_pins || { LANE_MSG="$moment: $LANE_MSG"; return 6; }
  LANE_MSG="$moment: ok identity=$id"
  return 0
}

lane_arm() {   # computes LANE_ARMED_ID (unless inherited from a parent) and admits; rc as lane_admit
  local id
  if [ -z "${LANE_ARMED_ID:-}" ]; then
    id=$(lane_identity ${LANE_FILES+"${LANE_FILES[@]}"} 2>&1) || { LANE_MSG="arming: identity: $id"; return 6; }
    LANE_ARMED_ID=$id
  fi
  export LANE_ARMED_ID
  lane_admit arming
}

lane_terminal_ok() {   # LINE: does it end a predecessor (or released duel) run, successfully or not
  echo "$1" | grep -qE "${LANE_TERMINAL_RE:-(^| )(DONE|FAILED|ABORT|REFUSING:?)( |$)}"
}

# Gates.  rc 0 admitted, 1 wait, 2 a predecessor ended without success.  LANE_MSG says why.
#   LANE_GATES       lines "<status file> <ERE>": the file's last non-empty line must match ERE (anchor it: a bare
#                    word also matches an ABORT line that quotes it).  A last line matching LANE_GATE_FAIL_RE stops.
#   LANE_GATE_PROCEED  an operator file that opens the LANE_GATES predecessors (never the yield check).
#   LANE_YIELD_DIR + LANE_YIELD_GLOB (a find -name pattern): any <x>.RELEASE there other than LANE_RELEASE whose
#                    <x>.status last line is not terminal (lane_terminal_ok) is a released run that goes first.
lane_gate() {
  local line file re last r st
  if [ -z "${LANE_GATE_PROCEED:-}" ] || [ ! -f "$LANE_GATE_PROCEED" ]; then
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      file=${line%% *}; re=${line#* }
      last=$(grep -v '^[[:space:]]*$' "$file" 2>/dev/null | tail -1)
      if echo "$last" | grep -qE "$re"; then continue; fi
      if [ -n "$last" ] && echo "$last" | grep -qE "${LANE_GATE_FAIL_RE:-(^| )(ABORT|REFUSING:?|FAILED)( |$)}"; then
        LANE_MSG="predecessor $file ended without success: $(echo "$last" | cut -c1-120)"; return 2
      fi
      LANE_MSG="waiting for $file to match '$re' (last: '$(echo "$last" | cut -c1-90)')"; return 1
    done <<EOF
${LANE_GATES:-}
EOF
  fi
  if [ -n "${LANE_YIELD_DIR:-}" ] && [ -d "$LANE_YIELD_DIR" ]; then
    while IFS= read -r r; do
      [ -n "$r" ] || continue
      [ "$r" = "${LANE_RELEASE:-}" ] && continue
      st=${r%.RELEASE}.status
      lane_terminal_ok "$(grep -v '^[[:space:]]*$' "$st" 2>/dev/null | tail -1)" && continue
      LANE_MSG="yielding to released run $(basename "$r") (its status is not terminal)"; return 1
    done <<EOF
$(find "$LANE_YIELD_DIR" -maxdepth 1 -type f -name "${LANE_YIELD_GLOB:-*.RELEASE}" 2>/dev/null | LC_ALL=C sort)
EOF
  fi
  LANE_MSG="gates open"
  return 0
}

lane_owner_pid() { head -1 "$LANE_LOCK/owner" 2>/dev/null | awk '{print $1}'; }

lane_lock_release() {   # removes the lock only when its owner line names this shell
  [ "$LANE_LOCKED" = 1 ] || return 0
  if [ "$(lane_owner_pid)" = "$$" ]; then
    rm -f "$LANE_LOCK/owner"
    if rmdir "$LANE_LOCK" 2>/dev/null; then lane_say UNLOCKED "$LANE_LOCK"
    else lane_say WARNING "could not remove $LANE_LOCK"; fi
  else
    lane_say WARNING "lock $LANE_LOCK owner is '$(lane_owner_pid)', not $$; left alone"
  fi
  LANE_LOCKED=0
}

lane_nap() { sleep "$1" & wait $!; }   # a trapped signal ends the wait at once

# Bounded admission wait.  Each poll: HOLD -> rc 3; LANE_WAIT_CEILING seconds passed -> rc 5; a failed predecessor ->
# rc 6; gates closed -> wait; mkdir LANE_LOCK (with LANE_USE_LOCK != 0) -> owner line "<pid> <lane> <utc>", gates
# re-checked with the lock held (closed -> give it back and wait).  rc 0 when admitted (and the lock is ours).
lane_lock_acquire() {
  local t0 last="" g
  t0=$(date +%s)
  while :; do
    if lane_hold_present; then LANE_MSG="while waiting: $LANE_MSG"; return 3; fi
    if [ $(( $(date +%s) - t0 )) -ge "${LANE_WAIT_CEILING:-3600}" ]; then
      LANE_MSG="admission wait ceiling ${LANE_WAIT_CEILING:-3600}s reached (${last:-no wait reason})"; return 5
    fi
    lane_gate; g=$?
    if [ "$g" = 2 ]; then return 6; fi
    if [ "$g" = 0 ] && [ "${LANE_USE_LOCK:-1}" != 0 ]; then
      if mkdir "$LANE_LOCK" 2>/dev/null; then
        LANE_LOCKED=1
        echo "$$ ${LANE_NAME:-lane} $(lane_now)" > "$LANE_LOCK/owner"
        lane_gate; g=$?
        if [ "$g" = 0 ]; then lane_say LOCKED "$LANE_LOCK after $(( $(date +%s) - t0 ))s"; return 0; fi
        lane_lock_release
        if [ "$g" = 2 ]; then return 6; fi
      else
        LANE_MSG="host lock $LANE_LOCK held by: $(cat "$LANE_LOCK/owner" 2>/dev/null)"
      fi
    elif [ "$g" = 0 ]; then
      return 0
    fi
    [ "$LANE_MSG" = "$last" ] || { lane_say WAIT "$LANE_MSG"; last=$LANE_MSG; }
    lane_nap "${LANE_POLL:-30}"
  done
}

lane_group_alive() { [ -n "$LANE_GPID" ] && pgrep -g "$LANE_GPID" >/dev/null 2>&1; }

lane_stop_group() {   # TERM the owned group, KILL after LANE_STOP_GRACE s; returns when no member is left
  local i=0
  [ -n "$LANE_GPID" ] || return 0
  kill -TERM -- "-$LANE_GPID" 2>/dev/null
  while lane_group_alive && [ "$i" -lt "${LANE_STOP_GRACE:-90}" ]; do sleep 1; i=$((i+1)); done
  if lane_group_alive; then
    kill -KILL -- "-$LANE_GPID" 2>/dev/null
    while lane_group_alive; do sleep 1; done
  fi
  wait "$LANE_GPID" 2>/dev/null
  return 0
}

lane_terminal() { lane_say "$1" "$2"; LANE_TERMINAL=1; lane_lock_release; }
lane_done() { lane_terminal DONE "${1:-} rc=0"; }
lane_abort() { lane_terminal ABORT "rc=$1 reason=$2"; exit "$1"; }
lane_pause() { lane_terminal PAUSED "reason=$1"; exit 1; }

lane_on_signal() {
  trap '' TERM INT HUP
  lane_stop_group
  lane_pause "signal $1${LANE_PAUSE_NOTE:+; $LANE_PAUSE_NOTE}"
}
lane_on_exit() {
  lane_group_alive && lane_stop_group
  [ "$LANE_TERMINAL" = 1 ] || lane_say ABORT "rc=99 reason=unexpected exit"
  lane_lock_release
}

lane_init() {   # traps and the START line; call once, before any wait
  trap 'lane_on_signal TERM' TERM
  trap 'lane_on_signal INT' INT
  trap 'lane_on_signal HUP' HUP
  trap lane_on_exit EXIT
  lane_say START "pid=$$ host=$(hostname) ${1:-}"
}

lane_free_gib() { df -k "$1" | awk 'NR==2{printf "%d", $4/1048576}'; }

# Runs CMD... as its own process group (setsid through LANE_PY) and watches it.  HOLD, LANE_MAX_SECONDS or the disk
# floor (LANE_DISK_DIR below LANE_MIN_FREE_GIB) stop the group and write PAUSED (exit 1); a signal does the same through
# lane_on_signal.  Otherwise returns the producer's rc, and the caller verifies its output and calls lane_done/abort.
lane_supervise() {
  local t0 why="" rc
  [ "$#" -gt 0 ] || lane_abort 2 "lane_supervise: no command"
  "${LANE_PY:-python3}" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" \
    >> "${LANE_LOG:-/dev/null}" 2>&1 < /dev/null &
  LANE_GPID=$!
  t0=$(date +%s)
  lane_say PRODUCER "pgid=$LANE_GPID ceiling=${LANE_MAX_SECONDS:-86400}s"
  while kill -0 "$LANE_GPID" 2>/dev/null; do
    if lane_hold_present; then why=$LANE_MSG
    elif [ $(( $(date +%s) - t0 )) -ge "${LANE_MAX_SECONDS:-86400}" ]; then why="timeout: wall ceiling ${LANE_MAX_SECONDS:-86400}s reached"
    elif [ -n "${LANE_DISK_DIR:-}" ] && [ "$(lane_free_gib "$LANE_DISK_DIR")" -lt "${LANE_MIN_FREE_GIB:-0}" ]; then
      why="disk free below ${LANE_MIN_FREE_GIB} GiB"
    fi
    if [ -n "$why" ]; then lane_stop_group; lane_pause "$why${LANE_PAUSE_NOTE:+; $LANE_PAUSE_NOTE}"; fi
    lane_nap "${LANE_MON_POLL:-10}"
  done
  wait "$LANE_GPID" 2>/dev/null; rc=$?
  lane_group_alive && lane_stop_group
  LANE_GPID=""
  return "$rc"
}

# Before deleting PATH: rc 3 and a DELETE_HELD line when any HOLD is present (the path is kept), else rc 0.
lane_hold_check_before_delete() {
  if lane_hold_present; then lane_say DELETE_HELD "$LANE_MSG; kept ${1:-}"; return 3; fi
  return 0
}

# SEED0 CLUSTERS: rc 0 only when the block [SEED0, SEED0+CLUSTERS) lies inside exactly one registered window of the
# seed registry committed in LANE_SEED_TREE (a checkout whose HEAD is an ancestor of LANE_SEED_MAIN_REF, default
# origin/main, with the registry files tracked and unmodified), as reported by its own scripts/seed_windows.py.
# `check --purpose other` exits 0 for a disjoint block, 1 for any overlap and 2 on a registry error; for rc 1 the block
# counts as registered only when the one overlapping window shares all CLUSTERS seeds.  LANE_SEED_PURPOSE, when set,
# must be that window's purpose.  LANE_MSG names the window or the refusal.
lane_require_registered_seeds() {
  local s0=$1 n=$2 tree=${LANE_SEED_TREE:-} ref=${LANE_SEED_MAIN_REF:-origin/main} out rc hi k=0 nlines=0 hit=""
  local re_head re_line line
  case "$s0$n" in *[!0-9]*|'') LANE_MSG="seeds: '$s0' '$n' are not non-negative integers"; return 6;; esac
  [ "$n" -ge 1 ] || { LANE_MSG="seeds: clusters must be >= 1"; return 6; }
  [ -n "$tree" ] && [ -f "$tree/server/scripts/seed_windows.py" ] || { LANE_MSG="seeds: LANE_SEED_TREE '$tree' has no server/scripts/seed_windows.py"; return 6; }
  git -C "$tree" ls-files --error-unmatch server/runs/seed_windows.json >/dev/null 2>&1 \
    || { LANE_MSG="seeds: server/runs/seed_windows.json is not tracked in $tree"; return 6; }
  out=$(git -C "$tree" status --porcelain --untracked-files=all -- server/runs/seed_windows.json \
        server/runs/seed_windows.d server/scripts/seed_windows.py server/shengji/seeds.py 2>&1)
  [ -z "$out" ] || { LANE_MSG="seeds: the registry in $tree differs from its HEAD: $(echo "$out" | head -3 | tr '\n' ' ')"; return 6; }
  git -C "$tree" merge-base --is-ancestor HEAD "$ref" 2>/dev/null \
    || { LANE_MSG="seeds: $tree HEAD is not on $ref"; return 6; }
  out=$(cd "$tree/server" && env -u SHENGJI_SEED_WINDOWS "${LANE_PY:-python3}" -P -B scripts/seed_windows.py \
        --registry runs/seed_windows.json check "$s0" "$n" --purpose other 2>&1); rc=$?
  hi=$((s0 + n))
  [ "$rc" = 0 ] && { LANE_MSG="seeds: [$s0, $hi) is in no registered window"; return 6; }
  [ "$rc" = 1 ] || { LANE_MSG="seeds: seed_windows.py check rc=$rc: $(echo "$out" | tail -1)"; return 6; }
  re_head='^\[([0-9]+), ([0-9]+)\) overlaps ([0-9]+) registered window\(s\):$'
  re_line='^  (.+) \(([a-z]+), seed0 ([0-9]+), ([0-9]+) clusters, span \[([0-9]+), ([0-9]+)\)\) shares ([0-9]+) deal seed\(s\) \[([0-9]+), ([0-9]+)\)$'
  while IFS= read -r line; do
    if [[ $line =~ $re_head ]]; then
      [ "${BASH_REMATCH[1]}" = "$s0" ] && [ "${BASH_REMATCH[2]}" = "$hi" ] || { LANE_MSG="seeds: check reported span [${BASH_REMATCH[1]}, ${BASH_REMATCH[2]})"; return 6; }
      k=${BASH_REMATCH[3]}
    elif [[ $line =~ $re_line ]]; then
      nlines=$((nlines + 1))
      if [ "${BASH_REMATCH[7]}" = "$n" ] && [ "${BASH_REMATCH[8]}" = "$s0" ] && [ "${BASH_REMATCH[9]}" = "$hi" ]; then
        hit="${BASH_REMATCH[1]} ${BASH_REMATCH[2]} [${BASH_REMATCH[5]}, ${BASH_REMATCH[6]})"
        if [ -n "${LANE_SEED_PURPOSE:-}" ] && [ "${BASH_REMATCH[2]}" != "$LANE_SEED_PURPOSE" ]; then
          LANE_MSG="seeds: [$s0, $hi) lies in ${BASH_REMATCH[1]}, a ${BASH_REMATCH[2]} window, not $LANE_SEED_PURPOSE"; return 6
        fi
      fi
    fi
  done <<EOF
$out
EOF
  [ "$k" -ge 1 ] && [ "$nlines" = "$k" ] || { LANE_MSG="seeds: unparsed check output (header $k, lines $nlines)"; return 6; }
  [ "$k" = 1 ] || { LANE_MSG="seeds: [$s0, $hi) overlaps $k registered windows; a reserved block lies in exactly one"; return 6; }
  [ -n "$hit" ] || { LANE_MSG="seeds: [$s0, $hi) is only partly inside a registered window"; return 6; }
  LANE_MSG="seeds: [$s0, $hi) reserved by $hit"
  return 0
}
