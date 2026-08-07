# Teacher-v1 staged experiment spec

Status (2026-08-07): historical packets `teacher-v1-entry-120m-v1` and
`teacher-v1-entry-143m-v2` are **REFUSED** and immutable. V1 stopped after all
eight captures because its in-memory ballot used tuples while JSON used lists.
V2 also completed capture but stopped before diagnostics because the V11
diagnostic actor could return a legal action outside its canonical ballot.

The versioned repair `teacher-v1-entry-149m-v3` is now
**STAGE A PASS / STAGE B STATES FROZEN**. At clean pushed commit `be25b4d`, Air
produced eight 128-deal captures and eight exact-parent diagnostics over seeds
`149000000..149001023`, then froze 64 states at SHA-256
`e016373e8ecb9b6c7b6f3c14f8f4b14d9845f76478137f7a2c07249628cb4648`.
The first primary producer failed closed on a tuple/list JSON publication
defect and remains immutable. Exact-parent repair `b41d8b3` then completed
fresh primary-v2/rerun-v2 populations. Stage-A gate SHA-256
`731dfa936b6f572866538ead701cdf48d231ef3d1d3a6a0034c2debb1517635b`
records PASS, zero problems, 64 deterministic matches and 218,112
candidate-world rollouts.

Bounded freezer transition `d6adbe6` permits only the exact `be25b4d ->
b41d8b3 -> d6adbe6` ancestry and changed-path scopes while keeping every game,
sampler, replay, actor, label and gate source exact. Air passed 123 focused
tests and froze 128 disjoint Stage-B states at SHA-256
`90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6`;
an independent recomputation matched all states with 96 representative, 16
boundary, 16 uncertainty and zero Stage-A overlap. No Stage-B receipt or label
exists yet. This remains mechanics/state evidence, not teacher-quality, model
or production evidence.

The executable entry boundary is `server/shengji/teacher_v1.py`,
`server/scripts/teacher_v1_states.py` and the singleton
`server/scripts/teacher_v1_entry_supervisor.py`; later receipts, labels and
gates remain in `server/scripts/teacher_v1_{receipt,label,gate}.py`. This is the
operational contract for a new counterfactual training/challenge asset. It is
not an extension of DEV-512 and may not read or score CALIB-512 or REPORT.

## Objective and stop rule

Produce action-ranking and scoring-bracket targets that can improve compiled
`mc-strong` N=30, rather than more precise labels for the old heuristic ceiling.
Stop a stage when its gate fails. A clean mechanics check alone does not prove
teacher usefulness; a held-out teacher gain alone does not prove bot strength.

## First execution packet — frozen before capture

Historical refused packets:

- `teacher-v1-entry-120m-v1`, seeds `120000000..120001023`: preserve its
  completed captures in place; it produced no admissible diagnostic,
  frozen-state or label population.
- `teacher-v1-entry-143m-v2`, seeds `143000000..143001023`: preserve its
  completed captures and off-ballot witness `143000001:44:0`; it produced no
  admissible diagnostic, frozen-state or label population.

Accepted entry packet id: `teacher-v1-entry-149m-v3`.

- Capture exactly 1,024 fresh deals, seeds `149000000..149001023`, as eight
  interleaved 128-deal shards (`seed0=149000000`, `max_deals=1024`, shard
  indices `0..7`). All eight use the same clean commit, compiled engine, strict
  void mode, exact Python `3.14.6`, production `mc-strong` actor and three
  digest-pinned exam splits. The experimental flags
  `SHENGJI_WEIGHTED_SPLITS`, `SHENGJI_UNIFORM_DEAL`,
  `SHENGJI_PHYSICAL_FILLS` and `SHENGJI_ALLOW_BALLOT_MISMATCH` must all be
  unset at producer and supervisor admission.
- Diagnose those exact eight capture artifacts in shard order. Stage A and
  Stage B use this same immutable diagnostic population; no extra capture may
  be appended after any selector diagnostic or label outcome is inspected.
