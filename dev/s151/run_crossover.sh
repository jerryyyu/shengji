#!/bin/bash
# Run directly under env -i HOME=/Users/jeryyu PATH=/usr/bin:/bin:/usr/sbin:/sbin.
# The release owner freezes the native hashes and the canonical seed registry and both actual predecessor
# terminal records before reviewing the host packet.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done
tools=/Users/jeryyu/Projects/shengji-wt/codex-s151-d3268923
trees=/Users/jeryyu/Projects/shengji-wt
fleet=/Users/jeryyu/fleet
packet=$fleet/s151-generator-crossover
base=$trees/codex-s151-fd968f7f
candidate=$trees/codex-s151-2fb1cc3f
source_dir=$tools/dev/s151
lib=$tools/server/scripts/lanes/lane_lib.sh
canonical_registry=$packet/canonical-seeds.json
registry=/Users/jeryyu/Projects/shengji/server/runs/seed_windows.json
models=$fleet/claude-ut-gen2/models
LANE_PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
LANE_NAME=s151-generator-crossover
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=150
LANE_MAX_SECONDS=3600
LANE_WAIT_CEILING=2
LANE_POLL=1
LANE_FILES=("$0" "$lib" "$packet/native.sha256" "$packet/predecessors.tsv" "$canonical_registry")
export PYTHONPATH=$tools/server
. "$lib" || exit 6

# Direct admission only. A previous partial or completed capture stays intact.
root=$packet/capture
check_slot() {
  local path terminal actual count=0
  local utc='[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'
  local state_prefix="^($utc )?[^[:space:]]+ "
  local s156_done="${state_prefix}DONE [^[:space:]]+( .*)?$"
  local s156_housekeeping="${state_prefix}(UNLOCKED|WARNING)( |$)"
  local failed='(^|[[:space:]])(ABORT|REFUSING:?|PAUSED|FAILED)([[:space:]]|$)'
  local nonzero_rc='(^|[[:space:]])rc=(0[^[:space:]]+|[^0[:space:]][^[:space:]]*)?([[:space:]]|$)'
  while IFS=$'\t' read -r path terminal; do
    case $count in
      0)
        [ "$path" = "$fleet/claude-ut-retrain4/DRV.status" ] &&
          [[ "$terminal" =~ ^DRV\ DONE\ [^[:space:]]+\ duels\ rc=0$ ]] || return 1
        actual=$(tail -n 1 "$path") || return 1
        ;;
      1)
        [[ "$path" = "$fleet/"* ]] && [ "$path" != "$fleet/claude-ut-retrain4/DRV.status" ] &&
          [[ "$terminal" =~ $s156_done && ! "$terminal" =~ $failed &&
             ! "$terminal" =~ $nonzero_rc ]] || return 1
        actual=$(LANE_HOUSEKEEPING_RE=$s156_housekeeping lane_last_state "$path") || return 1
        ;;
      *) return 1 ;;
    esac
    [ "$actual" = "$terminal" ] || return 1
    count=$((count + 1))
  done < "$packet/predecessors.tsv"
  [ "$count" = 2 ]
}

check_inputs() {
  local tree mod rel hash listed dirty
  [ "$(git -C "$tools" rev-parse HEAD)" = d32689231695cfcbad80c20262ab35d06ed6f57f ] &&
    dirty=$(git -C "$tools" status --porcelain) && [ -z "$dirty" ] || return 1
  # Require all ten in-place module paths, one digest per module per tree.
  for tree in "$base" "$candidate"; do
    for mod in engine/_fast ai/_cwv_math ai/_endgame_fast train/_pv_fast train/_reply_fast; do
      rel="$tree/server/shengji/$mod.cpython-314-darwin.so"
      listed=$(awk -v p="$rel" '$2 == p {print $1}' "$packet/native.sha256") || return 1
      hash=$(lane_sha "$rel") && [ "$hash" = "$listed" ] || return 1
    done
  done
}
check_seed_windows() {
  local file
  for file in "$canonical_registry" "$registry"; do
    [ -f "$file" ] && "$LANE_PY" -B "$tools/server/scripts/seed_windows.py" \
      --registry "$file" check 4301400 416 --purpose trajectory || return 1
  done
}
check_slot || { echo 'host packet or predecessor mismatch' >&2; exit 6; }
lane_arm || { echo "$LANE_MSG" >&2; exit 6; }
# mkdir is the one-shot claim even across competing invocations.
lane_init
lane_lock_acquire || { echo "$LANE_MSG" >&2; lane_abort 6 "$LANE_MSG"; }
lane_admit after-lock && check_slot && check_inputs && check_seed_windows || { echo 'admission, slot or native inputs changed' >&2; lane_abort 6 'preflight refused'; }
mkdir "$root" || lane_abort 6 'capture exists or cannot be created'
LANE_STATUS=$root/launcher.status
LANE_LOG=$root/launcher.log
lane_say START "pid=$$ host=$(hostname)"
for ((i=0; i<16; i++)); do
  lane_admit "capture $i" || lane_abort 6 "$LANE_MSG"
  check_slot || lane_abort 6 'predecessor changed'
  check_inputs || lane_abort 6 'capture tools or native inputs changed'
  lane_supervise "$LANE_PY" -B "$source_dir/capture_generator.py" capture "$i" \
    --root "$root" --base "$base" --candidate "$candidate" --models "$models" --registry "$registry"
  rc=$?
  [ "$rc" = 0 ] || lane_abort "$rc" "capture $i failed"
done
[ -s "$root/timings.json" ] || lane_abort 6 'missing terminal timings'
lane_done '16 captures sealed for comparison'
