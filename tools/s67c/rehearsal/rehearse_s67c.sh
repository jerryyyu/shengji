#!/bin/bash
# s67c host rehearsal (NON-scientific; answers Codex 1075/6407135624's execution-evidence gate): the FINAL launcher's exact heavy path on
# perf -- its own guard functions (sourced with LANE_FUNCTIONS_ONLY=1 from a copy of claude_s67c_perf.final.sh, sha-checked below) and
# run_dev's child form verbatim (setsid'd subshell = its own process group, timeout --signal=KILL, /usr/bin/time -v, the adapter over the
# pinned tree / extensions / packages / path map, --arm identity, 14 workers, plan r2, --exploiter-env S66_EXPLOITER=sc8p) -- on a throwaway
# block 243170000..243170055 (56 deals; seed_windows check rc 0, no host reservation overlaps; outside the reserved 243260910..243264829).
# Changed from run_dev: seed0, deals, out (this directory, never the lane's output root), the stops (1800 / 1810 s) and an RSS sampler
# over the process group.  It takes NO lock and writes no lane path: it refuses if the host lock, a legacy lock, a lane status/output or a
# legacy process exists.  Terminal line: 'REHEARSAL DONE rc=<rc>' or 'REHEARSAL REFUSING: ...'.
#   ON perf:  nohup setsid bash /root/claude-s67c-reh-20261026/rehearse_s67c.sh > /root/claude-s67c-reh-20261026/rehearse.nohup 2>&1 < /dev/null &
set -u
RD=/root/claude-s67c-reh-20261026
L=$RD/claude_s67c_perf.final.sh; L_SHA=2bc24cee41dd186e169e71cfe8463f2340280f0f8b6946d81833a51e924c5461
SEED0=243170000; NDEALS=56; RKILL=1800; RBACK=1810
LOG=$RD/rehearse.log
note () { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
refuse () { note "REHEARSAL REFUSING: $*"; exit 3; }
[ "$(sha256sum "$L" | cut -d" " -f1)" = "$L_SHA" ] || refuse "launcher copy $L is not $L_SHA"
LANE_FUNCTIONS_ONLY=1; source "$L"
[ "$SELF_SHA" = "$L_SHA" ] || refuse "sourced launcher sha $SELF_SHA"
E2PATH=/root/s58pkg/s58-e6-42444515.npz; PATH_MAP="/data/models/s58-e6-42444515.npz=$E2PATH"   # = the launcher's line 401
for p in "$HOSTLOCK" "$LEGACY" "$DATAGEN" "$S" "$OUT" "$RELEASE"; do [ ! -e "$p" ] && [ ! -L "$p" ] || refuse "$p exists (host busy or lane paths present)"; done
legacy_processes_running && refuse "a legacy process is running"
A=$RD/sc8p
[ ! -e "$A" ] || refuse "$A exists"
note "rehearsal start: launcher $L_SHA guards (placeholder, tree, packages, toml, compiled, names, mem)"
placeholder_guard; verify_tree; check_packages; check_toml; check_compiled
NAMES_LINE=$(check_names) || refuse "check_names failed"
note "$NAMES_LINE"
mem_guard
note "guards ok; MemAvailable $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) kB; nproc $(nproc); load $(cut -d' ' -f1-3 /proc/loadavg)"
mkdir "$A" || refuse "cannot create $A"
note "child start: seed0 $SEED0 deals $NDEALS workers $WORKERS plan $PLAN; KILL $RKILL s backstop $RBACK s"
t0=$(date +%s.%N)
( cd "$R/server" && exec setsid env SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 PYTHONPATH="$R/server" \
    FIND_GAPS_SERVER="$R/server" FIND_GAPS_PKG=/root/models/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="$PATH_MAP" \
    timeout --signal=KILL "$RKILL" /usr/bin/time -v -o "$A/duel.time" \
    "$PY" -B "$ADAPTER" --arm identity --seed0 "$SEED0" --deals "$NDEALS" --workers "$WORKERS" --round-plan "$PLAN" --out "$A/duel.jsonl" \
    --exploiter-env "S66_EXPLOITER=sc8p" \
    > "$A/duel.stdout" 2> "$A/duel.stderr" < /dev/null ) &
pid=$!
pg=; for i in 1 2 3 4 5 6 7 8 9 10; do pg=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " "); [ "$pg" = "$pid" ] && break; sleep 0.5; done
[ "$pg" = "$pid" ] || { kill -KILL "$pid" 2>/dev/null; refuse "child $pid is not its own group leader (pgid '$pg')"; }
( trap 'kill $s 2>/dev/null; exit 0' TERM; sleep "$RBACK" & s=$!; wait $s; kill -KILL -- "-$pid" 2>/dev/null ) & wd=$!
note "child pid/pgid $pid; watchdog $wd"
( while kill -0 "$pid" 2>/dev/null; do   # sampler: t, members, sum RSS kB over the group, rows written
    echo "$(date +%s.%N) $(ps -eo pgid=,rss=,stat= | awk -v g="$pid" '$1 == g && $3 !~ /^Z/ {n++; s+=$2} END {printf "%d %d", n, s}') $(wc -l < "$A/duel.jsonl" 2>/dev/null || echo 0)" >> "$RD/mem.tsv"
    sleep 2; done ) & smp=$!
wait "$pid"; rc=$?
t1=$(date +%s.%N)
kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null; wait "$smp" 2>/dev/null
kill -KILL -- "-$pid" 2>/dev/null && note "swept surviving members of group $pid"
for i in 1 2 3 4 5 6 7 8 9 10; do live=$(run_group_live "$pid"); [ -z "$live" ] && break; sleep 0.5; done
wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}')
note "child END rc=$rc wall_s=$wall maxrss_kb(time -v, largest single process)=$(sed -n 's/.*Maximum resident set size (kbytes): //p' "$A/duel.time" 2>/dev/null)"
note "peak group RSS kB / members: $(awk '{if ($3 > m) {m = $3; n = $2}} END {print m, n}' "$RD/mem.tsv") over $(wc -l < "$RD/mem.tsv") samples"
note "group $pid live members after exit: '${live}'; any process still in group: '$(ps -eo pgid=,pid= | awk -v g="$pid" '$1 == g {print $2}' | tr '\n' ' ')'"
note "rows $(wc -l < "$A/duel.jsonl") (expect $((2 * NDEALS))); stdout tail: $(tail -n 1 "$A/duel.stdout")"
( cd "$RD" && find . -type f ! -name SHA256SUMS ! -name rehearse.nohup ! -name rehearse.log -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
note "REHEARSAL DONE rc=$rc"
