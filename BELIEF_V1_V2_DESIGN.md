# BELIEF-V1 V2: diverse population, replayed reference, and scale design

Status: conditional design plus locally complete execution-source candidate.
The source still requires one consolidated exact-head review, and the later
host-specific freeze requires its own exact PASS. This document authorizes no
corpus access, capture, training, cloud use, test opening, sampler execution,
gameplay, strength claim, promotion, or deployment. The immutable V1 B2
pipeline at source `959c05de3b1ac379a6f9595b516608427486243d` remains
unchanged.

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
independent registry scan must reject every known population collision. The
freeze-time registry is not an informal grep: it must hash the complete
tracked `server/**/*.py` population plus every durable active (non-archive)
design document and the append-only `HANDOFF_REVIEW.md` evidence ledger. The
mutable `HANDOFF_ACTIVE.md` operational queue is excluded so queue refreshes
cannot circularly invalidate the artifact under review. The scan publishes
the complete `seed`/`round_seed`/`deal_seed` candidate-hit
report, classify every hit as a finite population, a derived per-decision
stream, or a non-population constant, and refuse any unclassified hit. At a
minimum its explicit population table binds B1/B2, C4 synthetic, teacher-v1,
the scored S3/S4/S6/Pair families, this V2 production schedule, and the V2
preflight schedule by literal source path and file SHA-256. The registry
artifact records both the scan-input population digest and the classified
table digest, so deleting a source file or adding an unclassified seed
namespace makes the check fail. Rank assignments are balanced before any deal
is generated; no later failure may substitute a seed or drop a row.

`belief_v2_seed_registry_builder.py` now supplies the real source-pinned table
rather than leaving it to an operator. Large contiguous historical domains
(including the 12-million-deal Pair capture and larger reserved Pair blocks)
are represented as inclusive ranges, while C4, V2 preflight, and V2 production
retain their exact non-contiguous seed lists. The registry publishes those
definitions, not only opaque summary hashes, so its independent reopener can
recompute population counts/digests and the zero-collision verdict without
materializing billion-scale ranges. Lower-case literal `"seed0"` protocol
entries require the same explicit classification as upper-case seed constants.
Classification is a reviewed finite table keyed by exact candidate identity;
the builder must never infer a safe bin from a variable name. A newly added
`NEW_SCREEN_POPULATION_SEED_START`-style candidate is a permanent mutation
witness and must refuse until its population semantics are explicitly added.

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

The review branch implements the score-free H0 inventory in
`belief_v2_human_inventory.py`. It verifies an exact source snapshot, replays
complete rounds far enough to establish hidden-label and attempted-channel
availability, and connects source-log sessions that contain the same human
player into one indivisible future split component,
and emits only aggregate counts and content-derived group digests. It emits no
names, file names, hands, kitty cards, actions, or model rows, and every
training/test/strength authority remains false. The real inventory must not be
run until this source receives the consolidated design PASS.

The first source-authorized component inventory ran against source-manifest
SHA-256 `07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e`.
Its canonical receipt SHA-256 is
`f1ddcd617dc9743d9d1357f09440c40fbf2eef29fc75ff7a8f00b41143a62071`.
It found 30 whole-session groups in 11 cross-file player components, 122
complete and seven incomplete rounds,
and 2,830 eligible human play decisions. The natural trump-rank population is
2=49, 3=21, 4=21, 5=10, 6=3, 7=6, 8=3, 9=3, A=4, Q=2; it is neither fixed at
rank 2 nor rebalanced after observation. Every eligible historical row has an
absent attempted-card channel, so V2 must carry an explicit versioned absence
mask and may never substitute engine-accepted cards for the missing attempted
cards. Hidden ownership is reconstructable for every complete round.

The V2 input adapter resolves this without a source/policy side channel. Both
synthetic and human rows are reduced to the same common engine-replay surface:
the final winning declaration and engine-accepted play cards. Overwritten
declaration chronology, attempted-card vectors, and failed-throw indicators
are masked for every row, even when synthetic capture possesses them. The
source actor's completeness flags remain hash-bound receipt metadata with
`model_input=false`; full synthetic and replay-only views of the same public
state must produce byte-identical model tensors. This is deliberately more
conservative than teaching the model that a missing channel means “human.”

The real component population invalidated the initially reviewed pure-hash
split before freeze: it assigned 27/1/2 groups and 2,812/18/0 eligible
decisions, while the supervisor still expected the old per-file 24/3/3 shape.
That score-free diagnostic receipt is not a freeze input. H0 split V3 repairs
the population contract rather than changing a namespace until a convenient
assignment appears. Positive components are ordered by eligible actor-decision
count and content digest; the largest seeds train, the second calibration and
the third test, and remaining positive components are assigned by the fixed
80/10/10 decision-imbalance objective. Zero-decision components go to train.
The rule uses eligibility counts, but no hidden labels, game outcomes, trump
rank, loss, or model evidence. It never separates a player component or
publishes a raw identity.

