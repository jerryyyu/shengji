#!/bin/bash
# s69 staged-layout preflight (called by test_s69_stage.sh as its PREFLIGHT_CMD): in a CLEAN environment (env -i), from the staged dir,
#  (1) the STAGED launcher's check_names python block, cut from the staged copy byte for byte, run against the COPIED harness (its
#      hypotheses import resolves only inside the staged dir) on this Mac's R48 tree, the one smv3out literal rewritten to the Mac copy;
#  (2) the STAGED reader's --check-imports (its pinned helpers and the S61 reference load only from beside it).
# Usage: bash stage_preflight.sh <copied harness> <staged dir> <staged root>
set -u
SA=$1; SD=$2; SR=$3
W=/Users/jerryyu/Projects/shengji-wt/claude-s69-redteam/server
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
S58=/Users/jerryyu/.claude/jobs/d0498cda/tmp/s69pkg/s58-e6-42444515.npz
PKG=/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz
L=$SR/claude_s69_cloud.sh
[ -f "$L" ] && [ -f "$SA" ] && [ -d "$SD" ] || { echo "preflight: staged launcher, harness or dir missing"; exit 3; }
v=$(LANE_FUNCTIONS_ONLY=1 bash -c 'source "$1" >/dev/null; printf "%s\n%s\n%s\n" "$COMBO_NAME" "$CAND_NAME" "$EX_ENV"' x "$L") || { echo "preflight: cannot source the staged launcher"; exit 3; }
COMBO=$(sed -n 1p <<< "$v"); CAND=$(sed -n 2p <<< "$v"); EXENV=$(sed -n 3p <<< "$v")
BLOCK=$(awk "/<<'PY'\$/{f=1;next} /^PY\$/{f=0} f" "$L")
[ -n "$BLOCK" ] || { echo "preflight: no check_names block in the staged launcher"; exit 3; }
names=$(cd "$W" && env -i HOME="$HOME" PATH=/usr/bin:/bin PYTHONPATH="$W" FIND_GAPS_SERVER="$W" FIND_GAPS_PKG="$PKG" FIND_GAPS_PATH_MAP="/data/models/s58-e6-42444515.npz=$S58" \
  SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 "$PY" -B - "$SA" "$COMBO" "$CAND" "$EXENV" "$S58" <<< "$(printf '%s\n' "$BLOCK" | sed "s#'/root/models/smv3out-491ee4bf.npz'#'$PKG'#")" 2>&1) || { echo "preflight: check_names through the copied harness failed: $(tail -2 <<< "$names")"; exit 1; }
imp=$(cd "$SD" && env -i HOME="$HOME" PATH=/usr/bin:/bin "$PY" -B "$SD/s69_read.py" --check-imports 2>&1) || { echo "preflight: the staged reader's --check-imports failed: $(tail -2 <<< "$imp")"; exit 1; }
echo "preflight ok: $(cut -c1-60 <<< "$names") ... | $imp"
