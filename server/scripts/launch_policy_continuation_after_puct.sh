#!/usr/bin/env bash
# Named cloud follow-up only. Run manually after reservation confirmation;
# --check validates readiness without taking the lane or starting compute.
set -euo pipefail
mode=${1:---check}
[[ "$mode" == --check || "$mode" == --launch ]] || exit 2
predecessor=codex-puct-gameplay-recovery-20260916.service
root=/root/codex-policy-continuation-20260916
out=/root/codex-policy-continuation-gameplay-20260916
py=/root/gen-hybrid/server/.venv/bin/python
state=$(systemctl show "$predecessor" --property=ActiveState --value)
result=$(systemctl show "$predecessor" --property=Result --value)
[[ "$state" == inactive && "$result" == success ]] || {
  echo "HOLD predecessor state=$state result=$result"; exit 3;
}
[[ $(git -C "$root" rev-parse HEAD) == 1ecefa90f010d6a635037814868ba1382019d4f7 ]] || exit 4
git -C "$root" diff --quiet HEAD -- server
"$py" - <<'PY'
import json
from pathlib import Path
base = Path('/root/codex-puct-gameplay-20260916')
for model in ('M1', 'G1'):
    for sweeps, depth in ((8,8),(32,8),(128,8),(128,16)):
        path = base / f'{model}-s{sweeps}-d{depth}' / 'summary.json'
        x = json.loads(path.read_text())
        assert x['complete'] and x['completed_clusters'] == x['requested_clusters'] == 13, path
        assert x['rounds'] == 26 and x['seed0'] == 617092026, path
        assert not x.get('problems') and not x.get('refused'), path
        assert x['bury_accounting_complete'], path
        c = x['config']; r = c['release27_search']
        assert (r['mode'], r['sweeps'], r['depth']) == ('puct', sweeps, depth), path
        assert c['decision_deadline']['seconds'] == 300, path
        assert r['arm_checkpoint'] == f'/root/claude-{model}.pt', path
PY
[[ ! -e /root/.claude-lane.lock ]] || { echo 'HOLD lane reserved'; exit 5; }
if pgrep -f '[c]wv_screen_queue|[c]wv_shortlist_screen|[t]rajectory_cli|[c]wv_release27_screen.py' >/dev/null; then
  echo 'HOLD occupied host'; exit 6
fi
if [[ "$mode" == --check ]]; then
  echo 'READY for named continuation queue; reservation confirmation still required'
  exit 0
fi
# Atomic lane claim after readiness; do not retry or steal an existing lock.
mkdir /root/.claude-lane.lock
trap 'rmdir /root/.claude-lane.lock' EXIT
export PYTHONPATH="$root/server" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1
mkdir -p "$out"
for model in M1 G1; do
  for horizon in k1 terminal; do
    extra=()
    [[ "$horizon" != terminal ]] || extra+=(--full-continuation)
    # One pair worker throughout; the initial pair remains in this13-pair run.
    # Existing output recipes are checked by the runner; no automatic retries.
    "$py" "$root/server/scripts/cwv_release27_screen.py" \
      --baseline-checkpoint /root/codex-release27-m1-12ce4415.npz \
      --prior-checkpoint /root/codex-release27-prior-b9ff76c9.npz \
      --arm-checkpoint "/root/claude-$model.pt" --mode policy \
      --control matched-continuation --guided-tricks 1 --continuation-tricks 1 \
      --seed0 618092026 --clusters 13 --workers 1 "${extra[@]}" \
      --out "$out/$model-$horizon" >> "$out/$model-$horizon.log" 2>&1
  done
done
echo 'CONTINUATION QUEUE DONE'
