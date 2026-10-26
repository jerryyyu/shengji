#!/bin/bash
# BUILD claude-main-56 on CLOUD (shengji-cloud): a fresh pinned clone of origin/main d33bfd70bb2f434368b7e83cdb5732cc791bd0ab (#1158) -- the
# cloud tree for the S69 red-team lane (tools/s69/): R48 as served (fly.toml SHENGJI_BOT ...-cd6dd3d2b02a; server/shengji/{ai,engine,train}
# byte-identical to 0c1e9965, the S63-S66 / M27 tree).  A MERGED head: no ALLOW_UNMERGED.  Body = /root/claude_build_main55_cloud.sh (cloud)
# with N=55 -> 56 and PEER claude-main-54 -> claude-main-55 (the newest claude-main-N on this host); nothing else changed.  Index 56 is
# unused on both cloud and perf (checked 2026-10-26).
# No lock: it clones and compiles only (nice 19).
# NEVER destructive: refuses if the tree, its .head or an in-progress clone exists and removes nothing.
#
# Usage, ON the host:
#   HEAD=d33bfd70bb2f434368b7e83cdb5732cc791bd0ab DRYRUN=1 bash /root/claude_build_main56_cloud.sh     # preflight only, clones nothing
#   HEAD=d33bfd70bb2f434368b7e83cdb5732cc791bd0ab nohup nice -n 19 bash /root/claude_build_main56_cloud.sh > /root/claude-main-56-build.nohup 2>&1 &
# Prepared 2026-10-26 UTC.
set -u
N=56; T=/root/claude-main-$N; LOG=$T-build.log; HEADF=$T.head; WIP=$T.clone-in-progress
PEER=/root/claude-main-55            # the newest claude-main-N on this host; its origin must be the one cloned here
ORIGIN=https://github.com/jerryyyu/shengji.git       # ssh shengji-cloud 'git -C /root/claude-main-15 remote -v' on 2026-10-01
PY=/root/gen-hybrid/server/.venv/bin/python
HEAD=${HEAD:-}
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSING: HEAD must be the full 40-hex merged sha (got '${HEAD}')"; exit 3; }
[ -e "$T" ] && { echo "REFUSING: $T exists (a claude-main-N tree is built once; use the next N)"; exit 3; }
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
say "build claude-main-$N: HEAD=$HEAD origin=$ORIGIN"
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
echo "BUILD_RC=$rc" | tee -a "$LOG"
exit $rc
