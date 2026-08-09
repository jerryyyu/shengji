# Backlog

Last re-derived: 2026-08-09 15:44 EDT.

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
  reopened the live parent and pinned closed S4 v1. Exact `b0ef0f9` freezes
  repaired 2,048-state v2 at `45802e47…a350`, but a later executable audit
  superseded its H0 v1 parent before outcomes. Freeze a new Stage-C binding
  only after bounded H0 v3 passes. Stage C is currently a design, not a
  dataset: no 2,048-state capture, labels, checkpoint or challenger exists.
- **Human corpus:** production logs were atomically refreshed on August 9.
  The exact Fly-snapshot-only `human_v8` rebuild contains 2,830 accepted plays,
  45 human buries and 122 fully replayed rounds; all seven incomplete rounds
  are counted, and 12 legacy local-only rooms are excluded. This is a
  proposal/diagnostic asset, not an authorized strength target. Clean producer
  `b52dc33` and corpus manifest `b9699790…16553` passed exact review; that
  evidence authorizes bounded H0 design only. V1 passed split review but named
  no executable V11 artifact. V2 repaired that identity and independently
  passed at `9fdb67a`; a later score-free execution audit found its analysis
  ballot cap, downstream continuation and requested candidate-recall output
  underdefined. No controller or outcome existed. Exact source `b02b6de` and
  packet commit `d6214ce` freeze bounded v3 at `4d3f0a35…8cc3c`: the same
  384-DESIGN/128-AUDIT play rows, all 36/9 exact bury keys, at most 17 play or
  33 bury candidates, explicit `HeuristicBot` continuation and a hard ceiling
  of 1,329,210 candidate-world rollouts. V3 delta review is open. Execution,
  labels, training and strength remain closed. The latest complete
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

## NOW — output ledger ordered by value

An item closes only when its named artifact and terminal gate both exist.
Passing a design review authorizes the next bounded step; it is not the
scientific output of that step.

| priority / milestone | next work | required output | exact exit gate |
|---|---|---|---|
| **P0 / T3.1 S3a terminal** | Let the sealed 2,048-cluster full-game screen finish | One verifier-authenticated screen aggregate and terminal verdict; on PASS, one frozen 8,192-cluster confirmation packet | Count-only monitor, then invoke the exact terminal verifier once. `AUTHORIZE_CONFIRM_PACKET_REVIEW` opens packet review only; `SELECT_NONE` immutably closes the recipe. |
| **P1 / T3.2 S4 whole-game screen** | Release Mini from S3a, create the one fresh admission/receipt and launch reviewed v2 | One 2,048-cluster three-arm whole-game aggregate versus live report-LCB and matched null, with a terminal screen verdict | Exact `cad3992` / `17036e63…1385`, Claude PASS `51a864c`, one launch only. PASS may open a separately frozen confirmation packet; SELECT NONE closes v2. No retry or promotion. |
| **P1 / T3.3 H0 bounded design** | Obtain independent delta review of bounded v3 | One external PASS/HOLD marker for packet `4d3f0a35…8cc3c`, including caps, folds, continuation and work ceiling | PASS authorizes score-free controller implementation only. HOLD requires a new version before implementation. No counterfactual outcomes. |
| **P1 / T3.4 H0 controller** | After T3.3 PASS, implement and test the immutable one-shot controller | One score-free controller packet binding exact inputs, candidate source/survival counters, 30-world selection, disjoint 300-world reports, refusals and terminal verifier | Independent controller PASS freezes the T4.1 execution candidate. T3 stops before execution. |
| **P1 / T3.5 Teacher Stage-C contract** | Rebind the 2,048-state design to executable H0 v3, then review it | One frozen Stage-C-v3 design packet plus external PASS/HOLD marker; it must name split quotas, scan windows, label budgets, parent identities and refusal counters | PASS makes T4.2 capture implementation legal; it does not create states or labels. HOLD returns only the named defect. |
| **P1 / T3.6 S3c exact-root feasibility** | Build the score-free natural-prefix census and one→two→three-card contract | One deal-disjoint census manifest, complexity distribution/capacity envelope, human witness appendix and immutable no-outcome launch packet | Review PASS may authorize the one-card feasibility run. Four-card work remains closed until three-card evidence passes its predeclared capacity and strength gates. |
| **P2 / T3.7 HUMAN-C1 no-traffic contract** | Complete the evidence boundary without connecting live traffic | One reviewed design/receipt schema, immutable block namespace/ledger, measured runtime identity check, candidate receipt, terminal estimator and synthetic C0 | External PASS establishes an inert launch-ready harness. A separate traffic packet and user authority are still required; evaluation logs remain training-excluded. |
| **P2 / T3.X experiment infrastructure** | Make reviewed jobs cheaper to launch correctly | One tested immutable `ExperimentSpec`/receipt boundary for code, data, policy, ballot, sampler, continuation, actor, seeds, metric, null, work, stop rule and output | Tests prove identity drift/refusal and exact reopen. Scheduling may automate reviewed work; it may not select or promote. |
| **P2 / product performance** | Keep the stronger bot pleasant under concurrent traffic | One concurrent-room p50/p95/p99 policy-latency report and pure/compiled parity record for each changed hot leaf | Tail gate passes before deployment; CPU resize remains a separate operational experiment. |

