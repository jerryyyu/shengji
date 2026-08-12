# Backlog

Last re-derived: 2026-08-11 21:11 EDT from terminal evidence, the weekly
strategy audit, the reviewed mid/late screen and prospective S4 power sizing.

This file owns the executable queue. `AI_POLICIES.md` owns terminal results,
`RL_PLAN.md` owns research design, `JOBS.md` owns compute, and
`HANDOFF_ACTIVE.md` owns the next review. Completed chronology belongs in the
dated files under `docs_archive/`, not in this queue.

## Two-minute state

- **Production champion:** compiled `mc-s0-report-lcb` in Fly release 17.
  Fresh RLCB-C1 confirmed `+0.338 +/- 0.068` signed levels versus `mc-strong`;
  the matched null was flat. Runtime rollback is release 16; policy rollback is
  `mc-strong`.
- **T4 produced learned capability but not a stronger standalone learned bot;
  its first fresh search hybrid passed a state-level capability screen.**
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
  The resulting trick-5+ model proposal protected by fresh N=300 search beat
  literal live by `+0.02020` (LCB `+0.01275`) and a same-work uninformed
  proposal by `+0.01570` (LCB `+0.00880`) on 256 fresh states. Independent
  terminal review reproduced the result byte-for-byte. It authorizes at most a
  new whole-game design—not a strength claim or deployment.
- **The downstream policy bug is fixed, but the source is not authorized.** Head
  `bed8f56` keeps the exact `mc-s0-report-lcb` move—not merely heuristic
  candidate zero—as incumbent, reproduces live/V11/structured/random sourcing,
  runs the public N=30 uncertainty predicate before Stage-C inference and
  gives at most one proposal a fresh N=300 report. The required REPORT PASS did
  not occur, so never freeze or screen this generation's composition.
- **Both spent S4 studies are individually terminal, but the mechanism remains
  the best near-term confirmation bet.** The screen was `+0.086914` (LCB
  `+0.030748`) and the independent replication was `+0.048828` (LCB
  `-0.006884`), with zero implementation-sentinel drift in both. Never append
  to or reinterpret either run. Their observed replication SD (`1.28634`) may
  size a genuinely new future-only fixed-look confirmation: N=12,288 gives an
  expected z=1.96 half-width `0.02274`, about 93% power at a predeclared
  worthwhile effect of `+0.04`, and about 99% at `+0.05`.
- **The next strategic gaps are not more generic MC.** The 7,040-state asset
  discards candidate-source provenance; 1,298/6,400 play rows have only one
  candidate and all 1,087 exact-late rows have zero ranking choice; almost all
  labels inherit one heuristic continuation. Proposal quality, continuation
  quality and a real two-card endgame curriculum are the next substantive
  levers.
- **Mini and Air are free.** Mini's 256-state mid/late result passed terminal
  review and now permits whole-game design work, not launch. Air is the
  intended host for a separately reviewed S4 powered confirmation. Neither
  host may reuse or pool a spent REPORT population.
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
Exploratory packets must predeclare zero-look repairs, per-row/stratum usability
and missing-data handling. All-or-nothing completion is reserved for claims
whose estimand truly cannot survive missing work, especially confirmation and
deployment gates; failure closes the exact recipe, not an entire mechanism
family.

