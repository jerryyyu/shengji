#!/bin/bash
# One-command status for every shengji job across the fleet
# (Mini + Air + optional local `shengji-cloud` strength and `shengji-perf`
# performance SSH aliases). Public addresses never belong in this repository.
# Probes LIVE state — no registry to go stale. Run from any directory.
#
# Job identification: our compute jobs are python processes in the
# server venv; heredoc-launched ones have opaque cmdlines ("python3 -"),
# so label each by the rl_data/snapshot/ckpt files it holds open.
#
# Convention for NEW long jobs: run as a named script/module logging to
# server/runs/logs/<name>.log, and note intent in the machine's JOBS.md.

# Run from anywhere. This used to require cwd=server/, and when the caller's
# cwd had drifted the script simply failed — printing an EMPTY Codex mailbox
# section that read exactly like "no new entries" (2026-08-04). A monitor that
# can fail silently is worse than no monitor.
cd "$(dirname "$0")/.." || { echo "FATAL: cannot reach server/"; exit 1; }

hdr() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

# Content reads are a separate authority from file metadata.  These exact
# paths are bound to reviewed supervisors whose stdout is score-free while
# outcomes remain sealed.  Add a future run only after checking its source;
# never broaden this to generic *.log / *.jsonl matching.
score_free_progress_file() {
  case "$1" in
    */teacher-v3-stage-c-midlate-composition-screen-v1/supervisor-console.log|*/pair-aware-whole-round-screen-v3/supervisor-console.log) return 0 ;;
    *) return 1 ;;
  esac
}

# A T4 heartbeat reports the current arm, not cumulative completion. Turning
# `treatment 400/512` into 78% hid the two later 512-round arms. Report an
# explicit sequential round-work fraction while leaving outcome bytes sealed.
composition_round_progress() {
  python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
    progress = value["progress"]
    order = {"treatment": 0, "matched_null": 1, "champion": 2}
    done = total = 0
    for item in progress:
        per_arm = int(item["rounds_total"])
        complete = int(item["rounds_complete"])
        arm = item["arm"]
        if arm not in order or not 0 <= complete <= per_arm:
            raise ValueError
        done += order[arm] * per_arm + complete
        total += 3 * per_arm
    if progress and total:
        print(f"sequential-round-work={done}/{total} ({100*done/total:.1f}%; {len(progress)} shards)")
except Exception:
    pass
' 2>/dev/null
}

# Any unexpected failure must be LOUD, not an empty section.
trap 'echo "FLEET_STATUS FAILED at line $LINENO — do not read the output above as an all-clear"' ERR

hdr "MINI — server-venv python jobs"
for pid in $(pgrep -f "server/.venv/bin/python"); do
  line=$(ps -o etime=,%cpu= -p "$pid" | tr -s ' ')
  label=$(lsof -p "$pid" 2>/dev/null |
    grep -oE "runs/logs/[^[:space:]]+|rl_data/[^[:space:]]+|[A-Za-z0-9._-]+\.log" |
    sort -u | head -2 | tr '\n' ',' | sed 's/,$//')
  script=$(ps -o command= -p "$pid" |
    sed -n 's|.*\(server/scripts/[^ ]*\.py\).*|\1|p' | head -1)
  echo "  pid=$pid up/cpu:$line  job: ${script:-(wrapper/interactive)}  touches: ${label:-(none)}"
done
echo "  --- allowlisted score-free supervisor heartbeats (30m)"
find /private/tmp -maxdepth 7 -type f \
  -path "*/server/runs/logs/*" -mmin -30 \
  -name "*supervisor-console.log" -print 2>/dev/null |
  while IFS= read -r f; do
    score_free_progress_file "$f" || continue
    age=$(( ($(date +%s) - $(stat -f %m "$f")) / 60 ))
    line=$(tail -1 "$f" 2>/dev/null)
    summary=""
    case "$f" in
      */teacher-v3-stage-c-midlate-composition-screen-v1/supervisor-console.log)
        summary=$(printf "%s\n" "$line" | composition_round_progress)
        ;;
    esac
    printf "  %s (%sm): %s%s\n" "$f" "$age" \
      "$(printf "%s" "$line" | cut -c1-160)" \
      "${summary:+  [$summary]}"
  done

