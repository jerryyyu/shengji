# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-04 (post-pivot)**.

## Current gate summary — read this first

The program pivoted on 2026-09-04 (ledger `0088544f` retrospective,
`295136ba` V2 unblock). Operational truth is the bus plus the ledger; this
file is a pointer.

1. **Value V2 is in DEV mode (tier i).** Up-front pipeline review PASSed at
   `c4b8f7e8` (ledger `ca459e14`). The first end-to-end D64 dev run is live on
   Perf: unit `value-v2-dev-d64-c4b8f7e8-r1.service`, root
   `/root/value-v2-dev-d64-c4b8f7e8-r1`. No freeze, packet, capacity rebind,
   marker, per-launch confirmation, or reconstruction applies to dev runs.
   Private artifacts and evaluations stay closed until `terminal.json` seals
   (route `D64_DEV_SEALED`); then one interpretation review, then D256.
2. **PT-Luna isolated route is COMPLETE** (32/32, ledger `6c71bee3`); the
   dataset is readable for the scoped teacher/value research only. Collection
   is closed.
3. **BELIEF R4 is terminal, R5 closed.** No belief compute unless the
   oracle-belief ceiling screen is positive.
4. **Next asks in order:** D64 seal → interpretation; oracle-value and
   oracle-belief ceiling screens; Luna disagreement analysis; V2 Luna
   fine-tune; search-policy variants through the RLCB paired harness.

Everything below this line is retained history for reconstruction only.

## Priority and authority

