#!/bin/bash
# s68dev local check of the launcher's check_names python block (this Mac): the block is cut out of claude_s68dev_perf.sh byte for byte
# (between "<<'PY'" and "PY") and run on the Mac candidate tree (claude-s68-cand at the launcher's TREE_HEAD_FULL, compiled) with the Mac
# copy of S58 in place of the perf path (a path is in no digest; the names must equal arm_spec's) and the Mac smv3out path in place of
# /root/models'.  The specs string is built as check_names builds it (arm, name, the arm_env words joined by commas).  Writes nothing but
# stdout.  = s67c's local_blocks_check.sh with the lane, tree, adapter, specs form and arguments changed.
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s68-combo/tools/s68dev
W=/Users/jerryyu/Projects/shengji-wt/claude-s68-cand/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
S58=/private/tmp/r48pkg/s58-e6-42444515.npz
L=${1:-$H/claude_s68dev_perf.sh}; AD=${2:-$H/s66_sc8_adapter.py}   # the adapter the block runs through (the staged-layout test passes the COPIED one)
LANE_FUNCTIONS_ONLY=1 source $L
[ "$(git -C $W rev-parse HEAD)" = "$TREE_HEAD_FULL" ] || { echo "tree $W is not $TREE_HEAD_FULL"; exit 3; }
echo "launcher $(shasum -a 256 $L | cut -c1-64); tree $TREE_HEAD_FULL; adapter $AD $(shasum -a 256 $AD | cut -c1-16)"
BLOCK=$(awk "/<<'PY'\$/{f=1;next} /^PY\$/{f=0} f" $L)
echo "block sha256 $(printf '%s\n' "$BLOCK" | shasum -a 256 | cut -c1-64) ($(printf '%s\n' "$BLOCK" | wc -l | tr -d ' ') lines)"
specs=
for arm in $ARMS; do sp=$(arm_spec "$arm"); read -r s0 nm <<< "$sp"; ew=$(arm_env "$arm"); specs="$specs$arm $nm ${ew// /,};"; done
cd $W && FIND_GAPS_SERVER=$W FIND_GAPS_PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=$W \
  $PY -B - "$AD" "$COMBO_NAME" "$S58" "$specs" "$CAND_SHA" <<< "$(printf '%s\n' "$BLOCK" | sed "s#'/root/models/smv3out-491ee4bf.npz'#'/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz'#")"
rc=$?; echo "rc=$rc"; exit $rc
