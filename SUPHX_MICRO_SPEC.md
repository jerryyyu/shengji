# Suphx-style privileged-feature-removal microbaseline

Status (2026-08-07): **O0 EXECUTABLE PACKET IMPLEMENTED / INDEPENDENT
RE-REVIEW REQUIRED / NO TRAINING AUTHORITY.** This document defines the next
Lane-C mechanism after terminal Direct-Q SELECT NONE. The runtime preflight
passed, and the exact DEV/freezer/trainer/evaluator/gate implementation now
exists, but no launch packet has been frozen and no learning run is authorized.

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
Direct-Q and synchronous-resume matrix is 80/80.

Implementation step 3 adds an immutable categorical actor and synchronous
on-policy actor-critic transition in `suphx_actor.py` and `suphx_learning.py`.
Actor contract/module SHA-256s are
`2592696365a16c8aebf10fa20c7554b69a177cbe63ab2500e652b332b4bcc7f0` /
`70c992155c280ab927af40875be5b12bdbf3865ccf5d41abdc19d2c07308a6e0`;
learning contract/module SHA-256s are
`8683e36488e7bf942114722bb240e91b83ec5e073bc43292542e6f5df0adff29` /
`3c6b76600626b753ec3eb0f18c24bb9f0464d3edeabf81f26ea087c43d06df85`.
Separate named deal/mask/action streams, complete ballots, exact behavior
log-probabilities, explicitly clipped role-signed attacker-point brackets,
scheduled gamma, per-surface entropy buffers and exact candidate adoption are
executable. An interrupted
`gamma=1` to `gamma=0` transition reproduces the next batch bytes, candidate,
learner, optimizer, replay, RNG and controller state. Different actor digests
now reproduce the same initial deal and ballot under a shared schedule-bound
deal root while consuming distinct mask/action streams. The lower-rate child
transition reopens only an exhausted, adopted exact parent; preserves model and
entropy-controller state; resets Adam, replay and learner RNG; binds all-zero
masks at one-tenth LR; proves finite deal-stream disjointness; and publishes
zero games or updates. Focused mechanics are 52/52 and the broader adjacent
matrix is 136/136.

Implementation step 4 is pushed at `b22ee8e`. The stdlib-only launcher refuses
experimental sampler/ballot keys before importing behavior code; the runner
then requires compiled+strict routing and a clean hash of every material
policy, ballot, engine and native-binary dependency. It executes exactly three
disposable one-round updates at each endpoint (`gamma=1` and `gamma=0`) on the
same actor-independent deal stream, retains no learned candidate, and permits
only timing and exact work counts across the artifact boundary. Its 13
falsification tests pass; the full Suphx/Direct-Q/resume-adjacent matrix is
158/158 in both ordinary and compiled-strict routing.

The exact Mini artifact
`server/runs/logs/suphx-o0-runtime-preflight-v1.json` passed and reopened at
SHA-256 `4f0c3dd542634b66fd0826a8caef5dc21c7a8b083f96804d1f2f9bbe653ee434`.
Six temporary updates took 2.665 seconds, all work and four role/surface counts
reconciled, and both endpoints used causal-deal digest
`ef63549f6f344db0b29a55a1b40cc807d6dcf360a79a383ce84f3f4895688f48`.
The conservative sub-hour formula recommends the capped 64 iterations per
arm. Every authority field remains false: this result sizes a later packet but
does not launch O0, select a model, authorize O1, or support production.
Frozen O0 DEV diagnostics and the exact reviewed launch packet still do not
exist.

Implementation step 5 now lives in
`server/shengji/rl/suphx_o0_screen.py` behind the stdlib-only
`server/scripts/suphx_o0_screen.py` launcher. The freezer creates the exact
three initial checkpoints, 192 collision-free causal training deals, and 128
one-state-per-deal DEV rows stratified 32/32/32/32 across the four policy
surfaces. A DEV hidden-world witness must satisfy card conservation, hand and
burial sizes, actor-visible state, demonstrated voids, pair/run caps and
remaining declaration evidence before it can test oracle sensitivity. Every
surface also carries a non-banker hidden-burial witness; an impossible
void-breaking swap is an explicit negative test. The deterministic greedy
evaluator uses both team flips and an exact same-model zero null. The terminal
gate applies the two fixed one-sided Student-t bounds and every conjunctive
health criterion below.

