#!/bin/bash
# s69r2 registry check (read only): seed_windows.py check (--purpose screen and other; the tool has no 'dev' purpose) for the 600-deal s69r2 lane
# window (no new rehearsal or smoke window), from the S69 worktree at origin/main d33bfd70 (the registry
# file is main's), plus a positive control (the registered runPVS1r46 block, expect REFUSED rc 2) and the registration state of the windows
# S61 and M27 used.   Usage: bash run_registry_check.sh > registry_check.local.txt
set -u
R=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
cd "$R" || exit 3
echo "# s69r2 registry check, $(date -u +%Y-%m-%dT%H:%M:%SZ); tree $R at $(git rev-parse HEAD) (origin/main $(git rev-parse origin/main)); registry server/runs/seed_windows.json $(shasum -a 256 server/runs/seed_windows.json | cut -c1-16); seed_windows.py $(shasum -a 256 server/scripts/seed_windows.py | cut -c1-16); $($PY -B --version 2>&1)"
for purpose in screen other; do
  for w in "312060910 600 lane-s69r2"; do
    set -- $w
    o=$("$PY" -P -B server/scripts/seed_windows.py check "$1" "$2" --purpose $purpose 2>&1); rc=$?
    echo "check --purpose $purpose $3 $1 $2: rc=$rc $o"
  done
done
o=$("$PY" -P -B server/scripts/seed_windows.py check 61740910 16000 --purpose screen 2>&1); rc=$?
echo "positive control, the registered runPVS1r46 block [61740910, 61756910) (expect REFUSED, rc 2): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-200)"
for w in "218060910 600 S61" "272170910 600 M27-h1a-r3" "311060910 600 S69-consumed"; do
  set -- $w
  o=$("$PY" -P -B server/scripts/seed_windows.py check "$1" "$2" --purpose screen 2>&1); rc=$?
  echo "reported (registration state): $3 [$1, +$2): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-200)"
done
