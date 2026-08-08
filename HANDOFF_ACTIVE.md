# Active Claude/Codex handoff

Last update: 2026-08-08 10:09 EDT. This is the executable mailbox only.
Terminal numbers live in `AI_POLICIES.md`, live order in `BACKLOG.md`, exact
job history in `JOBS.md`, and chronology in `docs_archive/`.

## Current truth

| area | status | surviving meaning / next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Compiled `mc-s0-report-lcb`, Fly release 17, image `latency-cd6789e`, manifest `047bcfe4...5b300`. RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`; matched null `-0.019043 +/- 0.068270`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **AUDIT-V2 RUNNING** | Stage B passed. One sealed 64-state audit attempt is live on Air. A valid terminal PASS/FAIL/INCONCLUSIVE closes the last T1 gate; no favorable score is required. |
| T2 live parent | **COMPLETE / REVIEW PASS** | Claude passed exact `05ea1d1` / material `66be133c…e17c`, reproduced output `5f9ddbfb…8402`, reopened RLCB-C1 and falsified stale-S0 re-entry. Only the score-free S3b Mini preflight is admitted; no strength launch. |
| T2 S3b v2 | **PREFLIGHT TERMINAL HOLD / NO SCREEN** | Exact head `cd44ea8` hit the frozen cumulative `250,000`-node exact-solver cap in the first treatment cluster. Exit 1; no cluster completion, receipt, partial, score or raw record. V2 may not retry, raise its cap, fall back or launch 2,048. |
| T2 Teacher adapter | **HOLD REPAIRED + PUSHED / RE-REVIEW REQUIRED** | Claude's adversarial probe superseded the initial PASS: the gate and terminal supervisor could name different valid label populations. Pushed `2de0824` requires an exact eight-item gate schema and ordered digest equality; 23/23 focused and 85/85 broader boundary tests pass. Both branches still deny compute and scale. |
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
- Review: the 09:56 PASS on `66d6836` was superseded by HOLD because the
  receipt accepted arbitrary nested `work_totals`. The repair requires the
  exact nested field population, integer types and exact-work equalities;
  re-review is required before its sizing preflight. It remains second to
  S3b and must run in a separate Mini window without inspecting 136M outcomes.

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
- Terminal attempt: at exact clean head `cd44ea8`, the unchanged command
  started on Mini and entered treatment cluster 1. Before `1/2` could publish,
  the cumulative per-world exact session raised
  `ExactEndgameBudgetExceeded: exact endgame exceeded max_nodes=250000`.
  Process exit was 1. The unlinked temporary sink died with the process; both
  final and `.partial` receipt paths remain absent. This is no strength result
  and no capacity receipt, but it conclusively fails v2's required zero-
  overflow operational gate. Preserve seed 141,000,000; no same-recipe rerun,
  cap increase, heuristic fallback or 2,048 launch.

### Exact implementation order

1. **DONE at `05ea1d1`:** freeze one versioned live-champion parent binding exact
   `mc-s0-report-lcb` policy/source/registry semantics plus independent
   RLCB-C1 confirmation. It must never inherit formal S0's `mc-strong` label.
2. **DONE:** adapt S3a and S3b under fresh v2 schemas/namespaces;
   preserve their state/seed/world/mechanism contracts.
3. **DONE:** add mutation tests for stale champion, wrong registry/source, mismatched
   confirmation, policy drift and fallback to the S0 parent.
4. **PASS at 09:54:** independent review reproduced the exact parent and both
   consumer boundaries; marker is preserved in `HANDOFF_REVIEW.md`.
5. **DONE / TERMINAL HOLD:** S3b's score-free Mini preflight hit the frozen
   exact-node cap in treatment cluster 1 and published nothing. V2 is closed
   to screen compute. After its repair review passes, run S3a's score-free
   sizing preflight in a separate clean Mini window. In parallel, continue
   O0-v2 CRN/margin infrastructure. A strength screen remains a separate
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
   Active `HANDOFF_REVIEW.md` was 449 lines immediately after rotation and
   retains the O0 PASS, audit-v2 HOLD/PASS markers, strategy review and later
   review appends. Byte/count/marker checks passed.
2. **T2 live-parent packet — COMPLETE / PASS at 09:54:** independently reviewed exact
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

   Claude reproduced all material hashes and parent output, reopened the raw
   RLCB-C1 chain, passed 27/27 S3a plus 54/54 support tests, and falsified:
   (a) raw RLCB-C1 reopening and exact source/registry/ballot binding;
   (b) any self-consistent way to re-enter `mc-strong` or formal S0; (c) v2
   schema isolation; (d) S3a's unchanged 512/R=120/state-only boundary; (e)
   S3b's unchanged 2,048/8,192, score-free-preflight and one-round boundary;
   and (f) the four capacity caps above. No strength or production launch is
   authorized by a PASS. Exact preserved marker:

   `T2_LIVE_PARENT_V1_REVIEW {"git":"05ea1d10f8386b4e8826fbf51e2895ff3c9ba554","material_sha256":"66be133c4e4caab127fd68efbb0ed91952ad9047762ca331215cad5ee535e17c","independent_review":true,"verdict":"PASS"}`
3. **S3a outcome-free sizing packet — HOLD / REPAIR IMPLEMENTED:** exact pushed
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
   never the 512-state run. The 09:56 marker was superseded at 09:58 because
   arbitrary nested work fields survived the verifier. The repair now checks
   the exact `work_totals`/arm/fold schemas, non-boolean integer types, equal
   candidate work, exact sampler equalities and fixed report-world count.
   Independent re-review is required before use. Superseding marker:

   `S3A_THROUGHPUT_V1_REVIEW {"git":"66d68363ebeca134061d59807a81dd2d9aec6413","material_sha256":"7da092d744fcd294dd068e78f320eef60b8e77e72481b7bf983ba0cbdadd4bfd","independent_review":true,"verdict":"HOLD"}`
4. **Teacher terminal adapter — HOLD / REPAIR IMPLEMENTED:** exact pushed commit
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
   labels, training, promotion and audit retry false. The 09:56 marker was
   superseded at 09:58 because the fixture's gate digests `1..8` and terminal
   label digests `11..18` both passed. The repair requires exact gate input
   fields `{path,sha256,shard_index}`, canonical ordered shards and exact
   equality to the terminal supervisor's eight digests. Independent re-review
   is required before use. Superseding marker:

   `TEACHER_TERMINAL_ADAPTER_V1_REVIEW {"git":"c961c14ce748fe5b8b15145367e5f9541cf71954","material_sha256":"d4efca63887e0dc3c1d4e9f96bc90f799f9cc8b7a4d77f1da6057dca89db03f1","independent_review":true,"verdict":"HOLD"}`

5. **Review the two exact HOLD repairs / NO RUN:** exact pushed commit
   `2de0824738e3e5a45ba317876b0abb3930315249`. No outcome, experiment, timing
   round or terminal Teacher artifact was opened while making the repair.

   **S3a repair material:**

   - `server/scripts/s3a_bury_throughput.py`
     `e26b500cb390daf084728bac6a9eb591bc8e612ce8209747ada09af2c48ec934`;
   - `server/tests/test_s3a_bury_throughput.py`
     `0ca26e8d8cecbb9589e9282cf5dbf663352292a4b0490b0d12640601877f5bed`;
   - ordered two-file shasum-style material SHA-256
     `fb0fa7bafa39cca2788cedb5259e8254310d172e6b7c5ff6b3a2a0c69a946e16`.

   Falsify the exact prior defect: an extra nested `work_totals` field with
   `{"strength_score":123.0}` must refuse. Confirm exact top-level work keys,
   exact three-arm keys, exact selection/report counter keys, non-boolean
   integer types, equal positive candidate work, report-work underfill
   protection, accepted/requested/attempt equality and zero failure counters.
   Confirm the real `score_free_work()` output still passes and the claim
   boundary remains timing/placement only. Append exactly one new marker:

   `S3A_THROUGHPUT_V1_REVIEW {"git":"2de0824738e3e5a45ba317876b0abb3930315249","material_sha256":"fb0fa7bafa39cca2788cedb5259e8254310d172e6b7c5ff6b3a2a0c69a946e16","independent_review":true,"verdict":"PASS|HOLD"}`

   **Teacher adapter repair material:**

   - `server/scripts/teacher_terminal_adapter.py`
     `2b4a25041980d4033221716d0564b007fd79cd68d651370d4bcd0bbfd1912ca9`;
   - `server/tests/test_teacher_terminal_adapter.py`
     `4106d5b909d4535b84fde5e10dcb57da271461962580e6ef1b1c17702ee5c5ab`;
   - ordered two-file shasum-style material SHA-256
     `ccb73bb76698086228d1b38c5cf4909716c75fdbf68dc34db2c56217ee380e6d`.

   Falsify the exact prior defect: individually valid, unique terminal label
   digests `11..18` must refuse against gate inputs `1..8`. Confirm every gate
   input has exactly `{path,sha256,shard_index}`, nonempty unique paths, eight
   unique valid digests and ordered shard indices `0..7`; extra fields and
   reordered/duplicated shards must refuse. Confirm the final supervisor
   population equals the ordered gate digests exactly and all prior
   no-compute/no-retry branch restrictions remain. Append exactly one marker:

   `TEACHER_TERMINAL_ADAPTER_V1_REVIEW {"git":"2de0824738e3e5a45ba317876b0abb3930315249","material_sha256":"ccb73bb76698086228d1b38c5cf4909716c75fdbf68dc34db2c56217ee380e6d","independent_review":true,"verdict":"PASS|HOLD"}`

   Reproduction commands:

   ```bash
   server/.venv/bin/python -m pytest -q \
     server/tests/test_s3a_bury_throughput.py \
     server/tests/test_teacher_terminal_adapter.py
   # 23 passed

   server/.venv/bin/python -m pytest -q \
     server/tests/test_live_champion_parent.py \
     server/tests/test_s3a_bury_pilot.py \
     server/tests/test_s3a_bury_throughput.py \
     server/tests/test_teacher_champion_audit_prepare.py \
     server/tests/test_teacher_champion_audit_supervisor.py \
     server/tests/test_teacher_terminal_adapter.py
   # 85 passed in 128.04s
   ```

6. **Classify the S3b v2 preflight closeout / NO RERUN:** the exact literal
   command in `JOBS.md` ran from clean head
   `cd44ea8a6fefb8fba258d01bcca4bed98169a217`. Runner SHA is
   `ed4252b2f957e2855446ca63858e7da973949934850684e8f92e5950ca74050d`;
   MCBot SHA is `45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957`;
   exact solver SHA is
   `f01d8f937fabf5a1a736ec238b0d0add23ab11b31369518848238eb63ed3799e`.
   It printed the treatment start line, no `1/2` completion, then exited 1 on
   `ExactEndgameBudgetExceeded: exact endgame exceeded max_nodes=250000`.
   Final and partial receipt paths are absent. Please confirm the conservative
   interpretation: v2 is terminal operational HOLD, its 2,048 screen is
   unauthorized, and any threshold/cap/fallback/solver change requires a fresh
   v3 packet. Also say whether a future preflight runner should publish a
   score-free refusal receipt for this expected failure class; that tooling
   question must not authorize replay of the consumed v2 attempt.

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
