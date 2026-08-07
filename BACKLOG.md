# Backlog

Last re-derived: 2026-08-07 13:27 EDT.

This is the execution queue, not an experiment notebook. Durable policy
conclusions belong in `AI_POLICIES.md`, model history in `RL_PLAN.md`, job
artifacts in `JOBS.md`, and detailed reviewer discussion in
`HANDOFF_REVIEW.md`.

## Current state

- **Production now runs compiled `mc-s0-report-lcb`.** The manual
  strength-first deployment is live at commit `74be565`; Fly version 16
  reports `{"bot":"mc-s0-report-lcb","fast":true}`. This decision rests on
  two independent 2,048-cluster development blocks: S0a
  `+0.353 +/- 0.069` and S0b `+0.357 +/- 0.066` versus `mc-strong`.
  `mc-strong` remains the immediate rollback.
- **The production latency complaint is confirmed, not subjective.** Room CAXI
  recorded 138 bot plays after the deployment, 109 of which searched. Search
  alone was p50 1.143s, p95 16.413s and max 20.499s on Fly's one-vCPU
  `shared-cpu-1x`; deployed version 16 then adds a fixed 0.7s delay before every
  bot turn. Early searched moves averaged 5.13s. Pushed latency branch
  `8e7afe3` freezes a sanitized 100-decision replay, offloads bot work from the
  event loop, preserves a 50ms seat-claim grace and makes 0.7s a minimum total
  turn time rather than an additive tax. Exact Air Python 3.14.6 replay passed
  100/100 with compiled search p50 0.172s, p95 0.357s and max 0.422s. Production
  deployment and same-image Fly CPU confirmation remain open.
- **Formal S0 is COMPLETE / SELECT NONE, for an evidence failure—not a measured
  loss.** All eight 1,024-cluster S0c shards and the aggregate completed, but
  the historical null had a lag-17 cross-cluster RNG collision. The exact
  score-blind 18-file seal succeeded; the one-shot corrected evaluator then
  refused before parsing outcomes after the keepalive supervisor state changed
  to `BLOCKED`. The numerical S0c result remains unread and must never be
  retried, pooled or reinterpreted.
- The outcome-blind closeout at `17f4085` permanently recorded
  `S0_COMPLETE_SELECT_NONE`, `outcomes_parsed=false`, and
  `promotion_admissible=false`. Closeout SHA-256 is
  `ef0a3659859b38d0b9362376e5e403fecb625f59c475600ed09906ce695fde9a`;
  commit `ca556c2` made the S0e-v2 parent lock terminal and
  `authorized=false`. All eight inert S0c launch services are unloaded; Mini
  is free.
- The frozen formal phrase “production remains mc-strong” describes what S0 was
  allowed to authorize. It does not undo Jerry's separate manual report-LCB
  deployment. A clean, newly versioned collision-free report-LCB confirmation
  is still required for a formal strength claim.
- The DEV-512 lead-ballot screen remains **SELECT NONE / CLOSED**. The current
  ballot had the lowest equal-work regret; CALIB-512 and REPORT remain sealed.
  Do not append arms to inspected DEV.
- **V11-v2 artifact repair is complete / FAIL.** No games were replayed. The
  repaired 2,048-cluster aggregate SHA-256 is `b7c90b…d21ad`; V11 minus current
  was `-0.1411 +/- 0.0698`, V11 minus null `-0.1099 +/- 0.0701`, and the null
  was sane. `protected_composition_authorized=false`, so the predeclared
  protected-anchor run is closed. Retain this checkpoint only as a within-state
  proposal/ranker and teacher disagreement source; it is not a scalar leaf.
