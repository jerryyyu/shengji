# Backlog

Last reconciled: 2026-08-12 11:03 EDT. This file is the active execution
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
| **P0 / T4 mid/late Teacher hybrid** | Use the learned model as a proposal inside Monte Carlo search after trick five, so the model contributes ideas while fresh simulations and the live move protect against bad guesses. | **Running on Mini.** A 256-state test beat both live and same-work random widening. The sole 2,048-cluster whole-round screen began 2026-08-11 23:20 EDT; at 10:32 all eight workers remained CPU-bound after 11h12m and every shard's reviewed score-free heartbeat had reached the `treatment 200/512` milestone. Outcomes remain sealed. **Left:** natural completion, score-free supervisor review, one admitted aggregate, and independent terminal result review. | Reviewed whole-game verdict versus literal live champion and matched uninformed proposal | Treatment must have positive one-sided 95% lower bounds versus both controls, exact work, both-role coverage and no integrity failure. A screen PASS opens confirmation design only. |
| **P0 / S4 fresh point-banking confirmation** | Make simulated players collect points with a winning point card when it is safe, so Monte Carlo prices realistic point flow. Accumulate evidence prospectively instead of discarding several small positive runs. | **Eight-shard profile HOLD; 16-shard successor designed.** The reviewed Cloud preflight completed 4/4 with every integrity/dose check green but projected 869.30 fleet-hours and 108.66 hours per old shard, above 768/96 caps. PR #56 `9f9d80b` preserves exact artifact `70a15405…413e`, cleanly reopens HOLD, blocks packet freeze, and fixes ARM/x86 last-bit display drift; 71 tests pass on both. Design-only PR #59 `f0c2a6d` retains 8,192/16,384 clusters and automatic stopping, uses 16 shards, fresh 300B seeds, and a measured 1,024/64-hour envelope; its rendered digest matches across architectures. **Left:** external HOLD/result review and C2 design PASS; implement/freeze/review the 16-shard packet; then separately authorize scored execution. | Reviewed 16-shard packet ready for launch; ultimately a terminal fresh sequential verdict | Do not retry the spent preflight or shrink the evidence target. Look 1 stops PASS if LCB > 0, otherwise automatically continues when clean; final look PASS/SELECT_NONE/HOLD is mechanical. No controller or design review alone authorizes scored work. |
| **P0 / S6 shuai-pai sourcing** | Keep every legal throw visible, but spend extra Monte Carlo only on a late full-hand boss/near move—the narrow shape that repeatedly showed value. | **Repaired v2 packet frozen; external review pending.** Exact oracle value was `+0.234` levels (LCB `+0.100`), the actor-visible selector realized `+0.307` (LCB `+0.175`), and literal champion play triggered in 13/512 rounds (`2.54%`). Source `a48542d` now binds the two-flip cluster map, canonical one-shot freeze receipt and factual strict-native runtime. PR #50 `936345b` preserves packet `19f3b2a3…79dd0`; all 62 S6 tests pass. **Left:** packet PASS; one four-cluster score-free Air preflight after the pair run; capacity review; then a separately reviewed fresh whole-game packet. | Reviewed, Air-runnable full-hand whole-game capacity preflight; then a powered fresh screen packet | Reused DEV establishes selector feasibility only. The fresh whole-game test must use literal live as candidate zero, a behavior-identical matched null, level utility, natural dose telemetry and a separately reviewed population before any strength claim. |
| **P0 / pair-aware rollout** | Remember which higher pairs have been exhausted inside simulated continuations, so search recognizes when a low pair has become unbeatable rather than treating every rollout as memoryless. | **Powered whole-game screen running on Air.** Capacity v3 passed after changing 6/8 mirrored roots. The reviewed packet (`4ece02b9…ae47`) fixes 7,168 clusters, 8×896, 500.9 projected fleet-hours and ~84% planning power at `+0.05`. Its sole execution began around 07:24; at 10:32 its detached supervisor and all eight workers remained healthy and CPU-bound after 3h08m; no shard had yet published a terminal record. **Left:** natural completion, score-free supervisor review, one admitted aggregate, and terminal external verdict. | One complete reviewed treatment/null/champion whole-game screen | Actor-available information only; no hidden-hand leakage. Matched null returns champion at equal work. Level utility is primary; win rate is secondary. Selected-root diagnostics motivate but never establish whole-game strength. |
| **P1 / pair ballot retention** | Keep every legal pair on the lead ballot before discretionary throws or tractors consume the 14-action cap, so a promoted low pair cannot disappear before search evaluates it. | **Source dose verified; advance narrowly.** Claude authorized content access, and the committed verifier accepted the exact million-round artifact (`557df627…61f3`). The current ballot omitted at least one legal pair on 15,187/18,618,281 leads (`0.0816%`), heavily early: 14,826 omissions (`97.6%`), versus 352 mid and 9 late. PR #55 `24b421d` preserves the exact result and regression test. **Left:** capture fresh disjoint omission states without outcomes, then compare retention versus current at equal ballot width/work on that trigger-matched set. Do not start with a uniformly sampled whole-game duel. | Reviewed trigger-matched affected-state packet and equal-work action-value screen | This repairs ballot availability only. The active pair-aware whole-game lane tests rollout valuation; neither result substitutes for the other. A positive affected-state screen would still need natural-dose composition before promotion. |
| **P1 / documentation and repository hygiene** | Keep one clear source of current truth so compute and review time go to hypotheses rather than reconstructing history. | **Current cleanup merged.** PR #43 merged the compact docs/fleet monitor; PR #57 merged the explicit merge/active/close and safe branch-deletion routine. Historical and redundant PRs were closed only after preservation checks, leaving eight active experiment PRs (#40, #49–#52 and #54–#56). **Left:** close each stack as its result becomes terminal and prune only clean, artifact-free worktrees. | Small active PR queue with preserved terminal evidence and current high-signal docs | No evidence marker, live run artifact or unmerged experimental head may be deleted. |

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
| **S4** | A reviewed score-free Cloud preflight and frozen sequential packet ready to launch, or a concrete external HOLD with a repaired packet pushed for review. |
| **S6** | A reviewed score-free Air preflight and frozen equal-work screen packet ready to launch, or a concrete external HOLD with a repaired packet pushed for review. |
| **Pair-aware** | A reviewed v3 score-free capacity result plus a capacity-sized whole-game packet ready for execution review, or a concrete reviewed reason this mechanism should stop. |

