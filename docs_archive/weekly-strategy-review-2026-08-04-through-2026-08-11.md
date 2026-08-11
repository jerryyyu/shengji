# Weekly strategy review — 2026-08-04 through 2026-08-11

This is a decision-oriented audit, not a run log. It separates four things the
project has often blended together:

1. strength that actually reached production;
2. credible research signals that have not yet become a policy;
3. diagnostic or training assets; and
4. correctness/process work that prevents false conclusions but does not make
   the bot stronger by itself.

Exact terminal results remain canonical in `AI_POLICIES.md`; active execution
belongs in `BACKLOG.md` and `JOBS.md`.

## Executive verdict

The week was **strong in scientific and production infrastructure, but weak in
strength conversion relative to the effort spent**.

- One policy improvement is unambiguous: `mc-s0-report-lcb` beat `mc-strong`
  by `+0.338 +/- 0.068` signed levels and shipped.
- Two tactical directions produced meaningful positive evidence: structured
  bury improved selected states but missed its whole-game bar; point banking
  passed one whole-game screen and stayed positive, but missed its independent
  replication bar.
- No learned policy has beaten the live report-LCB champion. The expanded
  Teacher play ensemble was the first learned candidate with positive DESIGN
  and CALIB lower bounds, but both its broad protected exam and its powered
  219-state champion-uncertainty exam selected none on untouched REPORT.
- The sampler, action semantics, evaluator, data provenance and compiled path
  became materially more trustworthy. Several fixes prevented invalid results,
  so this was not cosmetic bureaucracy.
- The process nevertheless became too serialized and too bespoke. Repeated
  packet/controller/review repairs often became the milestone, while the
  intended strength hypothesis remained untested. The right response is not to
  lower the final evidence bar; it is to move most rigor into reusable tooling
  and apply confirmation-grade review only after a cheap hypothesis screen.

Plain English: **we built a much better laboratory and found one stronger bot,
but we are still operating the laboratory as if each experiment requires a new
building inspection.**

Follow-through at 14:06 EDT: the audit's immediate recommendation was executed
once on all 219 untouched `champion_uncertainty` states. Exact work completed
with zero refusals. Action improvement was `+0.012129` with SE `0.010109` and a
one-sided 95% LCB of `-0.005056`, so the reviewed verifier returned
`SELECT_NONE`; independent terminal authentication reproduced every identity,
work count and statistic exactly. Outcome-NLL improvement was much larger and
clearly positive (`+0.47845`, LCB `+0.44201`),
but it was diagnostic rather than the action gate. The protected composition
source remains useful engineering, but this result gives it no evidence
authority.

## What tangibly moved