| priority / milestone | strategy in plain English | progress and what is left | next output | exit gate |
|---|---|---|---|---|
| **P0 / S4 powered confirmation** | Give the consistently positive point-banking rollout change one test large enough to distinguish a useful small win from noise. | **Design target fixed; source/packet still left.** Prior N=2,048 runs were `+0.0869` and `+0.0488`; the second missed only because its half-width was `0.0557`. Use those outcomes only for planning. Freeze one new deal-disjoint, fixed-look N=12,288 treatment-versus-live run with a small stratified identity sentinel, z=1.96, minimum worthwhile effect `+0.04`, no optional peeks/extensions and no historical pooling. At measured Air speed this is roughly 62–65 wall-hours. **Left:** implement the fresh namespace/stream and power receipt, run score-free preflight, external packet review, then launch on Air. | Reviewed N=12,288 fixed-look Air confirmation packet and one fresh terminal aggregate | Exact fresh population and work; zero control drift; treatment-minus-live LCB > 0 at the sole look. Otherwise `SELECT_NONE`. Passing still needs separate deployment review. |
| **P0 / mid/late protected Teacher successor** | Use the model like AlphaGo uses a policy prior: after trick five it offers one promising move, while fresh belief-sampled MC still prices that move and protects production's choice. | **Fresh state screen independently PASS; whole-game design authorized.** The selector froze 256 unique natural states balanced 64 per mid/late × attacker/defender. Evaluation spent exact 230,400 candidate-worlds across treatment, same-work uninformed proposal and literal live. Treatment−live was `+0.02020` (LCB `+0.01275`); treatment−null was `+0.01570` (LCB `+0.00880`); result `f18c2e42…948f6`, review-claim SHA `6287ac4a…e97ace`. **Left:** implement, freeze and externally review one fresh mirrored whole-game screen; no launch is yet authorized. | Frozen treatment/null/champion whole-game screen packet, then one reviewed fresh aggregate | Compare the complete hybrid against literal `mc-s0-report-lcb` at equal declared work; report utility, overall/role win rate and level-change tails. A screen PASS opens confirmation design only. |
| **P1 / candidate-rich Teacher scale** | Grow the Teacher only with examples that can teach a new choice, rather than paying to label more states where the ballot has one action or the same continuation blind spot. | **Current 7,040 rows are reusable development data, not a fresh exam.** More data stabilized all eight seeds and value calibration, but fresh action gates still missed. Of 6,400 play rows, 1,298 are single-candidate; all 1,087 exact-late rows have no ranking choice; source provenance was stripped and almost all labels use one heuristic continuation. **Left:** add roughly 7k candidate-rich rows with phase/role/position quotas, source tags (live/S5/S6/V11/human/structured/random), and explicit continuation identity; train matched 7k-versus-~14k eight-seed curves. Scale toward ~28k only if fresh CALIB action signal and seed stability improve. | Versioned ~14k candidate-rich asset, source-value diagnostics and matched learning curve | At least two meaningful actions on ranking rows; no REPORT reuse; whole-cohort improvement across seeds on fresh CALIB. More rows are not a pass if only loss or outcome NLL improves. |
| **P0 / S6 shuai-pai sourcing** | Ensure search can price a legal throw in early, middle and late leads instead of silently omitting the tactic. | **Source draft ready.** PR #19 `2605b04`; KESP AKQ/876 witnesses plus natural and trump-only late states; 12 focused tests pass pure and compiled+strict. A diagnostic-only 1,000-round census found a new proposal in 99%+ of eligible leads (mean additions early/mid/late 2.75/1.93/1.13), so this is broad widening rather than a rare tactic. **Left:** external semantics review, then a 64-state DEV screen with live, structured and trigger/candidate-count-matched random widening at equal candidate-world work and disjoint selection/report folds. | Public-only deterministic source followed by a small state-level capability screen—not a whole-game duel | Literal live ballot/candidate zero first; follow/no-shuai states no-op; treatment must beat both live and random widening before any game-screen design. |
| **P1 / proposal provenance flywheel** | Learn which extra source actually supplies useful actions so proposal budget goes to tactics, V11, throws or humans—not anonymous widening. | Capture has source tags, but the 7,040-row training asset strips them. **Left:** retain tags as diagnostics; report candidate recall, regret and incremental wins per source; select a fixed 1–3 proposal budget against candidate-count-matched random. | Source-aware DESIGN/CALIB table plus one equal-work fresh-state proposal screen | A named source must beat random widening at the same candidate/world budget; source identity is diagnostic metadata, not a hidden-information feature. |
| **P0 / continuation portfolio** | Fix systematic search pricing errors by evaluating selected actions under more than one plausible continuation, starting with point-aware winning and defensive slough discipline. | S4 was positive in both whole-game estimates but did not confirm; almost all Teacher labels still use one heuristic continuation. S5 has only a boundary fixture. **Left:** frozen S4 heterogeneity analysis, engine-replayed S5 legality census, then one substantively changed portfolio versus a matched single-continuation control. | Trigger-matched fresh-state effect by role/phase plus a bounded continuation successor | Must change the continuation contract, not retry S4. Advance only if treatment beats the matched continuation control with exact equal work. |
| **P1 / exact two-card endgame curriculum** | Solve a genuinely smaller game first, then distill it: at two cards per seat, alternate actions and hidden worlds are still meaningful but the horizon is bounded. | One-card controller exists but performed zero solver work; all 1,087 exact-late Teacher rows have candidate count one. **Left:** generate real/live-history two-card roots, enumerate alternate legal actions, solve each sampled world under a node cap, aggregate public-belief regret labels, then train/screen a student. | A versioned two-card dataset with solver work, alternate-action regret and a fresh student screen | Nonzero alternate candidates and exact solver work; bounded completion; student beats candidate zero on fresh roots before expanding to three cards. |
| **P1 / human proposal diagnostic v2** | Use strong human moves as ideas and hard-tail witnesses, then let counterfactual evaluation decide whether they help instead of copying every player. | **H0-v3 is a tooling no-result, not a human-policy rejection.** It stopped at 555/557 because two seven-card follow throws had 12 legal production candidates but only three actions in the generic analysis enumerator. Server corpus has 2,830 plays/45 buries. **Left:** before any outcome, validate that the analysis union contains the complete production ballot on every row; allow deterministic zero-look repair; freeze fresh scoring worlds; predeclare per-row exclusions/stratum reporting instead of an unnecessary global discard; compare tagged human/V11/random sources. | Completed engine-replayed proposal-value table by human cohort and decision type | Every scored row passes candidate-superset and legality checks; exclusions are declared before outcomes and reported by stratum. Human proposals must beat matched random counterfactually; observational correlation alone cannot admit a rule. |
| **P2 / posterior calibration** | Check whether determinized hidden hands have the right probabilities, not only legal support; more MC converges to the sampler's distribution even when that distribution is biased. | Hard validity/support gates pass; global posterior fidelity is unproved. **Left:** exact-toy posterior targets, likelihood/calibration diagnostics, then a separately gated weighting or belief model. | Exact-toy calibration report with a falsifiable uniform-baseline comparison | No posterior-changing production flag until calibration improves without breaking support, replayability or action semantics. |
| **P1 / repo integration cleanup** | Replace the long experimental PR stack with one reviewable integration on current `main`, without deleting run provenance. | PR #11 merged; #10/#12/#21/#25 and terminal no-use #26 closed; 17 remote branches, 14 merged/superseded local branch names and 23 clean worktrees removed. Evidence-bearing merged worktrees were detached but retained. One already-missing V11 worktree record was pruned. Draft PR #30 compacts docs, protects nine source-required markers and adds green PR checks; stacked PR #31 removes only proven-unreferenced `segbatch.py`. **Left:** review/merge #30, retarget/review #31, finish T4 evidence, then build one current-main Stage-C integration and audit evidence worktrees before removal. | One current-main integration PR plus branch/worktree inventory | Every retained source path has a consumer; every removed branch is merged/superseded or patch-equivalent and owns no sole evidence bytes. |
| **PARKED / HUMAN-C1** | Ultimately prove a candidate improves play against people, not only other bots. | Inert harness only; no traffic authority. **Left:** identity-bound candidate receipt, authenticated consent, immutable blocks, synthetic C0 and estimator. | Reviewed blinded candidate-versus-champion human test | Resume only after a challenger beats report-LCB in fresh bot confirmation and separate traffic authority exists. |

