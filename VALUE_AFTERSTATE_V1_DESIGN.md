# Value-Afterstate V1 — action-relative successor value

Status: design only. No data opening, training, gameplay, merge, strength,
promotion, deployment, or R5 authority.

Date: 2026-08-28

V0 source: `d9ad99f6377040424821d79071e12435fde802ae`

V0 independently reconstructed terminal:
`REFUSE_MECHANICS_OR_NEGATIVE_CONTROL`

V0 population manifest SHA-256:
`361389bfd87beebd6c10b4c40712638ef7db900ac0b1a6f62e6dfbd11ea55912`

V0 independent verification receipt SHA-256:
`26a165374104993fa1014425724881c307c98af51e184cd68f0fcda429dffa62`

V0 reconstructed terminal SHA-256:
`53b2afc98a8ebf26556894d823e7a325a2b5693bf417fdc783fda3eb9a477c2b`

This is a successor design, not a retry of V0. It changes the estimand from
absolute game outcome to the paired advantage of one engine-applied action
over the protected production incumbent. The first stage reuses only V0
train/calibration rows and must prove that the continuation labels contain a
stable action signal before another report population is generated.

## 1. Why V0 closed

V0 learned a real held-out base-rate signal but not the signal search needs.
The independently reconstructed result was:

| V0 result | Mean | One-sided/bootstrap interval |
|---|---:|---:|
| Natural NLL improvement | +0.404495 nats | lower +0.062702 |
| Geometry-label permutation | +0.403554 nats | lower +0.060474 |
| Complete-world shuffle | +0.426336 nats | lower +0.068957 |
| Expected-utility-error improvement | -969,028 ppm | [-1,170,085, -656,417] |
| Simple-regret improvement | -125,000 ppm | [-202,055, -17,858] |
| Protected-incumbent non-regression | -129,808 ppm | [-191,177, -51,283] |

All eight natural members improved absolute NLL, but all eight members of both
negative controls did too. Shuffling away the complete hidden world actually
improved the headline score. The action gate was harmful in all three measures
with intervals below zero. V0 therefore showed that the public game phase,
role, points and other broad context predict final outcome, while failing to
show that the model understood which sibling action or hidden world caused a
better continuation.

Increasing V0 model size, training epochs, data volume, or the report threshold
would preserve the wrong estimand. V1 must remove the shared state-level
outcome signal from the learning target.

## 2. V1 question and boundaries

V1 asks:

> In one known complete world, can a shared successor encoder predict which
> engine-applied candidate improves continuation utility relative to the
> protected incumbent?

V1 does **not** ask whether:

- a network can predict the absolute winner of a game;
- PT prose or a PT-selected move is numeric truth;
- a learned value can replace search;
- a BELIEF posterior is correct or useful;
- the production ballot contains the globally best legal action; or
- the model improves whole-game strength.

The engine still applies every candidate. Engine-owned continuations still
produce every numeric outcome. Search remains the final decision authority.
PT-Sol/PT-Luna may contribute reviewed state distributions later, but never
target values in this experiment.

## 3. The action-relative estimand

For root state group `g`, candidate `a`, protected incumbent `0`, and shared
continuation replicate `r`, let:

```text
u(g, a, r) = signed-level utility from the engine-owned continuation
d(g, a, r) = u(g, a, r) - u(g, 0, r)
```

The existing continuation identity deliberately omits the sibling candidate,
so the same `(state_group_id, world_occurrence, replicate)` derives the random
stream for every candidate. Divergence after the root action is real game
dynamics, not a separately selected seed.

Both utilities are half-integers; `d` is an integer in `[-203, +203]`.
Candidate zero has a mechanically exact advantage of zero. Non-incumbent
pairs are the training population. Weight is equal first by root state, then
by candidate, then by replicate, so wide ballots cannot dominate the loss.

This subtraction is the central V1 change. Root-state win probability, team
role, trump, points and game phase are identical on the two sides and cancel.
The learner receives credit only for variation associated with the two
engine-reached successors.

## 4. Three stages, with cheap failure first

### V1-P0 — paired-label ceiling audit

Before training, reopen only the already-sealed V0 `train` and `calibration`
rows. Never open or reuse the V0 `report` or `provider-audit` folds for V1
selection. Reconstruct the paired advantages and publish:

- eligible root states with at least two candidates;
- nonzero-advantage and best-action-flip dose;
- per-source, early/middle/late, lead/follow, role, trump-rank and trump-mode
  counts;
- replicate-to-replicate advantage correlation and sign agreement;
- cross-fit action utility: choose with replicate 0 and score with replicate 1,
  then reverse and average; and
- cross-fit simple regret against always retaining the incumbent.

