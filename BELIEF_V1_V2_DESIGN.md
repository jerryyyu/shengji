# BELIEF-V1 V2: diverse population, replayed reference, and scale design

Status: conditional design draft. This document authorizes no corpus access,
capture, training, cloud use, test opening, sampler execution, gameplay,
strength claim, promotion, or deployment. The immutable V1 B2 pipeline at
source `959c05de3b1ac379a6f9595b516608427486243d` remains unchanged.

## Decision and relationship to V1

V1 B2 asks whether `HistoryOwnershipV1` beats the sound constraint reference
on a fresh 4,096-round, rank-2, champion-self-play population. V2 is not a
retry of that population. It addresses four separately identifiable limits:

1. V1 starts a new `Game`, whose initial level is always rank 2. V1 is
   internally valid but cannot establish cross-rank calibration.
2. Champion self-play supplies the production-primary distribution but
   underproduces several human-relevant behavioral signals.
3. V1 REF-C reconstructs each state by repeating champion search even though
   the public decisions are already sealed.
4. V1 training uses only two CPU workers. Before scaling data, the project
   must measure whether input reconstruction, model compute, or cohort
   serialization is the actual training bottleneck.

The V1 terminal result controls routing:

- `PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW`: preserve the exact V1 result;
  use V2 to test rank, policy-domain, and human transfer while B3 sampler work
  proceeds behind its own review.
- `SELECT_NONE_NO_CALIBRATION_LIFT`: close the exact V1 recipe. V2 may proceed
  only if the terminal curves or preregistered strata support a named
  data-coverage or domain-shift explanation; merely training the same recipe
  on more rows is not re-entry.
- any `REFUSE_*`: repair the identified mechanics or evidence boundary before
  scale. A refusal never becomes permission to regenerate the population.

## Primary questions

V2 answers three questions without conflating them:

1. **Rank robustness:** does the ownership model remain calibrated across all
   legal trump ranks, rather than only rank 2?
2. **Policy transfer:** does a champion-trained belief transfer to human play,
   and does a bounded human training mixture improve human calibration without
   materially damaging the champion-primary distribution?
3. **Scale response:** at the same architecture and target, does a larger,
   more diverse corpus improve untouched proper score enough to justify B3?

It does not claim strength. Search, ballot, continuation, or rollout policy do
not change in this offline design.

## Synthetic population

The proposed primary synthetic population contains exactly 13,312 complete
champion-self-play rounds:

```text
16 lanes * 13 trump ranks * 64 rounds = 13,312 rounds
1,024 rounds per trump rank
832 rounds per lane
```

Every lane contains exactly 64 rounds at every rank. The 13 rank labels are
the engine's complete `RANKS` population, in canonical engine order. Rank is a
frozen population coordinate, not inferred from a random declaration or
selected after capture.

Each round is instantiated with the assigned trump rank and first-round
banker semantics. The implementation must use an explicit research round
factory equivalent to `Round(trump_rank, banker=None, rng=Random(seed))` or a
reviewed engine API with identical semantics. It must not set a non-null
banker merely to make `Game.start_round()` respect `level_idx`, because doing
so changes first-round declaration and banker behavior.

The design freeze must derive a fresh seed namespace from the exact source,
protocol, population schema, and literal rank schedule. The current actor-row
contract recomputes its train/calibration/test split from the round seed, so
V2 must preserve that validator rather than stamp an external split label.
For each rank, the protocol walks a domain-separated SHA-256 candidate stream
and accepts the first seeds required for the three frozen split quotas. It
then orders the accepted coordinates with a second domain-separated key and
assigns lanes round-robin. Candidate selection observes only the seed and its
hash-derived split—never a deal, decision, stratum, or outcome. A source-
independent registry scan must reject every known population collision. Rank
assignments are balanced before any deal is generated; no later failure may
substitute a seed or drop a row.

The split is by complete round and balanced within every trump rank:

| split | rounds per rank | total rounds |
|---|---:|---:|
| train | 819 | 10,647 |
| calibration | 102 | 1,326 |
| test | 103 | 1,339 |

No state-level oversampling changes the natural-frequency primary. Suit/no-
trump, banker seat/team, actor seat/role, lead/follow, early/middle/late play,
declaration strength, failed throw, proven void, pair/run cap, joker flush,
point discard, and banker-declaration eligibility are reported as observed
strata. Rare-event diagnostics may use a separately labelled targeted corpus;
they may not be pooled into the primary proper score.

