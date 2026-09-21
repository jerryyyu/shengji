#!/usr/bin/env bash
# One-shot Cloud successor; only qualifications, never full screens or retries.
set -euo pipefail
predecessor=codex-pv-production-w64-screen-20260921.service
expected_invocation=0eb17d68e7b34437b8221e2d826dbaab
python=/root/gen-hybrid/server/.venv/bin/python
launcher=/root/codex-joint-production-launcher-20260921/server/scripts/policy_abc_launcher.py
deadline=$((SECONDS + 21600))
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
        inactive) require_success; break ;;
        *) echo "Predecessor state $state; refusing handoff" >&2; exit 1 ;;
    esac
done
# Bind the output observed under live PID1422025 to its immutable launch plan.
"$python" - <<'PY'
import hashlib
import json
from pathlib import Path
root = Path('/root/codex-pv-production-w64-screen-20260921')
identity = root.stat()
if (identity.st_dev, identity.st_ino) != (2049, 1052663):
    raise SystemExit('Predecessor output directory replaced')
if hashlib.sha256((root / 'launch-plan.json').read_bytes()).hexdigest() != \
        '4138b06d8ddd2e5db16d350c5cae50c27cdde9090daabc3d2cad126686646e26':
    raise SystemExit('Predecessor launch plan differs')
summary = json.loads((root / 'SOFT_W64_K8' / 'summary.json').read_text())
if (summary.get('complete') != 800 or summary.get('expected') != 800
        or summary.get('errors') != [] or summary.get('aggregation_error')):
    raise SystemExit('Predecessor output unusable')
PY
# Recheck service identity; launcher's existing guards reject a busy/reserved
# host, changed source/checkpoints, insufficient resources or existing output.
read_snapshot
require_success
exec "$python" "$launcher" \
    --source /root/codex-policy-source-20260920 \
    --python "$python" \
    --checkpoint /root/head8k/m1-best.pt \
    --grid-checkpoint /root/head8k/g1-best.pt \
    --production-checkpoint /root/codex-production-js-m1-0d17fd03.npz \
    --out /root/codex-joint-production-qualify-20260921 \
    --suite joint-production-qualify --qualify --production-worlds 64 --run
