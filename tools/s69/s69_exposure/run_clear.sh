#!/bin/bash
# s69 deal-key clearance (read only) vs the R48 checkpoint lineage, the form of Codex's R48 clearance (/tmp/codex-r48-clearance):
#  (1) the R48 play package's checkpoint GEN5-PROD-SOFT-allPV-plusMCLCB-496k-SMV3/best.pt (sha 3e89e86f, the source of smv3out-491ee4bf)
#      with --follow-init (JS3-M1 soft, then the JS-M1 ancestor, whose train-out path is absent here: --allow-unresolved, printed), controls
#      44260910 23260910 61260910 22260910;
#  (2) the JS-M1 ancestor itself from its sha-identical perf copy (a5248cc5), control 20260905, no unresolved link;
#  (3) S58 (the belief package) trained on the registered runPVS*r46 windows + production room logs: covered by the registry check.
# For the lane window, the rehearsal window and the local smoke window.  Usage: bash run_clear.sh > clear.local.txt 2>&1
set -u
R=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
SMV3=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/train-out/cwv/GEN5-PROD-SOFT-allPV-plusMCLCB-496k-SMV3/best.pt
JSM1=/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/s43t/s43t_exposure/jsm1_perfcopy/JS-M1-policy-w0.2-full/best.pt
cd "$R/server" || exit 3
echo "# s69 seed clearance, $(date -u +%FT%TZ); tree $R at $(git -C $R rev-parse HEAD); SMV3 $(shasum -a 256 $SMV3 | cut -c1-64); JS-M1 copy $(shasum -a 256 $JSM1 | cut -c1-64)"
for w in "311060910 600 lane" "311960000 36 rehearsal" "311970000 4 smoke"; do
  set -- $w
  echo "### ($3) clear $1 $2 --checkpoint SMV3 --follow-init --allow-unresolved --purpose screen"
  nice -n 19 "$PY" -P -B scripts/seed_windows.py clear "$1" "$2" --checkpoint "$SMV3" --follow-init --allow-unresolved --purpose screen --control-seed 44260910 --control-seed 23260910 --control-seed 61260910 --control-seed 22260910 2>&1 | tail -1
  echo "rc=${PIPESTATUS[0]}"
  echo "### ($3) clear $1 $2 --checkpoint JS-M1 copy --follow-init --purpose screen"
  nice -n 19 "$PY" -P -B scripts/seed_windows.py clear "$1" "$2" --checkpoint "$JSM1" --follow-init --purpose screen --control-seed 20260905 2>&1 | tail -1
  echo "rc=${PIPESTATUS[0]}"
done
