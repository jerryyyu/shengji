# BELIEF-V1 B1/B2: opened-development corpus and calibration design

Status: reviewed design merged on canonical main. The governing specification
and B0 contracts from PRs #110–#112 are merged. The complete offline
implementation passed exact external review at PR #113 head
`3ee0eb8754b47743c52db0d7387372b6863913ae` and merged byte-preservingly
through canonical main `959c05de3b1ac379a6f9595b516608427486243d`.
Fresh Mini design `a8c5e05f…1fd53` now binds that source and the live
runtime/native/boot identity. Exact review commit `209407f` authorized this
offline sequence, which initialized once and began capture on 2026-08-15. No
terminal B2 result exists.

This document authorizes nothing. In particular it does not authorize corpus
generation, training, cloud use, sampler changes, gameplay evidence, strength
claims, promotion, or deployment.

## Decision this design must unlock

The offline program answers one question:

> Can a public-history ownership model predict the hidden allocation of cards
> more accurately and more honestly calibrated than the current constraint-
> consistent sampler, without leaking hidden state or violating hard engine
> constraints?

It does **not** ask whether the bot is stronger, and this population is not
sized to prove any named rare behavioral inference. A pass establishes only
aggregate ownership calibration and permits a request to review
`BeliefSamplerV1`; a failure closes this exact encoder/model/data recipe before
an online screen.

## Fixed scope

- Surface: natural ordinary-play decisions only, including both leads and
  follows. Bury, declaration choice, feed-gate policy, rollout continuation,
  search allocation, and action-value heads are out of scope.
- Acting policy: exact production `mc-s0-report-lcb` in all four seats.
- Input: exact `ActorObservationV1` with a complete `PublicTranscriptV1`.
- Label: separately sealed `BeliefTargetsV1`; privileged bytes never enter an
  input batch, model package, sampler API, or inference log.
- Learned output: hidden card-code ownership over the other three relative
  seats and the hidden-kitty receiver where applicable.
- First use: none. This design ends at offline calibration and usefulness
  evidence.

## Fresh population

The proposed opened-development population contains 4,096 complete rounds.
Its seed namespace is derived, rather than hand-picked:

```text
seed_material =
  belief-v1-b2-open-dev-corpus|
  b8c2a4c25e918278c72facc472c6736428e65af3|
  7ebfcf7959f5254fee3b3dda1fc2fd83600540e9
sha256(seed_material) =
  d4b635bd6bc44b5e25b23881944fba68caef04c0c74b4cbae076ded191932ac6
seed_start = first_64_bits_big_endian & (2**63 - 1), rounded down to 4096
           = 6104125432620400640
seed_end   = 6104125432620404735
```

The exact B1 split function gives:

| split | complete rounds |
|---|---:|
| train | 3,279 |
| calibration | 407 |
| test | 410 |

Each of 16 deterministic capture lanes receives exactly 256 round seeds. No
decision, replay prefix, or target from one round may cross splits. No
state-level resampling changes the primary natural-frequency metrics.

Before freeze, a source-independent seed registry scan must confirm that this
interval does not overlap any training, calibration, test, or strength
population known to the repository and canonical run manifests. A collision
changes the whole interval; individual seeds are never substituted.

## Capture contract and preliminary economics

Every round is driven by a source-pinned capture wrapper that owns
`PublicTranscriptV1` from the first deal event through round end. The sealed
capture record retains every attempted and engine-actual play for offline
integrity. An actor row exposes a failed-throw bit and the forced component to
every seat, but exposes returned attempted cards only to the seat that made the
attempt, matching the engine's broadcast surface. It emits paired actor and
target rows before each play.

A local compiled ARM preflight on one deterministic champion round at exact PR
#111 head measured:

- 76 decisions;
- 7,096.36 ms total round wall time;
- 72.864 ms total row capture, sealing, strict reopen, and validation;
- 0.959 ms capture work per decision, or 1.027% of measured wall;
- mean actor row 5,775.7 bytes and target row 1,306.6 bytes.

