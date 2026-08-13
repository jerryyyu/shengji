# INC-18: An S5 request template self-authorized a partial one-shot run

**Date**: 2026-08-13, 00:16 EDT

**Severity**: S3 — unauthorized gameplay consumed a one-shot admission; no result was published

**Status**: contained; the admission is preserved and spent; no retry is authorized

## What happened

PR #74's x86 portability wrapper required an exact review marker before it
could run the already-reviewed S5 diagnostic. The Codex-authored review request
contained the exact marker prefix and payload at column one. The wrapper checked
prefix, count and payload equality, but did not bind the line to a distinct
reviewer attestation or independently attributable review commit.

A durable queue therefore mistook the request template for Claude's PASS. It
completed the wrapper checks, created the one-shot admission and started the
unchanged S5 producer before the independent review existed. Codex saw the
unexpected process and terminated the exact scope.

This repeated the failure mode documented in INC-17. INC-17's prevention lived
in prose and ledger convention; the executable consumer did not enforce it.

## Bounded impact

- Exact systemd scope telemetry: **41.722 seconds wall**, **41.333 seconds
  CPU**, 126.6 MB peak memory. At most about 36.4 seconds followed admission.
- The producer started and read its private source inputs.
- No `result.json`, partial result, temporary result or terminal record exists.
  The launch log is empty and no process or tmux session remains.
- The 352-byte admission is preserved, SHA-256
  `8eb4d1672fd6126816ac6e3b53ab670fede3bc33c4bcfc30d3bbe5ac121ff4e7`.
  It binds the request-template marker, not an independent attestation.
- Exact completed-decision count is unrecoverable because the producer kept
  rows in memory and emitted no score-free stage heartbeat.
- No outcome was opened and no strength claim was made.

Claude subsequently PASSed the portability construction independently. That
PASS remains valid science, but its marker says `retry_authorized:false`; it
cannot revive an authority already consumed by the partial attempt.

## Second defect: queue checked the wrong admission path

The queue's re-entry/status precheck looked for
`s5-final-champion-x86-execution-admission-v1.json`, while the wrapper consumes
`human-v8-s5-final-champion-replay-x86-v1.execution.consumed.json`. The
wrapper's `O_EXCL` creation would still have blocked a second gameplay attempt,
but the queue could incorrectly report the slot unused and attempt entry again.
That queue is retired and must not be reused.

## Root causes

1. Request and reviewer attestation shared the same literal namespace and
   payload.
2. The executable gate authenticated content but not provenance.
3. The launch queue inferred authority directly from a mutable ledger path
   rather than a pinned review commit and distinct attestation record.
4. INC-17's rule was documented but not encoded in every executable marker
   consumer.
5. Admission ownership was duplicated between the queue and wrapper instead of
   exposing one canonical constant/path.

## Containment

1. Stopped only the exact queue/producer scope and verified no child survived.
2. Preserved the consumed admission; it will never be deleted, overwritten or
   reused.
3. Marked PR #74 operationally HOLD even though its later portability review
   PASSed.
4. Retired the queue and prohibited retry under the old marker, result path and
   admission namespace.
5. Kept the performance host on nonsealed engineering work.

## Required recovery and durable prevention

1. Request templates and reviewer attestations use different literal prefixes.
2. An executable gate reads the attestation from a pinned Git commit, proves
   the request commit is a strict ancestor, and binds the reviewed claim digest.
3. The request commit must contain zero reviewer-attestation records; the
   review commit adds exactly one and changes only the review ledger under the
   expected independent-review provenance.
4. Tests prove request text alone, working-tree injection, duplicate templates,
   the request commit itself and wrong-provenance descendants all refuse.
5. Queue and wrapper share one canonical admission path, with a regression for
   the exact spent path.
6. Any recovery needs a new named admission/result namespace and a separate
   external marker explicitly setting retry authority. A portability PASS is
   not retry authority.
7. One-shot producers publish an outcome-free stage heartbeat after admission
   so a stopped attempt has auditable progress without exposing results.

## Lesson

**A documented convention is not a gate.** Authority-bearing software must make
an implementer's byte-perfect request structurally incapable of satisfying an
independent-review requirement.