The repaired real-population preview assigns 21/4/5 source groups and 7/1/3
player components to train/calibration/test, with 2,323/456/51 eligible
decisions. Its candidate split SHA-256 is
`f29dea82f4497ffe6ad0fea9ed1c143c4d4c9864bd8890e664cceb49ca3b72fd`.
Those bytes must be regenerated from the clean repaired exact head after its
narrow source review; the dirty preview is validation evidence, not a freeze
receipt.

Human games provide two artifacts:

1. an untouched human out-of-distribution evaluation stratum, including its
   natural trump-rank and behavior distribution; and
2. a bounded human-mixture training arm, compared against a synthetic-only
   control with the same architecture, seeds, epoch rule, and exact total
   optimizer-decision count.

The initial mixture consumes every one of the 2,323 H0 training decisions
exactly once per epoch and never oversamples them. Human decisions replace,
rather than add to, the same number of synthetic training decisions; the
synthetic-only control and mixed arm therefore consume the same exact realized
optimizer-decision count in every epoch. The removed synthetic decisions are
selected once from train-only identities by a frozen digest-order rule and
are never selected using labels, loss, calibration, or test evidence. The
exact synthetic decision population is necessarily known only after capture;
the controller must publish and reopen its ordered manifest, exact count, the
removed prefix, and the resulting human fraction before training. The freeze
binds this derivation rule rather than inventing a pre-capture count. Even the
conservative floor of four play decisions per one of 10,647 complete synthetic
training rounds proves the human fraction is below 20%; the realized fraction
is expected to be much smaller and is reported, not tuned. Scale response is
evaluated by separately named digest-prefix synthetic-only data-volume arms;
it cannot be credited to the human-mixture comparison. A coarse actor-visible
policy-family field may name
`champion`, `human`, or a reviewed named-bot family by relative seat;
individual identity, username, session, and source-file identity are
forbidden model inputs.

The implemented realization boundary records a source-neutral SHA-256 round
group for every example. It deterministically derives four closed manifests:
all synthetic decisions for primary; the byte-identical population and batch
schedule for the label-permutation control; all human train decisions replacing
the same digest-ranked number of synthetic decisions for the mixed arm; and the
frozen digest prefix for the synthetic-scale arm. Selected decisions from one
round are kept in one batch, every batch stays at or below 256 decisions, and
the independent reopener reconstructs the exact removal list, population,
round grouping, schedule, active-label count, and work match from source rows.
Source kind and round-group identity stop at this scheduler and are absent from
the model batch.

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

All cohorts use one byte-identical balanced synthetic calibration population
for common-epoch selection. Human calibration groups do not participate in
early stopping; they remain unopened by training and are consumed only by the
preregistered mixed-versus-primary calibration selection below. This keeps the
human mixture from changing both the training distribution and the epoch rule,
and makes the primary, control, mixture, and scale learning curves directly
comparable.

The mixed arm is retained for test evaluation only if, on calibration:

- its human proper-score lower bound versus the synthetic-only model is
  positive; and
- it does not exceed the preregistered material-regression tolerance on the
  champion-primary calibration population or any load-bearing trump-rank
  stratum.

The frozen material-regression tolerance is a relative Brier increase of
0.5%. A rank is load-bearing when it contains at least 100 complete
calibration rounds; the balanced schedule supplies 102. The 13 simultaneous
rank comparisons use one paired round-bootstrap max-statistic, with a
one-sided familywise 95% upper bound. Retention requires the aggregate bound
and every powered rank's familywise bound to remain below +0.5%. No unadjusted
per-rank interval may be substituted after results are visible.

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

The review branch implements the exact synthetic schedule in
`belief_v2_protocol.py` and the rank-bound capture/replay adapters in
`belief_v2_capture.py`. Every one of the 13 ranks has an actor-byte-identical
capture/replay witness, while the default V1 path remains rank 2. One compiled
witness also runs the exact production champion at rank 9. The source/design
proposal still authorizes nothing.

## REF-C transcript replay

PR #116 exact source `478091e99f4810f20afffde7e73f093311267bf7`
provides the intended synthetic replay building block. It replays sealed
attempted plays through the engine, recomputes every actor row, and requires
byte identity instead of rerunning champion `decide_play` search.

The review branch integrates PR #116 as `de9de899b712ef73dfb717498209dabe06c64685`
and the local hardening child as
`c69f9fd32df9f5c1e7e37a6c11ae97048c813429`. The hardening delta adds the two
additional load-bearing witnesses required before adoption:

1. replay a genuine failed throw where attempted and engine-actual cards
   differ and require byte-identical downstream state; and
2. replay one exact `mc-s0-report-lcb` champion capture under the
   source/runtime mode used by V2, rather than proving only heuristic-policy
   fixtures.

The repaired test file passes 9 tests plus one production-fast-only skip in
pure mode, all 10 in strict compiled mode, and the 16 neighboring
capture/reference tests in strict compiled mode. Review must bind PR #116's
original exact source, its integrated commit, and the hardening child. Their
presence in this branch does not merge PR #116 or authorize replay execution.

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
   train/calibration tensor cache whose actor tensors and privileged labels are
   physically separate, whose control arm is a label-only overlay over the
   exact primary actor tensors, and whose reopener proves split, population,
   order, source-index, runtime, and byte identity before any consumer runs.
4. **Cohort execution:** compare the current two-process layout with
   deterministic per-member workers or an ensemble-batched implementation.
   Preserve all 8+8 members, exact common-epoch selection, and receipt chains;
   no best seed may be retained.
5. **Device choice:** freeze one exact accelerator candidate (`mps` or an
   indexed `cuda:N`) and qualify it against CPU on the realized primary
   schedule. The Mini has an available 10-core M4 GPU, but V1 deliberately
   pinned CPU and cannot be changed in flight. V2 retains the candidate only
   if end-to-end wall time, including input transfer and projection,
   materially improves and the reviewed probability, optimizer, checkpoint,
   memory, and reproducibility contracts still hold. Comparing unrelated
   machines is a separate capacity decision, not part of this device gate.
6. **Native sampler work:** profile only after replay. A native REF-C assignment
   kernel is lower priority if replay reduces the complete reference stage to
   a small fraction of capture/training cost.

The accelerator boundary is one code path, not device-specific trainer forks.
`belief_v2_accelerator.py` moves each immutable batch once and shares it across
all eight independently initialized members; model parameters, optimizer state,
labels, and active masks must reside on the same exact device. Supported device
identities are only `cpu`, `mps`, and an explicit indexed `cuda:N`. Every epoch
receipt hashes parameter names, shapes, dtypes, and values after a synchronous
copy to the canonical CPU float32 checkpoint stream. The published checkpoint
is an ordinary CPU `HistoryOwnershipModelV1`, so evaluation and any later
runtime consumer do not inherit an accelerator dependency.

Device qualification occurs after capture and before either final training
cohort begins. It uses the same digest-selected train batches, model seeds,
optimizer, and batch order for all arms. On a host with a supported accelerator,
CPU and the one frozen candidate get one warmup arm each that is excluded from
evidence, followed by three paired measured arms in alternating order. An
accelerator is retained only if all of the following are true: all arms complete
without fallback; its three same-seed reruns produce one checkpoint digest and
one loss receipt; every paired wall-time reduction is positive; aggregate
measured wall is at least 15% below CPU; batch population, schedule,
active-label count, and authority bytes are exact; and peak resident plus device
memory stays within the frozen cap. Cross-device checkpoint bytes need not equal
CPU bytes because floating-point kernels differ; deterministic repeatability
within the retained device and unchanged held-out calibration gate semantics
are mandatory. If the frozen host exposes no supported MPS or indexed CUDA
device, the only legal candidate is explicit `cpu`; qualification then runs one
CPU warmup plus three measured CPU repeats, requires identical checkpoint/loss/
receipt identities and bounded memory, and freezes CPU without making or
simulating an accelerator comparison. A CPU-only freeze refuses if a supported
accelerator is visible.

The exact bounded work is 32 complete realized training batches chosen by the
smallest SHA-256 ranks of
`belief-v1-v2-device-qualification-v1|full-schedule-sha256|batch-index`, then
executed in original schedule order. The warmup uses the same population. For
one named candidate device, the immutable arm order is CPU warmup, candidate
warmup, CPU→candidate pair 0, candidate→CPU pair 1, and CPU→candidate pair 2.
For an explicit CPU-only host, the immutable arm order is CPU warmup followed
by measured CPU repeats 0, 1, and 2; the wall-reduction statistic is exactly
zero and `accelerator_retained` is false.
The result reopens all eight member checkpoint hashes and loss receipts from
every measured arm; any within-device rerun drift, fallback, missing arm,
population/schedule change, or memory-cap breach refuses rather than selecting
CPU. CPU fallback is permitted only for an honest performance miss.