## Active T3 milestone — human-witness challenger flywheel

**Plain-English objective:** convert two observed production weaknesses into
an honest challenger and better Teacher data, without depending on a positive
S3a result.

Honest strength accounting: T1 and T2 have **not yet produced a confirmed
successor** to `mc-s0-report-lcb`. T1 certified the Teacher/evaluator and T2
has produced mechanism evidence plus several negative or bounded results. The
next strength milestone must spend that machinery on a frozen challenger and
freshly confirm it against report-LCB; another readiness packet alone is not a
bot-strength result.

Bot-vs-bot proof is the reproducible engineering filter, not the destination.
The product destination is a challenger that first improves over the live
champion against the same blinded human cohort and then posts positive absolute
utility against a named experienced-human cohort. T3 prepares that challenger,
its evidence-grade data loop and the HUMAN-C1 harness; it does not claim human
superiority from offline logs.

T3 is complete only when the required outputs below are terminal:

| output | milestone result | T3 exit condition |
|---|---|---|
| **T3.1 S3a verdict** | A verified structured-bury screen result | Terminal verifier returns once; positive result has a frozen externally reviewed confirmation packet, negative result has an immutable closeout. |
| **T3.2 S4 whole-game evidence** | Natural-traffic point-banking result rather than the existing exact-state witness only | The reviewed 2,048-cluster screen has launched and either terminally selected none or produced a frozen next packet. T3 does not require confirmation or promotion. |
| **T3.3 H0-v3 design** | A bounded, executable human/model proposal experiment | External PASS on exact packet `4d3f0a35…8cc3c`; no outcome is required. |
| **T3.4 H0 controller** | Reproducible machinery for one future counterfactual run | Score-free controller packet frozen and externally passed, with candidate source/survival, fold, work and refusal accounting. T3 does not execute it. |
| **T3.5 Stage-C-v3 contract** | A reviewed recipe for creating the first stronger-Teacher asset | Frozen packet bound to executable H0-v3 and external PASS. No state capture, label or training is implied. |
| **T3.6 S3c feasibility asset** | A bounded small-endgame path after S3b's four-card failure | Score-free natural-prefix census and reviewed one→two→three-card exact-root packet. No strength outcome is required. |
| **T3 data/evaluation boundary** | Human evidence can diversify proposals without contaminating final evaluation | `human_v8` remains provenance-verified; DESIGN/AUDIT and future HUMAN-C1 traffic are excluded from model-selection REPORT and training as declared. |

T3-support work—HUMAN-C1 launch hardening, generic experiment infrastructure
and production latency—is valuable in parallel but does not silently expand
the T3 exit gate.

The exact active `/goal` is recorded in `HANDOFF_ACTIVE.md`. It forbids
unreviewed strength compute, training, promotion and production changes.

### Today's concrete exits

1. Preserve S3a until one terminal verifier verdict; do not spend its sealed
   evidence twice.
2. **T3.2 packet PASS / launch queued:** S4 full-game v2 is already frozen at
   `17036e63…1385` and independently passed. Do not create its admission or
   launch while S3a owns Mini; release of Mini opens exactly one screen.
3. **T3.3 open review:** Claude passed H0 v2's executable V11/live-parent
   repair at `9fdb67a`, but v2 was superseded before controller work because
   its candidate cap, continuation and output semantics remained ambiguous.
   Review bounded v3 exact `d6214ce` / `4d3f0a35…8cc3c` now. PASS opens T3.4
   controller implementation only.
4. **T3.4/T3.5 code while compute runs:** after H0-v3 PASS, implement and freeze
   the score-free H0 controller; then rebind and freeze Stage-C-v3 for review.
   Neither step may execute counterfactuals, capture states, label or train.