P0 passes only if both cross-fit directions have positive mean improvement,
their combined deal-bootstrap lower bound is strictly positive, and the
held-out non-incumbent selection dose is at least 5% of eligible states. The
5% floor is a mechanism floor, not a whole-game transport claim. If P0 fails,
terminalize `STOP_NO_REPRODUCIBLE_ACTION_LABEL`; do not train V1 and do not buy
more rows for the same continuation recipe.

P0 is diagnostic use of previously opened development data. It grants no new
scientific claim and cannot tune a future report threshold.

### V1-P1 — action-relative train/calibration pilot

If P0 passes, derive an outcome-blind sub-split of the original V0 train fold:

- `fit`: model optimization;
- `select`: one common epoch for all members; and
- the original V0 `calibration` fold: a single untouched P1 audit.

Whole deal groups remain indivisible. The exact sub-split counts and hashes are
frozen before training. P1 must never open V0 report/provider-audit bytes.

Train eight fixed fresh initialization seeds. V0 checkpoints are not warm
starts: their dominant absolute-outcome representation is the failure V1 is
designed to avoid. Select one common epoch; no member-specific epoch, seed
dropping, retry, or audit-driven extension is allowed.

P1 is deliberately a development mechanism pilot. It decides whether an
action-relative model is worth a new dataset, not whether it may enter search.

### V1-P2 — compatible-world interaction packet

P2 is designed only if P1 learns action advantage. It creates multiple
engine-valid hidden worlds for the same actor-visible root and applies the
same frozen ballot and continuation identities in every world. It measures:

```text
I(g, a, w1, w2) = d(g, a, w1) - d(g, a, w2)
```

This is the first direct test of the reason BELIEF could matter: whether the
best action or its advantage changes across worlds that the actor cannot
distinguish. Public-twin worlds must have byte-identical actor observations,
different complete allocations, and separately reconstructed legal engine
transitions.

P2 must census world-sensitive decision dose before training. If compatible
worlds almost never change action value, a better posterior has no measured
consumer on this surface. P2 requires its own source+population review; P1
cannot silently generate or select those worlds.

## 5. V1-P1 model

Use the V0 public/history/world/perspective encoders as a starting shape, but
replace the 204-way absolute-outcome head with one shared bounded scalar scorer:

```text
q_theta(successor, root perspective) in [-101.5, +101.5]

A_theta(g, a) = q_theta(successor(g, a))
                - q_theta(successor(g, incumbent))
```

The same encoder and scalar head process both siblings. There is no free-form
action input: the action is represented only through the byte-verified state
the engine reached. Identical successor tensors therefore produce exactly zero
advantage, and swapping candidate/incumbent negates the prediction.

Train on paired raw `d(g,a,r)` using Smooth L1 loss with a one-level transition
point. The prediction is bounded by construction; no clipping is hidden in
evaluation. The only learned output is action-relative advantage. V1 adds no
policy, BELIEF, uncertainty, allocation, proposal, or absolute-value head.

The implementation may reference the immutable V0 successor tensor cache by
SHA-256 instead of copying tensors. Every pair record binds:

- root/deal identity and fold;
- incumbent and candidate indexes/actions;
- both successor hashes and tensor hashes;
- shared continuation identity and replicate;
- both raw terminal outcomes; and
- the mechanically rederived integer advantage.

The scorer receives none of the identity, fold, seed, source, label or artifact
path fields.

## 6. Gates

All interval inference is clustered by deal, not by candidate or repeated
outcome.

### P1 primary action gates

On the untouched P1 audit fold, freeze predictions before opening paired
outcomes and require all of:

1. **Advantage error:** ensemble absolute-error improvement over the exact
   zero-advantage baseline has a strictly positive one-sided bootstrap lower
   bound.
2. **Action utility:** choose the maximum predicted advantage, including the
   incumbent at exactly zero and breaking ties to it. Realized utility over
   always keeping the incumbent has a strictly positive lower bound.
3. **Simple regret:** model-choice regret improves over incumbent-choice regret
   with a strictly positive lower bound.
4. **Seed stability:** at least six of eight individual members have positive
   mean realized utility improvement over the incumbent.
5. **Dose:** the ensemble selects a non-incumbent on at least 5% of eligible
   states; report conditional utility and catastrophic tail on those states.

Absolute outcome NLL may be reported only as a historical diagnostic. It is
not a V1 gate and cannot rescue a failed action result.

### Controls that must fail on demand

1. **Root-only / identical-successor:** replace the candidate successor with
   the incumbent successor. Predicted advantage must be byte-exact zero and
   the action gates must fail.
2. **Action-association permutation:** rotate candidate-successor bindings
   across outcome-blind matched geometry buckets while retaining root-state
   and label marginals. The transform must change at least 90% of eligible
   non-incumbent pairs, and the control cohort must fail the primary action
   gates.
