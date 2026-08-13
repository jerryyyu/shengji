# INC-15: Reviewer child-boundary witness launched real S4 gameplay

**Date**: 2026-08-12, 15:38–15:44 EDT

**Severity**: S3 — unintended strength compute / confirmation population retired

**Status**: contained; old packet quarantined and disjoint replacement awaiting
review

## What happened

While independently reviewing the S4 recovery-v2 packet, Claude tried to
reproduce its child-boundary witness by calling the real controller `launch()`
inside a disposable Cloud worktree. The intended monkeypatch was supposed to
stop execution before worker creation. It patched `Progress` in the wrapper
module, but `launch()` resolves globals from the separately loaded controller
module. The patch therefore had no effect and the call started all 16 real
gameplay workers.

Codex's fleet reconciliation found the workers after roughly five minutes and
stopped only their exact process identities. The disposable namespace is
preserved. It contains admission and receipt material, a supervisor partial,
16 progress logs and 16 termination records, but no completed shard result,
aggregate or final. The formal recovery-v2 namespace was never admitted and
still contains only its review snapshot and launch-disabled packet.

## Impact

- Sixteen Cloud cores performed unintended S4 gameplay for about five minutes.
- No completed result or aggregate was published, and neither reviewer nor
  Codex observed an outcome.
- The immutable recovery-v2 packet claimed all earlier attempts stopped before
  gameplay. That statement became false, so the packet could not honestly be
  launched afterward.
- The entire 300-billion seed interval was conservatively retired. The S4
  hypothesis and test design remain alive on a fully disjoint 360-billion seed
  interval.
- Cloud immediately moved to an independently reviewed, score-free pair-ballot
  capture while the replacement S4 design receives review.

## Root cause

The immediate defect was patching a similarly named wrapper global rather than
the controller module global actually used by `launch()`.

The deeper defect was treating a monkeypatch as a safety boundary around a
gameplay-capable entry point. A reviewer process that can reach `launch()` also
holds the authority to create admissions, receipts and workers; an exception
intended to fire “before launch” is not a durable capability boundary.

The fleet check also caught an accounting discrepancy: the disposable
artifacts and observed process lifetime showed roughly five minutes of work,
not the initial two-minute estimate. Incident timing must come from process and
artifact timestamps, not recollection.

## Repair and prevention

1. Independent review must never invoke a gameplay-capable `launch()` path,
   monkeypatched or otherwise.
2. Child-boundary review uses the dedicated `validate-runtime` command or a
   construction-only fixture that has no worker-spawn capability.
3. If a required check cannot be expressed without launch authority, Codex
   performs the one authorized smoke and Claude reviews its immutable
   artifacts; the reviewer does not simulate execution authority.
4. Large-run controllers keep validation and execution as separate commands.
   Validation must not create an admission, receipt, progress file or worker.
5. Fleet monitoring inventories exact process families rather than relying on
   one expected session or command substring, and immediately reconciles any
   worker not owned by an authorized run.
6. An accidental population touch is bound into the next design. The affected
   packet and full seed interval are retired rather than retroactively rescued.
7. Reviewer heartbeat/status reports name whether any command can spawn
   gameplay and disclose start/end timestamps for every unmocked host probe.

## Lesson

**A monkeypatch is not an authority boundary.** Review code should be unable to
start gameplay by construction; careful intent inside a launch-capable process
is not enough.