hdr "AIR — broad process identity + live progress"
# INC-12: never infer IDLE from a remembered job-name substring. The prior
# probe also changed directory to one legacy checkout before inspecting the
# host, which could hide isolated /private/tmp evidence worktrees. Inventory
# every Python process first, retain its full command and cwd, and make a zero
# count explicitly UNKNOWN until expected run manifests are reconciled.
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 air '
  score_free_progress_file() {
    case "$1" in
      */teacher-v3-stage-c-midlate-composition-screen-v1/supervisor-console.log|*/pair-aware-whole-round-screen-v3/supervisor-console.log) return 0 ;;
      *) return 1 ;;
    esac
  }
  # Match the executable column, not the full argv: the probe command itself
  # command text contains the word "python" and would otherwise count itself.
  pids=$(ps -Ao pid=,comm= |
    awk "tolower(\$0) ~ /python/ {print \$1}")
  count=$(printf "%s\n" "$pids" | awk "NF {n++} END {print n+0}")
  echo "  Python processes visible: $count"
  if [ "$count" -eq 0 ]; then
    echo "  !! ZERO ROWS = UNKNOWN, not IDLE; reconcile expected PIDs,"
    echo "     heartbeat/log mtimes and terminal outputs before replacement"
  fi
  echo "  --- exact process command and cwd"
  printf "%s\n" "$pids" | while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    if meta=$(ps -p "$pid" -o pid=,ppid=,%cpu=,etime=); then
      command=$(ps -p "$pid" -o command=)
      script=$(printf "%s\n" "$command" |
        sed -n "s|.* \([^ ]*\.py\) .*|\1|p")
      role=$(printf "%s\n" "$command" |
        sed -n "s|.*\.py \([^ ]*\).*|\1|p")
      expected_git=$(printf "%s\n" "$command" |
        sed -n "s|.*--expected-git \([^ ]*\).*|\1|p")
      shard=$(printf "%s\n" "$command" |
        sed -n "s|.*--shard-index \([^ ]*\).*|\1|p")
      cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null |
        sed -n "s/^n//p" | head -1)
      echo "  $meta script=${script:-(unresolved)} role=${role:-(unknown)} git=${expected_git:-(none)} shard=${shard:--}"
      echo "    cwd=${cwd:-(unresolved)}"
    else
      echo "  pid=$pid vanished during probe; reconcile before status claim"
    fi
  done
  echo "  --- allowlisted score-free progress content (30m)"
  find /private/tmp -maxdepth 7 -type f \
    -path "*/server/runs/logs/*" -mmin -30 \
    \( -name "*.log" -o -name "*.jsonl" \) -print 2>/dev/null |
    while IFS= read -r f; do
      score_free_progress_file "$f" || continue
      age=$(( ($(date +%s) - $(stat -f %m "$f")) / 60 ))
      printf "  %s (%sm): %s\n" "$f" "$age" \
        "$(tail -1 "$f" 2>/dev/null | cut -c1-120)"
    done
  echo "  --- other recent evidence files: metadata only (30m)"
  find /private/tmp -maxdepth 7 -type f \
    -path "*/server/runs/logs/*" -mmin -30 \
    \( -name "*.log" -o -name "*.jsonl" \) -print 2>/dev/null |
    while IFS= read -r f; do
      score_free_progress_file "$f" && continue
      age=$(( ($(date +%s) - $(stat -f %m "$f")) / 60 ))
      size=$(stat -f %z "$f" 2>/dev/null || echo unknown)
      printf "  %s (%sm, %sB; content sealed)\n" "$f" "$age" "$size"
    done
'; then
  echo "  Air probe FAILED — state UNKNOWN (not idle)"
fi

