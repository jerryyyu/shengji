# BELIEF R4 opened-DEV policy diagnostic

Status: source review pending. This document grants no compute launch, test
opening, retry, merge, gameplay registration, strength claim, promotion,
deployment, or R5 authority.

## Decision

The first consumer of the preserved R4 models is a bounded opened-development
mechanism diagnostic, not another belief-training run and not a whole-game
screen. It compares three arms on identical legal actions, sampled worlds,
rollouts and random streams:

1. literal production `mc-s0-report-lcb` sampling and aggregation;
2. the R4 `synthetic-primary` ensemble used only to weight those worlds; and
3. the R4 `hard-geometry-label-permutation` ensemble passed through the same
   weighting code as a learned-signal control.

The diagnostic answers whether the primary posterior changes production search
in useful directions beyond the control's geometry and optimization effects.
It never opens R4 calibration or test evidence. The only R4 bytes admitted are
the authenticated selected training checkpoints and their receipts. R5 remains
paused regardless of the result.

R4 emits receiver-count marginals rather than a correlated joint posterior.
Consequently this experiment deliberately uses a **marginal-ratio weighting
bridge** over already-legal REF-C worlds. It is not called a BELIEF sampler and
cannot certify E1 projection. A later correlated sampler is justified only if
this cheap bridge produces useful policy signal.

## Frozen question and estimands

On a fresh, outcome-blind population of natural production-policy decisions:

- does primary weighting change the N=30 nomination or R=300 protected action;
- do those changes improve a paired true-world continuation value;
- does primary outperform the identically transformed label control;
- does it agree more often with a true-world rollout oracle; and
- can it do so without illegal worlds, world collapse, extra accepted worlds,
  extra logical rollout work or impractical runtime?

The primary estimands, reduced with the round as the independent unit, are:

- primary minus production paired true-world value;
- primary minus label-control paired true-world value; and
- each arm's exact final-action agreement with the true-world rollout oracle.

Decision-flip dose, nomination dose, raw/applied ESS, tempering, runtime,
accepted-world attempts, logical/physical rollout work and effects by rank,
role, lead/follow and round progress are named secondary estimands. Progress is
frozen by public decision index as early 0-24, middle 25-49, and late 50+.
Secondary strata publish counts and point estimates only; they cannot override
the round-bootstrap primary route. Every valid result is retained; an imprecise
or null result is not converted into a mechanics refusal.

## Fixed inputs

- Base policy: literal registry policy `mc-s0-report-lcb`.
- Selection dose: N=30 common complete worlds over the production ballot.
- Report dose: R=300 fresh common complete worlds.
- Protected incumbent: ballot index zero, with production's one-sided
  critical value 1.70 and minimum report gain zero.
- Continuation: the exact production `MCBot._rollout` continuation and scoring
  objective at the reviewed source head.
- Primary cohort ID: `synthetic-primary`, all eight selected members averaged
  by the existing `ensemble_ownership` contract.
- Control cohort ID: `hard-geometry-label-permutation`, also all eight selected
  members and the identical ensemble/weighting path.
- Model surface: `v2_scoring_actor`, V2 common-surface tensors and
  `UNIVERSAL_POLICY_IDS`; no attempted-card/source-channel feature is restored.
- Proposal reference: an independent 256-world batch from the literal
  production sampler for each selected decision. This `REF-PROD-256` estimate
  describes the worlds the deployed search can actually produce; it is not
  R4's sound offline REF-C comparator.

The immutable freeze binds the exact Git head, R4 freeze/admission/training
manifest hashes, 16 checkpoint hashes, policy/runtime/native identities,
population seed namespace, child-RNG derivation, folds, thresholds, progress
contract, worker count selected by capacity, caps and an all-false authority
map.

## Fresh population

The target is exactly 104 independent selected rounds: eight for each trump
rank `2` through `A`. No fixed-rank shortcut is allowed. A registered seed
namespace domain-separated from the R4/V1 populations in this source tree
supplies candidate rounds; the exact 416 candidate coordinates are bound into
the freeze. Within each rank, seeds are scanned in registered ordinal order
until eight qualifying rounds are found, subject to a frozen maximum of 32
scanned rounds per rank. Exhausting that maximum is
`REFUSE_INCOMPLETE_POPULATION`; it never permits a smaller or replacement
population.

All four seats use the source-pinned production policy. Candidate roots are
captured before the acting policy chooses an action. A root qualifies using
only actor-visible state and source mechanics when:

- play is in progress and the production policy would enter search rather than
  tractor-lock or a one-candidate return;
- the exact production ballot has at least two actions;
- strict-void sampling can fill the required work.

The known live-sampler banker-declaration defect is measured rather than
hidden: production pins a banker-declarer's shown card to its hand even though
the card may legally be buried. Every generated world is individually legal,
but the proposal can omit legal kitty worlds. Each root records whether the
actual hidden world is compatible with the proposal pin and whether
`declaration_eligibility` is present. Primary/control weighting cannot create a
world absent from the common proposal, so any support-miss stratum is reported
separately and cannot establish a positive policy route. Fixing production
declaration sampling is a separate reviewed change.

For each qualifying round, choose the root with the smallest SHA-256 of the
registered namespace tag, round seed, decision index and actor-observation
hash. No model output, hidden target, later play or outcome participates in
root selection. Only the chosen root's privileged true world is retained for
the named offline oracle/value audit.

## Common worlds and exact work

Three domain-separated child RNG streams drive fresh instances of the literal
production sampler and produce:

1. 256 reference-only worlds for production-proposal marginals;
2. 30 selection worlds; and
3. 300 report worlds.

Every sampled world must satisfy physical conservation, hand/kitty sizes,
voids, pair caps, run caps and sound declaration eligibility. The sampler is
called through the same `_sample_hands` path, strict-void mode, retry cap and
RNG semantics as `mc-s0-report-lcb`; a source witness compares a harness draw
to a draw made inside the production decision path under the same state and
seed. The 256 reference batch is converted to empirical marginals only after
every world passes the reviewed world validator.

All arms receive the exact same ordered selection and report worlds. Selection
evaluates every production-ballot action once on every one of the 30 worlds.
Each arm may nominate a different challenger. Report evaluates the union of
the incumbent and the three nominated challengers once on each of the 300
worlds. Each arm may read only its incumbent/challenger pair. Thus every arm
has the same logical N×K selection work and 2R report work; physical union work
is recorded separately and cannot be presented as extra evidence for any arm.

Sampler telemetry must prove identical accepted-world count and ordered world
hashes across arms. Attempt/rejection counts, rollout count, wall/CPU time and
core utilization are published per fold and shard.

## Marginal-ratio bridge

For legal world `w`, cohort `m`, active card/receiver cells `j`, projected
cohort probability `p_mj`, and independent empirical production-proposal
probability `p_Pj`, define:

```text
s_m(w) = mean_j log( max(p_mj(count_j(w)), 1e-12)
                     / Jeffreys256(p_Pj(count_j(w))) )
```

`Jeffreys256(k) = (k + 0.5) / (256 + 1.5)` for the three receiver-count
classes. Scores are rounded to integer nanonats before weighting. The mean over
cells keeps the scale comparable as unseen cards disappear; it does not claim
the cells are independent.

For temperature `alpha`, normalize `exp(alpha * s_m(w))` across a fold. The
primary and control must use one common alpha: take the largest value in

```text
1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64, 1/128, 1/256, 0
```

for which **both** arms have ESS at least 50% of the fold and no world carries
more than four times uniform weight. If only zero passes, both learned arms
become uniform for that fold and the shard records zero weighting dose. The
untempered and applied ESS/max-weight values are both retained. Normalized
weights are positive integer ppb summing exactly 1e9.

This common rule prevents a favorable temperature from being chosen separately
for the primary and its negative control. It is chosen without action values,
true-world values or outcomes.

## Search aggregation

Production uses uniform weights. The two learned arms calculate an action mean
over their fold's fixed world weights. Candidate sourcing, point-shy tie break,
incumbent protection and every rollout byte remain production code.

For report deltas `d_i` and normalized weights `w_i`, use:

```text
mean = sum_i w_i d_i
SE^2 = sum_i w_i^2 (d_i - mean)^2 / (1 - sum_i w_i^2)
LCB = mean - 1.70 * SE
```

This reduces to the existing paired sample-mean SE under equal weights. Report
ESS must be at least 30 (implied by the stronger 50% guard). The challenger
replaces candidate zero only when its LCB is nonnegative, exactly as in the
production arm.

## Privileged audit and PT/oracle agreement

After all three final actions are frozen, the engine applies the union of
ballot actions to the actual hidden world and completes each using the same
production rollout continuation. This is offline privileged evaluation; it is
never fed to weighting or selection.

