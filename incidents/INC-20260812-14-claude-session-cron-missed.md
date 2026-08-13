# INC-14: Session-only reviewer cron missed a launch-blocking cycle

**Date**: 2026-08-12, expected wake 15:11 EDT; detected 15:22 EDT

**Severity**: S3 — highest-value Cloud capacity sat idle behind a missed review

**Status**: contained operationally; scheduler root cause awaiting Claude's
explanation

## What happened

The exact S4 recovery-v2 packet-review request was present in the canonical
ledger at 15:00 EDT and was the first named review blocker. Claude's recurring
job `c591827b` was scheduled for every hour at `:11`, but it produced no 15:11
timeline event, ledger write, PR progress note or verdict. Cloud therefore
remained reserved and idle rather than starting the reviewed multi-day S4
strength run.

This was not inferred only from a quiet ledger. The local Claude job timeline
and `state.json` both stopped at 14:54 EDT, and `hourly_review_state` remained
at the prior review commit. The scheduled-task record explicitly identifies
the job as `durable:false` and session-only.

## Impact

- The 16-core Cloud worker remained idle from the expected review wake onward.
- The S4 launch was delayed; no admission or gameplay was started.
- No evidence, outcome, production state or predeclared population was touched.
- Mini and Air continued their authorized strength screens normally.

## Root cause

The immediate cause is a missed scheduler invocation, not a slow review: no
review process event exists for the scheduled time. The deeper reason the
session self-wake did not run is still pending Claude's inspection. The known
risk is that the task is session-only and non-durable, so it is not an adequate
sole dependency for launch-critical review coordination.

## Repair and prevention

1. Ask Claude to inspect `CronList`, explain the missed invocation and recreate
   or repair the recurring job.
2. If Claude cannot offer durable scheduling, move the wakeup to a real system
   scheduler such as `launchd`; the Claude session may still perform the review
   after being activated.
3. Record ephemeral `last_started`, `last_finished` and `next_due` telemetry so
   a missed wake is distinguishable from an active long review.
4. For reviews expected to exceed five minutes, post a non-authorizing
   `REVIEW_IN_PROGRESS` PR comment.
5. When a named launch blocker exists, decide it before broad PR enumeration,
   fleet reporting or rolling audits; unchanged status does not belong in the
   append-only review ledger.

## Lesson

**A review protocol is only as available as its wakeup mechanism.** Byte-exact
adversarial review protects evidence once it runs; a non-durable session cron
cannot by itself guarantee that a ready packet is reviewed on schedule.
