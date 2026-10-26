#!/bin/bash
# s69r2 local check of the launcher's check_names python block (this Mac): the block is cut out of claude_s69_cloud.sh byte for byte (between
# "<<'PY'" and "PY") and run on the Mac R48 tree d33bfd70 (compiled extensions built in place) with the Mac copies of smv3out and S58 in
# place of the cloud paths (the one literal '/root/models/smv3out-491ee4bf.npz' rewritten; a path is in no digest; the names must equal
# the launcher's).  Writes nothing but stdout.   Usage: bash local_blocks_check.sh [launcher] > local_blocks_check.out
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/tools/s69r2
W=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
S58=/Users/jerryyu/.claude/jobs/d0498cda/tmp/s69pkg/s58-e6-42444515.npz
PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz
L=${1:-$H/claude_s69r2_cloud.sh}
echo "launcher $(shasum -a 256 $L | cut -c1-64)"
BLOCK=$(awk "/<<'PY'\$/{f=1;next} /^PY\$/{f=0} f" $L)
echo "block sha256 $(printf '%s\n' "$BLOCK" | shasum -a 256 | cut -c1-64) ($(printf '%s\n' "$BLOCK" | wc -l | tr -d ' ') lines)"
LANE_FUNCTIONS_ONLY=1 source $L
cd $W && FIND_GAPS_SERVER=$W FIND_GAPS_PKG=$PKG FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=$W \
  $PY -B - "$H/exploit_duel_s61.py" "$COMBO_NAME" "$CAND_NAME" "$EX_ENV" "$S58" <<< "$(printf '%s\n' "$BLOCK" | sed "s#'/root/models/smv3out-491ee4bf.npz'#'$PKG'#")"
echo "rc=$?"
