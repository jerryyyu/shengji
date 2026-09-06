# Backlog

Last reconciled: **2026-09-06 (W32 milestone)**. This file is the prioritized
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
| **P0** | **Shortlist scaling — Codex, [#248](https://github.com/jerryyyu/shengji/issues/248)** | K8 is running Strength on 256 paired rank-2 deals / 512 rounds with the same A+B+C checkpoint, W32/N30/R300, batch 128, static encoding and reuse. Cost-order scheduling is descending prior pair time only; completed shards are resumable. Prior W64 and MC2 negative contrasts remain unresolved. | Report K8 strength and cost. Separately run the fresh balanced 13-rank K4 reference comparison; then investigate double-shortlist/depth and selective work. | Strength-first; higher compute is acceptable. Equal-cost matching is an optional diagnostic, not a gate. Use light resource safeguards and stop at 2h while retaining progress. |
| **P1** | **Model/data and PUCT — Claude** | A+B+C complete-world MLP is the measured W32 checkpoint. Run D produces diverse trajectory data; A+C+D training waits for it, with Run E queued afterward on Perf. D64's earlier result remains a small prediction diagnostic, not this consumer's certificate. | Test new checkpoint quality in the actual full-legal shortlist; keep model changes separate from K/W/N/R changes. PUCT remains a separate consumer experiment, sharing findings with shortlist. | No claim that within-ballot metrics, more rows or tree depth imply stronger play. Keep independent deal counts and continuation identities explicit. |
| **P1** | **PT-Luna efficiency and quality — Codex** | Historical Sol/Luna planning wins retained. Four-round batch4 comparison: 2.70× rounds/token, 2.08× rounds/wall; 16-game cost extension complete. PT52 fresh-deal panel/preparation is under parent review; no provider collection has launched, and old quality evidence is inconclusive. | Compare compact1 vs batch4 and run the separate free-tool bridge before a costed Luna/Sol collection proposal for disjoint fit and validation. Reuse the existing resumable runner. | No scaled collection from these cost numbers alone; mixed continuation outcomes are not one value target. |
| **P2** | **Fresh strength confirmation** | RLCB remains the only confirmed/deployed gain. W32 is a positive DEV screen, not a replacement for it. | Freeze one selected consumer and compare against literal production plus a useful work/behavior control on fresh mirrored deals. | Separate candidate selection from confirmation; old T4 widening is not the new W32 experiment. |
| **CLOSED** | **BELIEF R4 / R5** | R4 terminal `NO_PRIMARY_POLICY_SIGNAL` (weights ≈ uniform, 1/104 flips, paired value exactly 0). R5 closed. | Reopens only if a separate oracle-belief probe shows a gain worth pursuing. | No belief compute otherwise. |
| **COMPLETE** | **Original PT-Luna isolated collection** | Five attempts, one complete 32-game dataset retained; failed predecessors remain engineering evidence. | Reuse within its data contract. New bounded efficiency experiments are tracked separately above. | No retrospective upgrade of predecessor quality or independence. |
| **P2** | **Production-policy quality gaps** | User-reported bare-point / weak-fallback / point-insensitive play remain diagnosis surfaces. | Replay production decisions, classify cause, test one causal treatment with a matched null. | No blanket rules. |

## Immediate sequence

1. Let the bounded K8 Strength run complete or stop at its operational limit;
   retain resumable shards and report measured strength and cost.
2. Preserve Claude's Run D → Run E data queue and Run D → Mini A+C+D training
   dependency. Do not take a contended host for a performance benchmark.
3. After K8, run the prepared rank-diverse fresh 13-rank comparison separately;
   it is not launched and still needs seed registration with Claude. Neither
   W128 nor more uniform rollout work follows automatically from K8.
4. Improve teacher efficiency only alongside a quality check against the
   original planning harness. Scale a declared data recipe, not a cost proxy.
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
