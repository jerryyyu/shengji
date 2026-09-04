# Backlog

Last reconciled: **2026-09-04 (post-pivot)**. This file is the prioritized
decision queue, not a run log. Live processes and exact operator authority are
in `HANDOFF_ACTIVE.md`; immutable reviews and hashes are in
`HANDOFF_REVIEW.md`; research architecture is in `RL_PLAN.md`; callable policy
status is in `AI_POLICIES.md`.

Historical queues remain in `docs_archive/backlog-through-2026-08-11.md` and
Git history. Do not append dated progress blocks here.

## Program objective

Beat the live `mc-s0-report-lcb` champion on fresh mirrored whole games. The
2026-08-28..09-03 week (retrospective at ledger `0088544f`) produced five honest
adjudications and no strength learning because confirmatory-grade machinery was
applied to exploratory questions and every lane targeted an *input* to a
hypothetical future policy. The queue below inverts that: measure each lane's
ceiling first, attack the planner (the demonstrated lever: C0 with perfect
information lost, PT-Sol0 with perfect information and a flexible planner won
`+17/26`), prove transport at tiny scale before collecting more data, and apply
full rigor only to deploy claims (`RESEARCH_PRINCIPLES.md` §11-12,
`RL_PLAN.md` "Operating modes").

## Now — ordered by decision value

| priority | lane | current state | next decision-bearing output | gate |
|---:|---|---|---|---|
| **P0** | **Value V2 — DEV mode** | Jerry-directed unblock at ledger `295136ba`. Up-front pipeline review PASSed at `c4b8f7e8` (ledger `ca459e14`); the first end-to-end D64 dev run (width-8 spawn population → labels → train → calibrate → audit → sealed `terminal.json`) is live on Perf. Runs are resumable; no freeze/packet/rebind/marker/confirmation ceremony. | A sealed D64 model with its interpretation review, then D256 in the same mode. | Tier i. Score-free until sealed (private/ closed until `terminal.json`), reproducibility stamp, never-delete. Escalate to tier iii only when a V2-guided search variant approaches a deploy claim. |
| **P0** | **Ceiling screens** | Not yet run; both are days of work on existing opened roots. | Oracle-value ceiling: production search with a near-perfect leaf value vs production. Oracle-belief ceiling: production sampler given true hidden worlds vs production (C0 already suggests ≈0). | Tier i/ii. Each lane's second major spend is gated on a positive ceiling. |
| **P1** | **Luna dataset as diagnostic + fine-tune source** | `pt-luna-rpc-isolated-b0b1bd95-r1` sealed COMPLETE (32/32 games; ledger `6c71bee3`). Readable only for scoped teacher/value research. 30 predecessor games are engineering-only. Collection is CLOSED (46,729,487 tokens lane total). | (a) Where do Sol/Luna disagree with production and win, classified by mechanism (ballot, continuation, rollout allocation, objective, partnership)? (b) Fine-tune the D256-pretrained V2 model on Luna outcomes with a held-out teacher-agreement slice; does search with the fine-tuned leaf value move toward the teacher on the disagreement set? | Value targets, not action imitation (PT1's negative). No more collection until transport is shown at 32-game scale. |
| **P1** | **Search-policy variants in the RLCB paired harness** | The only harness that ever produced a confirmed gain (`+0.338 ± 0.068`). | Two or three variants derived from the Luna disagreement analysis, vs champion at equal work; promote only on the confirm bar. | Tier ii screen → tier iii confirm. |
| **P1** | **Search-capacity confirmation** | T4 uninformed widening was positive but compute-confounded (+14.8% worlds, +80.9% searches). | Three-arm design: champion, widening at champion work, widening at original-null work. | Separate from BELIEF/PT. |
| **CLOSED** | **BELIEF R4 / R5** | R4 terminal `NO_PRIMARY_POLICY_SIGNAL` (weights ≈ uniform, 1/104 flips, paired value exactly 0). R5 closed. | Reopens only if the oracle-belief ceiling screen is positive. | No belief compute otherwise. |
| **CLOSED** | **PT-Luna collection** | Five attempts; one complete dataset; consumer unproven. | — | Reopens only after transport is demonstrated. |
| **P2** | **Production-policy quality gaps** | User-reported bare-point / weak-fallback / point-insensitive play remain diagnosis surfaces. | Replay production decisions, classify cause, test one causal treatment with a matched null. | No blanket rules. |

## Immediate sequence

1. Let the D64 dev run seal; one interpretation review; then D256 in DEV mode.
2. Run both ceiling screens on existing opened roots (R4's 104 rounds, the
   26 Sol0 roots).
3. Luna disagreement analysis by mechanism; fine-tune the pretrained V2 model
   on Luna outcomes; teacher-agreement evaluation.
4. Derive search-policy variants; run them through the RLCB paired harness.
5. Nothing enters tier iii until a variant beats the champion on a paired screen.

## Entry criteria for new scientific lanes

A proposed lane enters the review queue only when it names:

1. the exact decision or prediction it changes;
2. natural dose and the smallest effect worth detecting;
3. candidate, literal parent, and behavior/work-matched null;
4. one frozen population/split and one terminal rule;
5. source/runtime/artifact identities plus recoverability behavior;
6. one consolidated review surface; and
7. for any projected multi-hour run, one pre-launch DAG audit proving there is
   no duplicate full-data integrity work, naming worker/core utilization for
   every expensive stage, demonstrating checkpoint/recovery behavior, and
   identifying the cheapest learning-bearing result before fleet scale.

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
| **PT1** | Negative for the frozen scope: exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. The recovered result carries a preregistration-governance caveat and is not a clean general closure of late-game teacher search. |
| **PT-Full** | Repeated true-world search recovered a bad single-world collapse but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | All fixed perfect-information consumer arms were negative versus both required parents; local bare-point improvements did not transport. |

Exact numbers, packet identities, incidents, and reviewer findings remain in
`HANDOFF_REVIEW.md`, `incidents/`, and the dated archives.
