#!/usr/bin/env bash
# Scheduling-only successor to the held launcher; never stops a live job.
# Launch in a retained systemd unit (no --collect), KillMode=control-group,
# RuntimeMaxSec bounded by the absolute deadline below, TimeoutStopSec=30.
# The outer cgroup deadline, not timeout alone, must contain all descendants.
set -euo pipefail
mode=${1:---check}
[[ "$mode" == --check || "$mode" == --launch ]] || exit 2
old=codex-puct-gameplay-recovery-20260916.service
state=$(systemctl show "$old" -p ActiveState --value)
[[ "$state" == inactive || "$state" == failed ]] || {
  echo "HOLD old launcher must be retired after M1 seals: $state"; exit 3;
}
root=/root/codex-puct-boundary-20260916
out=/root/codex-puct-gameplay-20260916
py=/root/gen-hybrid/server/.venv/bin/python
# Retain the original service's absolute 12-hour deadline, not a fresh 12h.
deadline=$(date -u -d '2026-09-16 15:32:38 UTC' +%s)
(( $(date +%s) < deadline )) || { echo 'HOLD original deadline elapsed'; exit 7; }
[[ $(git -C "$root" rev-parse HEAD) == b798bc4870eacf59c5c28804dcb182b9edde45a1 ]] || exit 4
git -C "$root" diff --quiet HEAD -- server
"$py" - <<'PY'
import hashlib
import json
from pathlib import Path
for sweeps, depth in ((8,8),(32,8),(128,8),(128,16)):
    p = Path(f'/root/codex-puct-gameplay-20260916/M1-s{sweeps}-d{depth}/summary.json')
    x = json.loads(p.read_text())
    assert x['complete'] and x['completed_clusters'] == x['requested_clusters'] == 13, p
    assert x['rounds'] == 26 and x['seed0'] == 617092026, p
    assert x['bury_accounting_complete'] and not x.get('problems') and not x.get('refused'), p
    c = x['config']; r = c['release27_search']
    assert (r['mode'],r['sweeps'],r['depth']) == ('puct',sweeps,depth), p
    assert r['arm_checkpoint'] == '/root/claude-M1.pt', p
    assert c['checkpoint_sha256'] == r['arm_sha256'] == '3cb9cd62a083736e3b41712baabaa86398b74f0e303a4a15290ec1cd9585612d', p
    assert c['baseline_asset_sha256'] == '12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f', p
    assert c['prior_asset_sha256'] == 'b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c', p
    assert c['decision_deadline']['seconds'] == 300, p
for path, sha in {
    '/root/claude-G1.pt': '1bcbb47f253a7151df08749b31868a1d1608fbf3e578a2dc4d24f232b1e2e648',
    '/root/codex-release27-m1-12ce4415.npz': '12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f',
    '/root/codex-release27-prior-b9ff76c9.npz': 'b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c',
}.items():
    with open(path,'rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest() == sha, path
PY
[[ ! -e /root/.claude-lane.lock ]] || { echo 'HOLD lane reserved'; exit 5; }
if pgrep -f '[c]wv_screen_queue|[c]wv_shortlist_screen|[t]rajectory_cli|[c]wv_release27_screen.py' >/dev/null; then
  echo 'HOLD occupied host'; exit 6
fi
if [[ "$mode" == --check ]]; then
  echo 'READY: four frozen G1 configurations, sequential, two workers each'
  exit 0
fi
mkdir /root/.claude-lane.lock
trap 'rmdir /root/.claude-lane.lock' EXIT
export PYTHONPATH="$root/server" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1
for pair in 8:8 32:8 128:8 128:16; do
  sweeps=${pair%:*}; depth=${pair#*:}
  name="G1-s$sweeps-d$depth"
  remaining=$((deadline - $(date +%s)))
  (( remaining > 0 )) || exit 7
  timeout --signal=TERM --kill-after=30s "$remaining" \
    "$py" "$root/server/scripts/cwv_release27_screen.py" \
    --baseline-checkpoint /root/codex-release27-m1-12ce4415.npz \
    --prior-checkpoint /root/codex-release27-prior-b9ff76c9.npz \
    --arm-checkpoint /root/claude-G1.pt --mode puct \
    --seed0 617092026 --clusters 13 --workers 2 --sweeps "$sweeps" --depth "$depth" \
    --out "$out/$name" >> "$out/$name.log" 2>&1
done
echo 'G1 SEQUENTIAL LADDER DONE'
