# Backlog

Last re-derived: 2026-08-09 14:36 EDT.

This file owns the executable queue. `AI_POLICIES.md` owns terminal results,
`RL_PLAN.md` owns research design, `JOBS.md` owns compute, and
`HANDOFF_ACTIVE.md` owns the next review handoff. Historical T1/T2 detail is in
Git and the dated files under `docs_archive/`; it is intentionally not repeated
here.

## Two-minute state

- **Production:** compiled `mc-s0-report-lcb` in Fly release 17. Fresh RLCB-C1
  confirmed `+0.338 +/- 0.068` signed levels versus `mc-strong`; the matched
  null was flat. Runtime rollback is release 16; policy rollback is
  `mc-strong`.
- **Live strength compute:** the reviewed S3a structured-bury full-game screen
  is running on Mini, eight shards × 256 clusters. Outcomes are sealed.
- **Teacher:** the fresh audit passed on ordinary states. Pre-review audit
  superseded Stage-C v1 because it mismatched the adapter packet ID, had not
  reopened the live parent and pinned closed S4 v1. Exact `b0ef0f9` now freezes
  repaired 2,048-state v2 at `45802e47…a350`. A later executable audit
  superseded its H0 v1 parent before outcomes, so this Stage-C packet is held
  pre-review. Repair it only after H0 v2 passes; no capture, labeling, compute
  or training is authorized.
- **Human corpus:** production logs were atomically refreshed on August 9.
  The exact Fly-snapshot-only `human_v8` rebuild contains 2,830 accepted plays,
  45 human buries and 122 fully replayed rounds; all seven incomplete rounds
  are counted, and 12 legacy local-only rooms are excluded. This is a
  proposal/diagnostic asset, not an authorized strength target. Clean producer
  `b52dc33` and corpus manifest `b9699790…16553` passed exact review; that
  evidence authorizes bounded H0 design only. Exact `9770313` froze and independently
  verified a score-free 384-DESIGN/128-AUDIT packet at `9ff160a9…247d3`;
  Claude independently passed v1's split semantics, but a pre-controller audit
  found its pinned V11 SHA names no artifact. V1 has no outcomes and cannot
  parent execution. Exact `12dac55` repairs the executable checkpoint/live-
  parent bindings and freezes score-free v2 packet `2cccf580…8f2b`, reproduced
  byte-exact on Air; rereview is now open. Execution, labels, training
  and strength remain closed. The latest complete
  server pull at 18:09 UTC found all 30 files unchanged, so this corpus remains
  the current production snapshot rather than a stale copy. Its split is
  name-derived pseudonymous-player/deal disjoint, not guaranteed true-person
  disjoint if a person changed names; that is acceptable for H0 diagnostics,
  not HUMAN-C1 evidence.
- **S4:** v1 is closed HOLD without outcomes because its material digest did
  not reproduce. Exact `1b35fb7` fixes the utility and evidence boundary. A
  fresh score-free Air capture froze 64 unique exact-late trigger states
  (32 per role) at `4538be85…6b5f`. Exact `b0ef0f9` then independently rescanned
  all 69,047 ascending deals and rebuilt every row exactly; witness
  `3079fb16…f0a9`. Claude passed rereview. The one reviewed Air execution
  exactly verified terminal result `abd9f36f…cdc00`: overall point delta
  `+5.156`, LCB `+3.029`, both roles positive, 35 wins/4 losses/25 ties.
  A pre-review audit invalidated the first complete-round packet without any
  launch or outcomes: its validator accepted wrong-signed/unbounded utility,
  underfilled report work and direct shards without reviewed authority. Exact
  `cad3992` is the repaired v2 runner/controller. Fresh score-free Air
  preflight `fcc8b891…ee060` passed, and packet `17036e63…1385` recomputes.
  Claude independently passed the repaired packet at marker commit `51a864c`.
  This authorizes exactly one 2,048-cluster Mini screen after S3a releases the
  host and a fresh admission/receipt is created; it is not a strength claim or
  confirmation authority. V1 `b64bc95` / `80e4f1bf…6947` is preserved as
  superseded evidence.
- **Learners:** V11 direct-v2, Direct-Q, O0 and O0-v2 all selected none under
  their registered gates. They remain diagnostics, not deployable policies.
- **Free capacity:** Air is free after S4's score-free preflight. No reviewed
  strength launch is available there; Mini remains exclusive to sealed S3a.

## NOW — ordered by value