1. R4 is terminal with route `NO_PRIMARY_POLICY_SIGNAL`; never relaunch it.
2. Keep R5 paused.
3. PT-Luna PR #188 head `d402bcb7` and combined ladder packet PASSed review.
   The fresh canary and one-worker arm passed, but the four-worker arm completed
   only 4/8 games. The sealed terminal route is
   `REFUSE_RESOURCE_OR_PROVIDER`; no freeze follows this attempt. Draft PR
   #189's play-only design PASSed at canonical ledger `6a07ea80`; its exact
   repaired source head `780fd7efc10bae08c75c2bdf4b044f4b0f42e71b`
   received a one-blocker HOLD at ledger `9b6eee1b`: its ordinal-2 exhaustion
   guard was correct but the named test did not witness a resumed fourth
   dispatch. Test-only head `ba6e06a9` closes exactly that gap: 145/145
   focused tests, and Claude's `>= 3` mutation makes the exact witness red.
   Claude PASSed the test-only repaired head at ledger `218d7513`; marker
   `ece086c8`. Fresh canary packet SHA `ec7936d0…` was substitution-confirmed,
   preflighted once, and PASSed: receipt `ddc88bd8…`, 1+4 committed decisions,
   both teams, engine state changed, zero tool events. Contingent capacity
   packet SHA `87402a2c…` was substitution-confirmed, preflighted once, and its
   sole score-free census launched at 00:11 EDT in tmux
   `pt-luna-rpc-capacity-ba6e-r1`. No scientific collection or freeze follows
   unless the capacity receipt passes its frozen affordability route. The
   census sealed at 01:08 with all 10/10 games complete, zero provider/process/
   tool failures, zero redispatches or exhaustions, arm-four observed
   parallelism 3.758 and scaling efficiency 0.928. Receipt file SHA is
   `32db0f60…`, internal SHA `bc93c75e…`. Its formal route is nevertheless
   `REFUSE_RESOURCE_OR_PROVIDER`: arm-four p95 game wall 948.866 seconds fails
   the frozen <=900-second gate, and the 104-game projection is 30,838 seconds
   versus the 28,800-second scientific wall. No freeze or retry follows. Claude
   then recorded canonical finding `a84e6c57`: the source implemented only a
   binary pass/refuse judge and omitted the play-only design's preregistered
   `FULL_104_ELIGIBLE | PILOT_32_ELIGIBLE | REFUSE` routing. Under those frozen
   rules this score-free profile would qualify for the distinct 32-game pilot
   (~9,489 seconds), not the 104-game lane. The old refusal remains final; the
   correct next step is one narrow source head implementing sections 5-6 with
   threshold/refusal witnesses, followed by one fresh census under that judge.
   A pre-freeze audit also found that `source_review_claim()` hashes the parent
   `PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md`, not the superseding play-only
   design; exact `execution_git` still content-binds the latter, but its named
   design hash does not. Exact repaired head
   `cb6e9c99cab8029b99a246d1b98dc66b75509679` is now pushed to PR #189. Its
   five-file delta implements the exact three routes, first-16-root-hash pilot
   schedule with both mirrors, route-bound receipt/freeze/CLI execution, and a
   two-design source-review hash. Related suites are 268/268 and 109/109 green;
   disabling the pilot at the actual selector makes three boundary witnesses
   red; an independent integration review PASSed; GitHub server/frontend CI is
   green. Claude PASSed the exact head at canonical ledger/marker `9b1ea54c`
   after walking design sections 5-6 against code and killing both the route-
   boundary and pilot-selection mutations. Fresh canary packet SHA
   `33cb9d78…` at
   `/private/tmp/pt-luna-rpc-cb6e9c99-canary-r1-launch-packet/launch.sh`; it is
   substitution-only versus the verified prior packet and Claude confirmed it
   on Agent Bus sequence 77. Its first preflight and launch invocations stopped
   before namespace creation or a provider call because three ignored `.pyc`
   shadows predated the packet; they were quarantined intact and the exact tree
   remained clean. Under the same pre-admission/unconsumed-grant precedent, the
   unchanged packet then passed preflight and launched the fresh formal canary
   at 01:56 EDT. It sealed and independently revalidated after 1+4 contested
   decisions with both teams acting, state changes in both fixtures, zero tool
   events, receipt `d41e8ce6…` and file SHA `557a22ec…`. Contingent capacity
   packet `27098081…` was substitution-confirmed; its read-only preflight
   passed, the required per-launch confirmation was received, and the sole
   corrected-judge score-free census launched at 02:02 EDT in tmux
   `pt-luna-rpc-capacity-cb6e-r1` and sealed at 02:54 EDT. All 10/10 games
   completed with zero provider/process/tool failures, zero retries,
   redispatches, or exhaustions. The four-worker arm measured 3.835-way
   parallelism, 0.884 scaling efficiency, and p95 918.267 seconds. The exact
   route is `PILOT_32_ELIGIBLE`: the 104-game projection is 29,844 seconds and
   misses the 28,800-second full-lane cap, while the first-16-cluster x two-
   mirror pilot projects to 9,183 seconds under its 12,000-second cap. Sealed
   capacity file SHA `cf1cb57d…`, internal receipt `3c254615…`; independently
   revalidated at exact head. Route-bound freeze `e24cf56b…` and census
   `ece5d9e0…` were independently rebuilt byte-exact at namespace
   `pt-luna-rpc-pilot-cb6e9c99-r1`; private/public scientific roots remain
   absent. Claude independently rebuilt and PASSed the exact freeze at
   canonical marker `9ccfd972`; Codex independently authenticated that marker.
   Jerry explicitly approved the <=33.3M-token / <=3h20m pilot budget in the
   Codex conversation. Exact 106-line packet SHA `30b68517…` passed its sole
   read-only preflight and the pilot launched once at 03:20 EDT. It terminally
   refused at 03:41 EDT after four completed games and four incomplete games;
   24 games were never started. Terminal route is
   `REFUSE_RESOURCE_OR_PROVIDER`, receipt `4a53e4d2…`, with every retry, data,
   label, gameplay, merge and strength authority false. All four incomplete
   attempts record the same pathless `PermissionError` message hash, which
   independently resolves to `[Errno 1] Operation not permitted`; the first
   refusal preceded the other three by 116 ms and cancellation produced the
   rest. A controlled four-worker transport race reproduces the exact error:
   completion and cancellation can both signal one process group, while clean
   completion signals after the group leader was reaped. Exact two-file repair
   head `d126ad019e1175cd6fe7d0a296c911bf28ae8883` gives cleanup exactly one
   owner and does not re-signal a clean wrapper exit; six same-altitude tests,
   all 326 PT-Luna tests, and a 200-call repaired-head stress pass with zero
   `PermissionError`; both PR checks are green. Claude PASSed the exact repair
   at marker commit `78775fa0`, authorizing one fresh canary and, only after a
   verified canary PASS, one fresh score-free census. Fresh 72-line, mode-0400
   canary packet SHA `ca1e8322…` was substitution-confirmed and launched once.
   It PASSed both production boundary fixtures with one nonterminal decision
   plus four alternating contested decisions, both teams acting, engine state
   changing, zero tool events, file SHA `ecc4cd85…`, and internal receipt
   `847712b0…`; the exact production reopener independently validates it.
   Contingent capacity packet SHA `0147b2fb…` passed its unchanged read-only
   preflight and received the required launch confirmation. Its one fresh
   score-free census completed both arms and independently reopens at file SHA
   `77fce3eb…`, receipt `1ba204ee…`. The route is
   `PILOT_32_ELIGIBLE`: four workers, 16 independent deal clusters / 32
   mirrored games, projected 9,329 seconds and 26,404,925 tokens. A fresh
   inert route-bound freeze now independently rederives: external SHA
   `fabb7048…`, internal `3b35bc8a…`, private census external `9af2ade6…`,
   internal `16acef9d…`. Exact launch packet `1f657b5f…` PASSed read-only
   preflight. Claude PASSed the freeze at canonical marker `098b708b`; Jerry
   explicitly approved the <=26.4M-token / <=12,000-second pilot and it
   launched once at 10:50 EDT. The public terminal independently validates at
   file SHA `d1cc5c13…`, receipt `c5034c20…`, route
   `REFUSE_RESOURCE_OR_PROVIDER`: 3 games completed, 4 were incomplete, and 25
   never started after 3.52M ledger tokens. The primary refusal was the frozen
   1,200-second per-game deadline after 78 committed decisions. One second
   later the supervisor terminated the other three in-flight provider
   subprocesses, whose private typed receipts all record return code -9 with
   the same message hash; these are cancellation cascades, not three
   independent provider outages. No outcome interpretation, data use, retry,
   merge, or strength authority exists. Never retry either spent pilot.
