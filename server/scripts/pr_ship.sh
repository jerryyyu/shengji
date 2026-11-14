#!/usr/bin/env bash
# Update a branch, run its gates, push it and open or update its PR, stopping
# at the first step that fails.
#
# Each step's status is checked before the next one runs, so a conflicted
# rebase never reaches the tests and a failing gate never reaches the push.
# The PR body and the review-ask comment carry the head read back from the
# remote after the push, never one typed by hand.
#
# Usage:
#   pr_ship.sh [--rebase] [--dry-run] [--base origin/main] [--remote origin]
#              [--title TITLE] [--body-file FILE] [--update-comment]
#
#   --rebase          rebase onto --base first; a conflict stops with the files listed
#   --title/--body-file
#                     a new PR needs both; for an existing PR they replace its title/body
#   --update-comment  when the PR exists, post "Review ask at <sha>." (plus the body
#                     file, when given) as a comment instead of editing the PR
#   --dry-run         run the refusal checks, then print the remaining steps only
#
# The body file may contain {{HEAD}}, replaced by the pushed head; a body without
# it gets a "Head: <sha>" line appended. Gates are server/scripts/affected_tests.py
# --run for the branch's changed paths; PR_SHIP_GATES replaces that command (a
# shell string run with bash -c). This script never posts to the agent bus.
#
# Exit codes: 2 usage or refused state, 3 rebase conflict, 4 gates failed,
# 5 push failed or the remote head differs, 6 gh failed.

set -euo pipefail

die() { local code=$1; shift; printf 'pr_ship: %s\n' "$*" >&2; exit "$code"; }
say() { printf 'pr_ship: %s\n' "$*"; }

