# PT-Luna batching: direct paired gameplay

Source-only follow-up to #261/#262, using the existing Luna game, compact
provider transport, and turn validator. No provider call or token grant is
implied by this document. Jerry approved the 6M-token/three-hour ceiling for
the earlier snapshot diagnostic on September 6; it is not a budget estimate
for this larger gameplay comparison, which still needs sizing.

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

There are **52 independent deals and 104 correlated mirrored games**, not
104 independent observations. This is a fixed comparison roster, not an
assertion that 52 deals can prove equivalence. In particular, failure to find
a difference is not evidence that batching preserves strength.

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

Before any launch, record the explicit token/wall ceiling and forecast the
whole 104-game workload from observed raw-token usage and wall cost. Report
uncertainty and the minimum detectable paired difference using deal-level
variance from the available matched data. The prior four-deal pilot is not
adequate evidence to claim precision. If the proposed budget cannot cover
the roster, resolve that **before** calls; do not silently shrink the roster
or promise a powered answer from an affordable subset.

## Existing path, recovery and data

Provider outputs pass through the existing compact parser and `TurnDriver`;
the scheduler never directly turns model prose into an engine action. Every
call retains its input packets, provider evidence and observed or reserved
usage before actions are committed. A malformed batch must not apply its
first valid slot while discarding another slot.

Each completed game immediately publishes its trajectory, terminal receipt
and explicit arm/split/continuation metadata. Losing and tied games are kept
alongside wins. Partial states and call evidence remain available on failure.
Model prose is kept separate from engine transitions and is never a value
label. Terminal outcomes describe this particular pair of continuation
policies, not optimal play or MC continuation values.

Recovery replays already accepted recorded responses through the same turn
validator, without another provider call. The original deadline, token
accounting, roots and source remain bound. An unsettled reservation or saved
refusal stops admission rather than being silently retried or charged as
free. Completed artifacts are never overwritten. No independent multi-hour
reconstruction stage is added: replay exists for recovery, while final
aggregation reads the small completed-game receipts.

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

Before execution: finish source and real-engine/recovery witnesses, one
consolidated source review, and an explicit affordable launch budget. After
this batching comparison: the separately named rollout-enabled teacher
bridge and any larger confirmation. No production deployment or automatic
data/model promotion follows from either source approval or a DEV result.

## Cost evidence, not a launch estimate

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
compound over all turns and both mirrors. The current full-game source stops
on a failed turn and preserves evidence, but must not be launched at scale
if that measured reliability predicts mostly incomplete pairs. Resolve the
call allowance and independent-game failure handling in this packet before
its one consolidated launch review, not after burning a gameplay budget.
