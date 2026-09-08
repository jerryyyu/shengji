# PT-Luna batching: direct paired gameplay

Source-only follow-up to #261/#262, using the existing Luna game, compact
provider transport, and turn validator. The September 6 tranche amendment
below is the next proposed execution: complete mirrored games, not another
snapshot or capacity test. It does not turn the earlier snapshot budgets into
an unlimited gameplay budget. No provider call is launched by this document.

## What this measures

The earlier cost pilots compared self-play runs and the fresh diagnostic
compares isolated decisions. Neither establishes that batched Luna remains
as strong over an entire game, when its own earlier choices and private plan
affect later decisions.

Here agent A is compact **batch4** Luna and agent B is compact **batch1**
Luna. They play each other on the same prepared roots, twice with teams
swapped. The model, medium reasoning, full-information observation, candidate
ballot, compact prompt, no-tool access and team-memory rules remain the same.
Only independent requests per provider invocation differ. Direct head-to-head
utility, not agreement with either teacher or the model's own value, is the
gameplay endpoint.

This makes the primary contrast direct head-to-head instead of the provisional
two separately MC-opposed arms described in #261. It saves opponent games and
isolates the batching comparison. It cannot inherit or reproduce either
teacher's historical margin over MC; that remains a separate bridge.
Fewer engine games do not imply half the LLM calls: both sides here are Luna,
whereas only one side would be Luna in each MC-opposed game. Size tokens from
actual provider decisions, not the number of game files.

This does **not** compare either arm with production MC or establish parity
with the historically stronger rollout-enabled teacher. A separate
rollout-enabled-versus-play-only comparison is still required by the larger
teacher-quality goal. Do not relabel this no-tool collector as that teacher,
or relabel MC actions as Luna actions to reuse a Luna-only artifact schema.

## Population and schedule

Use the existing, hash-bound 52-root panel: 13 trump ranks, two bankers and
two replicates, with no source-outcome filtering. The same root is used for
both team assignments. Replicate 0 stays fit-only and replicate 1 stays
validation-only; all descendants inherit their root's split. Source capture
status cannot be used to select easy or winning roots when a valid bound root
is available.

The larger comparison roster has **52 independent deals and 104 correlated
mirrored games**, not 104 independent observations. The explicitly named first
tranche selects eight roots before gameplay. Completing its 16 games must not
be reported as completing the larger roster. Neither eight nor 52 deals is
automatically sufficient to prove equivalence; failure to find a difference
is not evidence that batching preserves strength.

The scheduler operates on fixed waves of **eight** independent coordinates.
Since two arms share these games, using just four live games would tend to
offer batch4 only two eligible movers, losing much of the intended batching.
The maximum request stays four; a partly filled request remains explicit in
the evidence, including at wave tails. It batches only current
acting states from different coordinates; it cannot include future states or
both mirrors of one deal in a provider request. Each game retains its own
turn driver and separate private team plans. Team assignment swaps between
mirrors, while the provider arm stays bound to agent identity. One provider
process is active at a time, as in the measured batching pilot. Scheduling
order is fixed in the run inputs, not adjusted in response to wins or losses.

Before each tranche, record its exact roster and token/wall ceiling. Report
uncertainty using complete deals, not decisions as independent observations.
The old snapshot variance is not a full-game power estimate. Use actual
paired-game variance and cost to price the remaining experiment; do not require
a conclusive early strength result before collecting more games. An unaffordable
roster is resolved before calls, not silently shrunk after seeing outcomes.

## Existing path, recovery and data

### September 6 amendment: start with actual complete paired games

The full-game collector is already merged in #270. The only new execution
surface is an explicit coordinate selector after verifying the original full
panel. The selected roster is bound before calls. No provider, scheduler,
model, prompt, tool, retry or decision-rule rewrite is part of this amendment.

First tranche: these eight `(rank, banker, replicate)` coordinates, selected
for coverage before observing gameplay outcomes:

```json
[["2",0,0],["3",1,1],["4",0,0],["5",1,1],["6",0,0],["7",1,1],["8",0,0],["9",1,1]]
```

This gives eight independent deals, 16 full games with swapped teams, four
fit and four validation roots, and one full eight-coordinate scheduling wave.
Both teams are genuine play-only Luna throughout every game. The first tranche
does not cover all ranks or guarantee no-trump coverage. Actual suits/NT and
completed pairs are reported. Subsequent tranches take the unselected source
coordinates in their verified original order, without replacement or choosing
roots based on wins. Source snapshot comparisons are already opened; this is
a DEV gameplay experiment, not fresh confirmatory evidence.

Planning forecast: about **7.0M raw tokens and 3.5 hours** for the 16 games,
scaling the completed fresh diagnostic's per-decision rates and the prior
63.3 decisions/game. This is not a full-game measurement. The first-tranche
admission limits are **9M reported/reserved tokens, 18,000 seconds total,
120 seconds per provider call**, one provider at a time on Mini. The longer
call allowance applies equally to both arms; the earlier diagnostic had one
90-second compact timeout. It is not a promise that refusals disappear or
that provider billing is bounded exactly by reservations.