- The supervisor reopens every parent. Each diagnostic row's complete embedded
  state must be canonically identical to its exact capture row. The frozen
  64-state set must equal a fresh recomputation of `select_gate_states` over all
  eight diagnostics, and its coverage parent/record maps must be recomputed
  from those actual manifests. Invented, altered, reordered or out-of-range
  states refuse the packet.
- Freeze 64 Stage-A states once. Before labelling, create one exclusive
  `stage-a-primary` producer receipt, then bind all eight 8-state 256/256 shards
  to its exact bytes. Create a separate `stage-a-rerun` receipt with a distinct
  run id, SHA and nonce before running the same eight partitions a second time.
  The Stage-A gate requires deterministic evidence equality excluding wall
  time and refuses reused receipt identity before it can emit PASS.
- Only a Stage-A PASS bound to that exact state-set SHA authorizes freezing the
  128 disjoint Stage-B states. Create distinct `stage-b-cheap` and
  `stage-b-gold` receipts; label eight 16-state cheap shards, then one exact gold
  child for each cheap shard with 64/64 folds. Only the registered regret gate
  may authorize Stage C.
- No short shard, replacement seed, partial merge, world-count change or
  extension is admissible. A pre-label supply deficit closes this packet
  **INCONCLUSIVE**; predeclare a new larger fresh capture packet rather than
  appending deals.
- Every v3 entry artifact through the 64-state freeze is first written to an
  exclusive `.partial` and published by a no-overwrite hard link. A concurrent
  final, existing partial or dangling final symlink refuses and leaves the
  losing partial for diagnosis; no overwrite-capable rename is allowed on this
  entry path. Later receipt/label/gate publication must pass the same boundary
  before Stage-A labels are authorized.
- Prefer Mini for capture, diagnosis and Stage A because each bounded phase is
  expected to fit the sub-hour policy. Before Stage-B gold, use Stage-A/cheap
  timing to choose whole-shard placement; never pool partial artifacts from
  different executable identities.

The canonical artifact order is:

1. `capture_shard00..07.json` -> `diagnostic_shard00..07.json`;
2. `stage_a_states.json` -> primary/rerun receipt JSON ->
   `stage_a_primary_shard00..07.json` plus
   `stage_a_rerun_shard00..07.json` -> `stage_a_gate.json`; and
3. `stage_b_states.json` -> cheap/gold receipt JSON ->
   `stage_b_cheap_shard00..07.json` -> exact-parent
   `stage_b_gold_shard00..07.json` -> `stage_b_gate.json`.

Every consumer receives the literal SHA-256 of its input via
`--expected-input-sha256`. Stage-B freeze additionally receives
`--exclude-state-set stage_a_states.json --stage-a-gate stage_a_gate.json`.
Every real label invocation also receives `--producer-receipt` and
`--expected-producer-receipt-sha256`; every real gate receives `--state-set`
and `--expected-state-set-sha256`. Receipt creation happens before expensive
labelling and refuses to overwrite either a final or partial path.

## Immutable identity

- Fresh self-play deal seeds start at `149000000`; one selected state per deal.
- State actor is the version-pinned `mc-strong` policy frozen by this packet;
  it is not silently renamed to the subsequently deployed report-LCB policy.
  Store its checkpoint/policy identity, git tree, engine, sampler, Memory,
  action encoder and exact
  `BallotSpec` digests. Actor identity is converted to the JSON domain before
  hashing or comparison, so a write/read round trip is identical while a real
  ballot or source change still refuses.
- Derive independent RNG streams from experiment id + deal + state + candidate
  + fold for state selection, belief worlds, continuation and evaluation. Store
  the derivation inputs, not only a mutable RNG-state digest.
- Strict sampling is mandatory. Any illegal/unheld action, replay mismatch,
  zero-world decision, rejection, invalid world or named skip fails the shard.