These figures are planning inputs, not a host qualification. The consolidated
execution design must bind the concrete host and refuse fewer than 10 logical
CPUs or 16 GiB of physical memory before the one reviewed pipeline starts.
The 16 deterministic lanes are work partitions and may be scheduled across
those 10 cores. Initial hard caps are:

- 16 capture core-hours;
- 2 capture wall-hours on a 16-lane host;
- 4 GiB combined canonical rows, manifests, and logs;
- zero retries, dropped rounds, incomplete transcripts, split substitutions,
  or short rows.

The consolidated execution design binds the concrete host, boot, Python,
native extension and numerical mode before any stage starts.  This opened-
development pipeline deliberately has no separate capacity packet or
preflight-review hop: capture is the bounded workload, its immutable lane
receipts account exact wall/CPU/bytes, and the terminal reopener enforces the
aggregate caps below.  A lane or aggregate cap failure terminates this exact
recipe with no retry, resizing, or partial-corpus use.

## Reference distributions

Two controls are frozen.

### `REF-C`: sound constraint proposal using the current assignment kernel

For each held-out actor row, draw a fixed number of complete worlds with the
current sampler's randomized backtracking/split assignment kernel plus the
reviewed BELIEF-V1 hard-constraint adapter. A declaration by a non-banker
remains a hand pin. For a non-banker observer, each still-unplayed copy shown
by a banker-declarer is assigned without replacement only among the banker
hand and hidden burial; unrelated hands are ineligible. This adapter does not
change the production `Memory` or the acting `mc-s0-report-lcb` policy used to
generate the population. Convert those worlds into
empirical card-receiver count probabilities and derived suit/shape/point
marginals. The draw count, RNG stream, accepted/rejected work, and Monte Carlo
uncertainty are recorded. No learned features are present. The randomized
backtracking/split implementation is the exact baseline; this design does not
claim it is mathematically uniform over accepted worlds.

### `REF-H`: current hand-coded context

Use the same REF-C world weights while exposing the exact `Memory` and
`PointContext` facts available to current decision code when evaluating
derived action-context quantities. REF-H does not invent a second hidden-
ownership prior. Therefore REF-C and REF-H are expected to tie on ownership
proper scores and may differ only on downstream derived-context comparisons.

Draw exactly 256 accepted reference worlds per held-out decision. Receiver-
count Brier score is the primary metric. Secondary log loss uses a frozen
Jeffreys pseudocount of `0.5` in each `0/1/2` count cell so a finite reference
sample cannot create an accidental infinite loss. Two independent 256-world
REF-C replicates on the calibration split must disagree by less than one
quarter of the 0.5%-relative Brier improvement floor below; otherwise the
reference draw count returns for redesign before the test split opens.

REF-C's empirical multinomial Brier is not compared raw with an unsampled
candidate. For every receiver/card count row, subtract the unbiased finite-
sample variance estimate
`sum_k p_hat_k * (1 - p_hat_k) / (256 - 1)` from REF-C before C1, C2, N2 or
U1 comparisons. The implementation stores raw REF-C Brier, the exact integer
bias term and the corrected value separately. Candidate scores remain
unchanged. This prevents a candidate that merely reproduces the
constraint-consistent marginal distribution from banking the systematic
`1/N` error of the 256-world baseline. Removing the correction must make the
empirical-reference-clone regression fail.

Reference RNG seeds are `sha256(protocol-schema|ref-c|replicate|decision_key)`
truncated to a nonnegative 63-bit integer. The exact replicate labels are
`calibration-replicate-0`, `calibration-replicate-1`, and `test-primary`.
“One quarter of the floor” means a strict relative mean-Brier disagreement
below `0.00125`, represented as `1,250,000` parts per billion; it does not mean
a 25% absolute disagreement.

