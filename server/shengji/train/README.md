# Learned root search (DEV, not deployed)

`search_inference.py` consumes the existing `ValuePriorNet` checkpoint;
`search_policy.py` plugs it into the production MC-LCB selection/report split.
No retraining, BELIEF dependency, or production registry entry is required.

## What changes

- Use the current constrained hidden-world sampler.
- Enumerate every legal submitted action, including off-ballot actions. A
  population above the supported bound refuses; no capped prefix is scored.
- Score all actions with the prior head in bounded batches. Mix in 5% uniform
  probability so no action is excluded by the prior.
- Allocate root investigations with a PUCT-style rule. Compare a challenger
  and the incumbent on the same sampled world. An incumbent investigation
  evaluates it once, not twice.
- Apply the candidate in the engine, complete one trick by default, and predict
  value for the resulting acting seat. Convert by partnership to root-team
  signed levels. Terminal leaves use the engine result. Value-only and
  prior-only ablations are available. `--leaf-tricks 3` instead finishes three
  tricks with the fixed heuristic continuation before evaluating the leaf;
  it does not branch/search opponents' replies. `--leaf-tricks 0` evaluates
  immediately after the action and has not been screened below.
- Nominate one challenger, then run **unchanged production fresh-world full
  rollouts and its 300-world paired LCB report** against the original heuristic
  incumbent. Neural selection values do not enter this confidence calculation.

This is **root allocation, not recursive MCTS**. The reused model has a
531-feature actor-visible observation, a 512/256 MLP trunk, a signed-level
value head and a per-action prior head. Its RunA prior was trained on old
ballots, not exhaustive actions or MCTS visits; off-ballot generalization is
unproven. Its leaf value predicts outcomes under the training policy, not an
optimal perfect-information value. Unchanged report continuations can still
reject an actually good move they misunderstand.

`--paired-advantage` changes both root allocation and final challenger ranking
to mean candidate-minus-incumbent value from the same sampled worlds. Without
it, each action uses its absolute mean. The flag defaults to false; the
independent full-rollout report is unchanged in either case.

`SearchConfig(self_play=True)` enables root Dirichlet noise and samples the
played action from allocation visits on separate RNG streams. Mandatory
paired-reference evaluations are not policy visits. This collection mode
disables the report override and is explicitly different from duel mode;
the duel CLI never enables it. These are experimental root-allocation targets,
not full-tree AlphaZero visit targets.

## First experiment, specified before opening its outcomes

The saved default RunA model is used, not the best configuration from the
concurrent sweep: `lc-8000/best.pt`, epoch 11, SHA-256
`11dfc8590561e8d7f8e461fc7960ec194982ddbc51ea70829f324d6c78292b83`.
It uses the older v2 checkpoint schema, so `--allow-legacy` is explicit and
loading does **not** confer a held-out claim. Its sole RunA source has 8,000
deal seeds `20260905..20268904`, each mirrored; source manifest SHA-256
`985bfef5a295500b91f04e57abe19c32b0193da67ca265bc0b9dba28b0789949`.
Source inspection/reconstruction found no deck intersection with fresh seeds
`2026090401..2026098400`. Rank cycling changes rank, not the shuffled deck.

