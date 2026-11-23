#!/bin/bash
# One timed small-model slice measures CPU memory alongside the resident provider.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done
fleet=/Users/jeryyu/fleet
packet=$fleet/codex-sz2-small-capacity-v1
root=$packet/capture
tree=/Users/jeryyu/Projects/shengji-wt/codex-sz2-joint-a8898dbe
head=a8898dbeb6d3dacc54c1227a7304e30b385620d5
lib=$tree/server/scripts/lanes/lane_lib.sh
LANE_NAME=sz2-small-capacity-v1
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/codex-sz2-joint-v1/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
LANE_FILES=("$packet/run_small_capacity.sh" "$packet/small_capacity.py" "$packet/dispatch_small_capacity.sh" "$lib" "$tree/server/shengji/train/unified_readout.py" "$tree/server/scripts/sz2_gpu_smoke.py" "$tree/server/scripts/sz2_joint_segment.py" "$tree/server/scripts/sz2_offline_gate.py")
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=350
LANE_MAX_SECONDS=900
LANE_STOP_GRACE=30
LANE_WAIT_CEILING=2
LANE_POLL=1
LANE_GATES="$fleet/codex-sz2-smoke-r4/capture/launcher.status ^LANE DONE sz2-m2-smoke-r4 .* rc=0$
$fleet/s157-stepA-ultra/status.txt ^[^ ]+ RUN DONE 64 seeds rc 0$
$fleet/claude-ut-retrain4/RT4.status ^RT4 DONE 2026-11-22T22:30:21Z rc=0$
$fleet/claude-ut-retrain4/DRV.status ^DRV DONE 2026-11-22T22:32:56Z duels rc=4$
$fleet/claude-ut-retrain4/R4F.status ^UTD DONE 2026-11-22T23:40:37Z .* rc=0$
$fleet/s151-generator-crossover/capture/launcher.status ^LANE DONE s151-generator-crossover .* rc=0$"
export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.6 PYTORCH_MPS_LOW_WATERMARK_RATIO=0.5
export PYTHONPATH=$tree/server:$tree/server/scripts OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
[ "$(hostname)" = "$LANE_HOSTNAME" ] && [ "$0" = "$packet/run_small_capacity.sh" ] || exit 6
clean_tree() {
  local dirty
  [ "$(git -C "$tree" rev-parse HEAD)" = "$head" ] &&
    dirty=$(git -C "$tree" status --porcelain) && [ -z "$dirty" ]
}
clean_tree || exit 6
. "$lib" || exit 6
preflight() {
  clean_tree && ! lane_hold_present && lane_check_pins && lane_gate && lane_disk_check &&
    [ ! -e "$root" ] && [ ! -L "$root" ] &&
    "$LANE_PY" -B "$packet/small_capacity.py" "$root" --preflight >/dev/null
}
case "${1:-}" in
  --preflight)
    [ ! -e "$LANE_LOCK" ] && preflight && lane_identity "${LANE_FILES[@]}" || exit 6
    exit 0 ;;
  "") ;;
  *) exit 2 ;;
esac
lane_arm && preflight || { echo "refused: $LANE_MSG" >&2; exit 6; }
lane_init
lane_lock_acquire || lane_abort 6 "$LANE_MSG"
lane_admit after-lock && preflight || lane_abort 6 "preflight after lock: $LANE_MSG"
mkdir "$root" || lane_abort 6 'output already claimed'
LANE_STATUS=$root/launcher.status
LANE_LOG=$root/launcher.log
lane_say START "pid=$$ host=$(hostname) small CPU capacity"
lane_supervise "$LANE_PY" -B "$packet/small_capacity.py" "$root"
rc=$?
[ "$rc" = 0 ] || lane_abort "$rc" "small CPU sample incomplete"
lane_done "small CPU capacity sampled"