- Freeze exact state identities and split assignment before action outcomes are
  inspected. Train/tune/holdout are deal-disjoint 70/15/15 hashes. Existing
  original, late and deep-lead DEV/CALIB/REPORT deal identities are all
  digest-pinned and excluded from all three.
- Canonical label sharding is independently reconstructible:
  `sorted(states, key=state_id)[shard_index::8]`. A label's claimed shard index
  and local metadata are not trusted; the gate reopens the exact state-set bytes
  and reconstructs all eight assignments.
- A producer receipt binds clean commit/runtime, full executable digests, role,
  run id, random nonce and exact state-set SHA before work. All shards in one
  population share its exact bytes; Stage-A primary/rerun must differ in role,
  run id, SHA and nonce. Gates reopen and rehash receipts and label artifacts.
  This is a fail-closed orchestration boundary against accidental, stale,
  malformed or copied artifacts—not cryptographic attestation against a
  malicious repository owner.

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
lead/follow, action archetype and selection design. Representative rows are a
hash reservoir within each stratum and carry an honest inclusion probability.
Boundary/uncertainty rows are deterministic challenge ranks: they carry
conditional inclusion `1.0` and `deployment_weightable:false`, never a
plausible-looking inverse-probability weight.

## Label tensor

For every state, store exact replay, every current-ballot candidate and 512
strict common worlds shared by all candidates. Split worlds before scoring:
256 selection and 256 report. For every `(state, fold, world, candidate)` store
terminal attacker points, acting-team signed points, scoring bracket and signed
level utility under the uncapped house-rule target
`teacher-v1-uncapped-possession-utility-v1`. A future `+3` clip must be a new
named target, not an in-place label change. Also store paired deltas/moments
versus candidate 0, sampler counters, continuation id and exact candidate-world
work. Compressed shards may store the dense tensor; the manifest must expose its
shape and hashes.

The bulk continuation candidate is the deterministic heuristic only because it
is cheap. It is not presumed to be a valid teacher.

## Stage A — 64-state mechanics preflight

Use 48 representative states (four per phase/role/decision cell) plus 16
boundary/uncertainty states. Run the full 512-world label schema.

Stage A is complete. The original primary namespace is a preserved refusal:
post-link verification found `BallotSpec.config` tuple/list drift, so all eight
finals retained `.partial` markers and none entered the gate. Repair `b41d8b3`
canonicalizes each ballot and the complete payload into the JSON domain before
validation. Primary-v2 and rerun-v2 used distinct receipt SHA/nonces/run ids
and completed the same eight canonical 8-state partitions at exact 256/256
work. Gate SHA-256 `731dfa936b6f572866538ead701cdf48d231ef3d1d3a6a0034c2debb1517635b`
reopened every byte and records `PASS`, `problems:[]`, 64 states,
`stage_b_authorized:true` and `stage_c_authorized:false`.

Pass requires 64/64 exact replays, complete legal held ballots, 512/512 accepted
worlds per state, exact tensor shapes, fold disjointness, deterministic rerun
hashes, all counters zero and a measured runtime/work projection. Failure stops
and repairs the producer. Passing authorizes Stage B, not the 2,048-state wave.
The implemented gate requires two full executions whose evidence is identical
after excluding wall time, plus distinct predeclared primary/rerun receipts.
Stage B cannot freeze from the Stage-A state list alone: it requires the
complete/digest-valid 64-state asset and the exact Stage-A PASS artifact whose
`state_input_sha256` binds that asset. It reopens and rehashes all 16 Stage-A
label artifacts and their receipts, reconstructs their canonical partitions,
and reruns record, deterministic-rerun and runtime/source checks before
authorizing a Stage-B state set.

