# Backlog

Last reconciled: **2026-09-08 (integration cleanup and gated W32 serving)**. This file is the prioritized
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
| **P0** | **Gated W32 serving — Codex, #300 / #310** | NumPy serving is on main. Per-room access gate and actual-container socket checks are prepared; two complete test rounds passed. | One consolidated source/image review, then quiet-window deployment and a designated public test room. | Keep MC-LCB default; no active-game disruption, global switch or VM resize. |
| **COMPLETE** | **W32 engineering integration — Codex** | A+B+C W32: +0.1387 levels/round [+0.0645,+0.2168] on 256 opened rank-2 deals. Optimized replay preserves all saved traces and cuts decision wall 2.849× (10.61× → 3.53× production). #249 (`270bd3b9`) → #252 (`0a0d70d1`) → #254 (`0d355c4c`) merged after source PASS and CI; #251 holds the completed scaling readout. | Keep the optimization opt-in and record the measured result; no gameplay rerun is needed to integrate unchanged semantics. | No deployment or production-default change. |
| **COMPLETE / PARKED** | **Tested shortlist scaling — Codex, [#248](https://github.com/jerryyyu/shengji/issues/248)** | Keep optimized K4/W32. K8, W64, doubled final search and both 26-deal double-shortlist arms did not establish improvement. Adaptive root allocation completed at +0.00577 [−0.05774,+0.07308] versus flat; selective depth at −0.00577 [−0.06736,+0.05769] and 1.5892× wall, each on 260 opened broader-rank deals. | No additional unchanged-recipe arm queued. Use retained evidence or a separately tested better checkpoint to motivate any new mechanism. [Results](AI_POLICIES.md#completed-allocation-and-depth-screens). | No equivalence, universal depth-failure or fresh-confirmation claim. Retain all artifacts; no automatic world/threshold/depth sweep. |
| **P1** | **W32 engineering closeout — Codex** | #286 prepared-lead optimization merged. [#288](https://github.com/jerryyyu/shengji/pull/288) fused-input full-consumer A/B completed: identical outputs on nine pairs, 1.3324× speedup on two huge zero-reuse follows, neutral small panel with mixed individual timings. | One consolidated source+measurement review for #288 merge; no further capacity or reconstruction run. | Do not extrapolate to whole-game speedup, multiply different-host ratios or change live workers/production defaults. |
| **P1** | **Model/data — Claude** | Measured best is **A+C+D+E+F2 v2 `3cd27716`**: +0.1260 [+0.0798,+0.1712] on the 520 clean window (seed0 91261190), +0.0936 pooled over 780 deals; selected as teacher. In the data×encoder factorial the **only POSITIVE resolved** contrast is ACDEF v2 − ACD v1 = +0.0779 [+0.0250,+0.1308], and only with BOTH factors changed — data alone (+0.0394) and encoder alone (+0.0510 at 72k, +0.0385 at 96k) each cross zero, so v2 is not established better on its own. **The width ladder shows no resolved gain** across 273k–4.0M params: 1024−512 = +0.0250 [−0.0173,+0.0663], 1024−256 = +0.0202 [−0.0279,+0.0683], 256−512 = +0.0048 [−0.0452,+0.0548] — every contrast crosses zero, which is not equivalence. 2048 is second-best offline (0.6083) and **worst in search** (+0.0500) at the highest cost (4.97×). **Lower offline CE has not reliably selected stronger search checkpoints in these screens.** Four lower-LR models share the same 520 deals, seeds and default-LR baseline; all four search contrasts have negative point estimates, three resolve, and these are **not independent population replications**. The best offline checkpoint, h1024 (`val_ce` 0.6066), is −0.0337 [−0.0827,+0.0163] versus `3cd27716`, so that contrast remains **inconclusive**. The earlier lr-sweep winner `8d92dd6e` (0.6106) has the separately recorded resolved deficit, −0.0587 [−0.1067,−0.0106]; two other sweep winners transferred to nothing. D64 remains a small prediction diagnostic, not this consumer's certificate. The ballot-rooted PUCT ladder is CLOSED (loses at every budget; the learned prior buys ~0.04 over uniform). | ACDEFGH v2 (128,000 clusters) is training; screen it on the 520 window. Test every checkpoint in the actual full-legal shortlist and keep model changes separate from K/W/N/R changes. Future shortlist-rooted depth is a distinct experiment. | **Never compare checkpoints on the 260 window** (seed0 91260904): it is the SELECTION population and is anti-correlated with the 520, ordering exactly inverted, between-window effect +0.1510 [+0.0615,+0.2413] on ACDEF v2 — twice the checkpoint gap it produces. **`val_ce` is the training loss and early-stop signal only; never the chooser between finished checkpoints.** Neither teacher corpus is git-reproducible: run A predates `source_tree_sha256` and carries no content pin, and dirty trees supply 8,000/96,000 clusters (8.3%, F2) of the SELECTED ACDEF teacher and 24,000/128,000 (18.75%, F2+H) of the PENDING ACDEFGH corpus — whose added 32,000 clusters also shift the ballot mixture, so a positive ACDEFGH screen cannot separate more data from that shift. No claim that within-ballot metrics, more rows or tree depth imply stronger play. Keep independent deal counts and continuation identities explicit. |
| **COMPLETE** | **PT-Luna efficiency and quality — Codex** | #246/#275/#280 merged; #247 superseded with source archived. All 52 deals / 104 mirrored rounds complete. Batch4−compact1: −0.1058 [−0.2885,+0.0769] levels/round alongside 2.27× fewer reported tokens/decision and 1.70× serial provider throughput. Equal quality is not established. | Reuse the [completed readout and native harvest](server/runs/luna_quality_gameplay_tranche1_result_20260906.md): 3,900 fit + 3,852 validation records, losses included and provenance retained. Historical teacher bridge remains separate. No rerun required. | Seven shared-response waves limit deal-bootstrap inference; opened validation stays out of fitting and fresh confirmation. No historic-teacher equivalence, subscription-quota saving or automatic data promotion. |
| **P2** | **Fresh strength confirmation** | RLCB remains the only confirmed/deployed gain. W32 is a positive DEV screen, not a replacement for it. | Freeze one selected consumer and compare against literal production plus a useful work/behavior control on fresh mirrored deals. | Separate candidate selection from confirmation; old T4 widening is not the new W32 experiment. |
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
   Finish #288 engineering integration after its consolidated merge review.
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
