# Many-world shortlist: DEV cost and gameplay results (2026-09-05)

Result: the implementation completed a 16-deal pilot and a separate
256-deal-per-arm screen. **Neither existing hybrid model demonstrated a
strength gain over production.** Both used about 18% more decision CPU.
No production deployment or new model training ran.

## Completed 256-deal screen

Executing head `c760848537dd2674fb5b671ffff90956219203d2`; policy source is
unchanged from reviewed `47094e203fa5bb143283b6116b2e82d57aa3fcfb` (the newer
head strengthens only the batch-order test). Three sequential arms, each
256 fresh independent deal clusters / 512 mirrored rounds against production
MC-LCB N30/R300, same seeds `70361904` through `70362159`, rank 2 only.
Both checkpoints and the N64/refinement16/K3/T1/batch128/R300 recipe were
fixed before the screen; the pilot was not used to pick a winning head.

| Arm | Signed levels/round | 95% deal-cluster interval | Win rate | Decision CPU / baseline | Arm / baseline CPU seconds |
|---|---:|---:|---:|---:|---:|
| Level-head hybrid, 64 cheap worlds | -0.03320 | [-0.09961, +0.02539] | 49.02% | 1.1845x | 4,077.85 / 3,442.73 |
| Points-head hybrid, 64 cheap worlds | -0.01563 | [-0.08013, +0.05469] | 50.00% | 1.1804x | 4,081.19 / 3,457.52 |
| Ordinary MC, N45/R300 | +0.02539 | [-0.04102, +0.09766] | 52.34% | 1.0958x | 3,822.37 / 3,488.23 |

All three completed 256/256 pairs with **zero reported problems, failed
worlds, or underfilled searches**, on both sides. Intervals use 1,000
bootstrap replicates over deals, not 512 independent rounds. All include
zero: neither a positive hybrid result nor a statistically established
ordering between these three arms follows from their point estimates.

MC45 was selected in a separate outcome-blind cost measurement before
gameplay: 16 MC-generated deals at seed `70461904`, plies 0/8/24/48, all
seven arms on the same 64 positions with shuffled measurement order. Choose
the smallest tested MC N in 30/45/60/75/90 costing at least the mean of the
two fixed hybrids. Measured ratios were 1.11761 (levels), 1.09705 (points),
and 1.14533 (MC45); the measurement took 32.79s. Gameplay moved the actual
ratios to those above, so this is **not an exact equal-work comparison**.

Strength unit `world-shortlist-dev256-20260905` started at 06:57:39 UTC and
exited successfully at 07:21:59 UTC on September 5: **24m20.688s wall,
6h14m59.269s CPU, 6.4 GiB peak**, with 16 workers and one numerical thread
each (about 15.4 cores utilized on average). No timeout, restart or recovery
was needed; completed pairs were published throughout. Other hosts and
production were untouched.

Each hybrid evaluated about 5.8 million learned leaves, retained the
incumbent plus two alternatives, then used about 10 million full
continuation rollouts including the report fold. This reduced full
continuations from the baseline's roughly 12 million but did not save CPU:
the learned inference path alone consumed 654-683s. Fewer full rollouts is
not the same as a faster or stronger policy.

Artifacts: `/root/world-shortlist-dev.kzwYaa/dev256/{levels64,points64,work45}`
on Strength; complete copies (all 768 pair shards, configs, summaries) at
`/Users/jerryyu/shengji-archive/world-shortlist-20260905/dev256/` on Mini.
All 768 copied shards passed the existing recipe/mirror/seed reopener on
first consumption; no games or model scoring were rerun. The launch script
and `cost-control-mcstates.json` are also archived. Originals remain intact.

The earlier 16-deal pilot (seeds `70360904` through `70360919`) finished four
arms in 150.6s with no errors: identity +0.09375, levels +0.06250, points
0.00000, MC45 -0.12500 signed levels/round. It established mechanics and a
runtime estimate, not a strength gain. All pilot shards are retained in
the sibling `dev16/` archive.

Reading: do not scale this unchanged hybrid on the basis of these results.
The next separate experiment is #229's complete-world evaluator, whose
inputs and use of the value model differ from these actor-visible heads.
This screen neither evaluates nor refutes that newer model/consumer pair.

## What changes

