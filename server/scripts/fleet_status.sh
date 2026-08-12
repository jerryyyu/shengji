#!/bin/bash
# One-command status for every shengji job across the fleet
# (Mini + Air + the optional local `shengji-cloud` SSH alias).
# Probes LIVE state — no registry to go stale. Run from server/.
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
    printf "  %s (%sm): %s\n" "$f" "$age" \
      "$(tail -1 "$f" 2>/dev/null | cut -c1-160)"
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
  echo "  --- reviewed Pair V3 score-free capture progress"
  pair_capture_root=/var/tmp/shengji-pair-affected-capture-v3
  pair_capture_logs=/var/tmp/pair-affected-capture-v3-logs
  pair_capture_git=746882859529af883bb634e4da10e567720b7ce9
  pair_capture_seen=0
  pair_capture_min=750000
  pair_capture_max=0
  pair_capture_problem=""
  if [ ! -d "$pair_capture_root" ] \
      || [ "$(git -C "$pair_capture_root" rev-parse HEAD 2>/dev/null)" \
           != "$pair_capture_git" ] \
      || [ -n "$(git -C "$pair_capture_root" status --porcelain \
                   --untracked-files=all 2>/dev/null)" ]; then
    pair_capture_problem="exact reviewed worktree missing or dirty"
  else
    for f in "$pair_capture_logs"/shard-??.log; do
      [ -f "$f" ] || continue
      line=$(tail -n 1 "$f" 2>/dev/null || true)
      case "$line" in
        *"\"event\": \"pair-affected-capture-progress-v1\""*"\"score_free\": true"*) ;;
        *) pair_capture_problem="unexpected/non-score-free progress line"; break ;;
      esac
      deals=$(printf "%s\n" "$line" |
        sed -n "s/.*\"deals_scanned\": \([0-9][0-9]*\).*/\1/p")
      if [ -z "$deals" ]; then
        pair_capture_problem="missing deals_scanned counter"
        break
      fi
      pair_capture_seen=$((pair_capture_seen + 1))
      [ "$deals" -lt "$pair_capture_min" ] && pair_capture_min=$deals
      [ "$deals" -gt "$pair_capture_max" ] && pair_capture_max=$deals
    done
  fi
  if [ -n "$pair_capture_problem" ]; then
    echo "  !! content remains sealed: $pair_capture_problem"
  elif [ "$pair_capture_seen" -eq 0 ]; then
    echo "  (no reviewed Pair V3 heartbeat yet)"
  else
    pair_capture_pct=$(awk -v n="$pair_capture_min" \
      "BEGIN {printf \"%.1f\", 100*n/750000}")
    echo "  shards=$pair_capture_seen/16 deals_per_shard=$pair_capture_min..$pair_capture_max / 750000 (slowest ${pair_capture_pct}%)"
    echo "  content boundary: counters only; captured states remain unopened"
  fi
  echo "  --- reviewed S4 handoff queue"
  s4_queue_script=/var/tmp/s4-c2-360b-launch-queue.sh
  s4_queue_log=/var/tmp/s4-c2-360b-launch-queue.log
  s4_queue_sha=462a54975a4caea6a872bbc4ba474a16b03088ba690106026d3e10594ed383e9
  if tmux has-session -t s4-c2-360b-launch-queue 2>/dev/null; then
    actual_queue_sha=$(sha256sum "$s4_queue_script" 2>/dev/null |
      awk "{print \$1}")
    if [ "$actual_queue_sha" != "$s4_queue_sha" ]; then
      echo "  !! queue session exists but script identity drifted"
    else
      queue_event=$(grep -E \
        "^(queue_started|capture_complete_and_s4_admission_start|s4_launch_start)=|^HOLD:" \
        "$s4_queue_log" 2>/dev/null | tail -n 1 || true)
      echo "  session=s4-c2-360b-launch-queue script_sha=${actual_queue_sha}"
      echo "  state=${queue_event:-(waiting; no safe event line)}"
    fi
  else
    echo "  (no S4 queue session visible)"
  fi
  echo "  --- legacy unreviewed census: metadata only"
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
