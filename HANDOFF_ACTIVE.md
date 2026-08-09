# Active Claude/Codex handoff

Last compacted: 2026-08-09 11:18 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, live compute in `JOBS.md`,
queue order in `BACKLOG.md`, and reviewed markers in `HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` versus `mc-strong`. Keep release 16 as runtime rollback and `mc-strong` as policy rollback. |
| T1 Teacher / Stage C | **T1 COMPLETE + 2,048-STATE DESIGN FROZEN** | Adapter `56ccefbd…c2442`; exact producer `94cfc1e`, packet `4df94e6c…13354`. Queue design review after its H0 dependency; no capture, labels, compute or training. |
| T2 S3a structured bury | **2,048-CLUSTER SCREEN RUNNING / SEALED** | Exact `c599b42`, packet `de16247b…cdd4`, admission `567e8aa8…41c5e`, receipt `2c89bed3…cbb2c`; eight Mini shards × 256. Count-only monitoring, then one terminal verify. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The first frozen treatment cluster exceeded the 250k-node cap. Do not retry or relax v2. |
| T2 learner O0-v2 | **COMPLETE / SELECT NONE** | Gate `0dbd9aa8…f24e` independently replayed. O1 and production remain unauthorized. |
| S4 point banking | **CODE + SCORE-FREE 64-STATE ASSET / REVIEW OPEN** | Exact `402c012`, asset `f44a0c72…e6b72`; treatment/null outcomes are uncomputed. Review may authorize this state screen only. |
| Human corpus / H0 | **V8 REVIEW PASS + SCORE-FREE H0 PACKET FROZEN** | Corpus `b9699790…16553`; exact packet producer `9770313`, packet `9ff160a9…247d3`. Queue its design review after S4; no execution, labels, training or strength. |
| External review | **OPEN / S4 ONLY** | Review the exact S4 packet below. S3a remains already reviewed/sealed; human-v8 is closed PASS. |

The latest status-only S3a heartbeat still has all eight workers live with no
completed shard. The latest cluster-count snapshot was
`68,68,66,70,66,66,67,67 / 256` (538/2,048). Outcomes remain unread.

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
2. **Review the frozen point-banking screen.** Exact `402c012` changes rollout
   continuation only and leaves sealed MCBot/registry bytes untouched. The
   treatment acts only last, after the baseline chose to win, and only while
   retaining a higher winner. Its matched null executes the same analysis. A
   score-free capture froze 32 attacker + 32 defender states from 64 unique
   deals; no exact outcome has been computed. External review gates the
   one-shot exact state screen. The sign is not assumed.
3. **Review the frozen Teacher Stage C design.** Exact `94cfc1e` defines 2,048
   fresh states: 1,024 DESIGN, 512 CALIB and 512 REPORT, with separate play and
   bury surfaces. It spends hard-tail gold labels on uncertainty,
   disagreement, exact-late and point-banking states while preserving an
   ordinary anchor. Human examples are DESIGN diagnostics only and cannot
   enter CALIB/REPORT. Packet review precedes state capture, labels and compute.
4. **Review the frozen human H0 design.** The August 9 evidence-grade
   Fly-snapshot-only rebuild accepts 2,830 plays and 45 buries from 122 fully
   replayed rounds, counts seven incomplete rounds, and finds 25 legal
   off-ballot human plays. Twelve legacy local-only rooms are excluded.
   Claude's corpus review passed. Exact `9770313` now freezes 384 DESIGN and
   128 disjoint AUDIT play keys plus all 36/9 human buries, using human actions
   as proposals rather than truth. The packet is score-free and independently
   verifies; queue its review after S4. HUMAN-C1 evaluation games can never
   train or select the candidate.

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
and a ten-point future-control cost. The 64-state asset is score-free and
awaiting review; none of this is yet a strength result.

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

### OPEN NOW — S4 point-banking mechanism and exact-state screen

Review exact pushed main `402c01203324ea3902891bef6cedf077a91ecec7`
and canonical score-free asset
`/Users/jerryyu/Projects/shengji/server/runs/logs/s4-point-banking-state-screen-160m-v1/states.json`:

