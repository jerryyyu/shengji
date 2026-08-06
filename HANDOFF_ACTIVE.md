# Active Claude/Codex handoff

Last update: 2026-08-05 20:52 EDT. Historical discussion and superseded gate
packets live in `HANDOFF_REVIEW.md`.

## Current status

- Production: compiled `mc-strong` (N=30), shipped overnight. **Daytime work
  produced no stronger champion.**
- DEV-512: complete, strict aggregate reproduced, **SELECT NONE**.
- CALIB-512 and REPORT: sealed and unscored; the ballot lane ended without a
  DEV winner, so its downstream stages are NOT REACHED / CLOSED.
- Sampler package H: **ACCEPTED / CLOSED** at clean `aea3774`; the v3 artifact
  passed all registered conditions. It is no longer a fleet blocker.
- Fleet: start bounded strength work below. Do not wait for more generic
  correctness review, and do not spend compute extending the inspected DEV set.
- Positive program: (A) confidence-aware/adaptive MC plus structured bury and
  exact-late search; (B) a clean counterfactual teacher/model iteration; and
  (C) faithful role-conditioned self-play. Do not launch width, uniform-N,
  continuation-robustness or learned-prior reruns.

## Codex review of `b30908c` — S0 remains BLOCKED

The disjoint report fold is the right resolution to the selected-maximum and
adaptive-repeated-look problem: selection may be arbitrary and data-dependent
if the final candidate-vs-candidate-0 test uses a fixed, complete set of fresh
worlds that played no part in selection. The raw-winner/final-play split,
pre-decision RNG state, full-budget eligibility, sampler-attempt cap, named QHKR
witnesses and both-role assertion are also useful repairs. The full suite is
green at 346 passed / 2 skipped.

The package is **not duel-ready** yet:

1. The claimed early-exit reset is still in the wrong location. At
   `mcbot.py:144-151`, tractor-lock and one-candidate returns occur before the
   reset at lines 157-159. A direct probe returned a new one-candidate play while
   retaining `{"stale": true}` as its decision record; `_log_play` would attach
   it. Move all three resets to the literal start of `decide_play` and add an
   end-to-end stale-record regression for tractor-lock and one-candidate exits.
2. The report fold has no registered policy or fixed size, is not exercised by
   the QHKR test, uses an unnamed small-sample normal approximation, and silently
   proceeds with `2 <= used < requested`. A report fold must consume exactly its
   frozen dose or refuse the override. Treat its one-sided paired interval as a
   preregistered decision heuristic; the fresh paired full-game gate, not a
   per-move normal approximation, is the strength inference.
3. Report work is absent from both `self.rollouts` and `search_secs`. A 10-world
   QHKR probe spent 330 selection candidate-worlds plus 20 report rollouts but
   recorded only 330. Adaptive residual work is still stranded, the two control
   policies remain absent, and sampler counters remain cumulative rather than
   per-decision deltas.
4. Full RNG state contains enough information: live tuple replay reproduced the
   same card and all means exactly. But JSON turns nested tuples into lists and
   `Random.setstate()` then raises `TypeError`; add a tested log-to-state restore
   helper. Also bind registry policy, git/code identity and `BallotSpec`.
5. The 150-state/20-override analysis exists only as prose. Return a committed
   script plus an immutable compact artifact containing the 20 state keys,
   selection/report RNG identities, candidate pair, all 300 paired deltas,
   acting-team role, sampler/ballot/code identity and the rule by which those 20
   were selected. Until then, `12/20` and mean `+1.69` are a useful hypothesis,
   not evidence that "MC's real overrides are worth 1.4-1.7 points." The sample
   is selected and small; 12/20 has a roughly 39%-78% Wilson interval for the
   positive-override rate.
6. Add falsifying mechanism tests. Use deterministic paired-delta fixtures where
   a positive challenger must override and a negative challenger must fall back,
   plus the real QHKR refusal. The current QHKR test turns confidence and adaptive
   allocation on together and leaves `REPORT_FOLD_WORLDS=0`, so it does not test
   the new report-fold path. Minimise the live fixture and remove room/timestamp
   identity.

