# INC-21: R4 paid confirmatory costs before establishing BELIEF signal

**Date**: 2026-08-29

**Severity**: S3 — wasted-compute and delayed-learning risk

**Status**: closed as a process failure; the sealed inner terminal was
independently verified and the outer route is
`REFUSE_INCOMPLETE_OR_INTEGRITY`

## What happened

BELIEF R4 was built and operated like a final confirmatory experiment before
the project had a cheap answer to the exploratory question: does the learned
belief model improve held-out ownership prediction enough to merit a larger
program?

The run accumulated strict freezes, one-shot test-opening rules, deadline
contracts, byte-level artifact bindings, immediate full reconstruction and a
separate independent verifier. These controls protected the evidence, but the
pipeline did not first publish a cheap, reusable learning checkpoint with
training curves, calibration diagnostics, controls and an honest provisional
verdict. Late failures and performance defects therefore delayed the first
scientific answer and repeatedly converted engineering fixes into multi-day
operations.

R4 completed training, calibration selection and one-shot test scoring. Its
sealed inner terminal was independently verified, but the outer route refused
because reconstructed resource accounting exceeded the frozen cap. The inner
primary test was strongly positive, while the mandatory permuted-label control
was also unexpectedly positive. R4 therefore failed to distinguish genuine
behavioral belief learning from a nonbehavioral geometry, constraint or
estimation channel. The absence of an admissible answer after the elapsed
engineering and compute cost is the process failure.

## Impact

- Compute and review attention were spent proving provenance and replayability
  before the model had earned confirmatory-scale investment.
- Long stages were coupled: a late failure could strand valid capture, cache,
  checkpoint, calibration or scoring work behind a spent admission.
- Immediate reconstruction repeated expensive work instead of consuming
  independently sealed intermediate receipts.
- Some full-DAG runtime, deadline and recovery behavior was discovered only
  after the scientific namespace was active.
- The project still lacked a timely datapoint on the central hypothesis while
  infrastructure complexity continued to grow.
- The final primary model signal was large but uninterpretable: the real model
  improved mean Brier by 81,468,993 ppb (21.40% relative; 8/8 members positive),
  while the label-permutation control also improved by 28,404,787 ppb with a
  positive lower bound and therefore failed on demand.
- A late resource-accounting refusal took precedence over already-sealed model
  scores, so the official route could not express the useful-but-inconclusive
  diagnostic result directly.

## Root and contributing causes

1. **Exploratory and confirmatory modes were conflated.** Leakage and mechanics
   checks were necessary, but final-publication provenance and one-shot test
   ceremony were applied before a positive DEV signal existed.
2. **The artifact graph was not resumable enough.** Scientifically reusable
   stages existed, but the terminal contract still coupled scoring,
   integrity, reconstruction and outer publication too tightly.
3. **Verification duplicated computation.** Immediate and independent
   reconstruction re-scored or re-derived work that could have been sealed
   once and independently checked from receipts.
4. **Capacity checks did not cover the exact full DAG.** Component benchmarks
   did not adequately price the serial integrity and reconstruction tail.
5. **Progress stopped at important boundaries.** Scoring exposed progress,
   while the long integrity tail did not expose useful completion or ETA
   telemetry.
6. **Review optimized for fail-closed integrity, not time-to-learning.** A
   check could be individually sound while the composition made the scientific
   question unnecessarily expensive to answer.

## Process changes

### 1. Separate three experiment levels

- **Exploratory:** opened-development data only; resumable; curves and controls
  visible; partial results retained and explicitly labelled; goal is to decide
  whether signal exists.
- **Mechanism validation:** moderate held-out population; hard leakage,
  mechanics and causal controls; goal is to distinguish model, data and recipe
  failures.
- **Confirmatory:** immutable population, one-shot test and independent
  reproduction only after preregistered exploratory entry criteria pass.

No future lane may enter confirmatory mode merely because its infrastructure is
ready.

### 2. Require an early learning checkpoint

Before any multi-day confirmatory run, publish on opened data:

- train/select curves and calibration by epoch;
- comparator and negative-control curves;
- powered sample counts and uncertainty;
- invariant failure counts;
- examples of large errors;
- a predefined continue/repair/stop decision.

### 3. Seal and resume each expensive stage

Capture, labels/references, tensor cache, checkpoints, calibration scores, test
scores, integrity receipts and terminal publication must be separate immutable
artifacts. A failure after one boundary resumes from that boundary. Valid
score-free or already-consumed one-shot artifacts are never deleted merely
because a later stage failed.

### 4. Run one expensive computation once

Independent verification should verify immutable inputs, code, receipts and
outputs. It must not repeat multi-hour scoring or feature construction unless
that repeated computation is the scientific estimand and its cost was reviewed
explicitly. Every proposed duplicate pass must state what independent failure
class it detects that a receipt-level verifier cannot.

### 5. Rehearse the exact DAG and failures

Before scientific freeze, a bounded full-DAG rehearsal must exercise the real
controller and process topology, including deadline, cancellation, crash after
seal, resume, outer publication and independent verification. Helper-only
tests and per-stage benchmarks are insufficient.

### 6. Bind performance to admission

Every stage longer than 30 minutes must expose completed/total work, ETA,
current worker/core utilization, memory and last durable checkpoint. Capacity
must measure the exact production DAG and include serial tails. A scientific
freeze records why each worker count and wall cap was chosen.

### 7. Review proportionality explicitly

The prelaunch review must answer four questions in addition to correctness:

1. What is the cheapest artifact that can falsify the hypothesis?
2. Which work is duplicated, and why is each duplicate necessary?
3. From which exact durable boundary does every failure resume?
4. Are all available cores used where the algorithm permits parallelism?

## R4-specific remediation

- R4 is over. Do not rerun training, scoring, reconstruction, the verifier or
  the spent one-shot test opening.
- Preserve the sealed checkpoints, calibration artifacts and terminal scores
  for explicitly labelled diagnostics on opened-development data.
- Keep R5 paused. Before another large BELIEF run, explain the positive
  permuted-label control with a cheap candidate-vs-control-vs-REF-C diagnostic
  that publishes curves and stratum breakdowns while it runs.
- Require the real candidate to beat both REF-C and the negative control at a
  preregistered margin before scaling. Do not post-hoc subtract the R4 control
  and call the remainder a result.
- Treat the 21.40% primary improvement as evidence that the pipeline learned a
  predictive channel, not as a behavioral-belief, sampler or strength claim.

## Final diagnostic evidence

- Official route: `REFUSE_INCOMPLETE_OR_INTEGRITY` with
  `recomputed-resource-cap-exceeded`.
- Primary synthetic test: REF-C Brier 0.380757107 versus candidate
  0.299288114; mean improvement 0.081468993; one-sided bootstrap lower bound
  0.080604363; 8/8 member seeds positive; primary row `passed=true`.
- Permuted-label control: mean improvement 0.028404787; bootstrap lower bound
  0.027924301; `passed=false` because the lower bound was unexpectedly
  positive.
- Human-mixture selection: not retained on 28 human rounds; mean difference
  versus synthetic-primary -0.000985843 with a lower bound below zero.
- Human transfer: only five rounds / 51 decisions and descriptive; the two
  cohorts were indistinguishable at that precision.

## Lesson

Correctness is a constraint on learning, not a substitute for learning. Earn
confirmatory rigor with a cheap positive signal, then spend it once.
