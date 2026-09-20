#!/usr/bin/env bash
# Perf-only, one-shot qualification successor. Never launches the full screen.
set -euo pipefail
predecessor=codex-policy-wk-800-20260920.service
expected_invocation=466bab077e1746c2b0560f4eded26450
python=/root/gen-hybrid/server/.venv/bin/python
launcher=/root/codex-joint-grid-launcher-20260920/server/scripts/policy_abc_launcher.py
deadline=$((SECONDS + 33000))
while true; do
    invocation=$(systemctl show "$predecessor" -p InvocationID --value)
    [[ "$invocation" == "$expected_invocation" ]] || {
        echo 'Predecessor missing/replaced; manual verification required' >&2; exit 1;
    }
    state=$(systemctl show "$predecessor" -p ActiveState --value)
    case "$state" in
        active|activating|deactivating)
            (( SECONDS < deadline )) || { echo 'Queue observation deadline' >&2; exit 1; }
            sleep 30 ;;
        inactive)
            [[ $(systemctl show "$predecessor" -p Result --value) == success ]]
            [[ $(systemctl show "$predecessor" -p ExecMainStatus --value) == 0 ]]
            break ;;
        *) echo "Predecessor state $state; refusing handoff" >&2; exit 1 ;;
    esac
done
# Require the named predecessor's complete outputs, not just a stopped process.
"$python" - <<'PY'
import json
from pathlib import Path
root = Path('/root/codex-policy-wk-800-20260920')
for arm in ('W4_K8', 'W16_K8', 'W4_K16'):
    summary = json.loads((root / arm / 'summary.json').read_text())
    if (summary.get('complete') != 800 or summary.get('expected') != 800
            or summary.get('errors') != [] or summary.get('aggregation_error')):
        raise SystemExit('Predecessor output unusable: ' + arm)
PY
# The launcher independently verifies frozen source/checkpoints, both host
# reservations, processes and resources. Any refusal ends this queue: no retry.
exec "$python" "$launcher" \
    --source /root/codex-search-reference-source-20260920 \
    --python "$python" \
    --checkpoint /root/codex-joint-grid-models-20260920/js-m1.pt \
    --grid-checkpoint /root/codex-joint-grid-models-20260920/js-g1.pt \
    --out /root/codex-joint-grid-qualify-20260920 \
    --suite joint-grid-screen --qualify --run
