# Daily maintenance routine

Last rewritten: 2026-08-12. This is the canonical checklist, not proof that a
cron/loop is installed or firing. A scheduled session must record its actual
next wake and last successful execution; never infer that from this file.

## 0. Reconcile the checklist with reality

Recurring prompts rot. Before acting, compare the named champion, live roots,
run IDs, scripts and owners with `README.md`, the top of `BACKLOG.md`, the
process list and exact manifests. Correct the schedule/checklist before using a
stale instruction. A status command returning no rows is not automatically an
all-clear.

Recurring reviewers must keep a small machine-readable heartbeat with
`last_started`, `last_finished`, `next_due` and the exact current blocker.
Bound or rotate verbose session output separately; an ever-growing transcript
is not a heartbeat and can make a healthy scheduler look opaque.

## 1. Establish live fleet truth

Run `server/scripts/fleet_status.sh` as a first-pass convenience, then verify
each important job at its actual root. The script inventories Python processes
host-wide and resolves each process's command and working directory, including
isolated evidence worktrees. It tails content only from an explicit allowlist
of reviewed score-free progress streams; every other recent evidence file is
reported by metadata only. It remains a convenience view, not authority by
itself.

For every live job record:

- host, checkout, exact git SHA and dirty state;
- supervisor/worker PIDs, elapsed time and CPU;
- immutable run ID, parent/receipt/preparation identities and namespace;
- latest score-free heartbeat/progress and whether every expected worker lives;
- terminal/final/partial files by metadata only when outcomes are still sealed.

Before declaring a job dead or a host idle, all four views must agree: the
expected PID set, a broad unfiltered Python inventory, per-worker heartbeat or
log modification times, and terminal output count. A missing tool, SSH error,
or zero rows from a remembered-name filter means `UNKNOWN`. Never launch a
replacement until the old cohort is positively proven absent. See INC-12.
The inverse is also true: a broad command-line match does not prove a worker is
alive. Persistent tmux/shell/supervisor processes may retain old child-command
text. Any launch-blocking survivor check must confirm the expected executable
and immutable run arguments (or an owned PID receipt), then reconcile terminal
progress and outputs. See INC-16.

Never open a partial outcome, change a stopping rule from live scores, duplicate
a one-shot run, or infer success from a filename that may be published before a
worker's final provenance check. Mini is the default host for newly authorized
long and short compute; use Air as overflow or with a recorded placement reason.
Do not migrate a healthy sealed run between machines without measured benefit
and a protocol that permits it.

Before admitting an expensive multi-process run, require an exact-host smoke
that invokes one real child through the same packet, receipt, runtime and native
binary boundary while stopping before gameplay. Packet/controller verification
alone is insufficient. After launch, confirm the full expected worker set is
still alive after at least 60 seconds and that an explicitly reviewed
score-free heartbeat advances; otherwise preserve the namespace and report a
pre-gameplay failure rather than retrying.

Do not create a second host-specific authority merely to fill a temporarily
idle machine. For a small score-free capacity test, first compare the saved
wait against the permanent revocation/supersession code needed to make two
controllers fail closed. Prefer the already-reviewed host plus another useful
job when cross-host retirement would be more complex than the experiment. This
proportionality rule never weakens scored, sealed or deployment authority.

For every one-shot freeze or admission controller, validate the complete
exact-host runtime, required environment flags, immutable inputs and command
arguments **before the first namespace write**. A refusal must leave the fresh
namespace absent. Cover this ordering with a real regression that removes a
required flag and asserts zero files. If an older controller strands even one
file, preserve and authenticate that namespace, use a new run ID, and never
silently delete or reuse it.

## 2. Reconcile results and review markers

Read the canonical working-tree `HANDOFF_ACTIVE.md` and `HANDOFF_REVIEW.md`
before consulting `origin/main` or a branch-local copy. Scan for unanswered
requests, raw PASS markers **and** HOLD findings; a PASS-only search can leave
a precise repair sitting unnoticed. Requests and marker templates must remain
indented, while signed raw markers begin at column one and occur exactly once.
A review PASS must bind the intended git/material/script digests and scope; a
prose “looks good” is not a marker. Apply actionable findings to the queue, and
open an incident under `incidents/` if a defect reached production or trusted
data.
Before consuming a raw marker, also verify that its immediately preceding
entry is an independent-reviewer heading rather than the implementer's request.
Uniqueness and valid JSON are necessary but do not establish provenance. Every
request must name one literal marker prefix; see INC-17.