- **Teacher-v3 Stage A is complete / PASS.** Commit `be25b4d`
  fixed canonical lead/follow, single-action and fallback semantics, including
  witness `143000001:44:0` and a 1,452-decision zero-off-ballot scan. Fresh
  packet `teacher-v1-entry-149m-v3` captured 1,024 deals, completed eight
  diagnostics and froze 64 states at SHA-256 `e01637…b4648`. A JSON tuple/list
  publication defect burned the first primary namespace; exact-parent repair
  `b41d8b3` then passed 120 tests, primary-v2/rerun-v2 completed all 16 shards,
  and gate `731dfa…35b` passed with zero problems. Stage B is authorized, but
  no receipt exists: first version the freezer's whole-git transition and name
  old N=30 attribution-only versus a new report-LCB gold schema.
- **Direct-Q completed / SELECT NONE.** Its full admitted 512-iteration screen
  had a promising paired gameplay effect (`+0.1628 +/- 0.0588`; all three seed
  means positive) and healthy action spread, but failed the predeclared held-out
  Q gate: seed 1 regressed and pooled attacker/defender MSE-reduction LCBs were
  negative. Aggregate SHA-256 is `1fa678…791`; do not extend this run. Diagnose
  the target/probe and build the Suphx-style supervised microbaseline.
- **RLCB-C1 is frozen and RUNNING on Mini.** Receipt SHA-256 is
  `02c286…39d0`; eight shards cover fresh seeds `150000000..150002047` and
  exactly report-LCB/current/collision-free-current-null. The supervisor is
  score blind and started from clean pushed `ced1033`; completion/result is not
  required to close T1.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **T1 / Lane A production latency — CODE + AIR PASS / FLY OPEN** | Keep the first stronger-than-MC production policy enjoyable to play | Pushed `8e7afe3` preserves exact semantics, removes the 0.7s additive tax and keeps CPU-bound bot work off-loop. The frozen Air result passes 100/100 and all latency thresholds. Finish same-image current/faster Fly evidence, production-safe deploy and post-deploy timing; never change N=30, R=300, ballot or LCB as a perf patch. |
| **T1 / Lane A.1 V11pair — COMPLETE / FAIL** | Spend the learned milestone without granting a losing checkpoint authority | Repaired artifact `b7c90b…d21ad` fails both superiority bounds; protected composition is not authorized. Keep V11 as an exact-ballot proposal/ranker and source of Teacher-v3 disagreement states. A future search use needs a new label diagnostic and protocol, not a retry. |
| **T1 / Lane B teacher — STAGE A PASS** | Generate counterfactual data capable of exceeding the old heuristic continuation | Exact-parent repair `b41d8b3`; gate `731dfa…35b` reopened 16 shards, matched all 64 states and authorized Stage B. Before freezing/receipting its 128 states, close the source-compatible freezer transition and explicitly version the gold continuation. |
| **T1 / Lane C Direct-Q — COMPLETE / SELECT NONE** | Learn beyond MC imitation with a trustworthy target | Gameplay improved but the held-out Q gate failed, so no extension. Diagnose seed-1/role calibration and build the bounded Suphx supervised microbaseline before versioning Direct-Q v2. |
| **RLCB-C1 fresh confirmation — RUNNING** | Put the manually shipped report-LCB policy on clean formal footing | Clean 2,048-cluster confirmation launched on Mini under `ced1033`; all eight shards are live. Preserve score blindness until terminal aggregation. This is new evidence, never an S0c continuation. |
| **Formal S0 — COMPLETE / SELECT NONE** | Preserve the burned S0c evidence boundary | Closeout `ef0a365…fde9a`, terminal parent `ca556c2`, no parsed outcomes, no retry/extension, and an empty S0 service namespace. There is no remaining S0c work. |

## TODAY — T1 champion flywheel launch

**Milestone objective:** make the deployed search operationally sound while all
three non-MC strength lanes advance to their next honest run/stop gate. T1 does
not require every long run to finish today; it requires no lane to remain idle
behind code or protocol work we could have completed.

