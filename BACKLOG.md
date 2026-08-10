# Backlog

Last re-derived: 2026-08-10 16:16 EDT.

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
- **S4:** the point-banking mechanism passed both exact-state testing and its
  fresh full-game screen. Treatment-minus-live was
  `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment and matched
  null were identical and null-minus-live was zero. Preserve the PASS.
  The old 8,192-cluster confirmation remains too expensive at `365.592`
  fleet-hours / `45.699` max-shard hours. A cheaper fixed replication is now
  externally source-passed at `fb6ec1a`: all 2,048 treatment/champion clusters
  remain, while the exact-null control becomes a balanced 256-cluster sentinel.
  Its 8-cluster score-free preflight passed and projected 61.853 fleet-hours;
  frozen packet `b239b849…ab76b` now needs review before any outcome work.
- **Human corpus / H0:** reviewed `human_v8` contains 2,830 plays and 45 buries.
  The one authorized H0-v3 diagnostic ran, but only 555/557 rows completed;
  two score-free refusals forced terminal
  `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. Do not retry or mine partial
  utilities. No human-derived proposer enters Stage C; V11 survives only as
  its separately frozen bounded proposal source.
- **Teacher Stage C:** v3–v7 bought exact phase, hand-order, final-trick and
  split-safe capture semantics; state set `c7a769c4…e8e1c` and verifier
  `143fb2db…4adb` remain externally passed. Label v1 then exposed a different
  statistical defect: eight consumed shards produced two complete and six
  refused because v1 discarded repeated realized worlds. No aggregate or
  partial utility is usable, and its other eight slots may never run. Fresh
  iid-with-replacement source `8a202e9` retains posterior mass and validates
  duplicate/overlap telemetry. Capacity-v2 then terminated before sampling:
  Codex launched from its own marker and bare Mini Python lacked NumPy, so all
  32 V11 loads refused with zero candidate worlds, sampler attempts or retained
  outcomes. Fresh v3 `167feab` then passed external packet review and its one
  Mini probe: 32/32, exact 147,384 candidate-worlds, zero refusals/outcomes and
  result `e2eea8c4…d32d4`. External result review now gates the label packet.
- **S5 replay:** Claude passed PR #4 head `2351b36`, including the required
  lower-ranked-but-equal-point negative fixture and red `<`→`<=` mutation.
  One deterministic score-free census freeze is eligible later; no census,
  treatment or strength run exists.
- **Learners:** V11 direct-v2, Direct-Q, O0 and O0-v2 all selected none under
  their registered gates. They remain diagnostics, not deployable policies.
- **Capacity:** v1 result `111092b7…cee0` remains a valid terminal sizing
  artifact but did not target late small-support states. V2 is terminal no-use
  at result `64fdda5f…4cf2`; it measured an environment omission, not sampler
  capacity. Mini is idle at capacity-v3 result review. Air is separately idle
  at S4 packet `b239b849…ab76b` review after a score-free preflight PASS.
  Capture, label-v1 and capacity-v2 consumed slots may never rerun.
  HUMAN-C1 remains parked until a challenger first beats report-LCB.

## NOW — output ledger ordered by value

An item closes only when its named artifact and terminal gate both exist.
Passing a design review authorizes the next bounded step; it is not the
scientific output of that step.

