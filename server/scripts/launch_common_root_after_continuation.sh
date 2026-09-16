#!/usr/bin/env bash
# Named research packet only. Default checks; --launch requires independently
# confirmed review, seed allocation and host reservation. Not an auto-waiter.
set -euo pipefail
mode=${1:---check}
[[ "$mode" == --check || "$mode" == --launch ]] || exit 2
SECONDS=0
predecessor=codex-policy-continuation-20260916.service
load=$(systemctl show "$predecessor" -p LoadState --value)
state=$(systemctl show "$predecessor" -p ActiveState --value)
sub=$(systemctl show "$predecessor" -p SubState --value)
pid=$(systemctl show "$predecessor" -p MainPID --value)
result=$(systemctl show "$predecessor" -p Result --value)
invocation=$(systemctl show "$predecessor" -p InvocationID --value)
[[ "$load" == loaded && "$state" == active && "$sub" == exited &&
   "$pid" == 0 && "$result" == success &&
   "$invocation" == 70384b5d5002458aace414dc0a795173 ]] || {
  echo "HOLD continuation: $load/$state/$sub pid=$pid result=$result"; exit 3;
}
root=/root/codex-common-root-20260916
out=/root/codex-common-root-gameplay-20260916
py=/root/gen-hybrid/server/.venv/bin/python
[[ $(git -C "$root" rev-parse HEAD) == dd01f75f000b9cda735a51d86d257015868e7b9d ]] || exit 4
git -C "$root" diff --quiet HEAD -- server
"$py" - <<'PY'
import hashlib
import json
from pathlib import Path
models = {
    'M1': '3cb9cd62a083736e3b41712baabaa86398b74f0e303a4a15290ec1cd9585612d',
    'G1': '1bcbb47f253a7151df08749b31868a1d1608fbf3e578a2dc4d24f232b1e2e648',
}
baseline = '12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f'
prior = 'b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c'
for model, sha in models.items():
    for horizon in ('k1', 'terminal'):
        path = Path('/root/codex-policy-continuation-gameplay-20260916') / f'{model}-{horizon}' / 'summary.json'
        x = json.loads(path.read_text())
        assert x['complete'] and x['completed_clusters'] == x['requested_clusters'] == 13, path
        assert x['rounds'] == 26 and x['seed0'] == 618092026, path
        assert not x.get('problems') and not x.get('refused'), path
        assert x['bury_accounting_complete'], path
        c = x['config']; r = c['release27_search']
        assert r['mode'] == 'policy' and r['control'] == 'matched-continuation', path
        assert r['guided_tricks'] == 1, path
        assert r['continuation_tricks'] == (1 if horizon == 'k1' else None), path
        assert c['decision_deadline']['seconds'] == 300, path
        assert c['checkpoint_sha256'] == r['arm_sha256'] == sha, path
        assert c['baseline_asset_sha256'] == baseline and c['prior_asset_sha256'] == prior, path
assets = {f'/root/claude-{model}.pt': sha for model, sha in models.items()}
assets.update({'/root/codex-release27-m1-12ce4415.npz': baseline,
               '/root/codex-release27-prior-b9ff76c9.npz': prior})
for path, sha in assets.items():
    with open(path, 'rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == sha, path
PY
# This snapshot must be refreshed from canonical main and peer reservations
# reconciled at packet review; its existence alone does not allocate seeds.
registry=/root/codex-common-root-seed-registry.json
[[ -f "$registry" ]] || { echo 'HOLD missing reviewed seed registry'; exit 5; }
"$py" "$root/server/scripts/seed_windows.py" --registry "$registry" check 624092026 13 --purpose screen
[[ ! -e /root/.claude-lane.lock ]] || { echo 'HOLD lane reserved'; exit 6; }
if pgrep -f '[c]wv_screen_queue|[c]wv_shortlist_screen|[t]rajectory_cli|[c]wv_release27_screen.py' >/dev/null; then
  echo 'HOLD occupied host'; exit 7
fi
if [[ "$mode" == --check ]]; then
  echo 'READY; independent packet/seed/reservation confirmation still required'
  exit 0
fi
mkdir /root/.claude-lane.lock
trap 'rmdir /root/.claude-lane.lock' EXIT
export PYTHONPATH="$root/server" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1
mkdir -p "$out"
for model in M1 G1; do
  for warmup in 0 4; do
    remaining=$((86400 - SECONDS))
    [[ "$remaining" -gt 0 ]] || { echo 'STOP aggregate 24h ceiling'; exit 124; }
    timeout --signal=TERM --kill-after=30s "$remaining" \
      "$py" "$root/server/scripts/cwv_release27_screen.py" \
      --baseline-checkpoint /root/codex-release27-m1-12ce4415.npz \
      --prior-checkpoint /root/codex-release27-prior-b9ff76c9.npz \
      --arm-checkpoint "/root/claude-$model.pt" --mode puct \
      --sweeps 32 --depth 8 --reuse-root-actions --root-warmup-top "$warmup" \
      --seed0 624092026 --clusters 13 --workers 1 \
      --out "$out/$model-warmup$warmup" >> "$out/$model-warmup$warmup.log" 2>&1
  done
done
echo 'COMMON ROOT QUEUE DONE'
