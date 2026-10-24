#!/bin/bash
# Run one bound diagnostic; admission belongs to the reviewer-owned RELEASE.
set -euo pipefail
R=/root/codex-s61-continuation
PY=/root/gen-hybrid/server/.venv/bin/python
HEAD=7adee3e7b83d97975ef0a2399582b1131db62092
OUT=/root/codex-s61-continuation-output
HOLD=/root/codex-s61-continuation.HOLD
RELEASE=/root/codex-s61-continuation.RELEASE
LOCK=/root/.claude-host.lock
SELF_SHA=$(sha256sum "$0" | cut -d' ' -f1)
POLICY=pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0
refuse() { echo "REFUSING: $*" >&2; exit 3; }
absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
verify() {
  [ "$(git -C "$R" rev-parse HEAD)" = "$HEAD" ] || refuse source-head
  [ -z "$(git -C "$R" status --porcelain --untracked-files=no)" ] || refuse dirty-source
  absent "$OUT" || refuse existing-output
  [ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -ge 4194304 ] || refuse memory
  command -v timeout >/dev/null
  [ -x "$PY" ] || refuse interpreter
  (cd "$R" && sha256sum -c <<'SUMS'
ae09afa06a1f99879a82ef54fdba34f1539ab033bfb24ed2dbb5d75aa90f435a  /root/codex-s61-prefix-output-r2/prefix.json
cee55eace26fa088cd6824df7683599dc378f3b5a71a885fedce98bea5e60dbf  fly.toml
491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670  /root/models/smv3out-491ee4bf.npz
763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343  /root/models/s17long-e2-763b5e05.npz
ae256c79aa37869ab161d2c8fd029beb24f98d5bf995183d01958d7521045ddf  server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so
f5dc9ddbdea32c982e46a50b54f79b6486fa2b7df4e92276addc1a9bc1dad41e  server/shengji/ai/_cwv_math.cpython-314-x86_64-linux-gnu.so
a6505caf8f41279b2c0478a75116a796c8b01ef5b38b6ee949a8378634a00ad4  server/shengji/ai/_endgame_fast.cpython-314-x86_64-linux-gnu.so
SUMS
  ) || refuse input-drift
  (cd "$R/server" && SHENGJI_FAST=1 PYTHONPATH="$R/server" "$PY" -c 'from shengji.engine import fast; assert fast.HAVE_FAST and fast.activate()') || refuse compiled-engine
}
verify
if [ "${1:-}" = --dryrun ]; then
  absent "$LOCK" || refuse occupied-host
  echo 'DRYRUN PASS: one worker, two actions, 64 worlds, two tricks; 3600-second bound; no diagnostic run'
  exit 0
fi
absent "$HOLD" || refuse HOLD
[ -f "$RELEASE" ] && [ ! -L "$RELEASE" ] || refuse RELEASE
[ "$(tr -d '\n ' < "$RELEASE")" = "$SELF_SHA" ] || refuse release-sha
mkdir "$LOCK" || refuse occupied-host
printf 'codex-s61-continuation pid=%s sha=%s\n' "$$" "$SELF_SHA" > "$LOCK/owner"
cleanup() {
  rc=$?
  if [ -d "$OUT" ]; then printf 'TERMINAL rc=%s\n' "$rc" >> "$OUT/status"; fi
  rm "$LOCK/owner"
  rmdir "$LOCK"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
absent "$HOLD" || refuse HOLD
[ "$(sha256sum "$0" | cut -d' ' -f1)" = "$SELF_SHA" ] || refuse launcher-drift
mkdir "$OUT"
printf 'START source=%s seed=641024\n' "$HEAD" > "$OUT/status"
export SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd "$R/server"
timeout --signal=TERM --kill-after=15 3600 "$PY" -I "$R/tools/s61replay/run_saved.py" \
  --prefix /root/codex-s61-prefix-output-r2/prefix.json \
  --prefix-sha ae09afa06a1f99879a82ef54fdba34f1539ab033bfb24ed2dbb5d75aa90f435a \
  --recipe "$R/fly.toml" --recipe-sha cee55eace26fa088cd6824df7683599dc378f3b5a71a885fedce98bea5e60dbf \
  --play-package /root/models/smv3out-491ee4bf.npz \
  --belief-package /root/models/s17long-e2-763b5e05.npz \
  --policy-identity "$POLICY" --seed 641024 --output "$OUT/result.json" > "$OUT/console.log" 2>&1
(cd "$OUT" && sha256sum result.json > SHA256SUMS)
echo 'LANE DONE' >> "$OUT/status"
