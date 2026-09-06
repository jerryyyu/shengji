# Full-legal complete-world shortlist — DEV screen

Historical source-plan record below; the original screen has since run.
See the **Sep 6 scaling assessment** at the end for the retained ABC W32 result
and current queue. No promotion, deployment, or production-policy claim.
Extends #227 using the
merged #229/#230 evaluator/checkpoint, not the old public-observation head.
The #222 driver conflict is resolved in the merged stack; no duplicate repair.

## Policy and controls

1. Enumerate the **entire legal submitted-action set**, with harvest's
   `cap=None`. This includes multi-component throws; the engine decides which
   component actually plays in each sampled world. No truncated-prefix fallback.
2. Score every action on W shared production-sampled complete worlds. Apply the
   action, let the same #229 heuristic finish this trick, then evaluate the
   complete-world net in the root team's perspective (terminal outcomes exact).
   Batches retain O(legal actions + batch size) data, not a full world/state matrix.
3. Keep the **four highest-valued alternatives plus production's incumbent**.
   This explicitly means min(5, legal count), with the incumbent always first.
   Uniform control selects the same number of alternatives without replacement
   and without model rankings. A forced singleton needs no ranking.
4. Run production's unmodified uniform selection, full rollouts, point-shy
   handling and fresh report-LCB on this shortlist. The report remains R=300 in
   the requested screen. Selection N and W are chosen from timing, not outcomes.
   Production's tractor-lock bypass is disabled in these two arms so that it
   cannot bypass the requested full-legal enumeration.

Cheap sampling uses a named child RNG and restores the parent RNG. Production
selection/allocation/report retain their existing streams and algorithms.
Sampler counters retain the truthful overall total and explicitly separate
cheap samples from full-rollout samples. Cheap predictions are **not** rollouts.

The checkpoint selected before screen outcomes is
`tmp/train-out/cwv/runAB-mlp-points/best.pt`, SHA-256
`650d4144b0641741fce2d3168f70577ea31e2ae768c6161345354f6ae9ff1787`.
The evaluator uses its terminal-distribution head's expected signed levels;
the auxiliary points head trained this checkpoint but is not directly scored.

## Timing and screen plan

Use outcome-blind production states from seed **89260904**, not screen seeds.
The cost probe captures **all** decision surfaces, including forced and
tractor-locked decisions. For a subset it samples one seeded position per
chronological block; `--stride 1` measures the full census. A fixed every-fourth
or every-eighth decision can alias trick positions and is not used.

Measure the smallest W/N setting and larger W/N settings on the same states,
with counterbalanced timing order. Keep the baseline at N30/R300 and measure
production's own N90/R900. Preserve N30 for the learned arm where it fits;
use remaining time for more cheap worlds. Measure the uniform control's dose
too: matching shortlist size alone does not match its lower inference cost.
Publish selected W/N and measured times before opening the screen population.
If the minimum faithful configuration cannot fit a requested wall budget,
report that infeasibility rather than truncate legal actions or label an
over-budget run as equal-work.

Screen **256 fresh rank-2 clusters, seed0=90260904**, two team mirrors per
cluster, for learned 1x/3x targets, corresponding uniform controls, and the
production 3x arm. The current 1x production policy is always the opponent.
Report signed levels per round and deal-cluster-bootstrap CIs, alongside actual
decision CPU/wall ratios and enumeration/model/full-rollout work. Candidate
trajectories can change realized cost: disclose drift, never censor outcomes
or retune on them. This is an exploratory screen, not a confirmatory claim.

Reuse #227's process-pool pair runner, progress/ETA updates and atomic shards.
Use all 16 cloud workers in an exclusive screen window; numerical libraries
use one thread each. Resume the identical recipe over missing mirrored pairs.
Completed pairs survive failures. No resealing training data, no new capacity
framework, and no duplicated multi-hour reconstruction.

Commands (W/N replaced with the published cost-derived settings):

```sh
SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B scripts/cwv_shortlist_cost.py --checkpoint CHECKPOINT \
  --deals 2 --stride 1 --world-grid 1,4 --selection-grid 1,30 \
  --out COST_ROOT

SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B scripts/cwv_shortlist_screen.py --arm learned \
  --checkpoint CHECKPOINT --worlds W --selection-worlds N \
  --target-wall-multiplier 1 --clusters 256 --workers 16 \
  --seed0 90260904 --out LEARNED_1X_ROOT
```

Repeat for target 3x; `--arm uniform` omits the checkpoint and uses its measured
selection dose. `--arm production --production-multiplier 3` selects N90/R900.
Do not reuse smoke or cost seeds as screen seeds.

## Initial engineering evidence (not screen results)

