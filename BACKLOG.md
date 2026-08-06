# Backlog

Last re-derived: 2026-08-06 14:37 EDT.

This is the execution queue, not an experiment notebook. Durable policy
conclusions belong in `AI_POLICIES.md`, model history in `RL_PLAN.md`, job
artifacts in `JOBS.md`, and detailed reviewer discussion in
`HANDOFF_REVIEW.md`.

## Current state

- Production runs compiled `mc-strong` (N=30). Its frozen-current confirmation
  was `+0.222 +/- 0.140` paired signed level utility versus N=10 over 504 fresh
  deal clusters; the null was flat. N=60 versus N=30 was
  `-0.002 +/- 0.119`, so another uniform-N dose is not justified.
- The six-arm DEV-512 ballot experiment is complete and selected **NONE**.
  The current ballot had the lowest equal-work regret; quota widening did not
  beat random widening, and equal large work favoured more MC on the incumbent
  ballot over brute-force action expansion. This is an offline screen, not a
  full-game strength result.
- CALIB-512 and REPORT remain sealed and unscored. The abandoned ballot lane's
  CALIB, online-confirmation and learn-from-winner stages are **NOT REACHED / CLOSED**.
- DEV-512 was a design screen, not training data or an online-strength proof.
  Its primary half-width was 0.337; at the same variance 2,048 states would
  still be about 0.169, and resolving a 0.10 offline effect would take roughly
  5,800 states. Do not append to the inspected DEV set or try more arms on it.
- S0's code gate is complete: exact disjoint report folds, deterministic/random
  adaptive allocation, equal-work controls, replayable decision records and a
  fail-closed sharded runner are registered. S0a is **COMPLETE / ACCEPTED** on
  authoritative Mini: 8/8 clean shards and 2,048 clusters selected
  `mc-s0-report-lcb` (`+0.353 +/- 0.069` versus current; direct
  `+0.293 +/- 0.066` versus equal-work uniform; true null
  `+0.008 +/- 0.070`). Aggregate SHA-256 is
  `0fcd53d4f782a705bfef9ea8ec6155c49db45d76ec71ce25891a9f864413de49`.
  This is a mechanism-screen survivor, not a deployment result. Its exact
  parent-bound `s0b-lcb` block launched 8/8 Mini shards at 06:58 EDT. Air's
  duplicate records may never be pooled. At 14:36 all eight workers were live
  near 98–99% CPU with eight partial manifests, no final or FAILED marker, and
  clean frozen compiled+strict provenance. No partial effects are admissible.
- The separate V11 direct-current compatibility block is **RUNNING ON AIR**:
  eight clean compiled+strict 256-cluster shards at `e66b90b`, exact seeds
  121,000,000–121,002,047 and the SHA-pinned `ep07.npz`. At 14:36 all eight
  workers were live near 88–90% CPU with eight partial manifests, no real final
  or FAILED marker, and exactly 1,260/1,536 durable rows (82.0%) flushed per
  shard. The only final-named file is the non-evidence `_SMOKE`. No record,
  partial score or effect has been opened. This block retains its original
  direct-superiority verdict and cannot promote a policy.
- Before opening any V11 result, commit `7ecffd5` separately predeclared the
  protected-composition estimand. Standalone v11 superiority is not logically
  required for a search-protected proposal to help: a protocol-valid direct
  block with a sane null may admit the non-promotable 2,048-cluster screen on
  seeds 137M, after terminal S0. A PASS alone admits an independent
  8,192-cluster confirmation on seeds 138M. The frozen direct verdict is never
  rewritten; details are in
  `docs_archive/v11-protected-composition-protocol-2026-08-06.md`.
- The roadmap has three parallel strength lanes: S0 search, clean teacher/model
  iteration, and faithful role-conditioned self-play. They do not share
  evidence, and each must respect its own launch gate. Teacher entry code is
  now closed and Air preflight is **READY_AFTER_V11**. S2's exact synchronous
  infrastructure is code-closed at `e49cf60`; the next gate is a concrete,
  reviewed Suphx- or DouZero-style algorithm plus its own exact resumed-output
  test, not another generic checkpoint repair.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **S0a search strength — COMPLETE** | Frozen decision-rule screen accepted on authoritative Mini | Eight clean 256-cluster shards selected report-LCB. Independent recomputation matched the registered aggregate; this block cannot promote. |
