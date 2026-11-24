#!/usr/bin/env bash
# lane-lib: required
# Mini dispatch samples the live queue. Ultra owns the host lock until terminal status.
set -u
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

MINI_HOST=Jerrys-Mac-mini.local
ULTRA_HOST=Jerrys-Mac-Studio.local
ULTRA_HOME=/Users/jeryyu
QUEUE_TOOLS=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools
LANE_NAME=codex-sz2r-v1
FLEET=$ULTRA_HOME/fleet
LANE=$FLEET/$LANE_NAME
WORK=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 6
SCRIPT=$WORK/sz2r_fleet.sh

refuse() { printf 'REFUSING: %s\n' "$*" >&2; exit 6; }
valid_sha() { [[ $1 =~ ^[0-9a-f]{64}$ ]]; }
queue_line() { printf '%s released screen %s\n' "$LANE_NAME" "$1"; }

# A stable registry name can span releases with different search implementations.
check_comparator() {
  /opt/homebrew/bin/flyctl machine list -a shengji --json | /usr/bin/python3 -IB -c '
import hashlib, json, sys
machines = json.load(sys.stdin)
if len(machines) != 1 or machines[0]["state"] != "started":
    sys.exit("expected the served Shengji machine")
machine = machines[0]
if machine["image_ref"]["digest"] != "sha256:2c46ee82a86e4132bcb5c73c21215c04ce2ae709d6a88580488e91bacf9f512b":
    sys.exit("served image changed; verify its search source before dispatch")
env = machine["config"]["env"]
words = {k: v for k, v in env.items() if k.startswith(("SHENGJI_PV", "SHENGJI_CWV", "SHENGJI_BOT", "SHENGJI_FAST"))}
raw = json.dumps(words, sort_keys=True, separators=(",", ":")).encode()
if hashlib.sha256(raw).hexdigest() != "87349b34cd4443064b758ef15b7f912c353582206ae365ef0d630670256618b8":
    sys.exit("served gameplay settings differ from the screen comparator")
'
}

if [ "${1:-}" = comparator ]; then
  [ "$#" = 1 ] && [ "$(hostname)" = "$MINI_HOST" ] || exit 6
  check_comparator
  exit $?
fi

if [ "${1:-}" = dispatch ]; then
  [ "$#" = 2 ] && valid_sha "$2" || refuse "dispatch needs the reviewed launcher identity"
  [ "$(hostname)" = "$MINI_HOST" ] || refuse "dispatch runs on the Mini"
  identity=$2
  remote="env -i HOME=$ULTRA_HOME PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash $LANE/sz2r_fleet.sh"
  local_sha=$(shasum -a 256 < "$SCRIPT") || refuse "cannot read Mini dispatcher"
  remote_sha=$(ssh -o BatchMode=yes ultra "shasum -a 256 < $LANE/sz2r_fleet.sh") || refuse "cannot read Ultra dispatcher"
  [ "$local_sha" = "$remote_sha" ] || refuse "Mini and Ultra dispatchers differ"
  [ "$(ssh -o BatchMode=yes ultra "$remote identity")" = "$identity" ] || refuse "staged Ultra identity differs"
  check_comparator || refuse "live comparator changed"
  [ -s "$QUEUE_TOOLS/fleet_queue.json" ] || refuse "canonical fleet queue is absent"
  env -u FLEET_QUEUE -u HOSTS_JSON /usr/bin/python3 -IB - "$QUEUE_TOOLS" "$LANE_NAME" "$identity" "$LANE/sz2r_fleet.sh" <<'PY' || refuse "Ultra queue does not release this identity"
import importlib.util
from pathlib import Path
import sys

tools, lane, identity, launcher = sys.argv[1:]
spec = importlib.util.spec_from_file_location("fleet_queue", Path(tools) / "fleet_queue.py")
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)
entry = queue.next_lane(queue.load()["hosts"].get(queue.host_name("ultra"), []))
if (not entry or entry["id"] != lane or entry["state"] != "released" or entry["kind"] != "screen"
        or entry["sha"] != identity or entry.get("blocked_on") or entry.get("filler")
        or entry.get("launcher") not in (None, "", launcher)):
    sys.exit("the next Ultra entry is not the released screen at the exact launcher SHA")
PY
  # Pass the Mini sample to the detached launcher as one argument.
  queue_line "$identity" | ssh -o BatchMode=yes ultra "
    IFS= read -r sample || exit 6
    test -f $LANE/launcher.RELEASE && test ! -e $FLEET/.claude-host.lock || exit 6
    nohup /usr/bin/python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \
      $remote run $identity \"\$sample\" >>$LANE/dispatch.log 2>&1 </dev/null &"
  exit $?
fi