The execution freeze now binds the exact training-candidate identity, a live
physical-device profile (CPU hardware/host memory or accelerator hardware,
usable memory, backend/runtime, and CUDA index/capability when applicable), the
canonical digest of this qualification protocol, and separate host/device
memory caps. Every stage re-probes that profile before work, so a same-name
device or cloud-host swap cannot inherit the reviewed packet. CPU-only identity
also re-probes the absence of every supported accelerator. This prevents a
post-review choice of whichever device happened to look fastest. The actual
qualification plan
remains post-capture because
its 32 batches are derived from the sealed realized primary schedule; its
result must be published and reopened before final training begins. The same
source-neutral training path is then used for every cohort on the retained
device, which makes accelerator use a scalable V2 property rather than a
machine-local optimization.

The V1 packet ended as an operator-stopped resource failure after its frozen
eight-hour training wall cap was exceeded. It produced no final cohort,
calibration, test, or terminal result. V2 qualification therefore cannot reuse
V1 partial models or claim a V1 learning verdict.

The source audit already identifies two concrete V1 costs to measure. Each
cohort pins Torch to one thread, and `train_cohort_epoch_stream` applies every
batch to all eight models in a serial Python loop. In addition,
`_iter_corpus_batches` reopens corpus bundles and reconstructs actor tensors on
every train and calibration epoch. The first V2 diagnostic ruled out a
whole-population tensor cache on the target host. Four natural rounds averaged
44,381 bytes of per-decision NumPy surfaces and 80,572 bytes of padded Torch
batch payload. Projected to approximately 915,642 training decisions, the old
bridge would retain about 37.9 GiB of examples plus 68.7 GiB of batches—about
106.6 GiB before Python object overhead, on a roughly 30 GiB host. That path is
a pre-run resource blocker, not merely an optimization opportunity.

V2 retains the compact immutable training-input index as the source-of-truth
bridge, but the measured lossless sparse cache makes repeated tensorization no
longer necessary. After capture, the index stage opens train/calibration
targets one complete round or human group at a time and publishes only schedule
rows, content hashes, source locators, common-calibration identity, and realized
cohort schedules. A second deadline-bound stage reopens that index and writes:

- one lossless sparse actor-plus-label cache for each distinct natural
  schedule;
- one label-only hard-geometry control overlay over the exact primary actor
  cache; and
- one shared synthetic-calibration cache used by qualification, every epoch,
  epoch-journal rescoring, calibration selection, and terminal reconstruction.

No test tensor is cached or opened. Every batch file is independently hashed;
the stage manifest binds exact decision population, batch order, input-index
SHA, runtime SHA, storage cap, and all-false authority bytes. A restart reuses
only a completed cache or a batch prefix whose decoded tensors equal the exact
reconstructed source batch; an incomplete atomic write is regenerated, while
any different completed tensor refuses. The outer cache stage preserves its
original monotonic start and may reuse sealed child caches, so a process
interruption does not discard hours of exact preprocessing or reset the wall
cap.

The retained benchmarks are outcome-blind and generated-data-only. On 5,512
decisions, sparse bytes were 72,275,646 versus 447,743,533 for the dense PR
#121 form (6.19x smaller); one cached epoch was 32.36 seconds versus 169.78
seconds streaming (5.246x faster), with identical epoch receipts and final
model hashes. Removing an immediate duplicate source-to-example rederivation
reduced 1,332-decision construction from 21.38 to 9.45 seconds (2.261x) with
the same complete payload SHA. Batched REF-C validation reduced the profiled
generated round from 28.160 to 14.664 seconds (1.920x) while preserving all 68
actor rows, 17,408 worlds, sampler counters, ordered world bytes, and complete
seed/counter/attempt-stream SHA. These are implementation-retention results,
not learning or strength evidence.

The full cache population is projected at roughly 31 GiB, including primary,
label overlay, mixed-human, scale, and shared calibration caches. The fresh
freeze must use an exact host-specific capacity receipt and a conservative
aggregate training-artifact cap; the current review target is 64 GiB, not the
R3 32 GiB cap. Qualification and production training both consume the reviewed
cache path. Streaming remains a test oracle and recovery comparison, not an
automatic runtime fallback that could change the measured path after review.

The remaining performance order is one independent worker per model member,
followed by an ensemble-batched/vmapped implementation only if it preserves
the exact independent AdamW/member semantics and is faster than the simpler
workers. Parallel member workers must reproduce the serial reference's
per-member state and loss bytes before they become the V2 training path.

