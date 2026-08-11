# Backlog

Last re-derived: 2026-08-11 14:47 EDT from terminal evidence and the weekly
strategy audit.

This file owns the executable queue. `AI_POLICIES.md` owns terminal results,
`RL_PLAN.md` owns research design, `JOBS.md` owns compute, and
`HANDOFF_ACTIVE.md` owns the next review. Completed chronology belongs in the
dated files under `docs_archive/`, not in this queue.

## Two-minute state

- **Production champion:** compiled `mc-s0-report-lcb` in Fly release 17.
  Fresh RLCB-C1 confirmed `+0.338 +/- 0.068` signed levels versus `mc-strong`;
  the matched null was flat. Runtime rollback is release 16; policy rollback is
  `mc-strong`.
- **T4 has produced learned capability, but still no stronger learned bot.**
  The first protected play model lost its untouched REPORT. Expanded bury was
  positive but inconclusive on only 32 fresh rows and selected none. Expanded
  play had positive DESIGN/CALIB bounds, but its protected broad REPORT lost
  and its powered 219-state `champion_uncertainty` REPORT returned action mean
  `+0.012129`, SE `0.010109`, LCB `-0.005056`: independently reviewed
  `SELECT_NONE`.
- **The Teacher learned outcomes better than actions.** On the same powered
  REPORT, outcome-NLL improvement was `+0.47845` with LCB `+0.44201`, but that
  diagnostic cannot override the failed action gate. The best learned
  successor is an explicit advantage or bounded value/leaf hypothesis—not
  another direct argmax of this ranker. A terminal post-hoc outcome-head argmax
  also missed (`+0.00906`, LCB `-0.01184`, 203/219 triggers), so absolute value
  calibration alone is insufficient. Other post-hoc slices (diagnostic only) were
  negative early (`-0.0256`) and on 13+ candidate ballots (`-0.0102`), but
  positive mid (`+0.0234`), late (`+0.0825`) and on ≤8 candidates (`+0.0450`),
  motivating surface/horizon specialization and candidate-count calibration.
- **The downstream policy bug is fixed, but the source is not authorized.** Head
  `bed8f56` keeps the exact `mc-s0-report-lcb` move—not merely heuristic
  candidate zero—as incumbent, reproduces live/V11/structured/random sourcing,
  runs the public N=30 uncertainty predicate before Stage-C inference and
  gives at most one proposal a fresh N=300 report. The required REPORT PASS did
  not occur, so never freeze or screen this generation's composition.
- **S4 is terminal positive-but-inconclusive `SELECT_NONE`:** replication
  `+0.048828 +/-0.055712`, LCB `-0.006884`. Preserve the mechanism posterior;
  do not retry or extend the spent recipe.
- **The next strategic gaps are not more generic MC.** The 7,040-state asset
  discards candidate-source provenance; 1,298/6,400 play rows have only one
  candidate and all 1,087 exact-late rows have zero ranking choice; almost all
  labels inherit one heuristic continuation. Proposal quality, continuation
  quality and a real two-card endgame curriculum are the next substantive
  levers.
- **Mini and Air are free.** The Teacher REPORT is spent and complete. Both may
  run independently admitted S6, endgame, provenance or continuation work;
  none may reuse or pool the spent REPORT.
- **S6:** phase-wide shuai-pai sourcing is the best compute-free P1 follow-up.
  Draft PR #19 covers the KESP omissions and a late trump-only witness while
  preserving literal candidate zero. It still needs semantics review and a
  small equal-work screen—not a broad duel.
- **Repository hygiene:** Xray kitty-bury PR #11 merged. Four superseded
  status-only PRs and terminal no-use PR #26 closed; 17 dead/redundant remote
  branches and 14 merged/superseded local branch names removed. Evidence-heavy
  worktrees were retained even when their branch name was detached. The active
  Stage-C stack stays until its frozen runs finish; then consolidate it onto
  current `main` before pruning ancestor branches or evidence worktrees.

## NOW — output ledger ordered by value

An item closes only when its named artifact and terminal gate exist. A design
or source review authorizes the next bounded step; it is not a strength result.

