#!/bin/bash
# lane-lib: exempt producer runner: it never takes or releases the host lock and runs only while the s160.sh launcher holds it
# S160 arm runner (PREDECLARE_S160.md) = claude-rt2-attrib/ut_run_mix.sh 7518ef61 with: ROOT = this file's directory; inputs
# from ROOT/inputs; no confirmation guard; the host lock held by the lane launcher (pid S160_LANE_PID, the lock owner's first
# field), never taken here.  Status lines, the producer command, manifest and seal are ut_run_mix.sh's.
#   usage: s160_run.sh MODE [WORKERS [RECIPE]]   MODE = <ARM> | pilot<ARM> | timing<ARM>
# Refuses if its output or status exists.
set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
MODE=${1:?mode}; WORKERS=${2:-22}; RECIPE_ARG=${3:-}
ROOT=$(cd "$(dirname "$0")" && pwd); RECIPE=${RECIPE_ARG:?recipe}; ADAPTER=$ROOT/kit/ut_mix_adapter.py
PY=/Users/jeryyu/Projects/shengji/server/.venv/bin/python; LOCK=/Users/jeryyu/fleet/.claude-host.lock
case "$MODE" in
  pilot*) ARM=${MODE#pilot}; KIND=pilot ;;
  timing*) ARM=${MODE#timing}; KIND=timing; WORKERS=1 ;;
  *) ARM=$MODE; KIND=duel ;;
esac
eval "$("$PY" -I -B - "$RECIPE" "$ARM" "$KIND" <<'PYEOF'
import json, shlex, sys
rc = json.load(open(sys.argv[1])); a = rc["arms"][sys.argv[2]]; kind = sys.argv[3]
assert rc["schema"] == "utd-mix-recipe-r1" and rc.get("lane") == "S160" and a["ut_package"] is None, "not an s160 recipe"
seed0, deals = {"duel": (a["seed0"], a["deals"]), "pilot": (a["pilot_seed0"], 20), "timing": (a["timing_seed0"], 6)}[kind]
print(f"SEED0={seed0}; DEALS={deals}; TREE={shlex.quote(rc['tree'])}; TREE_HEAD={rc['tree_head']}; R_OUT={shlex.quote(a['out_root'])}")
print("DW=(%s)" % " ".join(shlex.quote(w) for w in a["defender_words"]))
print("EX=(%s)" % " ".join(shlex.quote(w) for w in a["exploiter_words"]))
print("WANT_NAMES=%s" % shlex.quote(json.dumps([a["defender_name"], a["exploiter_name"]])))
PYEOF
)" || { echo "REFUSING: recipe"; exit 6; }
[ "$R_OUT" = "$ROOT/out/$ARM" ] || { echo "REFUSING: the recipe's out_root $R_OUT is not $ROOT/out/$ARM"; exit 6; }
if [ "$KIND" = duel ]; then OUT=$ROOT/out/$ARM; STATUS=$ROOT/$ARM.status; else OUT=$ROOT/$MODE; STATUS=$ROOT/$MODE.status; fi
say () { echo "UTD $1 $(date -u +%FT%TZ) ${*:2}" >> "$STATUS"; }
[ "$(hostname)" = Jerrys-Mac-Studio.local ] || { echo "REFUSING: not the Ultra"; exit 6; }
[ ! -e "$OUT" ] && [ ! -e "$STATUS" ] || { echo "REFUSING: $OUT or $STATUS exists"; exit 6; }
[ "$(git -C "$TREE" rev-parse HEAD)" = "$TREE_HEAD" ] && [ -z "$(git -C "$TREE" status --porcelain)" ] || { echo "REFUSING: tree"; exit 6; }
RSHA=$(shasum -a 256 "$RECIPE" | cut -c1-64)
say START "mode=$MODE arm=$ARM pid=$$ seed0=$SEED0 deals=$DEALS workers=$WORKERS recipe=$RSHA"
"$PY" -I -B - "$RECIPE" "$ARM" <<'PYEOF' || { say ABORT "rc=6 reason=pins"; exit 6; }
import hashlib, json, sys
rc = json.load(open(sys.argv[1]))
pins = dict(rc["pins"]); pins.update(rc["arms"][sys.argv[2]].get("pins", {}))
bad = [p for p, s in pins.items() if hashlib.sha256(open(p, "rb").read()).hexdigest() != s]
sys.exit(f"pin drift: {bad}" if bad else 0)
PYEOF
if [ -n "${S160_LANE_PID:-}" ] && [ "$(head -1 "$LOCK/owner" 2>/dev/null | awk '{print $1}')" = "$S160_LANE_PID" ]; then
  say LOCKED "after 0s (co-run under this lane's own lock: $(cat "$LOCK/owner"))"
