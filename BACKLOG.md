# Backlog

Last re-derived: 2026-08-11 03:15 EDT.

This file owns the executable queue. `AI_POLICIES.md` owns terminal results,
`RL_PLAN.md` owns research design, `JOBS.md` owns compute, and
`HANDOFF_ACTIVE.md` owns the next review. Completed chronology belongs in the
dated files under `docs_archive/`, not in this queue.

## Two-minute state

- **Production champion:** compiled `mc-s0-report-lcb` in Fly release 17.
  Fresh RLCB-C1 confirmed `+0.338 +/- 0.068` signed levels versus `mc-strong`;
  the matched null was flat. Runtime rollback is release 16; policy rollback is
  `mc-strong`.
- **T4's first Teacher generation was honest but not stronger.** The
  1,536-state, eight-seed generation selected none on DESIGN/CALIB. A
  post-hoc-but-protected play ranker then received one untouched REPORT look;
  it triggered 171/480 states and lost to candidate zero (mean
  `-0.00822754`, LCB `-0.01894357`). Both spent REPORT populations are closed;
  no threshold retry or composition is legal.
- **The expanded Teacher produced a real capability, not strength yet.** On
  7,040 DESIGN/CALIB states, the epoch-32 all-pairs bury ranker passed in all
  eight seeds with median candidate-zero improvement `+0.016418`. The direct
  loss did not win, so increased coverage is the leading explanation.
- **Mini:** training terminal review passed. The one score-free freeze produced
  PR #32 packet `5ce892db…25f0` for the exact selected ensemble and 32 untouched
  bury states. Its external controller review is open; predictions, labels,
  utility and execution remain zero.
