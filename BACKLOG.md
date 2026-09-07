# Backlog

Last reconciled: **2026-09-06 (completed scaling screens, fused-input A/B and teacher continuation)**. This file is the prioritized
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
| **COMPLETE** | **W32 engineering integration — Codex** | A+B+C W32: +0.1387 levels/round [+0.0645,+0.2168] on 256 opened rank-2 deals. Optimized replay preserves all saved traces and cuts decision wall 2.849× (10.61× → 3.53× production). #249 (`270bd3b9`) → #252 (`0a0d70d1`) → #254 (`0d355c4c`) merged after source PASS and CI; #251 holds the completed scaling readout. | Keep the optimization opt-in and record the measured result; no gameplay rerun is needed to integrate unchanged semantics. | No deployment or production-default change. |
| **COMPLETE / PARKED** | **Tested shortlist scaling — Codex, [#248](https://github.com/jerryyyu/shengji/issues/248)** | Keep optimized K4/W32. K8, W64, doubled final search and both 26-deal double-shortlist arms did not establish improvement. Adaptive root allocation completed at +0.00577 [−0.05774,+0.07308] versus flat; selective depth at −0.00577 [−0.06736,+0.05769] and 1.5892× wall, each on 260 opened broader-rank deals. | No additional unchanged-recipe arm queued. Use retained evidence or a separately tested better checkpoint to motivate any new mechanism. [Results](AI_POLICIES.md#completed-allocation-and-depth-screens). | No equivalence, universal depth-failure or fresh-confirmation claim. Retain all artifacts; no automatic world/threshold/depth sweep. |
| **P1** | **W32 engineering closeout — Codex** | #286 prepared-lead optimization merged. [#288](https://github.com/jerryyyu/shengji/pull/288) fused-input full-consumer A/B completed: identical outputs on nine pairs, 1.3324× speedup on two huge zero-reuse follows, neutral small panel with mixed individual timings. | One consolidated source+measurement review for #288 merge; no further capacity or reconstruction run. | Do not extrapolate to whole-game speedup, multiply different-host ratios or change live workers/production defaults. |
| **P1** | **Model/data and PUCT — Claude** | A+B+C complete-world MLP is the measured W32 checkpoint. A dated peer report says Run D sealed 03:27 ET, Run E launched on Perf, and A+C+D was syncing to Mini at 03:28; this is not live status. D64 remains a small prediction diagnostic, not this consumer's certificate. The existing ballot-rooted PUCT ladder is closed. | Test new checkpoint quality in the actual full-legal shortlist; keep model changes separate from K/W/N/R changes. Future shortlist-rooted depth is a distinct experiment. | No claim that within-ballot metrics, more rows or tree depth imply stronger play. Keep independent deal counts and continuation identities explicit. |
| **P0** | **PT-Luna efficiency and quality — Codex** | Historical teacher bridge [#275](https://github.com/jerryyyu/shengji/pull/275) complete and distinct from gameplay. [#280](https://github.com/jerryyyu/shengji/pull/280) first eight deals / 16 mirrored rounds complete: +0.125 [−0.25,+0.50] batch4 levels/round, 2.324× reported-token efficiency, quality inconclusive. The fixed remaining 44 deals have separate 45M-token / 18-hour approval. | Finish that continuation, publish the fresh 44-deal readout and explicitly exploratory 52-deal pool, then native fit/validation harvest including losses. Prepared readout reports shared-wave dependence without changing the original paired-deal estimates. | No automatic extra tranche, historic-teacher equivalence, subscription-quota saving or data promotion. Preserve original provenance and continuation labels. Current process status belongs in HANDOFF_ACTIVE, not this queue. |
| **P2** | **Fresh strength confirmation** | RLCB remains the only confirmed/deployed gain. W32 is a positive DEV screen, not a replacement for it. | Freeze one selected consumer and compare against literal production plus a useful work/behavior control on fresh mirrored deals. | Separate candidate selection from confirmation; old T4 widening is not the new W32 experiment. |
| **CLOSED** | **BELIEF R4 / R5** | R4 terminal `NO_PRIMARY_POLICY_SIGNAL` (weights ≈ uniform, 1/104 flips, paired value exactly 0). R5 closed. | Reopens only if a separate oracle-belief probe shows a gain worth pursuing. | No belief compute otherwise. |
| **COMPLETE** | **Original PT-Luna isolated collection** | Five attempts, one complete 32-game dataset retained; failed predecessors remain engineering evidence. | Reuse within its data contract. New bounded efficiency experiments are tracked separately above. | No retrospective upgrade of predecessor quality or independence. |
| **P2** | **Production-policy quality gaps** | User-reported bare-point / weak-fallback / point-insensitive play remain diagnosis surfaces. | Replay production decisions, classify cause, test one causal treatment with a matched null. | No blanket rules. |

## Immediate sequence

1. Retain the sealed K8 readout, keep K4, and do not escalate to K16.
2. Preserve Claude's Run D → Run E data queue and Run D → Mini A+C+D training
   dependency. Do not take a contended host for a performance benchmark.
3. Retain the completed rank-diverse comparison at `bc89b557` and its
   inconclusive broader-rank estimate. Its actual allocation
   `[91260904,91261164)` is committed; PR259 documents the larger reserved range.
   Double-shortlist, adaptive root allocation and selective depth have since
   completed without a supported gain. Preserve their results; neither
   all-world depth, W128 nor more uniform rollout work follows automatically.
   Finish #288 engineering integration after its consolidated merge review.
4. Finish the already-authorized 44-deal Luna continuation and reusable harvest.
   Report its direct batching contrast separately from the completed historic
   teacher bridge. Shared responses can couple deals within collector waves;
   descriptive sensitivity ranges are not confidence intervals or a new gate.
   Scale a declared data recipe, not a cost proxy.
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
