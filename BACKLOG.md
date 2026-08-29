# Backlog

Last reconciled: **2026-08-27 08:35 EDT**. This file is the prioritized
decision queue, not a run log. Live processes and exact operator authority are
in `HANDOFF_ACTIVE.md`; immutable reviews and hashes are in
`HANDOFF_REVIEW.md`; research architecture is in `RL_PLAN.md`; callable policy
status is in `AI_POLICIES.md`.

Historical queues remain in `docs_archive/backlog-through-2026-08-11.md` and
Git history. Do not append dated progress blocks here.

## Program objective

Produce a decision-grade answer on whether public-history belief learning
improves hidden-hand prediction. Finish R4, run one efficient/recoverable R5,
independently reproduce its terminal verdict, and decide whether calibrated
belief should advance into gameplay search. The production strength standard
remains a fresh mirrored whole-game comparison against
`mc-s0-report-lcb`; offline prediction or open-DEV teacher evidence cannot
promote a bot.

## Now — ordered by decision value

| priority | lane | current state | next decision-bearing output | gate |
|---:|---|---|---|---|
| **P0** | **BELIEF R4 interpretation** | Optimized calibration is live on Perf at exact reviewed source `d82ba224`; the slower Strength-Cloud lane remains a reviewed fallback. Training, reusable cache/index artifacts, and test population are already sealed; test is unopened. | Independently reopened calibration, reviewed two-lane cutover, one test opening, independently reproduced terminal verdict. | Do not stop the fallback or open test until optimized calibration seals and the existing readiness/cutover controller says `READY`. No retry or partial-outcome inference. |
| **P0** | **PT-Sol0 policy-use diagnostic** | One reviewed 26-root / 52-role Mini run is live at `e73f970e`. Fresh ephemeral `gpt-5.6-sol` agents receive exact hidden state only through a bounded engine-owned observe/rollout/play interface. | Reopened complete report comparing Sol with PT-Full A/B and C0-S; one honest conclusion on whether general reasoning can use perfect information better than the fixed consumers. | Open-DEV mechanism evidence only. No merge, BELIEF integration, strength claim, retry, promotion, or deployment. |
| **P0** | **BELIEF R5** | Source is clean and locally validated at `9c5928f2`; host-independent all-rank/human inputs are sealed. No R5 process or review is active. | One exact-Perf 104-round full-DAG rehearsal, host receipts, immutable freeze, one consolidated source+freeze PASS, then a recoverable run and independently reproduced terminal verdict. | R4 releases Perf first. Rehearsal, freeze, and execution must share exact Git/source/runtime/device identity. Preserve train/calibration artifacts, curves, graceful deadline truncation, and zero test leakage. |
| **P1** | **Belief-to-search consumer** | Design only. No offline result yet authorizes a sampler or gameplay change. PT-Full/C0 show that collapsing onto one true/likely world is not a sufficient consumer. | If R4/R5 is positive, implement the smallest belief-weighted complete-world sampler and measure post-projection calibration plus final-action flip dose before a whole-game screen. | Search stays final authority. Compare equal work against REF-C/current sampling; never expose a hidden label or use one MAP world as truth. |
| **P1** | **Absolute leaf value** | Value V1 cleanly selected none: its labels contained action signal, but 44 fit deals could not support the 212k flat model and held-out action choice was harmful. Draft V2 keeps the canonical MCTS contract `V(any legal state) -> terminal outcome distribution`, uses one state per independent deal, distinguishes state/proposal teachers from the one frozen numeric continuation labeler, and separates the value learner from its later rollout/search consumer. | Review `VALUE_AFTERSTATE_V2_ABSOLUTE_LEAF_DESIGN.md`, then run only its score-free exact-32-deal label/teacher-economics census. Implement the learner only if D256 fits; a later full-DAG capacity gate chooses the largest outcome-blind D256/D512/D1024 tier whose exact independent source supply exists and whose natural/control training, audit, and reconstruction project to at most six hours under the immutable 12-hour cap. | No V1 retry or heldout reopening. PT-Sol/Luna/human states require fresh deal clusters and common-policy relabeling. No PUCT, policy head, BELIEF integration, or one-trick consumer is bundled into V2. |
| **P1** | **Privileged/full-information teacher successor** | PT0 found small late-endgame headroom over weak baselines but not production; PT1 was a clean negative; PT-Full and C0 selected none. PT-Sol0 is the current meaningfully different probe. | After PT-Sol0, choose one axis only: bounded-depth partnership search, learned full-information Q/policy, or stop. | A perfect-information consumer must first beat public production under exact state before it can justify distillation or BELIEF use. |
| **P1** | **Search-capacity confirmation** | The historical T4 uninformed widening arm was positive against champion but used 14.8% more accepted worlds and 80.9% more searches, so “same-work widening won” is not established. | Three-arm design: champion, widening at champion work, widening at original-null work. | Keep this separate from BELIEF and PT. It is a strength hypothesis, not a way to keep an idle host busy. |
| **P1** | **Performance engineering** | Native rollout work and R5 cache/projection parallelism materially reduce wall time with byte-identical results. Calibration projection on Perf uses 16 workers; training/cache artifacts are reusable. | Retain exact parity while profiling the next actual bottleneck; use all cores when the operation is safely parallel. | Performance is an enabler, not strength evidence. Never benchmark beside or modify a live sealed run. |
| **P2** | **Production-policy quality gaps** | User reports around bare points, weak fallback leads, and point-insensitive play are real diagnosis surfaces. C0 avoided some local symptoms but still lost whole rounds. | Replay current production decisions, classify legality/ballot/search/continuation/value cause, then test one causal treatment with a matched null. | Do not ship a blanket “never play a 10” rule or infer that BELIEF alone fixes policy/value defects. |