- asset SHA-256 `f44a0c72593bef0ff93d96d2f9d93ece1a7a5c8afe44ab900466dd1f7c9e6b72`;
  it records `score_free=true`, `outcomes_computed=false`,
  `training_authorized=false`, clean exact Git and compiled routing;
- code/test ordered material SHA-256
  `96f547f78150035dbf0be13fc56ac5f38280231fd8c671d8550284ff1c9124b3`;
  exact SHAs are point policy `49d10d13…24cd1`, screen
  `438384fd…99bb`, policy tests `d5c022ca…f2d3`, screen tests
  `6ca9042c…2163`;
- capture scanned 67,237 fresh deals at seed start 160,000,000 and froze 64
  unique deals, exactly 32 per acting-team role. Natural trigger supply was 32
  attacker versus 308 defender; the screen intentionally reports equal-role
  and per-role estimands rather than hiding that skew;
- pure focused evidence/identity suite passes 90/90; compiled S4 + fast parity
  passes 30/30. The full clean-worktree run had 927 pass / 63 skip; after S4
  isolation, the three sealed-source drift failures are cleared. The remaining
  seven are the pre-existing missing-local-assets/root-path/compiled-runtime
  checks for this worktree.

Check both named utility witnesses, baseline contest preservation, last-seat
and higher-reserve semantics, role symmetry, matched-null work, deterministic
telemetry, root-ballot equality, and that `mcbot.py`/`registry.py` are unchanged.
Then inspect score-free population selection, physical-deck replay, unique
deal/role quotas, exact two-card solver boundary, one-sided gate math,
exclusive publication, admission binding and authority. Do not compute or
inspect state outcomes during review. PASS authorizes exactly one execution of
this 64-state exact screen. It does not authorize a full-game packet/run,
training, strength, promotion or production. Requested raw marker:

`S4_POINT_BANKING_SCREEN_V1_REVIEW {"schema":"s4-point-banking-screen-review-v1","git":"402c01203324ea3902891bef6cedf077a91ecec7","states_sha256":"f44a0c72593bef0ff93d96d2f9d93ece1a7a5c8afe44ab900466dd1f7c9e6b72","material_sha256":"96f547f78150035dbf0be13fc56ac5f38280231fd8c671d8550284ff1c9124b3","states":64,"attacker_states":32,"defender_states":32,"unique_deals":64,"score_free":true,"outcomes_computed":false,"independent_review":true,"screen_launch_authorized":true,"full_game_launch_authorized":false,"training_authorized":false,"strength_claim":false,"production_promotion":false,"verdict":"PASS"}`

### Later conditional packets

After the S4 review closes, the next request is exactly one of:

- **S3a confirmation review**, only after a terminal screen PASS: inspect the
  frozen 8,192-cluster packet, live-parent/null identity, fresh seeds, capacity,
  one-shot controller and authority boundary.
- **Teacher Stage-C design review**: inspect strata, split exclusion, label
  escalation, exact data contract and explicit no-compute/no-training flags.
  Exact producer `94cfc1ebed8096a88bebd12a4adddfe2396f0cfd`;
  canonical packet
  `/Users/jerryyu/Projects/shengji/server/runs/logs/teacher-stage-c-hard-tail-design-v1/design_packet.json`,
  SHA-256 `4df94e6ce71a1de94cd83ab125a87c705b737d27ce49d1b4c5e7e13e09a13354`.
- **Human H0 design-packet review**: inspect source/encoder hashes, pseudonymous
  player/deal splits, replay/rejection counters, action-union semantics,
  continuation comparison and HUMAN-C1 evaluation exclusion. Exact producer
  `977031386ed514239c181f6fba8c636f7b588ae0`; canonical packet
  `/Users/jerryyu/Projects/shengji/server/runs/logs/human-v8-h0-counterfactual-pilot-v1/design_packet.json`,
  SHA-256 `9ff160a9bc54a30daa85a07b29440f5c4cdd1c8feb4574f81c102158e46247d3`.

Append exact PASS/HOLD markers only to `HANDOFF_REVIEW.md`. A review PASS does
not silently authorize a run.

Dependency order after S4: review H0 first, because Stage C consumes only its
DESIGN split; then review Stage C. If S3a terminates first, its immutable
terminal path takes priority.

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
