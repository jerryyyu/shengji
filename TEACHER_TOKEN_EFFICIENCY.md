# Teacher data per token — opened-DEV investigation

Scope: improve useful PT-Luna decisions per token, then propose Luna/Sol data
collection. This is a bounded diagnostic, not a new scientific collection,
policy promotion, or repeat of the historical teacher-strength screen.
Implementation and measurements: [PR #245](https://github.com/jerryyyu/shengji/pull/245).
This transport investigation is separate from the parked prompt-rubric
experiment in [#216](https://github.com/jerryyyu/shengji/issues/216); it does not
restart that screen.

Outcome: the matched four-round comparison completed in both arms. Batch4
delivered **2.70x completed rounds per reported token** and **2.08x completed
rounds per wall time**. Quality remains inconclusive on the small continuation
panel. Keep the adapter opt-in and bridge to the historical rollout-enabled
teacher before collecting at scale.

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

Of the static-prefix bytes, **1,661,785 repeat already-seen prefix variants**;
the two distinct variants total only 1,630 bytes. Their shared leading prefix
is 319 bytes (650,760 duplicate common-prefix bytes across the 2,041 calls).
This measures identifiable repetition, not the total repeated model input:
the hidden harness request and growing game history are separate. The
reported uncached input count is 20,751,468 tokens. Cached input is contained
in total input, as in the [OpenAI usage documentation](https://developers.openai.com/api/docs/guides/prompt-caching);
never add it to the total again or equate duplicate prompt bytes with tokens.

The four preceding attempts contain 2,281 accepted responses, 12 recorded
refusals and **24,568,052 observed tokens**. Eleven refusal records lack usable
token telemetry. Their lane ledger charged/reserved 24,749,862; the difference
must not be presented as measured model usage. Failed-call cost is not zero.
Of the observed total, 24,556,654 tokens came from accepted calls and 11,398
from the one refusal with telemetry (10,342 input, 1,056 output, of which
953 reasoning). The other eleven failures have unknown actual cost, not zero
cost. This distinguishes wasted-run tokens from the cost of the failing call
itself; accepted decisions from those runs still exist and may be reusable
under their original provenance.

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

The panel's provider-reported decomposition (16 accepted decisions per arm):

| arm | input (includes cached) | cached subset | output (includes reasoning) | reasoning subset | total |
|---|---:|---:|---:|---:|---:|
| Baseline | 159,873 | 0 | 7,776 | 6,090 | 167,649 |
| Compact1 | 155,066 | 27,648 | 9,389 | 8,498 | 164,455 |
| Batch2 | 83,900 | 27,648 | 5,340 | 4,627 | 89,240 |
| Batch4 | 48,318 | 20,736 | 5,925 | 5,268 | 54,243 |

Almost all the raw-token reduction is input amortization. The experiment
does not identify how much repeated input came from the Codex wrapper versus
the user packet. Cache reuse may affect latency or billing, but removing
cached tokens from the raw total would mix two different cost measures.

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

## Full-round comparison — both arms complete

Batch4 artifact:
`/Users/jerryyu/.shengji-runs/teacher-token-rounds-batch4-20260905.ZvnVUS/`.
The process exited successfully with four complete trajectories, **298
accepted decisions in 85 calls**, no failed calls and no missing usage.
Elapsed wall was **1,751.24 seconds (29.19 minutes)**. The four games needed
65, 69, 79 and 85 model decisions; all ended normally.
The four roots cover rank/suit pairs 2/D, 5/C, 9/H and K/S. They do not
cover no-trump; that remains required coverage in a future broad collection,
not a capability demonstrated by this four-game check.

| quantity | unchanged baseline | batch4 |
|---|---:|---:|
| Complete rounds | 4 | 4 |
| Accepted decisions | 286 | 298 |
| Provider calls | 286 | 85 |
| Failed / unknown-usage calls | 0 / 0 | 0 / 0 |
| Wall minutes | 60.58 | 29.19 |
| Input tokens, including cached input | 2,930,450 | 1,060,240 |
| Cached input (subset of input) | 0 | 470,016 |
| Output tokens, including reasoning | 146,316 | 80,799 |
| Reasoning tokens (subset of output) | 116,287 | 69,403 |
| Non-reasoning output | 30,029 | 11,396 |
| Total input + output | 3,076,766 | 1,141,039 |
| Accepted decisions / million total tokens | 92.95 | 261.17 |
| Completed rounds / million total tokens | 1.300 | 3.506 |
| Total tokens / accepted decision | 10,757.92 | 3,828.99 |
| Serial decisions / provider minute | 4.72 | 10.22 |

Batch4 delivered **2.81x decisions per raw token**, **2.70x complete rounds
per raw token**, and **2.08x complete rounds per elapsed wall time**. It used
62.9% fewer reported tokens for four rounds. These are matched-root costs, not
matched trajectories: the policies took different paths and made 286 versus
298 contested decisions. Both per-round and per-decision measures matter.
Zero observed failures in this small pilot is not a zero-failure guarantee.

The end-of-run tail matters. There were 65 four-slot calls (260 decisions,
896,138 tokens), four three-slot calls (12 decisions, 54,832 tokens), ten
two-slot calls (20 decisions, 125,092 tokens), and six one-slot calls (six
decisions, 64,977 tokens). The whole-run cost per decision was 11.1% higher
than the four-slot portion. Late-game positions also differ from early ones,
so this is not a causal estimate of the gain from a continuously filled queue.

Skipping single-choice ballots is **already implemented** by
`LunaSelfPlayGame._advance_forced`. All 298 recorded model decisions have at
least two ballot candidates. The trajectories contain another 50 single-ballot
engine actions without a model call (348 engine actions total). Do not count
forced-move skipping as another prospective speedup; the measured batching
gain is on top of that existing behavior. These are ballot-relative choices,
not a claim of exhaustive legal move coverage.

The matched baseline artifact is
`/Users/jerryyu/.shengji-runs/teacher-token-rounds-baseline-20260905.OvzEYs/`.
It exited successfully after **3,635.01 seconds (60.58 minutes)**, with four
terminal records and trajectories; the games needed 56, 74, 86 and 70 model
decisions. Both arms stayed within their previously stated bounds. The initial
32/52-minute forecasts were estimates; actual elapsed times were 29/61 minutes.
Its config independently matches batch4's four root hashes, runtime, producing
source, model and effort. Only the named arm and its previously stated budget
differ. It started only after batch4 completed. Do not substitute the older
32-game average for this matched result or infer a strength gain from
self-play outcomes; the two arms can take different paths through each game.

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

The snapshot panel, continuation check and both full-round arms are complete.
Snapshot mode reopens saved
calls without dispatch. Full-round mode preserves completed trajectories and
partial states, but deliberately does not resume partial games. The batch
wrapper is not yet wired to the existing journaled resume path; that is needed
before scale-up, not a missing capability of the underlying driver. Sol support
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
is changed by this experiment. The completed pilot supports the next bounded
quality comparison, not scaled collection or a teacher-strength claim.

## Smallest next step after the pilot

Keep the merged batch adapter opt-in. Do not build a new runner or replace the
default collector on the strength of this diagnostic.

1. **Bridge cost to teacher quality before scaling.** On a fresh, outcome-blind
   panel of eight deals and four stages per deal, compare batch4 with the
   unchanged play-only baseline and the historically rollout-enabled Luna
   teacher on identical positions and the same legal ballot. The first
   contrast measures batching; the second measures whether cheap play-only
   labels preserve enough of the stronger teacher's advantage to be useful.
   Use actual engine continuation outcomes, include all failures, and report
   game-clustered uncertainty and token cost. This is 32 positions, not 32
   independent games; a noisy answer remains inconclusive. Set a separate
   bounded call/token/wall budget from retained rollout-enabled call costs
   before executing. Do not build a larger collector before this quality
   question justifies one.
2. **Make collected work reusable before a larger collection.** Wire the batch
   wrapper to the existing `TurnDriver` / `FileTurnJournal` resume path,
   restoring committed engine
   events, team memories and the settled call ledger. Do not implement a
   second game-recovery framework. Reopen a completed call without dispatch;
   an unresolved provider call remains cost-unknown and is never silently
   retried. Test an interruption between response storage and engine commit.
   This is the missing boundary before collecting substantially more games,
   not a reason to replay the current pilot.
3. **Keep batches full from independent ready games.** A small queue can form
   batches of up to four distinct deals, draining to smaller batches at the
   end. No future turns, mirrors, or multiple decisions from one deal in a
   shared request. Keep per-game/team memory explicit. More concurrent
   provider processes are a separate measured change; these results used one.

Sol then uses this same packet/consumer contract through an explicitly pinned
Sol adapter, not an unrecorded model substitution in the Luna-only launcher.
Start with a two-position compatibility/cost check, then select the bounded
overlap panel and full-round count from that measured cost. Hold prompt, ballot
and tool access fixed when comparing model quality; vary rollout access in a
separately labeled comparison. No Sol calls or scaled collection are launched
by this investigation.

The eventual dataset needs the source model/effort, prompt and tool-policy
version, root deal and split, team/mirror, decision index, legal actions,
chosen action, actual continuation policy, and observed terminal outcome
where available. Store private reasoning separately; do not make it a runtime
input or a numeric value target. Targeted Sol examples need their selection
reason/probability; final validation must come from fresh disjoint deals, not
from the disagreement-selected fit set or these opened pilot roots.