## Immediate sequence

1. Monitor PT-Sol0 and R4 without interference.
2. When optimized R4 calibration seals, run the already-reviewed readiness,
   serial-stop, cutover-receipt, one-test-open, and terminal-reopen sequence.
3. Record the R4 prediction verdict and whether any calibration/mechanics gate
   failed.
4. Release Perf to the exact R5 rehearsal and freeze; request one review only.
5. Run R5, reproduce its terminal result, and make the BELIEF gameplay-search
   advance/stop decision.
6. Interpret PT-Sol0 separately and use it to choose or close the next
   full-information teacher axis.

## Entry criteria for new scientific lanes

A proposed lane enters the review queue only when it names:

1. the exact decision or prediction it changes;
2. natural dose and the smallest effect worth detecting;
3. candidate, literal parent, and behavior/work-matched null;
4. one frozen population/split and one terminal rule;
5. source/runtime/artifact identities plus recoverability behavior; and
6. one consolidated review surface.

Run a cheap score-free census or rehearsal first when dose, runtime, or
candidate geometry is unknown. Rehearsals prove mechanics, not efficacy, and
must never be used to choose scientific seeds or thresholds.

## Operating constraints

- No test opening before a durable pre-test readiness artifact proves that
  training, calibration, curves, and exact identities independently reopen.
- Expiry yields a sealed, explicitly truncated result at the best complete
  common epoch when the design permits it; it must not erase healthy learning
  or masquerade as convergence.
- Preserve reusable capture, reference, index, cache, checkpoint, and
  calibration artifacts when their contracts permit exact reuse.
- Progress must expose completed/total units, percent, elapsed time, ETA, stage,
  worker identity, and deadline headroom without exposing outcomes.
- Use diverse trump ranks and player/deal-disjoint human data. Human moves are
  behavior/proposal evidence, not strength labels.
- Keep facts, actor-private observations, probabilistic beliefs, and privileged
  labels typed and separate. Actor-visible runtime bytes must be invariant to
  hidden-world twins.
- Negative and refused results remain evidence. Never delete them, retry a
  spent namespace, or convert a mechanism PASS into deployment authority.
- Exact raw markers and chronology belong only in `HANDOFF_REVIEW.md`; current
  review asks belong only in `HANDOFF_ACTIVE.md`.

## Durable conclusions shaping the queue

| result | conclusion |
|---|---|
| **RLCB confirmed and deployed** | Two-stage Monte Carlo remains the only confirmed production strength gain and the named parent for challengers. |
| **S4, S6, T4 learned proposals, pair-aware, global learned rankers** | Rigorous mechanism work did not establish another whole-game winner. Reopen only with a materially different axis, not a larger retry. |
| **T4 widening control** | Positive but compute-confounded; requires the three-arm confirmation above before claiming widening itself won. |
| **BELIEF V1/R3 resource failures** | They provide no learning verdict. They motivated reusable artifacts, measured scheduling, graceful truncation, progress telemetry, and the R4/R5 recovery path. |
| **PT0** | Small privileged endgame edge over heuristic/smart; inconclusive versus production MC. |
| **PT1** | Clean negative: exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. |
| **PT-Full** | Repeated true-world search recovered a bad single-world collapse but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | All fixed perfect-information consumer arms were negative versus both required parents; local bare-point improvements did not transport. |

Exact numbers, packet identities, incidents, and reviewer findings remain in
`HANDOFF_REVIEW.md`, `incidents/`, and the dated archives.
