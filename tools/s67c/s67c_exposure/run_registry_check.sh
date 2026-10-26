#!/bin/bash
# s67c registry check (read only): seed_windows.py check (--purpose screen; the tool has no 'dev' purpose, as s60dev..s66b) for the one
# 3,920-deal arm block from the claude/s67c-screen worktree at origin/main abf653f8 (its only change is tools/s67c, untracked at this
# point), plus a positive control (the registered M17 block, expect REFUSED rc 2) and the registration state of the windows the packet
# names (S66b, S66, v106sc8, S65, S64).  Usage: bash run_registry_check.sh > registry_check.local.txt
set -u
R=/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
cd "$R" || exit 3
head=$(git rev-parse HEAD); dirty=$(git status --porcelain | grep -v '^?? tools/s67c' | wc -l | tr -d ' ')
reg=$(shasum -a 256 server/runs/seed_windows.json | cut -c1-16); swp=$(shasum -a 256 server/scripts/seed_windows.py | cut -c1-16)
echo "# s67c registry check, $(date -u +%Y-%m-%dT%H:%M:%SZ); tree $R at $head (origin/main $(git rev-parse origin/main)), dirty entries outside tools/s67c: $dirty; registry server/runs/seed_windows.json $reg; seed_windows.py $swp; $($PY -B --version 2>&1)"
o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check 243260910 3920 --purpose screen 2>&1); rc=$?
echo "check sc8p 243260910 3920: rc=$rc $o"
o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check 61740910 160000 --purpose screen 2>&1); rc=$?
echo "positive control, the registered M17 block [61740910, 61900910) (expect REFUSED, rc 2): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-200)"
while read -r s0 n name; do
  o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check "$s0" "$n" --purpose screen 2>&1); rc=$?
  echo "reported (registration state of the windows the packet names): $name [$s0, +$n): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-240)"
done <<'W'
242860910 3920 S66b
242560910 600 S66
250060910 901000 v106sc8-span
242260910 600 S65
242060910 100600 S64-span
W
