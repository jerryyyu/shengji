# Historical Luna bridge: replay old choices, compare current interfaces

Opened historical-distribution diagnostic, tracked in #216. No production
change, no fresh held-out claim, and no automatic provider launch.

## Question and retained population

The original PT-Luna0 teacher used high reasoning, a growing game session and
observe/rollout/play tools. Today's compact1/batch4 teacher uses medium
reasoning and independent play-only snapshots. Its token saving does not
establish parity with that historically stronger interface.

Replay the recorded historical choices under the exact archived engine and
seeded MC opponents. Compare every reconstructed pre-play observation with
the original record. No model call or old rollout-tool call is needed to
recover the already-recorded choice. Select the first eligible contested
decision at or after 0/6/12/18 completed tricks, deduplicate threshold crossings,
and retain missing stages. Selection never consults wins, regret or disagreement.

All 52 role games replayed to completion: **26 independent deals, 170 selected
positions, 38 missing stage slots, three no-trump deals**. The initial 180-second
bounded pass retained 40 roles; a continuation reused completed files and
finished the remaining roles, preserving the interrupted partial file too.
The current engine consumes all 170 snapshots, preserves the original ordered
ballots, and reproduces each archived selected immediate transition exactly.
This is mechanics compatibility, not new evidence of teacher strength.

Private persistent panel:
`~/.shengji-runs/luna-historical-panel-20260906.UEJmWS/`
with manifest file SHA
`a10d10801bdb882b4e7a12c28b1ffd1f3d3885bdb81fa2a9aa4096a593dd935a`.
Original public report SHA:
`fea40a5622efe2ce832483aebffbae8be25ca99bba11b60c8bfd0df666c27926`.
Archived source: `2394140bcdaebf72d81912a55ac18f5051848fe5`.
The original seed, hidden cards, prompts, choices and transcripts stay private.
The historical report has **no usable token total**; do not substitute the
later 32-game RPC run's 21,979,625 tokens.

## Producer, comparison, readout

1. `scripts/luna_historical_panel.py`: stdlib wrapper, lazily imports the named
   archived checkout, binds original report/evidence/seed, replays saved choices,
   publishes private per-role shards and preserves partial retries.
2. `scripts/luna_historical_compare.py`: consumes the panel with the current
   engine. Same current compact prompt/effort/tools for both queried arms, empty
   initial memory, unchanged historical ballot. Group by role/stage with at
   most one state from each independent deal in a request. Original choices
   are comparison labels, never fields of a provider's input packet.
3. `scripts/luna_historical_analyze.py`: score recorded historical, Compact1 and
   Batch4 choices using common `smart-all` primary and `heuristic-all` sensitivity
   continuations. Deduplicate identical choices; average matched positions within
   each underlying deal, keeping both roles together for uncertainty. Failures
   and missing positions remain explicit. Preserve independent completed score
   files on recovery; no second full replay is part of this readout.

Steps 1 and 2's zero-provider compatibility path have run on the actual data.
Provider comparison and its scientific readout are **not completed**. The
caller reuses the existing `luna_token_pilot.Pilot`: immutable calls, pending
reservations, unknown-cost charging, no failed-call redispatch, and an absolute
wall/token budget. No second provider harness or restored retired runner is added.
The analyzer can parallelize independent positions; this is a small bounded
diagnostic, not a new capacity campaign.

Focused current-checkout validation: **93 tests passed** across the exporter,
comparison, analyzer, existing Pilot, batch transport, quality comparison and
provider watchdog/transport tests with the compiled engine enabled. Tests use
fake provider responses, not paid calls. They exercise the real Pilot journal,
refusal reservation/reopen path, current-engine transitions, historical-action
score wiring, collection-terminal gating and no-recompute score recovery.
The complete retained 170-position panel also passed the compiled current
consumer's zero-provider preparation command.

## Call count and cost forecast

There are 170 Compact1 calls and 47 Batch4 calls (217 total), because grouping
preserves independent deals and leaves some short batches. The old reference
requires zero new calls. Today's fresh-panel averages project about **2.41M
raw tokens and 74 minutes** of sequential calls. This is not a measured cost:
historical states, response lengths, short batches and refusals may differ.
Unknown call usage is reserved, not charged as zero. The CLI requires explicit
token and wall limits to execute; default mode only describes the panel.

The proposed bounded Mini comparison is **3.5M reported/reserved tokens,
7,200 seconds total and 90 seconds per call**, one provider invocation at a
time. This leaves roughly 45% token and 63% wall headroom over the observed-rate
forecast; it is an admission/accounting bound, not a provider-enforced billing
ceiling. There is no automatic budget extension or replacement for a failed
call. Budget exhaustion publishes the collected prefix as truncated. Reopening
the same journal never redispatches completed or refused calls. It does not
authorize the separate 45.4M-token whole-game comparison.

After collection has published a terminal or explicitly truncated result,
score independent matched positions with four CPU workers, a 300-second soft
admission deadline, and single-threaded math libraries. Submitted finite
positions drain; completed score files survive an interruption. This small
CPU-only readout does not use MPS or compete for the training device. Report
collection truncation, missing/refused calls and scoring failures separately;
do not interpret an incomplete comparison as equivalent teachers.

From an installed current checkout's `server/`:

```sh
python -B -m scripts.luna_historical_compare --panel-root PRIVATE_PANEL
python -B -m scripts.luna_historical_compare --panel-root PRIVATE_PANEL --execute --out PRIVATE_CALLS --tokens 3500000 --wall-seconds 7200 --call-seconds 90 --codex-binary PINNED_CODEX_BINARY
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 SHENGJI_FAST=1 python -B -m scripts.luna_historical_analyze --panel-root PRIVATE_PANEL --calls-root PRIVATE_CALLS --out PRIVATE_SCORES --workers 4 --max-seconds 300
```

Keep provider-free preparation separate from an explicitly sized provider run.
The historical distribution is already opened and may overlap past model fit;
never assign it to the fresh panel's reserved validation partition. The
comparison estimates the combined teacher-interface gap, not a causal effect
of tools, effort or memory individually. Fixed-continuation action scores are
not optimal-action truth or observed paired gameplay strength. That last
question remains the separately prepared #270 gameplay experiment.
