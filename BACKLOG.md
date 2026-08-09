# Backlog

Last re-derived: 2026-08-09 17:34 EDT.

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
- **S3a:** the structured-bury mechanism improved its selected 512-state
  objective, but the fresh 2,048-cluster full-game screen terminally returned
  **SELECT NONE**: structured-minus-champion `+0.0464`, LCB `-0.0041`.
  Aggregate `20609613…271f` and final `32156d79…c9ff` verified. The consumed
  stream is closed—no retry, tuning, confirmation or pooling. A revisit would
  require a separately preregistered fresh larger design and is not queued.
- **S4 live strength compute:** the point-banking mechanism passed exact-state
  testing in both roles (`+5.156` points; LCB `+3.029`). Its separately
  reviewed full-game v2 screen is now running on Mini under exact `cad3992`,
  packet `17036e63…1385`, admission `1d99bb55…bdbf` and receipt
  `20a420d2…5cc`. Outcomes stay sealed until one terminal verification.
- **Human corpus / H0:** reviewed `human_v8` contains 2,830 plays and 45 buries
  from the exact Fly snapshot. The bounded v3 design passed, and exact producer
  `931f504` plus asset `ff277b4` now freeze a score-free controller over all
  557 selected rows at packet `13d9a97f…61fc`. It replayed every row while
  sampling **zero worlds** and computing **zero outcomes**. Independent
  controller review is the only remaining T3.4 gate; execution belongs to T4.
- **Teacher / endgame:** Stage-C v2 is held because it binds obsolete H0;
  rebind/freeze v3 only after the H0 controller review. Claude independently
  passed the S3c 768-root natural-prefix curriculum at marker commit `084ba7e`.
  That opens score-free one-card controller implementation only. Neither lane
  has produced labels, a checkpoint, a solver result or a strength claim.
- **Learners:** V11 direct-v2, Direct-Q, O0 and O0-v2 all selected none under
  their registered gates. They remain diagnostics, not deployable policies.
- **Capacity:** Mini is dedicated to sealed S4; Air is free for exact review
  reproduction and bounded coding tests. HUMAN-C1 infrastructure is parked
  until a challenger first beats report-LCB.

## NOW — output ledger ordered by value

An item closes only when its named artifact and terminal gate both exist.
Passing a design review authorizes the next bounded step; it is not the
scientific output of that step.