3. **Label permutation:** independently rotate paired advantages across the
   same matched buckets. A full fixed-seed control cohort must fail the primary
   action gates.
4. **Complete-world shuffle:** at inference, rotate only the complete-world
   tensors while keeping public successor/action pairs fixed. Report the
   natural-minus-shuffled advantage error and action utility. A positive
   lower bound is required for `PASS_TO_WORLD_TWIN_PACKET_REVIEW`; otherwise a
   model may at most terminalize `PASS_ACTION_ONLY_NO_WORLD_SIGNAL`.
5. **Symmetry:** swapping candidate and incumbent negates predictions; an
   identical pair is zero; root-actor rotation preserves the paired result.
6. **Integrity mutations:** transition, ballot, continuation, perspective,
   utility, pair binding, fold and tensor-hash mutations must refuse before
   parsing or prediction as applicable.

Every control publishes actual changed-row counts and hashes. A named control
with zero dose is a mechanics refusal, never a passing negative result.

## 7. Terminal routes

P0/P1 has exactly these terminal outcomes:

- `REFUSE_MECHANICS_OR_CONTROL` — an integrity, split, reconstruction,
  symmetry, negative-control, resource, or one-opening invariant failed.
- `STOP_NO_REPRODUCIBLE_ACTION_LABEL` — the paired continuation outcomes did
  not support stable action selection; close this continuation/label recipe.
- `SELECT_NONE_NO_ACTION_ADVANTAGE` — labels passed P0 but the model failed an
  action gate; close this model/target recipe.
- `PASS_ACTION_ONLY_NO_WORLD_SIGNAL` — action gates passed but complete-world
  removal did not hurt. This may motivate a separately designed public
  action-value model, but grants no BELIEF or known-world-search authority.
- `PASS_TO_WORLD_TWIN_PACKET_REVIEW` — action gates and the provisional world
  ablation passed. This authorizes only proposing P2; it does not authorize P2
  execution, E5, gameplay or strength evaluation.

There is no threshold relaxation, report extension, seed retry, member drop,
or post-result population increase.

## 8. Performance and observability

P0/P1 is intentionally cheaper than V0:

- reuse only V0 train/calibration continuation and tensor artifacts;
- create a small pair manifest rather than duplicate successor tensors;
- collate incumbent tensors once per root batch and broadcast them across
  sibling candidates;
- run the eight natural members and the fixed control cohort in bounded
  parallel worker slots chosen by a score-free memory/throughput receipt; and
- independently reopen pair manifests and predictions without rerunning engine
  continuations unless a sampled can-fail audit detects drift.

The capacity receipt must measure 1/2/4/8/16-worker scaling where the host
supports it, choose the fastest configuration below the memory limit, and
state CPU utilization rather than assuming all-core scaling. Scientific
execution reports percent, completed/total units, throughput, rolling ETA,
CPU/device utilization and peak memory for pair construction, every epoch,
each control, audit scoring and reconstruction.

No all-or-nothing multi-day run is allowed before P0 and a miniature full-path
rehearsal pass. The rehearsal uses synthetic or train-only rows, proves every
stage and refusal path, publishes no learning conclusion, and may not choose
architecture or thresholds.

## 9. Review and authority

The implementation should arrive as one consolidated packet containing:

- this design and the exact V0 result/reconstruction bindings;
- pair-schema, label-ceiling, model, training, evaluation and control code;
- can-fail witnesses at the consumer/wiring altitude;
- a score-free capacity receipt and exact P0/P1 population hashes;
- runtime/native/source bindings and resource caps;
- the synthetic/train-only end-to-end rehearsal receipt; and
- an all-false authority map except for one P0/P1 train/calibration-only
  execution and its immediate independent reconstruction.

P0/P1 review must explicitly keep V0 report/provider-audit opening, P2, E5,
gameplay, strength, merge, promotion, deployment, R5, retry and test extension
false. One consolidated source+packet review is preferred over separate design,
capacity and freeze review loops.

## 10. Relationship to search and BELIEF

If V1 eventually reaches a consumer, search still expands legal actions and
owns the final aggregate. The first consumer would compare, at equal wall
work, literal known-world rollouts against a hybrid that uses V1 only to score
engine-reached successors, with a literal-rollout floor and protected
incumbent guard.

BELIEF remains a separate component. Only after P2 proves that action values
change across compatible worlds would a later search design compute:

```text
Q(a | public observation)
    = expectation over sampled compatible worlds of A_theta(world, a)
```

That composition is never trained or inferred in V1-P1. Keeping the pieces
separate lets an action-value failure, a world-sensitivity failure and a belief
calibration failure remain distinguishable.