rebase=0 dry=0 update_comment=0
base=origin/main remote=origin title="" body_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rebase) rebase=1 ;;
    --dry-run) dry=1 ;;
    --update-comment) update_comment=1 ;;
    --base) [ $# -ge 2 ] || die 2 "--base needs a ref"; base=$2; shift ;;
    --remote) [ $# -ge 2 ] || die 2 "--remote needs a name"; remote=$2; shift ;;
    --title) [ $# -ge 2 ] || die 2 "--title needs a value"; title=$2; shift ;;
    --body-file) [ $# -ge 2 ] || die 2 "--body-file needs a path"; body_file=$2; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) die 2 "unknown argument: $1" ;;
  esac
  shift
done
if [ -n "$body_file" ] && [ ! -f "$body_file" ]; then
  die 2 "body file not found: $body_file"
fi

script_dir=$(cd "$(dirname "$0")" && pwd)
top=$(git rev-parse --show-toplevel) || die 2 "not inside a git work tree"
cd "$top"

# A rebase, merge or cherry-pick in progress means HEAD is not the branch the
# gates or the PR would describe.
for marker in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD; do
  path=$(git rev-parse --git-path "$marker")
  if [ -e "$path" ]; then
    die 2 "refusing: $marker present ($path); finish or abort it first"
  fi
done

dirty=$(git status --porcelain --untracked-files=normal)
if [ -n "$dirty" ]; then
  printf '%s\n' "$dirty" >&2
  die 2 "refusing: the work tree is dirty; commit or remove these first"
fi

branch=$(git symbolic-ref --quiet --short HEAD) || die 2 "refusing: detached HEAD"
pr_base=${base#"$remote"/}
if [ "$branch" = "$pr_base" ]; then
  die 2 "refusing: on $branch itself; ship from a topic branch"
fi

run_step() {
  # Print the step; run it unless this is a dry run.
  say "step: $*"
  if [ "$dry" -eq 0 ]; then "$@"; fi
}

run_step git fetch --quiet "$remote"

# Whether the PR exists is read before the gates, so a missing title or body
# stops the run before anything is pushed.
number=""
if [ "$dry" -eq 0 ]; then
  number=$(gh pr view "$branch" --json number --jq .number 2>/dev/null) || number=""
  if [ -z "$number" ] && { [ -z "$title" ] || [ -z "$body_file" ]; }; then
    die 2 "no PR for $branch yet: --title and --body-file are required"
  fi
fi

if [ "$rebase" -eq 1 ]; then
  say "step: git rebase $base"
  if [ "$dry" -eq 0 ]; then
    if ! git rebase "$base"; then
      conflicts=$(git diff --name-only --diff-filter=U)
      printf 'pr_ship: conflicting files:\n%s\n' "${conflicts:-<none listed>}" >&2
      die 3 "rebase onto $base stopped; resolve and 'git rebase --continue', or 'git rebase --abort'. Nothing was pushed."
    fi
  fi
fi

if [ -n "${PR_SHIP_GATES:-}" ]; then
  gates_desc="bash -c $PR_SHIP_GATES"
else
  python=python3
  if [ -x "$top/server/.venv/bin/python" ]; then python="$top/server/.venv/bin/python"; fi
  gates_desc="$python $script_dir/affected_tests.py --repo $top --base $base --run"
fi
say "step: gates: $gates_desc"
if [ "$dry" -eq 0 ]; then
  if [ -n "${PR_SHIP_GATES:-}" ]; then
    if bash -c "$PR_SHIP_GATES"; then gates_rc=0; else gates_rc=$?; fi
  else
    if "$python" "$script_dir/affected_tests.py" --repo "$top" --base "$base" --run; then gates_rc=0; else gates_rc=$?; fi
  fi
  say "gates rc=$gates_rc"
  if [ "$gates_rc" -ne 0 ]; then die 4 "gates failed (rc=$gates_rc); nothing was pushed"; fi
fi

ref="refs/heads/$branch"
old=$(git ls-remote "$remote" "$ref") || die 5 "cannot read $remote $ref"
old=${old%%[[:space:]]*}
local_head=$(git rev-parse HEAD)
# The lease pins the remote's head as read just now; an empty value means the
# branch must not exist yet.
say "step: git push --force-with-lease=$ref:$old $remote HEAD:$ref (remote head ${old:-<none>})"
if [ "$dry" -eq 1 ]; then
  say "step: create or update the PR for $branch against $pr_base at the pushed head"
  say "dry run: nothing fetched, rebased, tested, pushed or posted"
  exit 0
fi
git push --quiet --force-with-lease="$ref:$old" -u "$remote" "HEAD:$ref" || die 5 "push failed; the PR was not touched"
head=$(git rev-parse HEAD)
pushed=$(git ls-remote "$remote" "$ref") || die 5 "cannot read back $remote $ref"
pushed=${pushed%%[[:space:]]*}
if [ "$pushed" != "$head" ] || [ "$head" != "$local_head" ]; then
  die 5 "remote $ref is ${pushed:-<missing>}, local HEAD is $head; the PR was not touched"
fi
say "pushed $head to $remote $ref"

tmp=$(mktemp -t pr_ship.XXXXXX)
trap 'rm -f "$tmp"' EXIT
render_body() {
  # The body file with {{HEAD}} replaced, or with a Head line appended.
  if grep -q '{{HEAD}}' "$body_file"; then
    sed "s/{{HEAD}}/$head/g" "$body_file"
  else
    cat "$body_file"
    printf '\nHead: `%s`\n' "$head"
  fi
}

if [ -n "$number" ]; then
  if [ "$update_comment" -eq 1 ]; then
    { printf 'Review ask at `%s`.\n' "$head"; if [ -n "$body_file" ]; then printf '\n'; render_body; fi; } >"$tmp"
    gh pr comment "$number" --body-file "$tmp" || die 6 "gh pr comment failed"
    say "PR #$number: review ask posted at $head"
  elif [ -n "$body_file" ] || [ -n "$title" ]; then
    if [ -n "$body_file" ]; then render_body >"$tmp"; set -- --body-file "$tmp"; else set --; fi
    if [ -n "$title" ]; then set -- "$@" --title "$title"; fi
    gh pr edit "$number" "$@" || die 6 "gh pr edit failed"
    say "PR #$number updated at $head"
  else
    say "PR #$number exists; head is now $head (no body, title or comment given)"
  fi
else
  render_body >"$tmp"
  gh pr create --head "$branch" --base "$pr_base" --title "$title" --body-file "$tmp" || die 6 "gh pr create failed"
  say "PR created for $branch at $head"
fi
