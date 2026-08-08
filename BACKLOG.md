# Backlog

Last re-derived: 2026-08-08 15:45 EDT.

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
  1.138/1.858/3.106s, plus responsive claim/reconnect/X-ray checks. The first
  ordinary post-fix human room then completed five rounds with 195 search-like
  bot turns (`compute_seconds >= 0.05`): search p50/p95/max
  0.896/1.714/1.906s and full-turn
  0.904/1.716/1.907s. All 249 bot turns were offloaded and isolated. Continue
  monitoring concurrent rooms; a faster Fly CPU remains a separate lever.
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
- **Suphx O0 is terminal SELECT NONE.** Independent review bound exact packet
  SHA `6d4e6772…1ed65`; admission SHA is `67f79f29…3e590b`. All six frozen
  arms completed exactly 64 updates and exercised the real 32-update
  teardown/resume boundary. Terminal gate SHA `592a009a…bd407c` independently
  replays with `verified=true`. Oracle-minus-initial was `+0.336` with LCB
  `+0.274`; oracle-minus-public was only `+0.073` with LCB `+0.0025`.
  Per-seed oracle-minus-public means were `+0.344/-0.207/+0.082`, so the
  preregistered all-seeds robustness condition failed even though every other
  correctness, information-boundary, entropy, work and aggregate-efficacy
  criterion passed. O1 is not authorized. Do not extend iterations, add seeds,
  reopen DEV for tuning or reinterpret this as a strength result; diagnose the
  near-uniform policy/weak oracle-use mechanism and preregister a fresh learner.
- **Teacher-v3 Stage B passed; champion audit-v2 ended in operational refusal.** All 8/8 gold
  shards validated and the one-shot gate passed with
  upper regret bound `0.0195 < 0.10`. Audit v1 then exposed a deterministic
  publication bug before any label launched: its verifier rejected its own
  still-owned hard-linked partial. Preserve v1 as failed evidence. Exact
  evaluator repair `1866132` and controller `edc923f` use a fresh v2 run/root,
  keep states/folds/continuation unchanged and pass live Air preflight. The
  first controller review found an opaque-receipt bypass; `edc923f` now parses
  and pins exact receipt plus preparation identity. The revised review passed;
  receipt `ce51b826...71d0` and preparation `7f89a86c...6605` were valid, but
  shard 6 stopped on an incomplete champion report fold and the supervisor
  terminated its siblings. No label final or gate exists. This is no ML
  verdict. Exact score-free diagnostics and the retry/underfill semantics now
  independently pass: the intended 30+300 accepted-world estimator is
  unchanged, failed draws may retry only inside fixed caps, and all counters
  must reconcile. The outcome-blind exact complement was independently
  reviewed and frozen at `82da0fd8…9d94c`. Exact evaluator `f78e904` and Mini
  controller `0399591` passed no-write preflight over all 22 inputs and exact
  launch review. Receipt `e293858c…a10d` and preparation `83892930…c39`
  reopened cleanly; the reviewed eight-shard audit is now running on Mini.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **T1 / Lane A production latency — COMPLETE / LIVE MONITOR** | Keep the first stronger-than-MC production policy enjoyable to play | Fly release 17 runs exact `latency-cd6789e` / `047bcfe4...5b300`. Health, native activation, claim, reconnect, stale-discard, X-ray isolation and concurrent WebSocket responsiveness passed live. Keep release 16 as the runtime rollback and `mc-strong` as the separate policy rollback; collect ordinary human-room timing before considering a CPU resize. |