When a deep review will outlive the lightweight blocker scan, post one
ephemeral `REVIEW_IN_PROGRESS` PR comment naming the exact request/head before
starting. This is coordination telemetry, never authority: it must not appear
as a raw ledger marker and cannot authorize any action. It lets the implementer
distinguish a running review from a missed schedule without interrupting the
reviewer or launching replacement work on the reserved host.

After publishing a narrow HOLD, re-read the canonical tail once before ending
the review cycle. If the exact repair and fresh hashes have already landed,
review that bounded delta immediately when practical rather than imposing an
avoidable one-hour delay. Keep author headings accurate so automation and
humans can distinguish implementer requests from independent verdicts.

When a launch-blocking request is open, bound hourly orientation to the delta,
exact identity and live safety checks needed for that request; decide it before
the broad rolling audit. Unchanged fleet snapshots and open-PR inventories are
ephemeral status, not review-ledger entries. Append only authority markers or
concrete findings so the canonical ledger remains a review surface rather than
an hourly transcript.

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

## 6. Repository-hygiene contract

Repository size is not the target; a small, legible set of authoritative paths
is. Apply these gates whenever compute leaves implementation time available:

- **Branches and PRs:** one PR owns one durable output. Do not open status-only
  PRs when the canonical ledger is sufficient. Merge independently useful,
  reviewed features; close superseded documentation PRs. A stacked experiment
  remains intact while an exact run depends on it, then moves to one tested
  integration branch on current `main`; only after that merge may its ancestor
  branches and PRs be removed. Never delete the sole copy of ignored evidence.
- **Documentation:** one fact has one owner. `BACKLOG.md` is the executable
  queue, `AI_POLICIES.md` the terminal policy/result ledger, `RL_PLAN.md` the
  research rationale, `JOBS.md` live compute, and dated archives chronology.
  Rotate append-only ledgers at an acknowledged cutoff and preserve exact raw
  bytes plus a digest. Prefer a short plain-English progress/remaining-work
  column over another protocol paragraph.
- **Code:** before deleting or merging paths, prove the old path has no runtime,
  import, CLI, registry, test-fixture, or artifact-verifier consumer. Name the
  surviving replacement, retain tests for its contract, then run the narrow
  suite plus a broader smoke boundary. Consolidate complexity that only
  duplicates launch/controller plumbing. Remove one-shot admission, exact
  identity, replay, refusal, or evidence-isolation logic only when the
  replacement is equally falsifiable.
- **Artifacts:** tag or record the exact source commit and external/internal
  hashes before pruning a worktree. Remote-branch cleanup and worktree cleanup
  are separate actions; a merged branch can still own the only local run bytes.

Reconcile open PRs, remote branches, worktrees, top-level docs and reference-
audit candidates whenever a milestone becomes terminal rather than waiting for
a large periodic cleanup.

### Pull-request and branch closeout

Run this closeout whenever a successor PR becomes self-contained or an
experiment reaches a terminal verdict. The goal is a short active queue, not
the loss of negative results or exact evidence.

1. Inventory every open PR and classify it as **merge**, **active draft**, or
   **close**. Merge reviewed, independently useful product/infrastructure work.
   Keep only live experiment leaves and their necessary stack bases open.
2. Close a PR when its exact head is fully contained in a named active
   successor, or when its terminal result and unique artifacts have been
   preserved and synthesized. Leave a closing comment naming the successor or
   terminal verdict; `SELECT NONE` closes promotion of that recipe, not the
   learning or broader hypothesis.
3. Before deleting the remote branch, prove one of these conditions:
   `git merge-base --is-ancestor <closed-head> <surviving-head>` succeeds; the
   branch is merged into `main`; or every unique artifact has a durable hash,
   archive/PR reference and plain-English conclusion in the canonical docs.
4. Never delete the exact branch of a running/sealed job, a base still needed
   by an open stacked PR, the sole copy of ignored evidence, or a branch whose
   review marker cannot be reconstructed from canonical bytes.
5. Delete the remote head after the preservation proof. Remove its local
   worktree separately only after checking dirty state, ignored artifacts,
   open processes and open file handles. Then run `git worktree prune` and
   remove stale local branches whose upstream is gone.
6. Re-run the open-PR/remote-branch inventory. A healthy steady state contains
   the small set of genuinely active experiment leaves plus reviewable product
   changes—not every historical controller layer.

At minimum, the daily pass checks for merged PR heads still present remotely,
closed PRs whose exact heads are ancestors of an active consolidated PR, and
open drafts whose stated gate is already terminal or superseded.

## Standing rules

- Screens select; only fresh paired confirmations establish strength.
- Never deploy an unproven policy or silently change the named reference.
- Preserve failed evidence and exact non-PASS verdicts.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Measure before adopting, and keep human data/checkpoints out of git.