## Next mechanism queue — cheap exploration before full ceremony

These do not outrank the four active lanes, but they are valid work when all
active lanes wait on compute or review.

| rank | hypothesis | why it may improve strength | cheapest honest next test |
|---:|---|---|---|
| 1 | **ANTICIPATE_FEED / defensive slough discipline** | Rollouts may donate 5s, 10s and Kings into an already-lost trick or fail to anticipate a partner feeding the winner. Live forensics found this in human wins, though aggregate per-seat rates corrected an earlier exaggerated headline. | Engine-replay legal alternatives on trigger-matched live states, then a public-only rollout treatment/null exact-state screen. |
| 2 | **MC hand-shape bury search: voids + shuai-pai** | The current heuristic mostly ranks individual cards. The strategic choice is the hand left behind: creating a void enables ruffs, while preserving pairs/tractors and legal shuai-pai can create future control. Points may identify some weak states, but should not define the ballot or objective. | **Source, reusable population and later-throw sensitivities are coded; reviews remain ordered.** Claude checked PR #51 at `59cc2c6`; current head `a1d107b` adds only hidden-kitty refusal and portable one-world JSON, but still needs an exact-head delta PASS. PR #52 `fd7b434` pins the opened 512-state asset, selects 32 shape-rich rows + 32 anchors and journals completed states immutably. Stacked draft PR #54 `959cdbd` adds two non-recursive continuation modes: an `all_boss` arm requiring publicly boss components and no public ruff warning while the engine prices hidden ruffs, plus a deliberately aggressive boss-or-near sensitivity. The historical heuristic remains the literal baseline; mode, source hash and observed dose are manifest-bound. Fifty-nine focused/parent tests pass in strict compiled mode; no census or rollout ran. **Left:** #51 delta review, #52 population/resume review, #54 bounded semantics review, source-only census, then one-state/one-world capacity on a free host. |
| 3 | **Structured point/void bury gate** | S3a, the expanded Teacher exam and the `structured_point_void` stratum all point toward a narrow kitty surface where the current heuristic is too reluctant to create a useful shape when doing so buries points. | Gate only on the proven public stratum and compare it with the broader MC hand-shape search; do not assume point-bearing buries are the causal mechanism. |
| 4 | **Two-card exact endgame curriculum** | Endgames have shorter horizons and less hidden information, making exact search and distillation tractable before expanding outward, similar to solving a smaller game first. | Generate roots with at least two legal alternatives, solve sampled worlds under a node cap, and require nonzero exact regret before training. |
| 5 | **Teacher/value inside rollouts** | Teacher models predicted outcomes better than they ranked direct moves. Using value or policy inside continuation search may compound that skill instead of asking a bare model to override the champion. | Reusable DEV comparison of heuristic versus learned continuation on fixed public states; only then a matched whole-game screen. |
| 6 | **Human H0 repair** | Human moves remain useful for finding tactics and weak states even when they do not directly beat the teacher. The prior all-or-nothing run discarded 555 scoreable rows because two rows lacked legal scores. | Exploration-only partial-coverage repair that preserves refusal reasons and reports 555 valid rows without making a confirmatory claim. |

## Compute and evidence rules

- Mini owns T4 until its supervisor-final seal. Short work under one hour
  prefers Mini only when it does not contend with the live T4 run.
- Air runs the sole reviewed pair-aware screen under its one-shot admission.
  S4 and S6 remain separately queued behind exact reviews and must not compete
  with or inspect the pair population. No retry, extension or early outcome
  access is authorized.
- Cloud is the canonical S4 host and is currently idle by gate after the
  terminal capacity HOLD. The successor may use all 16 cores only after the
  HOLD, design, packet and execution reviews. The pair-ballot result is already
  reviewed and preserved. Never put the public server address in the
  repository.
- Exploration sets may be reused with explicit correction and diagnostic
  labels. Deployment claims use fresh, sealed, adequately powered populations.
- Before spending a sealed population, show that its minimum detectable effect
  is no larger than the effect that motivated the test.
- Use two-tier rigor: fast mutation-tested exploration for mechanism breadth;
  full one-shot review machinery only for strength/deployment evidence.
- Positive point estimates are not discarded as “nothing,” but they do not
  become claims without a predeclared accumulation rule.
- Exploratory drivers should journal completed clusters durably; a late crash
  may refuse a confirmatory aggregate without erasing already-earned
  diagnostic learning.
- Never deploy, restart production, wipe rooms, retry a spent population,
  inspect sealed outcomes or alter a running packet without explicit authority.
- A zero-row process filter is not proof that compute is idle. Before replacing
  any fleet job, reconcile its exact PID set, broad process inventory,
  heartbeat/log mtimes and terminal artifacts; see incident INC-12.

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
