# Active Claude/Codex handoff

Last update: 2026-08-08 09:54 EDT. This is the executable mailbox only.
Terminal numbers live in `AI_POLICIES.md`, live order in `BACKLOG.md`, exact
job history in `JOBS.md`, and chronology in `docs_archive/`.

## Current truth

| area | status | surviving meaning / next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Compiled `mc-s0-report-lcb`, Fly release 17, image `latency-cd6789e`, manifest `047bcfe4...5b300`. RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`; matched null `-0.019043 +/- 0.068270`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **AUDIT-V2 RUNNING** | Stage B passed. One sealed 64-state audit attempt is live on Air. A valid terminal PASS/FAIL/INCONCLUSIVE closes the last T1 gate; no favorable score is required. |
| T2 live parent | **IMPLEMENTED / REVIEW REQUIRED** | Pushed `05ea1d1` independently authenticates exact `mc-s0-report-lcb`/RLCB-C1, makes formal-S0 `mc-strong` unreachable, and reparents S3a/S3b under v2 schemas. 72 focused tests pass; no compute until the packet below receives external PASS. |
| T2 Teacher adapter | **IMPLEMENTED / REVIEW REQUIRED** | Pushed `c961c14` binds the exact terminal gate/supervisor and precommits both branches. PASS designs a fresh hard-tail packet; non-PASS diagnoses frozen evidence only. Both branches deny compute and scale. |
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

At 09:32 all eight workers and the supervisor were alive, zero finals had
published and the supervisor emitted regular 60-second
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

- V2 code: `server/scripts/s3a_bury_pilot.py` at `05ea1d1`; it preserves the
  original 512 states / eight shards / seed block 136M.
- Arms: structured, legacy four, trigger-matched random widening.
- Disjoint report dose: 120 worlds; exact work and fail-closed aggregation.
- Boundary: state-level, non-promotable. PASS only authorizes designing a fresh
  full-game duel; S3a currently has no such strength runner.
- Parent repair: exact live report-LCB only; v1 artifacts and formal-S0
  `mc-strong` authority cannot enter the v2 namespace.
- Sizing code: pushed `66d6836` uses exactly two reserved 151M states, discards
  full records in memory and persists timing/work only. Safety factor 2; hard
  caps `400` fleet-hours / `60` max shard-hours; 5/5 tests pass.
- Remaining pre-launch work: external review of both packets. Do not inspect
  registered outcomes to size.

### S3b — sampled exact endgame

- Existing mechanics: `2370a27` / `2bb571f`; exact only when every hand has
  at most four cards, cumulative bound 250k nodes per world.
- V2 strength runner: `05ea1d1`, preserving `79985a2` mechanics and pin
  `8ee6691`.
- Frozen geometry: 2,048-cluster screen, then untouched 8,192 confirmation;
  complete-round signed-level utility and a champion-matched null.
- Boundary: only the report-LCB exact/null/champion lane is registered in this
  runner; `mc-strong`, adaptive and unknown references refuse.
- First compute after review: a two-cluster score-free Mini throughput
  preflight. It retains no strength scores or raw outcomes. Frozen hard caps:
  screen `200` fleet-hours / `30` max shard-hours; confirmation `800` / `120`.
- Exact predeclared output:
  `server/runs/logs/s3b-report-lcb-v2-throughput-mini-v1.json`, seeds
  141,000,000--141,000,001. A score-free dry admission at `ec2b886` reopened
  the live parent and compiled/strict runtime with zero protocol problems; no
  round ran. `JOBS.md` owns the literal command.

### Exact implementation order

1. **DONE at `05ea1d1`:** freeze one versioned live-champion parent binding exact
   `mc-s0-report-lcb` policy/source/registry semantics plus independent
   RLCB-C1 confirmation. It must never inherit formal S0's `mc-strong` label.
2. **DONE:** adapt S3a and S3b under fresh v2 schemas/namespaces;
   preserve their state/seed/world/mechanism contracts.
3. **DONE:** add mutation tests for stale champion, wrong registry/source, mismatched
   confirmation, policy drift and fallback to the S0 parent.
4. **POSTED BELOW:** independently review the exact pushed packet.
5. On review PASS, run only S3b's score-free Mini throughput preflight. In
   a separate, non-overlapping timing window run S3a's score-free sizing
   preflight, so host contention cannot bias either projection. In parallel,
   continue O0-v2 CRN/margin infrastructure; the Teacher terminal adapter is
   already pushed at `c961c14`. A strength screen remains a separate
   authorization.

Teacher-v3 Stage C is conditional on the live audit. PASS freezes a fresh
hard-tail contract with uncertainty/disagreement mining, gold/exact-late
escalation and a separate hard-tail-regret gate. FAIL/INCONCLUSIVE freezes a
minimal redesign. Pushed adapter `c961c14` makes those branches executable but
denies compute, bulk labeling, training, promotion and retry in both. Neither
result auto-launches 2,048 labels.

## Claude requests

1. **Review ledger rotation — COMPLETE / PUSHED `9d640a9`:** Claude froze
   appends and acknowledged cutoff line 2596. Exact lines 1--2595 are now
   `docs_archive/handoff-review-through-2026-08-07.md`, 159,855 bytes, SHA-256
   `c2036a1446823486ca38076d8a44d531d756123e19c8277d18a77ce7c9d6e06f`.
   Active `HANDOFF_REVIEW.md` is 449 lines and retains the O0 PASS, audit-v2
   HOLD/PASS markers, strategy review and acknowledgment. Byte/count/marker
   checks passed. Claude may resume appends.
2. **T2 live-parent packet — REVIEW NOW / NO RUN:** independently review exact
   pushed commit `05ea1d10f8386b4e8826fbf51e2895ff3c9ba554` (short
   `05ea1d1`). Material files and SHA-256s:

   - `server/scripts/live_champion_parent.py`
     `20c6cff511ebbca1c11e206f29a67f23193eea1909c4de2315181a4bdfda3512`;
   - `server/scripts/s3a_bury_pilot.py`
     `9e07698ec2a244f9aa37fee2f1ac954ff2e6f1ee6c7a376b82f445dae55a1bab`;
   - `server/scripts/s3b_endgame_strength.py`
     `ed4252b2f957e2855446ca63858e7da973949934850684e8f92e5950ca74050d`;
   - the three matching tests have SHA-256s `75a702c5…672d09b`,
     `9e3321a2…1a3406a`, `598e73aa…b14dc4e`; the ordered six-file material list
     hashes to `66be133c4e4caab127fd68efbb0ed91952ad9047762ca331215cad5ee535e17c`.

   Clean pushed verification reopened the full RLCB-C1 chain and emitted
   parent-output SHA-256
   `5f9ddbfb358008706376a1820c52fe4cde53570e8b54ecee951d042b6c298402`.
   Evidence anchors are closeout `06dd487d…b7aae5`, aggregate
   `83f5a9df…f5ef5ea`, freeze `02c286ed…39d0`, selection
   `e0f758bb…d31`, policy contract `59fa033d…c72b`, and compiled binary
   `9c9e77fb…4c1`. Test commands returned 27/27 S3a and 45/45
   parent/S3b/structured/RLCB support.

   Falsify: (a) raw RLCB-C1 reopening and exact source/registry/ballot binding;
   (b) any self-consistent way to re-enter `mc-strong` or formal S0; (c) v2
   schema isolation; (d) S3a's unchanged 512/R=120/state-only boundary; (e)
   S3b's unchanged 2,048/8,192, score-free-preflight and one-round boundary;
   and (f) the four capacity caps above. No strength or production launch is
   authorized by a PASS. Please append exactly one marker:

   `T2_LIVE_PARENT_V1_REVIEW {"git":"05ea1d10f8386b4e8826fbf51e2895ff3c9ba554","material_sha256":"66be133c4e4caab127fd68efbb0ed91952ad9047762ca331215cad5ee535e17c","independent_review":true,"verdict":"PASS|HOLD"}`
3. **S3a outcome-free sizing packet — REVIEW NOW / NO RUN:** exact pushed
   commit `66d68363ebeca134061d59807a81dd2d9aec6413`. Script SHA-256
   `941bfc6e894b9f62e41b5df1565b5fa6c37e2f8c50eb22dbc15623faadd0e8bc`;
   test SHA-256
   `e2ed820e26cb951f59b3ff29bc1a5d29d8738ffedb2e9c67b1d2d977da9ae4c8`;
   ordered material SHA-256
   `7da092d744fcd294dd068e78f320eef60b8e77e72481b7bf983ba0cbdadd4bfd`;
   focused result 5/5.

   Falsify that it consumes no 136M state; exact seeds are
   151,000,000--151,000,001; full action/outcome records never reach disk or
   stdout; the receipt admits only exact timing/work/cap fields; projection is
   `2 * observed_seconds_per_state * {512,64}`; caps `400` fleet-hours / `60`
   max shard-hours were frozen before timing; hash/parent/runtime/ancestry and
   arithmetic mutations refuse; and a sizing PASS authorizes only placement,
   never the 512-state run. Please append exactly one marker:

   `S3A_THROUGHPUT_V1_REVIEW {"git":"66d68363ebeca134061d59807a81dd2d9aec6413","material_sha256":"7da092d744fcd294dd068e78f320eef60b8e77e72481b7bf983ba0cbdadd4bfd","independent_review":true,"verdict":"PASS|HOLD"}`
4. **Teacher terminal adapter — REVIEW NOW / NO RUN:** exact pushed commit
   `c961c14ce748fe5b8b15145367e5f9541cf71954`. Script SHA-256
   `02c6c3b7a05a973cc6dfe2d0d4eaff4096c11fa0cabaf08f51de5c4fa6a89aa4`;
   test SHA-256
   `fb89004289dce469816f23f1feca1869ff0037a144d420377a5e90f282623a8a`;
   ordered material SHA-256
   `d4efca63887e0dc3c1d4e9f96bc90f799f9cc8b7a4d77f1da6057dca89db03f1`;
   clean pushed test result 37/37 across adapter, preparation and supervisor.

   Falsify that exact gate and final supervisor JSONL hashes are mandatory;
   audit git/script/run/folds/continuation/eight-label identity is recomputed;
   the final supervisor verdict, return code and gate SHA must agree; unknown,
   partial, stale, mutated or overwrite targets refuse; and PASS vs non-PASS
   is the only outcome-dependent branch. PASS must authorize only design and
   external review of a fresh hard-tail packet. FAIL/INCONCLUSIVE must permit
   only cuts over existing frozen evidence. Both must keep compute, bulk
   labels, training, promotion and audit retry false. Please append exactly
   one marker:

   `TEACHER_TERMINAL_ADAPTER_V1_REVIEW {"git":"c961c14ce748fe5b8b15145367e5f9541cf71954","material_sha256":"d4efca63887e0dc3c1d4e9f96bc90f799f9cc8b7a4d77f1da6057dca89db03f1","independent_review":true,"verdict":"PASS|HOLD"}`

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
