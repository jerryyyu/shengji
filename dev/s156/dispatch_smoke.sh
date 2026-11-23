#!/bin/bash
# Direct admission samples the Mini's fleet queue immediately before dispatch to the Ultra.
set -eu
[ "$(hostname)" = Jerrys-Mac-mini.local ] || exit 6
tools=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools
[ -s "$tools/fleet_queue.json" ] || exit 6
packet=/Users/jeryyu/fleet/codex-sz2-smoke-r3-final
run="env -i HOME=/Users/jeryyu PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash $packet/run_smoke.sh"
local_sha=$(shasum -a 256 < "$0" | cut -d' ' -f1)
remote_sha=$(ssh -o BatchMode=yes ultra "shasum -a 256 < $packet/dispatch_smoke.sh")
[ "${remote_sha%% *}" = "$local_sha" ] || exit 6
case "${1:-}" in
  --preflight) exec ssh -o BatchMode=yes ultra "$run --preflight" ;;
  --dispatch)
    identity=$(ssh -o BatchMode=yes ultra "$run --preflight")
    [[ "$identity" =~ ^[0-9a-f]{64}$ ]] || exit 6
    next=$(env -u FLEET_QUEUE python3 "$tools/fleet_queue.py" next ultra)
    [ "$next" = "sz2-m2-smoke-r3:released sha=${identity:0:8}" ] || {
      echo "Ultra queue: $next" >&2
      exit 6
    }
    exec ssh -o BatchMode=yes ultra "test -f $packet/launcher.RELEASE && { nohup /usr/bin/python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1],sys.argv[1:])' $run >>$packet/dispatch.log 2>&1 </dev/null & }" ;;
  *) exit 2 ;;
esac