4. Value V2 census-10 is terminally refused, before labels/audit/science. Exact
   head `17bd059724cf05b9dab8adb6b0d68bc3929d220f` passed preflight and ran for
   2,451 seconds (2h23m aggregate CPU, 22.6 GB peak, zero swap). It completed
   preflight, continuation widths through 64, and member concurrency, then the
   production-shaped width-four cohort warm pass refused with
   `concurrent Torch thread scope drift`. Immutable failure artifact:
   `/root/value-v2-capacity-17bd059-r1-failure.json`, file SHA `d2431825…`,
   internal receipt `65bfb473…`; all authority is false and the namespace is
   spent. Root cause is reproduced: already-created Python controller threads
   do not observe a sibling's later Torch width change. Exact repaired head
   `8ff9c79cd294770b51127ec7a844694784b7d0bc` pins the creator/process thread
   before spawning cohort threads in both capacity and scientific adapters.
   The exact old-head spawned three-controller witness is red and the repaired
   witness is green; 630/630 Value V2 tests pass in required `-P -B` mode.
   Claude PASSed the exact head at canonical ledger `4365fa3f`. Census-11
   packet SHA `4fae16de…` is 104 lines, mode 0400, byte-identical local/Perf,
   and substitution-only versus the line-verified census-10 packet. Claude
   confirmed the substitution; the correctly invoked preflight PASSed with
   unchanged SHA, all five leaves absent, and unit `not-found`. (A prior direct
   shell invocation hit 0400 `Permission denied` before any packet line.)
   Claude explicitly confirmed launch, and Census-11 launched exactly once at
   06:49:35 UTC as `value-v2-capacity-8ff9c79-r1.service`, invocation
   `82478035de9945a08b5c4927261a03bb`. It completed every arm and all 19
   representative-DAG stages in 6,680 seconds with zero restart and 22.57 GB
   peak below the 30-GB cap, then sealed score-free failure file SHA
   `06019851…`, internal receipt `3a059e3d…`, route
   `full-dag/composed-projection-cap-drift`. The width-two composed D256 wall
   is 23,065 seconds versus the frozen 21,600-second/two-for-one limit (6.78%
   over); no label, audit, outcome, freeze, science or retry authority exists.
   The expensive stage counters are retained. The next source/design change
   must bind this exact failure and run only a longer production-shaped
   width-two-versus-width-four cohort benchmark plus fresh score-free
   preflight, then re-adjudicate the retained DAG. Do not repeat the 19 stages,
   move the cap, retry census-10, or duplicate Census-11.
   Exact child `8a11160bbdff86050729abcd1e2bc8679bc0c951` is pushed as
   draft PR #190. It implements only that retained-evidence path, including a
   fresh 32-deal preflight, sustained width-two/four production-topology arms,
   typed success/refusal, and shared downstream reopener. Strict Value tests
   pass 638/638. Its corrected launch-ready Perf packet SHA is `6a947cf2…`;
   exact read-only preflight PASSed. Claude PASSed source+launch at canonical
   ledger `936e8f4b`. The sole recovery census launched at 10:16:45 UTC as
   `value-v2-capacity-readjudication-8a11160-r1.service`, invocation
   `90cce19a605e4e79ba09b5399f493e00`, and terminally refused after 759
   seconds with zero restarts. Immutable failure artifact
   `/root/value-v2-capacity-readjudication-8a11160-r1-failure.json` is mode
   0400/single-link, file SHA `190d9e3d…`, internal SHA `aa2587ac…`, and
   independently reopens at exact source/runtime. It binds the Census-11
   failure and reports `composed projection cap drift`; every authority is
   false. The terminal diagnostic log is stable at SHA `25253a18…`: fresh
   preflight accepted 32/301 attempts; sustained warm/measured arm spans were
   approximately 42+41 seconds for width two and 68+72 seconds for width four,
   so width two remained materially faster and the unchanged 23,065-second
   D256 projection still exceeds the 21,600-second limit. Never repeat the 19
   stages or this recovery census. The typed failure retains only the generic
   cap refusal, not the new arm samples; the unsealed progress log is useful
   engineering evidence but cannot become capacity PASS evidence. Nested
   progress rows also display the inherited 7,200-second headroom while the
   actual receipt/worker/parent/systemd bounds were 3,600/3,600/3,600/3,900;
   treat that only as telemetry debt.
