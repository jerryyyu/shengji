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
  # Generic probe: name the jobs that are actually running, not the ones
  # that happened to be running when this script was written (the pool_/
  # gen_v3 greps outlived their jobs by two days).
  ps -eo pid,etime,command | grep "[p]ython" | grep -v "grep" |
    sed "s|/Users/[^ ]*/python3*|python|" | awk "{printf \"  proc %s up %s: %s %s %s\\n\", \$1, \$2, \$3, \$4, \$5}" | head -6
  for f in runs/logs/*.log *.log; do
    [ -f "$f" ] || continue
    age=$(( ($(date +%s) - $(stat -f %m "$f")) / 60 ))
    [ "$age" -lt 720 ] && echo "  $(basename "$f") (${age}m): $(tail -1 "$f" | cut -c1-100)"
  done 2>/dev/null | head -8
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

hdr "CODEX MAILBOX — HANDOFF_REVIEW.md discussion thread"
HR=../HANDOFF_REVIEW.md
if [ -f "$HR" ]; then
  # Match how entries are ACTUALLY written ("### Codex reply — ...",
  # "## Codex audit message ..."). The old pattern "^### \[Codex" matched
  # nothing and reported 0 unread while real replies sat in the file
  # (found 2026-08-04 — a monitor that cannot fail loudly is worse than none).
  n=$(grep -cE "^#{2,3} Codex" "$HR" 2>/dev/null || echo 0)
  echo "  Codex entries: $n   (file mtime: $(stat -f "%Sm" -t "%m-%d %H:%M" "$HR"))"
  last=$(grep -nE "^#{2,3} (Codex|Claude reply)" "$HR" | tail -2 | sed "s/^/    /")
  [ -n "$last" ] && printf "  last exchange:\n%s\n" "$last"
  [ "$n" -gt 0 ] && sed -n "/^### \[Codex/,\$p" "$HR" | head -30
else
  echo "  (HANDOFF_REVIEW.md not found)"
fi

hdr "JOB LOGS — age / size / last line (dead jobs have age but no output)"
# Only recent logs; older ones are history, and a finished job's log is
# small-but-complete (check the LAST LINE, not just the size).
now=$(date +%s)
for f in runs/logs/*.log; do
  [ -f "$f" ] || continue
  age=$(( (now - $(stat -f %m "$f")) / 60 ))
  [ "$age" -gt 720 ] && continue                 # ignore logs older than 12h
  sz=$(stat -f %z "$f")
  last=$(tail -1 "$f" 2>/dev/null | cut -c1-70)
  flag=""
  # A log with no meaningful output after 10 minutes is almost certainly a
  # launch failure (bad PATH, missing script). This exact pattern hid two
  # dead Air jobs for hours on 2026-08-03.
  [ "$sz" -lt 40 ] && [ "$age" -gt 10 ] && flag="   <<< NO OUTPUT — LIKELY DEAD"
  printf "  %-34s %4dm %7dB  %s%s\n" "$(basename "$f")" "$age" "$sz" "$last" "$flag"
done | sort -k2 -n
