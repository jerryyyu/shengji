#!/usr/bin/env bash
# Perf-only, one-shot qualification successor. Never launches the full screen.
set -euo pipefail
predecessor=codex-policy-wk-800-20260920.service
expected_invocation=466bab077e1746c2b0560f4eded26450
python=/root/gen-hybrid/server/.venv/bin/python
launcher=/root/codex-joint-grid-launcher-20260920/server/scripts/policy_abc_launcher.py
deadline=$((SECONDS + 33000))
read_snapshot() {
    local snapshot key value
    invocation= state= result= exit_status= main_pid=
    snapshot=$(systemctl show "$predecessor" -p InvocationID -p ActiveState \
        -p Result -p ExecMainStatus -p MainPID) || return 1
    while IFS='=' read -r key value; do
        case "$key" in
            InvocationID) invocation=$value ;;
            ActiveState) state=$value ;;
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
    [[ "$state" == inactive && "$result" == success && "$exit_status" == 0 \
        && "$main_pid" == 0 ]] || {
        echo 'Predecessor not terminal-success; refusing handoff' >&2
        return 1
    }
}
while true; do
    read_snapshot
    case "$state" in
        active|activating|deactivating)
            (( SECONDS < deadline )) || { echo 'Queue observation deadline' >&2; exit 1; }
            sleep 30 ;;
        inactive)
            require_success
            break ;;
        *) echo "Predecessor state $state; refusing handoff" >&2; exit 1 ;;
    esac
done
# Require the named predecessor's complete outputs, not just a stopped process.
"$python" - <<'PY'
import json
import hashlib
from pathlib import Path
root = Path('/root/codex-policy-wk-800-20260920')
# Captured while PID3719660 was live: /proc cmdline named this output and
# /proc environ INVOCATION_ID matched the pinned service invocation above.
# Bind this particular fresh run directory and immutable launch plan; merely
# placing successful stale summaries at the same pathname is insufficient.
identity = root.stat()
if (identity.st_dev, identity.st_ino) != (2049, 784066):
    raise SystemExit('Predecessor output directory replaced')
if hashlib.sha256((root / 'launch-plan.json').read_bytes()).hexdigest() != \
        'c827bf36b0c86d0ca18c9333664d077032ab2fc1aeba26967bc8fd404ac7d352':
    raise SystemExit('Predecessor launch plan differs')
for arm in ('W4_K8', 'W16_K8', 'W4_K16'):
    summary = json.loads((root / arm / 'summary.json').read_text())
    if (summary.get('complete') != 800 or summary.get('expected') != 800
            or summary.get('errors') != [] or summary.get('aggregation_error')):
        raise SystemExit('Predecessor output unusable: ' + arm)
PY
# The launcher independently verifies frozen source/checkpoints, both host
# reservations, processes and resources. Any refusal ends this queue: no retry.
read_snapshot
require_success
exec "$python" "$launcher" \
    --source /root/codex-search-reference-source-20260920 \
    --python "$python" \
    --checkpoint /root/codex-joint-grid-models-20260920/js-m1.pt \
    --grid-checkpoint /root/codex-joint-grid-models-20260920/js-g1.pt \
    --out /root/codex-joint-grid-qualify-20260920 \
    --suite joint-grid-screen --qualify --run