| lane | deliverable today | hard gate |
|---|---|---|
| **Lane A / production guardrail — IN PROGRESS** | Sanitized 100/109 CAXI searches and froze exact cards, ordered candidates, work, records and RNG. Of the 100 post-RNG witnesses, 81 equal the next live receipt; 19 are explicitly source-replay-derived because an intervening bot action consumed the shared room RNG. Scheduler code and Air gate are pushed. | Air: exact 100/100, p50 0.172s, p95 0.357s, max 0.422s. Still required: current/faster same-image Fly evidence, safe merge/deploy, no WebSocket starvation, and post-deploy timing. Billable resize requires Jerry's approval and empty rooms. |
| **Lane A.1 / V11pair — COMPLETE / FAIL** | Existing bytes were repaired without replay or rewrite; all seven normal shards plus shard-5 `.FAILED` reopened and sealed in `b7c90b…d21ad`. | Frozen superiority rule failed (`-0.1411 +/- 0.0698` versus current); null sane; protected anchor closed. This exact checkpoint may propose/rank teacher actions only. |
| **Lane B / stronger teacher — STAGE A PASS** | Entry froze 64 states; a tuple/list publication refusal exposed and preserved one bad primary namespace; exact-parent v2 then completed two independent 512-world executions. | Gate `731dfa…35b`: PASS, zero problems, 64/64 deterministic equality, 218,112 candidate-world work, Stage B authorized. Next close freezer transition + gold version, then freeze the disjoint 128-state gate. |
| **Lane C / beyond imitation — COMPLETE / SELECT NONE** | Six preflights admitted the bounded 512-iteration treatment/control run, which completed exactly. | Gameplay LCB passed and Q health stayed bounded, but all-seed/pooled held-out learning requirements failed. No extension; next code gate is target diagnosis plus Suphx microbaseline. |
| **Fresh search confirmation — RUNNING** | `RLCB-C1` froze 8x256 fresh clusters and exactly live report-LCB, `mc-strong`, and collision-free `mc-strong-null-rlcb-c1`; launched on Mini from clean `ced1033`. | Keep supervisor score blind, require all eight exact shards/dose/runtime and evaluate only the single paired superiority gate plus null calibration. Never touch burned 135M outcomes. |

### Fleet order for T1

1. **Mini:** keep all eight RLCB-C1 shards running to their immutable terminal
   aggregate. Do not add a competing full benchmark or learner while it is
   saturated.
2. **Air:** V11 and Teacher-v3 Stage A are finished. It supplied the
   uncontended latency gate and is now idle. Do not start Stage B until its
   source-transition and gold-continuation identities are frozen.
3. **Local + Fly diagnostics:** finish scheduler review and same-image current/
   faster-CPU evidence. Do not benchmark while humans occupy a production room;
   a billable temporary machine or resize needs Jerry's approval.
4. **No idle gap:** the next bounded job may start as soon as its exact parent,
   namespace, tests and stop rule are committed. A failed lane releases compute
   to another lane; it does not weaken its own gate.

### Explicit non-goals today

- Do not reopen, score or “complete” S0c. It is terminal and burned.
- Do not lower R=300, N=30 or the LCB threshold under the label of performance;
  any such policy change needs a matched strength screen and fresh confirmation.
- Do not scale teacher or Direct-Q data because a pipeline merely runs.
- Do not let formal confirmation crowd out Lane A.1, B or C compute; it uses
  capacity after the learned-strength gates are moving.

## AI-strength program

More rows from the old pipeline are not the answer. Existing nets mostly learn
old-ballot `Q^Heuristic(s,a)` under a non-strict biased sampler; scaling those
labels makes the model imitate that ceiling more precisely. Compute must buy
either a stronger search decision, a stronger target, or genuine policy
improvement.

### Lane A — make the production search stronger now

The sanitised live-incident challenge is the motivating regression. Defender
seat 2 held `SAAK`; that play was in the ballot and was SmartBot's candidate 0,
yet one N=30 draw let `DJ` clear the fixed five-point override margin. With
current code:

- 240 worlds prefer `SAAK` by about 5.4 attacker points;
- 500 independent N=30 replicas choose `SAAK` 479 times and `DJ` twice;
- the two `DJ` replicas overestimated it by 5.8 and 6.3 points, just enough to
  clear the fixed margin.

The mechanism is now implemented. Uniform N=30 nominates one challenger; a
fresh named R=300 paired report fold chooses it only when report mean or a
conservative one-sided LCB exceeds the separate `REPORT_MIN_GAIN=0`. Adaptive
selection uses direct overlapping-world candidate-vs-leader moments and exact
N*K work; random allocation and equal-total-work uniform controls are registered.
Short folds refuse, all work/counters reconcile, and live JSON records replay.

The clean immutable diagnostic (`s0_override_audit.v1.json`, SHA-256
`9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5`)
found 48 overrides in 150 frozen DEV states. Among the first 20, 12 N=300 gaps
were positive, mean gap was only +0.570 and median absolute gap 2.775. The
predeclared grid retained 2/3/5/6 positive references at R=30/60/120/300 under
LCB>0 with zero negative supports, selecting R=300. This is calibration, not
strength; it corrects the unsupported blanket claim that MC overrides are worth
1.4-1.7 points.

What survived the completed S0 program:

1. S0a and S0b independently found a large report-LCB improvement over
   `mc-strong`; equal extra work alone did not explain it.
2. Adaptive allocation's incremental effect was unresolved, so report-LCB is
   the simpler product choice.
3. S0c cannot answer the formal confirmation question because its one-shot
   evidence chain failed before the corrected evaluator parsed outcomes.

The next formal experiment is therefore a fresh report-LCB/current/null
confirmation—not a replay of S0c and not another allocation sweep. Use paired
signed level utility per fresh deal cluster with seat/team flips, a
collision-free null, exact accepted-dose accounting and one immutable gate.
Recompute sample size from the frozen estimand; random game seeds are not
limited by the corpus deal count.

Two independent search improvements can run beside it:

- **Structured bury search:** the old `MC_BURY` test priced four hand-built
  variants and tied. Enumerate ~20–50 point-preserving, void-forming and trump-
  preserving buries, price them with common worlds and evaluate full rounds.
  Once per round makes this a cheap place to spend much more compute.
- **Sampled exact endgame:** for the final ~4 tricks, solve each determinized
  world exactly or with bounded minimax instead of heuristic continuation, then
  aggregate under the acting seat's belief. Gate on endgame challenge states,
  then fresh paired games.

### Lane A.1 — spend the v11pair milestone instead of shelving it

`rl-override-v11pair` is frozen and confirmed at 57.7% versus SmartBot, but its
51.1% versus MC was unseeded SCREEN evidence. The rejected hybrids do not close
the best use of that fact:

- root-prior racing hard-pruned actions and lost to its random-prune control;
- `mc-gate-v11pair` used the net only to decide whether to invoke MC, and its
  equal-budget follow-up never produced a valid result; and
- pairwise deltas are not an absolute leaf value.

The artifact-only repair is now terminal. The clean-encoder direct actor lost
to current MC by `-0.1411 +/- 0.0698` over 2,048 clusters and also lost to its
null; the null-current interval contained zero and exact dose passed. The
frozen rule therefore says `protected_composition_authorized=false`. Do not run
the already-coded protected anchor from this checkpoint and do not reinterpret
the old SmartBot win as current-MC strength.

What remains useful is narrower and testable:

1. **Proposal/disagreement mining now:** v11pair's relative deltas are valid
   within one exact ballot. Teacher-v3 already reserves uncertainty states
   where Smart, N=30 and V11 disagree; label those actions rather than granting
   the model control.
