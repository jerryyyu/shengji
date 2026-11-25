#!/bin/bash
set -eu
packet=/Users/jerryyu/fleet/codex-sz3-cpu-filler-v1
remote=/Users/jeryyu/fleet/codex-sz3-cpu-filler-v1
[ "$0" = "$packet/dispatch_filler.sh" ] && [ "$(hostname)" = Jerrys-Mac-mini.local ] || exit 6
. "$packet/lane_lib.sh"
tools=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools
queue_ok() {
  [ "$(env -u FLEET_QUEUE python3 "$tools/fleet_queue.py" next ultra)" = 'sz3-joint-v1:released sha=405fb269' ]
}
qssh() { ssh -o BatchMode=yes -o ConnectTimeout=5 ultra "$@"; }
digest=$(lane_identity "$packet/filler.sh" "$0" "$packet/lane_lib.sh" "$packet/sz3_filler.py" \
         "$packet/sz3_filler_generator.py" "$packet/sz3_filler_pace.py" "$packet/sz3_filler_process.py")
[ "$(qssh "/bin/bash $remote/filler.sh --identity")" = "$digest" ] && queue_ok || exit 6
case "${1:-}" in
  --preflight) qssh "/bin/bash $remote/filler.sh --preflight" && echo "$digest" ;;
  --dispatch)
    [ "$(qssh "/bin/bash $remote/filler.sh --admit")" = "$digest" ] && queue_ok || exit 6
    qssh "cd $remote && /usr/bin/python3 -c 'import os,subprocess; subprocess.Popen([\"/bin/bash\",\"$remote/filler.sh\",\"--run\"],stdin=subprocess.DEVNULL,stdout=open(\"dispatch.log\",\"ab\"),stderr=subprocess.STDOUT,start_new_session=True)'"
    ;;
  *) exit 2 ;;
esac
