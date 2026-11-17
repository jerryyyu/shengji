#!/bin/bash
set -u
P=$1; O=$2; N=$3
cd /Users/jerryyu/Projects/shengji-wt/claude-pl1-r51/server
for i in $(seq 0 $((N-1))); do
  nice -n 10 /Users/jerryyu/Projects/shengji/server/.venv/bin/python -B /Users/jerryyu/.claude/jobs/d0498cda/tmp/pl1/scripts/draw.py "$P" "$O" $i $N > "$O/worker-$i.log" 2>&1 &
done
wait
echo ALL DONE
