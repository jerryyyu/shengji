# Backlog

Last reconciled: 2026-08-12 01:55 EDT. This file is the active execution
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
| **P0 / T4 mid/late Teacher hybrid** | Use the learned model as a proposal inside Monte Carlo search after trick five, so the model contributes ideas while fresh simulations and the live move protect against bad guesses. | **Running on Mini.** A 256-state test beat both live and same-work random widening. The sole 2,048-cluster whole-round screen began 2026-08-11 23:20 EDT; eight workers are healthy and outcomes remain sealed. **Left:** score-free supervisor review, one admitted aggregate, and independent terminal result review. | Reviewed whole-game verdict versus literal live champion and matched uninformed proposal | Treatment must have positive one-sided 95% lower bounds versus both controls, exact work, both-role coverage and no integrity failure. A screen PASS opens confirmation design only. |
| **P0 / S4 fresh point-banking confirmation** | Make simulated players collect points with a winning point card when it is safe, so Monte Carlo prices realistic point flow. Accumulate evidence prospectively instead of discarding several small positive runs. | **Controller ready; review open.** PR #40 `3403cdf` implements automatic looks at 8,192 and 16,384 fresh clusters with family alpha at most 0.05. At the replicated `+0.0488` effect maximum power is about 99.8%; at `+0.03`, about 84.7%. **Left:** controller PASS, score-free Air preflight, packet review, then the authorized sequence. | Reviewed, Air-runnable two-look packet with measured capacity; ultimately a terminal fresh sequential verdict | No historical pooling. Look 1 stops PASS if LCB > 0, otherwise automatically continues when clean; final look PASS/SELECT_NONE/HOLD is mechanical. |
| **P0 / S6 shuai-pai sourcing** | Always let search see a legal throw candidate on eligible early, middle and late leads, instead of silently omitting a high-upside Shengji tactic. | **Mechanism semantics passed; preflight review open.** PR #19 source `c78a2d8`; matched equal-work policy PR #39 `0bdebbc`; Air-bound v2 packet PR #41 `ea07efa`. **Left:** one reviewed score-free Air preflight, capacity review, then a fresh candidate-count-matched screen packet. | Reviewed, capacity-sized equal-work state screen against live and matched widening | Literal live ballot stays candidate zero. Treatment must improve over live and candidate-count-matched null; source coverage alone is not strength. |
| **P0 / pair-aware rollout** | Remember which higher pairs have already been exhausted inside simulated continuations, so search recognizes when a low pair has become unbeatable rather than treating every rollout as memoryless. | **Exact mechanism positive; complete-search dose sparse but nonzero.** PR #42 `d4d8ebd` gave `+9.21875` acting-team points (LCB `+6.67570`) over 64 exact endgames. PR #44 `1801aa0` then measured 24 balanced natural roots score-free: 17 activated, one changed action, 23 searches / 7,590 worlds in 32.6 seconds. **Left:** review both artifacts, then build/review a whole-round capacity preflight and size any scored packet from root-change traffic—not internal trigger count. | Reviewed score-free whole-round capacity/prevalence packet, then an adequately powered treatment/null/champion design | Actor-available information only; no determinized hidden-hand leakage. Matched null does identical analysis/work and returns champion. Exact and dose diagnostics can open packet design, never a strength claim. |
| **P1 / documentation and repository hygiene** | Keep one clear source of current truth so compute and review time go to hypotheses rather than reconstructing history. | **Compaction in progress.** Full old handoff/backlog history is archived; current handoff now names only live lanes and exact blockers. **Left:** push this compact slate, keep `JOBS.md` and the daily log current, then prune merged branches/obsolete PRs without touching active experiment heads. | Small reviewed docs PR plus a verified active-branch/PR inventory | No evidence marker, live run artifact or unmerged experimental head may be deleted. |

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
| **S4** | A reviewed score-free preflight and frozen sequential packet ready to launch, or a concrete external HOLD with a repaired packet pushed for review. |
| **S6** | A reviewed score-free Air preflight and frozen equal-work screen packet ready to launch, or a concrete external HOLD with a repaired packet pushed for review. |
| **Pair-aware** | A reviewed source/result plus a capacity-sized whole-game packet ready for execution review, or a concrete reviewed reason this mechanism should stop. |

## Next mechanism queue — cheap exploration before full ceremony

These do not outrank the four active lanes, but they are valid work when all
active lanes wait on compute or review.

| rank | hypothesis | why it may improve strength | cheapest honest next test |
|---:|---|---|---|
| 1 | **ANTICIPATE_FEED / defensive slough discipline** | Rollouts may donate 5s, 10s and Kings into an already-lost trick or fail to anticipate a partner feeding the winner. Live forensics found this in human wins, though aggregate per-seat rates corrected an earlier exaggerated headline. | Engine-replay legal alternatives on trigger-matched live states, then a public-only rollout treatment/null exact-state screen. |
| 2 | **Structured point/void bury gate** | S3a, the expanded Teacher exam and the `structured_point_void` stratum all point toward a narrow kitty surface where the current heuristic is too reluctant to bury points. | Gate only on the proven public stratum and run a powered whole-game composition, not another broad bury rewrite. |
| 3 | **Two-card exact endgame curriculum** | Endgames have shorter horizons and less hidden information, making exact search and distillation tractable before expanding outward, similar to solving a smaller game first. | Generate roots with at least two legal alternatives, solve sampled worlds under a node cap, and require nonzero exact regret before training. |
| 4 | **Teacher/value inside rollouts** | Teacher models predicted outcomes better than they ranked direct moves. Using value or policy inside continuation search may compound that skill instead of asking a bare model to override the champion. | Reusable DEV comparison of heuristic versus learned continuation on fixed public states; only then a matched whole-game screen. |
| 5 | **Human H0 repair** | Human moves remain useful for finding tactics and weak states even when they do not directly beat the teacher. The prior all-or-nothing run discarded 555 scoreable rows because two rows lacked legal scores. | Exploration-only partial-coverage repair that preserves refusal reasons and reports 555 valid rows without making a confirmatory claim. |

## Compute and evidence rules

- Mini owns T4 until its supervisor-final seal. Short work under one hour
  prefers Mini only when it does not contend with the live T4 run; otherwise
  use Air.
- Air takes the first externally authorized S4 or S6 score-free preflight.
  Pair exploration may use otherwise idle Air only when it cannot contaminate
  a frozen run namespace.
- Exploration sets may be reused with explicit correction and diagnostic
  labels. Deployment claims use fresh, sealed, adequately powered populations.
- Before spending a sealed population, show that its minimum detectable effect
  is no larger than the effect that motivated the test.
- Use two-tier rigor: fast mutation-tested exploration for mechanism breadth;
  full one-shot review machinery only for strength/deployment evidence.
- Positive point estimates are not discarded as “nothing,” but they do not
  become claims without a predeclared accumulation rule.
- Never deploy, restart production, wipe rooms, retry a spent population,
  inspect sealed outcomes or alter a running packet without explicit authority.

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
