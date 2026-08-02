# Daily maintenance routine

Run at least once a day (scheduled in the Claude session; this file is the
canonical checklist so any session can execute it).

1. **Pull status** — run `server/scripts/fleet_status.sh` (mini + Air):
   every running training/duel/generation job, PID + CPU (alive and
   working?), snapshots landed, probe/duel results since yesterday.
   Surface anything stalled or silently dead. Read the NOTES section of
   each machine's JOBS.md (the inter-agent mailbox: Air =
   ~/Projects/shengji-compute/JOBS.md) and act on or answer any new
   messages.
2. **Update human data** — `scripts/fetch_fly_logs.sh`, then rebuild human
   shards with current (v2) ballots into a NEW dir if any training has the
   old one open. Report corpus growth.
3. **Update documentation + cleanup** — sync AI_POLICIES.md / RL_PLAN.md /
   BACKLOG.md with all results since last sync; prune stale IN PROGRESS
   blocks and completed backlog items; push.
4. **Cleanup code** — behavior-preserving only: dead imports, duplicate
   logic from rapid edits, stale one-off scripts. Verify with a smoke game
   + `scripts/audit_sourcing.py` rerun. (Deleting measured-rejected toggle
   bodies stays a Jerry-approval item.)
5. **Remove dead artifacts** — experiment dirs feeding nothing (empty
   dmc2_*/smoke dirs), superseded shard dirs no process holds open, stale
   tmp logs. Never touch: checkpoints in the ladder, snapshots_* probe
   evidence, logs/ (source of truth), anything a live PID has open.

Standing rules: measure before adopting (see shengji adoption bars),
never deploy unproven models, keep human data / checkpoints out of git.
