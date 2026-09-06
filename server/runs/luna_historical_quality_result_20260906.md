# Historical Luna bridge — September 6, 2026

The comparison completed with **217 calls, zero failures and 2,424,353
reported tokens**. Batch4 used **2.77× fewer tokens per matched decision**
than compact1. Their decision-quality difference remains inconclusive.
The older rollout-enabled teacher's recorded choices score better under the
primary continuation, but that gap is not resolved under the sensitivity
continuation. Cheap collection is not yet evidence of equally good teaching.

## What was compared

170 matched saved positions from 26 previously opened independent deals
(52 role games). These are **not 170 independent games or fresh validation**.
The historical action is retained as a label, not shown to the new teachers.

- Historical: recorded high-reasoning Luna with session history and rollout
  tools.
- Compact1 and batch4: medium-reasoning Luna, the same full-information
  snapshot, compact prompt and candidate ballot, empty initial plan and no
  tools. Only independent requests per invocation differ between these two.

The historical contrast combines changes in reasoning, memory, prompt and
tool access. It does not identify the causal effect of tools alone. This
readout scores the chosen actions under fixed engine continuations, not by
playing new head-to-head games or measuring optimal-action regret.

## Measured cost

| Arm | Calls | Accepted decisions | Reported tokens | Provider wall |
| --- | ---: | ---: | ---: | ---: |
| Compact1 | 170 | 170 | 1,780,539 | 2,842.265 s |
| Batch4 | 47 | 170 | 643,814 | 1,618.603 s |

Both arms have zero failed calls and zero unknown-usage calls. Combined
collection wall was 4,462.076 s (74m22s). Batch4 yields 2.77× more accepted
decisions per reported token and 1.76× more per provider second. These are
reported-token counts, not billing, subscription-quota percentages or an
old-versus-new teacher cost comparison: historical token usage is unknown.

## Decision quality

Units are differences in signed-level terminal payoff under the named
continuation. Positions and role games are averaged within their deal before
10,000 deal-level bootstrap replicates (seed 20260906). Positive means the
first named teacher's chosen action scores better.

| Contrast | Primary: smart-all, mean [95% CI] | Sensitivity: heuristic-all, mean [95% CI] |
| --- | --- | --- |
| Historical − compact1 | +0.1101 [+0.0369, +0.1886] | +0.0176 [−0.0272, +0.0609] |
| Historical − batch4 | +0.1550 [+0.0833, +0.2303] | +0.0288 [−0.0208, +0.0849] |
| Compact1 − batch4 | +0.0449 [−0.0192, +0.1122] | +0.0112 [−0.0417, +0.0705] |

All 170 positions were scored; zero refused calls, error positions or
deadline-uncomputed positions. Four CPU workers used the compiled engine;
the result records `engine_fast_active`, `engine_fast_have_fast` and
`engine_fast_use_fast` as true. No second full reconstruction was run.

Failure to resolve compact1 versus batch4 is **not equivalence**. Likewise,
the primary historical advantage is useful diagnostic evidence, not a robust
whole-game strength margin, a new MC comparison or grounds to pool these
teacher contracts without labels.

## Evidence and next action

Source: PR #275 at `da753e0da2a3b204b30db786acd3d54d862aee2b`.
Private artifacts remain on Mini; only this aggregate readout belongs in Git:

- Panel: `/Users/jerryyu/.shengji-runs/luna-historical-panel-20260906.UEJmWS`;
  manifest SHA256 `a10d10801bdb882b4e7a12c28b1ffd1f3d3885bdb81fa2a9aa4096a593dd935a`.
- Calls: `/Users/jerryyu/.shengji-runs/luna-historical-calls-20260906.jGc5Z2`;
  collection-result file SHA256 `c27b5a2911e76d9de645e13fd06e99598bc50de9c6c406503a38db91bc6b4ea1`.
- Readout: `/Users/jerryyu/.shengji-runs/luna-historical-readout-20260906.DiQPBg`;
  embedded result SHA256 `5662f3be89582d7539c232f3a57406a082d67d95c0267a4ed6423923c749698b`.

Retain all matched choices and original provenance, not only positions where
one teacher wins. These opened historical roots must not become fresh audit
data. Any use for fitting needs explicit teacher/interface and continuation
labels and separation from held-out descendants of the same deals.

The next gameplay experiment is PR #280's named eight-deal / 16-mirror-game
tranche, compact1 versus batch4 with the same interface. It measures actual
full-game cost, completion and paired outcomes; it does not settle the
historical-teacher gap by itself. Price the remaining 44 panel deals from
actual game cost and deal-level variance. Do not promote the cheap teacher
or automatically scale the full roster from this snapshot result.
