# Backlog

Last re-derived: 2026-08-05 21:39 EDT.

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
  fail-closed sharded runner are registered. The clean DEV audit selected
  R=300; **no S0 strength result exists yet**. The bounded S0a 2,048-cluster
  screen is the next authorized fleet job.
- The roadmap has three parallel strength lanes: S0 search, clean teacher/model
  iteration, and faithful role-conditioned self-play. Do not wait for S0a to run
  the bounded teacher/RL entry gates on other workers.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **S0a search strength** | Run the frozen decision-rule screen now that the code gate is closed | Eight 256-cluster shards (seeds 132M) compare report-mean, report-LCB, equal-work uniform, null and current. Aggregate only with `s0_aggregate.py`; carry one rule by the registered screen criterion, never promote from this block. |
| **S0b allocation** | If S0a selects a report rule, test allocation separately | Run exactly one of `s0b-mean` / `s0b-lcb`: deterministic adaptive must beat both uniform-report and random allocation by paired point estimate. Freeze one survivor for an independent 8,192-cluster superiority confirmation. |
| **S0b v11pair utilization** | Use the one confirmed learned improvement as MC's protected root anchor | First revalidate frozen `rl-override-v11pair` directly against current compiled N=30 on one fresh 2,048-cluster paired block. Then test an equal-work hybrid that preserves the full current ballot and N=30 worlds but protects v11's thresholded choice instead of SmartBot's. Hard pruning, pairwise-as-leaf and search/no-search gating are not this experiment. |
| **S1 teacher/model** | Execute `TEACHER_V1_SPEC.md`, then earn scale | Pass the 64-state mechanics and 128-state gold-continuation gates before the 2,048-state wave. This is a new training/challenge asset, not an enlargement of DEV-512. Train three-seed action ranker + calibrated outcome head; scale only if untouched regret and paired games improve. |
| **S2 self-play RL** | Run faithful role-conditioned synchronous microbaselines | Unit-test attacker/defender signs, separately version reward targets, and bind immutable actors. Then run Suphx-style feature removal and DouZero-style direct-Q baselines for 20–30 minutes; stable spread plus held-out improvement earns fleet scale. |
| **S3 structured search** | Attack decisions outside ordinary play selection | In parallel, screen structured MC bury sourcing and sampled exact solving for the final ~4 tricks. Each changes a different once-per-round/tactical bottleneck and must duel the production champion directly. |
| **Frontend ship gate** | Run one bounded multi-tab soak | Cover join, simultaneous seat claim, disconnect-to-bot, reconnect/takeover, stale/displaced sockets, second absence, private-hand visibility, chat before initial state and >50 messages, and saved-room invite precedence. |
| **Evaluator boundary** | Repair legacy full-game cutoff semantics | A cutoff must return an explicit tie/refusal, never silently award team 0. Keep the engine's uncapped house-rule progression; the `+3` clip remains a separately versioned RL target. |

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
3. independent 8,192-cluster survivor-vs-current confirmation. Its paired 95%
   interval must be above zero to promote.

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

The new minimal hybrid keeps every current candidate and the full N=30 common-
world budget. On states where the frozen 0.02 v11 rule overrides SmartBot,
reorder that action to candidate 0 so the existing five-point MC margin protects
the demonstrably stronger learned prior; keep Smart's action in the ballot and
leave `TRACTOR_LOCK` unchanged for the first attribution arm. This tests anchor
quality, not sourcing, pruning, latency or leaf evaluation.

Required sequence:

1. **Current compatibility:** one immutable 2,048-cluster paired block from
   fresh 121M deal seeds: frozen v11pair versus compiled `mc-strong`, with an
   mc-vs-mc null, strict counters and checkpoint NPZ SHA-256
   `cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003`.
   Direct v11 promotes only on superiority; an interval containing zero is not
   equivalence.
2. **Anchor implementation:** exact same action set/worlds/candidate-world work
   as N=30; only candidate order/protected anchor changes. Record Smart and v11
   choices, predicted delta, MC paired delta and final reason. A same-trigger
   random-action anchor is the attribution control.
3. **Anchor strength:** primary contrast v11-anchor minus Smart-anchor on fresh
   paired signed level utility. Do not combine it with adaptive/confidence
   changes until each wins separately.
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
DEV/CALIB/REPORT. The first gate is 2,048 states balanced across lead/follow,
early/mid/late, banker/attacker/defender, candidate count, close margins and
policy disagreement. Include a small incident tranche from real human games.

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
   outcome labeller, including the union of Smart/v11/current/proposed actions;
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

1. Air: shard the 2,048-state teacher pilot and endgame/bury screens.
2. Mini: implement and replay the confidence allocator plus challenge corpus.
3. Training device: three model seeds and data-scaling curves as teacher shards
   arrive.
4. Both machines: fixed paired evaluation shards only for candidates that pass
   their local gate.

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

- [ ] **Role-correct target test.** DMC2 signs terminal returns by acting team
      but subtracts an attacker-perspective oracle from defenders without
      flipping it. Fix and falsify with attacker/defender antisymmetry before
      interpreting any AWAC/DMC result.
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