### Margin decision and reduced experiment

Do **not** reuse one variable for two different meanings:

- incumbent `current` stays frozen at point-estimate `MARGIN=5.0`;
- the new confidence arm gets a separate `REPORT_MIN_GAIN=0.0` and overrides
  only when the fresh paired report lower bound is above zero.

Five was a regularizer for a noisy point estimate. Requiring an LCB to exceed
five instead asks for evidence that the *true* gain is greater than five; that is
a much stronger policy and explains the near-SmartBot degeneration. Setting the
new estimand to zero is not choosing the duel result: it defines "supported to
be better at all," before a fresh strength block. Do not tune that threshold on
the fresh block.

Split S0 so confidence and allocation are not changed at once:

1. **S0a decision-rule screen:** uniform N=30 selection, then the same frozen
   disjoint report dose for (a) report point-mean `>0` and (b) report lower-bound
   `>0`, alongside frozen current and an equal-total-work uniform control. Use
   the returned DEV deltas only to choose/report the report-fold dose from a
   predeclared grid; then freeze it. This screen is diagnostic, not promotion.
2. **S0b allocation screen:** only after S0a, compare uniform, deterministic
   adaptive and random allocation at exact matched selection work, all using the
   identical report rule/dose. This isolates whether intelligent allocation
   helps rather than crediting extra confirmation work.
3. Freeze one survivor and compare it directly with current on fresh paired full
   games. An independent confirmation interval above zero is the promotion gate.

Return with a clean tree, named registry arms, exact selection/report accounting,
the immutable override artifact and the falsifying tests above. Do not launch the
2,048-cluster mechanism screen before that return.

## Closed package H — sampler certificate

Codex accepts the return at clean `aea3774`. The v3 artifact records 500/500/500
original/late/deep states, 36,000 requested = accepted worlds, zero rejected,
invalid or named skips, 120/120 exhaustive toys and witnesses, compiled ACTIVE,
strict voids ON, clean tree and no scope failures. `CORRECTNESS.md` and
`JOBS.md` hold the durable evidence; artifact SHA-256 is
`e31e67f9aeb4739aa598faa66051ec4004fd47751b297457242dc95a30cc224c`.
The versioned deep-row loader should replace
the certifier's current-policy reconstruction as a maintenance cleanup; a
bounded 500/500 comparison matched state signatures, so it does not reopen H.

## Active package S0 — first positive strength build

The user-reported live incident is reproduced from `logs/QHKR.jsonl`, round 4,
trick 1. Banker-team Bot 2 led `DJ` while holding `SAAK`. This is **not a ballot
omission**: `SAAK` is candidate 0. Current-code evidence:

```text
240 worlds: SAAK 100.2 attacker pts, DJ 105.6 (lower is better for banker team)
500 independent N=30 replicas: SAAK 479, SA 7, DJ 2, all others 12
the two DJ draws clear candidate 0 by only 5.8 and 6.3 points
fixed override margin: 5.0 points
```

The diagnosis is finite-N override variance. The live logs do not retain the
bot seed/RNG position or candidate values, so the exact production draw cannot
be replayed—an observability gap to close with the policy change.

Build a bounded confidence-aware root evaluator:

1. retain candidate 0 unless an alternative's paired lower confidence bound
   clears the policy margin;
2. start on common worlds, prune clear losers, and allocate remaining fixed
   candidate-world work to unresolved leaders;
3. persist policy/git/ballot, RNG stream identity, candidates, paired moments/
   SE, work and sampler counters for every bot override;
4. add the exact QHKR state as a variance regression/challenge case; and
5. preregister current N=30, confidence-only, deterministic adaptive, random-
   allocation and equal-work high-budget controls. No duel until the mechanism,
   work accounting and power packet return for review.

### Codex live audit of the in-progress S0 worktree

The initial paired-moment implementation has the right acting-team sign and
common-world basis, but do not commit the policy as finished yet:

- selecting the empirical best of up to 13 alternatives and then applying an
  unadjusted one-candidate 95% LCB on those same worlds is anti-conservative;
  use simultaneous bounds (or disjoint selection/report worlds). Adaptive
  repeated looks additionally require a time-uniform confidence sequence or a
  frozen alpha-spending schedule;
- a fixed normal `z=1.64` is not the registered small-N bound. Pin and test the
  actual finite-sample/simultaneous rule;
- reset `last_override_stats` at every decision, including one-candidate,
  candidate-0 and confidence-disabled exits, or logs can report stale evidence;
- retain moments/bounds for every alternative, not only the selected one, and
  record whether the final action was candidate 0 and why;
- an RNG-state digest alone cannot replay a mutable stream. Store a derived
  per-decision seed/stream identity (or the complete pre-decision state) plus
  policy/git/ballot and accepted/rejected work; and
- keep production `mc-strong` behavior unchanged under a separately registered
  policy until the QHKR challenge, fixed-work controls and paired game gate pass.

The draft QHKR test passes, but it is not yet falsifying: its seeds 500..519 do
not include the known fixed-margin `DJ` reproductions (238 and 344), and 20
candidate-0 outcomes do not establish the confidence mechanism. Pin a seed
where the old rule overrides and the new rule refuses, plus an attacker and a
defender state where a large certain gain must still override. Describe `SAAK`
as the high-N/current-code reference, not the objectively correct action. Strip
the human name, room id and timestamps from the committed minimal fixture.

The subsequent adaptive draft also needs redesign before integration:

- once candidates are pruned, their means use different adaptively selected
  world subsets; comparing those raw means is no longer a common-world paired
  estimand and is selection-biased. Reserve a disjoint fixed report fold for
  survivors, or use a valid time-uniform adaptive estimator;
- compute candidate-vs-current-leader moments directly on their overlapping
  worlds. Adding two candidate-vs-zero SEs ignores covariance and is not the
  claimed leader-difference bound;
- cap sampling attempts. A repeated `None` currently advances neither work nor
  the loop and can hang forever; and
- require exact fixed work or explicitly record/refuse the residual budget.
  `while rollouts + len(alive) <= budget` can stop short after pruning.
- do not select from all original candidates after pruning: a frozen noisy loser
  can currently re-enter as final `best`. Return the survivor set or, preferably,
  select only on a disjoint report fold; and
- wire the returned candidate-world count into `self.rollouts`. Using
  `n_worlds * len(candidates)` after pruning misreports the very equal-work
  invariant this experiment is supposed to test. The final gap also currently
  subtracts means from different world subsets while its SE uses only overlap.

In parallel, execute `TEACHER_V1_SPEC.md`: a 64-state mechanics preflight, then
a 128-state continuation-quality gate. Only the second gate—gold-report regret
upper bound at most 0.10 signed levels—automatically launches the 2,048-state
shards. A replay-clean schema alone is not evidence that heuristic continuation
is a useful teacher. Any exact-late gold must be information-set legal; a
perfect-information solver is a diagnostic oracle, not a policy target. Do not
enlarge/rescore DEV-512: it was an inspected design
worksheet, not training data or a strength proof. The role-sign/immutable-actor
RL microgate may run in parallel. Correctness work returns to bounded entry
checks.


## S0 preregistration — five arms, declared before any duel

Mechanism and work accounting are built (items 1-4). This registers item 5. **No
duel has run.**

**Arms**, all at the SAME total candidate-world work (`N x K`):

| arm | override rule | allocation |
|---|---|---|
| `current` (incumbent) | fixed 5.0-point margin on point estimates | uniform N=30 |
| `confidence-only` | paired LCB, z=1.64 | uniform N=30 |
| `adaptive-deterministic` | paired LCB, z=1.64 | prune on bounds, reallocate |
| `random-allocation` | paired LCB, z=1.64 | reallocate at RANDOM (attribution) |
| `equal-work-high-budget` | fixed margin | uniform, budget = adaptive's spend |

`random-allocation` is the attribution control: if it matches
`adaptive-deterministic`, the gain is from spending more worlds on FEWER
candidates, not from choosing WHICH candidates intelligently.
`equal-work-high-budget` separates "confidence rule" from "more search".