| **T1 / Lane A.1 V11pair — COMPLETE / SELECT NONE** | Preserve the learned milestone without forcing it into the champion | Artifact repair passed; the frozen rule rejected protected composition. Keep v11 as a bounded proposer/ranker and teacher diagnostic only. No protected-anchor run is authorized. |
| **T1 / Lane B teacher — RUNNING ON MINI** | Determine whether cheap N=30 choices remain good under the full champion continuation | Exact launch review passed. One-shot receipt `e293858c…a10d` and preparation `83892930…c39` reopened with zero post-preflight problems; one supervisor owns 8/8 shards for run `teacher-v3-report-lcb-audit-v3-mini-149m`. Wait for one terminal gate; no retry, Stage C or training is implied. |
| **T2 / live parent + S3 reparenting — COMPLETE / REVIEW PASS** | Make every new search mechanism challenge the bot people actually play | Claude independently passed exact `05ea1d1` / material `66be133c…e17c`, reproduced parent output `5f9ddbfb…8402`, reopened RLCB-C1 and falsified stale-S0 re-entry. S3a/S3b retain their narrow v2 boundaries. This authorizes only the predeclared score-free S3b Mini preflight, not strength compute. |
| **T2 / S3a structured bury — MECHANISM PASS / DUEL DESIGN NEXT** | Test whether a much wider, strategy-aware kitty ballot finds better once-per-round decisions | The reviewed 512-state Mini screen completed and separately verified: structured-minus-live-incumbent `+0.997 +/- 0.401` (LCB `+0.597`), minus legacy-four `+0.878 +/- 0.380` (LCB `+0.498`), and minus trigger-matched random widening `+3.253 +/- 0.561` (LCB `+2.692`). Design and review a fresh mirrored full-game duel plus champion-matched null. This screen cannot promote or deploy. |
| **T2 / S3b sampled exact endgame — PREFLIGHT TERMINAL HOLD / NO SCREEN** | Replace heuristic continuation with bounded exact solving when every hand has at most four cards | The exact predeclared Mini attempt reached the frozen cumulative `250,000`-node ceiling in its first treatment cluster and failed before publishing a receipt. No score/raw record survived and the 2,048 screen is unauthorized. Never rerun or raise the cap in v2; a future v3 must separately review a narrower threshold, a solver optimization, or a different bound. |
| **T1 / Lane C Direct-Q — COMPLETE / SELECT NONE** | Learn from the failure without selecting its positive gameplay tail | Preserve aggregate SHA `1fa6789e…791`; do not deploy, extend or mutate the 144M recipe. The next learner requires a separately frozen Suphx-style or other role-correct microbaseline gate. |
| **T1 / Lane C Suphx O0 — COMPLETE / SELECT NONE** | Test whether a full-information policy can learn before spending compute on feature removal | Preserve gate SHA `592a009a…bd407c`. Both ensemble LCBs passed, but seed 1 lost to its equal-seed public arm (`-0.207`), failing the registered robustness conjunction. O1 is closed for this exact recipe; the next learner needs a fresh packet, not an O0 extension. |
| **RLCB-C1 fresh confirmation — COMPLETE / ARTIFACT-ONLY CONFIRM** | Close formal report-LCB superiority | 2,048/2,048 fresh clusters, exact doses, zero stream collisions, sane null and positive superiority LCB. The late dirty-doc supervisor refusal is bound by non-replay closeout SHA `06dd487d…b7aae5`; preserve aggregate SHA `83f5a9df…f5ef5ea`. No extension or S0c reinterpretation remains. |
| **Formal S0 — COMPLETE / SELECT NONE** | Preserve the burned S0c evidence boundary | Closeout `ef0a365…fde9a`, terminal parent `ca556c2`, no parsed outcomes, no retry/extension, and an empty S0 service namespace. There is no remaining S0c work. |

### Adversarial-review hardening before reuse

Claude's 2026-08-08 broad review reproduced every closed result and required
no rollback. Scheduler direct/speculative equivalence and the Teacher
zero-exit guards are now mutation-covered in `edc923f`. The remaining findings
do not reopen terminal outcomes; they gate reuse of the named machinery:

- before another V11 repair/revalidation, add real-loader record-digest and
  evidence-grade fixtures plus an asymmetric contrast-sign fixture;
- before another Direct-Q screen, pin treatment-minus-control and
  start-minus-final signs with asymmetric fixtures;
- before an O0 successor, add semantic-replay and payload-identity red-path
  tests, then require kitty-to-banker card flow or explicitly legal relabeling;
- before reusing RLCB-C1 or Stage-B readiness, pin record `run` to manifest
  run ID and make worker discovery accept absolute script paths by basename.

### Strategy-audit decision

Accept the audit's spine: report-LCB is the only current champion, stop V11 as
a direct lane, prioritize counterfactual Teacher data, and merge Direct-Q/O0
into one learner-mechanism battery. Tighten execution in four places:

- the proven mechanism is not merely “more search” or even merely a split; it
  is fixed-challenger paired re-evaluation on disjoint worlds plus a positive
  conservative LCB;
- Stage B established cheap-versus-gold agreement on its sampled states, not
  on the mined high-SE/disagreement tail. Stage C must escalate uncertain
  states to gold/exact-late labels and separately gate hard-tail regret;
- v11pair is an admissible proposal diversifier, not a confirmed strength
  mechanism. Compare its proposal recall/regret with same-budget random
  diversification; never use its relative deltas as scalar leaves;
- do not bundle CRN repair, entropy control, dose and target changes into one
  O0-v2 conclusion. Use CRN and at least eight training seeds as the common
  evaluation design, then factorially isolate sharpening/dose mechanisms.

