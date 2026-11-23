#!/bin/bash
# Direct admission under env -i with the host's HOME and system PATH.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done
trees=/Users/jeryyu/Projects/shengji-wt
repo=/Users/jeryyu/Projects/shengji
fleet=/Users/jeryyu/fleet
tools=$trees/codex-tail-crossover-capture-d72d2628
engine=$trees/codex-trajectory-tail-mirrors-8c4c0f19
lib=$tools/server/scripts/lanes/lane_lib.sh
LANE_NAME=tail-mirror-generator-crossover
packet=$fleet/$LANE_NAME
root=$packet/capture
registry=$packet/canonical-seeds.json
LANE_PY=$repo/server/.venv/bin/python
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=150
LANE_MAX_SECONDS=3600
LANE_WAIT_CEILING=2
LANE_POLL=1
LANE_FILES=("$0" "$lib" "$registry" "$packet/native.sha256" "$packet/s156-terminal.tsv")
export PYTHONPATH=$tools/server
. "$lib" || exit 6

check_tree() {
  local dirty
  [ "$(git -C "$1" rev-parse HEAD)" = "$2" ] &&
    dirty=$(git -C "$1" status --porcelain) && [ -z "$dirty" ]
}
check_slot() {
  local path line extra actual
  # The release review binds the S156 terminal path and complete successful state line.
  [ "$(awk 'END {print NR}' "$packet/s156-terminal.tsv")" = 1 ] &&
    IFS=$'\t' read -r path line extra < "$packet/s156-terminal.tsv" || return 1
  case "$path" in *"/../"*|*"/./"*) return 1;; "$fleet"/*) ;; *) return 1;; esac
  case "${path#"$fleet"/} $line" in *s156*|*S156*|*sz2*|*SZ2*) ;; *) return 1;; esac
  [ -z "$extra" ] && [ -n "$line" ] && lane_terminal_ok "$line" &&
    [[ "$line" =~ ^([^[:space:]]+[[:space:]]){1,2}DONE[[:space:]].*[[:space:]]rc=0$ ]] &&
    actual=$(lane_last_state "$path") && [ "$actual" = "$line" ]
}
check_inputs() {
  local mod path want
  check_tree "$tools" d72d2628dafbf77526f09463b186f363a532a9c9 &&
    check_tree "$engine" 8c4c0f1982f5c015d4bf288b93722db5b32140e0 || return 1
  for mod in engine/_fast ai/_cwv_math ai/_endgame_fast train/_pv_fast train/_reply_fast; do
    path=$engine/server/shengji/$mod.cpython-314-darwin.so
    want=$(awk -v p="$path" '$2 == p {print $1}' "$packet/native.sha256") || return 1
    [[ "$want" =~ ^[a-f0-9]{64}$ ]] && [ "$(lane_sha "$path")" = "$want" ] || return 1
  done
}
check_registry() {
  # Every capture consumes the identical flattened registry. A new live reservation can still veto it.
  [ ! -e "$packet/canonical-seeds.d" ] && [ ! -L "$packet/canonical-seeds.d" ] &&
    [ -f "$repo/server/runs/seed_windows.json" ] &&
    "$LANE_PY" -B "$tools/server/scripts/seed_windows.py" --registry "$registry" check 4301400 416 --purpose trajectory &&
    "$LANE_PY" -B "$tools/server/scripts/seed_windows.py" --registry "$repo/server/runs/seed_windows.json" check 4301400 416 --purpose trajectory
}
lane_arm || { echo "$LANE_MSG" >&2; exit 6; }
check_slot || { echo 'S156 terminal required' >&2; exit 6; }
lane_init
lane_lock_acquire || lane_abort 6 "$LANE_MSG"
lane_admit after-lock && check_slot && check_inputs && check_registry || lane_abort 6 'host preflight refused'
mkdir "$root" || lane_abort 6 'capture already claimed or unavailable'
LANE_STATUS=$root/launcher.status
LANE_LOG=$root/launcher.log
lane_say START "pid=$$ host=$(hostname)"
for ((i=0; i<16; i++)); do
  lane_admit "capture $i" && check_slot && check_inputs && check_registry || lane_abort 6 'capture admission refused'
  lane_supervise "$LANE_PY" -B "$tools/dev/s151/capture_generator.py" capture "$i" \
    --root "$root" --tree "$engine" --models "$fleet/claude-ut-gen2/models" --registry "$registry"
  rc=$?
  [ "$rc" = 0 ] || lane_abort "$rc" "capture $i failed"
done
[ -s "$root/timings.json" ] || lane_abort 6 'missing terminal timings'
lane_done '16 captures sealed for comparison'
