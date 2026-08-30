# Active Claude/Codex handoff

> Current operational state only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> The latest authentic exact-head marker on remote main controls.

Last reconciled: **2026-08-30 08:29 EDT**. Remote main before this update:
`759311f`.

## Review queue — three narrow asks; R4 first

Review the exact machine-generated R4 sealed-inner recovery claim first. The
sole scientific unit reached its frozen hard limit at **12:23:20 UTC** with
`Result=timeout`, status 15 and zero restarts; the success-only verifier watcher
correctly launched nothing. The reviewed receipt builder then sealed
`r4-completion-timeout-receipt.json`, SHA-256
`b089dca4198dd3012b86ace734c9ff7f93fb5e0e57d05e75425a51eefabe1fd6`, with
`outcome_bytes_opened=false`, `test_split_reopened=false`,
`recovery_authorized=false` and `retry_authorized=false`. The reviewed pending
claim builder reproduced the sealed inner manifest/tree and printed the exact
dynamic claim without opening outcome bytes. Full claim and precise authority:
https://github.com/jerryyyu/shengji/pull/172#issuecomment-5468692412.

Validate that exact claim against live systemd state, the timeout receipt,
canonical source-review marker `00c184d`, sealed inner identities and recovery
source `5a81d89`. On PASS, append the authentic dynamic marker to canonical
`HANDOFF_REVIEW.md`. It may authorize only the outcome-blind pending outer
binding followed by one independent verifier; no test reopening, retry, result
replacement, interpretation, strength claim, promotion, deployment, training
or second verifier. No recovery process is running while this review is open.

Review PR #171 exact repaired head
`e271ede7021dc8440896fc3b816e0699579968bc`, parent
`b243368ca275988811c3e54db9c56b0de86f5fa1`. This is a two-file source delta
after the authorized `b243368` capacity refusal below localized the failure
above gameplay: both real Luna subprocesses recorded zero mailbox operations,
and the initially non-acting peer returned without a terminal witness before
the acting peer could establish a trace.

The repair leaves the reviewed game, ballot, rollout, utility, Stop-hook,
peer-sandbox, evidence, population and scheduler contracts unchanged. Both
private workspaces, mailbox servers and peer-denial profiles still become ready
first; only the engine's initial acting-team runner may then launch. The peer
launches only when the engine gives it a turn or round-end requires terminal
attachment. A can-fail witness holds the initial turn and raises on any eager
non-acting launch, then requires exact launch order and real actions by both
fake planners. Validation: **128 / 128** PT-Luna tests and clean diff-check.
Review request:
https://github.com/jerryyyu/shengji/pull/171#issuecomment-5468587196.

Requested authority is exactly one fresh non-scientific, score-free
progressive Mini capacity census; its first one-worker arm is the real launcher
witness. Do not authorize the 104-game collection, model prose/outcome use,
gameplay/strength claims, merge, retry beyond that census, training, promotion,
deployment or Value use. On success, the next review binds only the capacity
receipt plus immutable 52-deal x two-mirror freeze; unchanged source is not
reviewed again.

Review PR #170 exact repaired head
`7c77ca70068d72a8ce3774258107c04ad05efdff`, parent
`cf115ceac7dbf6f55a177a1de4058d14742a912b`. This is a two-file source delta
after the authorized `cf115cea` capacity census found 32/32 eligible fixtures
and then refused at the first state-successor arm because its legitimate
canonical replay output equaled the fixture input SHA. The repair hashes each
real operation output under an explicit operation-output schema/domain/stage,
while retaining the pre-wrap guard that rejects a worker returning the raw
fixture input identity. Its can-fail witness compares the exact ordered
32-fixture population. Validation: **434 / 434** V2 wildcard tests,
**48 / 48** focused capacity tests, both PR checks green and clean diff-check.
Review request:
https://github.com/jerryyyu/shengji/pull/170#issuecomment-5468647642.