The V2 CPU path uses exactly four member threads across the eight fixed cohort
members, persisting for each complete training or calibration pass while
retaining one Torch intra-op thread. Each task owns one member's model and
optimizer, every batch is immutable and shared read-only, and results are
reduced in fixed member order. Four workers are the fixed resource-efficiency
knee from the source-head diagnostic: on one four-round, 344-decision epoch,
four workers reduced median wall by 48.8% while increasing process CPU by
79.1%; eight workers reduced wall by 60.6% but increased process CPU by 129.4%.
The diagnostic is not execution evidence or a retention claim. Four workers
also permit the four frozen cohorts to occupy one 16-core host without member
oversubscription; exact execution scheduling remains part of the host freeze.
That scheduling is permitted only when the largest measured per-process CPU
qualification peak multiplied by the exact frozen cohort count fits under the
host-memory cap. The qualification manifest publishes the per-process peak,
process count, and conservative aggregate upper bound before any cohort may
start. Every cohort resource row repeats that calculation from its observed
process peak, and the terminal independently reconstructs it. Accelerator
cohorts have process count one and remain serial; they may not borrow the CPU
cohort concurrency rule.
The qualification keeps all 32 selected Torch batches resident through every
arm, whereas production training retains only the current streamed batch. Its
selection is not hash-only: it must include the maximum decision-count batch
and the minimum and maximum active-labels-per-decision batches, covering the
late/long-history and early/high-unknown tensor-shape extremes available from
the compact schedule. The remaining slots retain the source-neutral hash
selection. Any change to these anchors changes the qualification protocol hash
and requires a fresh freeze.
The MPS and CUDA paths remain serial because device kernels already share one
accelerator and concurrent Python submission is not part of their qualification
estimand. Multi-batch tests require the CPU path to reproduce the serial V1
reference's exact epoch receipts, calibration losses, and portable checkpoint
hashes. The device-qualification protocol hash binds both worker counts;
changing either topology requires a new freeze.

The source-neutral mechanics are now implemented in
`belief_v2_cohort_training.py`. They consume only independently realized
train schedules plus the shared synthetic calibration schedule, train all
eight fixed initializations on the qualification-selected device, preserve the
full epoch receipt chain, apply the common-epoch rule, and export ordinary CPU
checkpoint bundles. The V2-native hard-geometry label control changes only
privileged labels and publishes its exact changed-cell dose; public tensors and
optimizer work remain identical. The independent reopener reconstructs every
batch identity, initial and cross-epoch model-state link, selection decision,
checkpoint receipt, and checkpoint byte stream. No human calibration or test
row is accepted by this training boundary.

Every long, capped synthetic capture, synthetic reference, training-input
index, tensor-cache, device-qualification, and cohort-training loop has an
in-loop monotonic deadline rather than only a post-hoc timer. The immutable
freeze binds a
measured p95 next-unit wall
estimate for one capture round, one reference job, and one complete training
epoch, plus one safety reserve. Capture and reference check before and after
each unit; the input index checks around every source round/group and before
serialization; device qualification checks before and after each arm; the
cohort trainer checks before and after every epoch and before checkpoint
construction. No new unit may start unless the measured estimate plus reserve
fits before the hard wall cap.

Deadline semantics now distinguish absence of evidence from useful bounded
training. Expiry before the first complete epoch publishes one canonical
`deadline-refusal.json`, cannot seal, and blocks every later stage. After one or
more complete epochs, every epoch's models, optimizer states, receipts,
calibration losses, and selected-common-epoch state have already been appended
to a mandatory-latest journal. Expiry then seals the best common epoch with
`truncated_by_deadline: true`; it cannot also claim patience convergence, cannot
select an earlier operator-chosen checkpoint, and remains eligible for the
ordinary calibration/test gates. The final training manifest binds the exact
deadline refusal, so the global stage gate allows only that fully sealed narrow
case. Every reopener re-scores every journal epoch from the common calibration
cache before trusting it. A process restart must resume the highest contiguous
epoch and original monotonic wall; it cannot restart from scratch, reset the
deadline, or choose a model. If publication of the next journal entry itself
was interrupted, the regenerated state/curve bytes must equal every preserved
complete byte or exact prefix before that same next epoch can finish publishing;
unknown, reordered, or mismatched partial content refuses. Post-hoc resource
reconstruction remains an independent terminal check rather than the deadline
mechanism.

Performance changes must be bit-identical at the artifact or probability
contract they claim to preserve. A faster implementation never inherits
scientific or strength authority.

Every long worker command also emits canonical `BELIEF_V2_PROGRESS` JSON lines
to stderr. Capture, REF-C, historical-human replay, compact-index construction,
tensor-cache construction, device qualification, each cohort's training
batches and epochs, calibration, and the one-shot terminal report exact
completed and total units, integer percent in basis points, monotonic elapsed
time, and a mechanical remaining-time estimate.
The final successful update is exactly 100%. Parallel workers keep separate
stage/worker identities, so fleet progress can be aggregated without opening
their outputs.

An H0 source group with zero eligible human decisions is still a legitimate
frozen group, not a dropped input. It reports one group-stage progress unit,
publishes/reopens empty actor/reference populations with zero artifact bytes,
and contributes no scoring rows. The reviewed frozen 30-group H0 population
has seven such groups; their manifests remain part of split and source closure.