2. **Measure proposal precision:** on fresh teacher gold-report worlds, report
   how often V11 proposes the gold-preferred action, its paired regret, role/
   phase breakdown and whether it adds an action absent from candidate 0.
3. **Safe search integration only after a positive diagnostic:** retain every
   current candidate and the unbiased report fold. A new model may add a
   canonical missing proposal or softly allocate extra selection worlds; it may
   not prune. Include a same-trigger random proposal/allocation control.
4. **Version a new protected screen, never retry this one:** a successor with
   positive held-out proposal evidence may reorder candidate 0 under a newly
   frozen report-LCB parent/null contract. Exact activation and equal work stay
   mandatory.
5. **No V11 leaf:** pairwise deltas have unidentified cross-state scale.
   Learned-rollout and value-leaf variants remain separate hypotheses and need
   their own calibrated absolute target.

Teacher-v1 should train a `v11.1` successor only after the teacher gates pass:
preserve the pairwise/listwise objective that worked, add the calibrated
bracket head, and compare warm-start with scratch on clean current-ballot
labels. First uses remain proposal/ranker/allocator; no cross-state leaf.

### Lane B — generate data that can exceed the old teacher

Build `teacher-v1` as a vertically labelled counterfactual dataset, never from
DEV/CALIB/REPORT. Mechanics now pass on 64 states; next prove continuation
quality on 128 disjoint states. Only then freeze the 2,048-state pilot across
lead/follow, early/mid/late, attacker/defender, close margins and policy
disagreement. Keep real-human incidents as separate regression cases.

Entry is no longer hypothetical: 149M-v3 froze exactly 48 representative,
8 boundary and 8 uncertainty states, and Stage A now passes. Exact-parent
primary-v2/rerun-v2 used 256 selection + 256 report worlds on all 64 states,
matched deterministically and authorized the 128 disjoint Stage-B set. Before
Stage-B freeze or receipt creation, close the source-compatible freezer
transition and explicitly decide whether its currently implemented
gold remains `mc-strong@N=30` as an attribution baseline or is versioned to the
stronger live report-LCB continuation. Do not silently swap policies under the
old schema, and do not claim an `mc-strong`-gold labeler can exceed report-LCB
without a direct gate.

Use the historical high-N corpora to decide **where**, not **what**, to label.
The fixed-pair audit at `ab3c652` found that frozen v11 has real old-surrogate
signal plus a costly tail: original DEV `+0.397 +/- 0.037` acting-team raw
points/decision with 18.0% harmful overrides; later-ply DEV
`+0.334 +/- 0.047` with 25.7% harmful. It also found zero true-late original
DEV rows and only eight in the supplement, so neither artifact answers late
play. Next:

1. mine DEV only, one state/deal, into clear v11 wins, clear losses, threshold-
   boundary disagreements, high-SE rows and lead action-type transitions;
2. freeze the resulting selector and apply it to fresh non-evaluation deals;
3. feed those fresh states into teacher-v1's strict, disjoint-world, bracket-
   outcome labeller over the complete ordered current MC ballot; assert that
   Smart, N=30 and v11 choices are present rather than inventing a new ballot;
4. keep mined old losses as regression cases, not training or promotion data;
   and
5. do not rerun 37.1M old evaluations or fit another deployable threshold to
   their historical `Q^Heuristic` target.

For every state store the exact replay and `BallotSpec`, every candidate, 512
common strict worlds, per-world terminal attacker points and signed level
bracket, paired deltas/SE, sampler/continuation identities and all counters. A
stratified gold subset should use champion continuation and exact-late solving
where tractable to test whether the cheap continuation preserves candidate
ranking. If the cheap-selected action's gold-regret 95% upper bound exceeds
0.10 signed levels, do not train or scale that cheap target; redirect labels to
the stronger continuation. This tensor supports allocation research,
uncertainty calibration and supervised learning without rerunning rollouts.

Train three seeds at increasing state counts with:

- a listwise/pairwise action-ranking head aligned to the deployed choice—the
  useful `v11pair` insight;
- a separate calibrated scoring-bracket distribution head for absolute outcome
  and uncertainty, never treating pairwise deltas as a cross-state leaf; and
- role, public history, candidate/action and suit-symmetry aware encoding.

First use the model to propose/rank/softly allocate inside MC without pruning.
A held-out teacher gain plus a fresh paired win over `mc-strong` is only the
minimum research gate; a larger 10k/50k wave or champion replacement must beat
the live report-LCB parent or its formally confirmed successor. A promoted policy becomes the next
continuation teacher: collect -> train -> paired gate -> replace champion ->
relabel, rather than generating millions of labels once from a fixed teacher.

### Lane C — learn beyond MC imitation

The repaired DouZero-style Direct-Q path completed its bounded screen. This was
not “nothing worked”: its frozen actor beat the no-step control in gameplay by
`+0.1628 +/- 0.0588`, with positive differences in all three seeds and healthy
Q magnitude/action spread. But the learned Q target did not generalize
reliably: seed 1 worsened held-out MSE and pooled attacker/defender improvement
LCBs crossed zero. The predeclared conjunction therefore returns SELECT NONE.

Next sequence:

1. Reopen only diagnostics, not the training tail: localize seed 1 by role,
   target bracket, replay age, action count and state stratum; check whether
   gameplay gain came from a useful actor change the MSE aggregate obscures or
   from noisy evaluation.
2. Freeze a larger deal-disjoint held-out probe and ranking/calibration metrics
   before a new learner runs. The current result cannot authorize relaxing its
   gate post hoc.
3. Implement the bounded Suphx-style supervised microbaseline with scheduled
   privileged-feature removal plus partial-only/distillation controls. This
   tests encoder/target learnability without bootstrapped Q confounding.
4. Version Direct-Q v2 only after the microbaseline improves the frozen target;
   keep actors immutable within an iteration, use a frozen opponent pool and
   retain exact resume/role-sign/action-spread receipts.
5. Gate every candidate against the production champion on paired deal
   clusters. AWAC remains a later optimizer on a valid replay contract, not a
   substitute for fixing the target.

### Compute queue

1. **Mini / running:** finish immutable RLCB-C1. No second heavy job shares the
   host; no partial score is opened.
2. **Air / next admitted strength work:** Stage A is PASS and Air is idle.
   Implement/review the source-compatible Stage-B freezer transition, freeze
   the explicit gold-continuation schema, then and only then freeze the 128
   disjoint states and create cheap/gold receipts.
3. **Local/Fly / latency:** merge the exact scheduler branch, benchmark the
   current and an approved faster same-image CPU only with empty rooms, deploy
   safely, and collect post-deploy `bot_timing` receipts.
4. **CPU-light diagnosis in parallel:** analyze Direct-Q seed 1 and freeze the
   Suphx microbaseline code/probe contract; mine V11 proposal precision on the
   already frozen teacher states once labels exist.
5. **Do not launch:** current V11 protected anchor, a Direct-Q extension, any
   S0c repair, or Stage-B cheap/gold before the freezer transition and explicit
   continuation versioning are reviewed.
6. **Scale only winners:** larger teacher/RL waves require a valid teacher-
   quality or learning-screen PASS; full-game fleet confirmation is reserved
   for candidates that clear their local gate against the named live parent.

At each stage, failure frees the queue for the next mechanism; it does not
authorize adding more data to a target that failed.

## Correctness and data

- [x] **Current bounded P0 sampler certificate.** `aea3774` plus
      `server/runs/logs/certify_sampler_v3.json` passed the registered clean,
      compiled+strict scope: 500 original + 500 late + 500 deep states,
      36,000 requested = accepted, zero rejected/invalid/skips, and 120/120
      exhaustive toys/witnesses. This proves bounded hard validity/support,
      not posterior fidelity or a globally complete constructive dealer.