## Human corpus and policy diversity

Human data is used, but it is not silently merged with champion self-play.
Before any bytes are opened, one H0 inventory/reconstruction review must bind:

- the complete source-log digest population and consent/privacy boundary;
- pseudonymous game/session groups with no player identity feature;
- the exact hidden hands and kitty available as simulator-only labels;
- the public event surface actually logged at the time of each game;
- an explicit attempted-play channel value such as `complete`, `actor-only`,
  or `absent`; missing attempted throws are never imputed as
  `attempted == actual`; and
- game/session-grouped train, calibration, and test digests. Decisions from
  one game cannot cross folds.

The existing `human_v8` asset is the starting point, not a new anonymous data
search. Its published manifest is
`b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553`;
the manifest records 129 source rounds seen, 122 replayed rounds, seven
incomplete rounds, 2,830 accepted human plays, and 45 accepted human buries
across 30 source files. The later PR #99 point-flow census opened 165 private
rounds; that is a different descriptive corpus and must not be quoted as the
`human_v8` population. `human_shards.py` already binds source-log hashes,
excludes evaluation-only rounds, pseudonymizes players, and reconstructs the
full deck. Its manifest explicitly sets `training_authorized=false`, however,
so neither those artifacts nor their published counts authorize V2 training.

V2 needs a new belief-specific inventory, builder, and explicit review
authority because the current asset was built as a behavior/proposal corpus,
not as an actor/hidden-ownership calibration corpus. H0 may reuse its reviewed
source-provenance approach and disclose only aggregate completeness metadata;
it must not silently reuse the old training authority or treat `human_v8`
rows as ownership labels. The V2 builder must derive labels from reconstructed
rounds while excluding `player_id`, source name, round number, full-deck
metadata, and any world-generating key from model input.

Human games provide two artifacts:

1. an untouched human out-of-distribution evaluation stratum, including its
   natural trump-rank and behavior distribution; and
2. a bounded human-mixture training arm, compared against a synthetic-only
   control with the same architecture, seeds, epoch rule, and synthetic rows.

The initial mixture proposal is a maximum 20% of optimizer decisions from the
human-training fold. The exact fraction is frozen only after the H0 inventory
reports available complete rounds and decision counts. It is never tuned on
human test performance. A coarse actor-visible policy-family field may name
`champion`, `human`, or a reviewed named-bot family by relative seat;
individual identity, username, session, and source-file identity are
forbidden model inputs.

V1's `behavior_policy_ids` are hash-bound metadata but are not tensorized into
the model. V2 must therefore choose explicitly between:

- a universal mixed-policy model, which receives no policy identity and is
  evaluated as an average across the frozen mixture; or
- a coarse per-relative-seat policy-family feature, which is a versioned model
  input and must pass a public-information/runtime-availability audit.

The initial human-mixture arm uses the universal model so data diversity is
the only model-axis change. A policy-conditioned successor is admitted only
if calibration shows a preregistered, opposing human-versus-champion transfer
residual that the universal model cannot fit. This prevents human data and a
new policy-conditioning architecture from being credited together.

The mixed arm is retained for test evaluation only if, on calibration:

- its human proper-score lower bound versus the synthetic-only model is
  positive; and
- it does not exceed the preregistered material-regression tolerance on the
  champion-primary calibration population or any load-bearing trump-rank
  stratum.

Otherwise the synthetic-only model remains the V2 candidate and the human
result is recorded as a transfer diagnostic. This prevents the small human
corpus from changing the primary estimand merely because it is interesting.

A named-bot or deliberately behavior-rich corpus may be added only as a
separate auxiliary stratum after a train-only prevalence census. It exists to
make declined feeds, forced-joker evidence, unforced point discards, and
failed throws evaluable; it does not substitute for natural champion or human
frequency.

## Correctness audit before capture

The V2 source review must prove each item with a positive and failing witness:

1. all 13 trump ranks reconstruct byte-identical actor/target rows, legal
   ordering, declarations, voids, pairs, tractors, and points;
2. a banker-declarer's still-unplayed shown copy is eligible for banker hand
   or hidden kitty for a non-banker observer, never forced into the hand;
