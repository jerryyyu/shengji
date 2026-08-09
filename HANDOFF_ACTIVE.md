# Active Claude/Codex handoff

Last compacted: 2026-08-09 12:18 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, live compute in `JOBS.md`,
queue order in `BACKLOG.md`, and reviewed markers in `HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` versus `mc-strong`. Keep release 16 as runtime rollback and `mc-strong` as policy rollback. |
| T1 Teacher / Stage C | **T1 COMPLETE + REPAIRED 2,048-STATE V2 DESIGN FROZEN** | Adapter `56ccefbd…c2442`; exact producer `b0ef0f9`, packet `45802e47…a350`. V1 is superseded before review. Queue v2 review after H0; no capture, labels, compute or training. |
| T2 S3a structured bury | **2,048-CLUSTER SCREEN RUNNING / SEALED** | Exact `c599b42`, packet `de16247b…cdd4`, admission `567e8aa8…41c5e`, receipt `2c89bed3…cbb2c`; eight Mini shards × 256. Count-only monitoring, then one terminal verify. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The first frozen treatment cluster exceeded the 250k-node cap. Do not retry or relax v2. |
| T2 learner O0-v2 | **COMPLETE / SELECT NONE** | Gate `0dbd9aa8…f24e` independently replayed. O1 and production remain unauthorized. |
| S4 point banking | **V1 CLOSED / V2 GENERATION REPLAY COMPLETE / REREVIEW OPEN** | Exact treatment `1b35fb7`, asset `4538be85…6b5f`; independent score-free replay `b0ef0f9` / `3079fb16…f0a9`. Treatment/null outcomes remain uncomputed. |
| Human corpus / H0 | **V8 REVIEW PASS + SCORE-FREE H0 PACKET FROZEN** | Corpus `b9699790…16553`; exact packet producer `9770313`, packet `9ff160a9…247d3`. Forward-only `45f30bb` refuses evaluation-tagged training publication; frozen evidence is unchanged. Queue H0 review after S4. |
| HUMAN-C1 | **INERT IDENTITY/LOG SEAM ONLY** | Exact `4880159` adds hidden complementary blocks, exact server-only identity and disjoint fail-closed logging. It is unreachable from WebSocket traffic; consent ingress, layout/runtime binding, C0 and analyzer remain. |
| External review | **OPEN / S4 ONLY** | Review the exact S4 packet below. S3a remains already reviewed/sealed; human-v8 is closed PASS. |

The latest status-only S3a heartbeat still has all eight workers live with no
completed shard. The latest cluster-count snapshot was
`97,96,94,98,95,95,95,95 / 256` (765/2,048). Outcomes remain unread.

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
2. **Review the frozen point-banking screen.** Exact `1b35fb7` changes rollout
   continuation only and leaves sealed MCBot/registry bytes untouched. The
   treatment acts only last, after the baseline chose to win, and only while
   retaining a higher winner. Its matched null executes the same analysis. A
   score-free v2 capture froze 32 attacker + 32 defender states from 64 unique
   deals, binds its executable material recipe and Air native runtime, and
   verifies by full replay; no exact outcome has been computed. External review
   gates the one-shot exact state screen. The sign is not assumed.
3. **Review the frozen Teacher Stage C design.** Exact `b0ef0f9` defines 2,048
   fresh states: 1,024 DESIGN, 512 CALIB and 512 REPORT, with separate play and
   bury surfaces. It spends hard-tail gold labels on uncertainty,
   disagreement, exact-late and point-banking states while preserving an
   ordinary anchor. Human examples are DESIGN diagnostics only and cannot
   enter CALIB/REPORT. V2 also consumes the adapter's literal packet ID,
   reopens the exact live parent, conditionally binds S4 v2, and defines the
   regret/recall estimands. Packet review precedes state capture, labels and
   compute; v1 `4df94e6c…13354` is superseded.
