# INC-13: S4 launch passed controller review but every child refused

**Date**: 2026-08-12, 13:34–13:42 EDT

**Severity**: S3 — run admission consumed / strength compute delayed

**Status**: contained before gameplay; recovery awaiting review

## What happened

The reviewed S4 C2 packet was admitted once on Cloud and launched under its
durable supervisor. All 16 tranche-one children exited within seconds with the
same refusal: `future S4 preflight is missing`. The controller then failed
closed. No child produced a shard JSON, aggregate, final, score or outcome.

The failed namespace, packet, admission, receipt, preauthorization, child logs
and exits remain preserved. The consumed admission is not reusable.

## Root cause

C2 was a thin profile over the reviewed C1 runtime. The controller correctly
rebound C2's static capacity artifact, runner and namespace, but the child-side
receipt validator still hardcoded C1's preflight, runner, controller,
design-review and packet shapes. Packet verification never invoked that child
boundary. Focused tests checked packet construction and command names, but
mocked or skipped the real child receipt path.

The first repaired native smoke then caught a second bug: after successful
validation, an already-relative receipt argument was passed through
`relative_to(REPO)` without first resolving it.

## Impact

- One admission and one recovery cycle were consumed.
- Sixteen workers ran for only seconds; the intended multi-day computation
  never began.
- Cloud remained idle while a fresh reviewed namespace was prepared.
- No statistical population was opened and no evidence was contaminated, so
  the same predeclared seeds remain scientifically untouched.

## Repair and prevention

1. Child receipt validation now has explicit profile seams for runner,
   controller, capacity path, design-review additions and packet-only fields.
2. Recovery uses a new run ID and byte-binds the entire failed attempt,
   including zero output/aggregate/final evidence; the old namespace cannot be
   retried or overwritten.
3. The controller invokes the real child `validate-runtime` command after
   receipt creation and before progress or any gameplay worker.
4. A native Cloud smoke must build a complete packet/admission/receipt and run
   that exact child command before a large launch can receive review.
5. After launch, fleet monitoring must confirm the full worker population is
   alive after 60 seconds and that a reviewed score-free heartbeat advances.

## Lesson

**Controller validity does not prove child startability.** Any expensive
multi-process run needs an exact-host child-boundary smoke through the same
receipt, packet and runtime checks the real subprocess will execute.
