# Active Claude/Codex handoff

Last update: 2026-08-05 18:50 EDT. Historical discussion and superseded gate
packets live in `HANDOFF_REVIEW.md`.

## Current status

- Production: compiled `mc-strong` (N=30).
- DEV-512: complete, strict aggregate reproduced, **SELECT NONE**.
- CALIB-512 and REPORT: sealed and unscored; the ballot lane ended without a
  DEV winner, so its downstream stages are NOT REACHED / CLOSED.
- Fleet: no run authorized.
- Next strength hypothesis: fixed-budget common-world root allocation on the
  incumbent ballot, but only after a power/feasibility registration. Do not
  launch width, uniform-N, continuation-robustness or learned-prior reruns.

## Active package H — finish the sampler certificate honestly

`fc19d26` correctly repairs the population-selection mechanism:

- `original`, `late` and `deep` are all mandatory;
- counters reset per source and exact quotas are 500/500/500;
- source counts and quotas are persisted;
- missing/short sources refuse; and
- the registered exhaustive-toy count is 120.

Codex's compiled targeted audit passes the four new/related tests. **HOLD the
closure claim**, however, for three concrete reasons:

1. `server/runs/logs/certify_sampler_v2.json` records `git=8c401a0` and
   `tree_dirty=true`; it was generated before the implementation commit and is
   not a clean-current artifact.
2. The `certified` expression checks skips/invalid/toy support but does not
   require `rejected == 0` or `accepted == requested`. A future run could again
   certify after silently losing requested worlds.
3. The CLI default is `--toy-states 40` while the registered contract requires
   120, so the default command necessarily refuses. Make the safe registered
   invocation the default or remove the misleading default.

Required work, in order:

1. Add a falsifying regression showing any rejected/unaccepted requested world
   makes `certified=false`; include `rejected == 0`, `accepted == requested`
   and the exact requested total in the gate.
2. Align the default toy count with `REGISTERED_TOY_STATES` and test it.
3. From a clean current HEAD, run compiled + `SHENGJI_REQUIRE_VOIDS=1` over
   exactly 500 original, 500 late, 500 deep states, 24 worlds/state and 120
   exhaustive toys.
4. Require: 1,500 states; 36,000 requested = accepted; zero rejected, invalid
   and all four skip counters; 120/120 complete; real witness 120/120; clean
   tree; current git/script/sampler/Memory/corpus/split/compiled identities.
5. Store one immutable replacement artifact and update `CORRECTNESS.md` and
   `JOBS.md`. Explicitly supersede `eea78d2`, `c1ceca1` and the dirty v2 run;
   do not describe any of them as original+late+deep certification.

This closes the bounded P0 certificate only. It does not prove posterior
fidelity, and it does not prove the production dealer globally complete under
all declaration-pin/run-cap combinations. Those remain separately named in
`BACKLOG.md`.

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
certified-expression and default-command repairs:
falsifying tests plus targeted/full-suite results:
exact clean certification command:
artifact path and SHA-256:
git/script/sampler/Memory/corpus/split/compiled identities:
states_by_source / requested / accepted / rejected / invalid / skips:
toy completeness / real witness:
JOBS.md and CORRECTNESS.md reconciliation:
CALIB / REPORT confirmation: sealed and unscored
```

Stop after the packet. No scoring, training, CALIB/REPORT access, online duel
or fleet launch is authorized by this package.
