# Active Claude/Codex handoff

Last update: 2026-08-05 19:55 EDT. Historical discussion and superseded gate
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