5. No scientific PT retry or Value run is authorized. Value V2 C1 draft PR
   #191 at exact head `a4d036ace3a6f8180f2373d5a616e1a9fcd4220b` preserves
   Census-11 D256 and implements only the explicit 7-hour complete-DAG / 14-hour
   service economics amendment. Review ask:
   `https://github.com/jerryyyu/shengji/pull/191#issuecomment-5512225804`.

## Review queue

1. **PT-Luna PR #189 PASSed at exact head
   `cb6e9c99cab8029b99a246d1b98dc66b75509679`.** Canonical marker
   `9b1ea54c` authorizes exactly one fresh canary and, only after its verified
   PASS, one corrected-judge capacity census. Canary packet `33cb9d78…` PASSed
   with independently validated receipt `d41e8ce6…`. Contingent capacity packet
   `27098081…` then passed preflight and the required launch confirmation; its
   sole census sealed `PILOT_32_ELIGIBLE` with file SHA `cf1cb57d…` and
   internal receipt `3c254615…`. Route-bound freeze `e24cf56b…` and census
   `ece5d9e0…` independently rebuild byte-exact. Claude PASSed the freeze at
   marker `9ccfd972`; Jerry approved the hard budget and the pilot launched
   once. It sealed `REFUSE_RESOURCE_OR_PROVIDER` after 4 completed / 4 failed /
   24 pending games, receipt `4a53e4d2…`; no outcome interpretation or data use
   is authorized. Exact repair head `d126ad019e1175cd6fe7d0a296c911bf28ae8883`
   is pushed to PR #189 with both checks green and PASSed at marker commit
   `78775fa0`. Exact fresh canary packet `ca1e8322…` PASSed and independently
   reopened at file SHA `ecc4cd85…`, receipt `847712b0…`. Exact capacity packet
   `0147b2fb…` passed preflight and launch confirmation and its sole census
   sealed `PILOT_32_ELIGIBLE` at file SHA `77fce3eb…`, receipt `1ba204ee…`.
   Exact freeze `fabb7048…` / internal `3b35bc8a…` and private census
   `9af2ade6…` / internal `16acef9d…` rederive byte-exact. Exact launcher
   `1f657b5f…` preflight-PASSed. Claude PASSed at canonical marker `098b708b`;
   Jerry approved the budget and the launch ran once. Its validated terminal
   is file SHA `d1cc5c13…`, receipt `c5034c20…`, route
   `REFUSE_RESOURCE_OR_PROVIDER`, with 3 completed / 4 incomplete / 25 pending
   games and 3.52M ledger tokens. One game hit the exact 20-minute deadline
   after 78 decisions; the other three incomplete workers were killed by the
   supervisor's terminal cancellation one second later (return code -9). No
   interpretation, data use, or retry is authorized. Never retry either spent
   namespace.
2. **Value V2 PR #187 PASSed at exact head
   `8ff9c79cd294770b51127ec7a844694784b7d0bc`.** Census-10
   at exact head `17bd0597` sealed a score-free refusal after 2,451 seconds at
   the real width-four controls topology; failure file SHA `d2431825…`, receipt
   `65bfb473…`. Canonical PASS `4365fa3f` authorizes one fresh census under the
   active per-launch protocol. Exact packet `4fae16de…` was substitution-
   confirmed, preflight-PASSed, explicitly launch-confirmed, and launched once
   as Census-11. It completed every expensive stage and sealed score-free
   failure SHA `06019851…` / receipt `3a059e3d…`: width two projects to 23,065
   seconds, 1,465 seconds above the frozen two-for-one limit. The next packet
   is not another full census. Draft PR #190 exact `8a11160b` binds that
   failure, measures only sustained production-topology width two/four, and
   re-adjudicates the retained 19 stages; 638/638 strict tests pass. Its exact
   corrected Perf packet `6a947cf2…` PASSed read-only preflight and Claude
   PASSed at ledger `936e8f4b`. Its sole score-free recovery census invocation
   `90cce19a…` terminally refused after 759 seconds: width two remained faster
   than width four, so recomposition preserves the 23,065-second D256 wall and
   fails the unchanged 21,600-second cap. Failure file SHA `190d9e3d…`,
   internal SHA `aa2587ac…`; independent reopen PASSed and every authority is
   false. No second census, freeze, science, audit, merge, deployment,
   promotion, or strength authority exists. Any Value continuation now needs
   a new design/source decision that reduces the measured critical path or
   explicitly changes its scientific economics; it may not relabel this
   refusal as a capacity pass.
3. **Value V2 C1 draft PR #191 awaits one source/design review at exact head
   `a4d036ace3a6f8180f2373d5a616e1a9fcd4220b`, parent exact `8ff9c79c`.** It
   reopens the exact Census-11 refusal, retains the 23,065-second D256 DAG, and
   changes only the explicit caps to 25,200 seconds complete / 50,400 seconds
   service. Canonical amendment file SHA `178d713b…`, internal `9da98a66…`;
   pure 636, compiled 637, and focused 63 tests pass. Review ask is PR comment
   `5512225804`. PASS may authorize one target-free final-head rehearsal only;
   no scientific compute, labels/audit/outcomes, merge, gameplay, retry,
   deployment, promotion, or strength claim.