## Model `HistoryOwnershipV1`

The first model is deliberately small and single-purpose.

### Inputs

- one token per public declaration and public play event, preserving relative
  seat, trick position, the public failed-throw signal, actor-visible attempted
  cards, and engine-actual cards;
- per-card-code fact features from the actor hand, actor-known burial, played
  counts, played-by-seat counts, unseen counts, declaration hand pins,
  banker-hand/hidden-kitty eligibility groups, and effective suit/rank under
  the current ordering;
- global banker/role/trump/points/hand-size/trick context; and
- exact information-class masks distinguishing observed, actor-private, and
  logically deduced fields.

No target-derived statistic, target file name, true hidden card count, or
privileged corpus manifest is an input. The receiver set and remaining public
hand/kitty sizes come from the actor contract and are not privileged.

### Encoder and output

- a two-layer GRU event encoder with hidden width 128;
- a shared card-code embedding joined with the event summary and exact fact
  features;
- receiver logits for each unknown card code; and
- a deterministic constrained projection enforcing zero/one hard masks, card
  multiplicity, receiver hand size, and hidden-kitty size.

Published probabilities are integer parts per billion with scale
`1_000_000_000`. Projection resolves rounding residuals by canonical card-code
then receiver order, so expected card and receiver totals remain exact at that
scale and the same actor bytes produce bit-identical probability bytes.

The learned layer represents soft receiver preferences, not every joint card
correlation. Complete-world sampling and derived marginals remain separate B3
work. If projected card marginals fail receiver-count or linear-expectation
calibration, this factorization closes; joint pair/tractor/top-rank event
calibration is a B3 gate, and an autoregressive successor requires a new
design.

The primary candidate is the ordered equal-weight ensemble of all eight member
predictions. Integer member count probabilities are summed with weight one and
passed once more through the exact constrained projection. This restores any
parts-per-billion card or receiver margin lost by independently rounded member
outputs. The ordered eight checkpoint hashes, fixed initialization seeds, and
final-projection flag define the ensemble identity; no member is selected.

### Training cohort

Eight fixed initialization seeds are trained as one cohort:

```text
495023836, 847673502, 1041799603, 588875658,
442958256, 517235703, 1114290105, 823748771
```

No seed is selected or discarded by calibration or test performance. The
candidate prediction is the equal-weight probability average of all eight
models; all eight hashes remain in the runtime-research package. The
initial training recipe is AdamW, learning rate `3e-4`, weight decay `0.01`,
batch size 256 complete-round-grouped decisions, gradient-norm cap `1.0`, and
at most 30 epochs. Early stopping uses cohort-mean calibration ownership loss,
patience three epochs, and minimum improvement `1e-4`; all eight seeds stop at
the same selected epoch. The test split is opened exactly once after candidate
and negative-control cohorts are frozen.

The candidate cohort and N2 permuted-label cohort each select one common
epoch across their own eight members. They do not share an epoch across the
two different training objectives. Both complete cohort curves and both
selected epochs are frozen before the test split opens; neither choice may
use test performance.

A complete round is never split across optimizer batches. For epoch `e`, train
rounds are ordered by `sha256(protocol_sha256|epoch-e|round_seed)` and packed in
that order up to 256 decisions. Early stopping operates on integer cohort-mean
calibration loss in nanonats: an improvement is load-bearing only at
`100,000` nanonats or more; three subsequent non-improving epochs stop the
cohort and every member uses the same selected checkpoint epoch.
Every member receipt independently binds the sorted exact decision-key
population and the ordered batch/decision-key schedule for that epoch. All
eight members must agree; the population digest must remain constant across
epochs and the epoch-bound schedule digest must change with the frozen order.

Training hard caps are 32 CPU/GPU device-hours total for the eight candidate
and eight permuted-label control models, 8 wall-hours, and 16 GiB of
checkpoints/logs. Any out-of-memory, nonfinite loss, missing seed, or source
drift invalidates the cohort; it is not retried under the same recipe. The
concrete implementation review pins framework, numerical mode, device class,
and deterministic-algorithm settings before any training.