| area | tangible output | strength impact | audit verdict |
|---|---|---|---|
| Production search | report-LCB uses N=30 to nominate, then compares that fixed challenger with the heuristic incumbent on 300 fresh shared worlds and overrides only when its lower bound is positive. | Confirmed `+0.338 +/- 0.068` versus `mc-strong`; matched null flat. | **Real shipped strength.** The clearest result of the week. |
| Search width | N=30 beat N=10 twice; N=60 did not establish an increment over N=30. | More uniform worlds beyond N=30 did not buy a detected gain. | **Closed as a generic scaling strategy.** Spend extra work selectively or improve actions/continuations. |
| Structured bury / S3a | Strategy-aware point/void/trump candidates beat live, legacy and random choices on 512 selected states. | State screen `+0.997 +/- 0.401` versus incumbent; fresh whole-game mean `+0.0464`, LCB `-0.0041`. | **Useful mechanism, not a policy.** The local benefit did not clear the full-game bar. |
| Point banking / S4 | Rollouts can retain higher control while winning with a 5/10/K when secure. | Exact-state `+5.156` points; first 2,048-cluster game screen `+0.0869 +/- 0.0562`; independent replication `+0.0488 +/- 0.0557`. | **Most credible unshipped mechanism.** Both game estimates are positive, but replication missed its predeclared LCB. Redesign; do not retry the same recipe. |
| V11pair | Pairwise action deltas beat SmartBot and supplied disagreement proposals. | Confirmed 57.7% versus SmartBot; corrected direct-v2 was `-0.141 +/- 0.070` versus live. | **Useful proposer/ranker, not a direct policy or scalar leaf.** |
| Direct-Q | Role-conditioned action values from terminal returns. | Gameplay tail `+0.163 +/- 0.059`, but a seed and both pooled-role held-out learning gates failed. | **Promising clue, invalid promotion.** Redesign target/surface rather than extend the same run. |
| Suphx O0/O0-v2 | Training-time full-information signal and a shared-public CRN repair. | O0 aggregate positive but seed-unstable; O0-v2 control and margin arms did not pass. | **These scalar/margin mechanisms are closed.** This was not a faithful test of the full Suphx curriculum idea. |
| Teacher Stage C | Split-safe capture, iid hidden-world labels, 7,040 DESIGN/CALIB examples, eight-seed cohort training and untouched REPORT populations. | First generation and protected play failed. Expanded bury failed REPORT. Expanded play had positive DESIGN/CALIB bounds, but the powered 219-state uncertainty REPORT was only `+0.01213` with LCB `-0.00506`; outcome-NLL improved `+0.47845` with LCB `+0.44201`. | **The generation learned value/calibration better than action ranking and selected none.** No composition or game screen. |
| Human data / H0 | Refreshed 2,830 plays and 45 buries; designed a fixed-work human/V11/random proposal comparison. | Sole H0 execution completed 555/557 and emitted no aggregate. | **Operational no-result, not evidence humans are unhelpful.** Human actions remain witnesses/proposals, not labels. |
| Exact endgame / S3c | Bounded one-card controller and 768-root design. | Zero solver work and no model labels. | **Architecture only.** The AutoGo-style curriculum has not actually started. |
| Correctness | Bounded sampler validity/support certificate, action-semantics invariance, exact-work accounting, seeded pairing, encoder/sampler repairs and replayable provenance. | Prevented invalid worlds, wrong actors/signs, swallowed seeds, stale decisions and contaminated data from becoming strength claims. | **Necessary foundation.** Posterior probability fidelity remains open. |
| Performance | Compiled rollout path improved a like-for-like round `5.74s -> 1.68s` (3.42x); release 17 moved search/X-ray work off the event loop and overlapped pacing. | More experiments per hour and responsive production; no policy semantics changed. | **Real leverage.** The Python policy loop and multi-room capacity remain open. |

## Key research learnings

### 1. The best search gain came from independent rechecking, not more width

Report-LCB succeeded because it separates **nomination** from **verification**.
N=30 finds a plausible alternative; fresh common worlds ask whether it really
beats the safe heuristic move. N=60 on every candidate did not show the same
increment. Extra compute should therefore target uncertain comparisons,
better candidates or better continuation models—not uniformly widen every arm.

### 2. Missing actions and mispriced continuations are different bottlenecks

S3a and S6 address candidate recall: search cannot choose a legal tactic that
never enters the ballot. S4 addresses continuation bias: even a present action
can be mispriced when heuristic rollouts always spend the cheapest winner.
Both matter. “Use more MC” fixes neither an absent candidate nor a systematically
wrong rollout policy.

### 3. A state-level win is not automatically a whole-game win

S3a's large selected-state gain shrank to a narrow whole-game miss. S4's strong
exact-state gain became a small positive whole-game effect. Trigger frequency,
downstream continuation and opportunity cost determine whether a local tactic
survives natural traffic. Every mechanism now needs the same ladder: reproduce
the exact local behavior, measure trigger-matched value, then test full games.

### 4. More clean Teacher coverage helped more than the new loss

The expanded 7,040-state run compared the original all-pairs loss with a direct
candidate-zero-relative loss on the same states and seeds. The old loss won.
The main improvement came from scale and hard-tail coverage, not objective
novelty. This is useful: do not keep inventing losses before diagnosing ballot,
surface and continuation coverage.

