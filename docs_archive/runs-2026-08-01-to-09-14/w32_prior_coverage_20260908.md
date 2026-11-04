# Public-prior coverage of W32 proposals — 2026-09-08

**Keep value-only W32 as the baseline.** The old public policy heads are cheap
proposal sources, but neither safely preserves W32's best alternative under
aggressive filtering. This is agreement with a model, not move quality or strength.

## What ran

52 already-opened FIT root snapshots from the retained Luna comparison panel;
all 52 completed for each head. Same W32 `3cd27716`, 32 sampled worlds, four
alternatives plus the mandatory incumbent, batch128, static encoder and successor
reuse. Both prior heads see the root actor's observation and exhaustive legal set.
The W32 value rankings were exactly identical across the two runs. No MC gameplay
screen, hidden-label opening, registry change or production change.

The legal sets range from 6 to 5,016 actions (10,287 total). These are root positions,
not a representative sample of decisions across a round. Small legal sets make
large-prefix retention trivially perfect; the genuinely pruned subset is reported.

| Prior prefix, excluding incumbent | C prior: best W32 alternative retained | AB prior: retained | Roots where prefix actually prunes |
| --- | ---: | ---: | ---: |
| 16 | 44/52 (11/19 pruned) | 44/52 (11/19 pruned) | 19 |
| 32 | 49/52 (10/13 pruned) | 46/52 (7/13 pruned) | 13 |
| 64 | 51/52 (10/11 pruned) | 49/52 (8/11 pruned) | 11 |
| 128 | 51/52 (8/9 pruned) | 50/52 (7/9 pruned) | 9 |

C prior scoring took 0.048s across the panel; W32 value ranking took 16.827s.
This is component timing on Mini, not an end-to-end speedup: the diagnostic still
ranks every action with W32. A two-value/two-prior hybrid retained 80.8% of W32's
four proposals on average with the C head. Its best W32 alternative is retained
by construction, so that alone cannot demonstrate improved quality.

## Next test

Prefer a bounded **union** experiment: incumbent + four existing value proposals
+ two distinct prior proposals, leaving selection/report logic unchanged.
Compare with value-only W32 and a matched-width value-only shortlist to distinguish
prior content from simply searching more moves. Measure final decisions, paired
gameplay and actual cost; do not turn this FIT agreement result into a promotion.
The historical wider-shortlist null remains relevant, but does not test prior content.

`3cd27716` is a value-only checkpoint; its policy head is separate. The trainer's
`--public-head` is an evaluation comparator, not an input to the CWV model or its
optimizer. C and AB are older v1 policy heads, not policy heads trained on the newer
ACDEF data. A lack of benefit here would not close better-trained priors.

## Reproduce / evidence

From `server/`:

```sh
SHENGJI_FAST=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=. \
  python scripts/cwv_prior_coverage.py --value-checkpoint VALUE.pt \
  --prior-checkpoint PRIOR.pt --panel OPENED_FIT_PANEL.json \
  --out NEW_DIRECTORY --limit 52 --deadline-seconds 300
```

The deadline is checked between roots; an external process limit is needed for a
hard wall bound. Completed rows/progress survive errors; partial/error runs return
nonzero. Outputs include opaque IDs and full rankings, not plaintext hands.

- Value SHA: `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
- C prior SHA: `b0001163407fa24ebe02087d4042d9273e5d875b5d6173a9186fd3ce02cb3b8e`.
- AB prior SHA: `b7fcd798b557b6049064896045b58c651a58c61c8a5c7cff85bff3c2538a63cb`.
- FIT panel SHA: `048672b5df256dceaf788af9bde45e405c2cb0ac936c894ba443c758cbf81e33`.
- Private artifacts: `~/shengji-archive/2026-09-08/w32-selected-serving.zXBQED/prior-{c,ab}-fit52/`.
- Executed script SHA: `d65d5dae71e87ff56cb5fc375c43338a514bf6186901099fa80c92a06394296f`.
- 20 targeted tests passed (11 diagnostic + 9 existing shortlist tests). Includes
  actual candidate-path wiring, no production-tractor skip, exhaustive-single-action
  refusal boundary, exact positive/negative retention values and error persistence.

The initial diagnostic copied production's tractor/ballot skips; primary review
removed them before either run because W32 deliberately bypasses those restrictions.