| **S0b allocation — RUNNING** | Test allocation separately under the selected LCB report rule | Eight exact parent-bound `s0b-lcb` shards cover seeds 134,000,000–134,002,047 on Mini. Adaptive and uniform-report are complete on every shard; all eight are running the third/final random-allocation arm. Deterministic adaptive must beat both controls by paired point estimate; otherwise report-LCB survives. Do not score partials. |
| **S0c confirmation** | Independently confirm exactly the S0b survivor | Eight 1,024-cluster shards on seeds 135,000,000–135,008,191 compare survivor, `mc-strong-null`, and current. Promote only if survivor-current and survivor-null paired 95% lower bounds are >0 and the null does not clear; otherwise close S0 SELECT NONE. |
| **S0d terminal packet + cleanup** | Turn the terminal S0 result into one auditable decision | Independently regenerate and byte-compare the return packet, verify every artifact/hash/counter/seed/runtime field, refuse unexpected S0 workers, then remove only the packet-proved services. Apply a production policy change only on PROMOTE; SELECT NONE leaves `mc-strong` unchanged. A Fly restart remains a separately authorized quiet-room action. |
| **V11 direct compatibility — RUNNING ON AIR, SEPARATE FROM S0** | Establish whether frozen v11pair still improves on today's N=30 contract | Eight 256-cluster shards at clean `e66b90b` cover exact seeds 121,000,000–121,002,047. At 14:36 all eight were healthy with eight partials/no real finals; every shard had flushed exactly 1,260/1,536 rows (82.0%) and no effect was opened. The final-named `_SMOKE` is non-evidence. Apply the original rule exactly: V11-current and V11-null LCBs >0 and true-null interval contains zero. Never promote from this block. |
| **V11 protected composition — CODE GATE CLOSED / WAITS FOR DIRECT + S0** | Test whether search can retain good v11 proposals while rejecting its bad tail | `7ecffd5` blind-froze the estimand; `d2229d0` implements it. The runner binds the exact `e66b90b` direct source/hash contract, preserves its original verdict, reopens every screen shard/record for confirmation, uses champion-matched nulls and exclusive publication, and reports score-blind progress. A sane direct null plus terminal S0 admit the 2,048-cluster 137M screen even if standalone v11 is neutral. All three anchor LCBs must exceed zero and the null interval contain zero; PASS alone admits the disjoint 8,192-cluster 138M confirmation. Never use v11 as a scalar leaf. |
| **S1 teacher/model — ENTRY CODE GATE CLOSED / CAPTURE NEXT** | Test whether a clean counterfactual teacher is worth scaling | Commit `23a9e0b` binds the exact `teacher-v1-entry-120m-v1` packet (1,024 deals, seeds 120000000–120001023, 8 shards) through capture, diagnostics, state sets, canonical label partitions and gates. Exclusive pre-label receipts bind role, run, nonce, exact state-set bytes and executable identity; Stage A reopens primary/rerun receipts and Stage-B freeze reopens all 16 Stage-A artifacts. Independent review is PASS; teacher/pilot acceptance is 134 passed, 23 skipped. No evidence exists. When a whole machine is free, run 8/8 capture then diagnose/freeze; Stage A is 64 states with an independent receipt-bound rerun, Stage B is 128 disjoint states and passes only if gold regret U95 <=0.10. |
| **S2 self-play RL — SYNCHRONOUS INFRASTRUCTURE PASS / ALGORITHM NEXT** | Implement faithful role-conditioned synchronous microbaselines | `e49cf60` closes exact interrupted/resumed state, BaseException poisoning/rollback, named-vs-global RNG enforcement, learner/optimizer hidden configuration, frozen collector state, algorithm-contract batch identity and exclusive candidate publication. The focused acceptance is 46/46. This is an algorithm-neutral chassis only: implement one reviewed Suphx/DouZero collector/loss that loads the verified actor and passes its own bounded uninterrupted-vs-resumed output match before any training claim. |
| **S3a structured bury search — CODE GATE CLOSED / WAITS FOR TERMINAL S0** | Improve the once-per-round decision that ordinary play search never touches | `e946696` registers the 512-state 136M screen with banker-only sources, literal terminal-champion candidate zero, exact equal candidate-world work, disjoint named folds and legacy-four/trigger-matched-random controls. Its consumer reconstructs each named deal, redraws both folds and replays every raw scorer value; tampered digest and wholesale-score falsifications fail. Focused acceptance is 27/27. After terminal S0, a PASS may authorize only a fresh full-game duel design, never promotion. |
| **S3b sampled exact endgame — MECHANICS CHALLENGE PASS / STRENGTH PROTOCOL NEXT** | Replace heuristic continuation where only about four cards per hand remain | Commits `b807ad1` and `2370a27` close the feature-off core and bounded mechanics gate. Four frozen real late states x four named sampler worlds completed all 140/140 exact frontier evaluations, 16 shared sessions, 130,989 nodes and 97,834 cache hits with zero refusal/overflow under the cumulative 250k-node/session cap. This proves bounded mechanics only. Next register a terminal-champion-matched feature-on policy and fresh paired full-game screen; it remains a sampled perfect-information oracle, not exact imperfect-information Shengji. |
| **Frontend ship gate — COMPLETE / PASS** | Keep the multiplayer ownership state machine shippable | The real multi-socket server suite passes 33/33, including join, simultaneous claim, disconnect/bot cover, reconnect/takeover, stale/displaced sockets, repeated absence, token rotation and private-hand visibility. Browser connection/intent tests pass 14/14, including pre-state chat, >50-message rollover and invite-over-saved-room precedence; lint has only existing fast-refresh warnings and the production build passes. |
| **Evaluator boundary — COMPLETE / PASS** | Keep arbitrary full-game cutoffs out of strength claims | `play_game` now raises typed `FullGameCutoff` for every unfinished max-round exhaustion, tied or unequal, while retaining the partial state only for diagnosis. Legacy mirrored `evaluate` propagates the refusal and returns no partial score. Completed-game results are unchanged; the one-round registered evaluator, uncapped engine progression and separately versioned `+3` RL target are untouched. |

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