The S3a 136M/512-state asset is a **non-promotable state-level mechanism
screen** and is now terminal PASS: all three frozen clustered LCBs are
positive. That authorizes design of a fresh full-game duel, not a strength
claim. The reviewed v2 parent binds both S3 lanes to exact
`mc-s0-report-lcb` and blocks formal-S0/`mc-strong` re-entry. S3b v2 stopped at
its operational preflight after a first-cluster exact-budget overflow; its
2,048/8,192 path is closed. S3a now needs a new mirrored full-game runner and
champion-matched null on fresh deal clusters.

## Milestones

### T1 — Champion flywheel launch: fresh Teacher asset/controller gate

T1 is complete in four of five lanes: production report-LCB/release 17 is
live, RLCB-C1 confirmed it, V11 direct-v2 selected none, and Direct-Q/O0 each
reached an honest stop. Teacher audit-v2 produced no valid terminal verdict.
Its diagnosis, retry semantics and untouched complement have passed review,
but T1 is still not complete. The fresh evaluator/controller and exact launch
packet passed review; the valid audit is now running on Mini. Preserve its
first terminal gate, independently verify it, then route it through reviewed
adapter v2 to Stage-C design or redesign/stop.

### T2 — First live-champion challenger: active in parallel

**Plain-English objective:** get one genuinely new search mechanism into an
honest comparison with the report-LCB bot people are playing today, while
turning the Teacher result into a data plan that can eventually exceed that
bot rather than imitate it.

| order | deliverable | completion gate |
|---|---|---|
| **T2.0 — COMPLETE / REVIEW PASS** | Version one reusable live-champion parent contract for S3 evidence | Exact `05ea1d1` / material `66be133c…e17c` independently passed at 09:54. Review reproduced the real parent output and falsified anchor drift, formal-S0 re-entry and consumer-boundary widening. No strength or production authority was conveyed. |
| **T2.1 / S3a — COMPLETE / MECHANISM PASS** | Run the 512-state structured-bury mechanism screen under its fresh v2 namespace | Eight shards and the aggregate completed; separate verification passed. All three state-level LCBs exceed zero. Aggregate `74aa5a39…396cd`, final `d3f2b1ab…69a6b`. This authorizes only the next deliverable: a separately preregistered full-game duel. |
| **T2.2 / S3b — COMPLETE / TERMINAL HOLD** | Run the score-free two-cluster throughput preflight for the report-LCB sampled-exact lane on Mini | At exact head `cd44ea8`, the first treatment cluster raised `ExactEndgameBudgetExceeded: max_nodes=250000`; exit 1, no `1/2` completion, receipt or partial. This falsifies the v2 zero-overflow feasibility condition. Same-recipe retry/cap change/fallback is unauthorized. |
| **T2.3 / S3b v2 — CLOSED / UNAUTHORIZED** | Launch the 2,048-cluster complete-round sampled-exact screen when capacity and preflight permit | The required preflight did not pass and the zero-overflow invariant failed before a cluster completed. Preserve the seed and failure. A fresh v3 design/review—not a mutation of this attempt—is required before more sampled-exact compute. |
| **T2.4 / Teacher — AUDIT RUNNING / ADAPTER REVIEW PASS** | Convert a valid terminal audit into a Stage-C contract | Exact Mini launch review passed; one supervisor owns 8/8 audit shards. Claude independently passed exact adapter `5b26c4b`, including canonical paths, literal parent populations/receipt nonce, Python runtime and symlink refusals. Independently verify the first terminal gate, then create and verify one adapter artifact; neither branch launches compute. |
| **T2.5 / learner — INTEGRATION MERGED / RUNNER PACKET NEXT** | Write, but do not yet bundle-run, a fresh O0-v2 mechanism battery | Claude passed exact `dd730a8` / material `639c259b…a0494b`; equivalent merge `59a23c7` passes 22/22 focused and 112/112 Suphx. Freeze a fresh population/runner/gate packet without changing dose, target, feature schedule, optimizer, or margin cell. No training is authorized yet. |
| **T2.6 / S3a duel — DESIGN / REVIEW NEXT** | Test whether the state-level structured-bury gain survives full games against production | Freeze fresh mirrored deal clusters, exact report-LCB parent, structured treatment, champion-matched null, equal work, clustered utility gate, terminal stop rule and one-shot controller. Independent review precedes compute; no tuning from the inspected 512 states. |