- 45 focused native tests passed across shortlist, evaluator, legal enumerator
  and production S0 search; the 13 shortlist tests also passed after explicit
  cheap/full sampler accounting was added. One existing unknown-pytest-mark
  warning, no failures.
- One real two-mirror smoke, seed88261904, completed in 47 seconds on Mini with
  zero summary problems. This deliberately used candidate N1/**R30** versus
  baseline N30/R300: **not an equal-work or strength comparison**. It evaluated
  64,610 cheap action/world rows across 74 candidate decisions; the largest
  observed legal set exceeded 13,000 actions. All legal actions were included.
  Raw receipt: `/private/tmp/cwv-shortlist-smoke-20260905/` on Mini.
- Small Mini-only outcome-blind timing probe: one production deal, 11 seeded
  block-sampled states (seed89260904), W1/N30=0.919x, W4/N30=0.963x,
  production N90/R900=2.939x measured decision wall. These are noisy diagnostics
  on a shared Mini, **not** the cloud budget calibration. Raw receipt:
  `/private/tmp/cwv-shortlist-cost-mini-stratified-20260905/`.
- An earlier seven-state systematic-stride probe overrepresented leads and is
  retained at `/private/tmp/cwv-shortlist-cost-mini-20260905/`, but is not used
  for choosing the screen dose. The cost sampler now avoids four-seat aliasing.

Historical next steps at the original source freeze: consolidated source review; exclusive Strength timing window;
publish the dose choices; run and retain all five arms; append result/ledger
and request the result review for merge under Jerry's authorization.

## Sep 6 scaling assessment — #248 / #251

The retained **A+B+C W32** run (not the original A+B checkpoint above) completed
256 deal clusters / 512 mirrored rounds. Checkpoint SHA:
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
Source: `2f98cf404f58fdfd9bad823d04b21c581b49ef94`; seed0 `90260904`, rank 2,
four alternatives plus incumbent, batch128, N30/R300. Its signed-level utility
was +0.13867 per round, paired-deal bootstrap 95% CI [+0.06445, +0.21680], at
**10.6126x production decision wall**. This is opened exploratory DEV evidence,
not equal-work superiority or independent confirmation.

Retained evidence on Mini:
`~/shengji-archive/2026-09-05/cwv-shortlist-abc-rerun/learned-3x/`.
The directory's historical `3x` name is not its measured cost or world count.

### Where a larger final-MC budget would go

Reading all 256 existing cluster traces, with counts reconciled against the
stored summary (no games, model inference or new labels):

| Quantity | Observed |
|---|---:|
| Arm decisions / forced singletons / searched decisions | 18,272 / 3,092 / 15,180 |
| Full selection rollouts | 1,930,770 |
| Full paired-report rollouts | 9,108,000 (82.51% of full rollouts) |
| Ranking wall / total arm decision wall | 30,924.20s / 33,952.56s (91.08%) |
| Challenger retained by report-LCB | 5,092 |
| Positive report mean rejected by its LCB | 2,596 |
| Report gap=0 and SE=0 | 1,738 |

The last row is included in the 5,092 overrides: production accepts a report
statistic **equal to** its zero threshold. It is not 1,738 proven-positive
improvements. Of 1,179 off-ballot plays, 270 had this flat sampled report tie.
Conversely, a positive mean rejected by the LCB is not proof of a missed good
action. More independent rollout samples may resolve uncertainty, but cannot
fix systematic continuation-policy bias or a bad candidate set by themselves.

On these fixed positions, doubling **all nonranking time** would increase arm
decision time by 8.92%, or both sides' combined decision time by 8.15%. This is
a linear-cost forecast, **not a measured speed, upper bound or strength
prediction**: nonranking time includes fixed overhead, and new decisions alter
later states, RNG streams and the legal-action cost tail. It nevertheless makes
N60/R600 a substantially cheaper scaling question than doubling the 91%-of-wall
ranking stage. No bootstrap of the existing worlds is treated as fresh draws.

### Separate comparisons, after Claude releases Strength

1. **Production x10:** N300/R3000 against literal N30/R300 production on the
   retained 256 deal coordinates. Compare paired cluster utilities with retained
   ABC W32; report actual wall mismatch instead of assuming x10 means equal work.
2. **Full W64:** same checkpoint, exhaustive legal set, four alternatives,
   batch128 and N30/R300. No two-stage pruning bundled into the scaling contrast.
3. **Final MC x2:** W32/N60/R600, separately, against retained W32/N30/R300.
   The ranking recipe stays fixed; only selection and report dose double.
   This tests the combined final-MC budget, not which of N or R deserves credit.
   Do not expand this into an N-by-R grid before reading this bounded contrast.

Each new arm uses the existing 16-worker resumable paired harness, with one
native thread per worker and all completed pairs retained. No model training,
new population, duplicate integrity pass or changed live process is required.
The shared 256 coordinates improve pairing but do not make multiple comparisons
independent or turn this exploratory follow-up into confirmation.

Initial forecasts: production x10 roughly 45–60 minutes, W64 90–110 minutes,
and final-MC x2 roughly 55–70 minutes; update from completed-pair pace. These are
projections from the retained ~49-minute W32 run, not new measurements. Launch
only after the PUCT unit is actually terminal and Claude's host queue is clear.
Jerry subsequently authorized incorporating the encoding/successor-reuse
optimizations in these not-yet-started runs **after decision parity, profiling
and Claude's source approval**. Bind the same engineering mode for W32 and W64,
with a matched optimized-W32 cost measurement; retain the old W32 strength
evidence but do not call its old 10.6126x wall the optimized cost. Record the
executing source and enabled mode explicitly. This conditional adoption does
not change the checkpoint, world counts, RNG, submitted action set, model batch
shapes, or final MC policy. No live PUCT job is altered. If parity or review
fails, keep the original path and investigate before adopting the optimization.

### Isolated engineering A/B completed — 2026-09-06 02:54 UTC

On released Strength, exact PR #254 source
`30b5eddeda9c510fb8f6592b73449c1a713a9fe4` ran the actual ABC checkpoint on
seven existing saved positions, W32/N30/R300, batch128. Four learned modes and
production/production-x3/uniform controls produced all 49 requested rows. All
14 encoding and 14 successor-reuse pairs had exactly equal ordered score hashes,
batch populations, shortlist/final MC decisions and post-decision RNG state.

| Encoding / successor reuse | Seven-position end-to-end wall | Ranking wall | Speed vs reference/off |
|---|---:|---:|---:|
| Reference / off | 42.260s | 41.075s | 1.000x |
| Static / off | 37.243s | 36.082s | 1.135x |
| Reference / on | 11.887s | 10.711s | 3.555x |
| Static / on | 11.557s | 10.374s | 3.657x |

The 6,958-action position dominates: 40.156s -> 10.294s (3.901x). **Excluding
that position, the combined speedup is 1.665x**, not 3.657x. These selected
positions are not a natural-frequency corpus, so neither the ratio to production
(32.13x -> 8.79x here) nor the aggregate speedup replaces the full-game cost.
There are no repeated timing trials or timing confidence intervals in this
diagnostic; sub-millisecond forced positions should not be read as speed evidence.

Both reuse modes still process 227,552 action/world neural rows in 1,779 batches
(1,776 of 128, one of 96, two of 64). Finished-leaf and tensor constructions fall
to 2,177 each, with 225,375 reuse hits. Peak logical leaf entries are 36 and peak
tensor entries 128; each cache is bounded at 128. All actions still undergo
engine validation, and no neural rows or inference batches are elided.

Learned arms used approximately one effective CPU core each (CPU/wall 0.9998–
0.9999), deliberately isolated/sequential for a per-decision A/B. The process
lifetime RSS high-water was 356,278,272 bytes in every arm. This does **not**
measure per-arm memory savings or the aggregate RSS of 16 independent workers.
Native engine mode was enabled; torch/native math used one thread. All measured
decisions together took 109.870s, with no game outcomes opened by this profile.

Raw 49 rows, config, summary and log are retained at
`~/shengji-archive/2026-09-06/cwv-successor-profile/` on Mini, copied from
`/root/cwv-successor-profile.x94hty/` on Strength. The stored config binds the
source modules, checkpoint, native library and saved-state input SHA. Claude's
source review remains the condition before incorporating reuse into scaling.

### Production x10 launched — 2026-09-06

The separate production control started on released Strength from exact source
`508231a32a799fd76956f837b8223b3384bd8d7c` (PR #251), after all eight focused
screen/CLI wiring tests passed in the executing compiled environment. It does
not use the pending encoding/reuse changes. Unit:
`cwv-scaling-prod10-20260906.service`; root:
`/root/cwv-scaling-prod10.9nHvPq/`; output subdirectory: `production-10x`.

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -u -B scripts/cwv_shortlist_screen.py --arm production \
  --production-multiplier 10 --target-wall-multiplier 10 \
  --clusters 256 --workers 16 --seed0 90260904 --out OUTPUT
```

The existing per-pair progress/ETA and atomic-shard recovery are unchanged.
An outer 7,200s / 24GiB process limit protects the host; expiry retains completed
pairs and is not a scientific discard rule. Initial ETA remains 45–60 minutes,
to be replaced by measured pair pace. No job was interrupted to make room.
No new teacher collection, merge or deployment is bundled here.

### Reviewed optimized replay queued; retained production x3 reused

Claude PASSed exact optimization source `30b5edde` in
[#254 comment 5556545319](https://github.com/jerryyyu/shengji/pull/254#issuecomment-5556545319).
The pass includes 316 real-state equivalence checks, 161-position checkpoint
parity and can-fail world-key/pruning mutations. Rebase for the current CI
fixture is a **pre-merge** follow-up, not a change to this executing source.

The queued unit `cwv-scaling-w32-optimized-20260906.service` waits for the live
production-x10 unit to end and its complete 256-pair summary to exist without a
failure record. It then runs the identical original W32/N30/R300/4-alternative/
batch128/256-deal recipe with `--encoding mlp-static --reuse-successors` on
16 workers, from the already profiled `/root/cwv-successor-profile.x94hty/`
tree. Output: `w32-paired/`; log: `w32-paired.log` in that tree.
The small wait wrapper is retained beside it as
`launch_optimized_w32_after_prod10.sh`; it does not start W64 or MC-x2 by itself.
Its 3-hour outer limit includes waiting, retains completed pairs, and does not
discard the run's science on expiry.

This repeats the **same opened** 256 deals to measure representative optimized
end-to-end cost and check trajectory preservation; it is not fresh confirmation
or a second opportunity to select W32 by its outcomes. Reuse the old reference
run rather than rerunning an unoptimized comparator. Afterwards run W64 and
W32/N60/R600 separately, with the same optimization mode and checkpoint. Existing
#254 CLI already supports all three doses; no source integration/review round is
needed. Keep its descriptive wall target at 3x and report actual cost/overrun,
not an equal-work pass. The multiplier label does not control search effort.

There is also a completed same-population production-x3 control in
`~/shengji-archive/2026-09-05/cwv-shortlist-screen/production-3x/`: N90/R900,
256 pairs, identical original source/native hashes. Reusing it avoids another
control run. Its utility is +0.06836 signed levels/round (95% CI [0, +0.13672])
at 2.9579x production decision wall. On paired deal means, retained ABC W32 minus
production-x3 is +0.07031 [−0.02344, +0.16602], **not a resolved superiority**.
The old W32 cost was still 10.6126x; compare against optimized cost only when the
queued measurement finishes. None of these same-population comparisons is a
direct candidate-vs-candidate duel or independent confirmatory evidence.

The bounded read-only comparison driver is retained at
`/private/tmp/shengji-cwv-scaling.IZpVEL/compare_completed.py`. It reads complete
mirrored shards, reconciles their utility means to stored summaries, pairs deal
coordinates and reuses the existing screen's bootstrap (1,000 replicates,
seed20260904); no model/rollout recomputation or partial outcome selection.

### Remaining fixed-dose arms queued behind the replay

`cwv-scaling-tail-20260906.service` waits for the optimized-W32 unit to end.
Before starting any new arm it requires the completed W32 summary and compares
all saved mirrored traces against the original reference. The comparison keeps
chosen actions, recorded shortlist means, report statistics/seeds, history
digests, outcomes, sampler/full-rollout counts and neural row/batch counts.
Only named timing fields and the new encoding/reuse flags/cache telemetry are
ignored. Eight in-memory mutations of actual retained evidence (including play,
history, score, seed, and batch count changes) all fail this comparison; altered
timings/opt-in metadata are accepted. This reads files, not another model or
rollout evaluation. It does not claim that the old shards stored every raw
per-action neural score; those exact-score comparisons are the separate profile.

The source and the `compare_engineering_replay.py`, `compare_completed.py`,
`launch_scaling_tail_after_w32.sh` analysis/queue helpers are retained under
`/root/cwv-successor-profile.x94hty/`. The original Strength reference summary
and config at `/root/cwv-shortlist-abc-20260905.WZyZtH/learned-3x/` match the
Mini archive's SHA-256s. No existing run, source file or artifact is rewritten.

The fixed order is:

1. Read the completed production-x10 and optimized-W32 paired comparison.
2. W64/N30/R300 -> `w64-paired/`.
3. Restore W32 and use N60/R600 -> `w32-mc2-paired/`.
4. Read completed summaries/shards and print their paired comparisons.

Both new arms retain the same reviewed source, ABC checkpoint, 256 deal
coordinates, four alternatives, batch128, static encoding/reuse, and 16 workers
with one native thread each. This is not a parameter sweep: no outcome chooses
the next setting. `scaling-tail.log` identifies each phase and carries the
existing completed-pair percentage/ETA plus process CPU/RSS/time reports.
The tail's 6-hour outer host limit includes time spent waiting for W32. Any
failure or saved-trace mismatch stops the tail without advancing; every
completed pair remains on disk for the existing identical-recipe recovery.

### Production x10 completed — the missing comparable-compute control

All 256 pairs / 512 mirrored rounds completed normally in **39m58.04s**, exit0,
on 16 Strength workers. Process-tree CPU averaged 1,557% (~15.57 cores); measured
user+system CPU was 37,361.59s, no swaps. `/usr/bin/time`'s maximum child RSS was
508,892KiB; that is not the sum of worker memory (the observed live cgroup memory
was about 6GiB). The optimized-W32 wait unit then started automatically.

| Arm | Signed levels/round [95% deal CI] | Actual arm/opponent decision wall | Total arm decision wall |
|---|---|---:|---:|
| Retained ABC W32, unoptimized | +0.13867 [+0.06445, +0.21680] | 10.6126x | 33,952.56s |
| Production x10, N300/R3000 | +0.10547 [+0.03511, +0.17773] | 9.8880x | 33,902.01s |

W32 minus production-x10, paired on the 256 shared deal coordinates, is
**+0.03320 [−0.07236, +0.13677]**. Thus the missing control does not establish a
W32 advantage at comparable compute. The two total arm decision times differ
by only 0.15%; their within-run opponent-normalized ratios differ more because
their trajectories also change opponent decision time. No exact equal-work
label is inferred from nominal N or the `10x` name.

Production-x10 used 120,932,400 full rollouts versus W32's 11,038,770 full
rollouts plus 149,192,288 cheap neural action/world rows. These are distinct
work types, not interchangeable sample counts. The raw config's generic
`report_worlds=300` and shortlist N30 fields are not production-x10's actual
dose: the production worker applies `production_multiplier=10`, yielding
N300/R3000; the opponent remains N30/R300.

Result source: `/root/cwv-scaling-prod10.9nHvPq/production-10x/`; preserved on
Mini under `~/shengji-archive/2026-09-06/cwv-shortlist-scaling/production-10x/`
with the process log alongside. The read-only comparison helper reconciled all
256 paired utilities with the stored summary and reused the original bootstrap
seed/replicate count. No new model evaluation or policy tuning produced this
contrast. Optimized W32's completed cost and trajectory readout is still needed;
the seven-state 3.657x speedup must not be substituted into this table as a
whole-game measurement. This is exploratory opened DEV, not a promotion result.

### Optimized W32 completed — exact saved trajectories, 2.85x less decision wall

Exact reviewed source `30b5eddeda9c510fb8f6592b73449c1a713a9fe4` completed all
256 pairs / 512 mirrored rounds, exit0, with no summary problems. The queued
read-only comparison found **zero mismatched clusters**. Both normalized saved
trace chains hash to
`35331c35d8462560ff7bf1f1b97dd643d5d4d4a3deffa3dc59692459c67697c3`.
The comparison retains the decisions, saved scores, report seeds/statistics,
history digests, outcomes, model rows/batches and sampler/rollout counters;
only the previously named timing and opt-in cache metadata differ. This is
decision-preserving engineering on the original opened deals, not another
independent strength result.

| Quantity | Original W32 | Static encoding + successor reuse |
|---|---:|---:|
| Signed levels/round vs production N30/R300 | +0.13867 | +0.13867 (identical) |
| 95% paired-deal interval | [+0.06445, +0.21680] | identical |
| Total arm decision wall | 33,952.56s | 11,916.94s |
| Ranking wall | 30,924.20s | 8,719.90s |
| Actual arm/opponent decision wall | 10.6126x | 3.5287x |
| Full MC rollouts | 11,038,770 | identical |
| Scored action/world rows (includes exact terminals) | 149,192,288 | identical |
| Scoring batches | 1,170,992 | identical |
| Paired-run progress-loop elapsed | 48m57.3s | 24m23.9s |

Thus decision wall fell **64.90% (2.849x speedup)**, ranking wall fell by a
factor of **3.546x**, and the parallel job's elapsed time improved **2.006x**.
The separate process timer includes startup/summary overhead and reports
**24m27.11s**, 15,332.00 CPU seconds, **1,045% mean CPU (~10.45 cores)**,
483,160KiB maximum child RSS and zero swaps. The largest observed live cgroup
peak was **4.8645GiB**, distinct from child RSS. This is a measured snapshot of
the cgroup peak, not a retained post-exit aggregate-RSS receipt.

The lower whole-job speedup is important. The last pair, cluster255, ran alone
for **507.9s after pair255/256 completed**. Its two widest ranking decisions
have 64,897 and 44,760 submissions; they recorded **zero leaf-cache hits** and
took 330.58s and 201.25s. Other wide positions do collapse: cluster151's
55,314-action decision recorded 1,769,212 hits and 836 leaf completions across
32 worlds. Do not extrapolate the earlier 6,958-to-25 example to every wide
position, or infer that increasing the cache bound would fix a zero-hit case
without checking its accepted-successor population.

Across all decisions there were 134,486,297 leaf hits / 149,192,288 root-action
applications (**90.14% row-weighted reuse**), 14,705,991 leaf completions,
14,702,710 tensor constructions and 134,486,297 tensor hits. Terminal leaves
need no neural input, so leaf and tensor completion counts need not coincide.
There were 3,281 exact terminal rows and 149,189,007 nonterminal model rows;
the earlier shorthand "neural rows" for all 149,192,288 scoring rows included
those exact terminals. Scoring-batch counts likewise describe evaluator calls,
not necessarily a network forward for an all-terminal batch.
Only 4,136 of 15,180 non-forced ranking decisions had any leaf hit: most savings
come from large repeated-action populations, not most decisions. Cache maxima
stayed at 128 entries each. Scoring batches averaged **127.407 / 128 rows
(99.54% occupancy)**; reducing neural rows was not part of this optimization.

Ranking still consumes **73.17%** of arm decision wall. The optimized arm also
remains **above the descriptive 3x target** at 3.5287x; neither the label nor
the unchanged signed-level metric creates an equal-work pass. Against the retained
production-x3 control (2.9579x), the same-deal utility difference remains
+0.07031 [−0.02344, +0.16602], unresolved. Against production-x10, the utility
difference remains +0.03320 [−0.07236, +0.13677], now at much lower measured arm
cost. This supports a better measured strength/cost tradeoff, not a resolved
head-to-head superiority at precisely matched compute.

Completed replay and process log are preserved on Mini at
`~/shengji-archive/2026-09-06/cwv-shortlist-scaling/w32-paired/` and
`w32-paired.log`. `scaling-tail.log` retains the parity proof and comparisons;
its current archive is a snapshot while the tail continues. After the guard
passed, the predeclared W64/N30/R300 arm started automatically on 16 Strength
workers; W32/N60/R600 remains next, without outcome-dependent changes.

Follow-up engineering opportunity, **not applied to these running arms**:
schedule known expensive replay pairs earlier using prior timing only, while
preserving per-deal seeds, recipes and sorted results. Witness worker/order
independence before using it. The progress ETA currently extrapolates completed
pair means and repeatedly predicted seconds during this eight-minute tail;
future monitoring should distinguish an active straggler from an average-rate
ETA. Neither requires discarding or rerunning completed evidence.

### W64 completed — extra ranking worlds did not earn their cost here

All 256 pairs / 512 rounds completed, exit0, with no summary problems. The
complete config differs from optimized W32 **only in `shortlist.worlds`,
32 -> 64**; checkpoint, source hashes, runtime, encoding/reuse, four
alternatives, final N30/R300 and all other fields match. No pruning or new
checkpoint is bundled with this width comparison.

| Quantity | Optimized W32 | Optimized W64 |
|---|---:|---:|
| Signed levels/round vs production N30/R300 | +0.13867 | +0.09570 |
| 95% deal-bootstrap interval | [+0.06445, +0.21680] | [+0.02930, +0.16606] |
| Actual arm/opponent decision wall | 3.5287x | 6.2658x |
| Total arm decision wall | 11,916.94s | 20,307.54s |
| Ranking wall | 8,719.90s | 17,231.91s |
| Full MC rollouts | 11,038,770 | 11,035,110 |
| Scored action/world rows, including exact terminals | 149,192,288 | 301,555,328 |
| Scoring batches | 1,170,992 | 2,359,346 |

Paired W64 minus W32 is **−0.04297 [−0.09570, +0.00781]**, using the same
256 mirrored deal clusters, 1,000 bootstrap replicates and seed20260904.
That interval includes zero: do not call W64 statistically worse or claim
that additional worlds never help. This bounded opened-DEV run simply provides
no improvement to justify **1.704x total arm decision wall**. The two
arm/opponent ratios differ somewhat more because changed trajectories also
change opponent decision time. This is a same-deal comparison against a common
production opponent, not a direct W64-versus-W32 duel or fresh confirmation.

Ranking wall nearly doubled (**1.976x**) and now consumes **84.85%** of arm
decision wall. Aggregate scoring rows are slightly more than twice W32's
because the decisions/trajectories differ, not because another parameter was
changed. Of W64's scoring rows, 6,592 are exact terminals and 301,548,736 reach
the model; batch occupancy averages 99.85%. The final MC budgets did not change.

Process wall was **41m25.27s**, with 23,584.09 CPU seconds, **948% mean CPU
(~9.49 cores)**, maximum child RSS 494,976KiB and no swaps. The observed live
cgroup peak before transition was about 4.81GiB. Progress-loop wall was
41m22.3s; its final pair alone added 925.5s after 255/256 completed. As with
W32, the single-pair tail depresses whole-job core utilization. Do not confuse
that batch-scheduling limitation with the measured per-decision cost of W64.

Archive: `~/shengji-archive/2026-09-06/cwv-shortlist-scaling/w64-paired/`, with
the process timer in `scaling-tail.log`. The comparison helper re-read and
reduced completed saved records on Mini; no model inference or new rollout
evaluation was needed. The full-source config comparison was exact after
substituting only the intended world count.

The queued **W32/N60/R600** arm started automatically after W64's successful
exit, on the same 16-worker Strength unit and exact source. It was not selected
in reaction to this result. Interim width conclusion: retain W32 as the
reference; do not escalate to W128 on this evidence. The final-rollout readout
is still needed before selecting the next bounded search recipe.

### Final MC budget completed — doubling rollouts did not demonstrate a gain

The last predeclared arm completed all 256 pairs / 512 mirrored rounds, exit0,
with no problems or refusal. The tail unit then performed its saved-file
comparison and exited successfully: no further gameplay is queued. Source
remains `30b5eddeda9c510fb8f6592b73449c1a713a9fe4`.

The complete config equals optimized W32's config after changing only
`shortlist.selection_worlds: 30 -> 60` and `report_worlds: 300 -> 600`.
Checkpoint, four alternatives, W32 ranking, batch128, encoding/reuse, runtime,
source hashes and deal population match. All **15,210 searched arm decisions**
actually recorded N60/R600; all **15,085 searched opponent decisions** recorded
N30/R300. Every corresponding completed report receipt used the stated number
of worlds. Another 3,074 arm decisions were forced, without an MC dose trace.

Important inherited-summary caveat: `arm_description` still says identity
control and `work.arm_effective` still shows the base registry's N30/R300.
`summary_for` inherits those template fields from the base duel summarizer;
they do not describe the executed learned arm. The full config, per-decision
`selection_N`/`report_worlds`, report receipts and measured counters establish
the actual dose above. This is misleading report metadata, not an identity
run or a missing budget change. Preserve the original artifacts; fix these
labels with consumer-level witnesses in a future source update, not by
rewriting receipts or repeating this run.

| Quantity | Optimized W32 N30/R300 | Optimized W32 N60/R600 |
|---|---:|---:|
| Signed levels/round vs production N30/R300 | +0.13867 | +0.12109 |
| 95% deal-bootstrap interval | [+0.06445, +0.21680] | [+0.04688, +0.19146] |
| Actual arm/opponent decision wall | 3.5287x | 4.4921x |
| Total arm decision wall | 11,916.94s | 14,991.52s |
| Ranking wall | 8,719.90s | 8,698.35s |
| Full MC rollouts | 11,038,770 | 22,113,360 |
| Scored action/world rows, including exact terminals | 149,192,288 | 146,923,008 |
| Scoring batches | 1,170,992 | 1,153,282 |

Paired MC2 minus W32: **−0.01758 [−0.11919, +0.07227]**, with 57 deal
clusters better, 60 worse and 139 tied. Same 1,000-replicate deal bootstrap,
seed 20260904. No improvement is demonstrated for **25.80% more total arm
decision wall**; the interval also does not establish harm. Neither this
result nor W64 closes higher-compute search in general. Here the two extra-work
allocations failed to earn their cost on the observed point estimates.

Ranking work/time stayed nearly unchanged because W remained 32; it accounts
for **58.02%** of this arm's decision time. Non-ranking decision time grew to
6,293.17s, and full rollouts rose **2.003x**. Different trajectories explain
the small non-doubling of aggregate counts. There were 3,572 exact terminal
scoring rows and 146,919,436 nonterminal model rows; average scoring-batch
occupancy was **99.53%**. Both logical cache maxima remained 128.

Whole-process elapsed was **27m35.24s**, with 18,369.22 CPU seconds,
**1,109% mean CPU (~11.10 cores)**, maximum child RSS 502,076KiB and no swaps.
The largest observed shared-unit cgroup peak during MC2 was **5.1133GiB**;
this is a sampled live peak, not a separate post-exit per-arm RSS receipt.
Progress-loop elapsed was 1,651.8s; the final pair added **512.7s** after
255/256 finished. The average-pair ETA kept predicting seconds during this
eight-minute tail; completed work was retained and the live worker was not
restarted.

Mini archive: `~/shengji-archive/2026-09-06/cwv-shortlist-scaling/` now contains
`w32-mc2-paired/`, the **final** `scaling-tail.log` (not an in-flight snapshot),
`mc2-dose-cost-readout.json` and `final-comparison.json`. The latter reuses the
existing paired comparison helper on completed W32, production-x3,
production-x10, W64 and MC2 records. No model inference, new labels or gameplay
was needed for closeout. Original Strength artifacts remain intact.

### Combined readout and smallest next step

All rows below are measured against normal production on the same 256 rank-2
deals and mirrors. The optimized W32 row is the exact engineering replay of
the original, not a new independent strength observation. Actual cost ratios
use each arm's opponent decision wall; use total arm times when comparing
cost across trajectories. These are opened DEV comparisons, not deployment
evidence, exhaustive-rank coverage or direct candidate duels.

| Arm | Signed levels/round [95% interval] | Actual decision-wall ratio |
|---|---|---:|
| Production N90/R900 (retained control) | +0.06836 [0, +0.13672] | 2.9579x |
| Production N300/R3000 | +0.10547 [+0.03511, +0.17773] | 9.8880x |
| Original W32 N30/R300 | +0.13867 [+0.06445, +0.21680] | 10.6126x |
| **Optimized W32 N30/R300** | **same +0.13867, identical decisions** | **3.5287x** |
| Optimized W64 N30/R300 | +0.09570 [+0.02930, +0.16606] | 6.2658x |
| Optimized W32 N60/R600 | +0.12109 [+0.04688, +0.19146] | 4.4921x |

The comparable-compute contrast remains unresolved: original W32 minus
production-x10 = +0.03320 [−0.07236, +0.13677], at nearly identical total
arm decision wall. Engineering then retained that W32 performance at much
lower cost. Optimized W32 minus production-x3 = +0.07031 [−0.02344, +0.16602],
but their costs are not exactly matched. Do not interpolate an unrun
production 4–6x result or turn positive point estimates into a resolved lead.

**Retain optimized W32/N30/R300 as the working reference.** It is the least
costly learned arm tested here and has the highest point estimate, not a
proven globally optimal recipe. No W128 or larger uniform rollout escalation
is justified by this bounded screen alone.

1. **Next policy question: admission breadth, four -> eight alternatives.**
   Use the existing harness and same ABC checkpoint, W32/N30/R300, batch128,
   encoding/reuse and heuristic anchor. Change only `alternatives`; do not
   simultaneously change the checkpoint, prune worlds or deepen search.
   This tests whether the final search needs better options rather than more
   samples of its current options. Keeping eight instead of four is cheap
   for the existing ranking matrix but adds MC selection work; report that
   measured cost and the paired uncertainty. This is a proposed bounded
   follow-up, not another launch in the completed queue. A selected recipe
   then needs a fresh disjoint, rank/suit-diverse comparison with a production
   control at measured comparable work before a stronger claim.
2. **Next engineering steps:** bypass futile successor-cache work for legal
   follow roots and schedule historically expensive replay pairs earlier,
   with exact decision/order/seed/recovery witnesses. The saved-time scheduling
   calculation projects 1.51x batch throughput, not measured latency improvement.
   Neither change was applied to these runs. Also correct the inherited
   summary labels and make active-straggler ETAs explicit before the next run.
3. **Two-stage pruning stays a separate policy experiment.** The corrected
   precheck gives k4/K200 only 48/59 agreement on binding states; its >=30,000-
   action tail is unmeasured despite representing 26.2% of model rows in that
   source. Its old wall projections predate the 2.849x engineering gain and
   are not measured wall savings. Include that tail and distinguish agreement
   with W32 from actual rollout quality before selecting a pruning recipe.
   Random-subset rollout residual correction and selective depth remain later
   named hypotheses, not additions hidden inside this comparison.

Teacher-data investigation is also complete in #246,
`TEACHER_TOKEN_EFFICIENCY.md`: matched batch4 delivered 2.70x rounds per raw
token and 2.08x rounds per wall; the authorized 16-game cost extension finished.
Quality is inconclusive, so the proposed next teacher step is a bounded bridge
to historical rollout-enabled Luna before scale-up, followed by the existing
journal's resume wiring and an explicit Sol compatibility/cost check. The
proposed collection keeps fit/selection/validation deals disjoint and labels
the actual continuation policy; no new teacher collection is launched here.

This completes the bounded teacher/engineering/scaling investigation requested
in the active goal. #248 remains the follow-up tracker, and #254's pre-merge
rebase/CI cleanup is still separate. No merge, deployment, production-default
change or scaled teacher collection follows from these results.