Requested authority is exactly one replacement non-scientific, score-free
full-DAG Perf capacity census and, only after capacity success, one bounded
target-free rehearsal/preflight. Do not authorize scientific training, audit
opening, labels/outcomes, gameplay, PUCT/BELIEF integration, merge, retry
beyond those two actions, promotion, deployment or a strength claim. If both
succeed, the next review binds only their receipts plus the immutable
scientific freeze; unchanged source is not reviewed again.

Canonical ledger `979885f` PASSed both exact run-unblocking deltas: PR #171
`b243368ca275988811c3e54db9c56b0de86f5fa1` for one fresh score-free Mini
capacity census, and PR #170
`cf115ceac7dbf6f55a177a1de4058d14742a912b` for one replacement score-free
full-DAG Perf census followed, only on success, by one bounded target-free
rehearsal. Both censuses have now refused safely in their isolated namespaces
and consumed those authorities. PT and Value have the two repaired-head review
asks above. Neither refusal opened scientific data, and no retry is
pre-authorized.

PR #172 is fully source-authenticated. Canonical commit
`00c184dae0fb69c8c5d78d1e0c2b665366448451` appends the exact
`BELIEF_V1_V2_R4_RECOVERY_EXECUTION_V1_REVIEW ` marker for recovery head
`5a81d89cd954a63ac97ca8588926b3367c28c5c1`. Do not repeat this review or
publish another marker.

The live scientific unit has now timed out and the reviewed receipt/claim
entrypoints authenticated that marker against both clean cloud checkouts. The
first queue item is the required dynamic review. No recovery executes before
that exact claim receives PASS.

## Live work

### BELIEF R4 — top priority, hands off

- Strength Cloud exact execution head:
  `56bd35f0c45080121d094f6906ab8d1053ca9e6b`.
- Unit `belief-r4-terminal-scientific-56bd35f-r1.service` reached its frozen
  hard limit at **2026-08-30 12:23:20 UTC** with `Result=timeout`, status 15 and
  zero restarts. At **2026-08-29 14:58 UTC**, it had sealed the complete inner terminal:
  both score populations, human selection, scale curve, primary/control/human
  statistics, integrity receipt, result and inner manifest are immutable
  `0400`/one-link files. It timed out during mandatory immediate reconstruction
  before publishing outer `r4-completion-terminal.json`. Do not read the
  outcome. The success-only independent-verifier watcher exited without
  launching verification. Cgroup peak remained 23.76 GB under 24 GiB.
- Deadline expiry is now pre-adjudicated from the reviewed source. If
  `terminal.partial/` remains and `terminal/` is absent, no inner decision
  sealed and `recover-terminal-binding` is ineligible: preserve the namespace
  and draw no model conclusion. If `terminal/` exists, `terminal.partial/` is
  absent, and only `r4-completion-terminal.json` is missing, the narrow
  reviewed recovery may independently reopen that immutable inner terminal and
  publish only the missing outer binding after the scientific unit stops; it
  cannot reopen the test or choose a second result. If both inner and outer
  exist, recovery is forbidden and only the independent verifier remains.
- The sole test opening is consumed. Never stop, signal, duplicate, inspect
  outcome bytes, or touch the namespace.
- The reviewed timeout-receipt and pending-claim timers completed successfully.
  The receipt and exact dynamic claim are bound in the first review-queue item.
  No recovery has launched. A dynamic exact-claim PASS must precede the
  outcome-blind pending outer binding and sole independent verifier.
- The legacy duplicate-reconstruction watcher
  `belief-r4-terminal-recovery-watch-56bd35f-r1.service` is stopped and
  inactive. The old prose-PASS-bound `5a81d89-r1` timers are also stopped and
  inactive. The four marker-bound ref-refresh, timeout-receipt and pending-claim
  timers have now fired and are inactive. They published only the receipt and
  claim; they did not execute recovery, rescore, interpret outcomes or launch a
  verifier.
- R5 remains paused until the independently reproduced R4 verdict and curves
  are interpreted.

### PT-Luna0 — complete