REF-C generation has its own explicit cap: 64 CPU-hours, 8 wall-hours, and
4 GiB of immutable reference artifacts across both calibration replicates and
the test-primary replicate, with zero retries. Reference worlds are stored as
two-bit hidden-receiver count cells plus one ordered length-delimited canonical
world-stream digest per decision. Terminal reopening reconstructs and validates
every typed world; compact encoding does not weaken the reference contract.

## Exact mechanics gates

Every checkpoint and every test row must satisfy:

- **E1 conservation:** unknown card expectation and receiver expected sizes
  close to the exact integer totals within the frozen integer quantization;
  projected complete fixtures conserve exactly;
- **E2 hard facts:** zero probability for played, actor-known, and proven-void
  receiver/card combinations; probability one for forced ownership; completed
  tricks independently reconstruct winner and points, each winner leads the
  next trick, and the public attacker-point tally equals attacker-won history;
- **E3 public twins:** hidden-world counterfactual twins produce bit-identical
  actor bytes and model probability bytes;
- **E4 rotation:** absolute seat relabeling preserves the actor-relative output;
- **E5 isolation:** no target bytes or target-derived metadata enter inference;
  and
- zero duplicate decisions, cross-split rounds, incomplete transcripts,
  noncanonical rows, unknown cards, or unbound source/model identities.

Any mechanics failure terminates the recipe regardless of average loss.
The terminal mechanics artifact contains checked-population and
failure/mismatch counts, not caller-supplied pass booleans. Every probability
row is passed through the real ownership validator's non-raising mechanics
audit; conservation and hard-fact mismatches are counted from that audit, and
the ordinary raising validator consumes the same checks. E3/E4/E5 use
candidate predictions on C4 public-twin and absolute-seat-rotation corpus
rows. Cross-split counts are reconstructed from the actual train/calibration
round seeds logged after bundle opening, not from the split function alone.

## Primary calibration gates

The round is the bootstrap and uncertainty unit. All eight training seeds are
reported; no best-seed metric exists.

1. **C1 proper-score lift:** primary improvement is paired per-round hidden-
   ownership count-Brier `bias-corrected REF-C - candidate`. The raw REF-C
   mean and mean correction are reported alongside the corrected statistic.
   The one-sided 95% lower bound
   over untouched test rounds must be strictly positive and the mean reduction
   must be at least 0.5% of REF-C mean Brier. At least six of eight individual
   seeds must have positive mean improvement. Smoothed log-loss improvement is
   confirmatory and its mean improvement must be nonnegative. The lower bound
   is the fifth percentile of exactly 20,000 paired complete-round bootstrap
   resamples, using deterministic seed `4654505738542866658`. An integrity
   failure or missing round refuses the result; it is never dropped from the
   bootstrap population.
2. **C2 behavioral strata (descriptive in this B2):** report declined-feed,
   forced-trump/joker, and unforced-point-play strata. A future behavioral
   claim requires at least 500 test receiver-decision exposures in a named
   stratum and a positive lower bound there. The existing champion census makes
   declined-feed essentially absent, and this 4,096-round population was not
   sized from all three stratum prevalences. Sparse named strata and the pooled
   set are therefore reported without controlling the B2 terminal decision.
   No underpowered or pooled result may be cited as evidence that the model
   learned the named tactical inference. A separately sized natural or mixed-
   policy corpus is required before such a claim becomes binding.

Behavioral-stratum membership has two separate forms. The actor-visible form
uses public sequence patterns only. A target-side audit form may use the true
historical hand to determine whether the observed player actually had a feed,
higher-pair, nonpoint discard, or trump alternative. That privileged audit
label is sealed with targets and is forbidden from actor rows and inference.
This separation prevents “declined an available action” from leaking that the
action really was available.

