#!/bin/bash
# s69 local smoke (this Mac, throwaway window 311970000..311970003): the lane's child arguments (the nine --exploiter-env overrides, r2 plan,
# --arm identity) on the local R48 tree d33bfd70 (compiled extensions built in place), 4 workers; writes smoke/duel.jsonl only.
set -u
W=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam; H=$W/tools/s69
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
S58=/Users/jerryyu/.claude/jobs/d0498cda/tmp/s69pkg/s58-e6-42444515.npz
cd $W/server || exit 3
[ ! -e $H/smoke/duel.jsonl ] || { echo "REFUSING: smoke output exists"; exit 3; }
env SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONPATH=$W/server \
  FIND_GAPS_SERVER=$W/server FIND_GAPS_PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  /usr/bin/time -l nice -n 10 $PY -B $H/exploit_duel_s61.py --arm identity --seed0 311970000 --deals 4 --workers 4 --round-plan r2 --out $H/smoke/duel.jsonl \
  --exploiter-env SHENGJI_PV_WORLDS=256 --exploiter-env SHENGJI_PV_CANDIDATES=32 --exploiter-env SHENGJI_PV_EXACT_DEEP_CARDS=8 --exploiter-env SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=8 --exploiter-env SHENGJI_PV_EXACT_LEAD_MAX_SECONDS=9.0 --exploiter-env SHENGJI_PV_EXACT_DEEP_MAX_NODES=200000000 --exploiter-env SHENGJI_PV_EXACT_FOLLOW_MAX_NODES=200000000 --exploiter-env SHENGJI_PV_SERVING_BUDGET_SECONDS=60 --exploiter-env SHENGJI_PV_LEAF_GREEDY_DEADLINE= \
  > $H/smoke/duel.stdout 2> $H/smoke/duel.stderr
echo "rc=$?"
