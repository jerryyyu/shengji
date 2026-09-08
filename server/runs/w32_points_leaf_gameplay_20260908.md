# W32 with a learned continuation: small gameplay comparison

Question: does the lower-CE checkpoint work better as a leaf evaluator than
as a shortlist ranker? Keep the root search fixed and change its continuation
estimator. This is exploratory development, not a deployment or confirmation.

## What changes

Use the existing full-legal W32/K4 shortlist (incumbent plus four alternatives),
N30 selection and R300 fresh paired-report worlds. Finish the current trick
in each rollout, then use that checkpoint's auxiliary final-attacker-points
head. Encode the **last actor**, matching training afterstates. Keep the
existing banked-points floor, terminal outcomes and exact-endgame handling.
MC allocation, sign convention, report SE and LCB rule are unchanged.

This tests a different continuation estimator, not additional search depth,
better beliefs or clairvoyant play: model inputs contain sampled worlds,
never opponents' true hands. The points head was trained on actual MC-played
trajectory outcomes, not the deterministic heuristic rollout policy's mean.
Consequently, losing against that rollout reference offline did not establish
that the learned continuation loses in gameplay (see PR #292).

## Fixed comparison

| Checkpoint | SHA256 | Training recipe |
|---|---|---|
| Default ACDEF v2 | `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600` | LR 3e-4, selected epoch 5 |
| Lower-LR ACDEF v2 | `8d92dd6e3ba39bfc535d3aef75559c7cda4312cdb265a4202068719d6e6eeea9` | LR 1e-4, selected epoch 7 |

Run each checkpoint's leaf arm against literal production `mc-s0-report-lcb`
on the same **52 deals / 104 mirrored rounds**. Use clusters 0–51 of the
already-opened 520-deal comparison, seed0 **91261190**, cycling all 13 ranks.
No outcome-based subset selection or replacement deals. These are reused DEV
deals, not a new holdout. Compare the resulting paired-deal utilities with
the corresponding retained flat-W32 results, without replaying those games.

Report each leaf arm versus production, leaf-minus-flat for each checkpoint,
and lower-LR-minus-default within each consumer. Unit: whole signed levels
per played round, with both mirrors averaged before deal bootstrap. Publish
the 52-deal uncertainty and changed-decision examples; this small screen may
remain inconclusive. It cannot establish a new offline metric or close the
value-learning direction. No automatic larger sweep follows its outcome.

### Interpretation before results

This is a diagnostic with an unfavorable prior: earlier tested leaf/depth
recipes did not beat the supported flat shortlist, and the saved-state T1
points-leaf comparison in PR #292 was negative against its heuristic
continuation reference. Changing the consumer is not evidence of improvement.

Selected-epoch validation points MAE/bias, from each checkpoint's training
`receipt.json`: default epoch 5 **12.328 / +0.769** points; lower-LR epoch 7
**11.746 / -0.672**. These are errors against observed continuation outcomes,
not errors in estimating a conditional expectation or paired action gaps.

For scale only, the retained 520-deal flat-W32 records give the following
planning proxies at 52 independent deals. Each deal averages both mirrors;
units are whole signed levels per played round.

| Retained flat-W32 contrast | Deal sample SD | Approx. 95% half-width at 52 | Approx. 80%-power detectable effect |
|---|---:|---:|---:|
| Default vs production | 0.5340 | 0.1451 | 0.2073 |
| Lower LR vs production | 0.5243 | 0.1425 | 0.2036 |
| Lower LR minus default | 0.5578 | 0.1516 | 0.2166 |

Formulas: `1.96 * SD / sqrt(52)` and `2.80 * SD / sqrt(52)` (normal
approximation, two-sided 5% test, roughly 80% power). Source:
`cwv-gameplay-precision.DE3xDH/{completed-fresh-520,acdef-lower-lr-fresh-520}.json`
and their retained paired records. **The new leaf and leaf-minus-flat
variances are unknown.** These are not promised confidence widths or a
powered test for the old 0.0587 checkpoint gap. The small screen can expose
a large failure or promising large gain cheaply; modest effects need an
explicit follow-up decision rather than a declaration of no effect.

Absolute outcome error is not action-difference error. For two actions on the
same world, the relevant error is `e(a) - e(b)`; shared errors can cancel,
while action-dependent systematic errors need not average away over worlds.
Neither row-level MAE nor its ratio to MC finalist margins determines the
gameplay screen's power. Fresh report worlds quantify sampling variation,
not learned-model bias. The existing MC-LCB is deliberately unchanged here;
its sampling SE is not a guarantee that learned leaves are calibrated.

A negative result with useful precision counts against this exact
checkpoint/T1/points-head recipe. An interval spanning useful gains and losses
is inconclusive. Neither result closes learned leaves as a design class, and
small MAE improvements do not justify scaling this arm on their own.

Archived flat-W32 gameplay predates merged encoding/reuse optimizations.
The supporting parity artifact is
`~/shengji-archive/2026-09-07/cwv-pricing-path.9bKPfR/adoption-comparison.json`
(PR #296 comment 5577422990; integration landed via #297). Complete serialized
rows matched for shortlist and production on **four rounds/two deals**, with
two timing repetitions per policy/source, plus prior focused score/RNG tests.
That supports the intended decision-preserving change; it is not a fresh
520-deal parity replay or a hardware-matched timing comparison.

## Execution and recovery

- Separate clean checkout on Strength after Run H exits; verify the actual
  process and coordinate the slot with Claude. Do not update a live tree.
- Two 8-worker processes, one per checkpoint, on the 16-CPU host. Each worker
  uses one Torch/BLAS thread. CPU gameplay only; no Mini training contention.
- Use current merged v2 static encoding and tensor/successor reuse. No
  approximation, shortlist-width change or additional optimizer is hidden in
  this comparison. Timing versus old runs is descriptive across runtimes.
- Existing per-deal atomic shards, progress and config binding suffice.
  Failures retain completed deals; rerun the unchanged command to skip them.
  An interrupted unsealed pair may be recomputed and must be disclosed. Do
  not change recipe, checkpoint or source within an output directory.
- Publish outcomes from the existing shard reader; no second full-game
  reconstruction, capacity campaign or model-provider calls.
- Planning allowance: up to two host-hours for this initial comparison, not
  a scientific pass/fail gate. Derive the actual ETA from the first completed
  shards and report tails. If it is unaffordable, stop and report retained
  partial results rather than discard them or silently extend the population.

From the installed `server/` directory, once per checkpoint with different
immutable checkpoint/output paths:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
PYTHONPATH="$PWD" \
python -P -B -m shengji.train.cwv_shortlist_screen \
  --arm learned --checkpoint CHECKPOINT --worlds 32 --alternatives 4 \
  --selection-worlds 30 --report-worlds 300 --batch-size 128 \
  --encoding mlp-static --reuse-successors \
  --points-leaf-tricks 1 --points-leaf-view last_actor \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --seed0 91261190 --clusters 52 --workers 8 --out NEW_OUTPUT
```

The CLI does not enforce the operational allowance. After verifying the
existing owner is finished, launch each arm as a separate systemd transient
service with `RuntimeMaxSec=7200`, `KillMode=control-group` and
`TimeoutStopSec=60`. Both run concurrently, eight workers each. Record the
unit names, immutable commands, source and output paths. Expiry may interrupt
an unfinished pair but must retain completed atomic shards. This uses the
host's existing process supervisor, not another scientific admission protocol.
It never grants permission to stop another job or touch deployment.

Prepared Strength source: `/root/cwv-points-leaf-8d7ed763`, runtime
`/root/cwv-dev/server/.venv/bin/python` (Python 3.14.4, Torch 2.14.0+cpu).
`PYTHONPATH` must point at the prepared source, not the runtime's old editable
checkout. Both copied checkpoint SHA256s match the table. The native extension
is reused only after checking identical tracked `_fast.pyx` and `setup.py`
between its build source and this source. Thirteen screen-wiring tests pass
on that actual Linux runtime in 1.34 seconds; no full games were launched.

## Source validation already completed

Independent review found and repaired a counter-label mismatch before launch.
`rollout_invocations` / `total_rollouts` count scored search leaves;
`continuation_rollouts` excludes model predictions and includes exact exits.
`round_end_continuations`, `exact_shortcuts`, predicted leaves and accepted
search worlds are reported separately and reconciled by a real consumer test.

Integrated on main `2be371c9`: 57 focused native tests pass. Two actual
checkpoint probes each used W32/K4/N30/R300 on the same test-fixture position:
629 legal actions, 20,128 ranking rows and 750 learned-leaf calls (150
selection, 600 report). With truncation disabled, actions, score/report
records and RNG matched ordinary W32 exactly. T1 preserved the nominations
and root state and invoked the intended head. These probes are wiring
evidence, not whole-game strength or an isolated performance benchmark.

## Completed result — September 8, 2026

Both fixed arms completed all 52 deals without retries or timeout in 396.8s
and 382.6s, concurrently on 16-core Strength. The raw bundles are preserved
on Strength and Mini. [Full readout and examples](https://github.com/jerryyyu/shengji/pull/302#issuecomment-5581589663).

Paired leaf-minus-flat: default **−.1250 [−.3462, +.0865]**, lower-LR
**+.0288 [−.2212, +.2788]** whole signed levels/round. The checkpoint/consumer
interaction is **+.1538 [−.0962, +.4135]**. These are the same fixed 52 deals,
not differences from full-520 baseline means. Ten thousand paired-deal
bootstrap resamples, seed20260907; reused-DEV exploratory intervals.

Neither leaf arm demonstrates an improvement. Keep default flat W32; this
small screen is inconclusive, not proof of equivalence or a general closure
of learned leaves. No automatic expansion or production change. Source and
the preregistered comparison above were unchanged during execution.