| priority / milestone | strategy and problem, in plain English | progress so far and what's left, in plain English | next work | required output | exact exit gate |
|---|---|---|---|---|---|
| **DONE / T3.1 S3a terminal** | The banker is extremely reluctant to bury points. Give it deliberate point/void/trump kitty plans and test whether that makes the complete bot win more—not merely whether individual buries look better. | **Closed SELECT NONE.** Structured-minus-champion was `+0.0464`, LCB `-0.0041`: a near miss, not a PASS. **Left:** none in T3; preserve diagnostics. A revisit must be a separately preregistered fresh larger design. | No reuse of the consumed stream | Verified aggregate `20609613…271f` and final `32156d79…c9ff` | Satisfied. No retry, tuning, confirmation, pooling or promotion. |
| **P0 / T3.2 S4 whole-game screen** | Current rollouts usually win a trick with the cheapest card and can miss free 5/10/K points. Let simulated players bank a point card when they can still retain higher control, then test whether that local improvement survives a whole round. | The targeted state test passed in both roles (`+5.156` points, LCB `+3.029`). The reviewed 2,048-cluster full-game screen is running on Mini and outcomes are sealed. **Left:** terminally verify once, then close or freeze a confirmation packet. | Count/status monitoring only until all shards stop | One verifier-authenticated three-arm whole-game verdict versus live report-LCB and matched null | Exact `cad3992` / `17036e63…1385`, admission `1d99bb55…bdbf`, receipt `20a420d2…5cc`. PASS may open confirmation-packet review; SELECT NONE closes v2. |
| **P1 / T3-support S5 replay gate** | Live-loss mining suggests bots may give points to an enemy-owned trick even when a cheaper legal discard exists. First prove that exact situation exists and that today's champion still makes it; do not patch from an observational aggregate. | The original “bots feed nearly twice as much” claim was withdrawn after per-seat normalization. The narrower loss pattern remains interesting, but baseline follow logic already tries to avoid points and MC already offers both point-avoiding and point-seeking follows. **Left:** replay bot-seat decisions with full legality and current-policy checks. | Build a score-free, source-hash-bound census of losing-follow decisions from the frozen Fly snapshot | Exact trigger/refusal counts, identifier-free witness digests, legal lower-point alternatives, ballot membership and current champion/rollout reproduction; then either close the hypothesis or freeze an S5 design | No treatment or strength run until replay proves the avoidable action exists and isolates whether the defect is sourcing, ranking or continuation. Human-loss rows remain DESIGN/DEV only. This support lane does not expand T3's exit gate. |
| **P1 / T3.3 H0 bounded design** | Humans and V11 sometimes suggest moves outside the production bot's habits. Define a finite, fair experiment that evaluates those moves instead of blindly copying the human or flooding the ballot. | **Closed PASS.** V1 had a bad model identity; V2 repaired identity but left work/candidate semantics vague. Claude independently passed bounded v3 at marker `239f13c`. **Left:** none for the design; hand its exact contract to T3.4. | Preserve exact packet `4d3f0a35…8cc3c` and review marker `239f13c` | One external PASS marker binding caps, folds, continuation and the 1,329,210-work ceiling | Satisfied. The PASS authorizes score-free controller implementation only—no counterfactual outcomes. |
| **P0 / T3.4 H0 controller** | Turn the H0 paper experiment into a reproducible program so every human/model/random proposal is judged on intended shared worlds and partial failures cannot masquerade as results. | **Implementation/freeze complete.** All 557 rows replay score-free; tests pass 30/30; packet `13d9a97f…61fc` binds finite work and zero outcomes. **Left:** independent controller PASS/HOLD only. | Review exact producer `931f504` and asset `ff277b4`; do not execute | One external marker covering folds, utility, work/refusal accounting, replay and one-shot authority | PASS freezes the T4.1 execution candidate. T3 stops before execution. HOLD returns only the named defect. |
| **P1 / T3.5 Teacher Stage-C contract** | Earlier Teachers mostly repeated normal heuristic self-play. Build a better curriculum that keeps cheap labels for routine choices but spends report-LCB-quality work on uncertainty, novel proposals, bury, point play and late-game states. | Stage B established that cheap labels match expensive labels on ordinary states. The old Stage-C draft points to H0 v1 and leaves proposal/work semantics vague; no Stage-C dataset exists. **Left:** rewrite it around executable H0 v3, freeze it and obtain review PASS. | Rebind the 2,048-state design to executable H0 v3, then review it | One frozen Stage-C-v3 design packet plus external PASS/HOLD marker; it must name split quotas, scan windows, label budgets, parent identities and refusal counters | PASS makes T4.2 capture implementation legal; it does not create states or labels. HOLD returns only the named defect. |
| **P1 / T3.6→T4 S3c exact-root feasibility** | Four-card exact search exploded past its node cap. Start with naturally reached one-card endings, then two and three, proving capacity and useful choices at each size before attempting the hard case again. | **T3 design PASS.** The real 768-root census/curriculum reproduces on Mini and Air; one-card is mechanics-only while two/three cards have bounded real branching. Claude passed it at `084ba7e`. **Left:** implement/freeze and independently review the score-free one-card capacity controller; no solver run is authorized. | Implement the controller under the exact passed packet; do not compute outcomes | One immutable one-card controller packet with capacity/work/refusal/replay accounting | External controller PASS may authorize one score-free capacity execution. Two-/three-card and all strength work remain closed behind later gates. |
| **PARKED / HUMAN-C1 no-traffic contract** | Bot-vs-bot wins are necessary but do not prove people get a stronger opponent. Eventually compare a confirmed challenger with production against the same blinded human cohort without leaking evaluation games into training. | An inert consent/arm/ledger seam and the people-facing estimand exist; no traffic is authorized. **Left later:** account binding, measured runtime identity, immutable reviewed blocks, candidate receipt, synthetic C0 and estimator. | Preserve the seam; resume only after a challenger beats report-LCB in confirmation | A reviewed launch-ready harness tied to a real candidate | Not part of T3 completion. A separate traffic packet and explicit user authority remain required. |
| **P2 / T3.X experiment infrastructure** | Too many runs have failed because code, data, seeds or authority did not match the reviewed experiment. Put the whole experiment in one immutable receipt so launches become routine and falsifiable. | Several recent runners now have strong one-off receipts and fail-closed validators. **Left:** extract and test one shared `ExperimentSpec` boundary rather than rebuilding the contract for every lane. | Make reviewed jobs cheaper to launch correctly | One tested immutable `ExperimentSpec`/receipt boundary for code, data, policy, ballot, sampler, continuation, actor, seeds, metric, null, work, stop rule and output | Tests prove identity drift/refusal and exact reopen. Scheduling may automate reviewed work; it may not select or promote. |
| **P2 / product performance** | A stronger bot still feels weak if every move pauses the room. Measure concurrent tail latency and compile only proven hot paths without changing decisions. | Release 17 moved speculative search off the room event loop and is live; single-policy cost is known. **Left:** measure concurrent p50/p95/p99 and prove semantic parity for the next compiled hot path before deploying it. | Keep the stronger bot pleasant under concurrent traffic | One concurrent-room p50/p95/p99 policy-latency report and pure/compiled parity record for each changed hot leaf | Tail gate passes before deployment; CPU resize remains a separate operational experiment. |

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