| priority / milestone | strategy in plain English | progress and what is left | next output | exit gate |
|---|---|---|---|---|
| **P0 / mid/late protected Teacher successor** | Trust the learned model only after five tricks, where the horizon is shorter, and let it offer one idea to report-LCB rather than directly play it. | **Fresh hypothesis; no evidence authority.** The rule was discovered after REPORT: mid/late was positive on DESIGN (`+0.01189`, LCB `+0.00872`), CALIB (`+0.01248`, LCB `+0.00612`) and the spent REPORT slice (`+0.02255`, LCB `+0.00790`, 97 triggers), while early play was harmful. Draft PR #35 at `3668814` binds trick 5+ before source/scope/model work; 78 focused tests pass. **Left:** score-free capture exactly 256 new one-state-per-deal triggers, balanced across mid/late × attacker/defender; require public champion uncertainty and a legal model disagreement. On separate common worlds, run the actual protected N=300 decision, a trigger-matched random proposal and the literal live incumbent, then evaluate all final moves on an independent N=300 fold. The spent SD (`~0.085`) makes 256 states about 80% powered for a `~0.013` effect. | One 256-trigger fresh state-level composition screen; no large Teacher rebuild | Exact work and zero fallback; treatment-minus-live and treatment-minus-null one-sided LCBs above zero; null-minus-live interval contains zero. The spent post-hoc slice cannot count as confirmation. |
| **P0 / S6 shuai-pai sourcing** | Ensure search can price a legal throw in early, middle and late leads instead of silently omitting the tactic. | **Source draft ready.** PR #19 `2605b04`; KESP AKQ/876 witnesses plus natural and trump-only late states; 12 focused tests pass pure and compiled+strict. A diagnostic-only 1,000-round census found a new proposal in 99%+ of eligible leads (mean additions early/mid/late 2.75/1.93/1.13), so this is broad widening rather than a rare tactic. **Left:** external semantics review, then a 64-state DEV screen with live, structured and trigger/candidate-count-matched random widening at equal candidate-world work and disjoint selection/report folds. | Public-only deterministic source followed by a small state-level capability screen—not a whole-game duel | Literal live ballot/candidate zero first; follow/no-shuai states no-op; treatment must beat both live and random widening before any game-screen design. |
| **P1 / proposal provenance flywheel** | Learn which extra source actually supplies useful actions so proposal budget goes to tactics, V11, throws or humans—not anonymous widening. | Capture has source tags, but the 7,040-row training asset strips them. **Left:** retain tags as diagnostics; report candidate recall, regret and incremental wins per source; select a fixed 1–3 proposal budget against candidate-count-matched random. | Source-aware DESIGN/CALIB table plus one equal-work fresh-state proposal screen | A named source must beat random widening at the same candidate/world budget; source identity is diagnostic metadata, not a hidden-information feature. |
| **P0 / continuation portfolio** | Fix systematic search pricing errors by evaluating selected actions under more than one plausible continuation, starting with point-aware winning and defensive slough discipline. | S4 was positive in both whole-game estimates but did not confirm; almost all Teacher labels still use one heuristic continuation. S5 has only a boundary fixture. **Left:** frozen S4 heterogeneity analysis, engine-replayed S5 legality census, then one substantively changed portfolio versus a matched single-continuation control. | Trigger-matched fresh-state effect by role/phase plus a bounded continuation successor | Must change the continuation contract, not retry S4. Advance only if treatment beats the matched continuation control with exact equal work. |
| **P1 / exact two-card endgame curriculum** | Solve a genuinely smaller game first, then distill it: at two cards per seat, alternate actions and hidden worlds are still meaningful but the horizon is bounded. | One-card controller exists but performed zero solver work; all 1,087 exact-late Teacher rows have candidate count one. **Left:** generate real/live-history two-card roots, enumerate alternate legal actions, solve each sampled world under a node cap, aggregate public-belief regret labels, then train/screen a student. | A versioned two-card dataset with solver work, alternate-action regret and a fresh student screen | Nonzero alternate candidates and exact solver work; bounded completion; student beats candidate zero on fresh roots before expanding to three cards. |
| **P1 / human proposal diagnostic v2** | Use strong human moves as ideas and hard-tail witnesses, then let counterfactual evaluation decide whether they help instead of copying every player. | H0 stopped at 555/557 and published no aggregate; this is no scientific verdict. Server corpus has 2,830 plays/45 buries and identified bury, point-banking and throw witnesses. **Left:** reusable zero-look repair semantics, complete legal replay, source tags and matched human/V11/random comparisons. | Completed engine-replayed proposal-value table by human cohort and decision type | Human proposal must beat matched random on counterfactual value; observational win/loss correlation alone cannot admit a rule. |
| **P2 / posterior calibration** | Check whether determinized hidden hands have the right probabilities, not only legal support; more MC converges to the sampler's distribution even when that distribution is biased. | Hard validity/support gates pass; global posterior fidelity is unproved. **Left:** exact-toy posterior targets, likelihood/calibration diagnostics, then a separately gated weighting or belief model. | Exact-toy calibration report with a falsifiable uniform-baseline comparison | No posterior-changing production flag until calibration improves without breaking support, replayability or action semantics. |
| **P1 / repo integration cleanup** | Replace the long experimental PR stack with one reviewable integration on current `main`, without deleting run provenance. | PR #11 merged; #10/#12/#21/#25 and terminal no-use #26 closed; 17 remote branches, 14 merged/superseded local branch names and 23 clean worktrees removed. Evidence-bearing merged worktrees were detached but retained. One already-missing V11 worktree record was pruned. Draft PR #30 compacts docs, protects nine source-required markers and adds green PR checks; stacked PR #31 removes only proven-unreferenced `segbatch.py`. **Left:** review/merge #30, retarget/review #31, finish T4 evidence, then build one current-main Stage-C integration and audit evidence worktrees before removal. | One current-main integration PR plus branch/worktree inventory | Every retained source path has a consumer; every removed branch is merged/superseded or patch-equivalent and owns no sole evidence bytes. |
| **PARKED / HUMAN-C1** | Ultimately prove a candidate improves play against people, not only other bots. | Inert harness only; no traffic authority. **Left:** identity-bound candidate receipt, authenticated consent, immutable blocks, synthetic C0 and estimator. | Reviewed blinded candidate-versus-champion human test | Resume only after a challenger beats report-LCB in fresh bot confirmation and separate traffic authority exists. |