### 5. The current endgame curriculum is mostly nominal

The expanded Teacher contains 6,400 play examples. Of those, 1,298 have only
one candidate and therefore no ranking choice. Every one of the 1,087
`exact_late_eligible` examples is candidate-zero-only, with zero positive
alternative. The one-card S3c controller has performed zero solver work.

So the roadmap says “solve small endgames first,” but the model currently sees
late-state calibration rows—not exact comparisons among alternate actions.
The first real endgame milestone must enumerate alternate legal actions, solve
them on sampled beliefs, and produce regret labels for two-card roots.

### 6. Candidate provenance is being discarded too early

Capture records whether an action came from the live ballot, V11, a structured
mechanism or random widening. The 7,040-example model dataset explicitly strips
those source tags. Source identity need not be a model input, but it must remain
diagnostic metadata. Without it we cannot measure proposal recall, regret or
incremental value by source, and cannot decide whether V11, S6, S4 or human
actions deserve more proposal budget.

### 7. The Teacher still inherits a continuation ceiling

Most counterfactual action labels are values under one heuristic continuation
contract. S4 demonstrates that this continuation can misprice point-bearing
play. A model can fit those labels perfectly and still inherit the same blind
spot. Future labels should name the continuation and, on selected states, test
a small fixed portfolio rather than pretending one heuristic rollout is
generic game value.

### 8. Holdout power must be designed before a population is frozen

The current broad-play effect is about `+0.009` to `+0.010` per selected state.
At the observed dispersion, n=480 would have a negative lower bound even if it
reproduced that mean. Break-even is roughly 591–822 iid-equivalent states;
conventional power needs more than the remaining broad reservoir. Freezing an
exam first and checking power later is backwards.

The hold is scientifically correct. The process failure is that power and the
runtime environment were not machine-checked before the freeze/review request.

### 9. The Teacher learned the position better than it learned the move

The powered uncertainty exam is the cleanest diagnosis of the current model.
Its outcome-NLL improvement generalized very strongly, but replacing candidate
zero with its ranked action did not clear zero. The DESIGN/CALIB targeted
effect (`~+0.027` to `+0.028`) shrank to `+0.0121` on REPORT. This is not an
implementation failure: exact work, folds, population and runtime all held.

The next learned-policy hypothesis should therefore not be “train the same
ranker on more rows and take its argmax.” Test either an explicit pairwise
advantage target on named candidate comparisons, or use the value head as a
bounded leaf/continuation critic while report-LCB retains final action
authority. Both require fresh validation; good outcome calibration alone does
not prove useful action differences.

A terminal post-hoc check makes that warning concrete. On the same spent 219
rows, directly choosing the action with the highest outcome-head expected
utility triggered 203 times but improved only `+0.00906` with LCB `-0.01184`.
So neither “take the rank-head argmax” nor “take the value-head argmax” is a
supported successor. Any leaf use must show that search converts absolute
calibration into better *differences*; explicit common-world advantage learning
is the cleaner first test.

Post-hoc, unadjusted slices make the next hypothesis more specific. Mean action
improvement was negative early (`-0.0256`, n=89), positive mid (`+0.0234`,
n=98) and larger late (`+0.0825`, n=32); early attackers were `-0.0516`, while
mid follows were `+0.0938`. Wider ballots were also harder: 13+ candidates
averaged `-0.0102`, versus `+0.0450` for at most eight. These are diagnostic
multiple looks—not promotion evidence—but they argue for horizon/surface-
specific advantage learning and explicit candidate-count calibration rather
than another global argmax ranker.

## Larger strategic misses

### Milestones measured machinery more often than outcomes

T1/T2/T3 produced valuable audits, controllers and assets, but the milestone
language often let “review PASS,” “dataset frozen” or “controller executable”
sound like strength progress. T4 is better defined, but still accumulated many
intermediate gates before one model reached an untouched exam.

