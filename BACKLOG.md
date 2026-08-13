# Backlog

Last reconciled: 2026-08-13 17:53 EDT. This file is the active execution
queue. Detailed policy interpretation belongs in `AI_POLICIES.md`, experiment
design in `RL_PLAN.md`, live compute in `JOBS.md`, and historical queues in
`docs_archive/backlog-through-2026-08-11.md`.

## Strength objective

Beat the live `mc-s0-report-lcb` champion in complete mirrored Shengji rounds,
then confirm the win on a fresh population before considering production.
State-level and exact-endgame tests are useful mechanism screens; only
whole-game utility against the named live champion establishes bot strength.

## NOW — output ledger ordered by value

| priority / lane | plain-English strategy | progress so far and what is left | next concrete output | gate |
|---|---|---|---|---|
| **P0 / T4 mid/late Teacher hybrid** | Use the learned model as a proposal inside Monte Carlo search after trick five, so the model contributes ideas while fresh simulations and the live move protect against bad guesses. | **All eight Mini shards completed cleanly before cutoff.** The score-free supervisor final binds 8/8 zero exits and publishes no outcome/statistic; aggregate and admission remain absent. **Left:** independent supervisor-final PASS, one admitted aggregate, recursive read-only reconstruction and terminal verdict. | Reviewed whole-game verdict versus literal live champion and matched uninformed proposal | Treatment must have positive one-sided 95% lower bounds versus both controls, exact work, both-role coverage and no integrity failure. A screen PASS opens confirmation design only. |
| **P0 / S4 fresh point-banking confirmation** | Make simulated players collect points with a winning point card when it is safe, so Monte Carlo prices realistic point flow. Accumulate evidence prospectively instead of discarding several small positive runs. | **Look one completed cleanly and the reviewed controller automatically continued.** Integrity passed; the early-efficacy boundary was not crossed, which is neither failure nor final verdict. All 16 tranche-two workers are healthy at 3,967/8,192 (48.43%); outcomes remain sealed. **Left:** finish tranche two, run the pinned read-only verifier and obtain terminal review. | Terminal fresh sequential verdict from the reviewed 16-shard 360-billion confirmation | The packet marker authorizes one automatic run only. No old namespace/seed may be retried, no reviewer may call a gameplay-capable path, and any controller/integrity mismatch exits HOLD. |
| **P0 / S6 shuai-pai sourcing** | Keep every legal throw visible, but spend extra Monte Carlo only on a late full-hand boss/near move—the narrow shape that repeatedly showed value. | **Air preflight remains queued; the opened-DEV scored packet is frozen for review.** PR #94 exact `0dd8f11` PASSed all 12 guards and 100/100 pure plus 100/100 strict x86 tests. Host packet `6489d9b8…b9983` independently re-verifies, while admission, records and final remain absent. **Left:** obtain packet PASS, execute once serially, preserve records sealed and review only the score-free final. | Reviewed Air capacity result and reviewed opened-DEV result; then a powered fresh screen packet | Reused DEV establishes selector feasibility only. Do not create two executable host authorities merely to improve utilization. The fresh whole-game test must use literal live as candidate zero, a behavior-identical matched null, level utility, natural dose telemetry and a separately reviewed population before any strength claim. |
| **P0 / pair-aware rollout** | Remember which higher pairs have been exhausted inside simulated continuations, so search recognizes when a low pair has become unbeatable rather than treating every rollout as memoryless. | **Powered whole-game screen runs on Air at 3,280/7,168 (45.76%).** All eight workers are alive and outcomes sealed; timeout risk persists. PR #93's 16-lane capacity attempt correctly refused over cap and cannot retry. Fresh successor PR #96 exact `25ed31a` preserves all 7,168 clusters and 1.5x safety under an explicit 52-hour cap, binds the exact systemd fragment before admission, and passes 109/109 pure plus 109/109 strict compiled; source review and all run authority remain pending. **Left:** preserve natural Air completion or terminal HOLD; independently review the successor before any fresh packet. | One complete reviewed treatment/null/champion whole-game screen | Actor-available information only; no hidden-hand leakage. Matched null returns champion at equal work. Level utility is primary; win rate is secondary. Selected-root diagnostics motivate but never establish whole-game strength. |
| **P1 / attacker-gated pair-cap successor** | Keep the broader opponent-pair rule only when an attacker leads, because the broad replay's two helpful changes had attacker dose while its harmful reversion was defender-only. | **Action semantics externally PASSed; capacity design underway.** Claude reproduced PR #69 `ca1913f` at 22:36: the parent returns live v1 rather than champion, the incremental rule is attacker-only, and all mutation seams fail. A clean three-arm capacity design now compares incremental treatment, matched v1 parent and literal champion. **Left:** finish/falsify that design and decide whether broad-pair economics justify a run. No gameplay is authorized. | Reviewed score-free three-arm capacity design | Diagnostic action agreement is not strength. Broad pair-aware outcome and experiment economics still route any large successor. |
| **P1 / pair ballot retention** | Keep a legal pair from being crowded out before search can price it. | **The score-free capacity result and declarative scored design independently PASSed.** Claude PASSed PR #86 exact head `a43a17c` at canonical `fe6eb3b`, opening only a future controller-design review. The exact #55→#60→#61→#72 source stack is merge-ready in order; champion-natural dose remains required. | Separately reviewed controller design | REPORT remains sealed. No effect estimate, packet implementation/freeze/run, evidence access, scoring, aggregation, retry, strength, training, promotion or deployment authority exists. |
| **P1 / engine and MC performance — independent enabler** | Make every rollout and round cheaper without changing its move, RNG stream or game result. This lowers production latency and lets fixed fleet-hours test more strength ideas; speed alone is not evidence that a policy is stronger. | **The exact combined stack cleared its preregistered gate and terminal review.** The immutable six-pair N=30/R=300 batch completed once: `111.464s -> 78.782s`, **29.3203% lower wall**, 27.8619% one-sided paired lower bound, all six pairs positive and normalized gameplay/work/RNG/sampler bytes exact. Claude independently reopened all 63 artifacts and VERIFIED/retain at `e5818ee`. Draft PR #98 exact `008d75e` extracts the nine byte-identical measured runtime/parity files, removes harness/recovery code, and passes 113/113 pure plus compiled with a non-authorizing receipt. **Left:** CI and exact merge review; V5 never reruns and V6 is superseded. | Reviewed semantics-preserving performance PR and immutable benchmark bundle | Performance-only work, not bot strength. Never benchmark beside sealed strength runs; do not change frozen historical constants or substitute optimized code into sealed experiments. |
| **P1 / documentation and repository hygiene** | Keep one clear source of current truth so compute and review time go to hypotheses rather than reconstructing history. | **PR #64 and the reviewed Pair foundation are merged; active handoff is compact.** PRs #74/#76 were closed after preserving the spent S5 incident; PR #70 retains reusable diagnostic source. **Left:** keep terminal fleet facts synchronized and archive only evidence already preserved canonically. | Concise backlog/job/daily truth plus a safe handoff compaction point | No evidence marker, live run artifact or unmerged experimental head may be deleted. Experiment-specific monitoring allowlists must not become permanent dead code. |