4. Value V2 PR #187 prior source PASS is canonical at ledger `70cfaab2` and packet
   approval at `6a4a6b9a`. Its sole preflight refused before execution because
   the inherited venv imported the old checkout; the subsequent launch attempt
   repeated the same guard and also refused pre-systemd. Canonical ruling
   `93e9188f` preserved the grant. The checkout-local editable path was repaired
   without changing packet bytes; exact preflight PASSed and capacity then
   sealed a terminal projection refusal after all 19 stages.
5. PT-Luna PR #189 design PASS is canonical at `6a07ea80`, exact head
   `6df640ea35001bcabee105dcc9434a6068a57ebb`. Ultra and offline reconstruction
   found an opaque transient nonzero exit plus disposable-probe observability
   debt, not a Luna/schema refusal. Jerry then authorized bounded casual design
   probes. Exact receipts `r7` SHA `3e5edd54…` and `r8` SHA `d03f99ab…`
   together cover the predeclared fixed packet population: 24/24 serial and
   24/24 four-way concurrent calls, 48 attempts, zero refusals/retries/tools,
   max four active RPCs, exact runtime stable. Serial p95/max were 42.322/44.691
   seconds; concurrent p95/max were 38.466/40.235 seconds. The next review is
   still one consolidated source + canary/capacity-launch packet after nested
   production-schema reuse, durable unknown-telemetry refusal evidence, exact
   retry/accounting, and capacity-altitude witnesses are locally green.
   Independent architecture review rules out a transport-internal retry loop
   and a no-retry full run: the roughly 6,378-call population requires durable
   `(logical_packet_sha256, attempt_ordinal)` journal/ledger identities so each
   eligible attempt is charged, settled, recoverable, and unable to commit
   twice. Play-only remains the policy simplification; availability redispatch
   remains limited to the two reviewed classes and two extra attempts.
6. PT-Luna PR #188 source PASS/marker are canonical at `09cb59df`, and its
   combined ladder packet is approved at `de0664b1`. Exact preflight PASSed and
   the fresh canary→capacity run sealed a validated refusal receipt. Ultra is
   complete: the current full-rollout/no-retry 104-game lane fails both
   reliability and wall-time gates. No freeze or retry follows this attempt.
7. Value capacity receipt
   `/root/value-v2-capacity-81f662b-r1-failure.json` is terminal, file SHA
   `2c31f1b3…`, with all authorities false and no outcome/label/science open.
   Its fresh census selected cohort width 1 as the fastest eligible arm, so
   the earlier width-4 counterfactual did not materialize. Ultra found the
   24,082-second DAG arithmetic exact with no duplicate stage, but the width
   selector is not representative: one 0.768-second nested-thread observation
   at 15.6% utilization chose the production topology. Replaying sealed walls
   gives width 1/2/4 = 24,082/22,764/16,928 seconds; only width 4 passes. The
   smallest repair is a bounded score-free production-altitude width benchmark
   with real controller processes, selection, checkpoint/reopen, warm/order-
   balanced repeats, and byte identity. No rehearsal, freeze, or repeat census
   is authorized before that source/design packet is ready.

## PT-Luna supervisor RPC — simplified source review

- Draft PR: #183. Exact reviewed source head:
  `f4287954ab592d4a3fe8380e17c331d02c6626d7`.
- Claude source PASS: canonical ledger `7dba67bd`; exact machine marker commit
  `655545664006fcd8c32f7b1e9deb8f4639f68b19`.
- Formal boundary canary PASSed and independently reopened: canonical receipt
  SHA `0faefc5c…`; nonterminal and four-play alternation both changed engine
  state with zero tool events.
- Spent formal capacity root:
  `/Users/jerryyu/.shengji-runs/pt-luna-rpc-f4287954-capacity-r1`.
- Formal receipt SHA `295c3469…`, route `REFUSE_RESOURCE_OR_PROVIDER`. Game 0
  hit 1,216 seconds; game 1 failed after 406 seconds. Both had zero tool events,
  but the formal schema discarded the second exception class. No later arm ran.
- No scientific collection, outcomes, Value use, retry, merge or strength claim
  is authorized.
- The guarded watcher correctly launched nothing. One separate non-scientific
  Luna-medium game then completed and verified in 782.368 seconds with 63 RPCs,
  692,000 tokens and zero tool/process errors. Receipt:
  `/Users/jerryyu/.shengji-runs/pt-luna-casual-medium-f428-r1/result.json`, file
  SHA `1c87361f…`. It is not formal capacity or scientific evidence.