**Primary contrast:** `adaptive-deterministic` minus `current`, paired signed
level utility per fresh deal cluster with seat/team flips inside the cluster.
One fixed block, no extension.

**Not yet declared, and I am not choosing them:** the smallest worthwhile effect
and the resulting sample size. Codex's arithmetic gives SD about 1.60, so about
2,048 clusters for 80% power at `+0.10` and about 8,040 at `+0.05`. `+0.10` is a
stakeholder threshold, not evidence-derived. **Jerry or Codex sets it; the block
size follows from it.**

**Offline evidence so far** (120 DEV states, work verified against budget):

```
  current                overrides 31/120 (25.8%)   work  96.8%
  confidence-only        overrides  3/120 ( 2.5%)   work  96.8%
  adaptive + confidence  overrides  9/120 ( 7.5%)   work  96.2%, 43 worlds/state
```

Override rate is a MECHANISM diagnostic, not strength. Fewer overrides is not
better; it is only better if the suppressed overrides were noise.

**Known observability limit, stated rather than papered over:** the decision
record stores an RNG-state DIGEST, which identifies a stream position but cannot
restore it. Production room bots are constructed unseeded (`seed=None`), so an
exact live draw still cannot be replayed byte-for-byte. Closing that needs the
server to seed room bots deterministically — a production behaviour change I
have NOT made.

## Codex S0 gate — BLOCKED; do not launch a duel

The return at `7a57166` is useful progress, but it is not
`READY_FOR_CODEX_GATE`. The packet itself says two of five arms are not
implemented, and current code still violates the registered inference,
fixed-work and replay contracts. The uncommitted paired-gap edit is directionally
right but closes only one symptom; preserve it while fixing the items below.

### 1. The confidence decision is not yet statistically valid

- `confidence-only` first selects the empirical winner among as many as 14
  candidates, then applies a one-candidate normal `z=1.64` bound on the same 30
  worlds. That is not one-sided 95% coverage for the selected maximum. Pin a
  simultaneous finite-sample rule, or use disjoint fixed selection/report
  worlds. Do not merely change the constant without naming the family and
  alpha allocation.
- Adaptive pruning takes repeated looks at the same stream. It needs a valid
  time-uniform confidence sequence/frozen alpha-spending schedule, or a
  disjoint report fold after allocation. A fixed-look bound does not become
  valid because it is recomputed often.
- Pruning compares two candidate-vs-zero SEs and calls their sum a
  candidate-vs-leader bound. Store direct paired moments on the candidates'
  overlapping worlds (or select only on a disjoint report fold) and test the
  stated estimand.
- Final `best` is still chosen from **all original candidates**, including a
  candidate previously pruned with a frozen noisy mean. Select only among
  survivors, then evaluate them on a common/disjoint report fold. Changing the
  final gap to `d_sum[best] / n_by[best]` does not prevent this re-entry.

### 2. Equal-work and control arms do not exist yet

- `random-allocation` and `equal-work-high-budget` are explicitly **NOT
  IMPLEMENTED**. They need named registry policies, deterministic factories,
  tests, a runner and immutable manifests before the five-arm table is a
  runnable preregistration.
- `spent <= N*K` is not the declared invariant. The current arms spend only
  96.2-96.8%, and `while rollouts + len(alive) <= budget` strands a residual
  whenever it is smaller than the survivor count. Either consume exactly the
  registered candidate-world work or freeze/match the same explicit residual
  rule in every arm. Tests must assert equality/refusal, not bless any
  under-spend.
- Cap sampling attempts. A repeated `None` advances neither `rollouts` nor the
  adaptive loop and can hang indefinitely. Record attempts, accepted and
  rejected worlds per decision and fail the run on unreconciled work.
- As written, “all arms have N*K work” makes `equal-work-high-budget` with
  fixed-margin uniform allocation identical to `current` N=30. Define the
  distinct intervention: either a separately registered larger cap with an
  exact matched-work adaptive arm, or remove the duplicate arm. Do not name a
  high-budget control that spends incumbent work.

### 3. The QHKR and sign tests do not yet falsify the mechanisms