## T4 milestone — stronger learned-search composition

T4 is complete only when all of the following are true:

1. the admitted 2,048-cluster screen finishes without retry or evidence leak;
2. an independent reviewer passes the score-free supervisor final;
3. the aggregate is created exactly once and independently reproduced;
4. the terminal result says either:
   - **PASS:** the hybrid beats both literal live and same-work random proposal
     with positive lower bounds, opening a fresh confirmation design; or
   - **SELECT NONE:** this exact composition closes honestly; and
5. `AI_POLICIES.md`, `RL_PLAN.md`, `BACKLOG.md`, `JOBS.md`, handoff and the
   daily log agree on the verdict and what it does—and does not—authorize.

Plain English: T4 tests whether a learned model can make the existing search
stronger, not whether a bare neural network can replace Monte Carlo.

## Parallel-lane exit criteria

| lane | result this goal must reach |
|---|---|
| **S4** | The retired 300-billion packet remains quarantined. Its disjoint 360-billion successor reaches a reviewed, runnable packet and is admitted/running, or a concrete external HOLD has the next repair pushed for review. The spent score-free capacity result is reused, never rerun. |
| **S6** | The already-reviewed Air preflight runs from its durable queue after pair-aware seals, followed by a frozen equal-work screen packet ready to launch. The retired Mini fallback stays closed; only the Air authority survives. |
| **Pair-aware** | The running 7,168-cluster screen reaches a reviewed terminal whole-game verdict, or a concrete integrity HOLD; no retry or resize substitutes for that result. |

