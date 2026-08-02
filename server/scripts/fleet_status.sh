#!/bin/bash
# One-command status for every shengji job across the fleet (mini + Air).
# Probes LIVE state (processes, snapshot dirs, log tails) — no registry
# to go stale. Run from server/:  ./scripts/fleet_status.sh
#
# Convention for new long-running jobs: log to server/runs/logs/<name>.log
# (stable path, survives agent sessions) and note intent in the machine's
# JOBS.md (Air: ~/Projects/shengji-compute/JOBS.md).

hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

hdr "MINI — trainings"
for p in "distill_train" "dmc2"; do
  pgrep -fl "$p" | grep -v grep | while read -r pid rest; do
    et=$(ps -o etime= -p "$pid" | tr -d ' ')
    cpu=$(ps -o %cpu= -p "$pid" | tr -d ' ')
    echo "  $p  pid=$pid  up=$et  cpu=${cpu}%"
  done
done
for d in snapshots_v7 snapshots_v61 snapshots_v7w; do
  [ -d "$d" ] && echo "  $d: $(ls "$d" 2>/dev/null | tr '\n' ' ')"
done

hdr "MINI — duels/evals (python jobs that aren't trainings/server)"
ps aux | grep "server/.venv/bin/python" | grep -v -e grep -e distill_train \
  -e shengji-server | awk '{printf "  pid=%s cpu=%s%% up=", $2, $3}' \
  2>/dev/null | head -5
echo ""
[ -d runs/logs ] && for f in runs/logs/*.log; do
  [ -f "$f" ] || continue
  echo "  $(basename "$f"): $(tail -1 "$f")"
done

hdr "AIR — via JOBS.md + live probe"
ssh -o BatchMode=yes -o ConnectTimeout=8 air '
  cd ~/Projects/shengji-compute/server 2>/dev/null || exit 1
  n=$(grep -h "^PAIR" pool_*.log 2>/dev/null | wc -l | tr -d " ")
  [ "$n" != "0" ] && echo "  pool pairings: $n/24 ($(pgrep -f pool_20260802 | wc -l | tr -d " ") procs alive)"
  pgrep -fl "distill_generate" | grep -v grep | head -2 | sed "s/^/  gen: /"
  echo "  --- NOTES from Air agent (if any):"
  sed -n "/## NOTES/,\$p" ../JOBS.md | tail -n +3 | grep -v "^(leave" | head -5
' 2>/dev/null || echo "  Air unreachable (asleep / off tailnet / SSH off)"

hdr "background session tasks (this machine, current agent session)"
echo "  (agent-session scoped; see the conversation for task ids)"
