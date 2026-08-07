# Suphx-style privileged-feature-removal microbaseline

Status (2026-08-07): **FEATURE-PARTITION CODE GATE PASS / NO TRAINING
AUTHORITY.** This document defines the next Lane-C mechanism after terminal
Direct-Q SELECT NONE. It may authorize implementation and score-blind runtime
benchmarking only. A later version must bind exact code, runtime, seeds, doses,
state assets and artifact destinations before any learning result is produced.

Implementation step 1 now lives in `server/shengji/rl/suphx_micro.py` with
feature-contract SHA-256
`dfbdf9d679f87999344864554d01f493995beade99c5b275266d8de37fd4b97f`.
The feature module itself hashes to
`5636a137dedbfe593d26d5a18e606ee4a0b59e42092e13d12907ce077d111b85`.
Its 12 focused falsification tests pass. Implementation step 2 adds four
independent attacker/defender x lead/follow policy/value heads in
`server/shengji/rl/suphx_policy.py`, policy-contract SHA-256
`34d12e09f0f46bf1794b8480aa6abcecc9ed080666fad7cd99d11acab5d46735`
and module SHA-256
`ed799bbe40320dda5468633c37cabdc908ea61c8cbb1d59024927df862c503a5`.
The combined Suphx mechanics gate is 19/19 and the adjacent encoder,
Direct-Q and synchronous-resume matrix is 80/80. No actor, learner, CLI,
registry entry, run artifact or training result exists yet.

## Claim boundary

The hypothesis is narrow:

> An ordinary-play policy that first learns with exact hidden-card features,
> then trains through an elementwise Bernoulli feature-removal curriculum, can
> retain a stronger public-information policy than equal-work immediate
> removal or oracle-distillation controls.

This is a Shengji test of Suphx's oracle-guiding mechanism. It is not a full
Suphx reproduction, not a claim about pMCPA, not an extension of Direct-Q or
DMC2, and never production authority by itself. It supports ordinary play
only. Declaration and burial remain explicit frozen controls until separately
modelled.