The executable sequence is:

1. S0a: current, true null, uniform+report-mean, uniform+report-LCB and uniform
   high-work control over 2,048 fresh clusters (8x256, seeds 132M);
2. S0b: only the selected report rule, comparing uniform, deterministic adaptive
   and matched random allocation at exact `30K+600` work; and
3. independent 8,192-cluster survivor/current/null confirmation on frozen seeds
   135M. Survivor-current and survivor-null paired 95% lower bounds must both
   exceed zero while null-current does not clear; otherwise S0 selects none.

Primary deployment estimand is paired signed level utility per fresh deal
cluster with seat/team flips. Using conservative observed cluster SD ~1.60,
about 2,048 clusters gives roughly 80% two-sided power for `+0.10` levels/deal;
`+0.05` needs roughly 8,000. Recompute from the frozen protocol, then register
one block with no extension. Random game seeds are not limited by the 3,842
unused corpus deals; that scarcity applied to the frozen state instrument, not
fresh online self-play.

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

Required sequence:

1. **Current compatibility:** one immutable 2,048-cluster paired block from
   fresh 121M deal seeds: frozen v11pair versus compiled `mc-strong`, with an
   mc-vs-mc null, strict counters and checkpoint NPZ SHA-256
   `cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003`.
   Direct v11 promotes only on superiority; an interval containing zero is not
   equivalence. `server/scripts/v11_revalidate.py` now implements this exact
   block and cannot promote production.
2. **Anchor implementation:** exact same action set/worlds/candidate-world work
   as N=30; only candidate order/protected anchor changes. Record Smart and v11
   choices, predicted delta, MC paired delta and final reason. A same-trigger
   random-action anchor is the attribution control. Registered policies are
   `mc-v11anchor` and `mc-v11anchor-random`; implementation is complete, but
   neither has strength evidence.
