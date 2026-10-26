#!/bin/bash
# s67c: the reader e2e fixture and the adversarial battery, detached (each ~15-25 min on this Mac), outputs beside this script
set -u
H=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
cd /private/tmp
( /usr/bin/time -l nice -n 15 $PY -B $H/test_s67c_read.py $H/s67c_read.py > $H/test_s67c_read.out 2> $H/test_s67c_read.err; echo "rc=$?" >> $H/test_s67c_read.out ) &
( /usr/bin/time -l nice -n 15 $PY -B $H/battery_s67c_adapter.py $H/s67c_read.py $H/test_s67c_read.py --out $H/battery_s67c.out > $H/battery_s67c.log 2> $H/battery_s67c.err; echo $? > $H/battery_s67c.rc ) &
wait