The code intentionally cannot train from the freezer alone. A separate
`review_admission.json` must bind the exact launch-packet SHA-256 and an
immutable byte copy of an independently supplied review record. The source
record must be outside the run namespace and contain exactly one
`SUPHX_O0_PACKET_REVIEW_V1` JSON marker naming that packet SHA, a literal PASS,
independent review, O0 training authority and false O1/strength/production
authority. Plain prose, a HOLD, another packet hash or a file inside the run
cannot admit training. Training then
exercises a real 32-update midpoint teardown/reopen before completing the
fixed 64-update arm. A PASS can authorize only freezing and independently
reviewing O1; neither PASS nor failure creates strength or production
authority. The focused suite currently passes 22/22, including a reduced real
train/resume/evaluate/reopen path. These candidate bytes still require
independent re-review before `freeze`, `admit` or `train` is invoked.

The complete O0 namespace is fixed before freeze at
`server/runs/logs/suphx-o0-fixed-ensemble-v1`. Every freezer, verifier,
admission, training, evaluation and terminal-gate entry point rejects any
other root, and the launch packet binds both that relative root and every
artifact name. The operator may not redirect reviewed bytes into a new run
identity.

Packet reopening has two explicit costs. Routine admitted train/evaluate calls
verify immutable hashes, structure, runtime and source identity without
regenerating the 128 DEV games. Freeze and the independent `verify-packet`
review path regenerate the complete DEV asset, while the terminal gate
recomputes every diagnostic and semantically replays every raw comparison
round. This removes redundant simulation from ordinary reopen without moving
semantic replay away from an authority boundary. Freeze, diagnostics,
evaluation and terminal replay emit progress at least every 16 DEV deals or 64
replayed rows.

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
- **Causal deals:** each schedule binds an explicit nonnegative deal-stream
  root. Deal seeds depend only on that root plus batch/round sequence, never on
  actor checkpoint, arm identity, mask stream or action stream. Equal-work
  arms must bind the same root; after policies diverge they still receive the
  same deals but generate their own trajectories.
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
- Use on-policy action probabilities with the explicitly bounded acting-team
  attacker-point bracket (`-3.5` through `+3.5`) and a learned value baseline.
  This is not uncapped `RoundResult.level_change` and must never be reported as
  such. A stored behavior
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
  unrecorded optimizer mutation. Its parent must be exactly exhausted with the
  terminal candidate adopted; the child preserves model/controller bytes but
  explicitly resets Adam, replay and learner RNG and starts a fresh disjoint
  causal deal stream. Constructing this boundary creates no game or update.

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

The arms share initial bytes and the same schedule-bound deal-stream root but
use domain-separated exploration/mask streams. An executable witness requires
different actor digests to reopen the same initial deal/ballot tensors. No arm
may inherit another arm's sampled action or trajectory after its policy
diverges.

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

## O0 launch candidate — executable implementation ready, packet still unfrozen

The following candidate converts the successful timing preflight into one
small oracle-acquisition question. The 2026-08-07 20:51 independent review
accepted the mechanics but correctly required the inference target to say
whether the three learner seeds are fixed or sampled. O0 chooses the narrower
fixed-ensemble estimand below. The executable implementation now exists, but
its immutable launch packet and review admission are absent, so no training
command may treat this section as authority.

### Exact O0 estimand

The primary estimand is the mean paired greedy-play improvement of the **exact
frozen three-seed ensemble** on the named non-production deal population. The
three model/learner/runner identities are part of the candidate definition;
they are not a random sample from a training-seed population. For each of the
128 DEV deals, the analysis averages the two team flips and the three fixed
seed members into one deal-cluster observation. The two one-sided t bounds
therefore quantify variation across the frozen deal clusters conditional on
those exact trained learners and action streams.