Each public signal is active only for the natural downstream decision window
before that source seat acts again. Public pattern rows never contain the
source actor's hand or the private alternative audit. The audit stream alone
records whether a point/nonpoint alternative existed and, for the trump-pair
signal, the source's pre-play trump length and pair count.
3. **C3 reliability:** for each emitted receiver count class `0/1/2`, report
   a separate fixed 10-bin ECE, Brier component, and reliability slope—never a
   pooled three-class curve—overall and by frozen public role,
   phase, declaration, and hidden-kitty strata when at least 1,000 probability
   cells are present. Also report calibration/error for linear expectations
   derivable from the ownership marginals: suit/trump length, point count, and
   pair count. Void, tractor-length, boss/top-rank, and multi-card action-event
   distributions are joint-posterior outputs and are therefore deferred to B3
   complete-world sampling; B2 must not fabricate them with an unreviewed
   independence assumption.
4. **C4 exact synthetic posterior shim:** a synthetic posterior fixture using
   real full-domain actor rows exercises the same encoder, count head, optimizer
   step, and exact projection against two fully enumerated compatible targets.
   It does not certify the full capture contract or a reduced-deck game. On an
   untouched synthetic fold,
   maximum event-probability error and total-variation distance must remain
   within preregistered tolerances. This validates the learning pipeline; its
   weights are never mixed with the full-deck candidate.

   The frozen C4 instance contains four distinct public contexts. Each context
   is represented by two real corpus rows with byte-identical actor
   observations and different privileged hidden allocations. The two worlds
   have equal prior mass; the observed public action has integer likelihood
   weights `3:1`, yielding an exact posterior of `3/4:1/4`. Training uses 4,096
   rows (1,024 per context), 16 rows per batch, the same GRU/count head, AdamW
   step, and exact projection, for 30 epochs from seed `495023836`. The
   untouched fold re-enumerates every receiver/card/count event. Both maximum
   event-probability error and maximum categorical-row total variation must be
   at most `20,000,000` ppb (2%). A uniform/no-learning control must fail. C4
   weights are diagnostic only and never enter the candidate cohort.

No metric may be repaired after the test fold opens.

## Negative controls

- **N1 history ablation (descriptive in this B2):** at inference only,
  deterministically permute the
  complete public event rows within each decision while leaving every event
  row, non-event actor fact, model weight, and true label unchanged.
  For any powered positive behavioral stratum, report the retained fraction;
  do not interpret a point ratio from an underpowered stratum as a mandatory
  closure. No second history-ablation cohort is trained.
- **N2 hard-geometry label permutation:** train the same eight-seed cohort on
  privileged count-label rows cyclically permuted between card codes only
  inside an identical actor-derived min/max receiver geometry and unseen-copy
  class. This preserves every card total, receiver size, void/declaration
  bound, split, and decision while breaking the card-to-hidden-owner label
  association. Its one-sided lower bound versus REF-C on the original test
  targets must not be positive. Literal cross-round target-row permutation is
  forbidden because another row generally cannot satisfy the current actor's
  cards, hand sizes, voids, or declaration pins.
- **N3 policy shift:** report the frozen champion-trained model separately on
  available human and named-bot opened-development corpora. This is descriptive
  transfer evidence only; no corpus is silently added to training.

An unexpectedly positive N2 lower bound closes the recipe as leaked or
nonbehavioral. N1 cannot close this aggregate-calibration B2 because the
natural population was not sized to make its behavioral strata evaluable.

## Offline usefulness gates

- **U1 true-world likelihood:** this is exactly the C1 per-cell held-out proper
  score, not an independent joint-world test or second line of evidence.
- **U2 fixed-world value quality:** deferred to B3 because it requires a frozen
  sampleable joint posterior. Before any online screen, B3 must show lower
  fixed-world rollout value error or variance at unchanged continuation and
  must separately rule out bias.

