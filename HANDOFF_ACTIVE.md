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

In parallel, prepare a 64-state schema/replay preflight for a **new** 2,048-state
teacher/challenge asset. If all 64 rows replay exactly, every candidate is legal
and held, 512/512 common strict worlds per candidate are accepted, tensors have
the registered shape and all sampler/skip counters are zero, automatically
launch the 2,048-state shards. Do
not enlarge or rescore DEV-512: it was an inspected design-selection worksheet,
not training data or a strength proof. Its primary 95% half-width was 0.337;
2,048 comparable rows would still be about 0.169. The new asset earns its cost
by storing far deeper counterfactual labels and per-world outcomes, not merely
by being four times larger. The role-sign/immutable-actor RL microgate may run
in parallel. Correctness work returns to bounded entry checks.

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

Return after the implementation/preflight packet before a full online duel or
any 10k/50k teacher expansion. Bounded local challenge runs and the 64-state
preflight are authorized; a clean preflight automatically authorizes the
registered 2,048-state shards. CALIB and REPORT remain sealed.