- Draft PR #184 design PASS: canonical main marker commit `3629b7ac`; exact
  design head `8353d7fc501120e760d9433658fa6040c211da0b`.
- Draft PR #186 exact source head
  `e976759bb63c82e384f90b414e519f436e382c14` implements medium reasoning,
  nested provider actions, typed
  restart-stable failures, absolute deadlines, progress, and fixed arms `[1,4]`
  selecting exactly four workers. The exact RPC suite is 129/129 green.
- Claude combined PASS: canonical ledger commit `ca6858bd`; it authorizes one
  formal pinned canary then one score-free capacity census, in that order.
- Machine marker commit `5f52ccd2` is canonical. The formal canary PASSed and
  independently reopened with receipt SHA `516fcd01…`: the mixed rollout/play
  case and four-play alternation both changed engine state with zero tools.
- The separate immutable capacity packet is
  `~/.shengji-runs/pt-luna-rpc-e976759b-capacity-r1-launch-packet/launch.sh`,
  SHA `27e133b6…`, mode 0400. Its production preflight PASSed and the sole
  score-free census launched in tmux `pt-luna-rpc-capacity-e976-r1` at 19:48
  EDT. It is terminally stopped; do not launch another formal attempt.
- The first one-worker game completed and verified: 57 committed decisions and
  69 RPCs. In the second game, RPC 22 returned a trace lacking the exact
  completion telemetry required by the reviewed parser. The journal correctly
  sealed that provider-schema refusal, but after the temporary journal was
  removed the capacity wrapper tried to summarize it again. That secondary
  `FileNotFoundError` masked the original typed refusal and prevented a durable
  `capacity.json` receipt. The formal capacity grant is spent.
- Current repair scope is deliberately narrow: report failure progress from a
  pre-cleanup snapshot, preserve the original provider-schema classification,
  and add a non-null-progress-sink witness at the real runner altitude. There
  is no evidence yet for relaxing the strict telemetry parser.
- Draft PR #188 exact head
  `d402bcb7e2e7e08a898a7ebbfe2d54f83039c4d4` implements that two-file
  repair. The production-altitude witness is red on `e976759b` and green here,
  pins the original provider-schema stage/kind/type/message SHA, and observes
  one opened RPC, zero committed decisions, and the `game-failure` event. Full
  RPC suite: 129/129. Request one source review only; no formal retry follows
  without a new explicit grant.
- Claude's source PASS is canonical at `09cb59df`; exact CI is green. Combined
  repaired-head ladder packet
  `/private/tmp/pt-luna-rpc-d402bcb7-ladder-r1-launch-packet/launch.sh` is
  byte-identical to its immutable run copy and hashes to `43457ede…`. It runs a
  fresh canary, then capacity only if the canary passes and reopens. Packet
  review/grant is canonical at `de0664b1`. Exact preflight PASSed; tmux
  `pt-luna-rpc-d402-ladder-r1` launched at 20:24 EDT. The fresh canary PASSed
  and sealed receipt `1f2244b2…`: exact source/review `d402bcb7`, both cases
  state-changing, zero tools. The one-worker arm sealed PASS at
  `capacity-work/arm-1.json` (SHA `8fca9a97…`): both games completed and
  independently verified in 866.8/678.1 seconds with 76/74 RPCs, zero failure
  dispositions, and aggregate 1,644,454 tokens. The four-worker arm observed
  four simultaneous RPCs and 3.363-way realized parallelism, but only 4/8 games
  completed. Two failed because the Codex command emitted stderr; one lacked
  the required completion telemetry. The fourth surfaces publicly as
  `TurnJournalError("planner transport exception")`, but source inspection
  proves that wrapper catches a non-`TurnRPCError` from dispatch/transport and
  then makes capacity misclassify it as journal I/O; its underlying type was
  not preserved in the public metric. Neither deadline flag fired. The
  validated terminal receipt is
  `/Users/jerryyu/.shengji-runs/pt-luna-rpc-d402bcb7-ladder-r1/capacity.json`,
  file SHA `ceb91adf…`, internal receipt SHA `f8a899c9…`, route
  `REFUSE_RESOURCE_OR_PROVIDER`. Even absent those failures, its projected
  104-game wall is 38,981 seconds versus the frozen 28,800-second scientific
  wall. No freeze follows; do not retry this exact design.
- Jerry authorizes clearly labeled casual, non-scientific PT experiments after
  the simplified design review. They may reproduce and validate this repair,
  but cannot supply formal capacity evidence or authorize collection.
- Authorized casual step 2 PASSed: four workers x four committed decisions in
  95.995 seconds, 26 RPCs, 279,948 tokens, zero tool events, peak four active
  RPCs, and observed parallelism 3.3132.
- Authorized casual step 3 stopped once at its declared admission boundary:
  814.874 seconds, 73 RPCs, 60 committed decisions, 800,005 charged tokens,
  zero tool events, engine healthy. The 900,000-token envelope retained its
  100,000-token next-call reserve. No retry or cap increase occurred; it is not
  a complete game, capacity evidence, or scientific evidence.
