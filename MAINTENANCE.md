# Daily maintenance routine

Last rewritten: 2026-08-08. This is the canonical checklist, not proof that a
cron/loop is installed or firing. A scheduled session must record its actual
next wake and last successful execution; never infer that from this file.

## 0. Reconcile the checklist with reality

Recurring prompts rot. Before acting, compare the named champion, live roots,
run IDs, scripts and owners with `README.md`, the top of `BACKLOG.md`, the
process list and exact manifests. Correct the schedule/checklist before using a
stale instruction. A status command returning no rows is not automatically an
all-clear.

## 1. Establish live fleet truth

Run `server/scripts/fleet_status.sh` as a first-pass convenience, then verify
each important job at its actual root. The script's Air section still probes
the legacy `~/Projects/shengji-compute` checkout and may omit isolated evidence
worktrees such as the current Teacher audit; it is not authoritative by itself.

For every live job record:

- host, checkout, exact git SHA and dirty state;
- supervisor/worker PIDs, elapsed time and CPU;
- immutable run ID, parent/receipt/preparation identities and namespace;
- latest score-free heartbeat/progress and whether every expected worker lives;
- terminal/final/partial files by metadata only when outcomes are still sealed.

Never open a partial outcome, change a stopping rule from live scores, duplicate
a one-shot run, or infer success from a filename that may be published before a
worker's final provenance check. Mini is the default host for newly authorized
long and short compute; use Air as overflow or with a recorded placement reason.
Do not migrate a healthy sealed run between machines without measured benefit
and a protocol that permits it.

## 2. Reconcile results and review markers

Check `HANDOFF_REVIEW.md` for the newest exact marker or finding. A review PASS
must bind the intended git/material/script digests and scope; a prose “looks
good” is not a marker. Apply actionable findings to the queue, and open an
incident under `incidents/` if a defect reached production or trusted data.

`HANDOFF_REVIEW.md` is the Claude-owned append-only review ledger. Do not
rewrite, stage or rotate it while Claude may be writing. Rotation requires an
acknowledged cutoff, exact archive digest, and a fresh active ledger that links
the archive.

## 3. Update documentation by ownership

Prune and synthesize; do not append another copy of current truth:

- `README.md`: two-minute plain-English state and glossary.
- `AI_POLICIES.md`: canonical terminal-results table, policy/toggle contracts
  and durable AI conclusions.
- `BACKLOG.md`: current milestone, ordered work, blockers and exit gates only.
- `RL_PLAN.md`: model/search/data design rationale; no duplicate live queue.
- `JOBS.md`: one authoritative running section plus compact terminal stubs.
- `docs_archive/`: daily chronology and completed experiment bodies.

Put current state at the top with a date. Re-read every “running”, “next”,
“current” and “champion” claim after a result or deploy. Rebuild factual tables
from disk, git and manifests. Replace unnamed “current/champion” references with
an exact named policy at freeze time. Push every accepted commit.

## 4. Update human and production evidence

Fetch production logs read-only with `scripts/fetch_fly_logs.sh` when new human
traffic exists. The fetch stages and validates every remote JSONL before any
publish, preserves changed local copies in a timestamped ignored archive,
atomically replaces each file, and writes a source-hash manifest. Keep
`logs/local/` out of human
mining. Build a fresh versioned corpus with `shengji.rl.human_shards`; require
source/producer/encoder hashes, explicit replay/rejection counters and
pseudonymous decision sidecars. Do not merge it into training automatically:
banker rows generated under the private-kitty encoder drift are quarantined,
and raw human choice/round return is a proposal or BC control—not strength
truth—until a declared split and counterfactual Teacher gate pass.

For release 17, monitor ordinary and concurrent-room bot timings, stale-search
discards, WebSocket responsiveness and X-ray isolation. Keep the runtime
rollback (Fly release 16) separate from the policy rollback (`mc-strong`); the
project owner is the deploy/rollback decider. See `DEPLOY.md`.

## 5. Cleanup code and artifacts safely

Behavior-preserving cleanup includes dead imports, duplicated validation,
superseded one-off launch helpers and stale comments. Run proportionate focused
tests plus a smoke game; policy/sampler changes need their exact replay and
counter checks. Deleting a measured-rejected toggle body remains a project-
owner decision.

Before moving or deleting any run artifact, inspect its exact path, owner and
open handles (`lsof`). Never touch evidence namespaces, checkpoints in the
ladder, source game logs, partials/finals from a live or failed one-shot run, or
anything a process has open. Completed history is compacted by archive pointer,
not by destroying its only bytes.

## Standing rules

- Screens select; only fresh paired confirmations establish strength.
- Never deploy an unproven policy or silently change the named reference.
- Preserve failed evidence and exact non-PASS verdicts.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Measure before adopting, and keep human data/checkpoints out of git.