3. **Anchor strength:** primary contrast v11-anchor minus Smart-anchor on fresh
   paired signed level utility. Freeze its reference, seeds, sample size and
   advancement rule only after S0 names the terminal production champion. Do
   not combine it with adaptive/confidence changes until each wins separately.
4. **Soft allocation, later:** after S0 has valid simultaneous/time-uniform
   inference, allow v11 only to prioritize unresolved candidates after a common-
   world floor. Compare it with uncertainty-only and random priorities at exact
   work. Never revive hard top-k pruning.
5. **Continuation probe:** teacher-v1 Stage B may compare v11pair-as-policy
   continuation with heuristic/champion continuation. This is a valid policy
   use, unlike a v11 leaf, but earlier stronger-rollout ties make it lower
   priority than the anchor.

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

The bounded P0 certificate passed at `aea3774`; keep compute occupied with
staged strength work rather than one speculative monolith:

1. Mini remains authoritative for the live S0b/S0c chain; do not displace or
   pool those eight workers. All current S0 capacity is productively occupied.
2. Air is running the whole immutable V11 direct-compatibility block: 8x256
   clusters at clean `e66b90b`, seeds 121,000,000–121,002,047. Aggregate only
   after 8/8 final manifests; never pool it into S0.
3. While both machines compute, keep local work bounded and non-competing.
   S3a's replay gate is closed at `e946696`; S2's generic synchronous boundary
   is closed at `e49cf60`; and V11 composition is closed at `d2229d0`. S3b's
   bounded mechanics challenge is already PASS, so its terminal-champion-
   matched full-game protocol is the active local code slice. Do not launch an
   S3 strength block before S0 supplies the terminal champion and each
   reference is frozen.
4. Preserve the original direct-V11 verdict, then use the separately blind-
   frozen `7ecffd5` composition rule. After a protocol-valid direct aggregate
   and terminal S0, the 137M screen may run even if standalone v11 is neutral,
   because protected complementarity is the estimand. Only its PASS admits the
   independent 138M confirmation.
5. Teacher entry code is closed and the exact Air packet has passed preflight.
   As soon as every V11 worker exits and its singleton aggregate seals, launch
   the exact 8x128 capture/diagnostic packet on Air before
   inspecting any selector outcome. A Stage-A pass authorizes only the
   128-state teacher gold gate. A Stage-B
   pass authorizes implementing and sharding Stage C; it does not silently
   launch millions of labels.
6. Training hardware receives three-seed scaling runs only after a valid frozen
   teacher asset exists. Full-game fleet evaluation is reserved for candidates
   that pass their local data/model gate.
7. During the user-authorized six-hour autonomous window, Codex owns singleton
   transitions and pushed documentation. Claude may post a concrete review or
   blocker, but must not duplicate V11 aggregation, teacher capture, or any S0
   phase. Local coding continues on bounded S3b and concrete direct-Q gates
   while both evidence hosts are occupied.

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
- [ ] **Dataset contract.** New training records must bind exact state replay,
      role/perspective, legal action multiset, `BallotSpec`, sampler, continuation
      policy, utility target, actor checkpoint and source/split digests. The
      high-N and late corpora are valuable state reservoirs, not clean oracles.
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
- [x] **Exact synchronous self-play infrastructure.** `29c8cc1` and `e49cf60`
      bind learner, optimizer, replay ring, progress, named RNGs, runtime and
      immutable actor/candidate generations; interruptions poison and rollback,
      hidden/global mutable state refuses, and bounded resumed execution matches
      uninterrupted execution. Each concrete algorithm still owes its own
      verified-actor collector and exact resumed-output test.
- [ ] **Faithful synchronous microbaselines.** Separately test a Suphx-style
      privileged-feature-removal policy curriculum and a DouZero-style
      from-scratch role-conditioned direct-Q learner. Do not describe the old
      scalar residual recipe as either paper's algorithm.
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
