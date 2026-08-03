#!/bin/bash
# One-command status for every shengji job across the fleet (mini + Air).
# Probes LIVE state — no registry to go stale. Run from server/.
#
# Job identification: our compute jobs are python processes in the
# server venv; heredoc-launched ones have opaque cmdlines ("python3 -"),
# so label each by the rl_data/snapshot/ckpt files it holds open.
#
# Convention for NEW long jobs: run as a named script/module logging to
# server/runs/logs/<name>.log, and note intent in the machine's JOBS.md.

hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

hdr "MINI — server-venv python jobs"
for pid in $(pgrep -f "server/.venv/bin/python"); do
  line=$(ps -o etime=,%cpu= -p "$pid" | tr -s ' ')
  label=$(lsof -p "$pid" 2>/dev/null |
    grep -oE "(snapshots_[a-z0-9]+|rl_data/[a-z0-9_]+|[a-z0-9_]+\.log)" |
    sort -u | head -2 | tr '\n' ',' | sed 's/,$//')
  echo "  pid=$pid up/cpu:$line  touches: ${label:-(none — likely a duel/eval)}"
done
for d in snapshots_v7 snapshots_v61 snapshots_v7w; do
  [ -d "$d" ] && echo "  $d: $(ls "$d" 2>/dev/null | tr '\n' ' ')"
done
[ -d runs/logs ] && for f in runs/logs/*.log; do
  [ -f "$f" ] && echo "  $(basename "$f"): $(tail -1 "$f")"
done

hdr "AIR — via JOBS.md + live probe"
ssh -o BatchMode=yes -o ConnectTimeout=8 air '
  cd ~/Projects/shengji-compute/server 2>/dev/null || exit 1
  n=$(grep -h "^PAIR" pool_*.log 2>/dev/null | wc -l | tr -d " ")
  [ "$n" != "0" ] && echo "  pool pairings: $n/24 ($(pgrep -f pool_20260802 | wc -l | tr -d " ") procs alive)"
  pgrep -f "distill_generate" >/dev/null && echo "  gen: running ($(ls rl_data/gen_v3/*.npz 2>/dev/null | wc -l | tr -d " ") shards)"
  echo "  --- NOTES from Air agent (if any):"
  sed -n "/## NOTES/,\$p" ../JOBS.md | tail -n +3 | grep -v "^(leave" | head -25
' 2>/dev/null || echo "  Air unreachable (asleep / off tailnet / SSH off)"

hdr "INTEGRITY — process identity + dataset provenance"
# Aggregates (hot count / total CPU) hide orphans: on 2026-08-03 two
# workers killed by pkill survived 10h on buggy code and wrote into the
# live dataset. Identify EVERY long-running python by its open files,
# and flag shards from worker ids that no live process owns.
for pid in $(pgrep -f "server/.venv/bin/python"); do
  et=$(ps -o etime= -p "$pid" | tr -d ' ')
  # etime is [[DD-]HH:]MM:SS — only 2+ colons (or a day part) means hours
  case "$et" in
    *-*) hrs=99;;
    *:*:*) hrs=${et%%:*};;
    *) hrs=0;;
  esac
  tag=$(lsof -p "$pid" 2>/dev/null | grep -oE "runs/logs/[a-z0-9_]*\.log|rl_data/[a-z0-9_]+" | sort -u | head -1)
  [ -z "$tag" ] && tag="(unidentified — INVESTIGATE)"
  if [ "${hrs:-0}" -ge 6 ] 2>/dev/null; then
    echo "  !! pid=$pid age=$et  $tag   <-- long-running, confirm intentional"
  fi
done
for d in rl_data/gen_v3_mini rl_data/gen_v3; do
  [ -d "$d" ] || continue
  ids=$(ls "$d" 2>/dev/null | sed -n 's/shard_\([0-9]\{3\}\).*/\1/p' | sort -u | tr '\n' ' ')
  echo "  $d shard-writing worker ids: ${ids:-none}"
done
echo "  (any id here with no matching live process = orphan; quarantine its shards)"
