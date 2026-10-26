#!/bin/bash
# s67c: the launcher stays fresh-only with the resumable producer.  (1) Sourced with LANE_FUNCTIONS_ONLY=1 (host guards stubbed:
# predispatch_guard, check_packages, check_toml, check_compiled, check_names, mem_guard), run_dev refuses an existing arm directory
# (REFUSING, rc 3) before creating anything, for every arm, and leaves the directory's contents untouched (a planted duel.jsonl and its
# .resume.json).  (2) The main flow refuses an existing output root before mkdir and before the first run_dev, and the file has no
# recovery / resume mode.  Writes nothing outside a temp dir.  = s66dev's test_s66dev_launcher_fresh.sh with the launcher path and the arm changed.
set -u
L=${1:-/Users/jerryyu/Projects/shengji-wt/claude-s67c-screen/tools/s67c/claude_s67c_perf.sh}
echo "launcher $(shasum -a 256 "$L" | cut -c1-64)"
fails=0
T=$(mktemp -d /private/tmp/s67cfresh.XXXX)
for arm in sc8p; do
  mkdir -p "$T/out/$arm"; printf '{"seed":1}\n' > "$T/out/$arm/duel.jsonl"; printf '{}\n' > "$T/out/$arm/duel.jsonl.resume.json"
  before=$(cd "$T/out/$arm" && ls -A | tr '\n' ' '; cat duel.jsonl duel.jsonl.resume.json | shasum -a 256)
  out=$( ( LANE_FUNCTIONS_ONLY=1; LANE_ROOT=$T OUT=$T/out; source "$L"
           predispatch_guard () { :; }; check_packages () { :; }; check_toml () { :; }; check_compiled () { :; }; check_names () { :; }; mem_guard () { :; }
           run_dev "$arm" ) 2>&1 ); rc=$?
  after=$(cd "$T/out/$arm" && ls -A | tr '\n' ' '; cat duel.jsonl duel.jsonl.resume.json | shasum -a 256)
  if [ "$rc" -eq 3 ] && echo "$out" | grep -q "REFUSING: DEV output for $arm already exists in $T/out/$arm" && [ "$before" = "$after" ]; then
    echo "PASS run_dev $arm refuses an existing arm dir (rc 3), contents unchanged: $(echo "$out" | tail -1 | cut -c22-130)"
  else echo "FAIL run_dev $arm rc=$rc out=$out"; fails=$((fails + 1)); fi
done
rm -r "$T"
m=$(grep -n '\[ ! -e "$OUT" \] || die "output root $OUT already exists"' "$L" | cut -d: -f1); k=$(grep -n '^mkdir -p "$OUT"' "$L" | cut -d: -f1); f=$(grep -n '^  run_dev "$arm"$' "$L" | cut -d: -f1)
if [ -n "$m" ] && [ -n "$k" ] && [ -n "$f" ] && [ "$m" -lt "$k" ] && [ "$k" -lt "$f" ]; then echo "PASS main flow: output-root refusal (line $m) before mkdir (line $k) and the first run_dev (line $f)"; else echo "FAIL main-flow order ($m $k $f)"; fails=$((fails + 1)); fi
if grep -qE 'RECOVERY|ATTEMPT_ID|--resume' "$L"; then echo "FAIL a recovery/resume mode is present"; fails=$((fails + 1)); else echo "PASS no recovery or resume mode in the launcher (fresh runs only)"; fi
[ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILED"
exit "$fails"
