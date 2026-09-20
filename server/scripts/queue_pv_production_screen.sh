#!/usr/bin/env bash
# Cloud-only one-shot production comparison after the frozen world-scaling screen.
set -euo pipefail
predecessor=codex-pv-world-scaling-800-20260920.service
expected_invocation=4065f2b75f7d4cc298e82bf01fdff710
python=/root/gen-hybrid/server/.venv/bin/python
launcher=/root/codex-production-full-launcher-20260920/server/scripts/policy_abc_launcher.py
deadline=$((SECONDS + 66000))
read_snapshot() {
    local snapshot key value
    invocation= state= substate= result= exit_status= main_pid=
    snapshot=$(systemctl show "$predecessor" -p InvocationID -p ActiveState \
        -p SubState -p Result -p ExecMainStatus -p MainPID) || return 1
    while IFS='=' read -r key value; do
        case "$key" in
            InvocationID) invocation=$value ;;
            ActiveState) state=$value ;;
            SubState) substate=$value ;;
            Result) result=$value ;;
            ExecMainStatus) exit_status=$value ;;
            MainPID) main_pid=$value ;;
        esac
    done <<< "$snapshot"
    [[ "$invocation" == "$expected_invocation" ]] || {
        echo 'Predecessor missing/replaced; manual verification required' >&2
        return 1
    }
}
require_success() {
    [[ "$state" == active && "$substate" == exited \
        && "$result" == success && "$exit_status" == 0 \
        && "$main_pid" == 0 ]] || {
        echo 'Predecessor not terminal-success; refusing handoff' >&2
        return 1
    }
}
require_launcher() {
    # The reviewed supervisor is standalone (stdlib imports only). Bind its
    # exact bytes, not merely a mutable checkout pathname, at handoff time.
    "$python" - "$launcher" <<'VERIFY_LAUNCHER'
import hashlib
import sys
from pathlib import Path
if hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest() != \
        'd83f8c25b5f8ef63b32e47b57bbc911bcbe1893f95c5add6462c5c119e093dd1':
    raise SystemExit('Reviewed production launcher changed; refusing handoff')
VERIFY_LAUNCHER
}
while true; do
    read_snapshot
    case "$state/$substate" in
        active/exited)
            require_success
            break ;;
        active/running|activating/*|deactivating/*)
            (( SECONDS < deadline )) || { echo 'Queue observation deadline' >&2; exit 1; }
            sleep 30 ;;
        *) echo "Predecessor state $state; refusing handoff" >&2; exit 1 ;;
    esac
done
# Require the named predecessor's complete outputs, not just a stopped process.
"$python" - <<'PY'
import json
import hashlib
from pathlib import Path
root = Path('/root/codex-pv-world-scaling-800-20260920')
# Captured while PID1416118 was live: /proc cmdline named this output and
# /proc environ INVOCATION_ID matched the pinned service invocation above.
# Bind this particular fresh run directory and immutable launch plan; merely
# placing successful stale summaries at the same pathname is insufficient.
identity = root.stat()
if (identity.st_dev, identity.st_ino) != (2049, 1051821):
    raise SystemExit('Predecessor output directory replaced')
if hashlib.sha256((root / 'launch-plan.json').read_bytes()).hexdigest() != \
        '521a9d5d56d0a5cb625b077467d15884c53c07a72a673c8756099392b9bf9345':
    raise SystemExit('Predecessor launch plan differs')
for arm in ('W16_K8', 'W32_K8', 'W64_K8'):
    summary = json.loads((root / arm / 'summary.json').read_text())
    if (summary.get('complete') != 800 or summary.get('expected') != 800
            or summary.get('errors') != [] or summary.get('aggregation_error')):
        raise SystemExit('Predecessor output unusable: ' + arm)
PY
# The launcher independently verifies frozen source/checkpoints, both host
# reservations, processes and resources. Any refusal ends this queue: no retry.
read_snapshot
require_success
require_launcher
exec "$python" "$launcher" \
    --source /root/codex-policy-source-20260920 \
    --python "$python" \
    --checkpoint /root/head8k/soft-best.pt \
    --production-checkpoint /root/codex-production-js-m1-0d17fd03.npz \
    --out /root/codex-pv-production-800-20260920 \
    --suite pv-production-screen --run
