# Backlog

Last re-derived: 2026-08-07 17:50 EDT.

This is the execution queue, not an experiment notebook. Durable policy
conclusions belong in `AI_POLICIES.md`, model history in `RL_PLAN.md`, job
artifacts in `JOBS.md`, and detailed reviewer discussion in
`HANDOFF_REVIEW.md`.

## Current state

- **Production now runs compiled, formally confirmed `mc-s0-report-lcb`.** The
  strength-first policy now runs in latency-hardened Fly release 17 from exact
  image `latency-cd6789e` / digest `047bcfe4...5b300`; health
  reports `{"bot":"mc-s0-report-lcb","fast":true}`. S0a and S0b first measured
  `+0.353 +/- 0.069` and `+0.357 +/- 0.066` versus `mc-strong`. Fresh RLCB-C1
  then confirmed `+0.338 +/- 0.068` on 2,048 new clusters while its
  collision-free current null measured `-0.019 +/- 0.068`; every predeclared
  gate passed. Aggregate SHA-256 is
  `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
  `mc-strong` remains the immediate operational rollback.
- **The production latency complaint was real and its scheduler fix is now
  shipped.** Room CAXI
  recorded 138 bot plays after the deployment, 109 of which searched. Search
  alone was p50 1.143s, p95 16.413s and max 20.499s on Fly's one-vCPU
  `shared-cpu-1x`; the server then adds a fixed 0.7s delay before every bot
  turn. Early searched moves averaged 5.13s. Release 17 preserves the exact
  report-LCB policy but searches an isolated snapshot off-loop and overlaps
  that pacing delay. Its live ship-gate room recorded 42 bot turns at
  search p50/p95/max 1.136/1.857/3.104s and turn p50/p95/max
  1.138/1.858/3.106s, plus responsive claim/reconnect/X-ray checks. Continue
  monitoring real human rooms; a faster Fly CPU remains a separate lever.
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
- The frozen formal phrase “production remains mc-strong” describes only what
  S0 was allowed to authorize. It does not undo the separate deployment or the
  later RLCB-C1 confirmation. RLCB-C1 closes the one-round superiority claim;
  it does not repair S0c, prove adaptive allocation, or establish multi-round
  progression.
- The DEV-512 lead-ballot screen remains **SELECT NONE / CLOSED**. The current
  ballot had the lowest equal-work regret; CALIB-512 and REPORT remain sealed.
  Do not append arms to inspected DEV.
- **V11 direct-v2 is repaired and terminal SELECT NONE.** The artifact-only
  consumer reopened the immutable 2,048-cluster population without replaying
  games: v11-current `-0.141 +/- 0.070`, v11-minus-null
  `-0.110 +/- 0.070`, null-current `-0.031 +/- 0.068`.
  `protected_composition_authorized=false`; retain v11 only as a proposal,
  ranking and teacher diagnostic.
- **Direct-Q 144M is terminal SELECT NONE.** Gameplay was encouraging at
  `+0.163 +/- 0.059`, but seed 1 and both pooled role-specific held-out MSE
  gates failed. Its attractive report tail cannot authorize deployment,
  extension or recipe tuning.
- **Teacher-v3 is the live strength job.** Actor canonicalization, capture,
  diagnostics, exact 64-state freeze and the independent champion-audit
  protocol are code-complete. Air is running eight Stage-B N=30 gold shards;
  do not inspect outcomes or launch audit labels until all eight validate and
  the receipt-to-gate transition passes.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **T1 / Lane A production latency — COMPLETE / LIVE MONITOR** | Keep the first stronger-than-MC production policy enjoyable to play | Fly release 17 runs exact `latency-cd6789e` / `047bcfe4...5b300`. Health, native activation, claim, reconnect, stale-discard, X-ray isolation and concurrent WebSocket responsiveness passed live. Keep release 16 as the runtime rollback and `mc-strong` as the separate policy rollback; collect ordinary human-room timing before considering a CPU resize. |
| **T1 / Lane A.1 V11pair — COMPLETE / SELECT NONE** | Preserve the learned milestone without forcing it into the champion | Artifact repair passed; the frozen rule rejected protected composition. Keep v11 as a bounded proposer/ranker and teacher diagnostic only. No protected-anchor run is authorized. |
| **T1 / Lane B teacher — STAGE-B RUNNING; AUDIT PREFLIGHT PASS** | Generate counterfactual data capable of exceeding the old heuristic continuation | Eight Air workers remain healthy; the outcome-blind fold counter was 20.1% at 18:08, not an ETA. Complete and validate all eight attribution-only gold shards, seal the Stage-B gate exactly once under the readiness checklist in `HANDOFF_ACTIVE.md`, then—and only on PASS—label the separately frozen 64-state champion-continuation audit at exact `182d1df`/script SHA `57796fda...887ead`. Fresh-process Air preflight binds the literal report-LCB actor, rollout, ballot, engine and frozen state; superseded `f4f3dc0` is cache-tainted and may never create a receipt. Receipt/label/gate filenames authorize nothing until their creator exits `0`, the partial disappears and exact bytes reopen. No Stage-B outcome may tune the audit. |
| **T1 / Lane C Direct-Q — COMPLETE / SELECT NONE** | Learn from the failure without selecting its positive gameplay tail | Preserve aggregate SHA `1fa6789e…791`; do not deploy, extend or mutate the 144M recipe. The next learner requires a separately frozen Suphx-style or other role-correct microbaseline gate. |
| **RLCB-C1 fresh confirmation — COMPLETE / ARTIFACT-ONLY CONFIRM** | Close formal report-LCB superiority | 2,048/2,048 fresh clusters, exact doses, zero stream collisions, sane null and positive superiority LCB. The late dirty-doc supervisor refusal is bound by non-replay closeout SHA `06dd487d…b7aae5`; preserve aggregate SHA `83f5a9df…f5ef5ea`. No extension or S0c reinterpretation remains. |
| **Formal S0 — COMPLETE / SELECT NONE** | Preserve the burned S0c evidence boundary | Closeout `ef0a365…fde9a`, terminal parent `ca556c2`, no parsed outcomes, no retry/extension, and an empty S0 service namespace. There is no remaining S0c work. |

## TODAY — T1 champion flywheel launch

**Milestone objective:** make the deployed search operationally sound while all
three non-MC strength lanes advance to their next honest run/stop gate. T1 does
not require every long run to finish today; it requires no lane to remain idle
behind code or protocol work we could have completed.

| lane | deliverable today | hard gate |
|---|---|---|
| **Lane A / production guardrail** | **Shipped:** exact-semantic speculative scheduling and off-loop X-ray are live in release 17. Continue passive timing collection from ordinary rooms. | The 100-decision replay was exact; the live smoke met p50 <=1.5s, p95 <=4.0s and max <=8.0s, showed no additive 0.7s after long searches, and kept WebSockets responsive during X-ray. A billable Fly resize still requires Jerry's approval. |
| **Lane A.1 / V11pair** | **Closed:** artifact-only repair published from unchanged bytes and selected none. | No protected composition. Reuse v11 only in a new explicitly diagnostic/proposal contract. |
| **Lane B / stronger teacher** | Finish the running Stage-B gold labels, validate their exact gate, then execute the frozen 64-state report-LCB continuation audit. | All eight shards and receipts exact; no outcome-conditioned audit change; disjoint 32-world selection/report folds and full downstream report-LCB continuation at every information set. |
| **Lane C / beyond imitation** | **Closed:** Direct-Q finished but failed its conjunctive learning screen. Specify a fresh microbaseline before more learning compute. | The 144M report result cannot choose seeds, recipes, stopping or continuation. |
| **Fresh search confirmation** | **Closed:** RLCB-C1 formally confirmed report-LCB. | Preserve the exact aggregate and claim boundary; no additional confirmation compute is needed now. |

### Fleet order for T1

1. **Local + production diagnostics:** own the latency benchmark and
   exact-semantic server optimization; do not consume Mini/Air training slots.
2. **Mini:** RLCB-C1 and Direct-Q are terminal, so Mini is free for bounded
   compiled latency profiling or the next separately admitted learner gate.
   Never improvise a Direct-Q extension or protected-anchor run.
3. **Air:** keep all eight Stage-B gold workers owned by the frozen Teacher-v3
   transition. After validation, run only the already-frozen 64-state audit;
   do not redesign it from Stage-B outcomes.
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

The implemented minimal hybrid keeps every current candidate and the full N=30 common-
world budget. On states where the frozen 0.02 v11 rule overrides SmartBot,
reorder that action to candidate 0 so the existing five-point MC margin protects
the demonstrably stronger learned prior; keep Smart's action in the ballot and
leave `TRACTOR_LOCK` unchanged for the first attribution arm. This tests anchor
quality, not sourcing, pruning, latency or leaf evaluation. The checkpoint is
digest-pinned and fail-closed; the cached numpy weights are immutable.

Current sequence:

1. **Recover corrected direct-v2 evidence:** the clean-encoder games finished;
   repair only the validator's invalid capped-utility assumption, then reopen
   and bind the exact artifact. Preserve the stored verdict and admit no
   activation claim because that runner did not record one.
2. **Choose the anchor reference explicitly:** formal S0 closed on
   `mc-strong`, while production manually moved to report-LCB. Version the
   protected-composition parent against the policy we actually want to beat;
   do not silently inherit the obsolete meaning of “champion.”
3. **Run the protected screen:** exact same action set/worlds/candidate-world
   work as its named search reference; only candidate order/protected anchor
   changes. Compare v11 anchor with reference, same-trigger random anchor and a
   matched null. Nonzero activation and reconciled dose are mandatory.
4. **Confirm only a screen winner:** a positive screen may admit one fresh
   paired full-game confirmation. Never revive hard top-k pruning or use the
   pairwise head as a scalar leaf.
5. **Continuation probe, later:** teacher Stage B may compare v11pair as a
   policy continuation. Earlier stronger-rollout ties keep this below the root
   anchor test.

Teacher-v1 should also train a `v11.1` successor: preserve the pairwise/listwise
objective that worked, add the calibrated bracket head, and compare warm-start
with scratch on clean current-ballot labels. First uses remain anchor/ranker/
allocator; no cross-state leaf.

### Lane B — generate data that can exceed the old teacher

Build `teacher-v1` as a vertically labelled counterfactual dataset, never from
DEV/CALIB/REPORT. First prove mechanics on 64 states and continuation quality
on 128 disjoint states; only then freeze the 2,048-state pilot balanced across
lead/follow, early/mid/late, attacker/defender, close margins and policy
disagreement. Keep real-human incidents as separate regression cases.

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

First use the model to rank/prune/allocate inside MC. Only a held-out teacher
gain plus a fresh paired win over `mc-strong` earns a direct override or a
larger 10k/50k-state generation wave. A promoted policy becomes the next
continuation teacher: collect -> train -> paired gate -> replace champion ->
relabel, rather than generating millions of labels once from a fixed teacher.

### Lane C — learn beyond MC imitation

In parallel with teacher work, repair the DMC2 role-sign target and snapshot
contract, then run two faithful synchronous baselines:

- Suphx-style policy learning with scheduled privileged-feature removal and
  partial-only/distillation controls;
- DouZero-style from-scratch role-conditioned direct Q from signed episodic
  returns and sequential action history.

Keep actors immutable within an iteration, train against a frozen opponent
pool, and gate every candidate against the production champion on paired deal
clusters. A short micro-run must preserve action spread and improve a frozen
held-out metric before filling the fleet. AWAC is a later optimizer on the same
valid replay contract, not a substitute for fixing its target.

### Compute queue

RLCB-C1, V11-v2 and Direct-Q have terminal decisions. Spend hosts on the open
teacher and production boundaries, not extensions of closed runs:

1. **Air now:** finish all eight frozen Teacher-v3 Stage-B gold shards and run
   their exact receipt/gate once. If valid, launch only the separately frozen
   64-state report-LCB continuation audit.
2. **Mini/local now:** finish compiled exact-semantic latency validation. Mini
   may run bounded sub-hour production-class profiles while Air owns teacher
   evidence; it must not improvise Direct-Q or protected-V11 extensions.
3. **After the teacher audit:** use cheap-vs-champion regret and disagreement
   strata to specify the smallest teacher improvement that can beat the live
   champion, then collect/train/gate that version. Do not scale labels merely
   because generation works.
4. **Next learner:** review and continue implementing `SUPHX_MICRO_SPEC.md`,
   the fresh
   Suphx-style privileged-feature-removal contract. It separates legal banker
   burial from simulator-only ownership, tests oracle acquisition before
   removal, and requires equal-work immediate-removal plus distillation
   controls and frozen held-out diagnostics before allocating training
   compute. The feature partition plus four independent role/surface
   policy/value heads plus immutable actor/on-policy learner pass 45/45 focused
   and 122/122 adjacent tests, including exact interrupted resume across a
   `gamma=1` to zero boundary. The lower-rate segment, frozen O0 diagnostics,
   exact launch packet and independent review remain; no training is
   authorized. The terminal 144M report cannot choose its recipe.
5. **Other search lanes:** structured bury or sampled exact endgame must be
   explicitly reparented to confirmed report-LCB with matched null/work before
   any strength run.
6. **Scale only winners:** larger teacher/RL waves and full-game confirmation
   are reserved for candidates that first clear their independent local gate.

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