This work does not use the MPS training device. Use the pinned known-good
Codex binary and a virtualenv installed in the executing checkout. Wait for
the current historical comparison's provider process to finish; its readout
uses a separate short CPU task. No additional provider-based rehearsal or
capacity census precedes these actual games. One consolidated review covers
the selector, its real-consumer tests and this exact first-tranche plan.

The committed selector is `runs/luna_quality_gameplay_tranche1_20260906.json`.
The existing private source panel is
`/Users/jerryyu/.shengji-runs/luna-quality-panel-20260906.sl6QAC`, manifest SHA256
`6c7f553a670bbc91a2f23a14f27ee0aa287a9e27017b6f16cf8c4d35eff0dcb3`.
From the reviewed checkout's `server/`, after its own `uv sync --frozen` and
native extension build, the single launch command is:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
.venv/bin/python -u -B -m scripts.luna_quality_games \
  --panel-root /Users/jerryyu/.shengji-runs/luna-quality-panel-20260906.sl6QAC \
  --coordinates-file runs/luna_quality_gameplay_tranche1_20260906.json \
  --out NEW_PRIVATE_GAMEPLAY_ROOT \
  --codex-binary /Users/jerryyu/.local/share/codex-0.149.0/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex \
  --tokens 9000000 --wall-seconds 18000 --call-seconds 120