3. the production sampler and REF-C either share this sound rule or publish an
   explicit, separately named baseline difference—V1's adapter repair may not
   hide a production-sampler contradiction;
4. actor-visible failed-throw information matches the engine broadcast surface
   for synthetic and human rows, including a real attempted-versus-actual
   divergence witness;
5. human rows with an absent attempted channel use a versioned input mask and
   cannot be serialized as complete;
6. overwritten declarations, banker-known burial, public pass/timing fields,
   and game-level context are either represented or named as V2 omissions;
7. rank, deal seed, policy RNG streams, split, and source-log digests are
   domain-separated and reproducible;
8. target labels remain in separate sealed bytes and no round seed, log path,
   player identity, or target manifest enters model input; and
9. rank/policy/game-group rotations and hidden-world twins preserve the
   versioned actor observation exactly.

Rank-2-only coverage is a population-scope defect, not evidence that V1's
rank-2 rows are wrong. False hard constraints, train/evaluation leakage, or
engine-public mismatches are correctness defects and stop V2 before scale.

The current tensor schema already allocates a 13-way trump-rank one-hot and
recomputes every card's effective suit/level from the actor's ordering. V2
therefore does not need a larger input shape merely to support other ranks.
The problem is statistical: V1 activates only the rank-2 column, leaving the
other twelve rank columns and their interactions untrained. Cross-rank tests
must prove the existing representation is sufficient before adding new rank-
specific features or increasing model size.

## REF-C transcript replay

PR #116 exact source `478091e99f4810f20afffde7e73f093311267bf7`
provides the intended synthetic replay building block. It replays sealed
attempted plays through the engine, recomputes every actor row, and requires
byte identity instead of rerunning champion `decide_play` search.

Local child `9aabdcd` (not yet pushed) adds the two additional load-bearing
witnesses required before adoption:

1. replay a genuine failed throw where attempted and engine-actual cards
   differ and require byte-identical downstream state; and
2. replay one exact `mc-s0-report-lcb` champion capture under the
   source/runtime mode used by V2, rather than proving only heuristic-policy
   fixtures.

The repaired test file passes 9 tests plus one production-fast-only skip in
pure mode, all 10 in strict compiled mode, and the 16 neighboring
capture/reference tests in strict compiled mode. Review must bind the exact
PR #116 parent-to-child delta; the local child does not itself merge or
authorize replay execution.

The integrated V2 reference driver must construct declaration/bury policies
from the source-pinned policy registry rather than accept an unbound arbitrary
list. It must reauthenticate policy seeds, policy source, rank, and captured
round identity. The captured actor bytes remain authority; a replay shortcut
that differs at any decision refuses the round and the population, never
falls back to search, substitutes a seed, or drops the row.

Human replay is a separate adapter because a log digest replaces the synthetic
round seed and attempted-play completeness varies. It must reconstruct the
same versioned actor bytes from public events and sealed hidden labels without
inventing unavailable events.

## Performance plan

V2 optimizes measured stages in this order:

1. **Reference reconstruction:** land transcript replay. The V1 Mini result
   showed that champion re-search, not constraint sampling, dominated REF-C.
2. **Capture:** profile exact multi-rank champion capture with native mode on
   a small out-of-population matrix. Preserve one search trajectory and derive
   actor rows, targets, transcript, and later reference states from it once.
3. **Input pipeline:** profile canonical-row parsing, tensor construction, and
   optimizer compute independently. If parsing dominates, publish a hash-bound
   train/calibration tensor cache that contains actor features only and proves
   split/target isolation.
4. **Cohort execution:** compare the current two-process layout with
   deterministic per-member workers or an ensemble-batched implementation.
   Preserve all 8+8 members, exact common-epoch selection, and receipt chains;
   no best seed may be retained.
5. **Device choice:** benchmark one source-pinned epoch on Mini and the intended
   cloud device. A cloud accelerator is used only if end-to-end wall time,
   including input transfer, materially improves under identical numerics.
6. **Native sampler work:** profile only after replay. A native REF-C assignment
   kernel is lower priority if replay reduces the complete reference stage to
   a small fraction of capture/training cost.