- Ultra's independent redesign audit concludes that fixing only the mislabeled
  journal failure cannot save the lane: arm-four p95 was 1,199.406 seconds
  versus the exact 886.154-second full-population ceiling, and four terminal
  provider failures occurred across 521 arm-four calls. Draft PR #189 at exact
  head `6df640ea35001bcabee105dcc9434a6068a57ebb` is a one-file play-only design.
  It removes the optional rollout-phase calls, permits at most two
  identical-packet redispatches only for zero-exit/nonempty-stderr and
  completion-telemetry drift, and predeclares either the full 52x2 source, the
  first-16-cluster mirrored pilot, or refusal using capacity data only.
- Claude independently PASSed that design at canonical ledger `6a07ea80`; its
  arithmetic and wrapper diagnosis reproduced. Section-7 casual probes were
  released under Jerry's separate authorization. Setup attempts r1/r2 stopped
  before a provider call on isolated scratch-environment mistakes; r3 also
  stopped pre-provider on a disposable private-binding mismatch. After an
  explicit binding self-check, r4 made exactly one real pinned Codex 0.149.0
  Luna-medium call for fixed packet `b4bdf058…` and received
  `CodexProviderResourceError("Codex turn process failed")` (nonzero exit),
  before any engine commit. Its private refusal carried unknown tool-count
  telemetry; the disposable wrapper rejected that `None` and crashed before
  publishing `result.json`. The root/log are preserved, no action or outcome
  was published, and the reviewed stop rule forbids retry or advancing to the
  whole-game probe. Ultra concluded that this is an opaque nonzero Codex
  subprocess exit plus a disposable observability bug, not evidence that Luna
  rejected the play-only packet. The private request binding had already
  validated; exact exit/stderr/trace/final presence were then lost at temporary
  cleanup. Offline reconstruction is recorded at
  `/private/tmp/pt-luna-play-only-r4-offline-diagnosis.md`, SHA
  `7d82c9ef…`. It also found that the probe exactly reused the existing nested
  production play schema while the design text sketches a different flat
  schema. The smallest next packet explicitly reuses the production schema,
  durably preserves private refusal evidence before cleanup, treats unknown
  telemetry as fail-closed/full-reserve, seals accounting before reporting,
  and witnesses the original disposition at capacity altitude. Fold this into
  the single consolidated source + formal-launch review; no standalone design
  round is planned.
- The repaired disposable instrumentation first ran one diagnostic packet in
  20.186 seconds / 10,884 tokens with an accepted nested play response and zero
  tools. The bounded availability experiment then completed across two fresh
  casual roots without repeating any completed packet: `r7` file SHA
  `3e5edd54…` supplied all 24 serial plus the first 10 concurrent packets; `r8`
  file SHA `d03f99ab…` supplied the remaining 14 concurrent packets. Combined:
  48/48 accepted, zero first-attempt failures, eligible refusals, exhausted
  packets, retries, private refusal files, or tool events; 521,060 charged
  tokens; maximum four active calls; runtime identity stable. These are design
  diagnostics only and cannot satisfy formal capacity or enter a corpus.

## Value-Afterstate V2 — repaired capacity terminal refusal

- Draft PR: #181. Exact source head:
  `d3b731eff27a471720c24cae46ad5f362ef8f692`.
- Claude source PASS: canonical ledger `e282895f`.
- Perf unit: `value-v2-capacity-d3b731e-r1.service`.
- Progress:
  `/root/value-v2-capacity-d3b731e-r1.progress.jsonl`.
- Future terminal receipts:
  `/root/value-v2-capacity-d3b731e-r1.json` and
  `/root/value-v2-capacity-d3b731e-r1-failure.json`.
- The service terminally refused after 6,529 seconds with no restart and all
  authorities false. Failure receipt SHA `826a6973…`; route detail
  `composed projection cap drift`.
- The complete-DAG projection is 24,283 seconds versus the frozen 21,600-second
  maximum (12.4% over). This is a conservative composed critical path, not an
  observed scientific overrun. Largest projected stages are `label-p0` 4,439s,
  complete-world shuffle 3,200s, and the two permutation controls 3,012s each.
- Optimize output-identical label generation and repeated control materials
  first. Parallel control cohorts require a new topology witness/design change;
  raising the cap merely to fit this receipt is not authorized.
- Draft PR #187 at exact head `81f662bf` now binds the composed projection to
  the selected cohort width and retains complete passed arm-census evidence in
  later failures. The retained walls project to 24,283 / 22,965 / 16,941
  seconds at widths 1 / 2 / 4. The legacy d3 failure did not retain the selected
  cohort arm; its `workers=2` stage rows identify member concurrency and cannot
  select one counterfactual. Full Value suite: 619/619 plus two final topology
  witnesses. One source/design review of this exact repaired head is the next
  prerequisite before any fresh capacity packet; no cap raise is proposed.
