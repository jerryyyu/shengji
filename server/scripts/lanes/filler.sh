#!/bin/bash
set -eu
packet=/Users/jeryyu/fleet/codex-sz3-cpu-filler-v1
[ "$0" = "$packet/filler.sh" ] && [ "$(hostname)" = Jerrys-Mac-Studio.local ] || exit 6
. "$packet/lane_lib.sh"
LANE_HOSTNAME=Jerrys-Mac-Studio.local
LANE_RELEASE=$packet/launcher.RELEASE
LANE_HOLDS="$packet/launcher.HOLD"
LANE_FILES=("$0" "$packet/dispatch_filler.sh" "$packet/lane_lib.sh" "$packet/sz3_filler.py"
            "$packet/sz3_filler_generator.py" "$packet/sz3_filler_pace.py" "$packet/sz3_filler_process.py")
py=/Users/jeryyu/Projects/shengji/server/.venv/bin/python
case "${1:-}" in
  --admit)
    lane_arm || { echo "$LANE_MSG" >&2; exit 6; }
    echo "$LANE_ARMED_ID" ;;
  --preflight|--run)
    ! lane_hold_present || exit 6
    [ "$1" != --run ] || lane_arm || exit 6
    exec /usr/bin/env -i HOME=/Users/jeryyu PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/sbin/taskpolicy -b "$py" -s -B "$packet/sz3_filler.py" "$1" ;;
  --identity) lane_identity "${LANE_FILES[@]}" ;;
  *) exit 2 ;;
esac