## Admission economics for large runs

Before reserving more than one host-day, the packet must state six numbers or
decisions in plain English. This is a spend gate, not another evidence layer:

| required field | question it answers |
|---|---|
| natural dose | How often does the mechanism actually fire in complete champion rounds? |
| conditional effect | How much did it help on the affected states that motivated the lane? |
| implied whole-game effect | After accounting for natural dose and interactions, what gain could plausibly remain? |
| minimum detectable effect | Is the proposed run precise enough to see that implied gain? |
| maximum fleet-hours | What is the largest cost before an automatic stop or next look? |
| decision unlocked | Will the result close the recipe, open confirmation, choose a narrower gate, or authorize composition? |

Do not spend a sealed population when the run cannot detect the effect that
motivated it. Small exploration may reuse DEV/CALIB and retain partial rows;
deployment-grade evidence still uses fresh sealed populations.

## Mechanism-family routing

| family | current branches | how the next spend is chosen |
|---|---|---|
| **Pair understanding** | Pair-aware continuation; attacker-gated pair-cap; pair-ballot retention | Finish the running broad pair-aware screen first. Advance attacker-gated pair-cap only if it isolates a useful role effect or the broad result leaves that question open. Advance ballot retention only after the affected-state estimator is repaired and champion-natural dose implies a detectable whole-game effect. Do not launch three expensive pair screens merely because all three are coded. |
| **Point-flow realism** | S4 banks points while winning; S5 protects points when losing after the partner acted; a future feed rule targets inferred-boss states rather than increasing the aggregate feed rate | Test each rule separately so attribution stays clean. Human and rollout aggregate feed rates are already similar; the open gap is where they feed. Endgame conservation also needs remaining-point reserve pricing, not the old `POINTS_DRY` zero check. If at least two mechanisms survive, compare a small named portfolio rather than combining them prematurely. |

The old adaptive-search result rearranged work **within one decision's ballot**
and did not win. A separate open hypothesis is **decision-type allocation**:
spend more search on high-consequence buries, leads and short endgames, and less
on forced follows. It needs a fixed-state cost/utility screen before a
whole-game budget change.

## Next mechanism queue — cheap exploration before full ceremony

These do not outrank the four active lanes, but they are valid work when all
active lanes wait on compute or review.