| output | what question this answers, in plain English | progress so far and what's left, in plain English | milestone result | T3 exit condition |
|---|---|---|---|---|
| **T3.1 S3a verdict** | Do strategy-aware point/void kitty choices improve the complete bot, or did they only look good on selected bury states? | **Complete: SELECT NONE.** The selected-state signal did not survive full games. **Left:** none; this exact recipe is closed. | Verified aggregate `20609613…271f` and final `32156d79…c9ff` | Satisfied by immutable closeout; no confirmation, retry or tuning. |
| **T3.2 S4 whole-game evidence** | Does point banking still help at its natural frequency after accounting for later control, rather than only on hand-picked trigger states? | **T3 launch condition satisfied.** Exact-state mechanism and packet passed; one 2,048-cluster screen is running on Mini. **Left for science:** one terminal verifier verdict after shards stop. | Natural-traffic point-banking result rather than the existing exact-state witness only | T3 required launch or terminal resolution; launch is satisfied. Outcomes remain sealed and promotion remains closed. |
| **T3.3 H0-v3 design** | Can we test human and learned-model ideas fairly without assuming they are correct or giving them unlimited candidate/work advantage? | **Complete:** bounded v3 reproduces on both machines and Claude passed it at `239f13c`. **Left:** none for this row; no outcomes were computed. | A bounded, executable human/model proposal experiment | Satisfied by external PASS on exact packet `4d3f0a35…8cc3c`. |
| **T3.4 H0 controller** | Can that counterfactual experiment be run once, exactly as designed, with every candidate source, fold and failure accounted for? | **Implementation/freeze complete:** producer `931f504`, asset `ff277b4`, packet `13d9a97f…61fc`; 557 rows replayed and zero worlds sampled. **Left:** independent controller review only. | Reproducible machinery for one future counterfactual run | Score-free packet receives external PASS, including source/survival, folds, work and refusal accounting. T3 does not execute it. |
| **T3.5 Stage-C-v3 contract** | Do we have an executable recipe for generating training examples that challenge the live champion instead of repeating ordinary heuristic self-play? | Stage B's ordinary-state audit passed; Stage C is still an obsolete H0-v1-bound draft. **Left:** rewrite, freeze and review v3; no capture or labels exist yet. | A reviewed recipe for creating the first stronger-Teacher asset | Frozen packet bound to executable H0-v3 and external PASS. No state capture, label or training is implied. |
| **T3.6 S3c feasibility asset** | Can sampled exact search work reliably on tiny natural endgames and then grow one card at a time, rather than jumping back to the failed four-card case? | **Complete for T3:** the 768-root census/curriculum reproduces and Claude passed it at `084ba7e`. **Left after T3:** implement/review the one-card capacity controller; no solver is authorized. | A bounded small-endgame path after S3b's four-card failure | Satisfied by the reviewed score-free natural-prefix census and one→two→three-card packet. No strength outcome was required or produced. |
| **T3 data/evaluation boundary** | Can human play diversify the bot's ideas while keeping both model selection and the eventual human A/B test honest? | `human_v8` is provenance-verified and split; 25 off-ballot actions and 22/45 point-bearing buries are retained as proposal evidence. **Left:** keep these rows out of REPORT and enforce structural exclusion for future human A/B traffic. | Human evidence can diversify proposals without contaminating final evaluation | `human_v8` remains provenance-verified; DESIGN/AUDIT and future HUMAN-C1 traffic are excluded from model-selection REPORT and training as declared. |

