#!/usr/bin/env bash
# Block until something an agent should react to happens, print it, and exit.
# For harnesses with no background notifications: run this as the last step of a
# turn; the turn resumes when it returns. Every source is read-only.
#
# Usage:
#   server/scripts/agent_wait.sh [--me codex] [--peer claude] [--timeout 3600] [--interval 30]
#       [--pr N]... [--issue N]... [--file PATH[:REGEX]]... [--ssh HOST:PATH[:REGEX]]...
#
# Sources (any that fire end the wait; all are checked every --interval seconds):
#   bus     a new agent-bus line from --peer to --me (always on; peeked, never acked)
#   --pr    a new issue comment, review or review comment on PR N, or a new head sha
#   --issue a new comment on issue N
#   --file  a new line in a local file, optionally matching REGEX (grep -E)
#   --ssh   the same for a file on a remote host (one ssh per poll, bounded by ConnectTimeout)
# Exit: 0 an event (printed as "EVENT <source> <detail>"), 2 timeout, 3 usage or setup error.
# The first poll records a baseline and reports nothing, so only changes after the start count.
set -u
ME=codex PEER=claude TIMEOUT=3600 INTERVAL=30
PROJECT=${AGENT_WAIT_PROJECT:-/Users/jerryyu/Projects/shengji}
REPO=${AGENT_WAIT_REPO:-jerryyyu/shengji}
BUS=${AGENT_BUS:-agent-bus}
PRS=() ISSUES=() FILES=() REMOTES=()
while [ $# -gt 0 ]; do
  case $1 in
    --me) ME=$2; shift 2 ;;
    --peer) PEER=$2; shift 2 ;;
    --timeout) TIMEOUT=$2; shift 2 ;;
    --interval) INTERVAL=$2; shift 2 ;;
    --pr) PRS+=("$2"); shift 2 ;;
    --issue) ISSUES+=("$2"); shift 2 ;;
    --file) FILES+=("$2"); shift 2 ;;
    --ssh) REMOTES+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "agent_wait: unknown argument $1" >&2; exit 3 ;;
  esac
done
case "$TIMEOUT$INTERVAL" in *[!0-9]*) echo "agent_wait: --timeout and --interval take whole seconds" >&2; exit 3 ;; esac
[ "$INTERVAL" -ge 5 ] || { echo "agent_wait: --interval must be at least 5" >&2; exit 3; }
command -v "$BUS" >/dev/null || { echo "agent_wait: $BUS not found" >&2; exit 3; }
if [ ${#PRS[@]} -gt 0 ] || [ ${#ISSUES[@]} -gt 0 ]; then
  command -v gh >/dev/null || { echo "agent_wait: gh not found" >&2; exit 3; }
fi

# Each probe prints one fingerprint line; a changed fingerprint is an event.
bus_probe() {   # count and last line of PEER->ME messages
  local out rc
  out=$("$BUS" log --project "$PROJECT" 2>/dev/null); rc=$?
  [ $rc -eq 0 ] || { echo "ERR"; return; }
  printf '%s\n' "$out" | grep -F "$PEER->$ME" | tail -n 1 | awk -v n="$(printf '%s\n' "$out" | grep -cF "$PEER->$ME")" '{print n" "$0}'
}
pr_probe() {    # head sha plus counts of comments, reviews and review comments
  local n=$1 head c r rc_
  head=$(gh pr view "$n" -R "$REPO" --json headRefOid --jq .headRefOid 2>/dev/null) || { echo "ERR"; return; }
  c=$(gh api "repos/$REPO/issues/$n/comments?per_page=100" --paginate --jq 'length' 2>/dev/null | paste -sd+ - | bc 2>/dev/null)
  r=$(gh api "repos/$REPO/pulls/$n/reviews?per_page=100" --paginate --jq 'length' 2>/dev/null | paste -sd+ - | bc 2>/dev/null)
  rc_=$(gh api "repos/$REPO/pulls/$n/comments?per_page=100" --paginate --jq 'length' 2>/dev/null | paste -sd+ - | bc 2>/dev/null)
  [ -n "$c" ] && [ -n "$r" ] && [ -n "$rc_" ] || { echo "ERR"; return; }
  echo "$head $c $r $rc_"
}
issue_probe() { # count of comments
  local n=$1 c
  c=$(gh api "repos/$REPO/issues/$n/comments?per_page=100" --paginate --jq 'length' 2>/dev/null | paste -sd+ - | bc 2>/dev/null)
  [ -n "$c" ] || { echo "ERR"; return; }
  echo "$c"
}
file_probe() {  # matching-line count and the last matching line
  local spec=$1 path re
  path=${spec%%:*}; re=${spec#"$path"}; re=${re#:}
  [ -r "$path" ] || { echo "MISSING"; return; }
  if [ -n "$re" ]; then grep -E -- "$re" "$path" | awk 'END{print NR" "$0}'; else awk 'END{print NR" "$0}' "$path"; fi
}
ssh_probe() {   # the same as file_probe, on HOST
  local spec=$1 host rest path re
  host=${spec%%:*}; rest=${spec#"$host":}; path=${rest%%:*}; re=${rest#"$path"}; re=${re#:}
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$host" \
    "if [ -r '$path' ]; then if [ -n '$re' ]; then grep -E -- '$re' '$path' | awk 'END{print NR\" \"\$0}'; else awk 'END{print NR\" \"\$0}' '$path'; fi; else echo MISSING; fi" 2>/dev/null \
    || echo "ERR"
}

BASE=$(mktemp "${TMPDIR:-/tmp}/agent_wait.XXXXXX") || exit 3
trap 'rm -f "$BASE" "$BASE.new"' EXIT
base_get() { awk -F '\t' -v k="$1" '$1 == k { v = $2 } END { print (v == "" ? "ERR" : v) }' "$BASE"; }
base_set() { awk -F '\t' -v k="$1" '$1 != k' "$BASE" > "$BASE.new"; printf '%s\t%s\n' "$1" "$2" >> "$BASE.new"; mv "$BASE.new" "$BASE"; }
probe_all() {   # prints "key<TAB>fingerprint" lines
  printf 'bus\t%s\n' "$(bus_probe)"
  local x
  for x in "${PRS[@]+"${PRS[@]}"}"; do printf 'pr#%s\t%s\n' "$x" "$(pr_probe "$x")"; done
  for x in "${ISSUES[@]+"${ISSUES[@]}"}"; do printf 'issue#%s\t%s\n' "$x" "$(issue_probe "$x")"; done
  for x in "${FILES[@]+"${FILES[@]}"}"; do printf 'file:%s\t%s\n' "$x" "$(file_probe "$x")"; done
  for x in "${REMOTES[@]+"${REMOTES[@]}"}"; do printf 'ssh:%s\t%s\n' "$x" "$(ssh_probe "$x")"; done
}

probe_all > "$BASE"
deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  sleep "$INTERVAL"
  fired=0
  while IFS=$'\t' read -r k v; do
    # an unreadable source is not an event; its baseline waits for a good read
    if [ "$v" = "ERR" ]; then continue; fi
    old=$(base_get "$k")
    if [ "$old" = "ERR" ]; then base_set "$k" "$v"; continue; fi
    if [ "$v" != "$old" ]; then
      echo "EVENT $k ${v:0:400}"
      fired=1
    fi
  done < <(probe_all)
  [ $fired -eq 1 ] && exit 0
done
echo "TIMEOUT after ${TIMEOUT}s"
exit 2