4. **Review the frozen human H0 design.** The August 9 evidence-grade
   Fly-snapshot-only rebuild accepts 2,830 plays and 45 buries from 122 fully
   replayed rounds, counts seven incomplete rounds, and finds 25 legal
   off-ballot human plays. Twelve legacy local-only rooms are excluded.
   Claude's corpus review passed. Exact `9770313` now freezes 384 DESIGN and
   128 disjoint AUDIT play keys plus all 36/9 human buries, using human actions
   as proposals rather than truth. The packet is score-free and independently
   verifies. Historical identity is pseudonymized from names, so the split is
   name-ID/deal-disjoint but cannot prove true-person disjointness if one
   person changed names; review must accept this as a diagnostic-only H0
   limitation. Queue its review after S4. HUMAN-C1 evaluation games instead
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
repairs that evidence boundary and a fresh v2 64-state asset is awaiting
review; none of this is yet a strength result.

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

The v1 request at `402c012` / `f44a0c72…e6b72` is closed HOLD and has no
authority. Claude reproduced every individual file and the score-free asset,
but correctly refused its unexplained material digest and unpinned test-count
claims. Review this fresh replacement only:

- exact pushed source `1b35fb7c6234fb6022181b54ce8210c796cc35c3`;
- canonical score-free asset
  `/Users/jerryyu/Projects/shengji/server/runs/logs/s4-point-banking-state-screen-161m-v2/states.json`,
  SHA-256 `4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f`;
- the asset records `score_free=true`, `outcomes_computed=false`,
  `training_authorized=false`, exact clean Git, host
  `Jerrys-MacBook-Air.local`, Python `3.14.6`, compiled routing and compiled
  binary SHA-256 `d14eefdd…ebe2e0`;
- it scanned 69,047 fresh deals beginning at seed 161,000,000 and froze 64
  unique deals, exactly 32 per acting-team role. Natural trigger supply was 32
  attacker versus 321 defender; report equal-role and per-role estimands rather
  than hiding that skew;
- the code computes its own material identity. In order, the canonical JSON
  list contains `server/shengji/ai/point_banking.py` at `49d10d13…24cd1`,
  `server/scripts/s4_point_banking_screen.py` at `5c6c0bbc…40b6`,
  `server/tests/test_point_banking.py` at `d5c022ca…f2d3`, and
  `server/tests/test_s4_point_banking_screen.py` at `46b6ee8f…d674`.
  Serialize that list with sorted keys, separators `(',', ':')`, plus one final
  newline, then SHA-256 it: `5eeb1b507efc6645c7121fb9214b3e269f48fd251d815b7b029eabffa385c6a8`;
- exact pure command from `server/`:
  `uv run pytest -q tests/test_point_banking.py tests/test_s4_point_banking_screen.py`
  — 27 passed;
- exact compiled command from `server/`:
  `SHENGJI_FAST=1 uv run pytest -q tests/test_point_banking.py tests/test_s4_point_banking_screen.py tests/test_fast_parity.py`
  — 41 passed. Air independently reproduced both as 27/27 and 41/41 using its
  bound Python.

Delta-specific correctness fixes are part of this review: the secondary
house-rule utility now distinguishes 80 (`+0.5`) from 120 (`+1.5`), the full
admission object must match exactly, capture/runtime/native/material fields
fully verify, exact run-directory/filename relationships refuse alternate
artifact names, and a one-shot receipt consumes the namespace before the first
outcome. The namespace is deliberately portable across clean worktrees; it was
never an absolute-root invariant. `verify-screen` fully recomputes any terminal
artifact. No `screen.json`, receipt or admission exists yet.

The 11:53 audit correctly noted that structural replay alone did not prove the
ascending population. Exact pushed verifier `b0ef0f9fe59e15c1618ae25e7dfa5ddd851bd94e`
therefore rescanned the entire score-free stream on Air without calling an
outcome scorer. Canonical witness
`/Users/jerryyu/Projects/shengji/server/runs/logs/s4-point-banking-capture-generation-replay-161m-v2/generation_replay.json`
has SHA-256 `3079fb16cd4d697668f342a50187b859b86fa01219f8f0cc1fe441e01b65f0a9`.
It independently selected the first 32 triggers per role in ascending order,
stopped at deal 69,047, reproduced observed supply 32/321, and rebuilt all 64
stored states/actions/telemetry exactly. Its own source SHA is
`03707140…c9fb1`; the exact compiled battery passes 44/44. The witness grants
review only and leaves screen launch false.