T3-support work—S5 bot-decision replay, HUMAN-C1 launch hardening, generic
experiment infrastructure and production latency—is valuable in parallel but
does not silently expand the T3 exit gate.

The exact active `/goal` is recorded in `HANDOFF_ACTIVE.md`. It forbids
unreviewed strength compute, training, promotion and production changes.

### Today's concrete exits

1. **T3.1 closed:** S3a terminally selected none at aggregate
   `20609613…271f` / final `32156d79…c9ff`. Preserve the negative; do not retry,
   tune, confirm or pool it.
2. **T3.2 launched:** S4 full-game v2 is running on Mini under exact
   `cad3992` / `17036e63…1385`, admission `1d99bb55…bdbf` and receipt
   `20a420d2…5cc`. Read only count/status until one terminal verify.
3. **T3.3 closed PASS:** Claude passed bounded H0 v3 exact `d6214ce` /
   `4d3f0a35…8cc3c` at marker `239f13c`. This opens T3.4 controller
   implementation only; it does not authorize outcomes.
4. **T3.4 controller frozen / review open:** exact producer `931f504`, asset
   `ff277b4`, packet `13d9a97f…61fc`; 30/30 focused tests, all 557 rows replay,
   zero worlds/outcomes. Obtain external PASS/HOLD, then rebind and freeze
   Stage-C-v3. Neither step may execute counterfactuals, capture, label or train.
5. **T3.6 design closed PASS:** exact producer `0b96fae`, asset `4fb90a1`,
   census `23632609…b52a` and packet `df102428…9eca` passed external review at
   `084ba7e`. Implement/freeze the score-free one-card capacity controller only;
   do not turn the census or controller into a hidden solver/strength screen.
6. **S5 diagnosis without a policy patch:** exactly replay the frozen human-log
   bot decisions, enumerate legal lower-point alternatives and ask whether the
   current champion/continuation reproduces the action. The corrected
   observational aggregate alone cannot authorize a treatment.
7. Keep Mini on the reviewed S4 job and use Air for exact review reproduction
   or bounded coding tests. Idle compute is not a reason to invent an
   unregistered strength run.
8. Keep the next real product gate as candidate-versus-champion performance
   against the same blinded human cohort, followed by an absolute experienced-
   human benchmark. Bot Elo and site-average win rate remain diagnostics.

## T4 milestone — first stronger-Teacher challenger

T4 is the first milestone whose required output is a newly trained policy and
an online strength result. It does not close merely because its pipelines or
reviews pass.