- [ ] **Global dealer completeness/runtime.** The pair-cap forward check in
      `75b06da` is a sound necessary prune and fixed the observed DEV rejection,
      but it is sufficient only in a reduced no-pin/no-run-cap model. Production
      still uses up to eight randomized card fills per count matrix. Do not call
      this globally complete without a bounded constructive allocation or proof
      covering declaration pins and run caps.
- [ ] **Posterior fidelity (P1).** Accepted worlds are not sampled at the true
      physical-deal proportions. Weighted count splits reduced excess TV by
      `0.060 +/- 0.031` but remained biased and was too slow; uniform card choice
      contributed essentially nothing. All experimental sampler flags remain
      OFF. Any repair needs exact-toy calibration, runtime measurement and new
      policy revalidation.
- [x] **S0 runtime-flag durability (main only).** Commit `4dc5302` refuses all
      four posterior-changing sampler/ballot flags even when present with an
      empty value, records an explicit empty list, and rejects missing,
      nonempty, within-phase or cross-phase drift. Focused S0 acceptance is
      39/39. The frozen live Mini chain was not touched. S0c launchd metadata
      plus the static wrapper supplied the external receipt: none of the four
      keys was inherited and only compiled+strict flags were added. Include it
      in closeout; do not misattribute it to the newer runner guard.
- [x] **S0 process cleanup.** After the outcome-blind terminal lock verified,
      Codex required the loaded namespace to equal the eight inert S0c labels,
      required every PID to be absent, booted out exactly those labels and
      verified the full `com.shengji.s0mini.*` namespace empty. No evidence
      file was removed. General automatic prior-phase retirement remains useful
      operator simplification, but it no longer blocks S0 or compute capacity.
- [ ] **Dataset contract.** New training records must bind exact state replay,
      role/perspective, legal action multiset, `BallotSpec`, sampler, continuation
      policy, utility target, actor checkpoint and source/split digests. The
      high-N and late corpora are valuable state reservoirs, not clean oracles.
- [ ] **Encoder provenance repair.** `66aad44` restores and hashes encoder-v1's
      public/no-private-kitty semantics. Full replay proves all 5,923 banker
      rows in `rl_data/highn_enc` match only the drifted implementation (the
      14,922 nonbanker rows are invariant). Byte audit also quarantines
      `human_v4/v5/v6` (509/551/551 private-only banker rows). Regenerate all
      four from retained raw sources before training or new agreement claims.
      `gen_v4_all` is definitively clean; the existing v13abs checkpoint is not,
      because it trained from `highn_enc`, and must be retrained after repair.
- [ ] **House-v1 conformance corpus and native ABI guard.** Preserve positive
      and negative rule cases; refuse a stale compiled extension using an API
      version and source/binary digest.

## ML / RL

- [x] **Role-correct target and immutable actor tests.** The legacy DMC2 path
      now applies the same acting-team sign to terminal return and attacker-
      perspective oracle, versions its clipped reward, and gives every worker a
      digest-bound immutable checkpoint plus named batch seed. A second audit
      bug was also fixed: a passing gate now promotes the exact evaluated
      candidate, not whatever newer learner weights exist when the duel ends.
      Historical DMC2 results remain invalid and no new run is strength evidence.
- [x] **Exact DMC2 candidate promotion seam.** Commit `d5d71d2` adds a pure
      PASS/FAIL resolution boundary. PASS re-verifies and returns the exact
      immutable candidate given to the duel even when a distinct newer learner
      exists; FAIL retains the exact incumbent, and generator drift refuses.
      Focused DMC2/self-play acceptance is 32/32. This repairs code provenance,
      not the invalid historical DMC2 strength result.
