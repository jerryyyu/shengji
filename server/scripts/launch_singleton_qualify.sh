#!/bin/bash
# Run one bound diagnostic; admission belongs to the reviewer-owned RELEASE.
set -euo pipefail
R=/root/codex-singleton-qualify
PY=/root/gen-hybrid/server/.venv/bin/python
HEAD=eb0975da0d47271c3bac5c23b1cb004e21819220
OUT=/root/codex-singleton-qualify-output
HOLD=/root/codex-singleton-qualify.HOLD
RELEASE=/root/codex-singleton-qualify.RELEASE
LOCK=/root/.claude-host.lock
SELF_SHA=$(sha256sum "$0" | cut -d' ' -f1)
refuse() { echo "REFUSING: $*" >&2; exit 3; }
absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
verify() {
  [ "$(git -C "$R" rev-parse HEAD)" = "$HEAD" ] || refuse source-head
  [ -z "$(git -C "$R" status --porcelain)" ] || refuse dirty-source
  absent "$OUT" || refuse existing-output
  [ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -ge 4194304 ] || refuse memory
  command -v timeout >/dev/null
  [ -x "$PY" ] || refuse interpreter
  (cd "$R" && sha256sum -c <<'SUMS'
1fcb2fbfe386a0df562e292d7b89c9acdca39f3c87332d4be36eed25834a2056  fly.toml
491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670  /root/models/smv3out-491ee4bf.npz
424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e  /root/codex-r48-assets/s58-e6-42444515.npz
befa81f4d3cb87a27fbd0c284c51112c09901b7f735fb38a70c4afd520cab51e  server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so
ea75715e63e16f4d4355b5ad145895bd716da6d1c78c36a61b0eff7d09f61733  server/shengji/ai/_cwv_math.cpython-314-x86_64-linux-gnu.so
7b49a90c3dde1d5b00738ef85b884e4870c894279520e84b847a6ed32ff35d19  server/shengji/ai/_endgame_fast.cpython-314-x86_64-linux-gnu.so
SUMS
  ) || refuse input-drift
  (cd "$R/server" && SHENGJI_FAST=1 PYTHONPATH="$R/server" "$PY" -c 'from shengji.engine import fast; assert fast.HAVE_FAST and fast.activate()') || refuse compiled-engine
}
verify
if [ "${1:-}" = --dryrun ]; then
  absent "$LOCK" || refuse occupied-host
  echo 'DRYRUN PASS: one worker, 52 fixed fixtures per arm, 600-second bound; no qualification run'
  exit 0
fi
absent "$HOLD" || refuse HOLD
absent /root/.claude-screen.lock || refuse legacy-screen
absent /root/.claude-datagen.lock || refuse data-generation
grep -Eq '^[0-9TZ:-]+ h1a DEV output sealed \(.*\); LANE DONE$' /root/claude_h1a_screen.status \
  && ! grep -Eq ' (ABORT|REFUSING): ' /root/claude_h1a_screen.status || refuse predecessor-not-done
if pgrep -f '[s]earch_audit_probe_v5.py' >/dev/null; then refuse live-probe; fi
[ -f "$RELEASE" ] && [ ! -L "$RELEASE" ] || refuse RELEASE
[ "$(tr -d '\n ' < "$RELEASE")" = "$SELF_SHA" ] || refuse release-sha
mkdir "$LOCK" || refuse occupied-host
printf 'codex-singleton-qualify pid=%s sha=%s\n' "$$" "$SELF_SHA" > "$LOCK/owner"
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
printf 'START source=%s fixtures=52 arms=2\n' "$HEAD" > "$OUT/status"
export SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd "$R/server"
timeout --signal=TERM --kill-after=15 600 "$PY" -I -c 'import runpy,sys; sys.path.insert(0,"/root/codex-singleton-qualify/server"); runpy.run_module("scripts.qualify_singleton_challenger",run_name="__main__")' \
  --recipe "$R/fly.toml" --recipe-sha 1fcb2fbfe386a0df562e292d7b89c9acdca39f3c87332d4be36eed25834a2056 \
  --play-package /root/models/smv3out-491ee4bf.npz \
  --belief-package /root/codex-r48-assets/s58-e6-42444515.npz \
  --out "$OUT/qualification.jsonl" > "$OUT/console.log" 2>&1
(cd "$OUT" && sha256sum qualification.jsonl > SHA256SUMS)
echo 'LANE DONE' >> "$OUT/status"
