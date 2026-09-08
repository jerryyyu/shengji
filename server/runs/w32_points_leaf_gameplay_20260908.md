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
python -P -B -m shengji.train.cwv_shortlist_screen \
  --arm learned --checkpoint CHECKPOINT --worlds 32 --alternatives 4 \
  --selection-worlds 30 --report-worlds 300 --batch-size 128 \
  --encoding mlp-static --reuse-successors \
  --points-leaf-tricks 1 --points-leaf-view last_actor \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --seed0 91261190 --clusters 52 --workers 8 --out NEW_OUTPUT
```

The process must run under the existing bounded launcher/dependency wait;
the CLI command itself does not enforce the two-hour operational allowance.
It never grants permission to stop another job or touch deployment.

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

No whole-game leaf result exists yet. Do not promote this arm from unit or
saved-state evidence alone.