- [x] **Exact synchronous self-play infrastructure.** `29c8cc1` and `e49cf60`
      bind learner, optimizer, replay ring, progress, named RNGs, runtime and
      immutable actor/candidate generations; interruptions poison and rollback,
      hidden/global mutable state refuses, and bounded resumed execution matches
      uninterrupted execution. Each concrete algorithm still owes its own
      verified-actor collector and exact resumed-output test.
- [ ] **Faithful synchronous microbaselines.** `868b6d8` closes a bounded
      Shengji-specific DouZero-style two-role direct-Q code gate with exact
      resume, but not paper faithfulness or learning evidence. Predeclare and
      run its small held-out learning gate before scaling. Separately implement
      and test a Suphx-style privileged-feature-removal policy curriculum. Do
      not describe the old scalar residual recipe as either paper's algorithm.
- [ ] **Absolute value contract.** If a leaf is revisited, predict a calibrated
      scoring-bracket distribution or expected signed level utility under a
      named belief, role and continuation policy. `v11pair` is a useful direct
      override/ranker on its exact ballot, not a cross-state scalar leaf.
- [ ] **Belief model only after the hard sampler boundary is current.** Learned
      ownership weights may reweight valid worlds; they must not hide invalid
      or already-biased base sampling. Report exact-toy calibration and effective
      sample size.
- [ ] Human-style fine-tuning only after the human corpus contains a few
      thousand validated decisions.

## Performance and simplification

- [ ] Port the remaining rollout hot leaves (`_lead`, `_current_winner`,
      `_cheapest_winning`) to the compiled core, then evaluate int-native hands.
      Existing phases 0–2 delivered about 3.42x; require pure/compiled parity
      tests and end-to-end decision timing for each phase.
- [ ] Vectorize `bc_train`; its per-decision loop is MPS-dispatch-bound.
- [ ] Introduce one immutable `ExperimentSpec` containing code/data/ballot/
      encoder hashes, actor paths, seeds, budget, metric, null, stop rule and
      artifact destinations. Only then add a bounded fleet queue; scheduling may
      be automatic, promotion and metric changes may not.
- [ ] Remove duplicated/dead helpers when their replacement has tests:
      unimported `segbatch.py`, unreferenced `replay_log.pretty_cards`, trainer
      batch copies, and component-local `seatPos`/card helpers.
- [ ] Split the large API module only along established room/reconnect test
      seams; do not mix this with frontend behavior changes.
- [ ] Add GitHub Actions for server tests and the frontend build.

## Product backlog

- Spectator mode with no private hand or action bar.
- Trick-history and full-game replay viewers.
- X-ray explanations and per-candidate uncertainty already returned by the API.
- Persistent rooms across server restart; public lobby/profiles only if usage
  justifies SQLite.
- Portrait layout, card animations and zh-CN strings.
- Optional local commentator/coach, kept asynchronous from gameplay.

## Closed — do not re-queue

- The bounded original+late+deep sampler certificate passed at `aea3774`;
  posterior weighting and global constructive completeness remain separately
  open, but neither holds the strength queue.
- N=30 over N=10 confirmed twice; N=60 over N=30 found no advantage.
- DEV-512 ballot sourcing/selection experiment completed with SELECT NONE;
  CALIB/REPORT remain sealed.
- V3 widening, full-universe widening, learned root-prior racing, v7/V13 value
  leaves and pairwise-as-leaf are not champion paths on current evidence.
- Bounded submitted-action semantics and pure/compiled tractor enumeration are
  covered, including the server-boundary failed-throw regression.
- Evaluator consolidation, deterministic seed forwarding, strict shard merge,
  ballot/checkpoint identity and two-machine replay-corpus preflight shipped.
- Late-ply state capture and the balanced DEV/CALIB evaluation assets are done;
  they are evaluation/state assets, not automatically valid training labels.

Standing rule: strength claims use `scripts/evaluate.py`, paired deal clusters,
an explicit null and immutable manifests. Offline regret may reject an idea; it
cannot promote one to production.
