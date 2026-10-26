#!/bin/bash
# s67c local smoke (this Mac, M4, nice 10, one worker, sequential): the lane's exact producer path -- the adapter s67_sc8p_adapter.py
# wrapping exploit_duel_s61.py (b15d292f, verbatim) -- on the 8a50fe8a tree (claude-s67, compiled; the pair / tractor challenger),
# defender = fly.toml's R48 (this Mac's S58 copy via the path map), exploiter = R48 + the pair / tractor challenger (--exploiter-env
# S66_EXPLOITER=sc8p); r2 plan, 2 throwaway deals 243160000..243160001 (registry-checked, below every lane block).  Plus the premise
# control r48 (no override: every margin must be exactly 0, through the adapter, which then delegates to the harness's variant_factory).
# The latency switches come from fly.toml through served_env on both sides; the outer env carries none.  Writes smoke/<arm>.jsonl, .log
# (rc), .time.  = s66dev's smoke/run_smoke.sh with the tree, adapter, sentinel and seed window changed.
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c
W=/Users/jerryyu/Projects/shengji-wt/claude-s67/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
PKG=/Users/jerryyu/Projects/shengji-wt/pkg
S58=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/r47_redteam/pkg/s58-e6-42444515.npz
env | grep -q "SHENGJI_\|S66_" && { echo "a SHENGJI_ / S66_ variable is in the outer env"; exit 3; }
[ "$(git -C $W rev-parse HEAD)" = "8a50fe8a4a2b1b3b4142693fb4c0298920a2de4f" ] || { echo "tree $W is not 8a50fe8a"; exit 3; }
cd $W
for arm in ${ARMS:-sc8p r48}; do
  case $arm in
    sc8p) EENV=(--exploiter-env S66_EXPLOITER=sc8p);;
    r48) EENV=();;
  esac
  [ ! -e $H/smoke/$arm.jsonl ] || { echo "smoke/$arm.jsonl exists"; exit 3; }
  FIND_GAPS_SERVER=$W FIND_GAPS_PKG=$PKG/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=$W \
    /usr/bin/time -l nice -n 10 $PY -B $H/s67_sc8p_adapter.py --arm identity --seed0 243160000 --deals 2 --workers 1 \
    --round-plan r2 ${EENV[@]+"${EENV[@]}"} --out $H/smoke/$arm.jsonl > $H/smoke/$arm.log 2> $H/smoke/$arm.time
  echo "rc=$?" >> $H/smoke/$arm.log
done
