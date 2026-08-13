# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local ledgers
> are never review authority. Raw review markers belong at column 1 in the
> canonical review ledger and must occur exactly once.
>
> Full earlier history is preserved in `docs_archive/`. This file is only the
> current executable truth; the review ledger remains the evidence authority.

Last reconciled: 2026-08-13 07:29 EDT from canonical main `5bdb231`.

## Pair V3 capacity gate

The frozen Pair V3 capacity packet PASS at canonical commit `88866f25` was
authenticated and consumed exactly once on the performance Cloud. The
systemd-owned **score-free** preflight finished in 157.535 wall seconds and
182.430 CPU seconds, used 543.1 MB peak memory, and left no workers or partial
files. Its one result is `544499d1…a764` / internal `ca36d1af…a4fb`; scored
evaluation, REPORT access, strength claims, training, promotion and deployment
all remain closed.

Claude independently reproduced the result science in canonical commit
`8843be7`: 1.0499 projected fleet-hours against the 64-hour cap, 0.088 hours
on the worst lane against 4 hours, closed score-free schema and no retry.
Claude then reviewed final PR #84 head `f571146`, ran its read-only verifier
against the canonical artifacts and appended the generated raw PASS marker at
canonical commit `16af447`. The verifier binds the exact dependency bytes and
stable single-read artifact identities; script SHA is `5ca14e1f…646a1`, test
SHA is `d7959903…9f3b`, and 21 focused tests pass.

That marker opens **scored-packet design only**. PR #86 exact head `a43a17c`
now publishes the declarative scored-packet design after an independent
internal PASS, and exact-head external review has been requested. It only
builds and verifies the design; no packet has been frozen or run. Packet
freeze, packet execution, scored evaluation, REPORT access, retry, extension,
strength claims, training, production promotion and deployment all remain
explicitly closed pending separate exact-design and authority review.

## Live fleet

| host | current work | safe progress and next boundary |
|---|---|---|
| **Mini** | T4 mid/late Teacher whole-round screen, eight workers | All workers are live. The safe lower bound is 6,396/12,288 = 52.05%: treatment is complete, seven shards have reached matched-null 300/512 and one has reached 200/512. The deadline remains knife-edge; the slow tail projects to about 16:59 EDT, after which the champion arm must average no more than 26.7 seconds per cluster to beat the 20:46 child deadline. Monitor only. On terminal publication, Claude reviews the score-free supervisor final before any aggregation or outcome access. |
| **Air** | Broad Pair-aware whole-game screen, eight workers | The reviewed safe counter is 2,064/7,168 = 28.79%. The current pace remains on a substantive timeout trajectory; do not inspect shard outcomes or intervene. A terminal supervisor final, including timeout, needs score-free review before aggregation. Reviewed S6 preflight remains queued behind this run. |
| **Strength Cloud** | S4 360B point-banking sequential confirmation, 16 workers | All workers are healthy. The reviewed score-free look-one counter is 6,187/8,192 = 75.52%. The reviewed controller automatically stops or continues at look one. Inspect only reviewed score-free telemetry. |
| **Performance Cloud** | Pair V3 score-free preflight is complete; no live strength worker | Idle because authority remains design-only and PR #86 awaits external review. The completed preflight namespace is one-shot and must not be retried or altered. Performance exploration must not mutate frozen strength code or evidence. |
| **Production** | Release 18, `kitty-xray-b5a35ae`, champion `mc-s0-report-lcb` | No deploy, restart, room wipe or policy change without explicit user approval. |

## Current review queue

1. **Pair V3 scored-packet design / PR #86 `a43a17c`.** The declarative
   build-and-verify-only design passed independent internal audit and awaits
   exact-head external review. It grants no packet-freeze, run, result-access,
   retry, strength, training, promotion or deployment authority.
2. **Terminal closeout helper follow-up / PR #80 `e61975c`.** Claude prose
   PASSed parent `9c896e2` at canonical `3f7916d`. This direct child adds the
   requested aggregate pre-open binding, final-change TOCTOU and sealed-shard
   drift refusal fixtures and isolates the dependency-path test from
   `SHENGJI_FAST`; 22/22 tests pass both plain and fast, and CI is green.
   Exact-head delta review is pending, with no new verdict or execution
   authority.
3. **Performance stack, in dependency order.** PR #75 `90c5630` binds PR #71
   compatibility to the corrected 64-character native identity; PR #77
   `0381081` prepares accepted hidden worlds once; PR #81 `c6c7126` adds the
   native common-case winner path; PR #83 `69ff44e` adds the guarded native
   lead path. PR #83's ordinary three-seed exploratory A/B was positive on all
   pairs and 10.20% lower wall in aggregate with normalized semantics and work
   unchanged; an independent internal audit passed, but its raw evidence is
   owner-writable and is not authoritative strength evidence. The attempted
   resolve-trick successor is retired: its forced/no-search harness refused, so
   no timing claim was made. None of these PRs changes strength authority.
4. **Exploration/docs.** PR #78 `8ab5db2` is the opened-DEV bury/S6 diagnostic;
   83 tests and CI are green. PR #82 `a498bf5` is the score-free H0
   legality/geometry repair; 30 focused plus 64 adjacent tests and CI are
   green. Both superseding heads await review. Docs PR #64 is currently
   `c7782be`; request and review only that exact head after the technical
   blockers.
5. **Air timeout contingency / PR #85 `111314f`.** This repaired design-only
   successor closes strict hash/type, dynamic worker-seed overlap, exact
   ceiling-economics and 48-hour-cap gaps; 40 tests and CI are green. Its
   superseding exact head awaits re-review while the current Air run remains
   untouched, and it authorizes no replacement launch, retry or extension.
6. **Pair stack merge gap.** PR #55 exact head `24b421d` still needs review of
   its one artifact-preservation commit beyond the passed `5696144` boundary.
   If clean, merge readiness can cover #55 → #60 `7468828` → #61
   `22ddfa3` → #72 `373de84` in order. Do not mutate this stack during the
   active Pair scored-design lane.

Already reviewed: PRs #51, #52 and #54 passed for bounded bury/S6 exploration;
PR #69 passed for the incremental attacker-gated Pair-cap design; PR #80
`9c896e2` prose-PASSed at canonical `3f7916d` with the follow-up fixtures above;
PR #84 `f571146` passed at canonical `16af447` for scored-packet design only;
PR #50's S6 v2 packet passed for one score-free preflight and sleeps behind
Air. PR #73 remains conditional on the broad Pair terminal result and its
economics. S5 is closed: its old admission is spent, PR #76 is validation-only,
and no retry or diagnostic execution is authorized.

## Terminal sequences

For T4 or broad Pair:

1. The existing supervisor publishes a terminal score-free final.
2. Claude reviews that final without opening shard outcomes.
3. Only an explicit PASS may admit one aggregation.
4. Claude independently reproduces and terminally reviews the aggregate.
5. A positive screen can justify a fresh confirmation design; it never deploys.

For S4, follow the predeclared two-look controller exactly. Never pool old S4
outcomes post hoc, inspect a live tranche, or manually override its automatic
transition.

## Standing invariants

- Do not inspect live or sealed shard result files; process state and explicitly
  reviewed score-free heartbeats are the safe monitoring surface.
- Exploration may be fast and reusable. Deployment evidence remains sealed,
  powered, independently reviewed and one-shot.
- Same deals, role flips and policy randomness are shared across treatment,
  matched null and champion; the null must remain behavior-identical to the
  champion.
- Feature telemetry is dose/integrity evidence, not whole-game utility.
- No screen or controller PASS implies REPORT reuse, retry, training,
  production promotion or deployment.