Check both named utility witnesses, baseline contest preservation, last-seat
and higher-reserve semantics, role symmetry, matched-null work, deterministic
telemetry, root-ballot equality, and that `mcbot.py`/`registry.py` are unchanged.
Then inspect score-free population selection, physical-deck replay, unique
deal/role quotas, exact two-card solver boundary, one-sided gate math,
exclusive publication, admission binding and authority. Do not compute or
inspect state outcomes during review. PASS authorizes exactly one execution of
this 64-state exact screen. It does not authorize a full-game packet/run,
training, strength, promotion or production. Requested raw marker:

S4_POINT_BANKING_SCREEN_V2_REVIEW {"schema":"s4-point-banking-screen-review-v1","git":"1b35fb7c6234fb6022181b54ce8210c796cc35c3","states_sha256":"4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f","material_sha256":"5eeb1b507efc6645c7121fb9214b3e269f48fd251d815b7b029eabffa385c6a8","states":64,"attacker_states":32,"defender_states":32,"unique_deals":64,"score_free":true,"outcomes_computed":false,"independent_review":true,"screen_launch_authorized":true,"full_game_launch_authorized":false,"training_authorized":false,"strength_claim":false,"production_promotion":false,"verdict":"PASS"}

### Later conditional packets

After the S4 review closes, the next request is exactly one of:

- **S3a confirmation review**, only after a terminal screen PASS: inspect the
  frozen 8,192-cluster packet, live-parent/null identity, fresh seeds, capacity,
  one-shot controller and authority boundary.
- **Teacher Stage-C design review**: inspect strata, split exclusion, label
  escalation, exact data contract and explicit no-compute/no-training flags.
  Review v2 only after H0. Exact producer
  `b0ef0f9fe59e15c1618ae25e7dfa5ddd851bd94e`;
  canonical packet
  `/Users/jerryyu/Projects/shengji/server/runs/logs/teacher-stage-c-hard-tail-design-v2/design_packet.json`,
  SHA-256 `45802e47a4b81a6418cf3f4f75c0314b5b9c9dec52b16398fffb8cfb7f4a350b`.
  V1 `94cfc1e` / `4df94e6c…13354` is superseded and grants no review.
- **Human H0 design-packet review**: inspect source/encoder hashes, pseudonymous
  player/deal splits, replay/rejection counters, action-union semantics,
  continuation comparison and HUMAN-C1 evaluation exclusion. Explicitly judge
  whether name-ID/deal disjointness is sufficient for this diagnostic-only
  pilot despite not proving true-person disjointness. Exact producer
  `977031386ed514239c181f6fba8c636f7b588ae0`; canonical packet
  `/Users/jerryyu/Projects/shengji/server/runs/logs/human-v8-h0-counterfactual-pilot-v1/design_packet.json`,
  SHA-256 `9ff160a9bc54a30daa85a07b29440f5c4cdd1c8feb4574f81c102158e46247d3`.

Append exact PASS/HOLD markers only to `HANDOFF_REVIEW.md`. A review PASS does
not silently authorize a run.

Dependency order after S4: review H0 first, because Stage C consumes only its
DESIGN split; then review Stage C. If S3a terminates first, its immutable
terminal path takes priority.

The forward HUMAN-C1 delta `45f30bb..4880159` is not a launch request and does
not block S4. A later bounded review should confirm ordinary-room log behavior
is unchanged, evaluation/training roots cannot overlap, the room bot's policy
name must match the hidden arm, both block slots are complementary, evaluation
write failures surface, and the corpus refuses tags anywhere in a round.
Focused human/H0/WebSocket/scheduler tests pass 68/68. No consent/assignment
ingress, evaluation room route, traffic, strength claim or promotion exists.

## Fleet and safety rules

- Mini owns the sealed S3a screen. Do not switch or dirty its detached
  `c599b42` worktree, inspect shard logs, read partial outcomes, retry or extend.
- Air completed the fresh score-free S4 v2 capture and is otherwise free. It
  has no reviewed outcome/strength launch; do not run the S4 screen before the
  exact marker above passes.
- Long reviewed compute prefers Mini; sub-hour bounded work may use Mini when
  it does not contend with a live exclusive job.
- Every strength run binds the exact champion, engine, sampler, ballot,
  continuation, utility, seeds, null, work and stop rule. Screens may select
  one design; fresh confirmation is required for a strength claim.
- Formal S0, V11 direct-v2, Direct-Q, O0/O0-v2, S3b-v2 and Teacher audit
  failures are closed. Diagnose them; never silently extend them.