Progress is outcome-blind operational telemetry only. It is never written
under the evidence root, never changes stdout or any manifest/result/checkpoint
bytes, and carries no loss, score, candidate-selection, test-result, or
terminal-route field. It cannot authorize a retry, result opening, strength
claim, promotion, or deployment. Tests bind both the fail-closed monotonic
reporter and callbacks from real controller paths; a helper-only witness is
insufficient.

The supervisor task plan is source-bound in
`belief_v2_supervisor_plan.py`, and the one-shot executor is
`scripts/belief_v2_supervisor.py`. The source fixes ten ordered stages; the H0
split receipt fixes the exact task count. The repaired real-population preview
has 85 tasks: 16 synthetic capture, 30 human capture, one input index, one
tensor cache, one device qualification, 16 synthetic plus 13 human references,
four cohort trainings, one calibration, one test opening, and one terminal
verification. Human references are exactly two calibration replicates for
each of four calibration groups plus one test-primary replicate for each of
five test groups; train groups receive none. The old
30-by-three Cartesian matrix, a missing cache stage, any dropped/extra task,
or a stage/concurrency reorder refuses before the ops start token is written.

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

The final cap receipt also binds exact-source/runtime deadline measurements.
Capture uses all 416 raw round-wall samples from the reviewed capacity
preflight. Reference uses 32 rank-diverse, out-of-population complete REF-C
rounds under the same 16-worker topology. Training uses two complete passes
over the same 32 one-round batches after one discarded warmup. Each pass
freshly reconstructs examples and collates its batches, then includes the
unchanged eight-member optimizer work and calibration evaluation;
its wall is projected to the exact 10,647 train-round population with one
round per batch and a frozen 1.25 margin. That is deliberately conservative:
the production scheduler may pack multiple whole round groups into each
256-decision batch, while the pre-freeze probe never does. The larger of the
two projected epoch estimates is the p95 next-epoch value, and the single
safety reserve is `max(60 seconds, 5% of that value)`.

`belief_v2_deadline_estimate.py` and
`scripts/belief_v2_deadline_preflight.py` are the only producer/reopener for
this receipt. They publish every raw wall sample, the exact all-rank schedule,
REF-C manifest-population hashes, deterministic training receipt hashes, and
the mechanical projection. Captured rows, sampled worlds, model states, and
losses are discarded before return. The cap fields must equal the reopened
receipt values byte-for-byte. A mutable estimate, an operator guess, a
semantically non-repeatable training probe, or an estimate plus reserve that
cannot fit beneath its stage wall cap refuses the freeze.

The execution-freeze child implements this in `belief_v2_preflight.py` and
`scripts/belief_v2_preflight.py`. Its exact schedule is two rounds at every
rank in every one of 16 lanes (416 rounds), SHA-256
`ffbd1a5cf76886d11fc27c511e8899348342943f29866c2c349c650cf606e698`.
It requires a clean source checkout, isolated `-P -B` Python, strict voids,
the compiled engine, a content-bound source/Python/native runtime, and a real
common overlap among all 16 lanes. Captured rows are discarded. The result
independently reconstructs the population and all resource summaries and
keeps production capture, training, test, and strength authority false.

The first authorized planning preflight completed on Strength Cloud at source
`22c8568dd64d11f873e1397569b5ee1efb473b0a`; result SHA-256
`3b40250e25acccf7ed9f9c8becf763956c434fe0bae2098336b6dd2bae16290c`.
All 416 rounds completed under a real 16-lane overlap, exit status was zero,
and stderr was empty. Mean/p95 round wall were 12.709/16.609 seconds;
mean/p95 artifact size 591,916/763,734 bytes; aggregate CPU was 5,285.7
seconds; 16-lane parallel wall was 342.8 seconds; maximum recorded lane RSS
was 398,468 KiB; and three rounds exercised engine-adjusted actions. A direct
mean projection for 13,312 rounds is 47.0 capture core-hours, 2.94 wall hours
per lane, and 7.34 GiB. A conservative p95 projection is 3.84 wall hours per
lane and 9.47 GiB. These measurements supersede the earlier V1-derived 26.2
core-hour/6.7-GiB planning estimate and must drive the final automatic caps.
That V1 receipt remains planning evidence only. The final source now requires a
fresh V2 preflight receipt whose runtime row also binds hostname, machine,
physical memory, boot identity, Python/native bytes, and all 16 CPUs to the
same live runtime used by the deadline probe and freeze builder. A receipt from
another host or boot cannot be reused even when its source commit matches.

