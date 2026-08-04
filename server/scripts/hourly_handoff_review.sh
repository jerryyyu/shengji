#!/bin/zsh
# Run one bounded Codex audit of the shared Shengji handoff. Scheduling belongs
# to cron; this script deliberately performs no internal sleeping or looping.
set -eu

export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

audit_repo=/Users/jerryyu/Projects/shengji
audit_lock=/private/tmp/shengji-codex-hourly-review.lock
audit_log="$audit_repo/server/runs/logs/codex_hourly_review.log"

# If a prior pass lasts longer than an hour, skip instead of overlapping it.
if ! mkdir "$audit_lock" 2>/dev/null; then
    exit 0
fi

cleanup_lock() {
    rmdir "$audit_lock" 2>/dev/null || true
}
trap cleanup_lock EXIT HUP INT TERM

{
    date '+--- hourly Codex audit: %Y-%m-%d %H:%M:%S %Z ---'
    /opt/homebrew/bin/codex exec \
        --ephemeral \
        --color never \
        --sandbox workspace-write \
        --cd "$audit_repo" \
        'Perform exactly one bounded audit pass for the Shengji project. Read the latest Codex-Claude discussion in HANDOFF_REVIEW.md, then inspect repository changes made since the latest Codex entry and the current job ledger. Re-examine only substantive new evidence about ML/RL strategy, experiment validity, engine correctness, Cython/native parity, frontend correctness, and duel/simulation performance. Preserve all existing dirty work. Do not launch experiments or training, do not kill processes, and do not commit or push. Run only bounded read-only diagnostics or tests that are proportionate to new changes. If and only if there is substantive new evidence, a correction, or a question to answer, append one concise timestamped Codex response to HANDOFF_REVIEW.md using apply_patch. If nothing substantive changed, leave every file untouched. End after this single pass.'
    echo
} >> "$audit_log" 2>&1