```

`NEW_PRIVATE_GAMEPLAY_ROOT` is a fresh private directory recorded at launch;
it never aliases the current historical run. The CLI executable SHA256 is
`f4a74117b8142cda581c95ff753abf4508b5636d89682c1ed77e4a9249af8963`.
Record the actual source/runtime identity and command there. This is DEV, not
an additional immutable-freeze or capacity-review step.

Each tranche has its own output root/configuration. Same-roster recovery replays
saved accepted responses without new provider calls and retains the original
budget/deadline. A larger or different roster is **not** a resume: it gets a new
run root over previously unused coordinates. Combine completed game receipts
and provenance across tranches, never transplant/relabel call files. A partial
tranche stays partial; no failed deal is replaced and no timeout discards the
other completed games. Terminal aggregation remains a small-receipt readout,
not a second gameplay replay.

The first tranche's deliverables are full trajectories, actual whole-game
token/wall cost and completion rate, and a descriptive paired strength estimate
with its uncertainty. It need not establish equivalence or a winner to be useful.
Price the remaining 44 deals from that evidence and use the observed deal-level
variance to state the precision we can afford. Do not repeatedly open nominal
95% intervals until one is positive and call that confirmation. All completed
tranches, ties, losses, failures and partial trajectories remain in the ledger;
any later confirmatory claim needs a separate fixed analysis plan.

This amendment is an explicit staged launch, not a claim that the larger
teacher-quality objective is finished after eight deals. Jerry has requested
and authorized bounded Luna experimentation/token spending; a review verifies
this plan and source, it does not manufacture user authority or authorize an
automatic 45.4M-token continuation.

Provider outputs pass through the existing compact parser and `TurnDriver`;
the scheduler never directly turns model prose into an engine action. Every
call retains its input packets, provider evidence and observed or reserved
usage before actions are committed. A malformed batch must not apply its
first valid slot while discarding another slot.

Each completed game immediately publishes its trajectory, terminal receipt
and explicit arm/split/continuation metadata. Losing and tied games are kept
alongside wins. Partial states and call evidence remain available on failure.
Provider refusals and collector-wide stops also publish the accepted partial
trajectory for each unfinished affected game with its root, split, arm,
continuation and stop reason. These have distinct partial filenames, no
terminal outcome, and cannot be mistaken for completed-game receipts. Later
recovery may publish a completed trajectory without overwriting the partial.
Model prose is kept separate from engine transitions and is never a value
label. Terminal outcomes describe this particular pair of continuation
policies, not optimal play or MC continuation values.

Recovery replays already accepted recorded responses through the same turn
validator, without another provider call. The original deadline, token
accounting, roots and source remain bound. An unsettled reservation or saved
provider refusal is retained and charged conservatively, never retried or
charged as free. Quarantine only the affected deal(s), including any unfinished
mirror, and continue the other fixed deals. A failed batch quarantines every
deal in that request. Do not spend additional calls completing a mirror that
cannot form a complete pair, substitute replacement deals, or change the
original budget. Completed games stay intact even if their other mirror fails.
Malformed accepted responses or source/packet drift still stop the collector;
they are not ordinary provider refusals. Completed artifacts are never
overwritten. No independent multi-hour
reconstruction stage is added: replay exists for recovery, while final
aggregation reads the small completed-game receipts.

Before committing a fresh response, the collector binds its chosen action,
planning note, confidence and usage to the persisted call row, plus provider
identity hashes when evidence is present. The entire batch passes this check
before its first move is applied. Cached responses are reconstructed from the
saved provider evidence. Thus live execution and recovery cannot silently
consume different returned and recorded actions.

Per-call state snapshots contain only the one-to-four games changed by that
call, not all 104 game states. Recovery uses the bound roots and saved calls;
these small state deltas are inspection aids, not a second checkpoint system.
Use a virtualenv installed from the exact reviewed checkout (`uv sync
--frozen` in `server`): the provider watchdog deliberately clears PYTHONPATH,
so borrowing another checkout's editable environment can fail before dispatch.

## Readout and remaining work

`python -B -m scripts.luna_quality_games_analyze --run PRIVATE_RUN` reads the
small configuration, metadata and terminal receipts; it does not invoke
providers, scan all private response traces or replay the games. It derives
batch4's utility from team 0's terminal utility with the mirror sign applied,
then averages both mirrors into one deal observation. Missing mirrors never
become zero scores. A one-deal partial readout has no confidence interval.

Report A-minus-B signed levels and win/tie/loss rates with deal-clustered
uncertainty; keep both mirrors together. Also report completion and missing
coordinates, actual rank/suit/no-trump coverage, per-arm calls and raw/cached/
output tokens, elapsed wall, and failure/unknown-cost counts. Per-slot token
allocation inside one batch is an accounting split, not measured per-position
usage. Incomplete mirrored pairs cannot enter a complete-pair strength claim.
Report partial evidence as partial, including possible completion bias.

The base collector and its engine/recovery witnesses are merged in #270.
Before the first tranche: one consolidated selector/source + named-run review,
using the budget above. The separate historical-teacher bridge is already
running under #275; it is not a requirement that its difference be statistically
conclusive before actual gameplay can proceed. No production deployment or
automatic data/model promotion follows from source approval or a DEV result.

## Cost evidence, not a launch estimate

The fresh 207-matched-position diagnostic is now complete; see
[its readout](luna_fresh_quality_result_20260906.md). It measures about 2.98x
reported-token efficiency with no clear fixed-continuation quality difference,
not full-game equivalence. Its means suggest roughly 45.4M tokens and 23 hours
for this roster before growing plans, partial batches and operational overhead.
The one observed compact timeout must also inform expected complete-pair yield;
it cannot be ignored by extrapolating successful requests only. No new run is
launched by this source packet.

The completed September 5 batch4 scale16 pilot used 3,825,314 reported tokens
for 1,013 decisions in 16 whole games and 6,665 seconds wall. Its 283 calls
had no failures, p95 49.37 seconds and maximum 70.77 seconds. The separate
four-deal snapshot pilot used 164,455 tokens for 16 compact1 decisions versus
54,243 for the same 16 batch4 decisions. Evidence roots under
`/Users/jerryyu/.shengji-runs/`:

- `teacher-token-scale16-20260905.CCpsso/result.json` and arm call files;
- `teacher-token-panel-20260905.R3AL8V/result.json` and arm call files.

Using those means, **only as a rough extrapolation**, 104 games at 63.3 moves
per game with half each arm would consume about 46M raw tokens. Compact1
whole-game cost has not been measured; its plan/context growth and batch4's
partly filled requests can change this substantially. The old no-tool pilot
does not size the historical rollout-enabled teacher. This is why the current
6M snapshot grant is not being stretched into a 104-game launch.

Use the current fresh comparison's call latency, failure/missingness pattern,
token cost and quality diagnostic before proposing the full-game budget. A
per-request success rate alone is not a complete-game success rate: failures
compound over all turns and both mirrors. The collector quarantines failed
deals so unrelated games can continue, but must not be launched at scale if
measured reliability predicts mostly incomplete pairs. Resolve the call
allowance and expected complete-pair count in this packet before its one
consolidated launch review, not after burning a gameplay budget. A completed
schedule containing refusals has a distinct status and is not a complete
104-game panel or evidence of equivalence.

## Validation for the tranche amendment

The focused gameplay, tranche and small-receipt readout suite passes **28 tests**
in pure Python and compiled-engine mode. The new CLI witness verifies the full
52-root source panel, selects the committed eight coordinates, runs all 16 real
engine games through a fake provider, and reaches the saved per-game receipts
and eight-pair readout. It checks four-slot batching, mirrored assignments,
split/roster provenance and explicit `complete-tranche` rather than full-panel
completion. This is wiring evidence, not teacher quality or provider throughput.

Invalid/duplicate/unknown selectors refuse before provider construction; a JSON
`null` cannot accidentally select the whole panel. Changing the actual bound
roster refuses in the existing `Pilot.configure` path. Removing a declared
complete tranche's terminal receipt fails the real readout. The existing
provider/refusal/partial-evidence recovery witnesses remain in the same suite.