- Exact source `2394140bcdaebf72d81912a55ac18f5051848fe5`; report
  `/Users/jerryyu/Projects/shengji-ptluna0-2394140-r1.json`; 52/52 complete and
  independently reopened.
- Mean signed-level contrasts: Luna−A +0.385, Luna−B +0.442,
  Luna−C0-S +0.615, Luna−Sol −0.269. Luna beats fixed baselines; Sol remains
  the stronger reviewed privileged teacher. No promotion or strength claim.

### PT-Luna fresh self-play — repaired capacity refused before gameplay

- PR #171 exact head `b12eea0485b944225ed1b99670d99c31dd010d33`
  received three convergent canonical source PASS entries. At **06:09 EDT**
  Codex launched the one authorized fresh score-free progressive Mini census
  in tmux `pt-luna-capacity-b12-r1`, root
  `/private/tmp/shengji-pt-luna-capacity-b12eea0-r1`. It failed closed in the
  first one-worker arm after about two minutes. The immutable public receipt is
  `capacity-failure.json`: team 0's genuine Luna subprocess returned normally
  with one `agent_message` and `turn.completed`, but zero `command_execution`
  items and zero mailbox operations, so no terminal mailbox witness existed;
  team 1 was then peer-aborted and also performed zero mailbox operations. No
  scientific deal, action, trajectory, outcome or model prose was retained.
- Canonical main `979885f` PASSed repaired exact head
  `b243368ca275988811c3e54db9c56b0de86f5fa1` for one replacement score-free
  capacity census. It launched at **07:44 EDT** in tmux
  `pt-luna-cap-b243368-r1`, root
  `/private/tmp/shengji-pt-luna-capacity-b243368-r1`, and refused safely in the
  first one-worker arm at **07:46 EDT**. The immutable public
  `capacity-failure.json` records two verified Luna subprocesses but zero
  mailbox operations from either team. Team 0 produced only two Codex error
  items and no final output; team 1 produced four error items plus two agent
  messages/final output, but no terminal mailbox witness. No action,
  trajectory, outcome or model prose was retained or opened.
- This localizes the remaining defect above the game engine: PR #171 reuses
  the reviewed production ballot, continuation evaluators, signed-level
  utility and engine mechanics, but its dual-process mailbox/peer-sandbox/Stop
  orchestration is new relative to successful PT-Luna0. The next change must
  prove one real exact-launch Luna process reaches the mailbox's first
  `observe` under the production sandbox before requesting another capacity
  authority. Do not spend another review on prompt-only or synthetic evidence.
- PR #171 repaired head
  `e271ede7021dc8440896fc3b816e0699579968bc` applies the narrow engine-turn
  launch gate described in the review queue. It is pushed and awaits one delta
  review; no Mini process is running and no retry is authorized yet.
- The 104 games remain unauthorized. Their eventual trajectories are only
  state/proposal sources for later engine relabeling, never value truth or a
  gameplay/strength result.

### Value-Afterstate V2 — output-identity repair awaits delta review

- Reviewed design: PR #169 exact `b2eb02bc`, design-only PASS. Draft PR #170
  repaired pushed head `cf115ceac7dbf6f55a177a1de4058d14742a912b` is
  clean; parent `ba17ab1eaa7eee4b083688e0f9e6cd19e683cb2c` remains the exact
  previously reviewed DAG source.
- The 42-file implementation completes the production path from D256
  population through P0, optimizer canary, labels, six natural/control
  cohorts, precision selection, audit attempt, terminal and reconstruction.
  Capacity runs the real P0 evaluator rather than a root-construction proxy;
  CPU/resource projections cover all 19 substages. Training recovers only
  sealed common-epoch member rows. Batched inference is byte-identical after
  canonical probability quantization. Audit inputs are durably sealed before
  any audit label opens.
- Repaired-source validation is bound by canonical PASS `979885f`. The
  original integrated Terra review found one real early-terminal dispatch
  defect; it was repaired and re-reviewed to PASS. The five actual
  adapter/controller witnesses include the initial population-deadline frontier
  that the first repair missed.
