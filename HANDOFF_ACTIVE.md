# Active Claude/Codex handoff

Last compacted: 2026-08-09 13:55 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, live compute in `JOBS.md`,
queue order in `BACKLOG.md`, and reviewed markers in `HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` versus `mc-strong`. Keep release 16 as runtime rollback and `mc-strong` as policy rollback. |
| T1 Teacher / Stage C | **T1 COMPLETE + REPAIRED 2,048-STATE V2 DESIGN FROZEN** | Adapter `56ccefbd…c2442`; exact producer `b0ef0f9`, packet `45802e47…a350`. V1 is superseded before review. Queue v2 review after S4; no capture, labels, compute or training. |
| T2 S3a structured bury | **2,048-CLUSTER SCREEN RUNNING / SEALED** | Exact `c599b42`, packet `de16247b…cdd4`, admission `567e8aa8…41c5e`, receipt `2c89bed3…cbb2c`; eight Mini shards × 256. Count-only monitoring, then one terminal verify. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The first frozen treatment cluster exceeded the 250k-node cap. Do not retry or relax v2. |
| T2 learner O0-v2 | **COMPLETE / SELECT NONE** | Gate `0dbd9aa8…f24e` independently replayed. O1 and production remain unauthorized. |
| S4 point banking | **MECHANISM PASS + REPAIRED FULL-GAME V2 PACKET FROZEN / REVIEW QUEUED** | Pre-review audit superseded v1 without launch/outcomes. Exact v2 `cad3992`; score-free Air preflight `fcc8b891…ee060`; Mini packet `17036e63…1385` fully recomputes. No duel launch or strength claim. |
| Human corpus / H0 | **V8 REVIEW PASS + H0 DESIGN PASS** | Corpus `b9699790…16553`; exact packet producer `9770313`, packet `9ff160a9…247d3`. Claude authorizes implementation of a separately reviewed score-free controller only. Outcomes, labels, training, strength and HUMAN-C1 claims remain closed. |
| HUMAN-C1 | **INERT IDENTITY/LOG SEAM ONLY / AUDIT FIXES LANDED** | Exact `b198839` moves evaluation-tag refusal before every replay rejection and terminally invalidates a room on evaluation-log failure; mixed publications and unlogged starts now refuse. The 77-test corpus/server battery passes locally and on Air. No traffic path; consent/assignment ingress, runtime reopen, disconnect invalidation, C0/analyzer remain. |
| External review | **OPEN / S4 COMPLETE-ROUND V2 ONLY** | H0 design review passed. Claude's HOLD applied to obsolete v1 only; repaired v2 has fresh namespaces, an existing packet in named Mini/Air worktrees and pinned test commands. Review the v2 delta below. |

The latest status-only S3a heartbeat still has all eight workers live with no
completed shard. The latest cluster-count snapshot was
`152,151,152,154,155,152,153,151 / 256` (1,220/2,048). Outcomes remain unread.

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
2. **Advance the verified point-banking mechanism honestly.** Exact `1b35fb7` changes rollout
   continuation only and leaves sealed MCBot/registry bytes untouched. The
   treatment acts only last, after the baseline chose to win, and only while
   retaining a higher winner. Its matched null executes the same analysis. A
   score-free v2 capture froze 32 attacker + 32 defender states from 64 unique
   deals and independently replayed. Claude passed the packet; one reviewed
   Air execution then returned overall point mean `+5.156`, LCB `+3.029`, with
   both role means positive and level utility `+0.25`. Exact verification
   reproduced `abd9f36f…cdc00`. Pre-review audit then found that the v1 full-
   game validator accepted a wrong utility sign, utility `999`, underfilled
   report work and an unadmitted direct shard. V1 `b64bc95` / `80e4f1bf…6947`
   is therefore superseded with no launch or outcomes. Exact `cad3992` v2
   recomputes raw round outcomes, enforces all 330 accepted worlds per search,
   binds every canonical shard to the reviewed packet/admission/receipt chain,
   and hard-refuses confirmation before a future reviewed controller. Its
   fresh four-cluster score-free Air preflight passed in 321.32 seconds and
   projects 91.40 fleet-hours / 11.42 max-shard hours. Packet
   `17036e63…1385` is frozen and recomputes; review remains required before any
   duel, and no strength claim or production change exists.