Future strength milestones should end in one of three outcomes:

- a new mechanism beat a matched control on fresh states;
- a composed challenger reached a fresh whole-game screen; or
- a candidate beat the exact live champion in confirmation.

Everything else is an enabling task, not the milestone.

### Confirmation-grade ceremony was applied too early

Engine semantics, data identity, final confirmation and deployment deserve
strict fail-closed review. A 64-state DEV mechanism probe does not need a new
bespoke evidence system. The current process repeatedly reviewed signal
ownership, subprocess handling, receipts and environment pins in experiment-
specific wrappers. Those contracts should live once in a reusable runner.

### Operational failures consumed scarce statistical assets

Several populations were declared spent after argparse, identity or fold-
completeness failures that opened zero labels, predictions or utility. This is
safe but wasteful. Future protocol should distinguish an **execution attempt**
from an **epistemic look**. A zero-look failure may consume its immutable run
receipt but should not automatically destroy the statistical population after
an independently reviewed mechanical repair.

### Positive signals were terminally filed instead of transformed

The no-retry rule correctly prevents tuning on spent evidence. It should close
an exact recipe, not erase the research posterior. S4 stayed positive twice;
Direct-Q had a positive gameplay tail; S3a had strong local value; v11pair beat
SmartBot. Each needs a substantively changed successor derived from mechanism
and heterogeneity analysis, not either an identical retry or permanent burial.

### The roadmap has underinvested in proposal quality and continuation quality

Most learning still ranks an incumbent-generated ballot under heuristic
continuation. That can distill the current search, but it cannot reliably
discover actions the ballot omits or strategies the rollout policy never
plays. Candidate generation and continuation modeling should be first-class
learned components, not side diagnostics.

## Best current strength hypotheses

| rank | hypothesis | confidence now | why it could work | next falsifiable output |
|---|---|---|---|---|
| **1** | **Build a source-aware proposal flywheel: S6 throws, V11, structured tactics and supported human actions propose; search judges.** | **Medium-high strategic upside; medium immediate confidence.** | V11's verified value is relative ranking; KESP proves throws are omitted; S3a proves named structured actions can beat equal-width random. MC cannot recover an absent action, and the current Teacher dataset strips the metadata needed to learn which source helped. | Preserve source tags, report recall/regret by source, and select a fixed 1–3 action proposal budget that beats candidate-count-matched random widening on fresh states. |
| **2** | **Improve the continuation model with a small policy portfolio, starting with point-aware play.** | **Medium-high mechanism confidence; medium game confidence.** | S4 stayed positive in two independent game samples, while the current Teacher inherits one heuristic continuation. This is the strongest repeated evidence of a systematic pricing bias. | Analyze frozen S4 heterogeneity, replay S5 legality, then preregister a substantively changed point-aware portfolio against an equal-work single-continuation control. |
| **3** | **Convert the Teacher's calibration signal into an explicit common-world advantage critic; test bounded leaf use separately.** | **Medium for advantage learning; low for direct value argmax.** | The powered REPORT showed large outcome-NLL gain (`+0.47845`, LCB `+0.44201`), but rank argmax missed (`+0.01213`, LCB `-0.00506`) and post-hoc outcome argmax also missed (`+0.00906`, LCB `-0.01184`). Absolute outcome knowledge is not yet accurate action difference. | On one named decision surface, predict candidate-zero-relative or pairwise advantage from common-world deltas. Separately test a bounded leaf against a matched no-leaf control; require a fresh state screen before game compute. |
| **4** | **Actually solve and distill small endgames, then expand horizon.** | **Medium confidence, high upside.** | Hidden information and long horizons shrink late; this is the cleanest AutoGo-style curriculum and creates labels beyond heuristic continuation. Current exact-late rows provide no ranking signal, so the hypothesis is nearly untested. | Two-card roots with alternate legal actions, sampled-belief exact values, bounded nodes, regret labels and a student-vs-candidate-zero fresh state screen. |
| **5** | **Train decision/role-specialized models instead of one global play ranker.** | **Medium-low to medium.** | Direct-Q's gameplay tail and Teacher's surface differences suggest signal is mixed across bury/lead/follow and attacker/defender contracts. The powered uncertainty set was also 188/219 lead, so it was not a balanced test of every play surface. | One predeclared surface, eight seeds, held-out role learning gate and protected composition; no global scale until it passes. |
| **6** | **Use human play for proposal diversity and hard-tail discovery, not direct imitation.** | **Medium as a source, low as a standalone policy.** | Live logs found concrete bury, point-banking and shuai-pai misses. H0 failed operationally, not scientifically. Human skill is mixed, so counterfactual scoring is essential. | A reusable H0 successor that completes, retains source metadata, and reports human-proposal incremental value versus matched random by decision type and player cohort. |
| **7** | **Learn or correct the hidden-world posterior.** | **High eventual upside, currently blocked.** | More MC converges to the sampler's distribution; legal-but-biased worlds can systematically misprice actions. | Exact-toy posterior calibration and weighted/uniform completion repair before any learned belief reweighting or promotion use. |

