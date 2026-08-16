# Backlog

Last reconciled: 2026-08-16 00:35 EDT. This file is the active execution
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
| **P0 / BELIEF-V1 V2 calibrated baseline** | Learn an actor-visible distribution over hidden ownership and hand shape, then prove it improves held-out calibration before changing search. | **V1 produced no learning result.** Exact design `a8c5e05f…1fd53` completed capture and REF-C, but both CPU training cohorts exceeded the frozen eight-hour wall cap. They were stopped through Claude's reviewed sequence at 00:35 EDT; the supervisor recorded `exit-143`/`exit-143` and exited before test or terminal. The spent partial namespace cannot retry. V2 base `0949404` adds all-rank, human-domain, replayed-reference and accelerator infrastructure, but still needs resource-failure re-entry, fail-closed registry classification and live deadlines. | Publish one repaired V2 successor, obtain a consolidated source/design PASS, run a ≥16-CPU host preflight, then build and review one immutable host-specific freeze | V1 is an infrastructure failure, not a calibration null. No partial model/test result may be used. V2 execution requires a separately reviewed repaired route and exact freeze; B3/gameplay/strength remain unauthorized. |
| **CLOSED / pair-aware rollout evidence paths** | Determine whether actor-visible exhausted-pair memory improves complete rounds, not just selected disagreements. | **Neither whole-game path produced evidence.** Air hit its fixed 64.08h timeout with `0/8` terminal shards and no manifest/final. The Performance checkpoint V1 one-shot fail-closed on microshard 3 `treatment work drift`; its host is now off and the admission is spent. | Preserve the diagnosis and require a fresh reviewed recovery design if this family is ever reconsidered | No retry, resume, partial-outcome access, aggregation or strength interpretation. Pair is no longer a live prerequisite for BELIEF-V1. |
| **DONE / post-null roadmap reset** | Choose the next research milestone from evidence rather than keeping idle hardware busy. | **T4, S4 and combined S6 all selected none; BELIEF-V1 is the chosen materially different representation milestone.** The closeout identified selected-state signal, sparse natural dose, weak same-work attribution and continuation fragility. | Execute BELIEF-V1's calibration → sampler → same-work ladder in order | Before any large scored screen, require natural-dose economics, treatment-vs-champion and treatment-vs-same-work-null evidence, robustness under two continuation/role strata, and detectable whole-game effect. |
| **CLOSED / T4 mid/late Teacher hybrid** | Use the learned model as a proposal inside Monte Carlo search after trick five. | Terminal `SELECT_NONE`; treatment LCB `-0.00759` versus champion and `-0.03313` versus its work-matched null. The uninformed arm was positive versus champion, but used 14.8% more accepted worlds and 80.9% more searches than champion, so widening and compute are confounded. | Implement the separately reviewed three-arm attribution design; do not retry T4 | No confirmation, retry, promotion or deployment for the learned recipe. Any widening claim must distinguish champion-work from original-null-work arms. |
| **CLOSED / S4 point banking** | Make simulated winners bank point cards. | Clean two-look, 16,384-cluster confirmation terminally selected none at review `15e8dbb`; natural incidence was only about 0.7% of decisions. | Preserve diagnostic states only | No retry, pooling, promotion or deployment. |
| **CLOSED / combined S6 sourcing** | Spend extra search on late full-hand boss/near throws across bury and lead sources. | Result `de1c4f33…d0bc` terminally selected none for fresh-screen design. Bury source passed all criteria; lead source failed three. | Preserve the bury-side asymmetry as hypothesis-only | No fresh screen, retry, REPORT, strength or deployment from this evidence. |
| **PARKED / attacker-gated pair-cap successor** | Keep the broader opponent-pair rule only when an attacker leads, because the broad replay's two helpful changes had attacker dose while its harmful reversion was defender-only. | Action semantics and a three-arm capacity design were reviewed, but both Pair whole-game evidence paths later closed without a terminal result. This diagnostic cannot justify a third execution by itself. | None unless a fresh causal diagnosis materially changes the estimand and earns a new design | Diagnostic action agreement is not strength. No retry, recovery, capacity packet or scored run is queued. |
| **PARKED / pair ballot retention** | Keep a legal pair from being crowded out before search can price it. | The foundation and PR #100/#101 design-only successors are merged, but both Pair whole-game attempts later closed without evidence. Neither design contains executable census/controller code, and BELIEF-V1 now owns the active representation milestone. | Preserve the designs; require a materially new causal case before implementation | REPORT remains sealed. No implementation, census, packet, run, evidence access, scoring, retry, strength, training, promotion or deployment is queued or authorized. |
| **P1 / engine and MC performance — independent enabler** | Make every rollout and round cheaper without changing its move, RNG stream or game result. This lowers production latency and lets fixed fleet-hours test more strength ideas; speed alone is not evidence that a policy is stronger. | **Two exact stacks cleared preregistered x86 gates and merged.** PR #98's immutable six-pair N=30/R=300 batch measured **29.3203% lower wall** with 27.8619% one-sided paired lower bound and exact normalized gameplay/work/RNG/sampler bytes. PR #103 then retained a separate **3.4074%** increment with +1.0299% lower bound, exact semantics, and zero mismatch across 12 million differential rounds; reviewed head `3044a2f` merged at `e3af8c3`. Do not add the percentages across baselines. | Profile the merged stack only when a powered-on host has a separately reviewed next candidate; no benchmark is queued now | Performance-only work, not bot strength or deployment. Never benchmark beside sealed strength runs; do not change frozen historical constants or substitute optimized code into running experiments. |
| **P1 / point-flow census and feed anticipation** | Compare human and rollout choices only where each side actually had a legal point-card opportunity, then test narrowly named continuation rules instead of inferring policy from aggregate card counts. | **PR #99 exact `0ee28a0` passed external descriptive-tooling review and repairs the PR #95 denominator/provenance boundary.** On 165 private opened rounds, literal legal-opportunity rates are human 164/204 and rollout 14,664/14,666; inferred-strict rates are 32/46 and 302/989. Exact 150-row binding found 20 policy flips, only three toward the human action. The former 70%-versus-23% headline is withdrawn. **Left:** choose a separately designed consumer, if any. | Reviewed descriptive census and a separately designed cheapest honest follow-up | Private opened logs are not sealed strength evidence. The census grants no scored run, training, strength, promotion or deployment authority. |
| **P1 / documentation and repository hygiene** | Keep one clear source of current truth so compute and review time go to hypotheses rather than reconstructing history. | PR #114's compact current-state documents and PR #115's append-only merge guard are merged. This refresh records the V1 wall-cap failure, spent/no-verdict classification, and repaired V2 path in every live ledger. | Routine exact updates at terminal, incident, review and launch transitions | `HANDOFF_REVIEW.md` remains append-only. Rotate it only after an acknowledged cutoff and hash-bound archive manifest. |

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