- Claude's exact-head PASS is canonical at ledger `70cfaab2`. The reviewed
  packet candidate is byte-identical locally and on Perf at SHA `8b17cee2…`,
  mode 0400, with fresh `81f662b-r1` paths and the old refusal bound by SHA.
  packet approval is canonical at `6a4a6b9a`. The preflight then correctly
  found that the copied `.venv` still resolved `shengji` from the old
  `d3b731e` checkout. Codex mistakenly attempted launch after that refusal; the
  packet repeated the same import-origin guard and refused again before
  `systemd-run`. All five output/work/log leaves remain absent; unit is
  `not-found`, PID 0, zero restarts. Canonical ruling `93e9188f` preserved the
  grant and authorized an environment-only repair under the same packet. The
  dependency venv now resolves `shengji`, supervisor, and `_fast` inside the
  exact `81f662b` root; packet SHA `8b17cee2` remained unchanged. Fresh
  preflight PASSed and unit `value-v2-capacity-81f662b-r1.service` launched at
  00:27 UTC, invocation `f11a5ea9…`, active with zero restarts. The population
  preflight completed; all six `state-successor` worker arms completed. All
  progressive arm grids (`state-successor`, `continuation-mechanics`,
  member/cohort concurrency, inference batch, and reconstruction) completed.
  `label-p0` and `optimizer-canary` completed without a restart and the actual
  full-DAG execution advanced to `label-precision-select`; the progress history
  retains all earlier stage rows. At 22:05 EDT the unit remained active with
  PID `358543`, zero restarts, 4.02 GB current / 22.48 GB peak memory, roughly
  331 GB disk free, and 6,696 seconds of stage-local headroom. The stage-local
  elapsed counter reset is not a service restart. Measured utilization has
  varied from roughly 19% in tails to 88% while work was full.
- No freeze or scientific authority exists yet.
- The current reviewed implementation is intentionally D256-only:
  `world_afterstate_v2_capacity_runner` marks exact source supply true only
  for D256, and the training-input adapter independently refuses any larger
  tier. D512/D1024 PT-Sol/PT-Luna/human projections are planning evidence for
  a future source amendment; neither the active capacity census nor its first
  scientific successor can ingest PT data silently.
- Draft PR #185 at exact head
  `80735f97be18d5029b0f5f903d446561f3986a83` closes the required
  public-`forward` malformed-batch witness debt. It is the direct base/ancestor
  of PR #187, so that witness is already present in the executing `81f662bf`
  source head. No post-capacity source edit, separate review, or repeated
  capacity run is needed for it.
- On PASS: exactly one target-free rehearsal, five inert freeze inputs, one
  consolidated exact-freeze review, then one resumable scientific run. Do not
  separately call `initialize` followed by `run`; `run` consumes admission.
- The fresh exact-head capacity completed all 19 stages in 6,542 seconds and
  sealed failure receipt SHA `2c31f1b3…` (internal receipt SHA `172ba949…`).
  The composed projected science DAG is 24,082 seconds, 2,482 seconds/11.49%
  over the 21,600-second cap, and also fails the two-for-one service-wall rule.
  The fresh arm census selected cohort width 1 because widths 2 and 4 were not
  faster eligible arms. The service exited once with no restart and a 22.48 GB
  peak cgroup footprint. No rehearsal/freeze follows this refusal.

## R4 — terminal

- Route: `NO_PRIMARY_POLICY_SIGNAL`; terminal ledger `2615423`.
- All 104 opened-DEV shards and 60,944 legal worlds verified.
- Synthetic-primary changed one final action; label control changed zero. Both
  paired true-world value contrasts were exactly zero.
- Primary Brier improved versus REF-C, but the shuffled-label control also
  improved unexpectedly, so this is not clean behavioral-belief evidence.
- The sealed test remained unopened. R5/gameplay/deployment authorities remain
  false.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | R4 terminal retained; idle | no R4/R5 relaunch |
| Perf Cloud | Value V2 retained-evidence recovery is terminal `composed projection cap drift`; failure `190d9e3d…` / `aa2587ac…`, width two remained faster, all authority false | idle; never duplicate the run or repeat the old 19-stage DAG; redesign or optimize before any new capacity work |
| Mini | PT-Luna `d126ad01` capacity sealed `PILOT_32_ELIGIBLE` (`77fce3eb…` / `1ba204ee…`); exact 32-game freeze `fabb7048…` / `3b35bc8a…` PASSed at marker `098b708b`; launcher `1f657b5f…` preflight-PASSes; no gameplay live | wait only for Jerry's fresh 26.4M-token affordability approval, then launch once |

All long work must expose elapsed time, ETA, utilization, deadline headroom and
resumable progress. Do not repeat spent namespaces or duplicate multi-hour
integrity work.
