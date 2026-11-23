#!/bin/bash
# The single-use root owns both joint arms and their matched prefix reports.
set -u
for setting in ${!LANE_@}; do echo "inherited lane setting: $setting" >&2; exit 6; done
fleet=/Users/jeryyu/fleet
packet=$fleet/codex-sz2-joint-v1
root=$packet/capture
tree=/Users/jeryyu/Projects/shengji-wt/codex-sz2-joint-afaa8941
head=afaa89412b0f880f9b8bf3cc3771643f9b66694a
lib=$tree/server/scripts/lanes/lane_lib.sh
worker=$tree/server/scripts/sz2_gpu_smoke.py
LANE_NAME=sz2-joint-v1
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_LOCK=$fleet/.claude-host.lock
LANE_HOLDS="$packet/launcher.HOLD $fleet/claude_ut_gen2.HOLD"
LANE_PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
LANE_FILES=("$packet/run_joint.sh" "$packet/joint_phases.sh" "$packet/dispatch_joint.sh" "$lib" "$tree/server/shengji/train/unified_readout.py" "$tree/server/scripts/sz2_gpu_smoke.py" "$tree/server/scripts/sz2_joint_segment.py" "$tree/server/scripts/sz2_offline_gate.py")
LANE_DISK_DIR=$fleet
LANE_MIN_FREE_GIB=350
LANE_MAX_SECONDS=9000
LANE_STOP_GRACE=1700
LANE_WAIT_CEILING=2
LANE_POLL=1
LANE_GATES="$fleet/codex-sz2-smoke-r4/capture/launcher.status ^LANE DONE sz2-m2-smoke-r4 .* rc=0$
$fleet/s157-stepA-ultra/status.txt ^[^ ]+ RUN DONE 64 seeds rc 0$
$fleet/claude-ut-retrain4/RT4.status ^RT4 DONE 2026-11-22T22:30:21Z rc=0$
$fleet/claude-ut-retrain4/DRV.status ^DRV DONE 2026-11-22T22:32:56Z duels rc=4$
$fleet/claude-ut-retrain4/R4F.status ^UTD DONE 2026-11-22T23:40:37Z .* rc=0$
$fleet/s151-generator-crossover/capture/launcher.status ^LANE DONE s151-generator-crossover .* rc=0$"
export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.6 PYTORCH_MPS_LOW_WATERMARK_RATIO=0.5
export PYTHONPATH=$tree/server OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
[ "$(hostname)" = "$LANE_HOSTNAME" ] && [ "$0" = "$packet/run_joint.sh" ] || exit 6
clean_tree() {
  local dirty
  [ "$(git -C "$tree" rev-parse HEAD)" = "$head" ] &&
    dirty=$(git -C "$tree" status --porcelain) && [ -z "$dirty" ]
}
clean_tree || exit 6
. "$lib" || exit 6
. "$packet/joint_phases.sh" || exit 6
preflight() {
  clean_tree && ! lane_hold_present && lane_check_pins && lane_gate && lane_disk_check &&
    [ ! -e "$root" ] && [ ! -L "$root" ] &&
    "$LANE_PY" -B "$tree/server/scripts/sz2_joint_segment.py" small --root "$root" >/dev/null
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
lane_say START "pid=$$ host=$(hostname) joint training"
joint_training