hdr "CLOUD — broad process identity + live progress"
# The public address belongs only in the operator's local SSH config.  Keeping
# this probe on the `shengji-cloud` alias makes the repository safe to share
# and lets the host be replaced without editing experiment code.
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 shengji-cloud '
  pids=$(ps -Ao pid=,comm= |
    awk "tolower(\$0) ~ /python/ {print \$1}")
  count=$(printf "%s\n" "$pids" | awk "NF {n++} END {print n+0}")
  echo "  Python processes visible: $count"
  echo "  Capacity: $(nproc) CPUs; load $(cut -d" " -f1-3 /proc/loadavg)"
  free -h | sed -n "2s/^/  Memory: /p"
  if [ "$count" -eq 0 ]; then
    echo "  !! ZERO ROWS = UNKNOWN, not IDLE; reconcile expected PIDs,"
    echo "     tmux sessions, progress mtimes and terminal outputs"
  fi
  echo "  --- exact process command, cwd and source"
  printf "%s\n" "$pids" | while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    if meta=$(ps -p "$pid" -o pid=,ppid=,%cpu=,etime=); then
      command=$(ps -p "$pid" -o command=)
      cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
      git=none
      if [ -n "$cwd" ]; then
        probe=$cwd
        while [ "$probe" != / ] && [ ! -e "$probe/.git" ]; do
          probe=$(dirname "$probe")
        done
        if [ -e "$probe/.git" ]; then
          git=$(git -C "$probe" rev-parse HEAD 2>/dev/null || echo unreadable)
        fi
      fi
      echo "  $meta git=$git"
      echo "    cwd=${cwd:-(unresolved)}"
      echo "    command=$command"
    else
      echo "  pid=$pid vanished during probe; reconcile before status claim"
    fi
  done
  echo "  --- tmux sessions"
  tmux list-sessions 2>/dev/null | sed "s/^/  /" || echo "  (none visible)"
  echo "  --- allowlisted S4 score-free progress"
  s4_progress_dir=/var/tmp/shengji-s4-c2-360b-run/server/runs/logs/s4-point-banking-future-c2-360b-v1
  if [ -d "$s4_progress_dir" ]; then
    python3 - "$s4_progress_dir" <<PY
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for path in sorted(root.glob("tranche-1-shard-*.log.partial")):
    try:
        line = path.read_text().splitlines()[-1]
        value = json.loads(line)
        if value.get("event") != "s4-point-banking-future-progress-v1":
            continue
        rows.append((
            int(value["shard_index"]),
            int(value["clusters_complete"]),
            int(value["clusters_total"]),
        ))
    except (IndexError, KeyError, OSError, TypeError, ValueError):
        continue
if len(rows) == 16 and {row[0] for row in rows} == set(range(16)):
    totals = {row[2] for row in rows}
    if len(totals) == 1 and all(0 <= row[1] <= row[2] for row in rows):
        per_shard = totals.pop()
        done = sum(row[1] for row in rows)
        total = 16 * per_shard
        values = [row[1] for row in rows]
        print(f"  tranche-1 clusters={done}/{total} ({100 * done / total:.1f}%); per-shard={min(values)}-{max(values)}/{per_shard}")
    else:
        print("  !! S4 progress totals drifted; state UNKNOWN")
else:
    print(f"  !! S4 progress rows={len(rows)}/16; state UNKNOWN")
PY
  else
    echo "  (active S4 progress directory absent)"
  fi
  echo "  --- unreviewed census progress: metadata only"
  f=/var/tmp/pair-retention-census-v1.log
  if [ -f "$f" ]; then
    age=$(( ($(date +%s) - $(stat -c %Y "$f")) / 60 ))
    printf "  %s (%sm; %sB; content not opened)\n" "$f" "$age" \
      "$(stat -c %s "$f")"
  else
    echo "  (no cloud census progress file)"
  fi
  echo "  --- census terminal artifact metadata only"
  for artifact in /var/tmp/pair-retention-census-v1.json; do
    [ -e "$artifact" ] || continue
    printf "  %s (%sB; content not opened)\n" "$artifact" \
      "$(stat -c %s "$artifact")"
  done
'; then
  echo "  Cloud probe FAILED — state UNKNOWN (not idle)"
fi

