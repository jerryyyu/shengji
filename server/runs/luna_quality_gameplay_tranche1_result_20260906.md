# PT-Luna paired gameplay: first eight-deal tranche

Completed all **8 independent deals / 16 mirrored rounds** at source
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
all thirteen ranks or every trump suit. There are **eight independent deals**,
not 946 independent labels or sixteen independent paired observations.

The original complete run, provider calls and progress records remain at
`~/.shengji-runs/luna-quality-games-tranche1-20260906.yNwAwr/` on Mini. A complete
27-MiB retained copy plus the no-replay `readout.json` is at
`~/shengji-archive/2026-09-06/luna-gameplay-tranche1-final.WQKoLZ/`.
No winning-game filtering, label transplantation or automatic data promotion.
These exposed validation deals must not be relabeled as fresh confirmation.

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
