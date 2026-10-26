#!/bin/bash
# s68dev: the reader's end-to-end test once per fixture arm and the adversarial battery once per arm, in parallel, each to its own .out
# with a trailing rc= line (the battery's table goes to battery_s68dev.<arm>.out via --out).  Usage: bash run_long_tests.sh
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s68-combo/tools/s68dev; PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
cd /private/tmp || exit 3
for a in b a; do
  ( nice -n 15 $PY -u -B $H/test_s68dev_read.py $H/s68dev_read.py $a > $H/test_s68dev_read.$a.out 2>&1; echo "rc=$?" >> $H/test_s68dev_read.$a.out ) &
  ( rm -f $H/battery_s68dev.$a.out; nice -n 15 $PY -u -B $H/battery_s68dev_adapter.py $H/s68dev_read.py $H/test_s68dev_read.py $a --out $H/battery_s68dev.$a.out > $H/battery_s68dev.$a.log 2> $H/battery_s68dev.$a.err; echo "rc=$?" > $H/battery_s68dev.$a.rc ) &
done
wait
echo "long tests done"