The capture CPU cap is not operator-selected after measurement. It is exactly
the ceiling, in whole core-hours, of the capacity preflight's measured
aggregate CPU extrapolated from its complete round population to all 13,312
production rounds, multiplied by the fixed 5/4 margin. The freeze builder
recomputes that value and refuses any lower or higher supplied cap. Every
worker stage enters through `_load_root`, whose live-execution gate directly
re-probes the current host boot identity and then rebuilds the runtime profile
before any resume journal is trusted; it does not compare two copies of the
freeze.

The immutable 13,312-coordinate production schedule is memoized only after
its first complete derivation. This preserves its canonical bytes while
reducing later coordinate validation from about 48 milliseconds to
microseconds; a run must not repeatedly regenerate the full schedule for each
captured round.

After synthetic and human capture seal, the dependency graph is:

```text
rank/human capture --> training index --> tensor cache --> device qualification
       |                                                        |
       +--> synthetic + human REF-C replay -----------+         |
                                                       v         v
                                                four cohort trainings
                                                       |
                                                       v
                                                  calibration
```

REF-C is not a training dependency. It may overlap training only when the
frozen host topology proves that the combined worker population fits without
CPU or memory oversubscription. R4's reviewed CPU topology is four concurrent
cohorts times four member workers, which already occupies all 16 logical CPUs,
so its supervisor runs the reference population before cohort training rather
than silently changing the measured trainer. Replay makes that sequential
stage materially cheaper. No cloud should be powered merely to hold an idle
reviewed process.

The first V2 execution freeze remains single-host: every stage re-authenticates
one exact runtime/native/boot profile. Concurrency above therefore means
parallel processes on that host. Running REF-C on Cloud while training on
Mini would require a separately reviewed, hash-closed stage export/import and
role-specific runtime profiles; that distributed boundary is not implemented
or silently authorized by this design. The device-neutral code and portable
CPU checkpoint format preserve that future path without weakening the first
packet.

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

All model selection occurs before the test split opens. On calibration, the
human-mixture model replaces the synthetic primary only when its complete-human-
round bootstrap lower bound versus primary is positive and its mixed-minus-
primary regression remains strictly below +0.5% at both the synthetic aggregate
and every powered rank under the preregistered 13-rank max-statistic upper
bound. Otherwise primary remains selected. Each data-scale arm is compared
with primary on the same synthetic calibration rounds and reports a positive
data-scaling signal only when the complete-round bootstrap lower bound for
`scale Brier - primary Brier` is positive. Scale results never select the
test candidate.

The single test opening scores all frozen cohorts for reproducibility, but only
the calibration-selected candidate can satisfy the primary gate. It must beat
REF-C by at least 0.5% relative Brier, have a strictly positive complete-round
bootstrap lower bound, improve in at least six of eight initialization members,
avoid a log-loss sign reversal, and remain below the +0.5% simultaneous rank
regression boundary. The label-permutation control's lower bound versus REF-C
must not be positive. Human test rows publish exact round/decision n, primary
and mixed confidence intervals, and their paired difference as descriptive
policy-domain transfer only.

Terminal routing is closed: integrity/mechanics/resource failure routes to
`REFUSE_INCOMPLETE_OR_INTEGRITY`; an unexpectedly learned label control routes
to `REFUSE_NEGATIVE_CONTROL`; a passing selected candidate routes only to
`PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW`; a failed primary with a
preregistered positive scale and/or simultaneous rank signal routes to
`SELECT_NONE_WITH_PREREGISTERED_REENTRY` with the exact signal names; otherwise
it routes to `SELECT_NONE_NO_CALIBRATION_LIFT`. No V2 route authorizes a sampler,
gameplay screen, strength claim, promotion, or deployment.

`belief_v2_result.py` now implements that precedence as a pure terminal
boundary. Its resource receipt carries measured expected-versus-reopened
capture, reference, cohort, checkpoint, synthetic-test, and human-test
populations; stage/mechanics failures; retries, drops, and test-open count;
parallel wall/compute/artifact totals; accelerator result identity; and peak
host/device memory. Caps and population totals are recomputed against the
execution freeze. The terminal binds all input artifact digests and refuses
selection drift, coordinated result rewrites, or a calibration-selected cohort
that differs between synthetic and human reports. Re-entry signals are emitted
only on a failed primary and only for preregistered positive data-scale or
simultaneous rank evidence.

Rank attribution comes only from the balanced synthetic rank contrasts.
Human-versus-champion transfer jointly changes policy, rank mix, and logging
surface, so a human transfer failure or success may never be reported or
spent as evidence for a rank mechanism. It remains a policy-domain transfer
result unless a separately balanced synthetic rank contrast establishes the
rank effect.

