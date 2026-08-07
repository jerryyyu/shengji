# Backlog

Last re-derived: 2026-08-07 12:00 EDT.

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
- Corrected V11 direct-v2 compute finished, but publication falsely failed
  because its validator hard-coded capped `+/-1..3` utility while the house
  engine is uncapped. Repair and verify the existing artifact without replaying
  games; do not rewrite its stored result or infer activation that was never
  recorded.
- Teacher-v2 capture finished but the gate refused before diagnostics because
  the v11 actor could emit a semantically legal action outside its canonical
  ballot. Version a fresh actor/gate packet with canonical lead/follow actions
  and a single-action fast path; preserve the refused namespace.
- Mini's next compute is the six score-redacted Direct-Q preflights. Before
  launching protected-V11, structured-bury or sampled-exact strength work,
  explicitly rebind each lane to either the formal `mc-strong` parent or the
  manually deployed report-LCB policy. Do not silently call one the other.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **Production report-LCB — SHIPPED / MONITOR** | Operate the strongest currently supported product policy | Live health must stay `bot=mc-s0-report-lcb, fast=true`; monitor decision time, short/zero-world fallbacks and bot errors. Roll back only on an operational or correctness regression—not because formal S0 was administratively SELECT NONE. |
| **Formal S0 — COMPLETE / SELECT NONE** | Preserve the burned S0c evidence boundary | Closeout `ef0a365…fde9a`, terminal parent commit `ca556c2`, no parsed outcomes, no retry/extension, and an empty S0 launch-service namespace. This closes the old adaptive-confirmation lane without claiming adaptive/report-LCB lost. |
| **Fresh report-LCB confirmation — DESIGN NEXT** | Put the manual production choice on clean formal footing | Freeze a collision-free null and fresh deal block, compare exactly report-LCB/current/null, bind accepted dose and runtime, and use one immutable superiority gate. Do not include adaptive allocation unless a separate experiment first resolves its `+0.037 +/- 0.060` incremental effect. |
| **V11 corrected direct v2 — COMPUTE DONE / ARTIFACT REPAIR** | Recover the already-spent clean-encoder evidence | Fix the uncapped-utility validator in a new artifact-only repair path, reopen exact raw bytes/counters, and bind the aggregate hash regardless of PASS/FAIL. No game replay and no activation claim. |
| **Teacher actor/gate v3 — CODE FIX THEN 64-STATE ENTRY** | Build a stronger counterfactual teacher without repeating the refused packet | Canonicalize v11 actions to the actor ballot, return the sole action directly, add off-ballot falsification, then version fresh disjoint capture -> diagnostics -> exact 64-state freeze. Stop before labels until reviewed. |
| **Direct-Q — PREFLIGHT NEXT ON MINI** | Test whether the bounded role-conditioned learner has a real learning signal | Run six exact 32-iteration treatment/no-step preflights; inspect only wall/storage and semantic receipts. Full 512-iteration screen starts only if the frozen preflight admits it. |
| **Dependent search lanes — REPARENT BEFORE RUN** | Spend the report-LCB and v11 milestones coherently | Protected V11, structured bury and sampled-exact code gates are closed, but their frozen parent semantics predate the manual production change. Version an explicit reference decision before spending compute; then run bounded screen -> fresh confirmation. |
| **Frontend ship gate — COMPLETE / PASS** | Keep multiplayer ownership state shippable | Real multi-socket and browser tests cover join/rejoin, simultaneous claim, bot takeover, stale sockets, private hands and chat. |
| **Evaluator boundary — COMPLETE / PASS** | Keep partial games out of strength claims | Full-game cutoff raises a typed refusal; registered one-round and versioned RL targets remain separate. |

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

Mini is free after formal S0 cleanup. Spend hosts on staged strength evidence,
not more protocol scaffolding:

1. **Mini first:** run the six frozen Direct-Q 32-iteration preflights. They are
   short, score-redacted and answer whether the full bounded learner fits the
   host budget. Launch the 512-iteration screen only on an admitted receipt.
2. **Artifact repair before replay:** finish corrected V11-v2 validation from
   its existing exact raw outputs. The hard-coded capped-utility check is a
   consumer bug under uncapped house rules; no fresh games are justified.
3. **Air next:** version the teacher actor/gate repair, prove zero off-ballot
   actions on the named witness population, then run only fresh capture ->
   diagnostics -> exact 64-state freeze. Stop for review before labels.
4. **Formalize the shipped search:** register one fresh collision-free
   report-LCB/current/null confirmation. Do not reuse 135M, inspect the burned
   S0c outcomes, or fold adaptive allocation into this question.
5. **Reparent dependent screens:** protected V11, structured bury and sampled
   exact endgame must name whether they compare against formal `mc-strong` or
   live report-LCB. Prefer live report-LCB for product strength, but change the
   protocol explicitly and retain matched null/work controls.
6. **Scale only winners:** training hardware gets larger teacher/RL waves only
   after a valid teacher-quality or learning-screen PASS; full-game fleet
   confirmation is reserved for candidates that first clear their local gate.

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
