# Shengji agent workflow

Use the smallest workflow that produces a working, measured result. The primary
Sol thread owns requirements, architecture, research judgment, integration,
external authority, heavy execution and final conclusions.

## Forward implementation first

Classify proposed work as semantic implementation, focused validation, or
administrative bookkeeping. Prefer the first two. A hash, receipt, marker,
dashboard row or file's presence is never evidence that a capability works.

- Build the real producer-to-consumer path before polishing orchestration.
- Keep a forward cursor. Replay only when input meaning, the producing source,
  the target revision, or consumer compatibility changed, or a run disproved
  the previous output.
- Replay only the affected dependency cone. Missing or stale administrative
  metadata does not invalidate otherwise valid output.
- Content hashes identify material source, input, checkpoint and result bytes
  at trust boundaries. Verify them at publication and first consumption; do
  not turn repeated hashing or identical reconstruction into roadmap credit.
- Preserve valid completed shards, datasets and checkpoints across downstream
  repairs. Never use a stale artifact with a semantically changed producer.

## Long-running work

Before committing hours or opening a one-shot split:

- review the complete DAG through final scoring, reconstruction and verification,
  including the critical path, fan-out/fan-in, duplicate work, resume boundary
  and every terminal/refusal route;
- benchmark the exact heavy path on the intended host, profile the bottleneck,
  and size CPU, memory, storage and deadline from measured work;
- use all safe cores for independent work and record measured scaling; do not
  stack competing heavy jobs merely to report utilization;
- run the smallest representative end-to-end rehearsal that exercises the real
  producer and consumer without becoming a tuning set;
- publish progress, active workers and ETA at a stage-appropriate interval no
  longer than 60 seconds for opaque multi-hour stages;
- make material nodes atomic, immutable, idempotently reopenable and resumable;
  failure must leave a typed diagnostic and preserve completed work.

Optimize the path before scaling the population. Align with the user before a
design adds a duplicate multi-hour reconstruction or integrity pass. An
independent reproduction must answer a meaningfully independent question, not
call the same implementation again.

For any long-running research DAG:

- Seal the first interpretable scientific result before optional or independent
  reconstruction. Track later verification status separately; a verifier
  failure must not erase valid datasets, checkpoints or already sealed results.
- A deadline at a completed node is graceful truncation, not automatic loss.
  Seal the best valid completed boundary with an explicit truncated status.
- Build and exercise recovery before the one-shot opening. Recovery reuses
  byte-bound valid inputs and completed checkpoints and reruns only invalid or
  incomplete descendants.
- Rehearse the exact production terminal path, not just training or helper
  functions. A witness must reach the recorded output at the altitude where a
  regression would matter.
- Do not raise a frozen resource cap merely because the measured projection
  exceeds it. Any cap change needs an independent rationale, renewed headroom
  analysis and explicit review.
- Prefer one optimized critical-path owner. Do not keep serial and optimized
  copies competing for hosts unless the fallback has a named, still-useful role.

## Reviews and evidence

- Ask for review only when PASS directly unblocks a named capacity run, freeze,
  one-shot execution, merge or deployment.
- Make one launch-ready source packet: complete dependency cone, exact command,
  success and failure witnesses, measured resources and explicit authority.
- Add another review only after a load-bearing defect or material source
  change. Keep delta review scoped to the changed surface and preserve the
  unaffected prior verdict.
- Use a separate immutable freeze review only when its measured artifacts
  cannot exist during source review.
- A consolidation PR names every superseded PR. After the consolidation merges
  and its source is verified on `main`, close those PRs and remove only branches
  that hold no unique evidence or active-run ancestry.
- During early research, optimize for the cheapest falsifiable learning. Apply
  full one-shot rigor after the approach has enough signal to justify it.
- Keep correctness, performance, calibration and gameplay strength as separate
  claims. No diagnostic or capacity receipt authorizes deployment.

## Native Codex orchestration

- Keep simple questions, single-file changes and tightly coupled work in Sol.
- Delegate only concrete, independent work. Prefer `luna_explorer` for
  read-only discovery, `luna_implementer` for resolved implementation capsules,
  and `terra_reviewer` for risk-justified independent review.
- A Luna capsule names owned files or symbols, invariants, forbidden changes,
  acceptance checks and stop conditions. Never assign overlapping write
  surfaces. Use at most three concurrent subagents.
- The primary agent inspects every resulting diff and its validation evidence.
  Parallel workers prepare support work; they do not become competing truth.
- Preserve unrelated user changes. Never use `git add .`, and never commit,
  push, merge, deploy or launch merely because a subagent finished.

## Project records

`HANDOFF_ACTIVE.md` owns current fleet state and the single actionable review
ask. `HANDOFF_REVIEW.md` owns durable review authority. `BACKLOG.md` owns ordered
work, `RL_PLAN.md` the technical roadmap, `AI_POLICIES.md` measured policy
evidence, `RESEARCH_PRINCIPLES.md` scientific doctrine, and `incidents/`
process failures. Do not create a parallel documentation framework.

Native setup and rollback instructions are in `CODEX_WORKFLOW.md`.