3. **Review the frozen Teacher Stage C design.** Exact `b0ef0f9` defines 2,048
   fresh states: 1,024 DESIGN, 512 CALIB and 512 REPORT, with separate play and
   bury surfaces. It spends hard-tail gold labels on uncertainty,
   disagreement, exact-late and point-banking states while preserving an
   ordinary anchor. Human examples are DESIGN diagnostics only and cannot
   enter CALIB/REPORT. V2 also consumes the adapter's literal packet ID,
   reopens the exact live parent, conditionally binds S4 v2, and defines the
   regret/recall estimands. Packet review precedes state capture, labels and
   compute; v1 `4df94e6c…13354` is superseded.
4. **Implement the independently passed human H0 design boundary.** The August 9 evidence-grade
   Fly-snapshot-only rebuild accepts 2,830 plays and 45 buries from 122 fully
   replayed rounds, counts seven incomplete rounds, and finds 25 legal
   off-ballot human plays. Twelve legacy local-only rooms are excluded.
   Claude's corpus review passed. Exact `9770313` now freezes 384 DESIGN and
   128 disjoint AUDIT play keys plus all 36/9 human buries, using human actions
   as proposals rather than truth. The packet is score-free and independently
   verifies. Historical identity is pseudonymized from names, so the split is
   name-ID/deal-disjoint but cannot prove true-person disjointness if one
   person changed names. Claude accepted that limitation for this diagnostic-
   only pilot and authorized implementation of a separately reviewed score-
   free execution controller only. The frozen DESIGN selection is intentionally
   late-weighted (162 late / 111 mid / 111 early), and the requirement to keep
   every late and off-ballot row means inclusion within eligible fold deals,
   not that the entire packet is late-only. HUMAN-C1 evaluation games instead
   require stable consented session identity and can never train or select the
   candidate.

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
opponent win with a 5/10/K instead. This is not the old point-feeding issue.
S4 is now implemented outside the sealed production modules: it preserves the
root ballot/contest decision, acts only from the secure last seat and requires
a higher winning reserve. Named continuations show both a ten-point benefit
and a ten-point future-control cost. The first score-free asset is closed HOLD
because its claimed material digest was not reproducible. Exact `1b35fb7`
repaired that evidence boundary. Its reviewed 64-state exact screen is terminal
mechanism PASS: 35 wins, 4 losses and 25 ties; overall acting-team point delta
`+5.156` with one-sided LCB `+3.029`, and attacker/defender means
`+6.406/+3.906`. This establishes the narrow exact-late continuation
mechanism, not whole-bot strength. The repaired complete-round v2 packet is
frozen at exact `cad3992` / `17036e63…1385`; external review still gates its
only launch.

### H3 — human actions escape heuristic support

The refreshed corpus contains 25/2,830 human plays outside the broad
exhaustive-follow analysis ballot and humans buried points in 22/45 observed
banker decisions.
That is direct evidence that site play explores actions the historical
self-play generator can omit or disfavor. It does not say those moves are
better. H0 must add each human action to the frozen candidate union and price
it on common worlds under production and alternate named continuations. The
frozen H0 packet selects every late and every off-analysis-ballot row, caps a
deal at eight play decisions, and keeps the one-player/28-deal AUDIT component
untouched by DESIGN.

## Claude review packet

### CLOSED PASS — H0 human-action counterfactual design

Claude independently passed exact `9770313` / packet `9ff160a9…247d3`. The
full marker and measured review live in `HANDOFF_REVIEW.md`; this active file
does not duplicate them. Scope is deliberately narrow: implementation of a
separately reviewed score-free controller only. Counterfactual execution,
outcomes, labels, training, strength, promotion and HUMAN-C1 evidence all
remain unauthorized. Name-derived identity is acceptable for this diagnostic
pilot but does not prove true-person disjointness.

