# Declaration and hidden-world sampling: September 10 DEV readout

Issue [#326](https://github.com/jerryyyu/shengji/issues/326).
**Decision: no policy promotion.** Keep W32, baseline declarations, ordinary
constrained sampling and shipped hybrid bury in production and future-generation
recipes. Preserve the research code and all outcomes, including losses and ties.
No broad belief retraining or production changes were made.

## What was tested

| Question | Evidence | Conclusion |
| --- | --- | --- |
| Does R4 contain ownership information? | Shared 39 positions from 13 saved deals; primary, shuffled and ordinary forecasts | Primary marginal Brier is better on this small panel; not proof of a useful joint posterior |
| Does the old adapter express it? | Exact archived energy reproduced; shared ranking and MC matrices | Original weights nearly uniform; concentration guard was not causing the flattening |
| Can a different adapter affect W32? | Capped empirical-world mixture, same valid worlds and model outputs | Yes: admission and final moves change; effects separated below |
| Does that improve play? | 14 fresh deals /70 games, ranking-only primary/control vs ordinary | No R4-specific strength benefit established |
| Can earlier pair declarations help? | 24 affected fresh deals /48 games | Negative/inconclusive; not promoted |
| Does waiting over a partner help? | 16 affected fresh deals /32 games | Negative/inconclusive; not promoted |
| Do structure-based suit choices offer leverage? | Two separate 1,060-deal score-free censuses | Too few final-trump changes for a useful small gameplay screen |
| Are current sampling constraints sound? | Legal banker-burial witness and actual sampler tests | Banker hand-only declaration pin is unsound; separate opt-in repair in PR327 |

## Sampling: constraints and the R4 adapter

Current MC proposes complete hands/kitty under public constraints; it is not
independent random card guessing or a proven uniform posterior. W32 uses those
worlds for ranking and MC. Reweighting existing worlds preserves their card
counts, hand sizes and enforced void/pair/run constraints; it cannot restore
missing support.

**Concrete support defect:** natural seed4, rank2, banker0 can declare S2 and
legally bury it. Opponents' Memory still pins a copy to the banker hand, excluding
the true hand. The valid evidence is a lower bound over banker hand **plus
hidden kitty**, less that banker's public plays. Do not inspect the real burial
to choose the bound.

[PR327](https://github.com/jerryyyu/shengji/pull/327) at
`a5c9faaf0afd76d766019a023cf24e169bc9bcbd` removes only the incorrect banker
hand pin and rejection-conditions the existing proposal on that union bound.
Ten focused tests cover conservation, hand sizes, voids, hidden twins, original
nonbanker/self-banker streams, rejection counters/caps, and the actual W32
ranking/MC consumer. It is opt-in, reviewed independently, and **undeployed**.
On52 retained states, both arms supply1,664 accepted worlds; attempts rise
1,664→2,908 and sampler CPU0.175→0.344s. This is not a whole-game cost estimate.
A separate1,976-round hybrid-bury census saw513 banker-declarers and zero such
burials: absence there does not refute the legal support counterexample.

The archived R4 adapter averages marginal log ratios before exponentiation.
In the preserved104-round PR179 diagnostic, mean primary ESS was96.79%;
its concentration guard never reduced the multiplier. Old records lacked full
world/replay state, so current W32 comparisons used saved DEV replay positions.

### Shared-state discrimination and consumer effects

Same13 saved deals, prefixes1/16/17:39 positions, not39 independent deals.
The13 lead positions had82–4,703 legal actions. Both model cohorts consume
the same actor observation; hidden state is reserved for diagnostic scoring.
The archived common-surface transform applies to both training and inference.
Missing full declaration timing is not silently invented or called a mismatch.

| Forecast on finite32-world panel | Ownership Brier |
| --- | ---: |
| Ordinary empirical marginals | 0.46297 |
| Old primary energy weighting | 0.46006 |
| Primary fitted mixture | 0.44586 |
| Shuffled fitted mixture | 0.45393 |
| Direct primary marginal model | 0.39282 |
| Direct shuffled marginal model | 0.43930 |

These finite-world forecasts have sampling error; their differences are not
unbiased latent-posterior or strength estimates. The fitted mixture minimizes
distance to model count marginals over supplied worlds, caps weight at4/N,
then blends toward uniform for ESS≥N/2. It consumes no true ownership,
action values or outcomes. This is an approximate empirical mixture—not a
Bayesian joint posterior or the optimum of a jointly ESS-constrained problem.
All78 saved fits hit the fixed500-iteration limit without convergence.

Both mixtures alter10/39 admitted sets. Final-MC decisions differ as follows:

| Weighting location | Primary changed moves | Shuffled changed moves |
| --- | ---: | ---: |
| Ranking only | 2/39 | 0/39 |
| MC only | 5/39 | 3/39 |
| Ranking and MC | 6/39 | 3/39 |

Ordinary and uniform-weight paths reproduce saved final decisions on39/39.
Shared MC columns needed10,890 missing-column rollouts and78 witnesses,
11.54s wall, no new games/worlds. Weighted report bounds are exploratory:
fitting weights does not inherit the original frequentist coverage guarantee.
Candidate throw identities denote attempted plays, not guaranteed acceptance.

### Fresh ranking-only gameplay: complete

[PR329](https://github.com/jerryyyu/shengji/pull/329) source head
`89d9e4bc127f8f1844aaa5a8b6d7e483f587d43b` matches local execution
`69d3ac39` across19 files;50 focused tests and independent component reviews
passed. A later documentation commit does not change this measured source.

A persistent archived subprocess loads both cohorts once and accepts only
actor JSON. Three saved leads ×three arms reproduce actor/model outputs,
ranking means and final actions. Partial-response deadlines, ownership of
child cleanup and completed-record resume binding have witnesses.

Fourteen fresh deal clusters cover all13 ranks plus a genuine first round.
Each cluster shares one ordinary baseline across the primary/control team
mirrors:5 games,70 total. Average the mirrors within deal. Declarations,
ordinary MC and unbudgeted hybrid bury remain common; this is not the Fly
two-second-budget comparison and does not include PR327's sampler change.

| Comparison | Signed levels, mean [95% deal-bootstrap CI] | Win-rate difference |
| --- | --- | ---: |
| Primary − ordinary | +0.0357 [−0.1071,+0.2143] | +3.57pp |
| Shuffled − ordinary | +0.1429 [0,+0.3571] | +7.14pp |
| Primary − shuffled | −0.1071 [−0.2857,0] | −3.57pp |

The4,000-resample intervals are exploratory and discrete at n=14; zero-ended
intervals do not establish strictly positive lower bounds. The shuffled model
is not a pure noise null. Do not promote either arm or infer that R4 as a whole
is disproven. **This bounded ranking-only recipe did not show useful lift.**

All recorded failed-world/short-search/void-fallback/zero-world counters are0.
Active executor wall449.2+2,912.9=3,362.1s (56min), excluding the launch gap;
one worker for the retained first cluster, two for the rest.
Mean game wall ordinary86.27s /primary87.65s /control88.02s: different
trajectories, not a decision-preserving engineering A/B.
Parent CPU sums1,202.11/2,359.48/2,369.60s for14/28/28 games exclude child CPU.
Primary/control inference wall totals84.04/84.31s.
Only9/798 primary and13/796 control fits converged; minimum ESS≈0.5.
Primary−ordinary kitty bonus0 [−4.29,+4.29] does not resolve rare tail risk.
Weighted final-MC gameplay remains untested, distinct from the completed
saved-state MC diagnostic.

## Declarations: rules, experiments and limits

Actor views contain own currently dealt cards, engine legal options and public
banker/rank/declarer context—not deck, kitty, opponents' hands or future cards.
Baseline reproduces SmartBot: suited score is effective-trump length +2 for a
pair; joker-pair NT scores14+rank-card count only when that count≥3.
Acceptance thresholds are8 during deal and6 on explicit final calls.
A last-card callback still uses the during-deal rule. Stable ties retain engine
option order. Engine legality handles increasing declaration strength and
redeclaration. Bot-only final calls/pass/finalize are modeled, not human grace
windows. First-round banker follows the final winning declarer.

Four additional engine-boundary cases directly witness equal/weaker refusal,
pass reset on a stronger overcall, the single→rank-pair→LJ-pair→BJ-pair ladder,
NT finalization with known/unknown banker, closed-window refusal and real-kitty
fallback. All34 declaration tests pass after this test-only addition. An
eight-card all-joker kitty is impossible in the physical four-joker deck;
its defensive fallback is not an untested natural declaration opportunity.

Historical `DECLARE_TUNE` mixed weaker-suit preference and point-rank eagerness
and hurt by roughly2 points in its old screen; do not resurrect that bundle.
New arms change one mechanism, preserving fixed hybrid/W32 continuations:

| Arm | Change | Fresh exposure and result |
| --- | --- | --- |
| Pair-eager, PR328 | Allow suited rank pairs at score6/7 during dealing; preserve accepted baseline/final/NT choices | 24 affected deals from1,060;48 games; levels−0.25 [−0.6667,+0.125], wins−8.33pp |
| Partner-wait, PR330 | Suppress during-deal overcall of partner; retain final/self/opponent/no-prior choices | 16 affected deals from a separate1,060;32 games; levels−0.50 [−1.0625,+0.0625], wins−18.75pp |
| Structure-tie | At equal original score and declaration strength, prefer longest trump tractor then pair count | 3 final-trump changes on1,060 fresh deals; no gameplay |
| Structure-near | Same strength and original threshold, allow at most1 score point of length tradeoff for structure | 1 final-trump change on a different1,060 deals; no gameplay |

The declaration schedule cycles52 rank/banker cells plus a true first-round
cell. Affected pairs were selected from declaration-only censuses before
gameplay, not by eventual utility. Report conditional results, not all-deal
strength. Pair-eager had3 better/15 tied/6 worse; partner-wait1/10/5.
All16 partner-wait final trumps differ; all10 tied-level games also change burial,
plays and points. Keep those ties in n=16. The six nonzero differences belong
only to a tie-excluding sign test—not a replacement mean-utility population.

Pair-eager kitty bonus+2.92 [0.42,6.67], but no≥80 kitty cases in either arm;
partner-wait every kitty bonus is0, so tail-risk evidence is absent.
Pair-eager parent CPU baseline1,303.17/treatment1,380.97s; partner958.28/809.57s.
Partner executor wall919.3s, two workers. Changed trajectories are not speedups.
All reported failure counters are0.

On the structure-near population's baseline path:1,454 suited accepted calls,
only34 with multiple eligible suits at the same strength (26 within1 score
point);111 accepted NT calls. Of1,565 accepted calls,1,557 use the during-deal
rule, including final-card callbacks. This limits suit-ranking opportunity,
not the importance of trump quality. Separate censuses cannot establish
head-to-head superiority of the structure probes. No NT-quality or match-level
strength improvement was tested.

### Sampled completion: considered next experiment, not launched

Timing offers more decision opportunities than near-tied suit ranking, but
partner-wait shows that blanket delay is not enough. If pursued, compare
call-now versus wait under shared sampled deal completions:

1. Inputs: current own hand, public deal position, shown declarations and
   rank/banker context. Exclude real future deck, hidden hands/kitty and the
   multi-seat capture event list (it contains private actor hands).
2. Condition physical completions on shown-card evidence and hand capacities;
   require hidden-twin identity at the actual sampling consumer.
3. Apply each legal declaration/pass, fixed future declaration policy, then
   bury/play on completed states. Never feed a raw partial-hand declaration
   state to the play-only value model.
4. Use separate evaluation completions; measure disagreement and paired return
   precision before funding a gameplay screen. Report cost and conditional
   exposure rather than silently replacing the current generation recipe.

This is a plausible next hypothesis, not an implemented or proven improvement.
No further ad-hoc bonus sweep or broad posterior training follows automatically.

## Source and retained evidence

- [PR327](https://github.com/jerryyyu/shengji/pull/327): opt-in support repair,
  head `a5c9faaf`; no production integration.
- [PR328](https://github.com/jerryyyu/shengji/pull/328): pair-eager driver,
  head `aeb2d361`;22 focused tests at publication.
- [PR329](https://github.com/jerryyyu/shengji/pull/329): R4 mixture/runtime,
  measured source `89d9e4bc`;50 tests at publication.
- [PR330](https://github.com/jerryyyu/shengji/pull/330): partner-wait driver,
  measured source `d0da283e`;30 focused tests then4 engine-boundary cases.
  The later test-only commit changes neither driver nor measured policy.
- Parked branches `codex/declare-structure-tie-dev` at `d0e17955` and
  `codex/declare-structure-near-dev` at `43b30456`;34/37 declaration tests.
- Selected compact W32 model SHA `fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`.
  Measured files/commits remain preserved; no merge is implied.

All result roots below are under `~/shengji-archive/2026-09-10/`:

- `declare-belief-dev-20260910.gzyIgY/`: old weighting audit, initial
  declaration censuses, `banker-support-panel52.json`.
- `r4-w32-early13/`, `r4-w32-lead16/`, `r4-w32-prefix17/`: captured actor,
  shared private world/action matrices, reference marginals and proper scores.
- `r4-mixture-fit32-anchored.json`, `r4-mixture-mc-readout/summary-39.json`:
  fitted weights, separate consumer decisions, shared-column parity.
- `r4-runtime-parity.json`, `r4-mixture-rank-gameplay/`:
  completed arm/cluster records and `complete-consumer-readout.json`;
  reducer script `r4-mixture-gameplay-readout.py`.
- `declare-pair-eager-conditional24/`, `declare-partner-wait-conditional16/`:
  selection plans, complete records, summaries and per-arm work.
- `declare-structure-census1060.json`,
  `declare-structure-near-census1060.json`,
  `declare-opportunity-audit1060.json`, with adjacent replay scripts.

New-data eligibility work is preserved separately in
`posterior-data-eligibility.json` and overlap/ownership witnesses. Available
newer trajectories do not by themselves justify new posterior training; old
population exclusions and a clearly useful downstream consumer still matter.