B2 cannot use calibration success to skip U2.

## Artifacts

The offline run must publish immutable, separately reviewable artifacts:

- actor-corpus manifest and ordered actor row hashes;
- privileged-target manifest and ordered target row hashes;
- split and round-seed manifest;
- capture source/runtime/work/cost receipt;
- exact reference-world manifest and sampler counters;
- eight candidate and eight permuted-label checkpoints plus cohort manifests;
- separate candidate and permuted-label train/calibration curves and their
  separately selected common cohort epochs, with no test payload;
- one terminal test report with E/C/N metrics, the explicit U1=C1 alias, and
  descriptive per-stratum counts; and
- a no-authority result envelope.

The corpus population envelope is canonical and binds all 4,096 rounds in
ascending seed order. Each round row records its deterministic lane and policy
seeds, split, decision count, capture-manifest and transcript hashes, separate
length-delimited actor- and privileged-target-stream hashes, and a rederived
round-bundle hash. The envelope recomputes exact `3,279/407/410` split counts,
`256` rounds in every capture lane, the total decision count, protocol hash,
and all-false execution/runtime authority. Terminal review must reopen the
separated bytes and reproduce the entire envelope; a valid-looking population
JSON alone is not evidence.

Runtime packages may contain actor schema, model weights, and projection code.
They may not contain target rows, target manifests, true hidden allocations, or
test labels.

## Terminal decisions

The result is exactly one of:

- `PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW` — mechanics, completeness, C1,
  C3 reporting, N2, and C4 pass; C2 support is reported separately;
- `SELECT_NONE_NO_CALIBRATION_LIFT` — mechanics pass but the proper-score gate
  fails;
- `SELECT_NONE_BEHAVIORAL_CLAIM_UNSUPPORTED` — N2 is unexpectedly positive;
  underpowered or null C2 strata alone do not select this outcome;
- `REFUSE_MECHANICS_OR_LEAKAGE` — any exact invariant fails; or
- `REFUSE_INCOMPLETE_COHORT_OR_ARTIFACT` — cost, identity, or completeness
  fails.

No terminal decision authorizes a sampler run, gameplay screen, whole-game
strength evidence, promotion, or deployment.

The terminal evaluator consumes one typed mechanics report, one integer-only
resource receipt, the exact population/cohort/checkpoint/result inventory,
REF-C replicate stability, C1, pooled C2 plus inference-only N1, complete C3,
trainable N2, and C4. Decision precedence is mechanics/leakage first,
completeness/resource caps second, C1 calibration third, then N2 support.
C2/N1 support is published as a non-gating field. U1 is the same held-out
true-world proper-score gate as C1 and may not be independently relabeled.
`PASS_TO_B3...` permits only a
request to review B3 sampler implementation; the result itself leaves every
implementation, run, gameplay, strength, promotion, and deployment authority
false until an independent terminal reproduction accepts it.

## Consolidated review path

To avoid another long review chain while preserving real boundaries:

1. one source/design review covers the capture wrapper, model/projection code,
   this exact population, metrics, controls, caps, and terminal rule;
2. that PASS may authorize the bounded **opened-development** capture/training/
   test pipeline under the frozen caps—no separate one-shot admission, because
   no sealed or confirmatory evidence is consumed; and
3. one terminal reproducibility review reopens the immutable manifests and
   recomputes the decision.

The only operational runner is `server/scripts/belief_v1_b2.py` under its
required safe interpreter flags. Internal library stage functions are testable
mechanics, not alternate admissions. Initialization verifies that local
`origin/main` exactly equals the canonical GitHub `main` tip before accepting
the Claude ledger commit, then writes a durable sibling consumption tombstone
before creating the evidence root. Deleting only the evidence root cannot
create a second initialization or test-opening slot.

If later work uses sealed evidence or a strength population, it receives a
separate design and admission. This offline design grants none.