The **true-world rollout oracle** is the ballot action with the best value under
that same continuation, with the production point-shy tie break. PT/oracle
agreement means exact action agreement with this named oracle. It does not
claim equivalence to PT-Sol or PT-Luna reasoning. A later optional join to a
reviewed PT packet must be a separately named descriptive row because fresh
R4 diagnostic roots need not overlap existing PT roots.

## Result and interpretation

Mechanics refuse only for a concrete invalidity: input/checkpoint drift, a test
path open attempt, seed collision, population shortfall, illegal or mismatched
worlds, underfilled work, inconsistent model surfaces, nonfinite weights,
failed ESS guard, action/rollout mismatch, missing shard, cap/deadline expiry or
artifact reconstruction drift.

A complete result publishes paired round-bootstrap point estimates and 95%
intervals for all named estimands. It receives one of three descriptive routes:

- `PRIMARY_POLICY_SIGNAL`: proposal support contains every audited true world,
  and both primary-minus-production and
  primary-minus-control true-world value lower bounds are positive;
- `PRIMARY_SIGNAL_NOT_INTERPRETABLE_PROPOSAL_SUPPORT`: the numeric signal rule
  is positive but at least one audited true world is outside the production
  proposal's support, so no positive policy route is claimed;
- `PRIMARY_NOT_SEPARATED_FROM_CONTROL`: primary-minus-production is positive
  but primary-minus-control is not; or
- `NO_PRIMARY_POLICY_SIGNAL`: primary-minus-production is not positive.

These routes authorize only interpretation and follow-up design. They never
authorize R5, a whole-game screen, policy registration, a strength claim or
deployment. Flip dose, oracle agreement and runtime explain the route; they do
not override it post hoc.

## Efficient, recoverable DAG

```text
authenticate training-only R4 inputs once
                 |
                 +--> score-free worker/memory census (1,4,8,... workers)
                 |
                 v
freeze 104-round coordinates + selected worker count
                 |
     13 trump-rank lanes in parallel
                 |
     immutable one-round result shards
                 |
                 v
single manifest reduction + bootstrap --> terminal result
```

- R4 checkpoint authentication happens once while materializing a read-only
  model-input package. Workers verify its manifest hash, not the full R4 tree.
- Independent rounds are the parallel unit. The Linux worker pool preloads the
  16 models before fork so read-only pages are shared where the measured host
  supports copy-on-write.
- The capacity census runs fixed 1/4/8/13/15-worker arms and selects the largest
  passing arm no greater than the 13 scientific rank lanes only when a larger
  arm also passes memory/swap/headroom checks. No worker count is
  caller-asserted.
- The selected arm's slowest complete root is the frozen next-unit reserve.
  A worker starts no new coordinate unless that reserve still fits before the
  immutable deadline. The scientific wall estimate is eight such roots (the
  target per rank) times the larger of two safety waves or the actual number
  of worker waves needed for 13 rank lanes, and the wall cap is that estimate
  plus the larger of
  50% or 30 minutes, never above 48 hours. If the measured estimate itself
  exceeds 48 hours, freeze construction refuses rather than moving the cap.
- Each round writes an immutable, hash-bound shard atomically. A process or host
  interruption resumes only missing frozen coordinates under the same
  admission and deadline; an existing shard is never overwritten.
- Progress reports stage, scanned/selected/completed rounds, rank counts,
  attempts/worlds/rollouts, immutable shards, queue, workers, CPU utilization,
  RSS, elapsed, ETA and headroom at least every 60 seconds and every completed
  shard.
- Terminal reduction reads each shard once. Reconstruction verifies shard and
  manifest hashes and redoes only the cheap reduction/bootstrap; it never
  reopens models, resamples worlds or reruns rollouts. There is no second
  multi-hour integrity pass.

The capacity receipt supplies measured per-stage rates and therefore the final
scientific ETA. Before that receipt, only caps—not invented point estimates—are
reviewable. Admission uses measured pace; deadline expiry seals every completed
shard and returns an explicit truncated/incomplete route rather than deleting
diagnostic work.

## Review and launch sequence

1. One consolidated design/source review may authorize exactly one score-free
   capacity census on a named opened-DEV host.
2. A passing census produces the immutable freeze and measured ETA/caps without
   source changes.
3. One exact-freeze review may authorize exactly one bounded diagnostic run.

Neither review reopens R4 test data. If source changes after the census, its
receipt is invalid and the combined source/freeze review must say why a fresh
census is or is not required. Review asks must name the exact head, only the
load-bearing witnesses, and the authority granted; no review round exists only
to restate already-passed evidence.