T2 launch readiness is achieved: T2.0 passed and S3a produced a valid positive
mechanism screen. The next milestone is stronger: get S3a into one honest
fresh full-game duel while advancing the Teacher and O0 implementation gates
in parallel. It does not require manufacturing a positive duel result.

### Fleet order today

1. **Mini:** running the reviewed fresh Teacher audit with 8/8 label shards.
   Keep this one supervisor exclusive; do not duplicate, retry or migrate it.
2. **Air:** currently idle. Preserve both failed Teacher roots and frozen
   source assets; Air is evidence source/fallback, not the selected run host.
3. **Local/product:** continue passive release-17 timing collection; no policy
   or production change is part of T2.0.

### Parallel implementation queue — never wait idly for a run

Compute and coding are separate queues. Keep at most one reviewed next job
ready for each free host, but continue the first unblocked implementation item
whenever a review or run is live:

1. **COMPLETE:** exact `05ea1d1` T2.0 live-parent review passed;
2. **MECHANISM PASS:** S3a's reviewed 512-state screen passed every frozen
   LCB; design/review a fresh full-game duel and champion-matched null next;
3. **RUNNING ON MINI:** exact 30+300 accepted-world semantics and
   historical/current state provenance are frozen; one reviewed supervisor
   owns 8/8 fresh audit shards and must end at one terminal gate;
4. **ADAPTER-V2 REVIEW PASS at `5b26c4b`:** the fresh terminal adapter
   precommits PASS to a hard-tail Stage-C design and FAIL/INCONCLUSIVE to the
   existing-evidence diagnostic only, binds the exact v2 gate/supervisor and
   Mini provenance, and authorizes no compute;
5. **INTEGRATION MERGED at `59a23c7`:** keyed common-random-number streams, a
   shared public projection and the two-sided logit-margin cell are bounded;
   freeze a fresh runner/population/gate packet;
6. version the shared `ExperimentSpec`/progress receipt so reviewed jobs are
   launch-ready without making promotion or evidence decisions automatic;
7. if all strength work is review-blocked, use the slot for encoder-provenance,
   native parity/performance or frontend correctness tests—not an unregistered
   strength run.

Utilization means useful admitted work, not filling every core. Never duplicate
a sealed attempt, peek at a live score, weaken a cap after seeing strength, or
run a stale-parent job just to avoid an idle machine.

### Explicit non-goals

- Do not reopen, score or “complete” S0c. It is terminal and burned.
- Do not rerun or extend V11 direct-v2, Direct-Q or Suphx O0.
- Do not call an S3a state-screen PASS a bot-strength result.
- Do not scale Teacher data simply because Stage B passed; a valid repaired
  audit and reviewed hard-tail contract must decide what labeler deserves scale.

## Strength design ownership

`BACKLOG.md` deliberately does not repeat the full AI program. The current
design rationale, literature constraints, model lineage, data contract and
three-lane flywheel live in `RL_PLAN.md`; durable policy conclusions and exact
terminal numbers live in `AI_POLICIES.md`.

The queue above implements that design:

- **Lane A:** S3a structured bury and S3b sampled exact endgame challenge the
  live report-LCB policy directly.
- **Lane B:** Teacher-v3 decides whether the cheap counterfactual labeler is
  trustworthy, especially after a separate hard-tail gate, before training or
  scaling.
- **Lane C:** a fresh mechanism battery uses Direct-Q/O0 failures to isolate
  robust oracle use beyond MC imitation; it does not extend either closed run.
- **V11:** bounded proposal/ranking/diagnostic hypothesis only, always against
  a same-budget random diversifier; no direct, protected-anchor or scalar-leaf
  revival.

Adding a new strength task here requires a named champion parent, one falsifiable
mechanism, a minimum control/null, fresh population, screen metric, terminal
stop gate and the result that would justify larger compute.

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
- [x] **Faithful synchronous microbaselines reached terminal evidence.**
      Direct-Q completed and selected none after held-out role-MSE failures;
      Suphx O0 completed and selected none after seed robustness failed. The
      results diagnose different mechanisms and authorize no extension/O1.
- [ ] **Fresh learner-mechanism battery.** Use a new population, common-random-
      number evaluation and at least eight independent training seeds. Hold
      those constant while isolating sharpening, dose, feature-use and
      target/credit hypotheses; do not bundle every change or tune on O0 DEV.
- [ ] **Absolute value contract.** If a leaf is revisited, predict a calibrated
      scoring-bracket distribution or expected signed level utility under a
      named belief, role and continuation policy. `v11pair` is only a bounded
      proposal/ranking diagnostic on its exact ballot, not a cross-state scalar
      leaf or direct/protected candidate.
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