hdr "PERFORMANCE HOST — qualification / performance work only"
# This host is intentionally distinct from the strength Cloud worker above.
# It is not authorized for scored evidence until a future controller pins its
# exact runtime. This alias-only probe reads operating state, never evidence
# files or log content.
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 shengji-perf '
  echo "  Host: $(hostname)"
  echo "  Capacity: $(nproc) CPUs; load $(cut -d" " -f1-3 /proc/loadavg)"
  free -h | sed -n "2s/^/  Memory: /p"
  pids=$(ps -Ao pid=,comm= |
    awk "tolower(\$0) ~ /python/ {print \$1}")
  count=$(printf "%s\n" "$pids" | awk "NF {n++} END {print n+0}")
  echo "  Python processes visible: $count"
  if [ "$count" -eq 0 ]; then
    echo "  (no Python work visible; performance host remains unqualified for strength)"
  fi
  echo "  --- exact Python process command, cwd and source"
  printf "%s\n" "$pids" | while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    if meta=$(ps -p "$pid" -o pid=,ppid=,%cpu=,etime=); then
      command=$(ps -p "$pid" -o command=)
      cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
      git=none
      if [ -n "$cwd" ]; then
        probe=$cwd
        while [ "$probe" != / ] && [ ! -e "$probe/.git" ]; do
          probe=$(dirname "$probe")
        done
        if [ -e "$probe/.git" ]; then
          git=$(git -C "$probe" rev-parse HEAD 2>/dev/null || echo unreadable)
        fi
      fi
      echo "  $meta git=$git"
      echo "    cwd=${cwd:-(unresolved)}"
      echo "    command=$command"
    else
      echo "  pid=$pid vanished during probe; reconcile before status claim"
    fi
  done
  echo "  --- tmux sessions"
  tmux list-sessions 2>/dev/null | sed "s/^/  /" || echo "  (none visible)"
'; then
  echo "  Performance host probe FAILED — state UNKNOWN (not idle)"
fi

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
  tag=$(lsof -p "$pid" 2>/dev/null |
    grep -oE "runs/logs/[^[:space:]]+|rl_data/[^[:space:]]+|[A-Za-z0-9._-]+\.log" |
    sort -u | head -1)
  [ -z "$tag" ] && tag=$(ps -o command= -p "$pid" |
    sed -n 's|.*\(server/scripts/[^ ]*\.py\).*|\1|p' | head -1)
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
  codex_n=$(grep -cE "^#{2,3} Codex" "$HR" 2>/dev/null || echo 0)
  claude_n=$(grep -cE "^#{2,3} Claude" "$HR" 2>/dev/null || echo 0)
  if [ ! -f "$HR" ]; then
    echo "  MAILBOX UNREADABLE at $HR — this is NOT 'no new entries'"
  fi
  echo "  Codex entries: $codex_n  Claude entries: $claude_n   (file mtime: $(stat -f "%Sm" -t "%m-%d %H:%M" "$HR"))"
  last=$(grep -nE "^#{2,3} (Codex|Claude)" "$HR" | tail -2 | sed "s/^/    /")
  [ -n "$last" ] && printf "  last exchange:\n%s\n" "$last"
else
  echo "  (HANDOFF_REVIEW.md not found)"
fi

hdr "JOB LOGS — metadata only (content requires an explicit safe boundary)"
# Generic logs may contain sealed outcomes.  File age and size are operational
# metadata; content is shown only in the exact score-free allowlist above.
now=$(date +%s)
for f in runs/logs/*.log; do
  [ -f "$f" ] || continue
  age=$(( (now - $(stat -f %m "$f")) / 60 ))
  [ "$age" -gt 720 ] && continue                 # ignore logs older than 12h
  sz=$(stat -f %z "$f")
  flag=""
  # A log with no meaningful output after 10 minutes is almost certainly a
  # launch failure (bad PATH, missing script). This exact pattern hid two
  # dead Air jobs for hours on 2026-08-03.
  [ "$sz" -lt 40 ] && [ "$age" -gt 10 ] && flag="   <<< NO OUTPUT — LIKELY DEAD"
  printf "  %-34s %4dm %7dB%s\n" "$(basename "$f")" "$age" "$sz" "$flag"
done | sort -k2 -n
