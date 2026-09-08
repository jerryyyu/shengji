# Public-prior proposals added to W32

Small opened-DEV screen, not confirmation or deployment. No new training,
pruning, rollout policy or world sampler. Production and Run I are untouched.

## Question and arms

Does the public prior propose useful moves that the value top four misses?
Keep all exhaustive W32 scoring, the incumbent, and the existing top-four
value alternatives. Add the two highest-prior **distinct** legal actions that
are not already present, with action-key tie breaking. If fewer remain, take
all remaining actions. The prior sees the actual actor-visible root, not the
sampled true hidden world.

| Arm | Ballot before unchanged MC selection/report |
|---|---|
| V4 | Incumbent + top 4 W32 alternatives |
| V6 | Incumbent + top 6 W32 alternatives |
| U4+2 | Incumbent + top 4 W32 + top 2 distinct public-prior alternatives |

Direct mirrored comparisons: U4+2 vs V4; V6 vs V4; U4+2 vs V6. N30/R300,
W32, batch128, MLP-static and successor reuse on every value arm. Selection
and report costs are measured, not asserted equal from equal N/R.

Value checkpoint: A+C+D+E+F2 v2 source
`3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
Public prior: runC/pub-C/best.pt,
`b0001163407fa24ebe02087d4042d9273e5d875b5d6173a9186fd3ce02cb3b8e`.
This older v1 prior has not learned the newer value model's data mixture;
a negative result does not reject all possible policy heads.

## Cheap execution and interpretation

Use the first 26 deals of the already-opened 520-deal screen: seed91261190,
rank cycle 2,3,4,5,6,7,8,9,10,J,Q,K,A. This is deliberately reused diagnostic
data, not a fresh holdout. Two mirrors per deal; bootstrap deals, not decisions.
One initial full pair checks the actual consumer and gives a timing estimate;
retain it in the corresponding comparison rather than discard and repeat it.
Use up to 16 independent workers on idle Perf, single-threaded Torch/BLAS.
No job competes with Strength's Run I. Record actual workers, wall/CPU, RSS,
and comparison completion. Small-sample intervals may remain very wide.

Reuse the existing screen's atomic mirrored shards, 30-second progress, and
configuration-bound resume. A bounded execution window preserves completed
shards; incomplete comparisons are labeled incomplete, never reported as
negative findings or silently supplemented with changed settings. An external
stop can prevent final summary publication; re-open retained shards for the
summary without replaying their games.

Read results before looking at outcomes:

- U4+2 beats V6 but loses to V4: prior content helps at that width, but widening
  costs more than the content buys. Not a blanket rejection of priors.
- U4+2 beats V4: candidate improvement to investigate on a larger independent
  screen; the V6 contrast says whether this was content or just width.
- U4+2 loses to both: this prior adds no demonstrated useful proposals here.
- Intervals crossing zero are inconclusive, not equality or proof of no effect.

Report the actual extra-prior counts, prior-challenger/played counts and final
report outcomes alongside gameplay utility and cost. Proposal agreement with
W32 is not ground-truth move quality. Do not prune based on #314: C top16 kept
the best value alternative on only **11/19 actually pruned FIT roots**.
