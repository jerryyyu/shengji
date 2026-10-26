#!/bin/bash
# BUILD claude-sc8p-src-8a50fe8a on PERF (shengji-perf): a fresh pinned clone of 8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f, the pair / tractor
# challenger's execution source (claude/s67-pair-challenger: PR #1153's eb0975da + server/shengji/eval/pair_challenger.py, the singleton
# challenger refactored into a base class, and tests; fly.toml and server/shengji/{train,ai,engine} byte-identical to 0c1e9965 =
# /root/claude-main-55, release 48's served code) -- the perf tree for the s67c DEV duel (tools/s67c/): R48 + the pair / tractor
# challenger vs R48 as served, both sides from this tree.  NOT main (an unmerged branch commit): ALLOW_UNMERGED=1 is REQUIRED.
# = s66dev's claude_build_sc8_perf.sh (the script that built /root/claude-sc8-src-eb0975da on perf 2026-10-25, BUILD_RC=0) with this
# header, the tree name, the head, the script name and the date; nothing else changed.
# No lock: it clones and compiles only (nice 19; it may run beside a lane).
# NEVER destructive: refuses if the tree, its .head or an in-progress clone exists and removes nothing.
#
# Usage, ON the host:
#   HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_sc8p_perf.sh     # preflight only, clones nothing
#   HEAD=8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_sc8p_perf.sh > /root/claude-sc8p-src-8a50fe8a-build.nohup 2>&1 &
# Prepared 2026-10-26 UTC (s67c).
set -u
T=/root/claude-sc8p-src-8a50fe8a; LOG=$T-build.log; HEADF=$T.head; WIP=$T.clone-in-progress
PEER=/root/claude-main-55            # the newest claude-main-N on this host (the R48 tree); its origin must be the one cloned here
ORIGIN=https://github.com/jerryyyu/shengji.git       # ssh shengji-cloud 'git -C /root/claude-main-15 remote -v' on 2026-10-01
PY=/root/gen-hybrid/server/.venv/bin/python
HEAD=${HEAD:-}
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSING: HEAD must be the full 40-hex sha (got '${HEAD}')"; exit 3; }
[ "$HEAD" = "8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f" ] || { echo "REFUSING: this build script is pinned to 8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f"; exit 3; }
[ "${ALLOW_UNMERGED:-0}" = "1" ] || { echo "REFUSING: an unmerged branch head needs ALLOW_UNMERGED=1 (set it only for a sha-named DEV tree)"; exit 3; }
[ -e "$T" ] && { echo "REFUSING: $T exists (a DEV source tree is built once)"; exit 3; }
[ -e "$HEADF" ] && { echo "REFUSING: $HEADF exists"; exit 3; }
[ -e "$WIP" ] && { echo "REFUSING: $WIP exists (an earlier clone did not finish; inspect it by hand, this script removes nothing)"; exit 3; }
[ -x "$PY" ] || { echo "REFUSING: $PY missing"; exit 3; }
if [ -d "$PEER" ]; then
  peer_origin=$(git -C "$PEER" remote get-url origin 2>/dev/null)
  [ "$peer_origin" = "$ORIGIN" ] || { echo "REFUSING: $PEER origin is '$peer_origin', not $ORIGIN"; exit 3; }
else
  echo "REFUSING: peer tree $PEER missing on this host (the origin cross-check needs it)"; exit 3
fi
[ "${DRYRUN:-0}" = "1" ] && { echo "DRYRUN ok: would clone $ORIGIN at $HEAD into $T (via $WIP; peer $PEER origin matches), build with $PY, write $HEADF and BUILD_RC into $LOG"; exit 0; }
say () { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
say "build $T: HEAD=$HEAD origin=$ORIGIN (unmerged branch head, ALLOW_UNMERGED=1)"
git clone -q "$ORIGIN" "$WIP" || { say "BUILD_RC=3 (clone failed; whatever it left is at $WIP)"; exit 3; }
git -C "$WIP" fetch -q origin || { say "BUILD_RC=3 (fetch failed; clone left at $WIP)"; exit 3; }
git -C "$WIP" cat-file -e "$HEAD^{commit}" 2>/dev/null || { say "BUILD_RC=3 ($HEAD is not a commit on $ORIGIN; clone left at $WIP)"; exit 3; }
if ! git -C "$WIP" merge-base --is-ancestor "$HEAD" origin/main; then
  [ "${ALLOW_UNMERGED:-0}" = "1" ] || { say "BUILD_RC=3 ($HEAD is not on origin/main, so not a merged head; ALLOW_UNMERGED=1 overrides; clone left at $WIP)"; exit 3; }
  say "WARNING: $HEAD is not on origin/main (ALLOW_UNMERGED=1)"
fi
git -C "$WIP" checkout -q "$HEAD" || { say "BUILD_RC=3 (checkout failed; clone left at $WIP)"; exit 3; }
[ "$(git -C "$WIP" rev-parse HEAD)" = "$HEAD" ] || { say "BUILD_RC=3 (checked-out head is not $HEAD; clone left at $WIP)"; exit 3; }
mv "$WIP" "$T" || { say "BUILD_RC=3 (could not move $WIP to $T)"; exit 3; }
git -C "$T" rev-parse HEAD > "$HEADF"
say "checked out $(git -C "$T" rev-parse --short=8 HEAD) ($(git -C "$T" log -1 --format=%s | cut -c1-90)); head written to $HEADF"
cd "$T/server" || { say "BUILD_RC=3 (no server dir in $T)"; exit 3; }
"$PY" setup.py build_ext --inplace >> "$LOG" 2>&1; rc=$?
if [ $rc -eq 0 ] && [ ! -f shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so ]; then rc=4; say "build_ext exited 0 but the compiled engine is missing"; fi
for so in shengji/ai/_cwv_math.cpython-314-x86_64-linux-gnu.so shengji/ai/_endgame_fast.cpython-314-x86_64-linux-gnu.so; do
  if [ $rc -eq 0 ] && [ ! -f "$so" ]; then rc=4; say "build_ext exited 0 but $so is missing"; fi
done
if [ $rc -eq 0 ]; then
  for so in engine/_fast ai/_cwv_math ai/_endgame_fast; do say "ext $so $(sha256sum shengji/$so.cpython-314-x86_64-linux-gnu.so | cut -d' ' -f1)"; done
fi
echo "BUILD_RC=$rc" | tee -a "$LOG"
exit $rc
