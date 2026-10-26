#!/bin/bash
# s68dev registry check (read only): seed_windows.py check (--purpose screen) for the two 3,920-deal arm blocks and the rehearsal block,
# from the claude/s68-combo worktree (origin/main d33bfd70 + tools/s68dev only), plus a positive control (the registered M17 block, expect
# REFUSED rc 2) and the registration state of the windows the packet names (S67c, S66b, S64-span).
# = s67c's run_registry_check.sh with the blocks changed.  Usage: bash run_registry_check.sh > registry_check.local.txt
set -u
R=/Users/jerryyu/Projects/shengji-wt/claude-s68-combo
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
cd "$R" || exit 3
head=$(git rev-parse HEAD); dirty=$(git status --porcelain | grep -v '^?? tools/s68dev' | grep -v ' tools/s68dev/' | grep -v 'PROGRESS.md' | wc -l | tr -d ' ')
reg=$(shasum -a 256 server/runs/seed_windows.json | cut -c1-16); swp=$(shasum -a 256 server/scripts/seed_windows.py | cut -c1-16)
echo "# s68dev registry check, $(date -u +%Y-%m-%dT%H:%M:%SZ); tree $R at $head (origin/main $(git rev-parse origin/main)), dirty entries outside tools/s68dev + PROGRESS.md: $dirty; registry server/runs/seed_windows.json $reg; seed_windows.py $swp"
while read -r s0 n name; do
  o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check "$s0" "$n" --purpose screen 2>&1); rc=$?
  echo "check $name $s0 $n: rc=$rc $o"
done <<'W'
243660910 3920 arm-b
244060910 3920 arm-a
243570000 56 rehearsal
W
o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check 61740910 160000 --purpose screen 2>&1); rc=$?
echo "positive control, the registered M17 block [61740910, 61900910) (expect REFUSED, rc 2): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-200)"
while read -r s0 n name; do
  o=$(nice -n 19 "$PY" -B server/scripts/seed_windows.py check "$s0" "$n" --purpose screen 2>&1); rc=$?
  echo "reported (registration state of the windows the packet names): $name [$s0, +$n): rc=$rc $(echo $o | tr '\n' ' ' | cut -c1-240)"
done <<'W'
243260910 3920 S67c
242860910 3920 S66b
242060910 100600 S64-span
W
