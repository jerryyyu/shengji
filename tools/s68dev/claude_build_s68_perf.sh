#!/bin/bash
# BUILD claude-s68-src-8b6ead10 on PERF (shengji-perf): a fresh pinned clone of 8b6ead101108fac9aaf9a7c81026fd04f89e6bc7, the S68 candidate tree
# (branch claude/s68-cand: main d33bfd70 + claude/s68-bwc (the capacity-aware belief draw, SHENGJI_PV_BELIEF_CAPACITY, off by default) +
# #1156 at 39d514cc (the singleton challenger's opt-in serving registry) merged; fly.toml = main's) -- the perf tree for the s68dev DEV
# arms (tools/s68dev/): the S68 combo candidate vs R48 as served, both sides from this tree.  NOT main (an unmerged branch commit):
# ALLOW_UNMERGED=1 is REQUIRED.
# = s67c's build script (54e29983, BUILD_RC=0 on perf 2026-10-26) with this header, the tree name, the head, the script name and
# the date; nothing else changed.
# No lock: it clones and compiles only (nice 19; it may run beside a lane).
# NEVER destructive: refuses if the tree, its .head or an in-progress clone exists and removes nothing.
#
# Usage, ON the host:
#   HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 DRYRUN=1 bash /root/claude_build_s68_perf.sh     # preflight only, clones nothing
#   HEAD=8b6ead101108fac9aaf9a7c81026fd04f89e6bc7 ALLOW_UNMERGED=1 nohup nice -n 19 bash /root/claude_build_s68_perf.sh > /root/claude-s68-src-8b6ead10-build.nohup 2>&1 &
# Prepared 2026-10-26 UTC (s68dev).
set -u
T=/root/claude-s68-src-8b6ead10; LOG=$T-build.log; HEADF=$T.head; WIP=$T.clone-in-progress
PEER=/root/claude-main-55            # the newest claude-main-N on this host (the R48 tree); its origin must be the one cloned here
ORIGIN=https://github.com/jerryyyu/shengji.git       # ssh shengji-cloud 'git -C /root/claude-main-15 remote -v' on 2026-10-01
PY=/root/gen-hybrid/server/.venv/bin/python
HEAD=${HEAD:-}
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSING: HEAD must be the full 40-hex sha (got '${HEAD}')"; exit 3; }
[ "$HEAD" = "8b6ead101108fac9aaf9a7c81026fd04f89e6bc7" ] || { echo "REFUSING: this build script is pinned to 8b6ead101108fac9aaf9a7c81026fd04f89e6bc7"; exit 3; }
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
