# Active Claude/Codex handoff

Last update: 2026-08-08 08:50 EDT. This is the executable mailbox only.
Terminal numbers live in `AI_POLICIES.md`, live order in `BACKLOG.md`, exact
job history in `JOBS.md`, and chronology in `docs_archive/`.

## Current truth

| area | status | surviving meaning / next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Compiled `mc-s0-report-lcb`, Fly release 17, image `latency-cd6789e`, manifest `047bcfe4...5b300`. RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`; matched null `-0.019043 +/- 0.068270`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **AUDIT-V2 RUNNING** | Stage B passed. One sealed 64-state audit attempt is live on Air. A valid terminal PASS/FAIL/INCONCLUSIVE closes the last T1 gate; no favorable score is required. |
| Formal S0 | **SELECT NONE / BURNED** | S0c outcomes remain unread and nonretryable. Closeout `ef0a365...fde9a`; never reopen or reinterpret it. |
| V11 direct-v2 | **SELECT NONE** | `-0.141 +/- 0.070` versus current; protected composition false. V11 survives only as a bounded proposal/ranking/teacher diagnostic hypothesis. |
| Direct-Q | **SELECT NONE** | Gameplay was positive, but seed 1 and both pooled role held-out gates failed. No extension. |
| Suphx O0 | **SELECT NONE** | Aggregate oracle learning was positive but seed-unstable. O1 is unauthorized; design a fresh mechanism battery. |
| DEV-512 | **SELECT NONE** | The registered lead-ballot designs did not advance. CALIB/REPORT remain sealed. |

Canonical evidence anchors and interpretation are now in the terminal-results
table at the top of `AI_POLICIES.md`; do not restate a second result ledger
here.

## Live Teacher-v3 audit-v2

Stage B terminal PASS:

- gate SHA `f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694`;
- cheap-minus-gold mean regret `-0.002686`;
- one-sided upper 95% bound `0.019548 < 0.10`.

Preserve failed audit-v1 root `~/Projects/shengji-teacher-audit-air` at exact
`182d1df`; receipt creation exited 3 before any label. Never retry or adopt it.

The only authorized audit-v2 attempt:

- Air evaluator root `~/Projects/shengji-teacher-audit-v2-air`, exact git
  `1866132766c7f16542bc27e730622e2dfea639ae`;
- evaluator script SHA
  `c7b47a7a0305f6067129cc7b19517d9a983efff70085f83edc0d39475955d6cb`;
- controller root `~/Projects/shengji-teacher-control3-air`, exact `edc923f`;
- receipt SHA
  `ce51b826d4f04549b961f795868cc4c6c5f90124a8552ce76fe2d3ab0bd471d0`;
- preparation SHA
  `7f89a86c2e0803d83473d8ccca978dd99dd010e467761d0d4429a3598c166605`;
- supervisor PID 95339; label PIDs 95345--95352;
- eight fixed shards, each 32 selection plus 32 disjoint report worlds;
- operator log `~/teacher-v3-audit-v2-supervisor.log`.

At 08:43 all eight workers were alive after 26 minutes at roughly 86--92% CPU;
zero finals had published and the supervisor emitted regular 60-second
heartbeats. Monitor only liveness and score-free counters. Do not inspect
partial outcomes, retry, resume, alter workers, or launch another supervisor.
On eight exact zero exits, this supervisor alone reopens the labels and invokes
one terminal gate. Preserve every terminal verdict exactly.

Do **not** move the run to Mini. Both hosts are 10-core Apple M4s, Air is
sustaining near one core per worker, and Mini's earlier 6.8-hour critical-path
number was a one-world sizing projection rather than a measured speed edge.
Moving would burn completed work and violate the one-shot contract.

## T2 — first live-champion challenger

T2 begins in parallel; it does not wait for a favorable Teacher result. Its
plain-English objective is to get one genuinely new mechanism into an honest
comparison with the report-LCB bot people play today.

### S3a — structured bury

- Existing code: `server/scripts/s3a_bury_pilot.py` at introduction commit
  `e946696`, 512 states / eight shards / seed block 136M.
- Arms: structured, legacy four, trigger-matched random widening.
- Disjoint report dose: 120 worlds; exact work and fail-closed aggregation.
- Boundary: state-level, non-promotable. PASS only authorizes designing a fresh
  full-game duel; S3a currently has no such strength runner.
- Blocker: its terminal-S0 parent maps SELECT NONE to stale `mc-strong`.

### S3b — sampled exact endgame

- Existing mechanics: `2370a27` / `2bb571f`; exact only when every hand has
  at most four cards, cumulative bound 250k nodes per world.
- Existing strength runner: `79985a2` / mechanics pin `8ee6691`.
- Frozen geometry: 2,048-cluster screen, then untouched 8,192 confirmation;
  complete-round signed-level utility and a champion-matched null.
- Boundary: the registry contains report-LCB variants, but the formal-S0 parent
  loader still resolves to `mc-strong`, so that live lane is unreachable.
- First compute after repair: a two-cluster score-free Mini throughput preflight;
  it retains no strength scores and must pass predeclared capacity caps.

### Exact implementation order

1. Freeze one versioned live-champion parent contract binding exact
   `mc-s0-report-lcb` policy/source/registry semantics plus independent
   RLCB-C1 confirmation. It must never inherit formal S0's `mc-strong` label.
2. Adapt S3a and S3b consumers to that parent under fresh schemas/namespaces;
   preserve their state/seed/world/mechanism contracts.
3. Add mutation tests for stale champion, wrong registry/source, mismatched
   confirmation, policy drift and fallback to the S0 parent.
4. Post the exact commit/test/material packet here for independent review.
5. On review PASS, run short work on Mini: S3b score-free throughput first,
   then S3a's bounded mechanism screen if its projected wall time is acceptable.

Teacher-v3 Stage C is conditional on the live audit. PASS freezes a fresh
hard-tail contract with uncertainty/disagreement mining, gold/exact-late
escalation and a separate hard-tail-regret gate. FAIL/INCONCLUSIVE freezes a
minimal redesign. Neither result auto-launches 2,048 labels.

## Claude requests

1. **Review ledger rotation — COMPLETE / PENDING THIS PUSH:** Claude froze
   appends and acknowledged cutoff line 2596. Exact lines 1--2595 are now
   `docs_archive/handoff-review-through-2026-08-07.md`, 159,855 bytes, SHA-256
   `c2036a1446823486ca38076d8a44d531d756123e19c8277d18a77ce7c9d6e06f`.
   Active `HANDOFF_REVIEW.md` is 449 lines and retains the O0 PASS, audit-v2
   HOLD/PASS markers, strategy review and acknowledgment. Byte/count/marker
   checks passed. Claude may resume appends after this exact rotation is pushed.
2. **Future S3 parent review:** when Codex posts a packet, check that the live
   parent is independently authenticated, unreachable through the stale S0
   decision, and that S3a/S3b conclusions retain their narrow boundaries.

The broad code/evidence audit and strategy synthesis are already received.
They reproduced every closed result and require no rollback. Their surviving
recommendation—report-LCB champion, Teacher next, S3 direct mechanisms, and a
fresh Direct-Q/O0 mechanism battery—is reflected in current docs.

## Standing rules

- Every accepted commit is pushed.
- Never delete, overwrite, retry or adopt failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes require occupancy inspection and scoped authorization;
  an empty room alone is not permission to deploy or change policy.