Stage-B freezer transition `teacher-v3-stage-b-freeze-after-json-repair-v1`
is complete. It binds the exact Stage-A state/gate hashes, verifies both commit
ancestry edges and allows only `teacher_v1_label.py` plus its tests in the
historical repair and `teacher_v1_states.py` plus its tests in the freezer
repair. Removing the transition, changing either path scope, changing any
semantic source or breaking ancestry is mutation-tested to refuse. The final
128-state asset SHA-256 is
`90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6`.

## Stage B — continuation-quality gate

Freeze 128 stratified states, disjoint from Stage A, from the fresh population.
On the same candidates, add a gold continuation:

- production `mc-strong` N=30 for downstream partial-information decisions;
- 64 gold-selection plus 64 disjoint gold-report common worlds per action,
  with deterministic inner policy seeds.

Teacher-v1's first executable Stage-B estimand is exactly the production N=30
continuation above. An exact/minimax late continuation is not implemented or
silently mixed into this gate. It may become a separately named teacher only
after a registered solver is proved **information-set legal**; a solver that
lets a player act on opponents' hidden hands is an oracle diagnostic, not a
deployable gold continuation.

The Stage-B continuation decision is now frozen as
`teacher-v3-stage-b-n30-attribution-v1`: run the implemented
`mc-strong@N=30` 64/64 gate unchanged. This asks whether the cheap heuristic
preserves candidate ranking under the old production MC continuation. It does
**not** estimate fidelity to, or strength beyond, the live report-LCB champion.
A 16-state, 1/1 non-evidence timing smoke measured 225 seconds and 1,007,700
inner rollouts on Air, projecting about four hours for eight parallel 16-state
64/64 shards. This measurement fixes placement only; none of its action
outcomes may enter the gate.

The first attribution receipts at commit `85b9047` and their eight completed
cheap shards are preserved but closed before gold. The gold worker emitted no
bounded progress until shard completion, which would make a projected
four-hour run operationally opaque. Commit `a952b3d` adds JSON progress events
after every four outer gold worlds (roughly 30 seconds in the timing smoke) and
at every completed state; a test proves callbacks are periodic/final and do not
change artifact bytes. Fresh v2 cheap/gold receipts and a fresh cheap population
are required under that exact source. Never chain gold from the `85b9047`
population or pool the two attempts.

Before a Stage-C dataset is described as champion-quality, a separately named
`teacher-v3-report-lcb-audit-v1` must compare the N=30 proxy choice with the
live report-LCB continuation on a selector-frozen subset. That audit will use
its own receipts, folds, namespace and gate; it may not be substituted into
the N=30 artifacts. An N=30 Stage-B PASS can authorize the cheap 2,048-state
pilot as a proxy/ranking research asset, but cannot authorize champion
replacement, deployment, or a claim that its targets exceed report-LCB.

Choose the cheap action on its selection fold and the gold reference action on
the gold-selection fold. On gold-report worlds, estimate paired signed-level
regret of the cheap choice versus that frozen gold reference, clustered by
state. The gate passes only if its one-sided 95% upper bound is at most 0.10
signed levels per decision. Top-1 agreement and rank correlation are diagnostics,
not substitutes for regret.

- PASS: authorizes implementation and launch of Stage C with the named cheap
  continuation; it does not auto-launch compute.
- FAIL or inconclusive: do not bulk-label/train the cheap target. Use the next
  compute block to expand gold worlds to a predeclared fixed cap or label a
  smaller set with the stronger continuation; amend the continuation identity
  before any full wave.

## Stage C — 2,048-state pilot

Status: not implemented and not authorized until Stage B passes.

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

A fresh paired full-game win over compiled `mc-strong` N=30 is the minimum
research gate. Champion replacement additionally requires beating the live
report-LCB parent (or its formally confirmed successor) under a versioned
paired gate. Only that stronger result may authorize a 10k/50k state wave or
deployment. Use signed level utility as the primary metric, seat/team flips
inside deal clusters, an explicit null and a single predeclared block. Failed
data/model gates free the fleet for structured bury, exact-late or faithful
self-play work; they do not authorize blind scale.