| priority | work | exact exit gate |
|---|---|---|
| **P0 / S3a terminal** | Let the sealed 2,048-cluster full-game screen finish | Count-only monitor; run the exact terminal verifier once. PASS opens confirmation-packet review only. SELECT NONE closes the exact recipe. |
| **P1 / S4 point-banking rollout** | Wait for Mini, then admit and launch the one reviewed screen | Claude PASS at `51a864c` authorizes exact `cad3992` / `17036e63…1385` once. Create the fresh admission/receipt only after S3a releases Mini; then run 2,048 clusters exactly once. Confirmation, retry, strength and promotion remain closed. |
| **P1 / human counterfactual H0** | Rereview the repaired score-free v2 design | V1 split review passed but its V11 digest is non-executable. Exact `12dac55` / `2cccf580…8f2b` binds real `ep07.npz`, portable report-LCB parent and fixed 30/300 proposal/report semantics. This is the sole open review; PASS may authorize controller implementation only—not execution or outcomes. |
| **P1 / Teacher Stage C** | Repair the H0 parent binding, then review the 2,048-state design | Existing `b0ef0f9` / `45802e47…a350` consumes superseded H0 v1 and is held pre-review. After H0 v2 PASS, freeze a replacement. A later PASS may authorize score-free capture/controller implementation only—not capture, labels or training. |
| **P2 / S3a confirmation** | Confirm a positive screen against the live champion | Only conditional on terminal PASS: freeze and externally review an 8,192-cluster one-shot packet, then launch once. No automatic promotion. |
| **P2 / experiment infrastructure** | Make reviewed jobs cheaper to launch correctly | Introduce one immutable `ExperimentSpec`/receipt boundary for code, data, policy, ballot, sampler, continuation, actor, seeds, metric, null, work, stop rule and output. Scheduling may automate reviewed work; it may not select or promote. |
| **P2 / HUMAN-C1 instrumentation** | Make the people-facing gate executable without contaminating training | Exact `fff688b` extends the tag/log/disconnect/assignment guards with fail-closed active-policy reopening: exact Git/image, registry policy name and every derived ballot stage must match. The 94-test focused battery passes locally/Air. Still required: external review, durable one-use issuance, authenticated consent ingress, reviewed immutable deployment-receipt ingestion, terminal estimator and synthetic C0. No WebSocket route or human launch exists. |
| **P2 / production performance** | Keep the stronger bot pleasant under concurrent traffic | Continue passive release-17 timing; add a concurrent-room tail gate before changing CPU size. Port hot rollout leaves only with pure/compiled parity and end-to-end policy timing. |

## Active T3 milestone — human-witness challenger flywheel

**Plain-English objective:** convert two observed production weaknesses into
an honest challenger and better Teacher data, without depending on a positive
S3a result.

Bot-vs-bot proof is the reproducible engineering filter, not the destination.
The product destination is a challenger that first improves over the live
champion against the same blinded human cohort and then posts positive absolute
utility against a named experienced-human cohort. T3 prepares that challenger,
its evidence-grade data loop and the HUMAN-C1 harness; it does not claim human
superiority from offline logs.

T3 is complete when:

1. the current S3a screen has one independently verified terminal verdict;
2. a PASS has a frozen, externally reviewed confirmation packet, or a
   SELECT NONE has an explicit immutable closeout;
3. S4 point-banking has a verified terminal state screen (now positive at
   `abd9f36f…cdc00`) and a frozen full-game packet ready for external review;
   no full-game launch is required for T3; and
4. Teacher Stage C has a reviewed design packet bound to the executable H0
   parent but has not generated labels without separate authority; and
5. the refreshed human corpus and leakage-safe counterfactual H0 v2 design
   have independent PASS, and its score-free controller is frozen for review, with
   human evaluation games excluded from all training/model selection.

The exact active `/goal` is recorded in `HANDOFF_ACTIVE.md`. It forbids
unreviewed strength compute, training, promotion and production changes.

### Today's concrete exits

1. Preserve S3a until one terminal verifier verdict; do not spend its sealed
   evidence twice.
2. **packet PASS / launch queued:** independently review and run S4 exact-state v2 once. Supersede the
   defective unlaunched full-game v1 packet, then implement, preflight and
   freeze repaired full-game v2 at `17036e63…1385`. Claude passed the repaired
   packet; do not create its admission or launch while S3a owns Mini.
3. **open review:** H0 v1's split review passed, but executable audit
   found a nonexistent V11 digest before controller work. Exact `12dac55`
   freezes byte-reproduced v2 at `2cccf580…8f2b`; review it now. Then
   repair Stage C's H0 binding and only after PASS implement the H0 controller.
   No packet may execute, capture, label or train without new authority.
