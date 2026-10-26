#!/bin/bash
# s68dev host rehearsal (NON-scientific; the packet's execution evidence): the FINAL launcher's exact heavy path on perf -- its own guard
# functions (sourced with LANE_FUNCTIONS_ONLY=1 from a copy of claude_s68dev_perf.final.sh, sha-checked below) and run_dev's child form
# verbatim (setsid'd subshell = its own process group, timeout --signal=KILL, /usr/bin/time -v, the adapter over the pinned tree /
# extensions / packages / path map, --arm identity, 14 workers, plan r2, the arm's --exploiter-env words from arm_env) -- for BOTH arms in
# the lane's order (b, then a), each on the throwaway block 243570000..243570055 (56 deals = 4 x 14; seed_windows check rc 0, no host
# reservation overlaps; outside the reserved arm blocks).  Changed from run_dev: seed0, deals, out (this directory, never the lane's
# output root), the stops (3600 / 3610 s per arm) and an RSS sampler over the process group.  It takes NO lock and writes no lane path:
# it refuses if the host lock, a legacy lock, a lane status / output or a legacy process exists.  Terminal line: 'REHEARSAL DONE rc=<rc>'
# (rc = the first nonzero child rc, else 0) or 'REHEARSAL REFUSING: ...'.  = s67c's rehearse_s67c.sh with the lane, the arms loop and the
# per-arm exploiter env changed.
#   ON perf:  nohup setsid bash /root/claude-s68dev-reh-20261026/rehearse_s68dev.sh > /root/claude-s68dev-reh-20261026/rehearse.nohup 2>&1 < /dev/null &
set -u
RD=/root/claude-s68dev-reh-20261026
L=$RD/claude_s68dev_perf.final.sh; L_SHA=@@FINAL_LAUNCHER_SHA@@
SEED0=243570000; NDEALS=56; RKILL=3600; RBACK=3610
LOG=$RD/rehearse.log
note () { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
refuse () { note "REHEARSAL REFUSING: $*"; exit 3; }
[ "$(sha256sum "$L" | cut -d" " -f1)" = "$L_SHA" ] || refuse "launcher copy $L is not $L_SHA"
LANE_FUNCTIONS_ONLY=1; source "$L"
[ "$SELF_SHA" = "$L_SHA" ] || refuse "sourced launcher sha $SELF_SHA"
E2PATH=/root/s58pkg/s58-e6-42444515.npz; PATH_MAP="/data/models/s58-e6-42444515.npz=$E2PATH"   # = the launcher's main-flow line
for p in "$HOSTLOCK" "$LEGACY" "$DATAGEN" "$S" "$OUT" "$RELEASE"; do [ ! -e "$p" ] && [ ! -L "$p" ] || refuse "$p exists (host busy or lane paths present)"; done
legacy_processes_running && refuse "a legacy process is running"
note "rehearsal start: launcher $L_SHA guards (placeholder, tree, packages, toml, compiled, names, mem)"
placeholder_guard; verify_tree; check_packages; check_toml; check_compiled
NAMES_LINE=$(check_names) || refuse "check_names failed"
note "$NAMES_LINE"
mem_guard
note "guards ok; MemAvailable $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) kB; nproc $(nproc); load $(cut -d' ' -f1-3 /proc/loadavg)"
first_rc=0
for arm in $ARMS; do
  A=$RD/$arm
  [ ! -e "$A" ] || refuse "$A exists"
  mkdir "$A" || refuse "cannot create $A"
  ew=$(arm_env "$arm") || refuse "no arm_env for $arm"
  eargs=(); read -r -a words <<< "$ew"; for w in "${words[@]}"; do eargs+=(--exploiter-env "$w"); done
  note "child start $arm: exploiter env $ew; seed0 $SEED0 deals $NDEALS workers $WORKERS plan $PLAN; KILL $RKILL s backstop $RBACK s"
  t0=$(date +%s.%N)
  ( cd "$R/server" && exec setsid env SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
      NUMEXPR_NUM_THREADS=1 PYTHONPATH="$R/server" \
      FIND_GAPS_SERVER="$R/server" FIND_GAPS_PKG=/root/models/smv3out-491ee4bf.npz FIND_GAPS_PATH_MAP="$PATH_MAP" \
      timeout --signal=KILL "$RKILL" /usr/bin/time -v -o "$A/duel.time" \
      "$PY" -B "$ADAPTER" --arm identity --seed0 "$SEED0" --deals "$NDEALS" --workers "$WORKERS" --round-plan "$PLAN" --out "$A/duel.jsonl" \
      "${eargs[@]}" \
      > "$A/duel.stdout" 2> "$A/duel.stderr" < /dev/null ) &
  pid=$!
  pg=; for i in 1 2 3 4 5 6 7 8 9 10; do pg=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " "); [ "$pg" = "$pid" ] && break; sleep 0.5; done
  [ "$pg" = "$pid" ] || { kill -KILL "$pid" 2>/dev/null; refuse "child $pid is not its own group leader (pgid '$pg')"; }
  ( trap 'kill $s 2>/dev/null; exit 0' TERM; sleep "$RBACK" & s=$!; wait $s; kill -KILL -- "-$pid" 2>/dev/null ) & wd=$!
  note "child $arm pid/pgid $pid; watchdog $wd"
  ( while kill -0 "$pid" 2>/dev/null; do   # sampler: t, members, sum RSS kB over the group, rows written
      echo "$(date +%s.%N) $(ps -eo pgid=,rss=,stat= | awk -v g="$pid" '$1 == g && $3 !~ /^Z/ {n++; s+=$2} END {printf "%d %d", n, s}') $(wc -l < "$A/duel.jsonl" 2>/dev/null || echo 0)" >> "$RD/mem.$arm.tsv"
      sleep 2; done ) & smp=$!
  wait "$pid"; rc=$?
  t1=$(date +%s.%N)
  kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null; wait "$smp" 2>/dev/null
  kill -KILL -- "-$pid" 2>/dev/null && note "swept surviving members of group $pid"
  live=; for i in 1 2 3 4 5 6 7 8 9 10; do live=$(run_group_live "$pid"); [ -z "$live" ] && break; sleep 0.5; done
  wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}')
  note "child $arm END rc=$rc wall_s=$wall maxrss_kb(time -v, largest single process)=$(sed -n 's/.*Maximum resident set size (kbytes): //p' "$A/duel.time" 2>/dev/null)"
  note "peak group RSS kB / members ($arm): $(awk '{if ($3 > m) {m = $3; n = $2}} END {print m, n}' "$RD/mem.$arm.tsv") over $(wc -l < "$RD/mem.$arm.tsv") samples"
  note "group $pid live members after exit: '${live}'; any process still in group: '$(ps -eo pgid=,pid= | awk -v g="$pid" '$1 == g {print $2}' | tr '\n' ' ')'"
  note "rows $arm $(wc -l < "$A/duel.jsonl") (expect $((2 * NDEALS))); stdout tail: $(tail -n 1 "$A/duel.stdout")"
  [ "$rc" -eq 0 ] || { [ "$first_rc" -ne 0 ] || first_rc=$rc; }
done
( cd "$RD" && find . -type f ! -name SHA256SUMS ! -name rehearse.nohup ! -name rehearse.log -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
note "REHEARSAL DONE rc=$first_rc"
