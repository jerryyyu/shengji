# Teacher data per token — opened-DEV investigation

Scope: improve useful PT-Luna decisions per token, then propose Luna/Sol data
collection. This is a bounded diagnostic, not a new scientific collection,
policy promotion, or repeat of the historical teacher-strength screen.
Tracking: [#216](https://github.com/jerryyyu/shengji/issues/216).

## Current state — September 6

The [fresh 52-deal diagnostic](server/runs/luna_fresh_quality_result_20260906.md)
is complete: 208 sampled positions, 208 Batch4 and 207 Compact1 accepted
labels. Batch4 used about 2.98x fewer reported tokens per accepted decision;
the fixed-continuation quality difference is inconclusive, not equivalence.
Keep the 26 fit deals (104 positions with both labels) separate from the 26
validation deals. These are action labels on MC-generated states, not new
complete Luna games or value targets. Failures and both arms remain retained.

The [direct paired-gameplay source](server/runs/luna_quality_gameplay_design_20260906.md)
is merged in #270, but its forecast of roughly 45.4M tokens/23 hours is not
a launch budget. A separate [historical-teacher bridge](server/runs/luna_historical_bridge_20260906.md)
replays the original rollout-enabled teacher's saved choices: 52 role games,
26 independent deals, 170 selected positions. This avoids paying to regenerate
that reference; it does not make the old games fresh validation data. The
new compact responses and common-continuation comparison remain to be run.

The sections below retain the earlier four-deal pilot and its original commands
for provenance. Their "next"/"pending" wording is historical, not today's queue.

## Retained-run profile

The successful `pt-luna-rpc-isolated-b0b1bd95-r1` dataset contains 32 complete
games and 2,041 accepted provider responses. Its private journals reproduce:

| quantity | measured count |
|---|---:|
| Input tokens, including cached input | 20,772,204 |
| Cached input (subset of input) | 20,736 |
| Output tokens, including reasoning | 1,207,421 |
| Reasoning tokens (subset of output) | 992,063 |
| Non-reasoning output | 215,358 |
| Total input + output | 21,979,625 |

That is 94.5% input, a 0.10% input-cache hit fraction, approximately 10,769
reported tokens/accepted decision, and 1.456 completed games/million reported
tokens. These are raw usage counts, not API prices or subscription-quota costs.

The retained user prompts total 8,248,621 UTF-8 bytes: 6,540,304 packet bytes,
1,663,415 static-prefix bytes, 42,861 marker bytes and 2,041 trailing-newline
bytes. State-history fields account for 2,844,796 bytes; schema/hash fields
for 522,496 bytes. Field subtotals include JSON keys but exclude surrounding
commas/braces, so do not add overlapping field families. Prompt bytes are not
token counts. These records do not expose the entire rendered Codex system
request; the much larger provider input count cannot be attributed exactly
to the retained prompt alone.

The four preceding attempts contain 2,281 accepted responses, 12 recorded
refusals and **24,568,052 observed tokens**. Eleven refusal records lack usable
token telemetry. Their lane ledger charged/reserved 24,749,862; the difference
must not be presented as measured model usage. Failed-call cost is not zero.

Reproduce with `server/scripts/profile_luna_tokens.py PRIVATE_ROOT ...`.
Private roots remain under `/Users/jerryyu/.shengji-runs/`; never commit raw
hands, prompts, strategy notes or provider traces.

## Small first comparison

First panel: 16 retained positions from four distinct deals, at contested
decision indices 0/12/24/36. Selection uses hashed folder order and position
availability only, never outcomes. These are already-opened diagnostic games,
not a fresh validation set. Compare:

1. Unchanged baseline, one decision per invocation.
2. Compact packet plus stable response schema, one decision per invocation.
3. The same compact format, two independent-game decisions per invocation.
4. The same compact format, four independent-game decisions per invocation.

Keep the exact `gpt-5.6-luna` / medium, pinned Codex 0.149.0 runtime,
play-only policy, legal ballot/order and full engine-state contents fixed.
Compaction removes redundant audit metadata, not cards, history or team plans.
Baseline versus compact1 measures the packaging change; compact1 versus
batch2/4 isolates batching. Rotate arm order by game stage. Initial provider
concurrency is one in every arm: this measures invocation amortization, not a
claim about maximum parallel throughput.

**Bound: 44 calls, 1M reported/reserved tokens, 20 minutes, 90 seconds/call.**
Admission reserves `18,000 + 12,000 * batch_size` tokens before each call;
observed usage settles that reservation. This is a conservative admission
budget, not a provider-enforced billing ceiling. Unknown usage keeps the
reservation and stops the pilot. A refusal stops new calls; completed data is
retained. No retry, expanded population or automatic scaled collection.

Every batch contains at most one decision from each underlying deal; mirrors
and future turns of that deal cannot share a call. The host maps unique slots
back to full packet and team-memory identities and validates the entire batch
before consuming any response. Batch usage is counted once. Per-decision
allocated usage is explicitly attribution, not separately measured billing.
This enforces host-side routing and memory ownership; a shared model context
is not a hard semantic-isolation boundary. The model can still confuse slots,
which is a quality risk to measure. This adapter is full-information only,
not an equal-information collector for mutually hidden opponents.

Quality check: compare chosen actions on the same positions under frozen
`heuristic-all` and `smart-all` full continuations. Report disagreement and
paired signed-level differences, clustered by the four games. These are
continuation-sensitive proxies, not optimal-action truth or a strength test.
This small sample can expose obvious damage, not certify non-inferiority.

After this panel, the full-round check is four fresh baseline rounds
and four rounds with batch4. This is needed to measure completed
rounds/million tokens, tail batches, per-team memory, and failures. Do not
substitute snapshot throughput for complete-round throughput. The full-round
pilot is the next bounded stage: **batch4 at most 1.5M reported/reserved tokens
and 45 minutes; baseline at most 3.5M and 75 minutes**, one provider call at a
time. Same four fresh roots in each arm, all other mechanics fixed. A 90s
per-call bound and the pilot's absolute deadline both apply. Expected time
from the panel and retained mean decision count is about 32 minutes batch4
and 52 minutes baseline, before tail-batch effects. These bounds admit only
this eight-game comparison, not a scaled dataset. Completed games and all
call/state artifacts survive failure; no failed call is automatically retried.

## First measured result — 2026-09-05

Artifact: `/Users/jerryyu/.shengji-runs/teacher-token-panel-20260905.R3AL8V/`.
The 44-call panel completed in **657.6s / 475,587 tokens**. All 64 decision
responses were accepted; zero failures or unknown-cost calls.

| arm | tokens / accepted decision | raw-token reduction | serial decisions/min | baseline action agreement |
|---|---:|---:|---:|---:|
| Baseline | 10,478 | — | 4.96 | 16/16 |
| Compact1 | 10,278 | 1.9% | 4.38 | 12/16 |
| Batch2 | 5,578 | 46.8% | 7.84 | 12/16 |
| Batch4 | 3,390 | 67.6% | 7.90 | 12/16 |

Batching is the measured lever; metadata compaction alone is not. Batch4
provides **3.09x accepted decisions per raw token** and **1.59x serial
throughput**, not 3x throughput. Cache hits were baseline 0, compact1 27,648,
batch2 27,648, batch4 20,736 input tokens. Raw-token gains above count cached
input too; subscription quota savings are not inferred from them.

Under the two fixed continuation proxies, mean signed-level differences from
baseline were compact1 `+0.0625`, batch2 `+0.09375`, batch4 `0.0`.
Exploratory four-game bootstrap intervals for batch2 and batch4 were
`[-0.125,+0.3125]` and `[-0.1875,+0.1875]`. Baseline itself scored `-0.15625`
relative to candidate zero on this tiny proxy panel. This is **not evidence
that the play-only collector beats production**, nor that batching is
non-inferior. It just supports testing batch4's complete-round efficiency
without an obvious average quality collapse on this small panel.

The opt-in adapter reuses the existing zero-tool Codex runner and TurnDriver;
no collector defaults changed. Focused plus existing transport tests: 62
passed on the invocation's installed venv. An earlier run of the existing
transport suite with the stale root venv failed four subprocess-import tests
because that venv lacks `shengji.luna`; using the retained runner venv resolved
all four without source changes. Its watchdog bytes match the current source.

## Reproduction and current boundary

From an installed checkout's `server/` directory:

```sh
uv run --frozen python -B -m pytest tests/test_luna_transport.py tests/test_luna_token_batch.py tests/test_luna_token_pilot.py tests/test_profile_luna_tokens.py -q
uv run --frozen python -B scripts/profile_luna_tokens.py PRIVATE_ROOT
uv run --frozen python -B scripts/luna_token_pilot.py snapshots --private-root PRIVATE_ROOT --out NEW_PRIVATE_OUTPUT --codex-binary PINNED_CODEX_BINARY --arms baseline compact1 batch2 batch4 --tokens 1000000 --wall-seconds 1200 --call-seconds 90
uv run --frozen python -B scripts/analyze_luna_token_pilot.py PANEL_OUTPUT
```

The scripts resolve an installed `shengji` package, including in the contained
watchdog subprocess; a parent-only `PYTHONPATH` does not repair an incompatible
installation. Use the existing pinned Codex 0.149.0 binary, not a newer PATH
binary. The actual successful invocation used the retained runner venv and
an absolute checkout `PYTHONPATH`; the private `config.json` records the runtime
and producing source hashes. Do not rerun completed calls merely to change
environment or administrative metadata.

`rounds` uses the same four fixed diagnostic roots in each invocation and
accepts one arm. The bounded commands are:

```sh
uv run --frozen python -B scripts/luna_token_pilot.py rounds --out NEW_BATCH4_OUTPUT --codex-binary PINNED_CODEX_BINARY --arms batch4 --tokens 1500000 --wall-seconds 2700 --call-seconds 90
uv run --frozen python -B scripts/luna_token_pilot.py rounds --out NEW_BASELINE_OUTPUT --codex-binary PINNED_CODEX_BINARY --arms baseline --tokens 3500000 --wall-seconds 4500 --call-seconds 90
```

At this source publication the snapshot panel and continuation check are
complete; the eight-game comparison is pending. Snapshot mode reopens saved
calls without dispatch. Full-round mode preserves completed trajectories and
partial states, but deliberately does not resume partial games. A production
collector would need that continuation boundary before scale-up. Sol support
is a proposed follow-up, not implemented by this Luna-only adapter.

## Collection recipe to evaluate, not launch yet

- Use Luna for broad early/mid/late-game coverage. Preserve losses and failed
  attempts; keep the deal as the split/uncertainty unit. Balance rank/suit,
  including no-trump, from observed coverage rather than choosing winning
  games. Do not equate many positions with many independent deals.
- Use Sol for an outcome-blind mixture of random coverage and targeted
  disagreements/low-confidence positions, plus some full Sol rounds. Record
  selection probabilities and source tags; targeted labels are not a natural
  population benchmark. Compare Sol and Luna on some identical states.
- Teacher actions can train a prior over legal actions. Value labels must
  name the actual continuation policy: a Sol action followed by MC is not a
  Sol-continuation target. If mixing state sources for one value estimand,
  relabel them under the same frozen continuation. Do not turn prose or
  confidence into ground-truth values.
- Allocate fresh deals to fit, model selection and final validation before
  collection. Keep mirrors and all descendants together. Respect cumulative
  model exposure across pretraining/fine-tuning; previously fitted Luna games
  cannot become a clean validation set by relabeling their directory.
- Historical PT-Sol/Luna strength evidence came from a different,
  rollout-enabled planner. Faster play-only collection does not inherit that
  strength. Restore/test bounded rollout access as a separate quality/cost
  experiment after this transport comparison, not hidden inside compaction.

No production policy, existing collector default, live job or retained dataset
is changed by this experiment. Results and the next decision belong here once
the bounded pilot finishes.