| output | how this could make the bot stronger, in plain English | progress so far and what's left, in plain English | concrete artifact | terminal gate |
|---|---|---|---|---|
| **T4.1 H0 outcome** | Discover which human, V11 or random novel moves are genuinely useful under fair search, so Stage C learns from supported alternatives rather than copying style. | Corpus, bounded design and score-free controller packet exist; no counterfactual world or utility has been computed. **Left:** obtain controller PASS, create one receipt, then execute once. | One verified counterfactual bundle over the frozen 384 DESIGN / 128 AUDIT plays and 36/9 buries, with action-source survival and paired human/model/champion utilities | Run the independently passed controller once. Publish all refusals; partial work cannot publish utility. Classify proposal sources rather than treating human agreement as strength. |
| **T4.2 Stage-C dataset** | Create the first clean curriculum whose hard examples and candidate moves can exceed the old heuristic Teacher while preserving routine coverage. | Split sizes and desired mixture are drafted, but zero Stage-C states are captured or labeled. **Left:** pass the repaired Stage-C-v3 contract, implement capture/labeling and freeze all 2,048 rows. | Exactly 2,048 accepted replayable states—1,024 DESIGN, 512 CALIB, 512 untouched REPORT—with 1,920 play and 128 bury rows, rejection counters, action unions and named label provenance | Capture and label only under the reviewed Stage-C-v3 controller. Hash the dataset/manifest; no training begins if quotas, independence or label budgets drift. |
| **T4.3 seeded models** | Test whether the new signal is actually learnable and stable—not merely a lucky checkpoint—using heads that match how search will consume them. | No Stage-C dataset, frozen recipe or report-LCB-trained checkpoint exists. **Left:** freeze one recipe, train at least eight seeds and measure learning curves/variance. | At least eight seeds of separate play-ranking and calibrated signed-outcome heads, with bury modeled separately, plus state-count learning curves | Choose architecture/hyperparameters on DESIGN and one frozen recipe/checkpoint rule on CALIB. Training seed variance is part of the result; no single lucky seed advances. |
| **T4.4 untouched Teacher gate** | Check on unseen states whether the frozen model ranks and values actions better before spending a full gameplay screen or tuning to its mistakes. | Not started because the dataset/models do not exist; REPORT remains planned rather than opened evidence. **Left:** select once on CALIB, then open the 512-row REPORT exactly once. | One REPORT-open result for the frozen recipe: per-surface regret/coverage/calibration and comparison with the live Teacher baseline | Open REPORT once. PASS freezes exactly one bounded proposal/ranking challenger; failure is classified as data, target, capacity or composition rather than silently retuned on REPORT. |
| **T4.5 whole-game challenger screen** | Put the learned help inside the actual search and answer the only product-relevant research question: does the composed bot beat production at equal controlled work? | No Stage-C learned challenger has passed the untouched offline gate. **Left:** compose the one frozen passer with search and run the fresh champion/null screen. | One fresh paired screen of the frozen challenger versus live `mc-s0-report-lcb` and a same-budget random/null arm | Positive clustered utility against champion and null opens confirmation-packet review. SELECT NONE closes this exact challenger while preserving the diagnosed failure and reusable data. |
| **T4.6 scale decision** | Spend large fleet compute only when more examples are likely to amplify a real signal; otherwise use the diagnosed failure to change the data, target or model. | Scaling is withheld because no learning curve or online Stage-C signal exists. **Left:** use T4.3–T4.5 evidence to authorize a 10k/50k packet or close without scaling. | Either a reviewed 10k/50k collection packet or an immutable no-scale closeout | Scale only if T4.3 learning curves, T4.4 REPORT and T4.5 online behavior show the intended signal. More data is not the default response to a failed mechanism. |

Parallel **S3c** outputs one-/two-/three-card exact-root results and, if they
pass, a privileged diagnostic target for a distilled endgame head. It may
improve late play directly, but it cannot leak perfect information into the
public-policy Stage-C labels.

## Three-lane strength plan

### Lane A — improve the search policy directly

- **S3a structured bury:** directly addressed the bot's point-shy kitty
  behavior with strategy-aware void/point/trump candidates. The 512-state
  mechanism passed, but the fresh full-game screen selected none. Close this
  policy recipe; retain its disagreements as Teacher/proposal diagnostics.
- **S4 point-banking continuation:** the exact-late mechanism screen passed in
  both roles (`+5.156` points overall, LCB `+3.029`). Preserve the frozen
  continuation-only recipe and now test natural complete-round utility against
  the live champion and a trigger-matched null.
- **S5 defensive point protection:** this is a replay hypothesis, not yet a
  mechanism. Exact replay must show that a bot used a point-bearing losing
  follow while a lower-point legal action existed, and that the live champion
  or its rollout continuation still reproduces the choice. Only then isolate
  ballot sourcing versus ranking/continuation and freeze a matched treatment.
- **Later search:** S3b-v2 is closed on its node cap. Any exact-late successor
  needs a new bound/solver hypothesis and fresh review, not a relaxed retry.

### Lane B — make a Teacher that can exceed the champion

- Mine fresh non-evaluation states from uncertainty, high paired SE,
  champion/proposer disagreement, exact-late opportunities, point-bearing
  kitty voids, point-banking winner choices and replay-verified defensive
  point-protection opportunities.
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
and level utility `+0.25`. The running full-game v2 screen now restores natural
traffic weighting and may still select none; state-level mechanism evidence is
not whole-policy strength.

