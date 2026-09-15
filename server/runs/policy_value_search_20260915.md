# Policy/value search DEV — implementation log

Tracking: #436. No production deployment or strength claim.

## First consumer

`--value-continuation 0|1|2|full --baseline flat-shortlist` replaces both
selection and the fresh independent report with final signed-level values.
`--continuation-baseline mc|full` chooses the inherited point-based MC control
or the identical heuristic continued to round end on the signed-level scale.
This extra control separates truncation from changing the payoff objective.
When a prior is supplied, it is applied to both arms. Outcome head is explicit.
The horizon counts resolved tricks from BEFORE the candidate action, not from
its afterstate. Terminal leaves use exact engine outcomes, never the model.
No accrued-points correction is added. The sampled-world SE is not a measure
of model error. No exact-endgame substitution in the new continuation arms.

## Local real-checkpoint smoke (September 15)

M1 SHA256 `3cb9cd62a083736e3b41712baabaa86398b74f0e303a4a15290ec1cd9585612d`,
MLP static encoding, outcome head, one Torch thread. State from test seed19,
first player leads first card; score the following decision. Tiny diagnostic
dose: two admission worlds, three selection worlds, two alternatives, report30,
one-trick horizon. Decision selected `S3`, accepted by engine.

- Decision wall 0.1068s (model load excluded; not a paired speed benchmark).
- 20 admission rows, 69 continuation model rows in two batches.
- 138 heuristic plies, zero terminal continuation rows/full playouts.
- 35 sampled worlds total, no rejected/failed worlds.

Focused tests cover horizon boundaries, team perspective, input preservation,
terminal bypass, finite-output refusal, real selection/report, screen factory,
recipe identity, and separation of model rows from full rollout counts.

## Still required

Deadline-child/whole-round smoke and telemetry, prior checkpoint qualification,
launch-ready source review, then fresh capped paired comparisons. PUCT with
progressive widening and batched leaves remains subsequent implementation,
not a capability provided by this first consumer. Do not interpret this small
smoke as evidence of gameplay strength or representative inference cost.

## Capped mirrored-round integration smoke

Started on Mini with one worker, seed19, two admission worlds, three selection
worlds, two alternatives, report30, mlp-static encoding. Arm k=1 versus full
heuristic signed-level control. Existing 300s supervised play deadline enabled.
Output `/private/tmp/cwv-truncated-smoke.FumMMN`; source is this uncommitted
implementation, so preserve config and do not treat it as a clean-head screen.
No production or statistical claim. Verify terminal summary before using it as
integration evidence; an unfinished pair is not success.

Completed: 1/1 paired deal (two mirrored rounds), exit0, 224.7s elapsed;
120 total decisions, zero timeouts, zero failed/rejected worlds, complete work
accounting. Arm: 3,336 learned continuation rows, 33 terminal continuations,
5,847 heuristic plies. Full control: 3,306 terminal continuations, 138,445
heuristic plies. Decision wall 109.0s versus111.8s; admission consumed107.4s
versus107.9s, so this tiny no-prior smoke is dominated by admission. Different
trajectories mean these totals are not a same-state speed comparison. One deal
does not estimate strength. Summary/config/cluster shard retained at the above
path. Executed implementation was subsequently committed as46fa5065; tests and
notes do not affect the completed worker.

Review repair: the first smoke bypassed production's sampled-hand canonical
sorting/conservation boundary and did not persist continuation details in the
wrapper trace. Preserve it as historical integration evidence, NOT as validation
of the repaired policy. The consumer now uses `_complete_determinized_hands`
and sorted kitty; wrapper saves the actual continuation trace. New tests cover
permuted sampled multisets, corrupt-world refusal and durable wrapper details.

Repaired source4153e6ce: real M1 plus priorv2
`b6d928c5a13d7de2c5267cb3e936298628998dbc3868ee13d88ce726a797d1d6`
on both sides, same diagnostic dose/seed19 and 300s cap. Completed in18.1s,
120 decisions, zero timeouts,98 persisted continuation records. Prior activated
5 times on arm and4 on control. Decision wall5.12s/7.95s; maxima0.765s/0.978s.
Evidence `/private/tmp/cwv-truncated-prior-smoke.lHJdqw`. This differs from the
old smoke in prior admission AND the correctness repair, so not an isolated
prior speedup measurement. Subsequent main integration imports reviewed #434;
revalidate separate-prior consumer tests, not repeat all historical runs.

## First bounded screen request

Fixed two comparisons, each26 fresh paired deals,13 ranks cycled twice. Arm:
M1 outcome head + priorv2, threshold10000/top256, W32/selection30/report300,
four alternatives, static encoding, successor reuse, k=1. Controls:
(a) same admission + original point-MC, (b) same admission + full heuristic
signed-level continuation. No hybrid-bury or tie-rule changes; these screens
are not directly against the deployed hybrid-bury policy. All sides have300s
play caps. Source #438 exact reviewed tip, M1/prior hashes above. Priorv2's
historical split caveat is retained; use fresh gameplay deals only.

Proposed seed start610260915 (verify disjointness against fleet run inventory
before launch). Two sequential jobs on free Perf, up to16 one-thread workers,
with disjoint output directories. Persist each pair, never overlap a peer job.
Use CLI `--value-continuation 1 --continuation-baseline mc` then `full`, plus
`--baseline flat-shortlist --worlds 32 --selection-worlds 30 --alternatives 4
--report-worlds 300 --encoding mlp-static --reuse-successors --clusters 26
--workers 16 --seed0 610260915 --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A`.
Checkpoint, prior and output arguments must resolve on the target host; verify
first-consumption hashes once. No outcome-triggered extension. One2-hour job
bound per comparison; on expiry preserve completed pairs and report incomplete,
do not relaunch automatically. Initial ETA is not calibrated for this dose:
report live completion-based ETA after the first pairs, not a speculative speedup.

Readout: signed levels/round and whole-deal clustered95% interval, per-window
completeness, actual model/terminal rows and heuristic plies, decision/total wall,
tail/cap incidence and prior activation.26 pairs is a DEV screen, not proof of
non-inferiority or a shipping decision. This request must pass source review and
fleet/disjointness checks before launch. PUCT is not included in this first pair
of comparisons and stays on the active goal.
