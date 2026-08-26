# Active Claude/Codex handoff

> Current operational truth and exact review asks only. Historical evidence
> belongs in `HANDOFF_REVIEW.md` and Git history. Do not repeat a superseded
> review. There is no active review ask below.

Last reconciled: 2026-08-25 22:38 EDT.

## Immediate objective

1. Leave the live R4 completion run untouched through calibration, one held-out
   test opening, terminal verification, and independent interpretation.
2. Preserve the spent, result-free PT1 `r6` evidence. Diagnose its first-wave
   resource-cap refusal without retrying or opening hidden scientific bytes.
3. Keep R5 held until R4 is terminally interpreted and a final fresh Perf
   packet binds that result. R4 and R5 share one population and are not
   independent replications.

## Live execution — R4 completion-only

R4 requires no further source/freeze review and is active on Strength Cloud
under the exact `e10cb3d/r3` PASS marker in ledger commit `68e4522f`.

- unit: `belief-r4-completion-e10cb3d-r3.service`
- source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`
- freeze SHA-256:
  `59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4`
- evidence: `/opt/belief-r4-completion-v1-r3`
- phase: calibration, 1/4 outer stages, test unopened
- last direct health check, 2026-08-26 02:30 UTC: active/running,
  `NRestarts=0`; cgroup peak `20,569,944,064` bytes below the 24 GiB cap

Do not modify, restart, delete, merge, or infer a result from the outer 25%
counter. It advances only after the whole calibration stage publishes.

## PT1 `r6` — terminal resource refusal, no result

After Jerry reported the narrow `r6b` operator review PASS, Codex invoked the
corrected launcher once using the existing source+freeze marker at ledger
commit `31cca4d18bd1c2254f2dfbec9fd8a639cb265ee5`.

- source `e27240e46981cae9db099236113a2b655d88570c`
- launcher SHA-256
  `ca7743de78a65c9599eee8aae0b0e1c245f44eb6178598f47e683856bc5c9fef`
- freeze SHA-256
  `64352206b3e930eefa431c3b358356915bd5cb65708d0056c7711b7ef367d8dc`
- evidence `/Users/jerryyu/Projects/shengji-pt1-evidence-e27240e-r6`
- outcome: `FAILED`, `0/416`, `failure_code=cli_failure`, retry false
- exact CLI refusal: `execution scientific cap exceeded`
- no group artifact was admitted; score/action bytes persisted=false
- the 930.72-second deadline was not exhausted; about 14.4 minutes remained
  when the refusal was inspected

The first ten-state wave completed in memory, then failed the aggregate frozen
resource envelope before any group could publish. The receipt does not identify
which resource dimension exceeded its cap. Preserve this root; do not retry,
delete, reinterpret as a teacher verdict, or inspect the spent scientific
secret. A successor must first add a sanitized failing-cap dimension/observed
value receipt and repair the capacity population so the scientific population
cannot exceed an unmeasured envelope.

## Review queue

None. Do not review a PT1 successor until Codex has a narrow diagnosed repair
and fresh unspent freeze. Do not review R5 until R4 is terminally interpreted.

## Held — not an active review

PR #148 at exact head `7e14b529065383baee152c9dd2b8d3473627235c`
is source/CI green. Its old Perf freeze is boot-bound and must not be reused
after the host power cycle. After R4 terminal interpretation, Codex will build
one fresh final R5 packet binding the R4 result and request one consolidated
source+freeze review. Performance Cloud is offline and is not currently needed.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | R4 completion active in calibration | monitor only; interpret terminal result |
| Mini | idle after PT1 `r6` terminal cap refusal at 0/416 | preserve evidence; diagnose without retry |
| Performance Cloud | offline; no R5 job | hold until R4 interpretation |
| Air | idle / not required | none |

## Authority boundaries

No active packet authorizes merge, retry, deployment, promotion, gameplay, or
a strength claim. R4 is already running once under its exact marker. PT1 `r6`
is spent and result-free; no retry is authorized. R5 remains held.