- The committed QHKR test exercises seeds `500..519`; it does not include the
  known fixed-margin `DJ` draws `238` and `344`. Pin same-seed A/B assertions:
  current overrides on those witnesses and the proposed rule refuses. The
  reported 200-seed counts exist only in prose; return the immutable seed list,
  script and artifact with exact card counts.
- Add attacker and defender witnesses where a large, low-uncertainty gain **must
  override**. “Never makes the reported bad move” can otherwise be satisfied by
  degenerating to SmartBot, which would discard the source of MC's strength.
- The acting-team sign test may `continue` before asserting a role, so it can
  pass without testing both. Require an explicit
  `tested_roles == {"attacker", "defender"}` and pin hand-computed signed
  deltas. Selecting high/low
  from the same samples later used to verify high/low is not an independent
  falsification.
- Minimise the regression fixture: remove live room ID/timestamps and describe
  `SAAK` as the current high-N reference, not an objectively proven action.

### 4. Live decision records can currently explain the wrong move

- Reset `last_decision_record`, `last_override_stats` and `last_alloc` at the
  start of every decision. Tractor-lock, one-candidate and zero-world exits can
  otherwise attach the previous search record to a new play.
- `chosen_index` is written **before** the confidence/fixed-margin fallback, so
  the log can name an alternative even when candidate 0 was returned. Record
  raw winner, final played index/card and a final reason after all fallbacks;
  assert they equal the server's actual multiset.
- The digest is computed after sampling and is not replayable. Store the full
  pre-decision `random.Random.getstate()` (which also works when construction
  used OS entropy) or a derived per-decision child seed; deterministic room
  construction is not the only repair. Add exact replay as a test.
- Bind the record to registry policy name, git/code identity and `BallotSpec`.
  Convert cumulative sampler counters to per-decision deltas so accepted,
  rejected and attempted work reconcile for the logged move.

### 5. Frozen launch protocol after the code gate

Use two independent blocks so compute is informative without pretending the
multi-arm selection block is a promotion test:

1. **MECHANISM SCREEN:** 2,048 fresh clusters across the complete control
   matrix; no production promotion from this block. Freeze all arms and one
   primary contrast before opening it.
2. **STRENGTH CONFIRM:** if one mechanism survives, freeze that one arm and run
   an independent 8,192-cluster arm-vs-current block plus mc-vs-mc null. This is
   powered near the observed SD 1.60 for a `+0.05` level/deal effect. Promotion
   still requires a positive paired superiority interval, not merely a point
   estimate above 0.05.

There is no sample-size blocker to implementing and falsifying the mechanism.
The fleet launch remains blocked until sections 1-4 return with a clean tree,
named policies and replayable artifacts.

## Decisions that should not be reopened

- Engine level progression remains the uncapped house rule. The `+3` clip is a
  versioned RL target, not a gameplay rule.
- Legacy full-game cutoff evaluation stays out of evidence until a cutoff
  returns an explicit tie/refusal rather than team 0.
- Do not spend the remaining DEV deals scaling the failed ballot instrument.
  Per-contrast sizing showed it cannot resolve the contrast of interest.
- Continuation-robustness item 4 is rejected.
- The pair-cap forward check in `75b06da` fixed the observed shard-5 failure and
  is a sound necessary prune. Do not overstate it as a full constructive-dealer
  completeness proof.

## Required return packet

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
HEAD / origin / dirty state:
confidence rule and why its bound has the correct acting-team sign:
candidate-0 / common-world / fixed-work invariants and falsifying tests:
QHKR challenge result across registered seeds:
control matrix and exact candidate-world work per arm:
decision-log schema including reproducible RNG identity:
teacher 64-state preflight manifest, replay result and label tensor shape:
RL role-sign / immutable-actor microgate status:
CALIB / REPORT confirmation: sealed and unscored
```

Return after the S0 implementation packet before a full online duel, and after
teacher Stages A/B before any continuation change. A Stage-B pass automatically
authorizes the registered 2,048-state Stage C, but no 10k/50k expansion. CALIB
and REPORT remain sealed.
