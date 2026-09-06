# Selective extra-trick guidance: bounded DEV follow-up

Source and local timing checks complete; **no gameplay screen launched**. This is a single new recipe
against optimized flat W32, not another allocation-threshold/world-dose sweep.
Tracked in #248; separate from Claude's PUCT, training and F2 data generation.

## What the completed screens justify

Flat ABC W32/K4/N30/R300 remains the reference. Broader-rank adaptive allocation
changed half of contested decisions but scored +0.00577 levels/round
[−0.05774,+0.07308] over flat: no demonstrated gain. Always-applicable learned
double-shortlist was also inconclusive and cost 116.24x its flat opponent's
decision wall. Its repeated inner ranking, especially early wide branches, was
the measured bottleneck. Neither result proves that selective depth cannot help.

The question now is **whether changing the continuation at uncertain root
decisions improves play**, rather than estimating the same heuristic continuation
more precisely. Width limiting and the uncertainty trigger form one named
selective policy; this first comparison will not isolate their separate effects.

## One recipe, not a sweep

Keep ABC, exhaustive W32 root ranking, incumbent plus four alternatives, uniform
N30 selection and the independent R300 report. Keep actual sampled-world
constraints, point scoring, acting-team perspectives and the root LCB threshold.
No learned belief, new checkpoint, PUCT tree, production registry/default or
deployment is bundled in.

1. Compute the ordinary heuristic selection matrix on all N30 shared worlds.
   Choose the provisional non-incumbent challenger with inherited point-shy
   nomination. Its paired differences from the incumbent determine the trigger.
2. Enable guidance only when that paired standard error is positive and
   `abs(mean_gap) <= 1.7 * paired_SE`. Require all requested selection worlds.
   This is a heuristic uncertainty trigger, **not** a confidence certificate or
   evidence of an actually close decision. Zero-variance ties do not trigger it.
3. Freeze that one decision-level trigger **before reading any report world**.
   If false, use the ordinary selection matrix and ordinary heuristic report.
   If true, guide one extra trick on the representative first 4/30 selection
   worlds and 40/300 independent report worlds. Apply the same rule to every
   root candidate supplied to a stage; never pick optimistic worlds or guide
   only a favored candidate while scoring its rival with another rule.
4. At each simulated inner mover, rank the **complete** legal set only when it
   contains at most 128 actions. If enumeration is incomplete, uncountable or
   over that limit, play the heuristic incumbent and explicitly record the
   skipped guidance. Never rank a capped prefix as though it were exhaustive.
   The root legal set remains exhaustive and uncapped.
   Before enumerating a follow, bound the possible submitted card multisets
   from the mover's full hand at the required play size. If that conservative
   raw bound exceeds 4,096, skip guidance without enumerating. This can skip a
   position whose actual legal set is small; it deliberately bounds validation
   work and is not a claim about its legal count. Leads use closed-form counts.
5. Within an eligible inner position, retain the existing model shortlist plus
   incumbent and full heuristic evaluation of those finalists. Finish the extra
   trick, then use the terminal heuristic continuation. These inner choices use
   sampled-world perfect information **inside simulation**, not the true hidden
   hands and not an executable information-set-consistent inner policy.
6. Nominate the final challenger from the resulting selection values. The fresh
   report uses the already-fixed guidance policy and retains the original paired
   MC-LCB acceptance rule. No model output is substituted for its terminal score.

Selection and report estimate the same fixed mixed-continuation rule for the
current decision. Selection may be optimistic after trigger/nomination; the
independent report is not reused to choose the trigger, depth, worlds or recipe.
Strategy fusion and continuation/model error remain possible; an intact report
does not establish that the simulated policy is optimal or realistic.

## Cost and recovery

Reuse the flat selection matrix for un-guided cells; do not roll those paths
again after deciding the trigger. Count every additional guided outer completion
and inner finalist rollout exactly once, separately from neural ranking rows.
Preserve the original non-selective path when the feature is disabled.

At K4/N30/R300 the guided branch counts are at most 4*5 at selection and 40*2 at
report. One extra trick has at most four mover decisions. With a 128-action
complete-set limit this bounds inner model rows at **51,200 per triggered root
decision** and inner finalist terminal completions at **2,000**. These are
structural ceilings, not a measured runtime promise; bounded enumeration must
also avoid a hidden multi-million-candidate counting scan before falling back
(the fixed 4,096 raw-follow guard above).
All original root ranking remains; the existing ~81–82% ranking cost is not
removed by this policy. Existing successor/tensor reuse is already banked.

The intended first gameplay contrast uses the same 260 opened broader-rank DEV
deals `[91260904,91261164)`, balanced over 13 ranks, against flat ABC W32, not
production. Both mirrors stay in each deal bootstrap cluster. Retain every
completed pair and report actual suit/NT coverage, gate exposure, skipped inner
positions, extra rollouts, failures, measured CPU/wall, and uncertainty. No
fresh-confirmation, equivalence, isolated efficiency or deployment claim.

The real CLI-to-record path and three fixed fit-state timings below are complete,
including both changed continuations and wide fallbacks. Planning estimate:
**1–2 hours on Strength**, explicitly uncertain because three Mini states do not
measure a population's tails or cross-host throughput. Use the existing 35-minute
flat/adaptive screen as an additional anchor, not a promised time for this policy.
A **four-hour wall / 24-GiB process-group memory** safeguard bounds this first
screen; use 16 one-thread workers and prior-cost-ordered pair scheduling. The
four-hour limit is engineering headroom for this opened-DEV question, not a
scientific gate and not a rule derived from an outcome. It is fixed before launch.
Retain completed atomic pair shards on interruption; no automatic retry/cap
extension or replacement deals. Aggregate retained shards once without engine
replay. Coordinate a clean Strength handoff with Claude; do not compete with F2.