- Canonical main `3e98d06` and `9d12923` record the now-consumed exact-head
  `ba17ab1e` capacity authority. At **06:42 EDT**, the exact clean Perf census
  started and then refused safely after all 96 score-free attempts: only 14
  eligible fixtures existed versus the fixed 32 target. It never entered an
  arm, full-DAG, rehearsal, label, outcome, audit, or scientific stage. The
  bounded log is immutable and hash-bound above. The rehearsal authority was
  conditional on capacity success and therefore remains unused but cannot be
  applied to changed source. Exact repaired head
  `cf115ceac7dbf6f55a177a1de4058d14742a912b` launched its single authorized
  replacement capacity census at **07:44 EDT** as Perf systemd unit
  `value-v2-capacity-cf115ce-r1.service`, output root
  `/root/value-v2-capacity-cf115ce-output`. It found the exact 32/32 eligible
  score-free fixtures after 186 deterministic attempts, then refused at the
  first state-successor capacity arm with `capacity arm returned input identity
  instead of operation output`. No target, label, outcome, audit, rehearsal or
  later DAG stage opened. The service is failed/inactive with zero restarts;
  this capacity authority and its conditional rehearsal authority are spent.
- Root cause is local to the capacity identity guard: state-successor replays
  the canonical snapshot and hashes the canonical successor, which legitimately
  equals each fixture input SHA; the ordered output therefore triggers the
  anti-fake equality guard even though the operation ran. The repair must
  domain-separate identities derived from actual operation outputs while
  retaining a can-fail witness against a producer that merely returns fixture
  input identity. It must not change the V2 science DAG or estimand.
- The complete public progress log is preserved read-only at
  `/root/value-v2-capacity-cf115ce-output/capacity.progress.jsonl`, 9,076 bytes,
  SHA-256
  `62f4666de63fb14743e8c1f5fd2bbdaa9d956eed3984092246f12f82e8520081`.
  The runner emitted no structured failure receipt; record that as a later
  capacity-durability gap, not permission to fabricate one post hoc.
- PR #170 repaired head
  `7c77ca70068d72a8ce3774258107c04ad05efdff` changes only the capacity runner
  and its tests. It domain-separates identities derived from actual operation
  outputs and retains a failing-direction raw-input-identity witness over the
  exact 32-fixture population. The source is pushed, both PR checks are green,
  and the exact-head delta review above is the sole blocker to one replacement
  score-free capacity census. No Perf process is running and no rehearsal or
  scientific authority exists yet.

### Value-Afterstate V0 — independently verified refusal

- PR #164 exact head `d9ad99f6377040424821d79071e12435fde802ae`;
  consolidated source+capacity+population+freeze PASS at main `da7f0d7`.
  Marker SHA-256 `f656200b944f3fdb618df53ea3931b7afc7df646527f79913c26eadbb999c224`.
- Perf root `/opt/value-afterstate-v0-e3e4-d9ad99f-r1`; all attempts are
  consumed. Dataset generation sealed 7,446 rows. Eight members trained for
  seven common epochs and stopped for patience, selecting common epoch 2;
  training was not deadline-truncated. Heavy phases used about 16 effective
  cores. Independent verification re-executed every continuation and returned
  `verified=true`, terminal SHA-256 `53b2afc9…`.
- Terminal decision: `REFUSE_MECHANICS_OR_NEGATIVE_CONTROL`. The natural model
  passed held-out NLL (mean +0.404495 nats, one-sided lower +0.062702, 8/8
  seeds), but geometry-label permutation and complete-world shuffle also
  passed essentially the same gate. The model therefore learned a broad
  outcome/base-rate signal rather than the required action/world-sensitive
  value. Its action gate was negative on expected-utility error, simple regret,
  and incumbent non-regression. Pre-action ablation, rotation, and all five
  integrity mutations behaved correctly.
- No gameplay, E5a, retry, strength, merge, promotion, deployment, or R5
  authority exists. Preserve the artifacts; any successor needs a new design,
  not a retry or post-hoc threshold change.