## T4 milestone — what counts as progress

T4 exists to produce and test a stronger Teacher-generated challenger. It does
not close as a success because capture, labels, training or reviews work. This
generation reached a valid, independently authenticated scientific
`SELECT_NONE`: step 4 completed, but the action LCB did not authorize steps
5–6. T4 has no remaining execution or review gate.

The causal sequence is:

1. generate split-safe states and bounded counterfactual labels;
2. train at least eight seeds for each predeclared objective;
3. choose one whole cohort on DESIGN/CALIB;
4. open untouched REPORT once;
5. compose only a REPORT passer as one proposal against the exact live-policy
   decision; and
6. run a fresh treatment/null/champion whole-game screen.

`SELECT_NONE` at steps 3 or 4 is a valid scientific closeout for that exact
generation, but it is not a stronger bot. A positive screen opens review of a
separate confirmation design; it does not authorize confirmation or deploy.

## Strength lanes

### Lane A — improve search directly

- **report-LCB:** confirmed and live; this is the named reference.
- **S3a structured bury:** strong selected-state signal, fresh full-game
  `SELECT_NONE`. Preserve disagreements as Teacher data; do not tune the spent
  recipe.
- **S4 point banking:** exact-state and initial whole-game screens passed;
  independent replication stayed positive but crossed zero. The exact recipe
  is closed; continuation heterogeneity may inform a changed successor.
- **S5 point protection:** replay hypothesis only. Prove the legal alternative
  and current-policy reproduction before writing a treatment.
- **S6 shuai-pai:** missing-action hypothesis. Source the tactic broadly but
  test candidate quality at equal work before changing production ballots.

### Lane B — build a Teacher beyond heuristic imitation

- Retain repeated hidden worlds with replacement; independent folds use
  domain-separated RNG streams, not unique realized deals.
