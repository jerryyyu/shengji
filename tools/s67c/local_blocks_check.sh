#!/bin/bash
# s67c local check of the launcher's check_names python block (this Mac): the block is cut out of claude_s67c_perf.sh byte for byte
# (between "<<'PY'" and "PY") and run on the Mac 8a50fe8a tree (claude-s67, compiled) with the Mac copy of S58 in place of the perf path
# (a path is in no digest; the names must equal arm_spec's) and the Mac smv3out path in place of /root/models'.  Writes nothing but stdout.
# = s66b's local_blocks_check.sh with the lane, tree and adapter changed and the base-module sha passed as the block's sixth argument.
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c
W=/Users/jerryyu/Projects/shengji-wt/claude-s67/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
S58=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/r47_redteam/pkg/s58-e6-42444515.npz
L=${1:-$H/claude_s67c_perf.sh}
[ "$(git -C $W rev-parse HEAD)" = "8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f" ] || { echo "tree $W is not 8a50fe8a"; exit 3; }
echo "launcher $(shasum -a 256 $L | cut -c1-64)"
BLOCK=$(awk "/<<'PY'\$/{f=1;next} /^PY\$/{f=0} f" $L)
echo "block sha256 $(printf '%s\n' "$BLOCK" | shasum -a 256 | cut -c1-64) ($(printf '%s\n' "$BLOCK" | wc -l | tr -d ' ') lines)"
LANE_FUNCTIONS_ONLY=1 source $L
specs=
for arm in $ARMS; do sp=$(arm_spec "$arm"); read -r s0 nm <<< "$sp"; specs="$specs$arm $nm;"; done
cd $W && FIND_GAPS_SERVER=$W FIND_GAPS_PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=$W \
  $PY -B - "$H/s67_sc8p_adapter.py" "$COMBO_NAME" "$S58" "$specs" "$CAND_SHA" "$BASE_SHA" <<< "$(printf '%s\n' "$BLOCK" | sed "s#'/root/models/smv3out-491ee4bf.npz'#'/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz'#")"
echo "rc=$?"