4. Keep Mini on the long reviewed S3a job and use Air for bounded reviewed
   work only. Idle compute is not a reason to invent an unregistered run.
5. Define the next real product gate as candidate-versus-champion performance
   against the same blinded human cohort, followed by an absolute experienced-
   human benchmark. Bot Elo and site-average win rate remain diagnostics.

## Three-lane strength plan

### Lane A — improve the search policy directly

- **S3a structured bury:** directly addresses the bot's point-shy kitty
  behavior with strategy-aware void/point/trump candidates. The 512-state
  mechanism screen passed; the fresh full-game screen is live.
- **S4 point-banking continuation:** the exact-late mechanism screen passed in
  both roles (`+5.156` points overall, LCB `+3.029`). Preserve the frozen
  continuation-only recipe and now test natural complete-round utility against
  the live champion and a trigger-matched null.
- **Later search:** S3b-v2 is closed on its node cap. Any exact-late successor
  needs a new bound/solver hypothesis and fresh review, not a relaxed retry.

### Lane B — make a Teacher that can exceed the champion

- Mine fresh non-evaluation states from uncertainty, high paired SE,
  champion/proposer disagreement, exact-late opportunities, point-bearing
  kitty voids and point-banking winner choices.
- Keep human-observed examples as named DEV/regression witnesses. They may
  validate triggers but cannot appear in CALIB or REPORT.
- Escalate uncertain states to gold or exact-late continuation. Store action
  ballots and common-world paired outcomes, not only selected labels.
- Train ranking and calibrated signed-outcome heads only after the hard-tail
  labeler beats its ordinary baseline on untouched data. Start with
  state-count/seed curves before a 10k/50k collection wave.

### Lane C — learn beyond MC imitation

- O0-v2's shared-public CRN and semantic replay are reusable evaluation
  infrastructure; its margin arm and O1 path are closed.
- The next learner must change one substantive mechanism: target/credit,
  on-policy adaptation, decision-type specialization or data curriculum.
  Hold CRN evaluation and at least eight independent training seeds fixed.
- Use a learned model first as a proposal/ranking/allocation feature inside
  search. A scalar private-observation leaf remains invalid without a named
  belief and continuation policy.

## S4 point-banking implementation contract

The observed failure is narrower than “the bot never wins with points.” Root
MC can source point-card winners, and the heuristic uses one when it is the
only winner. The suspected bias occurs when rollout continuation has multiple
legal winners and `_cheapest_winning` selects a cheaper non-point card.

Implemented initially at `402c012`; the reviewable replacement is exact
`1b35fb7`:

- named states in both directions: treatment chooses a point winner when
  justified, and declines it when banking points harms team utility;
- exact legal-action equivalence and no engine/rule changes;
- root ballot and production policy byte/decision invariance with the flag off;
- a treatment trigger based on multiple winning actions, point delta, current
  trick ownership/team and remaining strategic cost—not merely “K available”;
- trigger-matched null that consumes equal work without changing continuation;
- per-decision trigger/opportunity/change/work counters and deterministic RNG
  replay;
- mutation tests proving each witness fails if the treatment is removed or
  applied at root;
- fresh, deal-disjoint state population and one predeclared screen metric.
- exact house/Teacher secondary utility (80 and 120 attacker points remain
  distinct), executable ordered-material identity, full admission equality,
  canonical namespace/receipt consumption, runtime/native binding and a full
  terminal recomputation command.

The replacement score-free asset scanned 69,047 fresh deals from seed
161,000,000 and froze 32 attacker plus 32 defender triggers from unique deals.
Natural supply was highly role-skewed (32 attacker, 321 defender), so the
mechanism screen reported both equal-role and per-role estimands. The one-shot
exact result passed: overall acting-team point delta `+5.156` (one-sided LCB
`+3.029`), attacker/defender means `+6.406/+3.906`, 35 wins, 4 losses, 25 ties,
and level utility `+0.25`. A future full-game screen must restore natural
traffic weighting and may still select none; state-level mechanism evidence is
not whole-policy strength.

## Teacher Stage-C packet contract

The Teacher audit says cheap and N=30 choices are faithful on its 64 ordinary
states, but the N=30 boundary diagnostic was weaker (`0.1421` upper bound).
Stage C should therefore spend compute on the hard tail rather than relabeling
ordinary states horizontally. “Hard tail” is not shorthand for openers: early
leads are one protected stratum, alongside follow, bury, late play, both roles,
uncertainty/disagreement and the two human-observed point mechanisms.