The source audit already identifies two concrete V1 costs to measure. Each
cohort pins Torch to one thread, and `train_cohort_epoch_stream` applies every
batch to all eight models in a serial Python loop. In addition,
`_iter_corpus_batches` reopens corpus bundles and reconstructs actor tensors on
every train and calibration epoch. V2 should therefore benchmark, in order:

- one immutable actor-tensor cache shared by candidate and control labels;
- one independent worker per model member reading that cache; and
- an ensemble-batched/vmapped implementation only if it preserves the exact
  independent AdamW/member semantics and is faster than the simpler workers.

The cache may contain actor-derived tensors and split/decision identities. It
must keep privileged labels in a separately bound artifact and must never
materialize test tensors before the single test opening. Parallel member
workers must reproduce the serial reference's per-member state and loss bytes
on a small fixture before they become the V2 training path.

Performance changes must be bit-identical at the artifact or probability
contract they claim to preserve. A faster implementation never inherits
scientific or strength authority.

## Preliminary capacity projection and host allocation

V1's preflight measured approximately 7.096 seconds per champion round and
about 0.5 MiB of canonical capture artifacts per round. Applied only as a
planning estimate, 13,312 rounds imply approximately:

- 26.2 capture core-hours before concurrency overhead; and
- 6.7 GiB of capture artifacts before model/reference/checkpoint receipts.

These are not caps. An exact multi-rank, full-concurrency capacity preflight
must measure mean and p95 round wall, CPU, peak RSS, storage, failed-throw
coverage, and all rank cells outside the production seed namespace. The
reviewed design then freezes caps with explicit margin and an automatic
refusal before population capture if the host does not qualify.

After capture is sealed, the dependency graph permits:

```text
                    +--> synthetic-only training --------+
rank/human capture -+--> bounded human-mixture training --+--> calibration
                    +--> REF-C transcript replay ---------+
```

REF-C is not a training dependency. It may run concurrently with training,
but replay should make it inexpensive enough for Mini. The intended cloud
priority is multi-rank champion capture and whichever training layout wins the
source-pinned epoch benchmark. No cloud should be powered merely to hold an
idle reviewed process.

The current immutable V1 supervisor remains sequential and may not be split,
migrated, or retrofitted with any V2 optimization.

## Gates and terminal routing

V2 retains the V1 mechanics, isolation, proper-score, calibration, negative-
control, and exact-synthetic gates. It additionally requires:

- a positive primary proper-score lower bound across the complete balanced
  synthetic test population;
- no preregistered material regression in any adequately powered trump-rank
  stratum;
- a reported human transfer result with confidence interval and exact n;
- a separately reported mixed-training result—never pooled with synthetic-
  only without the calibration rule above;
- learning curves versus data volume, so a scale claim distinguishes
  data-limited improvement from a flat recipe; and
- exact cost per captured round, reference decision, training decision/epoch,
  and retained checkpoint.

If the synthetic model fails again with no rank-specific or data-scaling
signal, this exact model/target family closes; V2 does not escalate to a larger
model by default. If it passes, B3 must still prove complete legal world
sampling, preservation of the calibrated marginals, joint-event calibration,
fixed-world value quality, and natural final-decision flip dose before any
same-work search screen.

## Consolidated review path

To avoid repeated source/design/admission round trips:

1. one source/design review binds the rank factory, PR #116 successor, human
   reconstruction boundary, model arms, exact population, profiling result,
   host/runtime, caps, metrics, and automatic routing;
2. that exact PASS may authorize the bounded score-free capture, parallel
   training/reference DAG, and one test opening under one immutable packet;
3. one terminal review independently reopens the result and routes B3 or
   closure.

No intermediate capacity, corpus, model, or reference milestone receives a
separate review if it is already closed and mechanically routed by the same
immutable design. A new review is required only when code, estimand,
population, authority, or sealed-resource boundary changes.

## Inputs still required before freeze

- the reviewed V1 B2 terminal result and resource receipts;
- exact review disposition and repair head for PR #116;
- a score-free H0 human-log inventory and public-event completeness report;
- a source-pinned multi-rank capacity/profile result;
- the exact fresh seed namespace, split hashes, and source-log digest set;
- frozen human-mixture fraction and material-regression tolerance; and
- exact host/runtime/native identities and final caps.

Until those inputs exist, this document is a design proposal only.