| priority / milestone | strategy and problem, in plain English | progress so far and what's left, in plain English | next work | required output | exact exit gate |
|---|---|---|---|---|---|
| **DONE / T4.2 capture + state set** | Mine a balanced set of ordinary and hard decisions where a stronger Teacher can reveal choices the live bot misses. | **Complete and externally passed.** V7 has one consumed receipt, 24/24 fresh shards, exact 2,048-state freeze, clean full replay and independent population/digest review. **Left:** none; preserve immutable assets. | No new compute | Exactly 1,024 DESIGN + 512 CALIB + 512 untouched REPORT states, including 1,920 play and 128 bury rows | Satisfied by reviewed state set `c7a769c4…e8e1c` and verifier `143fb2db…4adb`; no retry, pooling or extension. |
| **P0 / T4.2 labels** | Price every candidate with a stronger, explicitly bounded Teacher so the learner receives counterfactual ranking signal rather than another imitation label. | **V1/v2 terminal no-use. V3 capacity PASS:** result `e2eea8c4…d32d4`, 32/32, exact 147,384 worlds, zero refusals/retained outcomes; projected labels 1.640 fleet-hours. **Left:** Claude result PASS, fresh label-packet review, 16 complete shards and reviewed aggregate. | Externally review capacity-v3 result; freeze nothing before PASS | Complete candidate-level labels with correct posterior mass plus exact fold, continuation, work and refusal provenance | Every row and aggregate reopens; underfill, parent/runtime drift or budget breach terminally holds without partial utility. V1/v2 may never continue or aggregate. |
| **P0 / T4.3 seeded models** | Learn a stable ranker and calibrated outcome signal from the new Teacher rather than selecting one lucky checkpoint. | Capacity-v3 head `167feab` descends from the integrated iid-v2 source. Its isolated Mini environment now has exact Python 3.14.6, NumPy 2.5.1 and Torch 2.13.0; the model/training/REPORT slice passes 49/49 there. No checkpoint or REPORT look exists. **Left:** complete/review v2 labels, freeze/review training packet, then 48 play/bury × eight-seed × 25/50/100% cells using DESIGN/CALIB only. | Mini runs at most eight cells concurrently after reviewed labels and training packet; Air remains isolated to S4 | Eight seeds per surface/head family plus state-count learning curves, seed dispersion and one frozen CALIB selection | No single seed advances. The full-data cohort must meet the predeclared stability/calibration gate before REPORT opens. |
| **P0 / T4.4 untouched REPORT** | Ask once on unseen states whether the frozen learner improves Teacher choice/regret and calibration before paying for games. | Integrated `42e1726` routes both REPORT parent reads through the same exact-hash/source validator; REPORT has never opened. **Left:** wait for one DESIGN/CALIB selection, freeze/review exact evaluator assets, then consume REPORT once. | Later evaluate only the selected surface/head/epoch cohort | One 512-state REPORT result with ranking regret/coverage and signed-outcome calibration against the live baseline | Exactly one capability passes the frozen REPORT gate or the generation selects none; no REPORT retuning or second look. |
| **P0 / T4.5 composed challenger** | Let the model focus fresh report-LCB search on one Teacher-supported challenger, while a matched random proposal tells us whether the learned ranking—not merely narrowing the ballot—adds strength. | Integrated `42e1726` retains `68e351b` composition behavior and the prior 300-play/50-bury parity result while making the full parent chain executable. No model, packet or run exists. **Left:** later packet/source review, then after a REPORT passer score-free capacity and one fresh screen. | Execute only from the single REPORT passer | One mirrored treatment/null/champion result against `mc-s0-report-lcb` | Treatment must have positive one-sided utility LCB versus both champion and null; null must remain compatible with champion. PASS opens confirmation-packet review only. |
| **DONE / T4.1 H0 diagnostic** | Test whether human or V11 proposals survive fair counterfactual pricing before admitting them into the Teacher curriculum. | **Terminal no-use.** The one run completed 555/557 rows; two score-free refusals forced `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. **Left:** none for this exact diagnostic. Never retry or mine partial utilities. | Preserve the refusal and omit H0-derived rules | Immutable aggregate `84ef4400…196c` / internal `c314a2e1…6630` | Satisfied as a negative operational result. Stage C admits no human-derived proposer; V11 remains only its separately frozen bounded source. |
| **P0 parallel / S4 fixed replication** | Check whether point banking's first positive whole-game result repeats independently without spending 365.6 fleet-hours on a redundant full null arm. | **Screen/source/preflight PASS.** Score-free preflight `a89a4498…69` passed every criterion and projected 61.853 fleet-hours / 7.732 max-shard hours. Packet `b239b849…ab76b` has zero outcome work. **Left:** Claude packet PASS, then one fixed Air run. | Externally review the frozen packet; Mini remains reserved for T4 | Independent fixed-look replication plus exact null-sentinel control | LCB95(treatment−champion)>0 over all 2,048 clusters, null equals champion on all 256 sentinel clusters, exact dose/work; no retry/extension or automatic deploy. |
| **P1 / S6 shuai-pai sourcing** | Whenever a legal lead can be played as shuai-pai, make at least one such choice visible so search can price success, failed-throw and ruff risk instead of silently excluding the tactic. | Draft PR #19 head `cfa5a53` now covers the KESP actions plus natural early/mid/late states. A late trump-only witness is red under v1 and green under v2; append-only union preserves the literal live ballot and candidate zero. 11 focused / 58 broader tests pass. **Left:** external semantics review and an equal-work packet/screen after T4's current gate. | Review source after the immediate label gate, without launching compute | Public-only, lead-only, deterministic ≤8 additions with ≥1 legal shuai whenever possible, unioned with literal candidate zero plus same-work control | Source PASS authorizes packet design only; missing an available shuai in any phase fails the source gate, and no source PASS alone authorizes a screen. |
| **P1 / S5 replay census** | Determine whether the bot really donates points to lost tricks when a cheaper legal discard exists, instead of trusting observational log correlations. | Exact fixture boundary at `2351b36` passed, including the equal-point negative witness. **Left:** one deterministic score-free census freeze when it does not compete with T4. | Freeze/review census later | Trigger/refusal counts and replayable identifier-free witnesses | Census may open treatment design only; it cannot enter Stage C or claim strength automatically. |
| **PARKED / HUMAN-C1** | Ultimately prove the challenger is better for people, not merely against bots. | Inert harness only. **Left:** account binding, runtime identity, immutable blocks, candidate receipt, synthetic C0 and estimator. | Resume only after a challenger beats report-LCB in confirmation | Reviewed blinded candidate-versus-champion human test | Separate traffic packet and explicit user authority required. |

## COMPLETE T3 milestone — human-witness challenger readiness

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

T3 closed on 2026-08-09 only after every required output below became terminal:

| output | what question this answers, in plain English | progress so far and what's left, in plain English | milestone result | T3 exit condition |
|---|---|---|---|---|
| **T3.1 S3a verdict** | Do strategy-aware point/void kitty choices improve the complete bot, or did they only look good on selected bury states? | **Complete: SELECT NONE.** The selected-state signal did not survive full games. **Left:** none; this exact recipe is closed. | Verified aggregate `20609613…271f` and final `32156d79…c9ff` | Satisfied by immutable closeout; no confirmation, retry or tuning. |
| **T3.2 S4 whole-game evidence** | Does point banking still help at its natural frequency after accounting for later control, rather than only on hand-picked trigger states? | **Complete: terminal PASS.** Treatment-minus-live `+0.086914 +/- 0.056166`, LCB `+0.030748`; treatment and matched null were identical. **Left in T3/T4:** none; confirmation is a separately authorized future milestone. | Natural-traffic point-banking result rather than the existing exact-state witness only | Satisfied by the verified full-game screen. No confirmation, promotion or deployment follows automatically. |
| **T3.3 H0-v3 design** | Can we test human and learned-model ideas fairly without assuming they are correct or giving them unlimited candidate/work advantage? | **Complete:** bounded v3 reproduces on both machines and Claude passed it at `239f13c`. **Left:** none for this row; no outcomes were computed. | A bounded, executable human/model proposal experiment | Satisfied by external PASS on exact packet `4d3f0a35…8cc3c`. |
| **T3.4 H0 controller** | Can that counterfactual experiment actually proceed after its one-shot admission? | **T3 machinery passed; later T4 execution terminally refused aggregate utility at 555/557.** Two score-free row refusals correctly prevented partial evidence. **Left:** no retry; preserve the no-use result. | Reproducible machinery plus an honest terminal refusal | T3 controller gate was satisfied; the later T4 diagnostic admits no human-derived proposer. |
| **T3.5 Stage-C-v3 contract** | Do we have an executable recipe for generating training examples that challenge the live champion instead of repeating ordinary heuristic self-play? | **Complete / external PASS / zero states.** Packet `b60c4298…7b18` binds the passed 2,048-state design to passed H0-v3/S3c-v2 without changing the estimand; external marker is at `cb9471b`. **Left:** none in T3. | A reviewed recipe bound to executable human-proposal and conditional endgame controllers | Satisfied. No state capture, label or training is implied. |
| **T3.6 S3c feasibility asset** | Can sampled exact search work reliably on tiny natural endgames and then grow one card at a time? | **Complete / external PASS / zero solver work.** Exact S3c-v2 `cafbee43…f23e` passed at `205b6af`. **Left:** none in T3. | A bounded executable small-endgame path after S3b's four-card failure | Satisfied. The later mechanics run cannot claim strength. |
| **T3 data/evaluation boundary** | Can human play diversify the bot's ideas while keeping both model selection and the eventual human A/B test honest? | `human_v8` is provenance-verified and split; 25 off-ballot actions and 22/45 point-bearing buries are retained as proposal evidence. **Left:** keep these rows out of REPORT and enforce structural exclusion for future human A/B traffic. | Human evidence can diversify proposals without contaminating final evaluation | `human_v8` remains provenance-verified; DESIGN/AUDIT and future HUMAN-C1 traffic are excluded from model-selection REPORT and training as declared. |

T3-support work—S5 bot-decision replay, HUMAN-C1 launch hardening, generic
experiment infrastructure and production latency—is valuable in parallel but
does not silently expand the T3 exit gate.

The exact active `/goal` is recorded in `HANDOFF_ACTIVE.md`. It forbids
unreviewed strength compute, training, promotion and production changes.

### T3 closeout checkpoints and later terminal updates

1. **T3.1 closed:** S3a terminally selected none at aggregate
   `20609613…271f` / final `32156d79…c9ff`. Preserve the negative; do not retry,
   tune, confirm or pool it.
2. **T3.2 terminal PASS:** S4 full-game v2 produced
   treatment-minus-live `+0.086914 +/- 0.056166`, LCB `+0.030748`.
   Confirmation is preserved as eligible packet review but is not launched.
3. **T3.3 closed PASS:** Claude passed bounded H0 v3 exact `d6214ce` /
   `4d3f0a35…8cc3c` at marker `239f13c`. This opens T3.4 controller
   implementation only; it does not authorize outcomes.
4. **T3.4 machinery PASS; T4 diagnostic no-use:** H0-v3 later stopped at
   555/557 and published no aggregate utility. Never retry or mine partial rows.
5. **T3.5 closed PASS:** Stage-C rebind source `7018f36` / packet
   `b60c4298…7b18` passed at `cb9471b` with all seven curriculum commitments
   unchanged. Capture, labels and training remain T4 work.
6. **T3.6 closed PASS:** S3c-v2 packet `cafbee43…f23e` passed at `205b6af`;
   no mechanics receipt or solver session exists.
7. **S5 boundary fixture closed PASS:** PR #4 head `2351b36` pins the
   lower-ranked-but-equal-point non-trigger. One score-free census freeze is
   eligible later; it was not required for T3.
8. Mini and Air are idle pending iid-v2 capacity-packet review. On PASS, Mini
   owns one short outcome-discarding capacity run; its result and a later fresh
   label packet each require review before the 16-shard label run. Air is
   staged at iid-v2 `8a202e9` and waits for complete reviewed labels plus a
   reviewed training packet before the 48-cell matrix. Idle compute is not a
   reason to invent an unregistered strength run.
9. Keep the next real product gate as candidate-versus-champion performance
   against the same blinded human cohort, followed by an absolute experienced-
   human benchmark. Bot Elo and site-average win rate remain diagnostics.

## T4 milestone — first stronger-Teacher challenger

T4 is the first milestone whose required output is a newly trained policy and
an online strength result. It does not close merely because its pipelines or
reviews pass.

The canonical output-by-output status, plain-English motivation, remaining
work and exit gate is the `NOW` table above. T4 closes only after one frozen
Stage-C capability passes untouched REPORT and then clears the fresh
treatment-versus-live and treatment-versus-null whole-game gates. A negative
REPORT or screen is still a valid terminal T4 result for the exact generation,
but it is not a stronger policy; scaling remains withheld unless learning
curves, REPORT and online play all support the intended signal.

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
- **S4 point-banking continuation:** both the exact-late mechanism screen and
  the fresh natural-traffic whole-game screen passed. The latter measured
  `+0.086914 +/- 0.056166` versus the live champion, LCB `+0.030748`, with an
  exactly identical matched null. Preserve the recipe and result; a cheaper
  sequential independent-confirmation design is a future milestone, not part
  of T4.
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

## Teacher Stage-C v3 packet contract

The Teacher audit says cheap and N=30 choices are faithful on its 64 ordinary
states, but the N=30 boundary diagnostic was weaker (`0.1421` upper bound).
Stage C should therefore spend compute on the hard tail rather than relabeling
ordinary states horizontally. “Hard tail” is not shorthand for openers: early
leads are one protected stratum, alongside follow, bury, late play, both roles,
uncertainty/disagreement, the two established human-observed point mechanisms
and replay-verified S5 point-protection states if that gate passes.

Frozen source `20bdb95` and asset `1a29418` now bind packet
`f213314a…3b4`. It is deliberately a finite design rather than a request for
recursive report-LCB search at every future node:

- exactly 1,024 DESIGN / 512 CALIB / 512 untouched REPORT states, including
  1,920 play and 128 bury rows, with protected role/action/depth strata;
- at most 20 play and 33 bury candidates;
- ordinary anchors evaluated on two disjoint 256-world folds;
- hard-tail candidates selected on 64 common worlds, then only the fixed
  selection winner versus candidate zero reported on 300 fresh worlds;
- a deeper 128+600 diagnostic audit and a hard all-optional ceiling of
  10,494,720 candidate-world rollouts;
- `HeuristicBot` continuation and **zero recursive MC continuation rollouts**;
  the expensive work is deeper root comparison, not search calling search;
- raw H0 actions excluded from the fresh population. Only DESIGN-supported
  proposal rules may later enter, and H0 AUDIT cannot tune them;
- S4, S3c and S5 inputs conditional on their own terminal gates; and
- explicit zero-state/zero-label/zero-training authority before review.

Plain English: Stage C keeps broad routine coverage, spends most extra compute
on decisions where the live bot is uncertain or missing a plausible idea, and
protects a fresh exam set. External PASS/HOLD is still required. A PASS would
authorize only implementation of a capture/controller, not the dataset itself.

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
5. **done — controller review PASS:** source `6977dbb`, packet
   `3f68dc6e…7fcf` now bind the bounded production ballot plus actual human,
   V11 and matched-random proposals, fixed common-world/disjoint-report work,
   strict runtime and deletion-proof one-shot admission. T4 may create one
   diagnostic receipt; no outcome exists yet;
6. after that one T4 execution, report proposal-source membership and post-selection survival,
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