The packet must bind:

- fresh source population and deal-disjoint split assignment;
- quotas for early/mid/late, banker/non-banker, lead/follow, candidate count,
  uncertainty/disagreement and the two human-witness mechanisms;
- exact live parent, ballot, sampler, continuation, engine, encoder, role,
  utility and label budgets;
- cheap-to-gold/exact escalation rule frozen before outcomes;
- common proposal worlds plus independent report worlds;
- raw paired outcomes or sufficient statistics, not only an argmax;
- immutable actor/checkpoint identity and explicit no-label/no-training flags;
- a separate untouched hard-tail regret gate before scale.

## Human-data execution

The August 9 Fly-snapshot-only refresh found 2,830 accepted play decisions
across seven pseudonymous players, 45 human buries, seven explicitly rejected
incomplete rounds, and 25 legal human plays absent from the broad analysis
ballot. Humans buried at least one point in 22/45 observed buries. Those are
useful proposal/coverage findings, not proof that the human actions are better.

Next actions:

1. **repair queued:** freeze the independently reviewed `human_v8` identity in
   H0 v2 (`12dac55`, packet `2cccf580…8f2b`) and obtain a fresh design PASS;
2. use the connected-component boundary honestly: the three-player/78-deal
   component is DESIGN, the separate one-player/28-deal component is AUDIT,
   and the three tiny components (three players/five deals) are RESERVE. This
   corpus cannot support a credible three-way player+deal-disjoint REPORT;
3. **done:** select 384 DESIGN plus 128 AUDIT rows, cap repeated decisions at
   eight per deal, include every late/off-ballot row, and balance lead/follow,
   role and depth;
4. only after H0 v2 PASS, implement a score-free controller that unions the actual human action with
   report-LCB, structured and bounded-model proposals, binds fixed common-world
   and disjoint-report work, and refuses execution until its own review PASS;
5. measure candidate recall, human-minus-champion paired utility, continuation
   ranking flips and per-player/per-surface heterogeneity;
6. use supported actions for a proposal/prior head and hard-tail mining. Keep
   raw BC as a separately measured initialization/style control.

Current component inventory: DESIGN has 2,323 plays plus 36 buries across 78
deals; AUDIT has 456 plays plus nine buries across 28 deals; RESERVE has 51
plays, no buries and five deals. Formal strength REPORT remains fresh paired
bot play and the blinded people-facing ladder below.

The frozen sample covers 67 DESIGN and 24 AUDIT deals. DESIGN is 111 early,
111 mid and 162 late; AUDIT is 55 early, 54 mid and 19 late. All 19/5
off-analysis-ballot plays are retained. This deliberate hard-tail weighting is
reported explicitly and is not an estimate of site action frequency.

## People-facing strength ladder

Bot-vs-bot paired games remain the fast reproducible scientific gate, but they
are not the product's final objective.

1. **Offline human-action audit:** coverage/disagreement only; never claim that
   agreement means strength.
2. **Closed HUMAN-SCREEN:** after a bot-vs-bot confirmation, run blinded,
   opt-in games that randomize candidate versus champion across the same human
   cohort, balance banker/team/seat, and cluster inference by player session.
3. **HUMAN-C1:** require the candidate to improve signed level utility against
   humans versus the live champion with a predeclared one-sided interval, while
   remaining non-inferior on completion, illegal/fallback, latency and player
   experience metrics.
4. **Absolute target:** separately report win/level utility against a named
   experienced-human cohort. Site-average win rate is monitored but cannot hide
   cohort mix or repeat-player concentration.

All human evaluation rooms are quarantined from training and model selection.
Policy identity is hidden from players during the test, consent/opt-in is
recorded, and promotion still requires the bot-vs-bot correctness/strength
chain so noisy human traffic cannot select a policy by accident.

### HUMAN-C1 implementation boundary

The current production server is **not yet an evidence-grade A/B harness**:

- its bot policy is selected deployment-wide from `SHENGJI_BOT`, not assigned
  immutably per room/session;
- `round_start` does not bind an experiment arm, policy commit/image,
  assignment probability or consented pseudonymous participant/session ID;
- normal rooms can mix human and bot partners/opponents, so changing every bot
  does not isolate whether a policy helped its human partner or beat its human
  opponents; and
- all `/data/logs/*.jsonl` files feed the production-log snapshot. Evaluation
  traffic would therefore leak into a later human corpus unless it is
  structurally separated and refused again at corpus-build time.