LIB=$WORK/lane_lib.sh
[ -f "$LIB" ] && [ ! -L "$LIB" ] || refuse "the staged lane library is absent"
unset LANE_GATES LANE_GATE_PROCEED LANE_YIELD_DIR LANE_YIELD_GLOB LANE_GATE_FAIL_RE
unset LANE_HOUSEKEEPING_RE LANE_TERMINAL_RE LANE_PINS LANE_PIN_HOOK LANE_ARMED_ID
. "$WORK/lane_lib.sh"

LANE_FILES=("$SCRIPT" "$LIB" "$WORK/recipe.json" "$WORK/sz2r_capacity.json"
  "$WORK/sz2r_dispatch.py" "$WORK/sz2r_sequence.py" "$WORK/sz2r_run.py" "$WORK/sz2r_handoff.py"
  "$WORK/sz2r_read_once.py" "$WORK/sz2r_stage1.py" "$WORK/sz2r_producer.py" "$WORK/sz2r_recipe.py"
  "$WORK/sz2r_checkpoint_exposure.json" "$WORK/sz2r_preflight_exposure.json")
for path in "${LANE_FILES[@]}"; do
  [ -f "$path" ] && [ ! -L "$path" ] || refuse "missing or nonregular packet input $path"
done

if [ "${1:-}" = identity ]; then
  [ "$#" = 1 ] || exit 2
  lane_identity "${LANE_FILES[@]}"
  exit $?
fi

[ "$WORK" = "$LANE" ] && [ "$(hostname)" = "$ULTRA_HOST" ] || refuse "expected staged reservation $LANE on $ULTRA_HOST"
LANE_PREFIX=LANE
LANE_PY=$ULTRA_HOME/Projects/shengji/server/.venv/bin/python
LANE_HOSTNAME=$ULTRA_HOST
LANE_RELEASE=$LANE/launcher.RELEASE
LANE_STATUS=$LANE/launcher.status
LANE_LOG=$LANE/supervisor.log
LANE_HOLDS="$LANE/launcher.HOLD $LANE/HOLD $LANE/READOUT.HOLD"
LANE_LOCK=$FLEET/.claude-host.lock
LANE_USE_LOCK=1
LANE_WAIT_CEILING=1
LANE_POLL=1
LANE_MON_POLL=5
LANE_STOP_GRACE=90
LANE_MAX_SECONDS=14400
LANE_PAUSE_NOTE="SZ2-R pilot, timing and screen"
LANE_DISK_DIR=$FLEET
LANE_MIN_FREE_GIB=50
LANE_SEED_TREE=$ULTRA_HOME/Projects/shengji
LANE_SEED_MAIN_REF=origin/main
LANE_SEED_PURPOSE=screen

require_seeds() {
  lane_require_registered_seeds 2668000000 3920 || return $?
  [ "$LANE_MSG" = "seeds: [2668000000, 2668003920) reserved by sz2-r-screen-2668000000 screen [2668000000, 2668003920)" ] || return 6
  lane_require_registered_seeds 2668003920 26 || return $?
  [ "$LANE_MSG" = "seeds: [2668003920, 2668003946) reserved by sz2-r-preflight-2668003920 screen [2668003920, 2668003946)" ] || return 6
}

legacy_locks_clear() {
  local lock
  for lock in "$ULTRA_HOME/.claude-host.lock" "$ULTRA_HOME/.claude-screen.lock" "$ULTRA_HOME/.claude-datagen.lock"; do
    if [ -e "$lock" ] || [ -L "$lock" ]; then LANE_MSG="legacy host lock present at $lock"; return 5; fi
  done
}

# The locked PID binds the Mini's queue sample to the dispatch that acquired the host.
admission_receipt() {
  printf '{"lane":"%s","state":"released","kind":"screen","sha":"%s","owner":%s}\n' "$LANE_NAME" "$LANE_ARMED_ID" "$1"
}

check_inputs() {
  lane_disk_check && legacy_locks_clear && require_seeds || return $?
  env -i HOME="$ULTRA_HOME" PATH="$PATH" "$LANE_PY" -IB - "$LANE" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from sz2r_recipe import build

if json.loads((root / "recipe.json").read_bytes()) != build():
    sys.exit("staged recipe differs from the live R55/M2 recipe")
PY
}