The existing Luna measurement is 215/4,017 (5.4%) chosen actions outside
production on provider-contested decisions; 171/1,143 leads (15.0%). Restricting
to production-contested decisions gives 204/3,990 (5.1%), including 160/1,116
leads (14.3%). These are coverage facts, not estimated strength gains. The
62 games include engineering predecessors and share only 30 distinct deals;
they are not 62 independent confirmatory samples (issue #205).

One tiny N1/R30 mirrored wiring run completed in 1.9 seconds. CPU calibration
on two separate deals (`2026090501..502`), without choosing on outcomes:
candidate N30/R300 cost 1.234x production CPU; candidate N15/R300 cost 1.034x.
Interpolating those two cost points sets **candidate N12**, baseline N30,
both R300 for the first fresh sample. Do not keep tuning after that sample.

Fresh DEV sample: 26 deal clusters / 52 mirrored rounds, seeds
`2026090601..626`, two per rank, four CPU workers on Mini, no GPU use. Report
paired signed-level utility and deal-cluster bootstrap, wins, sampler/work
failures, coverage, and CPU cost (including enumeration/inference/report).
Keep compact decision traces for diagnosis. A 0.95–1.05 observed CPU ratio
is approximately cost-matched; outside it, label the result cost-unmatched,
not an equal-work win. A ratio below 0.95 is cheaper, not exactly equal cost.
This small sample cannot establish a strength gain or authorize deployment;
any positive must next face a cost-matched no-learning control and fresh data.
No confirmation, expanded collection or training is authorized by this README.

### Observed result — do not scale this recipe

At source `89b3cf6be09347fe387223639eb4392bf6a457ab`, all 26 pairs finished
in 110.4 seconds. Candidate won 21/52 rounds, with signed-level utility
**−0.21154 per round**, deal-bootstrap interval **[−0.38510, −0.03846]**.
CPU ratio was **0.97602** (within the predeclared approximate match band),
with no short/zero-world searches. It played 108 off-ballot actions. Preserve
the negative result; do not scale this exact combined model/search recipe.
The sample does not identify whether prior extrapolation, leaf values,
allocation or reduced selection dose caused the loss.

Data limitation: the RunA producer creates a fresh `Game` and its first round
for every seed, hence rank2. This sample cycles all13 ranks, so it also tests
transfer outside the training-rank population. The four rank2 rounds alone
are not a powered subgroup. RunA also includes 10% exploration with two
off-ballot additions, not purely unmodified production ballots. None of this
is evidence that the model has distilled PT-Luna yet.

Full result and interpretation: [PR #222](https://github.com/jerryyyu/shengji/pull/222#issuecomment-5547202677).
Local artifacts, including earlier unfavorable CPU calibration, remain under
`/Users/jerryyu/shengji-archive/learned-search-20260904/`.

### Six diagnostic ablations — same 26 deals, not independent confirmations

All arms keep candidate N12/R300 versus baseline N30/R300, all 13 ranks, and
four CPU workers. The first two used source `c8415708`; the later four used
`c02b838f`. The latter adds optional paired ranking and three-trick leaves,
with defaults preserving the original behavior. Each artifact records its
complete executing source and checkpoint identity. Intervals below bootstrap
deal clusters, not the two mirrored rounds as independent samples.

| Variant | Wins / 52 | Signed levels / round (95% interval) | CPU / MC-LCB |
| --- | ---: | ---: | ---: |
| Original combined heads, one trick | 21 | −0.212 [−0.385, −0.038] | 0.976 |
| Original prior only, full rollouts | 23 | −0.115 [−0.346, +0.077] | 0.954 |
| Original value only, one trick | 22 | −0.096 [−0.269, +0.058] | 0.932 |
| Original combined heads, paired ranking | 24 | −0.173 [−0.423, +0.077] | 0.982 |
| Original combined heads, three tricks | 20 | −0.269 [−0.442, −0.115] | 1.000 |
| Sweep prior_weight=3, prior only | 28 | +0.115 [−0.038, +0.269] | 0.962 |
| Sweep aux_search_mean=3, value only | 21 | −0.173 [−0.365, +0.038] | 0.939 |

The checkpoint swaps were chosen before their gameplay outcomes: prior weight
3 for improved prior fitting and auxiliary weight 3 for lower validation value
MAE. Their checkpoint SHAs are respectively
`3d88cb285eb9b60c7f8c2adce5064b6653909dd37c8c628a891959eac8853f39`
and `97005c86ac24f04761c4cde3c4c8bb18249e0e02373e7c0dc602fcfe69766937`.
Both retain explicit legacy-schema loading and have no Luna training data.
The lower-cost value arms are not exactly CPU-matched comparisons.

Interpretation: deeper heuristic continuation did not rescue the value head
on these deals, and lower held-out value error did not translate into better
gameplay here. This does not establish a causal one-vs-three-trick difference
or disprove recursive search. The prior-only checkpoint is the one positive
point estimate, but its interval crosses zero and choosing among reused-deal
arms makes it hypothesis-generating only. Do not expand a configuration sweep
until this hypothesis faces fresh games.

Fresh follow-up: keep that prior-only recipe unchanged on 104 new paired deal
clusters / 208 rounds, seeds `2026090701..2026090804`, same rank cycle and
N12/R300 versus N30/R300, in `fresh-prior3-n12-104`. Plan and all raw
diagnostic artifacts are preserved in the archive above. Expected wall is
7–9 minutes with four Mini CPU workers, leaving the MPS training sweep alone.
Do not stop or tune on intermediate outcomes. Report measured cost and failures
alongside results; a positive screen still needs a no-learning allocation
control before attributing the result to a learned prior.

Fresh-screen engineering finding: at `c02b838f`, cluster 14 reached 27,346
legal actions whose float32 softmax summed to 1.000001471914402. The consumer
correctly rejected that non-unit distribution. Only 12 complete pairs were
published: the executor's context-manager exit waited for all queued tasks
before reporting the exception, discarding their later results. The partial
artifact is retained and is not a gameplay verdict. Repair `90c5a614` normalizes
the global emitted probability mass without relaxing the consumer guard,
bounds in-flight work, reports failure immediately, and saves already-running
successes. All 37 focused tests pass, including a main-path failure/draining
witness; the exact failed pair now completes. One independent delta review
passed. The comparison restarts in `fresh-prior3-n12-104-repaired` on the
same 104 seeds and settings, carrying the new numerical producer identity.
Old partials remain separate; no seed or model selection used their outcomes.

One fixed control follows regardless of that result's sign:
`fresh-uniform-n12-104`, same seeds and N12/R300, exhaustive legal actions and
full rollouts but uniform root priors (no learned prior or value). It retains
the same allocator and report rule. Compare measured costs as well as outcomes
before attributing any benefit to learning rather than broader search.

## Run and recover

From `server/`, with the reviewed native extension built:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
  OPENBLAS_NUM_THREADS=1 python scripts/learned_search_screen.py \
  --checkpoint /path/to/lc-8000/best.pt --allow-legacy \
  --arm both --candidate-select-worlds 12 --clusters 26 \
  --seed0 2026090601 --workers 4 --out /path/to/fresh-dev-output
```

Each complete mirrored pair publishes atomically. Progress is printed at
least every 30 seconds. A failure preserves completed pairs and a typed
diagnostic; rerun the same command to finish only missing pairs. Changed
policy/model inputs cannot silently mix into the existing output directory.
The first summary is the result; there is no duplicate multi-hour integrity
pass. No long-running cloud data or GPU training job is stopped for this run.