Before recruiting players, freeze and review one no-traffic contract that:

1. runs two human teammates against two identical bot teammates, with balanced
   parity seats, banker opportunity and starting levels;
2. assigns candidate or champion once per room/session from a hidden,
   preregistered block schedule and never changes policy mid-session;
3. records experiment/arm probability, exact Git/image/policy/ballot identity,
   consent version, pseudonymous player cohort/session IDs, seat/team/banker,
   completion/refusal/fallback and timing;
4. writes to a dedicated evaluation log root outside `/data/logs`, while the
   corpus builder independently rejects the experiment tag if a file is copied
   into training inputs by mistake; and
5. reports candidate-minus-champion bot-team signed level utility with
   player/session-clustered inference. A separate absolute row asks whether the
   candidate bot team itself beats the named experienced-human cohort.

The site's ordinary one-human-plus-three-bot experience remains a later
product/latency and satisfaction A/B. It is not the clean strength estimand
because the changed policy appears on both the human's team and the opposing
team.

## Correctness and data

- [x] Bounded sampler hard-validity/support certificate on original, late and
  deep reservoirs under compiled strict execution.
- [ ] Prove global dealer completeness/runtime with declaration pins and run
  caps; current randomized filling is not a constructive completeness proof.
- [ ] Repair posterior fidelity only through exact-toy calibration, runtime
  measurement and fresh policy revalidation. Posterior-changing flags stay off.
- [ ] Regenerate quarantined banker-private-kitty encodings from retained raw
  states before training; `gen_v4_all` remains the known-clean v11 source.
- [ ] Version a house-v1 conformance corpus and native ABI/source digest guard.
- [ ] Require every dataset to bind replayable state, split, role, action
  multiset, ballot, sampler, continuation, utility, actor and producer hashes.

## Performance, simplification and product

- [ ] Port `_lead`, `_current_winner` and `_cheapest_winning` to the compiled
  core one bounded phase at a time; require pure/compiled semantic parity and
  end-to-end bot timing.
- [ ] Vectorize `bc_train`; the per-decision loop is MPS-dispatch-bound.
- [ ] Add a concurrent-room production latency gate and keep X-ray work off the
  event loop. CPU resize is a separate operational experiment.
- [ ] Remove dead helpers only after import/reference audit and replacement
  tests (`segbatch.py`, `replay_log.pretty_cards`, duplicated card/seat helpers).
- [ ] Split the API only along established room/reconnect tests; do not mix the
  refactor with frontend behavior changes.
- [ ] Add CI for server tests and frontend build.
- [ ] Finish spectator privacy, trick history/replay, reconnect/takeover edge
  tests and portrait/zh-CN polish as separate product lanes.

## Maintenance and documentation

- [x] Compact `HANDOFF_REVIEW.md` into a short active mailbox and archive the
  exact T1/T2 ledger.
- [x] Compact `HANDOFF_ACTIVE.md` around current truth, the next packet and
  standing rules.
- [x] Reconcile the live-champion roadmap across this file and `RL_PLAN.md`.
- [x] Remove 13 merged or ancestor-redundant remote branches and seven clean
  temporary worktrees. Retain sole evidence/active heads until tagged or
  integrated; never delete them merely to reduce a count. The reviewed S3a
  controller is now maintained on main via `d7cdf2e`; retain its original
  `c599b42` evidence head until the detached screen terminates, then tag the
  exact run commit before deleting that branch.
- [ ] Periodically archive completed `JOBS.md` stubs and keep top-level design
  docs limited to current operational references.

## Closed — do not re-queue

- Formal S0c is unread and nonretryable; RLCB-C1 independently supports the
  deployed report-LCB policy.
- N=30 beat N=10 twice; N=60 did not establish an increment over N=30.
- DEV-512 generic lead widening selected none; do not append arms to inspected
  DEV or open CALIB/REPORT.
- V11 direct/protected-anchor, Direct-Q 144M, O0, O0-v2/O1 and S3b-v2 are
  closed exact recipes. Preserve diagnostic lessons; require a new mechanism.
- Value-leaf, pairwise-as-scalar-leaf, generic widening and learned root-prior
  racing have no current promotion path.
- Correctness, faster simulation, larger corpora and green pipelines enable
  strength work but are not themselves AI wins.

Standing rule: a screen may reject or select one frozen design. Only a fresh,
paired, clustered confirmation against the exact deployed champion can
establish strength, and only a separately reviewed production packet can ship
it.
