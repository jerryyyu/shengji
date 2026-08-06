# Teacher-v1 staged experiment spec

Status: proposed for execution, 2026-08-05. This is the operational contract
for the new counterfactual training/challenge asset. It is not an extension of
DEV-512 and may not read or score CALIB-512 or REPORT.

## Objective and stop rule

Produce action-ranking and scoring-bracket targets that can improve compiled
`mc-strong` N=30, rather than more precise labels for the old heuristic ceiling.
Stop a stage when its gate fails. A clean mechanics check alone does not prove
teacher usefulness; a held-out teacher gain alone does not prove bot strength.

## Immutable identity

- Fresh self-play deal seeds start at `120000000`; one selected state per deal.
- State actor is the version-pinned production champion. Store its checkpoint/
  policy identity, git tree, engine, sampler, Memory, action encoder and exact
  `BallotSpec` digests.
- Derive independent RNG streams from experiment id + deal + state + candidate
  + fold for state selection, belief worlds, continuation and evaluation. Store
  the derivation inputs, not only a mutable RNG-state digest.
- Strict sampling is mandatory. Any illegal/unheld action, replay mismatch,
  zero-world decision, rejection, invalid world or named skip fails the shard.
- Freeze exact state identities and split assignment before action outcomes are
  inspected. Train/tune/holdout are deal-disjoint 70/15/15 hashes. Existing
  DEV/CALIB/REPORT deals are excluded from all three.

## State population

The full pilot contains 2,048 states:

- 1,536 representative states: exactly 128 in each phase x role x decision
  cell, where phase is early (`trick < 5`), mid (`5..11`) or late (`>=12`),
  role is attacker/defender and decision is lead/follow;
- 256 boundary states: among a separate fresh-deal pool, smallest absolute
  distance between the N=30 best-minus-candidate-0 gap and the five-point
  override margin; and
- 256 uncertainty/disagreement states: highest paired SE among remaining
  states where Smart/candidate-0, N=30 and v11pair are not unanimous, filled by
  highest SE if the disagreement supply is short.

The two reconstructed QHKR incidents are challenge regressions outside the
2,048 training rows. Record candidate count, role, banker identity, phase,
lead/follow, action archetype and selection probability/stratum so deployment-
weighted diagnostics remain possible.

## Label tensor

For every state, store exact replay, every current-ballot candidate and 512
strict common worlds shared by all candidates. Split worlds before scoring:
256 selection and 256 report. For every `(state, fold, world, candidate)` store
terminal attacker points, acting-team signed points, scoring bracket and signed
level utility. Also store paired deltas/moments versus candidate 0, sampler
counters, continuation id and exact candidate-world work. Compressed shards may
store the dense tensor; the manifest must expose its shape and hashes.

The bulk continuation candidate is the deterministic heuristic only because it
is cheap. It is not presumed to be a valid teacher.

## Stage A — 64-state mechanics preflight

Use 48 representative states (four per phase/role/decision cell) plus 16
boundary/uncertainty states. Run the full 512-world label schema.

Pass requires 64/64 exact replays, complete legal held ballots, 512/512 accepted
worlds per state, exact tensor shapes, fold disjointness, deterministic rerun
hashes, all counters zero and a measured runtime/work projection. Failure stops
and repairs the producer. Passing authorizes Stage B, not the 2,048-state wave.

## Stage B — continuation-quality gate

Freeze 128 stratified states from the fresh pilot population. On the same
candidates, add a gold continuation:

- production `mc-strong` N=30 for downstream partial-information decisions;
- exact/minimax continuation where the registered late-state solver is
  tractable **and information-set legal**. A solver that lets a player act on
  opponents' hidden hands is an oracle diagnostic, not a deployable gold
  continuation; and
- 64 gold-selection plus 64 disjoint gold-report common worlds per action,
  with deterministic inner policy seeds.

Choose the cheap action on its selection fold and the gold reference action on
the gold-selection fold. On gold-report worlds, estimate paired signed-level
regret of the cheap choice versus that frozen gold reference, clustered by
state. The gate passes only if its one-sided 95% upper bound is at most 0.10
signed levels per decision. Top-1 agreement and rank correlation are diagnostics,
not substitutes for regret.

- PASS: automatically launch Stage C with the named cheap continuation.
- FAIL or inconclusive: do not bulk-label/train the cheap target. Use the next
  compute block to expand gold worlds to a predeclared fixed cap or label a
  smaller set with the stronger continuation; amend the continuation identity
  before any full wave.

## Stage C — 2,048-state pilot

Shard the frozen state list across the fleet. Expected scale is roughly 7-8M
candidate-world heuristic rollouts if candidate counts resemble current assets.
Merge only exact experiment identities and require global counts, hashes,
strata, split disjointness, work and zero counters. Preserve the raw tensor;
do not collapse it to selected maxima or means.

## Stage D — model and strength gates

Train three seeds at 256, 1,024 and full-train state counts:

- a listwise/pairwise action-ranking head on the exact ballot; and
- a separate calibrated scoring-bracket distribution head.

Tune once on TUNE. Open HOLDOUT once for the frozen candidate. It must reduce
paired report-fold teacher regret versus candidate 0 and v11pair without a
calibration regression. First integrate it as an MC ranker/pruner/allocator;
do not force pairwise deltas into a cross-state leaf.

Only a fresh paired full-game win over compiled `mc-strong` N=30 authorizes a
10k/50k state wave or champion replacement. Use signed level utility as the
primary metric, seat/team flips inside deal clusters, an explicit null and a
single predeclared block. Failed data/model gates free the fleet for structured
bury, exact-late or faithful self-play work; they do not authorize blind scale.