| rank | hypothesis | why it may improve strength | cheapest honest next test |
|---:|---|---|---|
| 1 | **S5 defensive point protection** | The old “bots feed double” headline was a normalization artifact, but a narrower defect can remain: after the partner has acted and cannot rescue the trick, the rollout may preserve rank/structure by donating a 5/10/K even though a lower-point legal action exists. | **Execution remains closed after INC-18.** The reviewed census found 58 strict hindsight DEV triggers and PR #70 retains the reusable ten-witness diagnostic source. PR #74's request template self-authorized a 41.7-second partial attempt and spent the one-shot admission without a result. The validation-only repair PASSed, then PRs #74/#76 were closed instead of merging a spent execution chain. **Left:** decide whether the mechanism warrants a separately designed recovery with explicit retry authority and a fresh admission/result namespace; never reuse the old queue. |
| 2 | **MC hand-shape bury search: voids + shuai-pai** | The current heuristic mostly ranks individual cards. The strategic choice is the hand left behind: creating a void enables ruffs, while preserving pairs/tractors and legal shuai-pai can create future control. Points may identify some weak states, but should not define the ballot or objective. | **Opened-DEV capacity code PASSed external review; no run exists.** PRs #51/#52/#54 externally fixed hidden-kitty refusal, the deterministic 32 shape + 32 anchor journal, and actor-visible non-recursive continuations. PR #78 exact head `8ab5db2` PASSed with its no-strength authority pinned. It performs one outcome-blind 512-state census, selects that exact 64-state slice, and times baseline/`all_boss`/boss-or-near on one accepted common world for the widest state. It emits only work, timing, sampler and dose telemetry. **Left:** separately authorize the reusable DEV diagnostic when the performance host is free, then size—not guess—the next exploration pass. |
| 3 | **Structured point/void bury gate** | S3a, the expanded Teacher exam and the `structured_point_void` stratum all point toward a narrow kitty surface where the current heuristic is too reluctant to create a useful shape when doing so buries points. | Gate only on the proven public stratum and compare it with the broader MC hand-shape search; do not assume point-bearing buries are the causal mechanism. |
| 4 | **Decision-type search allocation** | The old adaptive allocator only shuffled work among candidates in the same decision. Bury, leads and short endgames may deserve more total search than forced follows because one mistake can swing many points. | Reusable fixed-state DEV screen with equal total work: allocate by decision type versus uniform work, reporting utility, dose and cost separately. |
| 5 | **Two-card exact endgame curriculum** | Endgames have shorter horizons and less hidden information, making exact search and distillation tractable before expanding outward, similar to solving a smaller game first. | Generate roots with at least two legal alternatives, solve sampled worlds under a node cap, and require nonzero exact regret before training. |
| 6 | **Teacher outcome/value inside search** | Teacher models predicted outcomes better than they ranked direct moves. A calibrated value or common-world advantage estimate may help terminate or allocate continuation search without asking a bare model to override the champion. | Reusable DEV comparison against full fresh search on fixed public states, with calibration and decision-regret gates; only then a matched whole-game screen. |
| 7 | **Human H0 repair** | Human moves remain useful for finding tactics and weak states even when they do not directly beat the teacher. The prior all-or-nothing run discarded 555 completed rows because two legal seven-card throws violated a false analyzer-cardinality assumption. | **Score-free geometry repair PR #82 exact head `a498bf5` PASSed external review with one fixture request.** It reproduces the real mismatch—production offered 12 legal choices while the generic analyzer exposed only three—and replaces the count assumption with direct legality. It has no scoring or launch surface, but its declarative `scoring_authorized=false` is not yet pinned by a test. **Left:** assert the whole authority map, then separately authorize any opened-DEV geometry prevalidation; a scored successor still needs a fresh population and design. |

## Research reserve — learned-policy successors

These remain legitimate research directions, but they are not runnable backlog
jobs today. The completed implementations selected none; re-entry requires a
materially different learning contract rather than more compute on the same
recipe.

| direction | plain-English reason to preserve it | concrete re-entry condition |
|---|---|---|
| **Direct-Q / DouZero-style return learning** | Learning directly from complete-game returns could eventually escape imitation of the current Monte Carlo teacher. The repaired run had a positive gameplay tail, but one seed and both pooled roles failed the held-out learning gate. | Freeze a new recipe with explicit acting-role perspective, shorter-horizon or decision-surface credit assignment, and multi-seed held-out success before any whole-game compute. Do not extend the spent 144M recipe. |
| **Suphx-style privileged curriculum or per-hand adaptation** | Full-information training or bounded adaptation over sampled worlds may teach patterns unavailable to a blind imitation target. Our scalar oracle-residual O0/O0-v2 tests did not robustly transfer and were not faithful Suphx policy curricula. | Specify either a same-policy privileged-feature curriculum that gradually removes hidden cards, or bounded public-information per-hand Monte Carlo policy adaptation. Pass a small reusable DEV learning gate before reserving fleet capacity. |

