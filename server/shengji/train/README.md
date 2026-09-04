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
- Apply the candidate in the engine, complete its current trick, and predict
  value for the resulting acting seat. Convert by partnership to root-team
  signed levels. Terminal leaves use the engine result. Value-only and
  prior-only ablations are available, but not a new training sweep.
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
