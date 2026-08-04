# Daily maintenance routine

Run at least once a day (scheduled in the Claude session; this file is the
canonical checklist so any session can execute it).

**Step 0 — audit the prompts themselves.** Recurring prompts rot: they
name jobs that finished, plans that a finding invalidated, or paths that
moved. Before executing any scheduled routine, check its own text against
reality and reschedule a corrected version if stale (CronDelete +
CronCreate; for the dynamic /loop, pass a corrected prompt to the next
ScheduleWakeup). A wrong recurring prompt silently drives wrong work —
on 2026-08-03 the goal loop still said "flip play-time ballots to v2 for
v8", which an external audit had just proven would recreate the Elo-798
collapse.

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
3. **Update documentation — PRUNE, don't append.** Sync AI_POLICIES.md /
   RL_PLAN.md / BACKLOG.md with results since the last sync, and in the same
   pass DELETE what is now wrong. Appending alone is how RL_PLAN ended up
   claiming "warm won, scratch killed" after that was refuted, calling
   MCValueLeaf a 45% failure after it settled at 50.4%, and listing finished
   generation as RUNNING (Jerry, 2026-08-03). Specifically:
   - put current state at the TOP with a date; if a reader must grep to find
     what changed, the update did not land;
   - re-read the sections you did NOT edit — especially "RUNNING", "in
     training", "in flight", "next", and any claim a later result overturned;
   - delete finished items instead of ticking them off; move long history to
     `docs_archive/` with a digest that keeps the reasoning;
   - rebuild factual tables (data inventory, job lists, test counts) from the
     source — disk, git log, the process list — never from the old version.
   Then push.
4. **Cleanup code** — behavior-preserving only: dead imports, duplicate
   logic from rapid edits, stale one-off scripts. Verify with a smoke game
   + `scripts/audit_sourcing.py` rerun. (Deleting measured-rejected toggle
   bodies stays a Jerry-approval item.)
5. **Check the external-review thread** — `HANDOFF_REVIEW.md` for new
   Codex entries; reply inline when actionable, and open an incident file
   under `incidents/` for anything it finds that reached data or prod.
6. **Remove dead artifacts** — and check `lsof` FIRST. On 2026-08-04 the
   "delete run files with <200 records" rule matched the JSONL of a
   confirmation that was still running, deleting the evidence out from under
   the live process; the aggregate log survived but the per-seed records and
   manifest did not. The checklist already said "never touch anything a live
   PID has open" and I broke it by filtering on size instead of liveness.
   Run `lsof -t <file>` (or skip files newer than the oldest running job) before
   deleting anything under `runs/`. — experiment dirs feeding nothing (empty
   dmc2_*/smoke dirs), superseded shard dirs no process holds open, stale
   tmp logs. Never touch: checkpoints in the ladder, snapshots_* probe
   evidence, logs/ (source of truth), anything a live PID has open.

Standing rules: measure before adopting (see shengji adoption bars),
never deploy unproven models, keep human data / checkpoints out of git.