## Human-loss diagnostic alignment

The August 9 loss mining is useful **DEV hypothesis generation**, with one
important correction preserved. The first comparison—48.2 bot points versus
25.4 human points sloughed into enemy-won tricks per round—was confounded by
bots occupying many more seats. Per seat-round, the descriptive rates are
roughly 19 for bots and 17 for humans, so there is no demonstrated global
“bots feed twice as much” effect.

The narrower patterns still route cleanly into the strength plan:

- point-bearing winning plays are a frequent feature of human-side wins; S4
  directly tests that winner policy and can also improve how rollouts price the
  winner's half of a point-banking/feeding interaction;
- humans bury points more often than logged bots, which validates S3a's target
  surface but does not prove any particular point bury is better;
- last-trick/kitty-control losses motivate S3c's one→two→three-card curriculum;
  cited human rounds become DESIGN witnesses, while fresh bot prefixes remain
  the formal selection population; and
- bot discards supplied a large share of points in a subset of lost defenses,
  which motivates S5 replay. It does not yet prove that a lower-point legal
  action existed or would have improved continuation value.

The source audit makes that last caveat load-bearing. `HeuristicBot` and
`SmartBot` already call `_forced_follow(..., prefer_points=False)` on losing
fallbacks, and `MCBot` already includes both point-avoiding and point-seeking
forced follows in its ballot. S5 must therefore distinguish four possibilities:
the play was forced; the safer action was missing after combination/ballot
caps; search ranked the point action higher; or the historical bot differs from
today's champion. The score-free census binds source-log hashes, reconstructs
the exact hand/trick, enumerates all legal alternatives, records point deltas
and ballot membership, and asks the current champion plus its rollout policy
to replay the state. Only a reproducible trigger may open a separately reviewed
counterfactual/treatment packet. No cited loss enters CALIB or REPORT.

## Teacher Stage-C packet contract

The Teacher audit says cheap and N=30 choices are faithful on its 64 ordinary
states, but the N=30 boundary diagnostic was weaker (`0.1421` upper bound).
Stage C should therefore spend compute on the hard tail rather than relabeling
ordinary states horizontally. “Hard tail” is not shorthand for openers: early
leads are one protected stratum, alongside follow, bury, late play, both roles,
uncertainty/disagreement, the two established human-observed point mechanisms
and replay-verified S5 point-protection states if that gate passes.

The packet must bind:

- fresh source population and deal-disjoint split assignment;
- quotas for early/mid/late, banker/non-banker, lead/follow, candidate count,
  uncertainty/disagreement, the two established human-witness mechanisms and
  a conditional replay-verified defensive point-protection cell;
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

1. **done — bounded v3 review PASS:** V2 repaired executable identity but was
   superseded before controller work. Claude passed exact bounded v3
   (`d6214ce`, packet `4d3f0a35…8cc3c`) at marker `239f13c`;
2. use the connected-component boundary honestly: the three-player/78-deal
   component is DESIGN, the separate one-player/28-deal component is AUDIT,
   and the three tiny components (three players/five deals) are RESERVE. This
   corpus cannot support a credible three-way player+deal-disjoint REPORT;
3. **done:** select 384 DESIGN plus 128 AUDIT rows, cap repeated decisions at
   eight per deal, include every late/off-ballot row, and balance lead/follow,
   role and depth;
4. separately replay **bot-seat** losing-follow decisions from the same frozen
   source logs for S5. H0 contains human actions and cannot by itself explain
   the bot mistakes surrounding those actions;
5. only after H0-v3 PASS, implement a score-free controller that unions the
   bounded production ballot with the actual human action, one V11 proposal
   and one matched-random proposal; bind fixed common-world and disjoint-report
   work, and refuse execution until its own review PASS;
6. report proposal-source membership and post-selection survival,
   human-minus-champion paired utility, continuation ranking flips and
   per-player/per-surface heterogeneity. Do not report undefined “candidate
   recall” without a complete named relevant-action universe;
7. use supported actions plus replay-verified bot-loss triggers for a
   proposal/prior head and hard-tail mining. Keep raw BC as a separately
   measured initialization/style control.

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