### Low-priority hypotheses now

- **More uniform N:** N=60 did not establish an increment over N=30.
- **Direct V11 or V11 as a scalar leaf:** corrected direct evidence is negative,
  and pairwise deltas do not define a state value.
- **Generic ballot widening:** DEV-512 selected none; every new source needs a
  named mechanism and a matched random control.
- **MCTS over the current model:** tree depth does not repair absent actions,
  a biased belief sampler or a mispriced continuation. Start with exact late
  roots and public-belief contracts.
- **Large AWAC/self-play now:** without a stronger stable actor/Teacher, this
  mostly amplifies the current policy's own blind spots. Revisit after one
  specialized learner or Teacher composition beats the champion.

## Recommended operating model

Keep the final standard; change where it is paid.

1. **Mechanism tier:** run many small, replayable DESIGN tests with matched
   controls. These produce effect size, trigger frequency and heterogeneity,
   not promotion claims.
2. **Candidate tier:** only promising mechanisms get a fresh state screen or
   untouched model REPORT. Power and environment are computed and pinned before
   the holdout is selected.
3. **Strength tier:** only REPORT/screen passers receive a fresh whole-game
   screen and then a separate confirmation against the exact live champion.
4. **Deployment tier:** production identity, rollback, latency and human-facing
   safeguards remain independently reviewed.

Build one versioned `ExperimentSpec`/runner for identity, exact work, seeds,
signals, namespaces, progress, termination and aggregation. New experiments
should usually provide a policy factory, population, estimand and controls—not
another controller stack.

Use block-sequential untouched evidence with a declared alpha-spending rule
when plausible effects are small. This preserves independent evidence while
letting 480-state blocks accumulate instead of forcing every block to become a
terminal, underpowered all-or-nothing exam.

Track one velocity metric alongside correctness: **time from a named mechanism
idea to its first matched fresh-state effect estimate**. A healthy target is
hours for a small mechanism and 24–48 hours for one new whole-game challenger.
Reviews and commits are not the numerator.

## Immediate decision

Do not compose or game-screen the current Stage-C ranker. The powered narrow
REPORT completed and its action LCB crossed zero. This generation is a useful
negative result, not an unfinished launch: more of the same ranking data is no
longer the default next step.

The next strength milestone should produce **two cheap, genuinely different
mechanism estimates before another large Teacher run**:

1. S6/source-aware proposal quality versus candidate-count-matched random; and
2. a changed continuation portfolio informed by S4/S5, versus equal-work
   heuristic continuation.

In parallel, retain proposal provenance in future data and build the first real
two-card alternate-action labeler. Then choose one learned successor: either a
surface-specific pairwise advantage model or a bounded value/leaf critic. Its
first gate is a fresh candidate-zero-relative state screen, not another long
controller chain or immediate whole-game duel.