- **Air:** the independent S4 point-banking replication remains sealed and
  healthy on eight workers. Read its score-free run ledger for volatile
  progress; do not inspect interim outcomes.
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
| **P0 / T4-L2 expanded labels** | Generate enough high-quality counterfactual labels to tell whether the first Teacher miss was data-limited, while keeping a new exam untouched. | **Terminal COMPLETE / external PASS.** Source `32d94a4`, receipt `48a64759…8efe`; 5,504/5,504 rows, zero refusals, aggregate `3deb3a81…f6ca`. The one packet-freeze authority is consumed. **Left:** none for this asset; it grants no training directly. | `TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW` | **Closed.** Byte-identical aggregate, shard membership and finite-work replay passed. |
| **P0 / T4-M2 matched Teacher objectives** | On the same 7,040 states, test whether more data helps the old loss and whether directly learning “is this move better than candidate zero?” fits the protected production decision better. | **Terminal COMPLETE.** The reviewed 96-cell A/B ran once. The old `all_pairs_v1` loss won selection; `candidate0_relative_v2` produced eligible cohorts but did not win. **Left:** none for the objective comparison. | Aggregate `5ad77eb0…b6bd`; original loss selected | The controlled comparison says expanded coverage mattered more than replacing the objective. This is not a strength verdict. |
| **P0 / T4-M3 train and select** | Learn whole eight-seed cohorts and select only a stable capability, not a lucky seed or checkpoint. | **Terminal external PASS.** All 96 cells and 576 checkpoints replayed. Selected epoch-32 all-pairs bury ranking: 8/8 positive seeds, median candidate-zero improvement `+0.016418`. The direct loss did not win. **Left:** none; its one packet-freeze authority is consumed. | Externally authenticated eight-model ensemble | **Closed as capability evidence.** No seed cherry-pick; no REPORT execution or strength follows directly. |
| **P0 / T4-R1 untouched REPORT** | Ask once whether the frozen bury ranker transfers to genuinely unseen states before paying for games. | **Packet frozen / external controller review open.** PR #32 exact `50e1464`; packet `5ce892db…25f0` schedules the 32 untouched bury rows in eight shards with a 262,848-world ceiling and rebuilt byte-exact. **Left:** raw packet PASS, then consume one look. | One candidate-zero comparison for the exact eight-model bury ensemble | Positive predeclared REPORT LCB and at least one trigger, or `SELECT_NONE`. No tuning, reuse, second capability or pooling. |
| **P0 / T4-C1 composition and game screen** | Let a REPORT-passing bury model propose one alternative, keep report-LCB/candidate zero as the safety fallback, and compare against a same-work random proposal. | **Source ready; no packet or REPORT authority yet.** Draft PR #33 exact `b85f810` reuses the reviewed one-shot runtime, isolates the expanded lane, and pins the reviewed Python path into every admission and child launch; 342 Stage-C tests pass, including receipt-tamper and expanded-profile-isolation checks. **Left:** R1 must pass, then freeze/review one composition packet, capacity preflight and fresh whole-game screen. | Mirrored treatment/null/champion screen against live `mc-s0-report-lcb` | Treatment must have positive one-sided utility LCB versus both champion and null; null must remain compatible with champion. Goal stops before confirmation/promotion/deploy. |
| **P0 parallel / S4 replication** | Check whether point banking's first positive whole-game result repeats independently without rerunning an expensive redundant full null arm. | **Live on Air.** Exact `fb6ec1a`, receipt `fc6d54e7…1077`, 8/8 workers; volatile progress stays in the run ledger. **Left:** terminal publication, pinned verify and independent result review. | Independent 2,048-cluster treatment/champion result plus 256 exact-null sentinels | LCB95(treatment−champion)>0; null equals champion on every sentinel; exact dose/work. No retry, extension or automatic deploy. |
| **P1 / S6 shuai-pai sourcing** | Ensure search can price a legal throw in early, middle and late leads instead of silently omitting the tactic. | **Source draft ready.** PR #19 `2605b04`; KESP AKQ/876 witnesses plus natural and trump-only late states; 12 focused tests pass pure and compiled+strict. A diagnostic-only 1,000-round census found a new proposal in 99%+ of eligible leads (mean additions early/mid/late 2.75/1.93/1.13), so this is broad widening rather than a rare tactic. **Left:** external semantics review, then a 64-state DEV screen with live, structured and trigger/candidate-count-matched random widening at equal candidate-world work and disjoint selection/report folds. | Public-only deterministic source followed by a small state-level capability screen—not a whole-game duel | Literal live ballot/candidate zero first; follow/no-shuai states no-op; treatment must beat both live and random widening before any game-screen design. |
| **P1 / S5 replay census** | Determine whether the bot actually donates point cards on lost tricks when a lower-point legal discard exists. | Boundary fixture passed at `2351b36`; no census run. **Left:** one deterministic score-free replay freeze when it does not compete with T4. | Trigger/refusal counts and replayable identifier-free witnesses | Census may open treatment design only; descriptive human logs alone cannot claim the mechanism. |
| **P1 / repo integration cleanup** | Replace the long experimental PR stack with one reviewable integration on current `main`, without deleting run provenance. | PR #11 merged; #10/#12/#21/#25 and terminal no-use #26 closed; 17 remote branches, 14 merged/superseded local branch names and 15 clean worktrees removed. Evidence-bearing merged worktrees were detached but retained. One already-missing V11 worktree record was pruned. Draft PR #30 compacts docs and protects nine source-required markers; stacked PR #31 removes only proven-unreferenced `segbatch.py`. **Left:** review/merge #30, retarget/review #31, finish T4 evidence, then build one current-main Stage-C integration and audit evidence worktrees before removal. | One current-main integration PR plus branch/worktree inventory | Every retained source path has a consumer; every removed branch is merged/superseded or patch-equivalent and owns no sole evidence bytes. |
| **PARKED / HUMAN-C1** | Ultimately prove a candidate improves play against people, not only other bots. | Inert harness only; no traffic authority. **Left:** identity-bound candidate receipt, authenticated consent, immutable blocks, synthetic C0 and estimator. | Reviewed blinded candidate-versus-champion human test | Resume only after a challenger beats report-LCB in fresh bot confirmation and separate traffic authority exists. |

## T4 milestone — what counts as progress

T4 exists to produce and test a stronger Teacher-generated challenger. It does
not close as a success because capture, labels, training or reviews work.

The causal sequence is:

1. generate split-safe states and bounded counterfactual labels;
2. train at least eight seeds for each predeclared objective;
3. choose one whole cohort on DESIGN/CALIB;
4. open untouched REPORT once;
5. compose only a REPORT passer inside the live search policy; and
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
  independent replication is live.
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
- Scale only when learning curves, seed stability and untouched REPORT show the
  signal survives. Row count alone is not progress.

### Lane C — learn beyond MC imitation

V11 direct-v2, Direct-Q, O0 and O0-v2 selected none under different gates.
Their reusable contribution is the eight-seed/CRN/replay chassis. A successor
must change a substantive target, credit, curriculum, role specialization or
bounded adaptation mechanism; estimator-only repairs and O1 remain closed.

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
- [ ] Add CI for server tests, frontend tests/build and a short compiled duel.
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
