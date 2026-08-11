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
- No learned policy has beaten the live report-LCB champion. The current
  expanded Teacher play ensemble is the first learned candidate with positive
  DESIGN and CALIB lower bounds, but it has not opened REPORT or played a
  game-level screen.
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

Follow-through at 13:35 EDT: the audit's immediate recommendation is now
implemented without opening evidence. The complete 219-state
`champion_uncertainty` REPORT packet is frozen under Python 3.14.6 with
84.7%/87.8% projected power and awaits independent execution review. The
downstream source also now protects the exact live report-LCB decision, rather
than collapsing to heuristic candidate zero, and reproduces the frozen
live/V11/structured/random proposal family. These are readiness improvements;
neither is a strength result until REPORT and a fresh whole-game screen pass.

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
| Teacher Stage C | Split-safe capture, iid hidden-world labels, 7,040 DESIGN/CALIB examples, eight-seed cohort training and untouched REPORT populations. | First generation and protected play failed. Expanded bury failed REPORT. Expanded broad play now has DESIGN `+0.00904` (LCB `+0.00542`) and CALIB `+0.01048` (LCB `+0.00336`), 8/8 positive seeds. | **Real learned capability, no strength claim yet.** Current n=480 broad REPORT is underpowered at the observed effect and is correctly on HOLD. |
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
| **1** | **Use the expanded Teacher ranker only where the champion is uncertain, inside report-LCB's protected fallback.** | **Medium-high for a state-level pass; medium-low for a game-level win.** | Champion-uncertainty is the only broad-play stratum consistently strong on DESIGN and CALIB: `+0.02715` / `+0.02848`, SD `0.14749` / `0.14698`, with positive LCBs. The global effect is diluted by exact-late zero-choice rows and weaker strata. | Re-freeze all 219 untouched eligible champion-uncertainty states under Python 3.14.6. Their plug-in break-even is only 86/78 states and approximate power is 85–88% at the observed effects; if REPORT passes, run one protected treatment/random/champion game screen. |
| **2** | **Build a source-aware proposal flywheel: S6 throws, V11, structured tactics and supported human actions propose; the Teacher ranks.** | **Medium-high strategic upside.** | V11's verified value is relative ranking; S6 proves the live ballot broadly omits throws; S3a proves structured actions can beat equal-width random. MC cannot recover an absent action. | Preserve source tags, report recall/regret by source, and train/select a 1–3 action proposal budget that beats candidate-count-matched random widening on fresh states. |
| **3** | **Improve the continuation model with a small policy portfolio, starting with point-aware play.** | **Medium-high mechanism confidence; medium game confidence.** | S4 is positive in both independent game samples, and the local-to-game shrinkage identifies continuation/trigger interaction rather than a dead idea. | Reanalyze frozen S4 heterogeneity without reopening selection; preregister a changed point-aware continuation bundle or robust portfolio and test it against a matched single-continuation control. |
| **4** | **Actually solve and distill small endgames, then expand horizon.** | **Medium confidence, high upside.** | Hidden information and long horizons shrink late; this is the cleanest AutoGo-style curriculum and can create labels beyond heuristic continuation. Current exact-late rows provide no ranking signal, so the hypothesis is nearly untested. | Two-card roots with alternate legal actions, sampled-belief exact values, bounded nodes, regret labels and a student-vs-candidate-zero fresh state screen. |
| **5** | **Train decision/role-specialized advantage models rather than one global Q policy.** | **Medium.** | Direct-Q's gameplay tail and Teacher's surface differences suggest signal exists but is being mixed across bury/lead/follow and attacker/defender contracts. | One predeclared surface, eight seeds, held-out role learning gate and protected composition; no global self-play scale until it passes. |
| **6** | **Use human play for proposal diversity and hard-tail discovery, not direct imitation.** | **Medium as a source, low as a standalone policy.** | Live logs found concrete bury, point-banking and shuai-pai misses. H0 failed operationally, not scientifically. Human skill is mixed, so counterfactual Teacher scoring is essential. | A new reusable H0-style diagnostic that completes, retains source metadata, and reports human-proposal incremental value versus matched random. |
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

Do not spend the current n=480 broad-play REPORT as frozen. It is underpowered
at the observed global effect, and its Python 3.14.3 pin drifts from the
reviewed 3.14.6 chain.

The highest-value successor is a **new, explicitly narrow policy hypothesis**:
use the ensemble only on champion-uncertainty states, where DESIGN and CALIB
effects are `+0.02715` / `+0.02848` with SD `0.14749` / `0.14698`; preserve
candidate zero elsewhere. The independently recomputed plug-in break-even is
86/78 comparable states. All 219 untouched eligible champion-uncertainty rows
after the four prior exclusions give roughly 85–88% normal-approximation power
at the observed effects, versus an underpowered broad n=480 mixture. Freeze
that exact 219-state scope under 3.14.6 and then take one fresh look. This is
not a claim that the broad model passed; it is a protected, targeted
composition chosen entirely from DESIGN/CALIB before REPORT.

In parallel, do not leave the fleet blocked on that review. S6's equal-work
64-state proposal-quality screen, source-provenance retention, and the two-card
endgame labeler are independent code/DEV work. They directly increase future
hypothesis throughput and address current strategic gaps.
