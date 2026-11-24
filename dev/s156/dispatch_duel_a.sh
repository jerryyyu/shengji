#!/bin/bash
# Sample the Mini queue immediately before handing the frozen identity to the Ultra.
# lane-lib: exempt This helper hands the identity to the Ultra launcher which owns the lane library gates.
set -eu
[ "$(hostname)" = Jerrys-Mac-mini.local ] || exit 6
[ "$#" = 1 ] || exit 2
tools=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools
[ -s "$tools/fleet_queue.json" ] || exit 6
name=sz2-duel-a-v1
packet=/Users/jeryyu/fleet/codex-$name
run="env -i HOME=/Users/jeryyu PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash $packet/run_duel_a.sh"
local_sha=$(shasum -a 256 < "$0")
remote_sha=$(ssh -o BatchMode=yes ultra "shasum -a 256 < $packet/dispatch_duel_a.sh")
[ "${remote_sha%% *}" = "${local_sha%% *}" ] || exit 6

case "$1" in
  --identity|--preflight) exec ssh -o BatchMode=yes ultra "$run $1" ;;
  --dispatch)
    identity=$(ssh -o BatchMode=yes ultra "$run --preflight")
    [[ "$identity" =~ ^[0-9a-f]{64}$ ]] || exit 6
    next=$(env -u FLEET_QUEUE python3 "$tools/fleet_queue.py" next ultra)
    [ "$next" = "$name:released sha=${identity:0:8}" ] || {
      echo "Ultra queue: $next" >&2
      exit 6
    }
    exec ssh -o BatchMode=yes ultra "test -f $packet/launcher.RELEASE && { nohup /usr/bin/python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1],sys.argv[1:])' $run --run $identity >>$packet/dispatch.log 2>&1 </dev/null & }" ;;
  *) exit 2 ;;
esac
