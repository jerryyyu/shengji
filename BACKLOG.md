# Backlog

Last reconciled: **2026-09-09 (release 21 W32 play / hybrid-bury ship pending)**. This file is the prioritized
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
| **LIVE / RESTRICTED TEST** | **W32 serving — Codex, #300 / #310** | Fly release 21 is observed as W32 PLAY with HEURISTIC BURY, unchanged 512MB/shared CPU. The prior public W32 round completed in 604.808s; 63 bot play turns, compute median/p95/max 5.358/27.763/122.273s, no worker errors. | Retain [rollout evidence](W32_FLY_SERVING.md); continue monitoring long-tail latency. | Do not infer hybrid bury is live; no active-game interruption, resize or extra replica. |
| **AUTHORIZED / PENDING DEPLOY** | **Hybrid bury integration — Codex, PR #323** | Merged at `ec7f27ad`; prepared `mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`, unchanged compact `fd6bb411` / source `3cd27716`, 2s cooperative deadline with heuristic fallback. Current release 21 still uses heuristic bury. | Primary owns deployment and health-source-of-truth confirmation. | Research had no deadline/fallback; hybrid vs heuristic was +0.03644 `[+0.01164,+0.06024]` utility and +1.62 pp `[+0.56,+2.68]` wins on 1,976 deals; hybrid vs MC unresolved and kitty≥80 was 4 vs 0 heuristic. Native actual-consumer smoke 11/11 and focused boundary/registry/config tests 17/17 passed. |
| **FUTURE INVESTIGATION** | **Model-to-search follow-up — Codex, coordinated with Claude** | Prior-assisted admission, learned continuations, harvest performance and v3 features remain separate mechanisms; bury completion does not close them. | Use retained model/search diagnostics to justify a specific next comparison, not an automatic sweep. | Preserve existing negative/neutral continuation and depth results; no new run is queued by this update. |
| **COMPLETE** | **W32 engineering integration — Codex** | A+B+C W32: +0.1387 levels/round [+0.0645,+0.2168] on 256 opened rank-2 deals. Optimized replay preserves all saved traces and cuts decision wall 2.849× (10.61× → 3.53× production). #249 (`270bd3b9`) → #252 (`0a0d70d1`) → #254 (`0d355c4c`) merged after source PASS and CI; #251 holds the completed scaling readout. | Keep the optimization available to the deployed consumer and record the measured result; no gameplay rerun is needed to integrate unchanged semantics. | Integration alone did not authorize deployment; the later W32 rollout did. |
| **COMPLETE / PARKED** | **Tested shortlist scaling — Codex, [#248](https://github.com/jerryyyu/shengji/issues/248)** | Keep optimized K4/W32. K8, W64, doubled final search and both 26-deal double-shortlist arms did not establish improvement. Adaptive root allocation completed at +0.00577 [−0.05774,+0.07308] versus flat; selective depth at −0.00577 [−0.06736,+0.05769] and 1.5892× wall, each on 260 opened broader-rank deals. | No additional unchanged-recipe arm queued. Use retained evidence or a separately tested better checkpoint to motivate any new mechanism. [Results](AI_POLICIES.md#completed-allocation-and-depth-screens). | No equivalence, universal depth-failure or fresh-confirmation claim. Retain all artifacts; no automatic world/threshold/depth sweep. |
| **COMPLETE** | **W32 engineering closeout — Codex** | #286 prepared-lead optimization merged. [#288](https://github.com/jerryyyu/shengji/pull/288) merged at `24541d98`: fused-input full-consumer A/B had identical outputs on nine pairs, 1.3324× speedup on two huge zero-reuse follows, neutral small panel with mixed individual timings. | Retain the source and measured scope; no further capacity or reconstruction run. | Do not extrapolate to whole-game speedup, multiply different-host ratios or change live workers/production defaults. |
| **P1** | **Model/data — Claude** | The earlier ACDEF v2 − ACD v1 `+0.0779` result did not replicate. Claude's five-window random-effects pooled contrast is `−0.0064 [−0.0412,+0.0285]`. I/J is `−0.0154 [−0.0455,+0.0148]` under its preregistered fixed-effect analysis; importing the other contrast's tau gives conditional sensitivity interval `[−0.0601,+0.0294]`. Neither resolves a generator improvement. | Preserve completed evidence; consult the latest [review ledger](HANDOFF_REVIEW.md) for Claude's active work. | `tau_paired ≈ 0.0290` is uncertain and contrast-specific, not a universal SE floor. Lower offline CE has not reliably selected stronger search checkpoints. Retain model/data provenance and independent-deal boundaries. |
| **COMPLETE** | **PT-Luna efficiency and quality — Codex** | #246/#275/#280 merged; #247 superseded with source archived. All 52 deals / 104 mirrored rounds complete. Batch4−compact1: −0.1058 [−0.2885,+0.0769] levels/round alongside 2.27× fewer reported tokens/decision and 1.70× serial provider throughput. Equal quality is not established. | Reuse the [completed readout and native harvest](server/runs/luna_quality_gameplay_tranche1_result_20260906.md): 3,900 fit + 3,852 validation records, losses included and provenance retained. Historical teacher bridge remains separate. No rerun required. | Seven shared-response waves limit deal-bootstrap inference; opened validation stays out of fitting and fresh confirmation. No historic-teacher equivalence, subscription-quota saving or automatic data promotion. |
| **P2** | **Fresh strength confirmation** | W32 is deployed by explicit product decision; earlier screens and the bury confirmation have their own limited claims. | A future challenger must name its exact live/reference parent, fresh population and useful work/behavior control. | Separate deployment from proof of superiority and candidate selection from confirmation; no new run is launched by this queue entry. |
| **CLOSED** | **BELIEF R4 / R5** | Original R4 test scored +21.40% Brier but failed the label control; outer resource/integrity refusal. Separate #179 DEV diagnostic: `NO_PRIMARY_POLICY_SIGNAL` (weights ≈ uniform, 1/104 flips, paired value exactly 0). | [All 18 reviewed PRs closed](https://github.com/jerryyyu/shengji/issues/217#issuecomment-5588118823), with exact heads reachable from permanent archive tags. [Preservation scope](RL_PLAN.md#r4-and-r5) is verified, not a full Mini dataset copy. | No research restart or artifact deletion. Original test is spent; any later confirmation needs a new disjoint population. |
| **COMPLETE** | **Original PT-Luna isolated collection** | Five attempts, one complete 32-game dataset retained; failed predecessors remain engineering evidence. | Reuse within its data contract. New bounded efficiency experiments are tracked separately above. | No retrospective upgrade of predecessor quality or independence. |
| **P2** | **Production-policy quality gaps** | User-reported bare-point / weak-fallback / point-insensitive play remain diagnosis surfaces. | Replay production decisions, classify cause, test one causal treatment with a matched null. | No blanket rules. |

## Immediate sequence

0. Finish the reviewed close/archive disposition in #196 and gated serving
   in #300/#310. #256's older playable-registry implementation is superseded
   by main, not a merge prerequisite. Preserve unique source and outcomes;
   #272/#284/#287 default changes and #307 identity repair remain real work.
1. Retain the sealed K8 readout, keep K4, and do not escalate to K16.
2. Runs A through H are complete and local; run I is generating the first
   shortlist-produced teacher data. Data generation yields to strength
   experiments when they contend for a box. Do not take a contended host
   for a performance benchmark.
3. Retain the completed rank-diverse comparison at `bc89b557` and its
   inconclusive broader-rank estimate. Its actual allocation
   `[91260904,91261164)` is committed; PR259 documents the larger reserved range.
   Double-shortlist, adaptive root allocation and selective depth have since
   completed without a supported gain. Preserve their results; neither
   all-world depth, W128 nor more uniform rollout work follows automatically.
   #288 engineering integration is complete; retain its bounded measurements.
4. Luna collection and native harvest are complete; preserve fit/validation
   separation and mixed play-only continuation labels when reusing the data.
   Keep the direct batching contrast separate from the historical teacher
   bridge. Shared-wave sensitivity is descriptive, not a confidence interval.
   No further provider collection is queued by this completed experiment.
5. Confirm a selected policy on fresh deals with measured work controls.

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
| **A+B+C W32 + exact engineering replay** | Positive model-guided whole-round DEV screen at substantially reduced cost. The model selects the small set that expensive MC evaluates; it is not proven as a standalone final evaluator. Extra worlds/final rollouts have not shown an incremental gain. Full numbers: [AI policy ledger](AI_POLICIES.md#experimental-w32-shortlist). |
| **S4, S6, T4 learned proposals, pair-aware, global learned rankers** | Rigorous mechanism work did not establish another whole-game winner. Reopen only with a materially different axis, not a larger retry. |
| **T4 widening control** | Positive but compute-confounded; still needs a separate work-controlled confirmation before claiming widening itself won. The new W32 screen does not settle that old experiment. |
| **BELIEF V1/R3 resource failures** | They provide no learning verdict. They motivated reusable artifacts, measured scheduling, graceful truncation, progress telemetry, and the R4/R5 recovery path. |
| **PT0** | Small privileged endgame edge over heuristic/smart; inconclusive versus production MC. |
| **PT1** | Negative for the frozen scope: exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. The recovered result carries a preregistration-governance caveat and is not a clean general closure of late-game teacher search. |
| **PT-Full** | Repeated true-world search recovered a bad single-world collapse but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | All fixed perfect-information consumer arms were negative versus both required parents; local bare-point improvements did not transport. |

Exact numbers, packet identities, incidents, and reviewer findings remain in
`HANDOFF_REVIEW.md`, `incidents/`, and the dated archives.