## T4 milestone — what counts as progress

T4 exists to produce and test a stronger Teacher-generated challenger. It does
not close as a success because capture, labels, training or reviews work. The
original global-ranker generation reached a valid, independently authenticated
scientific `SELECT_NONE`: step 4 completed, but the action LCB did not authorize
steps 5–6. That exact generation has no remaining execution or review gate.

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

The trick-5+ model-guided-search successor is a distinct fresh model-use
hypothesis, not a reopening of the global ranker. Its state screen is complete
and independently positive; implementation/freeze/review of the whole-game
screen is the live gate. Launch remains unauthorized.

## Strength lanes

### Lane A — improve search directly

- **report-LCB:** confirmed and live; this is the named reference.
- **S3a structured bury:** strong selected-state signal, fresh full-game
  `SELECT_NONE`. Preserve disagreements as Teacher data; do not tune the spent
  recipe.
- **S4 point banking:** exact-state and initial whole-game screens passed;
  independent replication stayed positive but crossed zero. Each spent run is
  closed. A separately frozen N=12,288 future-only confirmation is now the P0
  path; it must not pool, extend or relabel either old population.
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
- Both existing S4 populations are immutable and nonextendable. The new
  N=12,288 lane is a prospectively powered independent confirmation, not a
  retry or an extra look at either old run.
- Value-leaf, pairwise-as-scalar-leaf, generic widening and learned root-prior
  racing have no current promotion path.

Standing rule: screens select; only a fresh paired confirmation against the
exact deployed champion establishes strength, and only a separately reviewed
production packet can ship it.