Starting from reviewed #226 at `95061f1334e16e214d54565337e5de5e41786323`,
keep the production ballot, Memory sampler, tractor lock and final fresh
300-world full-rollout LCB comparison. Use a batched value head across all
candidates and many shared worlds to retain the incumbent plus two alternatives.
Evaluate those on 16 fresh worlds with full heuristic rollouts to choose the
challenger. Model values never enter the refinement or report means.

This differs from #226's value-at-leaf replacement of every continuation:
the new arm uses value only to shortlist, batches across worlds, and accepts
both older signed-level heads and newer auxiliary points heads. It does not
widen the ballot, train a model, or change production registration.

## Matched-state cost

Strength Cloud, isolated `/root/world-shortlist-dev.kzwYaa`, native extension
built from this base, Python 3.14.4 / torch 2.13.0+cu130. Existing environments
were read-only; no other fleet job was interrupted. Sixteen worker processes,
one numerical thread each. Each arm saw the same 64 states: 16 independently
seeded heuristic-play deals at plies 0, 8, 24 and 48. Sixty required search.
Arm order alternated by deal/position; model loading/warmup was excluded from
decision timing. Rank 2, one-trick prefixes, batch 128, shortlist 3,
refinement 16, report 300. No underfilled searches in either probe.

| Cheap worlds | Level-head CPU / production | Points-head CPU / production | Total sampled worlds per arm across 64 states |
|---|---:|---:|---:|
| Production selection 30 | 1.000 | 1.000 | 19,800 |
| 32 | 0.933 | 0.947 | 20,880 |
| 64 | 1.061 | 1.071 | 22,800 |
| 128 | 1.402 | 1.377 | 26,640 |

Production cumulative decision CPU was 17.567s in the level probe and 17.483s
in the points probe. Whole probe wall times were 7.979s and 8.017s, respectively
(parallel work, not an individual-decision latency). The checkpoints were the
existing A-only Huber-0.5 sweep and A-only points-head model, respectively.

The 64-world setting doubles the *cheap selection* sample count versus 30,
but total worlds increase only 15.2% because the unchanged report dominates.
It costs about 6–7% more CPU here, not equal work. The 128-world setting is not
free. These are single, small, matched-state probes with no uncertainty claim;
actual self-play state distributions and integrated production fastpaths may
change the ratios. Both arms used the same source base, which predates #221's
report-session optimization. This implementation inherits `_rollout`, so it
does not replace that fastpath when the stack is integrated.

Reproduce from the isolated `server/` directory:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 MKL_NUM_THREADS=1 \
python -P -B scripts/world_shortlist_benchmark.py \
  --checkpoint /path/to/sweep-huber.pt --allow-legacy --value-kind levels \
  --deals 16 --workers 16 --cheap-grid 32,64,128 --seed0 70460904 \
  --out /new/path/cost-levels.json
```

Set `PYTHONPATH` to the isolated server directory when using `-P`; the executed
command used `/opt/belief-r4-d2d466f-venv/bin/python` and an outer 240s timeout.
The points probe used the same command with `--value-kind points`, the points
checkpoint, and a separate output. One initial invocation refused the legacy
checkpoint container before compute; the final CLI explicitly supports
`--allow-legacy` rather than inventing missing population provenance.

Raw per-state costs, stage counters, checkpoint identities and source hashes
are retained at the remote root above and copied to
`/Users/jerryyu/shengji-archive/world-shortlist-20260905/`:

- `cost-levels.json`: SHA256 `bfaa7529eea8aa4df75328b94fae8f19d6edc63290b58c357a7062d8481e137c`
- `cost-points.json`: SHA256 `d52e562927e8870b3527a9157bfc556536edf86ae5a5856cfba8a3b0a57d1255`

## Initial implementation validation (before gameplay)

The new tests plus neighboring inference/policy/screen/value-leaf tests passed
**95/95**. After the independent review's one trace-wiring repair, the focused
suite passed **20/20**, and the narrow re-review passed. Tests include actual
mirrored game execution and atomic output reopening; terminal sign/units;
hidden-world twin identity for both head types; real batched/scalar agreement;
incumbent retention; fresh/refill RNG behavior; model exclusion from full
refinement/report; and exact persisted candidate-index/counter mapping.

That initial next step was completed by the pilot and 256-deal screen above,
using the existing resumable runner without another freeze, census, or
duplicate integrity run.