else
  say ABORT "rc=6 reason=host lock not held by the lane launcher ${S160_LANE_PID:-unset}"; exit 6
fi
trap 'say UNLOCKED "(lock not held by this run)"' EXIT
mkdir -p "$OUT"
I=$ROOT/inputs
PENV=(env SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONPATH=$TREE/server FIND_GAPS_SERVER=$TREE/server FIND_GAPS_PKG=$I/g3a-e04-f4f4127e.npz "FIND_GAPS_PATH_MAP=/data/models/b1a-028131a0.npz=$I/b1a-028131a0.npz;/data/models/p0-ft1-1fa201b2.npz=$I/p0-ft1-1fa201b2.npz")
cd "$TREE/server"
join () { local IFS=,; echo "$*"; }
NAMES=$(env -u UT_PKG -u UT_SHA256 "${PENV[@]}" "$PY" -B "$ROOT/kit/probe_names.ut.py" "$ADAPTER" "$(join "${DW[@]}")" "$(join "${EX[@]}")") || { say ABORT "rc=6 reason=names-probe"; exit 6; }
[ "$("$PY" -I -c 'import json,sys; print(int(json.loads(sys.argv[1].splitlines()[-1]) == json.loads(sys.argv[2])))' "$NAMES" "$WANT_NAMES")" = 1 ] || { say ABORT "rc=6 reason=names-differ-from-recipe"; exit 6; }
say NAMES "ok"
args=(); for w in "${DW[@]}"; do args+=(--defender-env "$w"); done; for w in "${EX[@]}"; do args+=(--exploiter-env "$w"); done
say PRODUCER "load=$(sysctl -n vm.loadavg)"
env -u UT_PKG -u UT_SHA256 "${PENV[@]}" nice -n 10 /usr/bin/time -l -o "$OUT/duel.time" "$PY" -B "$ADAPTER" --arm identity --seed0 $SEED0 --deals $DEALS \
  --workers $WORKERS --round-plan r2 --out "$OUT/duel.jsonl" "${args[@]}" > "$OUT/run.log" 2>&1 < /dev/null
rc=$?
rows=$(wc -l < "$OUT/duel.jsonl" 2>/dev/null | tr -d ' ')
if [ $rc -ne 0 ] || [ "$rows" != $((2 * DEALS)) ]; then say ABORT "rc=$rc rows=$rows reason=producer"; exit 4; fi
printf '{"schema":"utd-manifest-r1","mode":"%s","arm":"%s","recipe_sha256":"%s","seed0":%s,"deals":%s,"tree_head":"%s","rc":0}\n' "$MODE" "$ARM" "$RSHA" $SEED0 $DEALS "$TREE_HEAD" > "$OUT/manifest.json"
(cd "$OUT" && for f in duel.jsonl duel.jsonl.resume.json duel.time manifest.json run.log; do shasum -a 256 "./$f"; done > SHA256SUMS)
say DONE "recipe=$RSHA rows=$rows sums=$(shasum -a 256 "$OUT/SHA256SUMS" | cut -c1-64) rc=0"
exit 0
