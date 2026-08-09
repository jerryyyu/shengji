# Active Claude/Codex handoff

Last compacted: 2026-08-09 09:33 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, live compute in `JOBS.md`,
queue order in `BACKLOG.md`, and reviewed markers in `HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` versus `mc-strong`. Keep release 16 as runtime rollback and `mc-strong` as policy rollback. |
| T1 Teacher | **COMPLETE / STAGE-C DESIGN** | Gate `8a1532b7…91f8`, supervisor `02f4f8b…6f237`, and adapter `56ccefbd…c2442` verify. The only authority is design and external review of a hard-tail Stage-C packet—no labels, training or production. |
| T2 S3a structured bury | **2,048-CLUSTER SCREEN RUNNING / SEALED** | Exact `c599b42`, packet `de16247b…cdd4`, admission `567e8aa8…41c5e`, receipt `2c89bed3…cbb2c`; eight Mini shards × 256. Count-only monitoring, then one terminal verify. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The first frozen treatment cluster exceeded the 250k-node cap. Do not retry or relax v2. |
| T2 learner O0-v2 | **COMPLETE / SELECT NONE** | Gate `0dbd9aa8…f24e` independently replayed. O1 and production remain unauthorized. |
| External review | **NONE OPEN** | Do not ask Claude for a generic status review. Open a request only for one exact packet named below. |

The most recent count-only S3a heartbeat saw all eight workers live and
progressing at `8,9,8,8,8,9,8,8 / 256` clusters. Outcomes remain unread.

## Active milestone — T3 human-witness challenger flywheel

Plain-English objective: turn observed production weaknesses and human strategy
into one honest challenger of the bot people play, while preparing better
training data in parallel. T3 must make useful progress whether S3a wins or
selects none.

T3 exits only after all four boundaries below are satisfied:

1. **Resolve S3a without peeking.** Terminally verify the sealed 2,048-cluster
   screen. If it returns `AUTHORIZE_CONFIRM_PACKET_REVIEW`, freeze an
   8,192-cluster confirmation packet for external review; do not launch it
   before that review. If it returns `SELECT_NONE`, close this exact recipe—no
   tuning, retry or pooled inference.
2. **Make the point-banking observation testable.** Implement a rollout-only,
   team-aware mechanism that may choose a point-bearing winner when multiple
   legal winners exist. Preserve root action sourcing and the live policy.
   Require named human/synthetic witnesses, deterministic treatment/control
   replay, a trigger-matched null, exact work counters and a fresh state-level
   screen contract. The sign is not assumed positive.
3. **Freeze Teacher Stage C.** Build a reviewable design packet that samples
   uncertainty/disagreement and exact-late states plus the two human witness
   families below. Human examples are DEV diagnostics only and cannot enter
   CALIB/REPORT. Packet review precedes labels, compute and training.
4. **Refresh and counterfactually use human play.** The August 9 evidence-grade
   Fly-snapshot-only rebuild accepts 2,830 plays and 45 buries from 122 fully
   replayed rounds, counts seven incomplete rounds, and finds 25 legal
   off-ballot human plays. Twelve legacy local-only rooms are excluded.
   Freeze a player/deal-disjoint H0 pilot that uses human actions as proposals,
   not truth. Define the blinded HUMAN-C1 candidate-versus-champion protocol;
   its evaluation games can never train or select the candidate.

Active `/goal`:

> Complete T3 human-witness challenger readiness: preserve and terminally
> verify the sealed S3a full-game screen; conditionally freeze and externally
> review its confirmation packet or immutably close the recipe; refresh the
> production human-decision corpus under corrected replay/encoder provenance
> with explicit acceptance/rejection counters; implement and test a
> rollout-only, trigger-matched point-banking mechanism screen; freeze
> reviewable Teacher Stage-C and human-action counterfactual pilot contracts;
> and define a leakage-safe human-vs-bot evaluation ladder. Stop before any
> unreviewed strength compute, training, promotion, or production change.

## Human-observed strength hypotheses

### H1 — point-bearing kitty voids

Production is strongly point-shy, not structurally incapable of burying
points. The live heuristic's point multiplier is usually large, while existing
void/trump bonuses can occasionally outweigh it. S3a is materially broader:
it explicitly proposes complete one-/two-suit voids, records points and voids,
and evaluates them through rollouts. Its 512-state mechanism screen passed;
the live full-game screen is the first actual bot-strength test of this issue.

### H2 — point-banking continuation

The root follow ballot can contain point-card winners. The narrower bug is in
shared rollout continuation: when several legal winners exist, the heuristic
chooses the cheapest one, so it can under-price a low-trump lead that lets an
opponent win with a 5/10/K instead. This is not the old point-feeding issue and
is not yet implemented as a strength treatment. The proposed S4 experiment
changes continuation only and needs a team-aware trigger because banking a
point is not always strategically better.

### H3 — human actions escape heuristic support

The refreshed corpus contains 25/2,830 human plays outside the broad
exhaustive-follow analysis ballot and humans buried points in 22/45 observed
banker decisions.
That is direct evidence that site play explores actions the historical
self-play generator can omit or disfavor. It does not say those moves are
better. H0 must add each human action to the frozen candidate union and price
it on common worlds under production and alternate named continuations.

## Conditional Claude review packets

There is no blocker now. The next request is exactly one of:

- **S3a confirmation review**, only after a terminal screen PASS: inspect the
  frozen 8,192-cluster packet, live-parent/null identity, fresh seeds, capacity,
  one-shot controller and authority boundary.
- **S4 mechanism/preflight review**, if its code and packet are ready: inspect
  action semantics, witness non-vacuity, treatment isolation, trigger-matched
  null, counters and score-free capacity.
- **Teacher Stage-C design review**: inspect strata, split exclusion, label
  escalation, exact data contract and explicit no-compute/no-training flags.
- **Human H0 packet review**: inspect source/encoder hashes, pseudonymous
  player/deal splits, replay/rejection counters, action-union semantics,
  continuation comparison and HUMAN-C1 evaluation exclusion.

Append exact PASS/HOLD markers only to `HANDOFF_REVIEW.md`. A review PASS does
not silently authorize a run.

## Fleet and safety rules

- Mini owns the sealed S3a screen. Do not switch or dirty its detached
  `c599b42` worktree, inspect shard logs, read partial outcomes, retry or extend.
- Air is free but has no reviewed strength launch. Use it only for bounded
  implementation tests or an independently reviewed packet—not speculative
  evidence generation.
- Long reviewed compute prefers Mini; sub-hour bounded work may use Mini when
  it does not contend with a live exclusive job.
- Every strength run binds the exact champion, engine, sampler, ballot,
  continuation, utility, seeds, null, work and stop rule. Screens may select
  one design; fresh confirmation is required for a strength claim.
- Formal S0, V11 direct-v2, Direct-Q, O0/O0-v2, S3b-v2 and Teacher audit
  failures are closed. Diagnose them; never silently extend them.