### Closed this turn — S4 exact-state mechanism

Claude's marker at `0ce1f04` passed the v2 packet. The only reviewed Air screen
published admission `83993ec6…5e6d`, pre-outcome receipt `90124eb6…526b` and
terminal result `abd9f36f…cdc00`; exact `verify-screen` reproduced it. Verdict
is `AUTHORIZE_FULL_GAME_PACKET_REVIEW`, with no full-game launch or strength.

### OPEN NOW — repaired S4 complete-round v2 packet

Claude's 14:52 HOLD is accepted and terminal for obsolete v1
`b64bc95` / `80e4f1bf…6947`; it never launched and published no outcomes. The
request below is a fresh v2 delta, not a repost of v1. Review exact
pushed `cad399294b888865a3bb79c47a9892200b896013`, runner
`8bf72a64…cbf7`, controller `ef05d668…911b`, and canonical path-neutral packet
`server/runs/logs/s4-point-banking-duel-screen-100b-v2/launch_packet.json`,
SHA-256 `17036e6307ad0072ae10aeaaddde0ed3628a2f526ca440e909cdc35cd5071385`.
V1 `b64bc95` / `80e4f1bf…6947` was superseded before review because its record
validator accepted a loss with positive utility, utility `999`, one accepted
world for a 330-world report-LCB search and score-bearing direct execution
without a pre-existing reviewed receipt. No v1 duel or outcome exists.

Review the three-arm estimand: treatment, analysis-identical matched null and
live champion share each mirrored deal and all policy/opponent RNG streams.
The null must be raw-outcome-identical to champion on every seed/flip; treatment
must beat both by clustered paired level utility and trigger in both roles.
Champion/opponent S4 counters must remain zero and exact MC work is mandatory.
The screen is fresh 2,048 clusters at seed base 100 billion, eight Mini shards
of 256; PASS opens confirmation-packet review only.

Reopen score-free Air preflight `fcc8b891…ee060`: four clusters, no published
outcome/utility rows, exact treatment/null dose in both roles, 321.32 seconds,
projected screen 91.40 fleet-hours / 11.42 max-shard hours. Reopen mechanism
parent `abd9f36f…cdc00`. Inspect the separate portable live-parent reopener:
it authenticates fixed closeout/aggregate/freeze bytes and current champion
semantics while leaving the original historical-host reopener unchanged.
Verify raw `banker`/`attacker_points` outcome reconstruction, signed physical
utility bounds, exact `(30+300)*searches` accepted-world dose, canonical paths,
full review-authority reopening and confirmation refusal before compute.
The packet exists byte-identically at these exact review roots:

- Mini: `/Users/jerryyu/Projects/shengji-s4-duel-cad-mini/server/runs/logs/s4-point-banking-duel-screen-100b-v2/launch_packet.json`
- Air: `/Users/jerryyu/Projects/shengji-s4-duel-cad-air/server/runs/logs/s4-point-banking-duel-screen-100b-v2/launch_packet.json`

Run from the Mini worktree root with the repository venv. The exact pure
invocation measured 44/44:

```sh
PYTHONPATH=server /Users/jerryyu/Projects/shengji/server/.venv/bin/python -m pytest -q server/tests/test_point_banking.py server/tests/test_live_champion_parent.py server/tests/test_s4_point_banking_duel.py server/tests/test_s4_point_banking_duel_screen.py
```

The exact compiled-plus-parity invocation measured 58/58:

```sh
SHENGJI_FAST=1 PYTHONPATH=server /Users/jerryyu/Projects/shengji/server/.venv/bin/python -m pytest -q server/tests/test_point_banking.py server/tests/test_live_champion_parent.py server/tests/test_s4_point_banking_duel.py server/tests/test_s4_point_banking_duel_screen.py server/tests/test_fast_parity.py
```