Source review must directly unblock this named DEV screen after the timing and
host handoff; do not require a second immutable-freeze review for opened DEV.

## Required consumer evidence

- CLI persists the exact trigger/width recipe, factory creates a selective arm
  and unchanged flat baseline, and changed recipes cannot reopen old shards.
- The actual decision record shows trigger-on and trigger-off paths, actual
  guided work and nonzero extras. Disabling factory wiring or record propagation
  must break the witness, not merely a helper test.
- Report changes cannot alter a selection-fixed trigger; report RNG remains
  independent. Forced decisions clear prior state. Both team signs are tested.
- Overwide/incomplete inner sets invoke no learned ranking and never use a
  truncated legal prefix; narrow complete sets do reach learned guidance.
- Un-guided flat cells are not recomputed, root/world/input matrices are not
  mutated, and extra completions appear exactly once in emitted work totals.
- Legacy flat, adaptive and double-shortlist consumer tests remain unchanged.

No automatic larger depth, additional population, alternate threshold, random
gate or replacement checkpoint follows an inconclusive first screen. Read the
exposure and gameplay result before choosing the next experiment.

## Validation and local timing evidence

The shortlist/selective/adaptive/double-shortlist/screen/reuse/scheduling suite
passes **129 tests in pure and compiled modes**. Important concrete witnesses:

- A deliberately disconnected factory returning flat W32 turns both timed-worker
  record tests red with `KeyError: cwv_selective_depth`; the real wiring is tested.
- The eight-world/two-action fixture constructs only eight guided root leaves,
  leaves the other eight matrix cells untouched, and preserves both input worlds
  and the caller's matrix. It does not merely test an all-guided tiny population.
- Opposite report evidence cannot change the selection-fixed trigger; report and
  allocation seeds remain distinct. With a false gate the decision, moments,
  independent report and final RNG match flat W32 in both execution modes.
- A terminal-root-leaf witness caught and closed a new telemetry `KeyError`
  before review. Terminal branches now publish zero inner work correctly. A
  failed timing case stays failed on reopening, with no repeated decision call.

One compiled, single-thread, **contended Mini** timing probe used the existing
fit coordinate `[2,0,0]` at predetermined decision ordinals 0, 12 and 24. Same
ABC checkpoint, W32/K4/N30/R300, root/inner successor reuse and static MLP path;
the order was baseline/arm, arm/baseline, baseline/arm. No provider calls, new
games, outcome-based state selection or repeated capacity census.

| Fit decision | Flat wall | Selective wall | Gate | Eligible / skipped inner positions |
|---|---:|---:|---|---:|
| 0 | 0.6584 s | 1.0354 s | on | 152 / 248 |
| 12 | 0.1969 s | 0.9771 s | on | 304 / 96 |
| 24 | 0.1384 s | 0.1494 s | off | 0 / 0 |

All six decisions completed without error and preserved their input state.
Decision 0 skipped 87 inner positions **before enumeration** using the raw-follow
bound; 161 more used the incomplete/overwide legal-set fallback. Triggered
selection calls reused 130 of 150 flat cells, charged 20 extra outer completions
each, and guided 4/30 selection plus 40/300 report worlds. These are exposure
and timing observations, **not a strength result or representative speedup**.

Retained probe root:
`~/shengji-archive/2026-09-06/selective-depth-timing.Nwrz32/`.
It includes the checkpoint, source/recipe/script identities and all six records.
The later probe-only failed-reopen guard does not change the measured successful
path or policy source; its receipt is not relabeled as that later script hash.

Reproduction utility: `scripts/cwv_selective_depth_probe.py --panel FIT_PANEL
--checkpoint CHECKPOINT --out NEW_PROBE_ROOT`. It uses the three fixed ordinals
and retains each completed decision with a 120-second per-decision safeguard.
It is not a prerequisite to repeat this probe during review or before gameplay.

## One source-and-run review request

Review this source delta plus the named DEV screen together. A source PASS,
Jerry's standing bounded-experiment authorization, and a verified clean Strength
handoff unblock exactly this screen. No second immutable-freeze review is needed.
No merge, registry/default change, deployment or broader sweep follows from PASS.

At the final reviewed head in an isolated Strength checkout, bind the executing
head, native/runtime identity, command and new output root in the launch record.
Use a process-group supervisor with `RuntimeMaxSec=4h`, `MemoryMax=24G`,
`KillMode=control-group` and bounded stop grace so a timeout cannot leave workers
running. Do not touch Claude's F2 process or output without coordinating its owner.

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
python -B scripts/cwv_shortlist_screen.py \
  --arm learned --checkpoint /root/cwv-runABC-mlp-points-best.pt \
  --worlds 32 --alternatives 4 --selection-worlds 30 --report-worlds 300 \
  --inner-mode learned --inner-worlds 4 --inner-batch-size 128 \
  --inner-reuse-successors --selective-depth --inner-legal-limit 128 \
  --baseline flat-shortlist --encoding mlp-static --reuse-successors --batch-size 128 \
  --clusters 260 --workers 16 --seed0 91260904 \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --cost-order-from /root/cwv-ranks13-20260906.YtvILo/ranks13-paired \
  --out NEW_SELECTIVE_DEPTH_OUTPUT
```

Checkpoint SHA256:
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
At the first completed pair, inspect actual gate/inner/work/report records and
confirm a flat baseline. Update ETA from completed pairs and active tails. At
completion, publish the paired level estimate/interval, actual cost and exposure,
all failures and rank/suit/NT coverage, retaining both mirrors and every deal.