This screen deliberately makes no recipe-level claim over unseen
initializations, learner RNGs or exploration streams. Requiring every fixed
seed member to have a positive mean is a robustness gate, not an additional
inferential dimension. A PASS admits only these three exact oracle checkpoints
as the parents of a separately frozen O1 removal experiment. Any later claim
that the training recipe works across random seeds must use a new packet with
independent training runs as an explicit inference dimension; it cannot reuse
O0's deal-cluster confidence bounds.

- Run three from-scratch seed pairs. Within a pair, oracle and public use the
  same model seed, learner seed and actor-independent deal root, but different
  runner roots. The different runner roots domain-separate mask/action draws;
  the shared deal root keeps all 64 training deals causal and equal-work.
- Candidate seed identities are:
  `model=160000001..160000003`,
  `learner=160010001..160010003`,
  oracle runner `160020001..160020003`, public runner
  `160021001..160021003`, and shared per-pair deal roots
  `160030001..160030003`. The packet must enumerate all derived deal seeds and
  prove no within/between-pair collision.
- Each arm runs exactly 64 one-round/one-update iterations at learning rate
  `1e-3`, with `gamma=1` throughout oracle and `gamma=0` throughout public.
  This is 384 rounds and 384 updates total. Both arms start from byte-identical
  weights within each seed pair; every terminal candidate must be explicitly
  adopted and exact-resume verified.
- O0 DEV is 128 untouched non-production deals
  `160100000..160100127`. These deals are disjoint from all derived training
  deals and every current DEV/CALIB/REPORT/Teacher/C1 range. They may decide
  only PASS/SELECT NONE for this O0 recipe and may never choose O1 schedules,
  architecture, checkpoints or dose.
- The evaluator uses deterministic greedy ordinary play with the exact narrow
  training ballot and SmartBot declaration/burial controls. Every comparison
  uses both team flips on every deal. A same-model two-flip null must be exactly
  zero before any efficacy statistic is accepted.
- The two primary deal-clustered comparisons are oracle terminal minus its
  exact `gamma=1` initial model, and oracle terminal minus the equal-seed public
  terminal model. Average the two flips and three seeds within deal, allocate
  a one-sided Student-t deal-cluster LCB at alpha `0.05` to each comparison
  (Bonferroni family alpha at most `0.10`), and require both bounds to exceed
  zero. Every individual seed mean must also be positive on both comparisons.
- Hard health gates are exact work/provenance/reopen; finite model/controller
  state; all four role/surface cells in every arm; median normalized policy
  entropy at least `0.35` on multi-action DEV rows for every seed, arm and
  surface; a nonzero hidden-ownership logit witness in every oracle surface;
  and bit-identical public logits/actions under the corresponding hidden-world
  permutations. Initial-to-terminal value-MSE, greedy-action changes and
  entropy curves are diagnosis only, not alternate pass routes.
- A PASS authorizes only freezing and reviewing O1. A non-PASS selects none for
  this exact O0 recipe: do not append iterations, seeds, DEV deals or a more
  favorable checkpoint after reading it. Neither outcome is a strength or
  production claim.

The remaining implementation review should challenge the 128-deal power,
alpha allocation, entropy floor, seed/domain separation, legal hidden-world
validator and whether the greedy mixed-team evaluator is the smallest faithful
test of oracle acquisition. The fixed-ensemble estimand itself may not move
after any learning outcome exists. Once the implementation commit passes
independent review, it may freeze the executable assets and launch packet;
training remains unauthorized until those exact packet bytes receive a second
hash-bound independent review admission.

## Implementation order

1. Implement and falsify the normal/perfect encoder and endpoint permutation
   invariants.
2. Implement the four-surface policy/value model, named mask/action sampling,
   exact sample reconstruction and immutable synchronous update.
3. Prove uninterrupted versus resumed equality across a curriculum boundary,
   including entropy-controller and optimizer segment state.
4. **Complete:** run the score-redacted O0 runtime preflight on Mini and use it
   only to predeclare a sub-hour launch dose; no reward, loss or action outcome
   was opened during timing.
5. Freeze the exact O0 DEV diagnostic population and O0 launch packet at the
   preflight's 64 iterations per arm, then request independent review before
   any learning job. O1 assets and schedule remain a later boundary reached
   only if O0 passes its oracle-acquisition gate.