5. **T3.6 code while compute runs:** produce the S3c score-free prefix census
   and bounded one→two→three-card exact-root packet. Do not turn the census into
   a hidden strength screen.
6. Keep Mini on the long reviewed S3a job and use Air for bounded reviewed
   work only. Idle compute is not a reason to invent an unregistered run.
7. Keep the next real product gate as candidate-versus-champion performance
   against the same blinded human cohort, followed by an absolute experienced-
   human benchmark. Bot Elo and site-average win rate remain diagnostics.

## T4 milestone — first stronger-Teacher challenger

T4 is the first milestone whose required output is a newly trained policy and
an online strength result. It does not close merely because its pipelines or
reviews pass.

| output | concrete artifact | terminal gate |
|---|---|---|
| **T4.1 H0 outcome** | One verified counterfactual bundle over the frozen 384 DESIGN / 128 AUDIT plays and 36/9 buries, with action-source survival and paired human/model/champion utilities | Run the independently passed controller once. Publish all refusals; partial work cannot publish utility. Classify which proposal sources survive rather than treating human agreement as strength. |
| **T4.2 Stage-C dataset** | Exactly 2,048 accepted replayable states—1,024 DESIGN, 512 CALIB, 512 untouched REPORT—with 1,920 play and 128 bury rows, rejection counters, action unions and named label provenance | Capture and label only under the reviewed Stage-C-v3 controller. Hash the dataset/manifest; no training begins if quotas, independence or label budgets drift. |
| **T4.3 seeded models** | At least eight seeds of separate play-ranking and calibrated signed-outcome heads, with bury modeled separately, plus state-count learning curves | Choose architecture/hyperparameters on DESIGN and one frozen recipe/checkpoint rule on CALIB. Training seed variance is part of the result; no single lucky seed advances. |
| **T4.4 untouched Teacher gate** | One REPORT-open result for the frozen recipe: per-surface regret/coverage/calibration and comparison with the live Teacher baseline | Open REPORT once. PASS freezes exactly one bounded proposal/ranking challenger; failure is classified as data, target, capacity or composition rather than silently retuned on REPORT. |
| **T4.5 whole-game challenger screen** | One fresh paired screen of the frozen challenger versus live `mc-s0-report-lcb` and a same-budget random/null arm | Positive clustered utility against champion and null opens confirmation-packet review. SELECT NONE closes this exact challenger while preserving the diagnosed failure and reusable data. |
| **T4.6 scale decision** | Either a reviewed 10k/50k collection packet or an immutable no-scale closeout | Scale only if T4.3 learning curves, T4.4 REPORT and T4.5 online behavior show the intended signal. More data is not the default response to a failed mechanism. |

Parallel **S3c** outputs one-/two-/three-card exact-root results and, if they
pass, a privileged diagnostic target for a distilled endgame head. It may
improve late play directly, but it cannot leak perfect information into the
public-policy Stage-C labels.

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

1. **bounded v3 review open:** V2 repaired the executable identity and passed
   that delta at `9fdb67a`, but was superseded before controller work. Obtain a
   design PASS for exact bounded v3 (`d6214ce`, packet
   `4d3f0a35…8cc3c`);
2. use the connected-component boundary honestly: the three-player/78-deal
   component is DESIGN, the separate one-player/28-deal component is AUDIT,
   and the three tiny components (three players/five deals) are RESERVE. This
   corpus cannot support a credible three-way player+deal-disjoint REPORT;
3. **done:** select 384 DESIGN plus 128 AUDIT rows, cap repeated decisions at
   eight per deal, include every late/off-ballot row, and balance lead/follow,
   role and depth;
4. only after H0-v3 PASS, implement a score-free controller that unions the
   bounded production ballot with the actual human action, one V11 proposal
   and one matched-random proposal; bind fixed common-world and disjoint-report
   work, and refuse execution until its own review PASS;
5. report proposal-source membership and post-selection survival,
   human-minus-champion paired utility, continuation ranking flips and
   per-player/per-surface heterogeneity. Do not report undefined “candidate
   recall” without a complete named relevant-action universe;
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

The current inert seam is deliberately short of that contract. It can validate
canonical, short-lived consent assertions against the exact reviewed design,
derive a hidden complementary arm, reserve a pair/block slot once and reopen a
registry policy from declared receipt fields. It does **not** yet authenticate
the consent issuer to a site account, measure the Git/image actually executing,
prevent an operator from deleting a reservation ledger, or constrain
caller-selected block IDs to a reviewed namespace. Those are launch blockers,
not wording details; none of the current helpers grants human traffic.

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
