#!/bin/bash
# Each cache occupies its own single-use reservation and release.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done
arm=${1:-}
case "$arm" in S|M) ;; *) exit 2 ;; esac
fleet=/Users/jeryyu/fleet
name=sz2-post-$arm-v1
packet=$fleet/codex-$name
root=$packet/capture
[ "$(hostname)" = Jerrys-Mac-Studio.local ] && [ "$0" = "$packet/run_post.sh" ] || exit 6
read -r reserved head extra < "$packet/source" || exit 6
[ "$reserved" = "$arm" ] && [[ "$head" =~ ^[0-9a-f]{40}$ ]] && [ -z "$extra" ] || exit 6
tree=/Users/jeryyu/Projects/shengji-wt/codex-sz2-post-${head:0:8}
base=$tree/server/scripts
probe=$fleet/codex-sz2-small-capacity-v1
lib=$base/lanes/lane_lib.sh
clean_tree() {
  local dirty
  [ "$(git -C "$tree" rev-parse HEAD)" = "$head" ] &&
    dirty=$(git -C "$tree" status --porcelain) && [ -z "$dirty" ]
}
clean_tree || exit 6
. "$lib" || exit 6
LANE_NAME=$name
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/codex-sz2-joint-v1/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
LANE_FILES=("$packet/source" "$packet/run_post.sh" "$packet/dispatch_post.sh" "$lib" "$base/sz2_post_arm.py" "$base/sz2_export_arm.py" "$base/sz2_export_parity.py" "$base/sz2_gpu_smoke.py" "$base/sz2_cache_arm.py" "$base/sz2_polish_arm.py" "$base/sz2_joint_segment.py" "$tree/server/shengji/train/unified_readout.py")
LANE_PINS="b194fa7cb62ba8c3be7eb15e6ce9b813d32faff97cef7442969a381a3f424f88  $probe/small_capacity.py"
LANE_GATES="$fleet/codex-sz2-joint-v1/capture/launcher.status ^LANE DONE sz2-joint-v1 [^ ]+ joint arms complete rc=0$"
if [ "$arm" = M ]; then
  LANE_GATES="$LANE_GATES
$fleet/codex-sz2-post-S-v1/capture/launcher.status ^LANE DONE sz2-post-S-v1 [^ ]+ selected package parity verified rc=0$"
fi
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=350
LANE_MAX_SECONDS=86400
LANE_WAIT_CEILING=2
LANE_POLL=1
export PYTHONPATH=$tree/server:$probe PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
preflight() {
  local joint_id dir
  for dir in "$fleet/codex-sz2-cache-v1/$arm" "$fleet/codex-sz2-polish-v1/$arm" "$fleet/codex-sz2-export-v1/$arm"; do
    [ ! -e "$dir" ] && [ ! -L "$dir" ] || return 6
  done
  if [ "$arm" = M ]; then
    [ "$(cat "$fleet/codex-sz2-post-S-v1/source")" = "S $head" ] || return 6
    if compgen -G "$fleet/codex-sz2-cache-v1/S/*/*.npz" >/dev/null; then return 6; fi
  fi
  joint_id=$(cat "$fleet/codex-sz2-joint-v1/launcher.RELEASE") &&
    [ "${joint_id%% *}" = 3cb0b58c2ea079b2c2653c5f8687ebf5fa1773bd9f82ecac115c938753fdcb04 ] &&
    clean_tree && ! lane_hold_present && lane_check_pins && lane_gate && lane_disk_check &&
    [ ! -e "$root" ] && [ ! -L "$root" ]
}
case "${2:-}" in
  --identity) lane_check_pins && lane_identity "${LANE_FILES[@]}"; exit $? ;;
  --preflight) [ ! -e "$LANE_LOCK" ] && preflight && lane_identity "${LANE_FILES[@]}"; exit $? ;;
  "") ;;
  *) exit 2 ;;
esac
lane_arm && preflight || exit 6
lane_init
lane_lock_acquire || lane_abort 6 "$LANE_MSG"
lane_admit after-lock && preflight || lane_abort 6 "admission failed: $LANE_MSG"
mkdir "$root" || lane_abort 6 'output already claimed'
LANE_STATUS=$root/launcher.status
LANE_LOG=$root/launcher.log
lane_say START "pid=$$ serial cache, polish and selected checkpoint export"
LANE_MIN_FREE_GIB=150
lane_supervise "$LANE_PY" -B "$base/sz2_post_arm.py" "$arm"
rc=$?
[ "$rc" = 0 ] || lane_abort "$rc" "post-training worker failed"
lane_done 'selected package parity verified'