Air independently passed the same file lists using its compute venv. Packet
review may authorize one screen only; it may not authorize confirmation,
strength, training, promotion or production. Requested marker:

S4_POINT_BANKING_DUEL_PACKET_V2_REVIEW {"schema":"s4-point-banking-duel-screen-review-v2","git":"cad399294b888865a3bb79c47a9892200b896013","run_id":"s4-point-banking-duel-screen-100b-v2","packet_sha256":"17036e6307ad0072ae10aeaaddde0ed3628a2f526ca440e909cdc35cd5071385","preflight_sha256":"fcc8b8913d80db5b1fe4bb7d6b727dc722bb7d0f4ec9c8806842535fc43ee060","mechanism_screen_sha256":"abd9f36fa3e84c81b90e22f1c827f828a549f7fd6a9420ffbdb7c168974cdc00","independent_review":true,"screen_launch_authorized":true,"confirmation_launch_authorized":false,"strength_claim":false,"training_authorized":false,"production_promotion":false,"verdict":"PASS"}

### Later conditional packets

After the S4 review closes, the next request is exactly one of:

- **S3a confirmation review**, only after a terminal screen PASS: inspect the
  frozen 8,192-cluster packet, live-parent/null identity, fresh seeds, capacity,
  one-shot controller and authority boundary.
- **Teacher Stage-C design review**: inspect strata, split exclusion, label
  escalation, exact data contract and explicit no-compute/no-training flags.
  Review v2 after S4. Exact producer
  `b0ef0f9fe59e15c1618ae25e7dfa5ddd851bd94e`;
  canonical packet
  `/Users/jerryyu/Projects/shengji/server/runs/logs/teacher-stage-c-hard-tail-design-v2/design_packet.json`,
  SHA-256 `45802e47a4b81a6418cf3f4f75c0314b5b9c9dec52b16398fffb8cfb7f4a350b`.
  V1 `94cfc1e` / `4df94e6c…13354` is superseded and grants no review.

Append exact PASS/HOLD markers only to `HANDOFF_REVIEW.md`. A review PASS does
not silently authorize a run.

Dependency order: H0 design review is closed PASS. Review the already-frozen
S4 packet now so Mini cannot become idle after S3a; review Stage C next because
it consumes only H0's DESIGN split. H0 controller implementation may proceed
in parallel, but it cannot execute. S4 cannot launch without its own PASS or
while S3a owns Mini. If S3a terminates first, its immutable terminal path takes
priority.

The forward HUMAN-C1 range through `b198839` is not a launch request and does
not block S4. A later bounded review should confirm ordinary-room log behavior
is unchanged, evaluation/training roots cannot overlap, the room bot's policy
name must match the hidden arm, the participant-derived pair and per-arm ballot
identities cannot drift, both block slots are complementary, seats 0/2 are the
two bound humans, raw names/chat are absent, evaluation write failures surface,
and the corpus refuses tags anywhere in a round, including malformed rounds
that lack `round_start`. Confirm any evaluation write failure terminally
invalidates the room before a retry can manufacture a complete session.
Focused audit tests pass 77/77 on Mini and independently on Air. No
consent/assignment ingress, evaluation room
route, traffic, strength claim or promotion exists.

## Fleet and safety rules

- Mini owns the sealed S3a screen. Do not switch or dirty its detached
  `c599b42` worktree, inspect shard logs, read partial outcomes, retry or extend.
- Air completed the repaired S4 v2 score-free preflight and independent tests.
  It is free; packet `17036e63…1385` has no launch authority before review.
- Long reviewed compute prefers Mini; sub-hour bounded work may use Mini when
  it does not contend with a live exclusive job.
- Every strength run binds the exact champion, engine, sampler, ballot,
  continuation, utility, seeds, null, work and stop rule. Screens may select
  one design; fresh confirmation is required for a strength claim.
- Formal S0, V11 direct-v2, Direct-Q, O0/O0-v2, S3b-v2 and Teacher audit
  failures are closed. Diagnose them; never silently extend them.