The design follows the mechanism in the
[Suphx paper](https://arxiv.org/abs/2003.13590): train the same policy on
`[normal_features, delta_t * perfect_features]`, where every element of
`delta_t` is Bernoulli with keep probability `gamma_t`; decrease `gamma_t`
from one to zero, then continue at zero with a tenfold lower learning rate.
It does **not** substitute an oracle value, subtract an oracle scalar from a
return, or call distillation the treatment.

## Information contract

One encoder must make legal and privileged information structurally distinct:

- **Normal observation:** the versioned public observation, the acting seat's
  hand, chronological public play history, role, lead/follow surface and the
  banker's own buried cards when and only when the acting seat is the banker.
  The banker legally remembers its burial; omitting it would make the public
  endpoint intentionally wrong.
- **Perfect features:** remaining cards in the other three hands, relative to
  the acting seat, plus buried cards only when they are hidden from that seat.
  At ordinary-play time Shengji has no undealt wall, so these features cover
  all simulator-only card ownership.
- **Dropout:** a named local RNG draws one Bernoulli value per perfect-feature
  element per decision. Endpoints still consume the same mask stream. Action
  sampling uses a separate named RNG so changing `gamma_t` cannot silently
  change the action-randomness stream.
- **Public endpoint invariant:** with `gamma_t = 0`, logits, values and chosen
  actions must be bit-identical after any legal permutation of hidden hands
  and hidden burial that preserves the actor's information set and ordered
  ballot. No perfect feature or mask may enter the production adapter.
- **Oracle endpoint witness:** with `gamma_t = 1`, at least one named state
  pair differing only in hidden ownership must change a nontrivial policy
  logit. Otherwise the treatment has no executable privileged signal.

Every sample stores the exact normal encoder identity, perfect encoder
identity, ordered ballot, unmasked perfect vector, sampled mask, masked-vector
digest, actor checkpoint, batch/decision seed identities, behavior
probability, role/surface, terminal signed return and public-history sequence.
Reopening must reconstruct every tensor and action probability exactly.

## Policy and learning contract

- Use four independent ordinary-play policy/value parameter sets:
  attacker-lead, attacker-follow, defender-lead and defender-follow. This
  preserves Shengji role asymmetry and Suphx's decision-surface specialization
  instead of asking one monolith to absorb both.
- Score the complete ordered `rl-actions-v1-narrow-no-extra-throws` ballot
  with an action-conditioned policy head. The value head is a baseline only;
  it cannot choose actions or become a generic MC leaf.
- Begin from named, from-scratch weights for the mechanism screen. Do not warm
  start from the terminal Direct-Q candidate or choose initialization from its
  inspected positive gameplay tail.
- Collect synchronously from one immutable actor generation, update once, and
  publish the exact candidate before adoption. The existing exact-resume
  boundary must bind learner, optimizer, entropy controller, progress, replay,
  actor, candidate and all named RNGs.
- Use on-policy action probabilities with direct acting-team terminal
  level-bracket returns and a learned value baseline. A stored behavior
  probability must equal the recomputed pre-update probability. Replay from an
  older actor requires an explicit importance ratio and cap; the first
  microbaseline instead uses only its current immutable batch.
- Maintain a target policy entropy with controller state inside the exact
  checkpoint. Record entropy, action spread and clipping/rejection counts by
  role and lead/follow surface. Collapse in any surface is a stop, not a reason
  to change the target mid-run.
- After the curriculum reaches `gamma_t = 0`, continue public-only with a
  learning rate fixed at one tenth of the curriculum rate. This is a new exact
  synchronous segment rooted at the prior checkpoint, never an in-place
  unrecorded optimizer mutation.

## Causal arms

The mechanism is decomposed so a failed prerequisite does not consume the
full screen.

### O0 — oracle acquisition

Train equal-seed/equal-work full-information (`gamma=1`) and public-only
(`gamma=0`) arms under the same policy objective. The full-information arm
must show executable learning signal and remain noncollapsed on frozen oracle
diagnostics. If it does not, stop: feature removal cannot rescue an oracle that
never learned.

O0 is an unfair-information prerequisite, not a deployable result. Its
full-information policy never enters a public duel or production registry.

### O1 — removal mechanism

Fork every admitted oracle checkpoint byte-for-byte into three equal-work
arms:

1. **Curriculum treatment:** decay elementwise perfect-feature keep
   probability from one to zero, then run the lower-rate public-only segment.
2. **Immediate-removal control:** switch to zero at the first transition
   update and otherwise match samples, updates, endpoint learning rate and
   optimizer reset.
3. **Distillation control:** train a public-only student from the frozen oracle
   policy on the same state/ballot population, then give it the same number of
   public-only policy-gradient updates. Distillation targets are oracle logits,
   never terminal values; its total simulator trajectories and optimizer steps
   must match the treatment.

The arms share initial bytes and named deal identities but use
domain-separated exploration/mask streams. No arm may inherit another arm's
sampled action or trajectory after its policy diverges.

## Frozen diagnostics and gates

The executable launch packet must create disjoint assets before training:

- **MECH:** synthetic and exact replay witnesses for encoder separation,
  endpoint invariance, Bernoulli-mask reconstruction, role/surface routing,
  immutable actor use and interrupted/resumed byte equality. These may guide
  code repair but carry no learning claim.
- **DEV:** fixed non-production deals for O0 oracle-signal and action-spread
  diagnostics. DEV may choose only whether O0 is worth continuing; it cannot
  choose O1 schedule, seed, architecture or report dose.
- **REPORT:** untouched paired deals for public-only O1 endpoints. REPORT is
  opened once after all three arms and all seeds publish exact terminal
  checkpoints. It compares curriculum against both immediate removal and
  distillation, and compares each endpoint with its exact oracle-parent public
  projection.

Before compute, the launch packet must pin:

- three model/learner/runner seed triples and domain-separated deal, mask and
  action streams;
- O0 iterations, O1 decay shape and duration, zero-feature continuation dose,
  both learning rates, target entropy/controller rule, importance cap,
  optimizer, gradient cap and all checkpoint boundaries;
- exact MECH/DEV/REPORT deal populations and one-state-per-deal rules;
- sample counts, work reconciliation, role/surface minimum counts and failure
  behavior;
- simultaneous inference family and alpha allocation for the two O1 control
  comparisons; and
- exact artifact names, source/data/runtime hashes and one-shot terminal gate.

O1 passes its **learning screen** only if all of the following hold without a
seed exception:

1. public-endpoint invariance, exact work/provenance and resume checks pass;
2. every role/surface retains the predeclared minimum action spread and finite
   policy/value/gradient diagnostics;
3. curriculum minus immediate-removal and curriculum minus distillation both
   clear their preallocated paired lower confidence bounds on untouched REPORT;
4. no seed has a negative curriculum-minus-control mean on either primary
   comparison; and
5. the public endpoint has zero perfect-feature dependence under the hidden-
   state permutation challenge.

A pass authorizes only a larger fresh paired learning/strength confirmation.
A production candidate must later beat the exact live report-LCB champion in
a separately frozen paired round and multi-round progression gate. A failure
selects none; it does not authorize more seeds, a longer schedule or reading a
different checkpoint from the same run.

## Implementation order

1. Implement and falsify the normal/perfect encoder and endpoint permutation
   invariants.
2. Implement the four-surface policy/value model, named mask/action sampling,
   exact sample reconstruction and immutable synchronous update.
3. Prove uninterrupted versus resumed equality across a curriculum boundary,
   including entropy-controller and optimizer segment state.
4. Add a score-redacted O0 runtime preflight on Mini and measure enough only to
   predeclare a sub-hour launch dose; no reward, loss or action outcome may be
   opened during timing.
5. Freeze the exact O0/O1 launch packet and request independent review before
   any learning job.
