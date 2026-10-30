#!/bin/bash
set -uo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export LANE_FUNCTIONS_ONLY=1
source "$HERE/claude_s61dev_cloud.final.sh" || exit 3
unset LANE_FUNCTIONS_ONLY
OUT=/root/codex-s61dev-rehearsal-20261022
S=$OUT/status
RELEASE=/root/codex-s61dev-rehearsal.RELEASE
HOLD=/root/claude_s61dev.HOLD
WAIT_START=$SECONDS
E2PATH=/root/models/s17long-e2-763b5e05.npz
PATH_MAP="/data/models/s17long-e2-763b5e05.npz=$E2PATH"
hold_guard
test "$(readlink -f "$HERE/exploit_duel_s61.py")" = "$(readlink -f "$DUEL")" || die 'rehearsal import differs from pinned duel path'
test "$(readlink -f "$HERE/hypotheses.py")" = "$(readlink -f "$HYP")" || die 'rehearsal import differs from pinned hypothesis path'
verify_tree; check_packages; check_toml; check_compiled; check_names; mem_guard
test ! -e "$HOSTLOCK" && test ! -e "$LEGACY" && test ! -e "$DATAGEN" || die 'host occupied'
mkdir "$OUT" || die 'rehearsal root already exists or cannot be created'
STATUS_OWNED=1
take_host_lock
wait_legacy_peers
take_legacy_marker
install_lane_traps
say 'resource rehearsal: 14 workers, 14 reserved smoke/bench deals, 1800-second limit; no scientific seeds'
(cd "$R/server" && exec setsid env \
  -u SHENGJI_PV_ENCODE_PREFIX_CACHE -u SHENGJI_PV_LEAF_GREEDY_STREAM -u SHENGJI_PV_SINGLE_CANDIDATE_FAST \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  PYTHONPATH="$R/server" FIND_GAPS_SERVER="$R/server" \
  FIND_GAPS_PKG=/root/models/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="$PATH_MAP" \
  timeout --signal=TERM --kill-after=10 1800 "$PY" -B "$HERE/cloud_rehearsal.py" \
  "$HERE/claude_s61dev_cloud.final.sh" "$OUT/metrics.jsonl" > "$OUT/progress.log" 2> "$OUT/stderr.log") &
RUN_PGID=$!
say "rehearsal pid/pgid $RUN_PGID"
rc=0
wait "$RUN_PGID" || rc=$?
run_cleanup
say "REHEARSAL END rc=$rc"
exit "$rc"
