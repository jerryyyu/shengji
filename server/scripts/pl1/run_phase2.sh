#!/bin/bash
# PL1 phase 2: 3 S136 workers (PL1 tree) + 1 FT1 worker (R51 tree), one thread each, nice 10
set -u
R=/Users/jerryyu/.claude/jobs/d0498cda/tmp/pl1
P=/Users/jerryyu/shengji-archive/2026-11-06-s113-belief-teacher-b1a/data/points.jsonl
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
export OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
mkdir -p $R/phase2/s136 $R/phase2/ft1
cd /Users/jerryyu/Projects/shengji-wt/claude-pl1/server
for i in 0 1 2; do
  nice -n 10 $PY -B $R/scripts/score_s136.py $P $R/phase1/main/cands $R/phase2/s136 $i 3 512 > $R/phase2/s136/worker-$i.log 2>&1 &
done
cd /Users/jerryyu/Projects/shengji-wt/claude-pl1-r51/server
nice -n 10 $PY -B $R/scripts/score_ft1.py $P $R/phase1/main/cands $R/phase2/ft1 0 1 512 > $R/phase2/ft1/worker-0.log 2>&1 &
wait
echo PHASE2 DONE