### Value-Afterstate V1 — P0 passed; P1 selected none and is verified

- Capacity PR #166 is reviewed at repaired exact head
  `bd400a6855b83de263838cabdee1f07de6839ba2`. The old-head `-r1` and `-r2`
  invocations failed before data opening on operator-path guards; `-r3` then
  reached the train population and correctly exposed the missing singleton
  eligibility projection; the first repaired-head invocation exposed the
  same-prefix review-authenticator defect before row opening. All four failed
  outputs are absent and none is an ML/capacity result. Their exact lineage is
  bound into the P1 freeze.
- The new manifest-bound selector proves the entire declared candidate and
  replicate population before excluding only singleton ballots. The repaired
  review authenticator accepts the append-only exact-head marker after the old
  same-prefix marker. The final 13m01s capacity packet independently reopened
  with route `PASS_TO_P1_CAPACITY`; receipt SHA-256 is
  `31835b3e677239a72328535e63c1d3fd8535d3050308a33e578622b05da579f0`.
- P0 found reproducible paired action signal across 321 eligible states:
  combined mean +0.084112 signed levels, deal-bootstrap interval
  [+0.036050, +0.134259], and 23.3644% non-incumbent selection dose. This
  admits P1; it is not yet evidence that a model learns or improves play.
- The first P1 scientific admission at `3534fe0` is spent. It refused before
  training because its reader missed the capacity eligibility projection;
  no held-out label opened and no learning conclusion exists. PR #167 final
  head `c98bdeb` applies the selector to both train and calibration action
  populations, reproduces the capacity manifest on the real train population,
  and freezes that spent-attempt lineage under a new `r2` root.
- Claude's final exact-head PASS is `9aef077`. The single authorized Perf run,
  `value-afterstate-v1-p1-scientific-c98bdeb-r2.service` at invocation
  `7ffbb2af8de84873a41ee3c555479123`, completed successfully with zero restarts
  at 16:30:30 UTC. It consumed 42m34s wall / 8h27m CPU (about 11.9 effective
  cores), peaked at 2.1 GB, sealed all four early-stopped cohorts and target-free
  predictions before opening calibration exactly once, then independently
  reconstructed all 624 held-out rows. Every evidence file is immutable
  `0400`/one-link; reconstruction receipt is `2c361a3e...e4a35` and
  `verified=true`.
- Terminal decision: `SELECT_NONE_NO_ACTION_ADVANTAGE`. P0's label ceiling
  remained real, and all three negative controls failed on demand, but the
  natural model failed the action gate: advantage-error improvement was
  -0.139134 signed levels with interval [-0.164342, -0.115496], action/simple-
  regret utility was -0.061224 with interval [-0.174242, +0.128205], and only
  1/8 members was positive. World-shuffle separation also failed. This is a
  clean learning null, not a mechanics/control refusal.
- All gameplay, strength, merge, retry, P2, deployment and R5 authority remains
  false. Do not scale this recipe; preserve the verified result and use its
  curves to redesign the target/model only after R4 is interpreted.
- This is a 520-root mechanism pilot, not a final-quality model claim. Eight
  seeds test optimization stability, not data sufficiency; any later scaling
  adds independent roots/replicates only after P0/P1 establish real action
  signal.

## Fleet and boundaries

| host | current use |
|---|---|
| Strength Cloud | R4 sole scientific terminal + verifier watcher; hands off |
| Perf Cloud | free after Value V2 exact `cf115ce` capacity refused before its first arm completed |
| Mini | free after exact `b243368` PT-Luna capacity refused before gameplay; source diagnosis only |

- Keep hosts, branches, runtimes, and artifacts isolated.
- Do not stop, duplicate, retry, merge, deploy, resume R5, or launch additional
  scientific Value work. R4 interpretation remains the critical path.
- Report percentages, ETA, utilization, and failures plainly. Use all cores
  for materially parallel workloads; do not add risky concurrency merely to
  make a short deterministic prep step look busy.