If the synthetic model fails again with no rank-specific or data-scaling
signal, this exact model/target family closes; V2 does not escalate to a larger
model by default. If it passes, B3 must still prove complete legal world
sampling, preservation of the calibrated marginals, joint-event calibration,
fixed-world value quality, and natural final-decision flip dose before any
same-work search screen.

## Consolidated review path

To avoid repeated source/design/admission round trips while still binding the
private population and host-specific cap evidence:

1. one consolidated exact-head source/design review binds the rank factory,
   PR #116 successor, H0 identity/privacy boundary, model arms, exact synthetic
   population, profiling protocol, sparse-cache/source-index separation,
   exact cache and epoch recovery, graceful deadline truncation,
   streaming-oracle parity, CPU-member topology, the exact ten-stage supervisor,
   outcome-blind progress telemetry, metrics, and automatic routing. The
   reviewer returns one PASS or one HOLD containing every blocker found in
   that pass; these are not split into subsystem review requests. It may
   authorize only the real score-free H0 inventory and out-of-population
   capacity/profile probes;
2. one exact execution-freeze review binds the resulting private source-group
   population, human-mixture fraction, host/runtime/native identities, caps,
   V1 routing receipt, and complete immutable packet. Only that PASS may
   authorize bounded capture, the parallel training/reference DAG, and one
   test opening; and
3. one terminal review independently reopens the result and routes B3 or
   closure.

No intermediate capacity, corpus, model, or reference milestone receives a
separate review. A new review is required only when code, estimand, population,
authority, or sealed-resource boundary changes.

## Implemented source boundary and remaining freeze inputs

The local execution-source candidate now implements the complete bounded
offline path:

- the reviewed hardened PR #116 transcript replay, balanced all-rank synthetic
  schedule, real H0 replay, common attempted-channel mask, and tensor-level
  absence witnesses;
- exact synthetic and whole-session human capture/reference controllers,
  source-neutral work realization, all-human-once replacement, the 50% data-
  scale arm, and the 0.5% simultaneous rank-regression rule;
- one shared CPU/MPS/CUDA training implementation, an exact live accelerator
  hardware profile, a realized-schedule device qualification gate, portable
  CPU checkpoints, dual-domain calibration selection, one-shot terminal
  publication, and independent reopeners; and
- one consolidated worker, the split-derived closed supervisor, plus a
  receipt-driven
  `freeze-design` command. The
  command derives H0 counts and hashes, V1 route, preflight/runtime identities,
  exact source manifest, a compact independently reopenable historical/V2 seed
  registry, candidate-device protocol, cohorts, and authority bytes rather
  than asking an operator to hand-build the packet.

The following run-specific inputs still gate an exact freeze:

1. one authenticated V1 routing receipt. A naturally completed V1 PASS routes
   directly; a V1 SELECT_NONE requires the already named multi-rank/human-domain
   re-entry rationale. The spent V1 resource failure has exactly one narrower
   route, `RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW`: the receipt must
   prove the frozen wall cap was exceeded, both workers were stopped under the
   reviewed termination marker, only partial training slots exist, calibration
   and test were never opened, no terminal/model result exists, the admission
   is spent with no retry, and the in-loop defect is repaired in the new exact
   V2 head. This route is not a V1 PASS or SELECT_NONE, cannot use V1 partial
   models, and grants no execution authority by itself. Every other V1
   `REFUSE_*` remains blocking;
2. one consolidated external source/design PASS on the final V2 execution
   head, including the worker, freeze builder, GPU qualification, calibration,
   terminal, and adversarial tests;
3. a fresh complete seed scan/registry and fresh H0 inventory/split generated
   from that exact execution head;
4. the final host-specific runtime/native/boot identity, named training
   candidate (explicit CPU only when no supported accelerator exists), measured
   next-unit/epoch deadline receipt, and reviewed resource
   caps. The receipt must include the sparse-cache bytes-per-decision projection,
   exact free disk, the complete primary/control-overlay/human/scale/calibration
   population estimate, and a training-artifact cap with conservative margin
   (64 GiB for the current measured projection). `freeze-design` binds these
   together with the existing multi-rank preflight receipt; and
5. one external exact-freeze PASS on the canonical immutable JSON.

The actual CPU-versus-candidate qualification result is deliberately not a
freeze input: its 32 batches do not exist until capture seals the realized
primary schedule. It is produced once after capture under the same admission,
then either selects the accelerator on the exact performance/integrity gate or
selects CPU on an honest performance miss. REF-C is independent and may run in
parallel with qualification and final training. No intermediate stage needs a
new review.

The private H0 source and score-free diagnostic population exist; no repaired
exact-head H0 receipt, freeze, or execution admission exists yet. None
authorizes population capture or training. Until the remaining inputs and one
exact execution-freeze PASS exist, V2 remains non-executable.