## Compute and evidence rules

- Mini's T4 workers are complete. Keep its sealed shards untouched while the
  score-free supervisor-final review, one aggregation and terminal review run.
- Air runs the sole reviewed pair-aware screen under its one-shot admission;
  the reviewed S6 preflight queues behind it. No retry, extension or early
  outcome access is authorized.
- Cloud runs the sole reviewed S4 360-billion confirmation on all 16 workers.
  Pair V3's formal population and 16 receipts were copied read-only from this
  host to Performance Cloud; this did not interrupt S4 or touch REPORT. Never
  put a public server address in the repository.
- Performance Cloud is a separate 16-vCPU x86 host reachable only through the
  local `shengji-perf` alias. It owns isolated profiling and the spent Pair V3
  score-free capacity evidence. The result review at canonical `16af447` opens
  scored-packet design only; freeze, execution, scoring, REPORT, strength,
  training, promotion and deployment remain closed. Never copy strength-Cloud
  authority.
- Exploration sets may be reused with explicit correction and diagnostic
  labels. Deployment claims use fresh, sealed, adequately powered populations.
- Before spending a sealed population, show that its minimum detectable effect
  is no larger than the effect that motivated the test.
- Use two-tier rigor: fast mutation-tested exploration for mechanism breadth;
  full one-shot review machinery only for strength/deployment evidence.
- Performance is a parallel engineering lane, not a substitute for mechanism
  search. Code, parity and isolated throughput measurements belong on the
  dedicated performance host while Mini, Air and strength Cloud stay sealed.
- Positive point estimates are not discarded as “nothing,” but they do not
  become claims without a predeclared accumulation rule.
- A negative screen closes its exact promotion claim, not all learning. Keep
  predeclared conditional effects, role/phase splits, natural dose, tail
  failures and disagreement states as clearly labelled exploration inputs.
- Exploratory drivers should journal completed clusters durably; a late crash
  may refuse a confirmatory aggregate without erasing already-earned
  diagnostic learning.
- Never deploy, restart production, wipe rooms, retry a spent population,
  inspect sealed outcomes or alter a running packet without explicit authority.
- A zero-row process filter is not proof that compute is idle. Before replacing
  any fleet job, reconcile its exact PID set, broad process inventory,
  heartbeat/log mtimes and terminal artifacts; see incident INC-12.
- Reviewer code must be unable to start gameplay by construction. Never call a
  gameplay-capable `launch()` behind a monkeypatch; use `validate-runtime` or a
  construction-only fixture, and let Codex own any separately authorized
  execution smoke. See incident INC-15.

## Closed results that shape the queue

| result | plain-English learning |
|---|---|
| **`mc-s0-report-lcb` confirmed and deployed** | Fresh report worlds plus a conservative override rule produced the first rigorously confirmed improvement over MC. Search remains the live foundation. |
| **Direct V11 protected anchor selected none** | V11 remains a bounded proposal/diagnostic source; a bare learned override did not transfer out of sample. |
| **Teacher direct-play REPORTs selected none** | Models improved some labels and outcome prediction, but direct proposal/ranking gains did not reliably compose. The mid/late model-inside-search T4 lane is the materially different test. |
| **S3a structured bury `+0.046`, LCB `-0.004`** | Directionally useful and convergent with other bury evidence, but the broad full-game recipe did not clear its bar. Pursue a narrow trigger gate, not a blind retry. |
| **S4 `+0.087` then `+0.049`, second LCB `-0.007`** | The mechanism stayed positive with zero drift. The miss exposed an evidence-accumulation design gap; the fresh two-look successor addresses that prospectively. |
| **Suphx-style O0 and Direct-Q selected none** | Correct public/full-information coupling alone did not make the learner use the oracle robustly. A successor needs changed targets, credit assignment or adaptation—not more hardening of the same recipe. |

Historical exact hashes and terminal packet details remain in `AI_POLICIES.md`,
`RL_PLAN.md`, `JOBS.md`, the daily logs and archived handoff ledgers.