All five conditions are now satisfied. Canonical terminal review `a165274`
verified the recursively reconstructed `SELECT_NONE`. The treatment-work-
matched uninformed proposal beat champion on this population, but used 14.8%
more accepted worlds and 80.9% more searches than champion. The learned
proposal did not beat that control; no T4 continuation is authorized, and
widening requires a separate three-arm work-controlled confirmation.

## Parallel-lane exit criteria

| lane | result this goal must reach |
|---|---|
| **S4** | **Done:** clean two-look terminal `SELECT_NONE`; exact recipe closed. |
| **S6** | **Done:** 64-record scored-DEV terminal `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`; exact combined recipe closed. |
| **Pair-aware** | **Done without evidence:** Air terminally timed out at `0/8`; the Performance checkpoint attempt fail-closed and is spent. No retry or partial interpretation. |

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
| **Pair understanding** | Pair-aware continuation; attacker-gated pair-cap; pair-ballot retention | Both whole-game continuation attempts closed without evidence. Do not retry them. Re-enter only through a fresh diagnosis/design that isolates a useful role effect or demonstrates champion-natural dose large enough for a detectable whole-game result; do not launch coded pair screens merely because compute is idle. |
| **Point-flow realism** | S4 banks points while winning; S5 protects points when losing after the partner acted; a future feed rule targets inferred-boss states rather than increasing the aggregate feed rate | PR #99 shows the prior aggregate headline compared unlike legal-opportunity denominators: literal rollout almost always spends a point when one is legally available, while inferred-follow behavior differs by surface. Review that descriptive boundary first, then test each named rule separately. Endgame conservation also needs remaining-point reserve pricing, not the old `POINTS_DRY` zero check. If at least two mechanisms survive, compare a small named portfolio rather than combining them prematurely. |

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
| 1 | **S5 defensive point protection** | The old “bots feed double” headline was a normalization artifact, but a narrower defect can remain: after the partner has acted and cannot rescue the trick, the rollout may preserve rank/structure by donating a 5/10/K even though a lower-point legal action exists. | **Execution remains closed after INC-18.** PR #99 passed exact-head review and gives the broader census a like-for-like legal-opportunity denominator with exact counterfactual binding; it is descriptive only. PR #70 retains the reusable ten-witness diagnostic source. PR #74's request template spent its admission without a result, so any treatment still needs a separately designed recovery, explicit retry authority and a fresh namespace. |
| 2 | **MC hand-shape bury search: voids + shuai-pai** | The current heuristic mostly ranks individual cards. The strategic choice is the hand left behind: creating a void enables ruffs, while preserving pairs/tractors and legal shuai-pai can create future control. Points may identify some weak states, but should not define the ballot or objective. | **Opened-DEV capacity code PASSed external review; no run exists.** PRs #51/#52/#54 externally fixed hidden-kitty refusal, the deterministic 32 shape + 32 anchor journal, and actor-visible non-recursive continuations. PR #78 exact head `8ab5db2` PASSed with its no-strength authority pinned. It performs one outcome-blind 512-state census, selects that exact 64-state slice, and times baseline/`all_boss`/boss-or-near on one accepted common world for the widest state. It emits only work, timing, sampler and dose telemetry. **Left:** separately authorize the reusable DEV diagnostic when the performance host is free, then size—not guess—the next exploration pass. |
| 3 | **Structured point/void bury gate** | S3a, the expanded Teacher exam and the `structured_point_void` stratum all point toward a narrow kitty surface where the current heuristic is too reluctant to create a useful shape when doing so buries points. | Gate only on the proven public stratum and compare it with the broader MC hand-shape search; do not assume point-bearing buries are the causal mechanism. |
| 4 | **Decision-type search allocation** | The old adaptive allocator only shuffled work among candidates in the same decision. Bury, leads and short endgames may deserve more total search than forced follows because one mistake can swing many points. | Reusable fixed-state DEV screen with equal total work: allocate by decision type versus uniform work, reporting utility, dose and cost separately. |
| 5 | **Two-card exact endgame curriculum** | Endgames have shorter horizons and less hidden information, making exact search and distillation tractable before expanding outward, similar to solving a smaller game first. | Generate roots with at least two legal alternatives, solve sampled worlds under a node cap, and require nonzero exact regret before training. |
| 6 | **Teacher outcome/value inside search** | Teacher models predicted outcomes better than they ranked direct moves. A calibrated value or common-world advantage estimate may help terminate or allocate continuation search without asking a bare model to override the champion. | Reusable DEV comparison against full fresh search on fixed public states, with calibration and decision-regret gates; only then a matched whole-game screen. |
| 7 | **Human H0 repair** | Human moves remain useful for finding tactics and weak states even when they do not directly beat the teacher. The prior all-or-nothing run discarded 555 completed rows because two legal seven-card throws violated a false analyzer-cardinality assumption. | **Score-free geometry repair PR #82 exact head `bf72dff` PASSed and merged.** It reproduces the real mismatch—production offered 12 legal choices while the generic analyzer exposed only three—replaces the count assumption with direct legality and pins the complete false authority map. **Left:** separately authorize any opened-DEV geometry prevalidation; a scored successor still needs a fresh population and design. |

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

- Mini is idle after the reviewed stop of the over-cap BELIEF-V1 B2 training
  children. Air is idle; strength Cloud and Performance Cloud are last recorded
  powered off. Do not start a scored job merely for utilization.
- T4, S4, S6, broad Pair, and Pair checkpoint namespaces are terminal or spent.
  Keep their artifacts closed; no ad hoc reopening, retry, extension, resume,
  pooling, or partial-result interpretation is authorized.
- V1 marker `209407f` is spent with no terminal or calibration result. Never
  resume or inspect its partial models. Mini's next BELIEF use is source testing
  or device qualification only after a repaired V2 source PASS. A ≥16-CPU cloud
  host may run the later capacity preflight only after that PASS; it may not
  recover the spent V1 or Pair invocations.
- Never put a public server address in the repository or copy authority from
  one host, design, namespace, or evidence chain to another.
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
