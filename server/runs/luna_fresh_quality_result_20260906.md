# Fresh PT-Luna batching diagnostic — completed September 6

**Measured token saving; action-quality difference inconclusive. Not a
whole-game strength result or equivalence to the rollout-enabled teacher.**

The source comparison finished all 260 scheduled provider calls and the
provider process exited before the final readout. Of 416 requested arm-position
responses, 415 were accepted. One compact1 call timed out at 90 seconds with
unknown usage; its 30,000-token reservation and missing decision are retained.
No replacement call was made. Quality scoring completed all 207 matched
positions with zero scoring failures or uncomputed positions.

## Population and cost

52 production-played source deals, 13 ranks, 26 fit and 26 validation deals.
The four fixed contested-decision ordinals are 0, 12, 24 and 36; these are
sampling positions, not a guarantee of coverage through each round's endgame.
Full information, same compact prompt, `gpt-5.6-luna`, medium effort, play-only
access, one provider invocation at a time, native Codex CLI 0.149.0.

| Measure | Compact1 | Batch4 |
|---|---:|---:|
| Provider calls | 208 | 52 |
| Accepted positions | 207 | 208 |
| Accepted by ordinal 0 / 12 / 24 / 36 | 51 / 52 / 52 / 52 | 52 / 52 / 52 / 52 |
| Reported tokens | 2,137,290 | 721,669 |
| Reported plus unknown-call reservation | 2,167,290 | 721,669 |
| Observed tokens / accepted decision | 10,325.1 | 3,469.6 |
| Sum of observed call wall, including refusal | 3,253.97 s | 1,951.96 s |
| p95 / maximum call wall | 36.71 / 90.01 s | 59.96 / 73.82 s |
| Failed calls | 1 | 0 |

Batch4 uses **2.98x fewer reported tokens per accepted decision** on these
observations, or 3.02x when the compact1 unknown-call reservation is included.
The missing call's actual cost is unknown; the reservation is accounting, not
a claim about billing. Accepted decisions per total observed call time improve
1.68x. Raw input/output tokens are not subscription-quota or dollar savings.
These are isolated-state calls with no growing game-long private plan, so do
not assume the same rates for full games.

The retained comparison root accounts for 2,888,959 reported/reserved tokens.
Its result clock is 5,102.10 seconds from the repaired root's creation; it
includes imported successful calls and excludes earlier setup/repair downtime,
so it is not the complete end-to-end original-launch wall. Earlier failed
attempts and their accounting remain separate; none is erased by this result.

## Decision-quality result

Score the actions actually chosen by each arm and production on the same
known source state, then finish with the frozen named continuation. Average
positions within each deal and bootstrap the 52 deals, keeping correlated
positions together. This is a continuation-dependent action diagnostic, not
optimal regret, an independent world sample, or observed gameplay strength.

| Compact1 minus Batch4 | Mean signed-level difference | 95% deal-bootstrap interval |
|---|---:|---:|
| Primary: smart-all continuation | −0.01923 | [−0.06731, +0.02885] |
| Sensitivity: heuristic-all | +0.00481 | [−0.07692, +0.09135] |

Neither contrast establishes an advantage, and the nominal sign reverses
between continuations. There is no predeclared equivalence margin, so this
does **not** prove that batching preserves strength. Fit contributes 104
matched positions; validation contributes 103. The one missing position is
validation ordinal 0, not a missing stage.

Under the primary continuation, Batch4 minus the recorded production action
is −0.05288 [−0.13462, +0.01923]; Compact1 minus production is −0.07212
[−0.14904, −0.00481]. These are action scores under the fixed continuation,
not margins from actually playing MC. In particular, the historical PT-Luna
whole-game win cannot be attributed to this new play-only compact interface.

## Evidence and next step

Private source panel:
`~/.shengji-runs/luna-quality-panel-20260906.sl6QAC`, manifest SHA
`6c7f553a670bbc91a2f23a14f27ee0aa287a9e27017b6f16cf8c4d35eff0dcb3`.
Accepted/rejected requests, model responses and decisions are all retained in
`~/.shengji-runs/luna-fresh-quality-20260906.gPzshv`, result SHA
`070516ac0f03f44d0f2fb6b19db71c397b23b3b204a008abd2df6e16d16346e2`.
The final quality manifest is
`~/.shengji-runs/luna-quality-final-scoring-20260906.7IfSxK/manifest.json`, SHA
`a5b197bafcea5ad67d040bbaabe0d0fb5518e6356d8e8de140701f574fc9a0ee`.
Executing comparison/analyzer source: `6d71503ffafab70d245843c199f4f72f7f4017e8`.

A dependency-wrapper PATH error earlier triggered a two-second readout of
only 155 matched positions while collection was live. Its output is explicitly
marked `CUTOFF-NOT-FINAL.md` in `luna-quality-scoring-20260906.SVsBjW`; the
premature bus completion claim was corrected. The final scorer reused those
155 unchanged position shards, checked against the final call set, and scored
the remaining 52. No provider call, live source or comparison setting changed.
Do not cite the earlier 155-position snapshot as the completed result.

Prepared follow-up source directly compares Batch4 with Compact1 in mirrored
full games, retaining completed and partial trajectories and avoiding duplicate
provider calls on recovery. At the prior 63.3 provider decisions/game and
today's isolated-state means, a 104-game comparison extrapolates to roughly
**45.4M tokens and 23 hours** before plan growth, partly filled batches and
operational overhead. This is not a launch budget or an assertion of adequate
statistical power. One timeout in 208 compact calls can compound across a
whole pair: at that point estimate and independent errors, compact calls alone
would leave only about 74% of pairs complete. The estimate is very uncertain
and omits batch-correlated failures. Resolve affordability and recovery before
scaling; do not promise 52 completed pairs from per-request success alone.

Also retain a separate bridge to the historical rollout-enabled teacher. The
historical PT-Luna0 contract at `2394140b` used **high** reasoning with a
stateful, full-round observe/rollout/play session. Today's compact calls use
medium reasoning and play-only packets. Simply enabling current transport
`policy_mode="free"` would test rollout capability, not recreate the entire
historical teacher. Keep prompt, effort, memory and tool differences explicit
when sizing that bridge; do not attribute their combined gap solely to batching.
The
current result supports continued efficiency investigation, not automatic
scaling of a proven stronger teacher. No production change or data/model
promotion follows from this diagnostic.