- Mine uncertainty, proposer disagreement, point-bearing choices, throws and
  exact-late states. Human plays propose actions/states; they are not labels.
- Store candidate ballots and paired common-world outcomes, not only argmax
  labels. Bind sampler, continuation and acting-team signed utility.
- Retain candidate provenance for diagnostics; a ranker cannot improve actions
  it never sees, and anonymous widening prevents source-budget learning.
- Scale only when learning curves, seed stability and untouched REPORT show the
  signal survives. Candidate-rich rows and better continuation targets matter
  more than row count alone.

### Lane C — learn beyond MC imitation

V11 direct-v2, Direct-Q, O0 and O0-v2 selected none under different gates.
Their reusable contribution is the eight-seed/CRN/replay chassis. A successor
must change a substantive target, credit, curriculum, role specialization or
bounded adaptation mechanism. Large AWAC/self-play is parked until one
specialized learner or Teacher composition beats the live champion; otherwise
it mostly amplifies the same actor, ballot and continuation ceiling.

## Correctness and data

- [x] Bounded sampler hard-validity/support certificate on original, late and
  deep reservoirs under compiled strict execution.
- [x] Stage-C iid folds retain valid repeated draws with replacement and use
  domain-separated streams.
- [ ] Prove global dealer completeness/runtime with declaration pins and run
  caps; randomized filling is not a constructive completeness proof.
- [ ] Add exact-toy posterior calibration before enabling any posterior-
  changing sampler flag.
- [ ] Regenerate quarantined banker-private-kitty encodings from raw state;
  `gen_v4_all` remains the known-clean v11 source.
- [ ] Version a house-v1 conformance corpus and native ABI/source digest guard.
- [ ] Bind every dataset to replayable state, split, role, action multiset,
  ballot, sampler, continuation, utility, actor and producer identity.

## Performance, product and simplification

- [ ] Port `_lead`, `_current_winner` and `_cheapest_winning` to the compiled
  core one bounded phase at a time, with pure/compiled parity and bot timing.
- [ ] Vectorize `bc_train`; the per-decision loop is MPS-dispatch-bound.
- [ ] Add a concurrent-room production latency gate; keep Xray work off-loop.
- [ ] Centralize versioned environment-flag parsing. `SHENGJI_FAST=0` currently
  means false to some paths and true to others, so pure-route evidence must
  unset the variable until the migration lands with route/provenance tests.
- [x] Add fast PR CI: 139 pure-core server tests, 108 compiled/parity/seeded-
  pairing tests, frontend tests/build, and a high-severity dependency audit.
  The full local evidence suite remains outside CI because it requires ignored
  corpora, machine-bound receipts and experiment runtimes; those gates stay
  with their reviewed run packets rather than making every PR spuriously red.
- [ ] Finish reconnect/takeover, spectator privacy, trick history and portrait/
  zh-CN work as separate product lanes.
- [ ] Consolidate duplicated experiment wrappers only after reference audit.
  Draft PR #31 already proves and removes unreferenced `segbatch.py`.
  Remaining candidates include source-pinned `replay_log.pretty_cards`,
  duplicated card/seat helpers and superseded one-shot launch controllers;
  none may move without the same consumer/provenance audit.
- [ ] Do not simplify away admission, source/hash identity, replay, refusal or
  evidence isolation; replace those only with equally falsifiable machinery.

## Closed — do not re-queue

- Formal S0c is unread and nonretryable; RLCB-C1 supports report-LCB.
- N=30 beat N=10 twice; N=60 did not establish an increment over N=30.
- DEV-512 generic widening, V11 direct/protected-anchor, Direct-Q, O0/O0-v2,
  S3b-v2 and the first Stage-C protected Teacher all selected none or held.
- H0 completed only 555/557 and published no aggregate; no retry or partial
  mining and no human-derived Stage-C rule.
- S3a's spent whole-game stream selected none. A larger revisit needs a fresh
  preregistered design, not post-hoc continuation.
- Value-leaf, pairwise-as-scalar-leaf, generic widening and learned root-prior
  racing have no current promotion path.

Standing rule: screens select; only a fresh paired confirmation against the
exact deployed champion establishes strength, and only a separately reviewed
production packet can ship it.
