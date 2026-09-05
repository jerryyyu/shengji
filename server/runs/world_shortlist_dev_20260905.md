# Many-world shortlist: initial DEV cost probe (2026-09-05)

Result: the producer-to-consumer implementation and focused tests work. The
small cost probe supports trying a 32/64-world cheap stage; **it says nothing
yet about playing strength**. No large gameplay screen or deployment ran.

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

## Validation and next useful measurement

The new tests plus neighboring inference/policy/screen/value-leaf tests passed
**95/95**. After the independent review's one trace-wiring repair, the focused
suite passed **20/20**, and the narrow re-review passed. Tests include actual
mirrored game execution and atomic output reopening; terminal sign/units;
hidden-world twin identity for both head types; real batched/scalar agreement;
incumbent retention; fresh/refill RNG behavior; model exclusion from full
refinement/report; and exact persisted candidate-index/counter mapping.

Next: a small mirrored DEV gameplay comparison on separate seeds, using the
existing resumable screen, production identity control, and measured-work MC
control before any equal-work conclusion. Reuse completed pairs; no additional
freeze, census or duplicate integrity run is needed for that learning test.