readmit() {
  local owner=$1 lock_pid lock_lane rest queue_path
  lane_admit "$2" || return $?
  legacy_locks_clear && lane_disk_check && require_seeds || return $?
  [ -d "$LANE_LOCK" ] && [ ! -L "$LANE_LOCK" ] && [ -f "$LANE_LOCK/owner" ] && [ ! -L "$LANE_LOCK/owner" ] &&
    IFS=' ' read -r lock_pid lock_lane rest < "$LANE_LOCK/owner" &&
    [ "$lock_pid" = "$owner" ] && [ "$lock_lane" = "$LANE_NAME" ] && kill -0 "$owner" 2>/dev/null ||
    { LANE_MSG="current dispatch does not own the host lock"; return 6; }
  queue_path=$LANE/queue-admission.$owner.json
  [ -f "$queue_path" ] && [ ! -L "$queue_path" ] &&
    [ "$(cat "$queue_path")" = "$(admission_receipt "$owner")" ] ||
    { LANE_MSG="current dispatch lacks its bound Mini queue admission"; return 6; }
}

guard_or_stop() {
  local code=$1
  case "$code" in
    0) return 0 ;;
    3) lane_pause "$LANE_MSG" ;;
    *) lane_abort "$code" "$LANE_MSG" ;;
  esac
}

case "${1:-}" in
  check)
    [ "$#" = 1 ] || exit 2
    lane_hold_present && refuse "$LANE_MSG"
    check_inputs || refuse "$LANE_MSG inputs did not verify"
    lane_identity "${LANE_FILES[@]}"
    ;;
  admit)
    [ "$#" = 3 ] && valid_sha "$2" && [[ $3 =~ ^[1-9][0-9]+$ ]] || refuse "admit needs identity and lock owner PID"
    LANE_ARMED_ID=$2
    readmit "$3" child
    admission_rc=$?
    if [ "$admission_rc" != 0 ]; then printf 'REFUSING: %s\n' "$LANE_MSG" >&2; fi
    exit "$admission_rc"
    ;;
  run)
    [ "$#" = 3 ] && valid_sha "$2" && [ "$3" = "$(queue_line "$2")" ] || refuse "run needs the reviewed identity and Mini queue sample"
    LANE_ARMED_ID=$2
    lane_admit dispatch || refuse "$LANE_MSG"
    [ ! -e "$LANE_LOCK" ] && [ ! -L "$LANE_LOCK" ] || refuse "Ultra already holds a host lock"
    check_inputs || refuse "$LANE_MSG inputs did not verify"
    [ ! -L "$LANE_STATUS" ] && [ ! -L "$LANE_LOG" ] || refuse "launcher status or log is a symlink"
    [[ "$(lane_last_state "$LANE_STATUS")" != "LANE DONE $LANE_NAME "* ]] || refuse "lane already completed"
    lane_init "mode=run identity=$LANE_ARMED_ID"
    lane_lock_acquire
    guard_or_stop "$?"
    receipt=$LANE/queue-admission.$$.json
    (set -C; admission_receipt "$$" > "$receipt") || lane_abort 6 "cannot record the locked queue admission"
    readmit "$$" after-lock
    guard_or_stop "$?"
    lane_say CHECKED "identity=$LANE_ARMED_ID queue_admission_sha256=$(lane_sha "$receipt")"
    lane_supervise env -i HOME="$ULTRA_HOME" PATH="$PATH" "$LANE_PY" -B "$LANE/sz2r_dispatch.py" "$LANE" "$LANE_ARMED_ID" "$$"
    child_rc=$?
    if [ "$child_rc" != 0 ]; then
      lane_hold_present && lane_pause "$LANE_MSG"
      lane_abort "$child_rc" "supervisor exit $child_rc; see $LANE_LOG"
    fi
    readmit "$$" before-terminal
    guard_or_stop "$?"
    terminal=$("$LANE_PY" -IB - "$LANE" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
handoff = root / "screen.handoff.json"
receipt = json.loads((root / "screen.published.json").read_bytes())
data = handoff.read_bytes()
binding = json.loads(data)
hashes = ("handoff_sha256", "sums_sha256", "reader_sha256")
if (receipt["handoff"] != str(handoff) or receipt["reader"] != "codex"
        or receipt["reader_path"] != str(root / "sz2r_read_once.py")
        or any(not re.fullmatch("[0-9a-f]{64}", receipt[key]) for key in hashes)
        or hashlib.sha256(data).hexdigest() != receipt["handoff_sha256"]
        or binding["sums_sha256"] != receipt["sums_sha256"]
        or binding["recipe_sha256"] != receipt["recipe_sha256"]
        or binding["sources"]["sz2r_read_once.py"] != receipt["reader_sha256"]):
    sys.exit("invalid designated screen handoff")
print(" ".join(f"{key}={receipt[key]}" for key in hashes))
PY
    ) || lane_abort 6 "the screen handoff was not published"
    lane_done "identity=$LANE_ARMED_ID handoff=$LANE/screen.handoff.json $terminal"
    ;;
  *)
    printf 'Usage: %s identity | check | dispatch ID | admit ID PID | run ID QUEUE_SAMPLE\n' "$0" >&2
    exit 2
    ;;
esac
