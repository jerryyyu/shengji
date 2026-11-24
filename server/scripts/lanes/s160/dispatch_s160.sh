#!/bin/bash
# lane-lib: exempt Mini-side dispatcher; it hands the launcher identity to the Ultra launcher, which owns the lane library gates
# S160 dispatch (= codex-sz2-duel-a-v1/dispatch_duel_a.sh with this lane's names): run on the Mini.  The Ultra queue's next entry
# must be this lane released at the launcher's identity, sampled immediately before the hand-off; the launcher then refuses a
# held host lock instead of waiting, so the run starts only in the assigned idle slot.
#   usage: dispatch_s160.sh --identity | --dispatch
set -eu
[ "$(hostname)" = Jerrys-Mac-mini.local ] || exit 6
[ "$#" = 1 ] || exit 2
tools=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools
[ -s "$tools/fleet_queue.json" ] || exit 6
name=s160-rt4attrib-v1
packet=/Users/jeryyu/fleet/claude-$name
run="env -i HOME=/Users/jeryyu PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash $packet/s160.sh"
local_sha=$(shasum -a 256 < "$0")
remote_sha=$(ssh -o BatchMode=yes ultra "shasum -a 256 < $packet/dispatch_s160.sh")
[ "${remote_sha%% *}" = "${local_sha%% *}" ] || exit 6

case "$1" in
  --identity) exec ssh -o BatchMode=yes ultra "$run identity" ;;
  --dispatch)
    identity=$(ssh -o BatchMode=yes ultra "$run identity")
    [[ "$identity" =~ ^[0-9a-f]{64}$ ]] || exit 6
    next=$(env -u FLEET_QUEUE python3 "$tools/fleet_queue.py" next ultra)
    [ "$next" = "$name:released sha=${identity:0:8}" ] || {
      echo "Ultra queue: $next" >&2
      exit 6
    }
    exec ssh -o BatchMode=yes ultra "test -f /Users/jeryyu/fleet/claude_s160.RELEASE && test ! -e /Users/jeryyu/fleet/.claude-host.lock && { nohup /usr/bin/python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1],sys.argv[1:])' $run run $identity >>$packet/dispatch.log 2>&1 </dev/null & }" ;;
  *) exit 2 ;;
esac
