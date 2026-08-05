# Backlog

Last re-derived: 2026-08-05 18:45 EDT.

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
- No fleet run is authorized. The next strength idea needs a registered
  feasibility/power design first.

## NOW — ordered by value

| priority | work | exit gate |
|---|---|---|
| **P0 correctness** | Finish the sampler-certifier contract landed in `fc19d26` | Require original/late/deep files, exact 500/500/500 quotas, 120 toys, zero named skips, zero invalid/rejected worlds, `accepted == requested`, clean current HEAD, compiled+strict mode, and one immutable artifact. The current v2 artifact is pre-commit and `tree_dirty=true`; `certified` also does not yet consult rejected/accepted counts, and the CLI default requests 40 toys while the contract requires 120. |
| **Strength design** | Register fixed-budget, common-world **root allocation on the incumbent ballot** | First declare the allocation rule, uniform and random-allocation controls, total candidate-world work, paired deal-seed estimand, smallest worthwhile effect, sample size and one-block stop rule. Reject without running if fresh-deal supply cannot resolve the declared effect. This is not permission to widen the ballot, repeat N=60, or revive learned-prior racing. |
| **RL contract** | Make future learning experiments interpretable before spending fleet compute | Unit-test attacker/defender target signs; version the reward target separately from uncapped game scoring; bind immutable actor checkpoints; then run only the already specified faithful synchronous Suphx-style and DouZero-style microbaselines. A 20–30 minute stability/held-out gate must pass before fleet scale. |
| **Frontend ship gate** | Run one bounded multi-tab soak | Cover join, simultaneous seat claim, disconnect-to-bot, reconnect/takeover, stale/displaced sockets, second absence, private-hand visibility, chat before initial state and >50 messages, and saved-room invite precedence. |
| **Evaluator boundary** | Repair legacy full-game cutoff semantics | A cutoff must return an explicit tie/refusal, never silently award team 0. Keep the engine's uncapped house-rule progression; the `+3` clip remains a separately versioned RL target. |

### Root-allocation feasibility rule

The primary deployment estimand is paired signed level utility per fresh deal
cluster, with seat/team flips inside the cluster. A practical planning threshold
is `+0.10` levels/deal: using the conservative observed cluster SD of about
1.60, roughly 2,048 clusters gives about 80% two-sided power at 5%. A `+0.05`
effect would require roughly 8,000 clusters and is outside the remaining fresh
deal supply. Recompute from the exact frozen protocol before registration; do
not substitute DEV-512 state-level regret variance for online deal variance.

The experiment must compare, at identical total work:

1. incumbent uniform allocation;
2. one deterministic adaptive allocation rule driven only by observations
   available within the search; and
3. a matched random-allocation control.

Use common sampled worlds wherever the algorithms permit, record allocation
and accepted/rejected-world counts per action, and freeze one block with no
extension. A screen may eliminate the idea; only a fresh paired confirmation
may promote it.

## Correctness and data

- [ ] **Current P0 sampler certificate.** Close the exact gate above. The old
      `eea78d2` certificate is not an original+late certificate: one global
      limit exhausted inside `original`, so it covered zero late rows and had
      no skip counters. `c1ceca1` is current-original evidence only. The
      `fc19d26` per-source contract is the right repair but still needs the
      zero-rejection guard and a clean rerun.
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
