# PT-Luna paired gameplay: first eight-deal tranche

Completed all **8 distinct seeded deals / 16 mirrored rounds** at source
`6056dae5b76b700365e6980bd0ddcb0080be3279` (PR #280), with no failed or unknown-usage
calls. This is real batch4-versus-compact1 gameplay, not another capacity probe.
Both teams used the same full-information Luna medium policy, compact prompt,
ballot and no tools; separate team plans persist across play. Only batching
differs. It does not compare either arm with production or the historic teacher.

## Quality and cost

| Measure | Result |
|---|---:|
| Batch4 signed levels per round | +0.125 |
| 95% deal-bootstrap interval | [−0.25, +0.50] |
| Batch4 round win rate | 50% [31.25%, 68.75%] |
| Positive / zero / negative paired deals | 3 / 4 / 1 |
| Complete pairs / planned pairs | 8 / 8 |
| Total reported tokens | 7,045,441 / 9,000,000 cap |

| Arm | Calls | Accepted decisions | Tokens/decision | Provider decisions/min |
|---|---:|---:|---:|---:|
| Compact1 | 475 | 475 | 10,396.44 | 4.666 |
| Batch4 | 168 | 471 | 4,473.74 | 8.346 |

Batching provided **2.324× reported-token efficiency per accepted decision** and
**1.789× serial provider throughput**, with 2.80 decisions per batch call on
average. The two arms act at different states once their trajectories diverge;
these are realized workload costs, not a matched-position token A/B. Reported
input tokens include cached input tokens, so these ratios are not subscription
quota percentages or dollar savings. Provider-reported time sums to 2h38m14s;
the run used one provider request at a time. Mini also hosted Claude's training
and, later, an ACD screen, so this is not an isolated hardware wall benchmark.

The quality interval is wide. This is **no detected gameplay difference**, not
equivalence, a better teacher claim or a replacement for the stronger historic
rollout-enabled teacher. The separate #275 matched-position bridge measured a
quality gap favoring that older teacher; the two comparisons must not be pooled
as though they shared the same prompt/tools/reasoning or metric.

## Reusable evidence and limits

All 16 trajectories, including losses, are retained with source/root hashes,
agent assignments and `play-only` continuation metadata. Four deals are tagged
fit and four validation; keep both mirrors together. Coverage is one deal at
each rank 2–9, with root trump D 3, H 2, S 1 and NT 2. This does not represent
all thirteen ranks or every trump suit. There are **eight distinct seeded deals**,
not 946 independent labels or sixteen independent paired observations.

### Shared-response dependence — readout caveat added before opening the remaining 44

The eight first-tranche deals shared one fixed collector wave. Batch calls never
cross a wave, but responses can couple games within it; independent deal seeds
do not prove independent teacher errors. The original paired-deal means and
bootstrap intervals above are retained, **not** recast as wave-adjusted intervals.
The illustrative deal-level power arithmetic below has the same limitation.

The prepared readout additionally reports roster-bound wave membership and an
equal-deal-weighted leave-one-wave-out range. This is a descriptive sensitivity
check, not a confidence interval, new pass gate or reason to discard trajectories.
One observed wave has no such range. The unchanged remaining 44 run has six
planned waves (8+8+8+8+8+4); the exploratory 52-deal pool has seven. That is still
too few, and too structured by roster order, to assume reliable wave-level
population inference. Missing pairs remain explicit and never shift later games
into a different wave. No current-tranche outcomes were opened for this amendment.
All original fields except interpretation match the saved first-tranche readout
exactly (the new sensitivity field is additive). The 62 focused readout/harvest
tests pass, including unequal groups, missing mirrors, original roster order,
separate tranche wave identities and unavailable historical wave metadata.

The original complete run, provider calls and progress records remain at
`~/.shengji-runs/luna-quality-games-tranche1-20260906.yNwAwr/` on Mini. A complete
27-MiB retained copy plus the no-replay `readout.json` is at
`~/shengji-archive/2026-09-06/luna-gameplay-tranche1-final.WQKoLZ/`.
No winning-game filtering, label transplantation or automatic data promotion.
These exposed validation deals must not be relabeled as fresh confirmation.

### Native harvest reuse

The flat gameplay files can now enter the existing decision-record/replay
pipeline without fabricating historical `attempts/*` manifests:

```sh
python -B -m scripts.harvest luna-quality --run /path/to/completed-run \
  --split fit --out /path/to/new-fit-export
```

Repeat with `--split validation` and a separate output directory; repeat `--run`
for disjoint tranches. Source, acting batch arm, mixed play-only continuation,
model/effort, coordinate/mirror and original fit/validation labels are carried
in required provenance. This is **not** historical rollout-enabled Luna data.
The importer is excluded from `harvest all` and refuses output overwrite.
Provenance is administrative metadata, not a model feature. Do not pass these
validation files to fitting: the trainer's random deal split does not enforce
the source's holdout labels. Importability is not automatic training admission.

The real first-tranche diagnostic export retained **596 fit + 556 validation
records**, including all 16 rounds and all losing seats: 946 model decisions
plus 206 forced single-candidate decisions. Hidden hands, the synthetic deck
and burial stay in the mode-0600 private output. Missing/partial games receive
no invented terminal target; their raw trajectories remain at source, and a
completed mirror is not discarded when its partner is incomplete.

Diagnostic exports and the legacy byte-parity check are retained under
`~/shengji-archive/2026-09-06/luna-gameplay-harvest-check.TXWLnX/`.
They were generated from the implementation worktree (the sidecar's Git head
is its parent), not a frozen producer. The actual exporter/replay path took
under two seconds for both splits; this is a functional check, not an isolated
performance claim. No training or current-tranche outcome read was performed.

## Pricing the next tranche, not launching it

The first-tranche allowance does not authorize the remaining 44 deals. At this
observed mix, all 52 deals project to **45.80M reported tokens**, or **38.75M
additional tokens** for the remaining 44, and roughly 17.1 total serial provider
hours. These are linear planning estimates; rank/trajectory and provider tails
can change them.

The eight paired values have sample SD 0.5825 levels/round. An illustrative
normal approximation gives a 95% half-width about 0.16 at 52 deals and about
119 deals for 80% power against a 0.15-level effect. Eight deals are too few for
a reliable power guarantee. Choose a practically meaningful quality margin and
an affordable fixed continuation before spending the larger budget; do not stop
on the first favorable repeated interval or choose favorable replacement roots.
The completed tranche establishes usable full-game collection and meaningful
token savings, **not completion of the larger quality experiment**.

## Continuation plan — subsequently authorized and launched

The proposal below is retained as its pre-launch rationale. Jerry's additional
45M-token / 18-hour approval is recorded in
[PR #280](https://github.com/jerryyyu/shengji/pull/280#issuecomment-5562959834),
and the unchanged 44-deal collector launched on Mini on September 6 at 19:32 EDT.
Its result remains pending; neither the first-tranche result nor the exports
above substitute for the larger comparison.

`runs/luna_quality_gameplay_remaining44_20260906.json` contains exactly the
original manifest's unused coordinates, in manifest order. The existing panel
and selector validators confirm **44 deals, zero overlap**, 22 fit and 22
validation roots. Their actual root trumps are C 11, D 9, H 11, S 11 and NT 2.
Together with tranche one this restores the complete 52-deal rank-balanced
panel. No provider calls or outcome-based root selection were used to prepare it.

Proposed additional ceiling for Jerry's decision: **45M reported/reserved tokens
and 18 hours**, against a linear 38.75M-token / 14.5-hour estimate. This is not
funded by the unused portion of tranche one's allowance. Do not launch without
the new ceiling. Keep source behavior, model/reasoning, prompt, tools, team
memory, one provider, eight-coordinate waves and 120-second call cap unchanged.
The last four-coordinate wave may batch less efficiently; costs remain estimates.

Use a new private output root; do not extend the completed eight-deal run or
transplant calls. Existing recovery retains completed games and accepted provider
responses under the original deadline/budget. Report the 44-deal tranche and
pooled 52-deal exploratory estimates, always bootstrapping by deal and disclosing
incomplete pairs. No repeated-significance stopping, replacements, automatic
larger tranche or teacher/data promotion. This is an expanded roster and budget,
not another implementation, smoke/capacity run or source-review cycle.
