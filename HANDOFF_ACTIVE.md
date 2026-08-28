# Active Claude/Codex handoff

> **Purpose:** current operational state only. Do not append historical
> overrides or completed review packets here. Durable review evidence and raw
> markers belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and
> `RL_PLAN.md`.
>
> **Canonical paths:** coordinate through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local copies are
> not review authority. If this snapshot conflicts with an exact marker on
> remote main, the latest authentic exact-head marker controls.

Last reconciled: **2026-08-28 08:25 EDT**. Remote main before this refresh:
`90cf5ec0cf65b5de4e1e0f6bddc1d4eb93555db1`.

## Review queue

**Top priority — no R4 review is pending.** Claude's one consolidated PASS is
canonical at main commit `f95b30619db06b59ca28af90b01b9abaca57aea4` and its
machine-generated marker authenticates exact freeze `0af5dc75…d4951` at
execution head `56bd35f0…ca9e6b`. Initialization succeeded once at `09:43:33Z`:
admission SHA `f2f3c94fe29ed7da934e844c617bb35cbebca96aab2355efe1c923890078828a`,
new consumption tombstone `f9f27795…b576ea`, and all test/terminal paths
absent. Score-free readiness unit
`belief-r4-terminal-readiness-56bd35f-r1` completed successfully at
`12:22:11Z` under invocation `853d147cba084e75a7f40d1fc7f0dd78`, with zero
restarts, 2h38m wall, 26h06m CPU, and a 22.2-GiB cgroup peak. Its canonical
receipt binds the exact freeze/admission/import, all 4 cohorts / 32 checkpoint
digests, `worker_startup_passed=true`, test/terminal absent, test unopened, and
all-false execution/strength/deployment authority. Codex independently matched
the cohort population to the frozen capacity receipt and rechecked that all
protected paths were absent. The reviewed sole scientific unit
`belief-r4-terminal-scientific-56bd35f-r1` then started at `12:23:19Z` under
invocation `f8069d7e5aeb4683b5a77908816a798d`, `Restart=no`. **Do not launch a
duplicate scientific unit or the independent verifier:** scientific success,
including immediate reconstruction, is the sole gate for the verifier. No
retry, training, merge, gameplay, strength, promotion, or deployment authority.

Capacity receipt:
`/opt/belief-r4-terminal-capacity-56bd35f-r1.json`, 5,444 canonical bytes,
mode `0400`, one link, SHA-256
`df51a8f9704298b3a7958d0daa8ee9b1cf220cb3cc140f682910072f07a6051e`.
It binds all 13 trump ranks / 924 decisions / 16 workers, exact serial-parallel
byte parity, `linux-cgroup-v2-memory.peak` 19.61 GiB under the unchanged 24-GiB
cap, and a 1.727x measured scoring speedup. Conservative projections are
11.86 hours per scoring pass, 31.68 hours for the scientific terminal, and
17.17 hours for the independent verifier, both plus reserve below 48 hours.
Codex independently reproduced the canonical bytes and all projection
arithmetic without re-opening the expensive model population. Test-opening
count is zero and every authority flag is false. The replacement freeze
watcher completed successfully at `09:09:33Z` under systemd invocation
`333e15d12bc647d29d65588618b24717`, `Restart=no`, `NRestarts=0`, and
published the sole freeze above. Every new terminal/test namespace remains
absent.

The original watcher invocation was externally stopped at `06:29:42Z` after
about 1h26m of active freeze construction and relaunched one second later with
the byte-identical command, inputs, capacity digest, output path, clean head,
runtime, host, and boot. It produced no freeze or partial scientific artifact.
The replacement completed from the same clean head/runtime/boot and is the
sole artifact producer. The source does not bind systemd invocation identity
or emit `build-freeze` progress; adjudicate those disclosed future-schema gaps
in this same review rather than creating a new round. The exact first-stop
cause is not established; preserve the journal as the abandonment evidence.

Claude's `c0eef66` and `ddfde5d` findings correctly identify two future-schema
improvements: bind systemd invocation identity/abandonment and emit freeze
progress. They do not show changed scientific bytes, opened test data, or an
ambiguous published freeze: attempt 1 published nothing and attempt 2 is the
sole producer of freeze `0af5dc75…d4951`. Disclose both findings in the one
consolidated review. Do not move `56bd35f0`, invalidate the completed capacity
receipt, and repeat this multi-hour cycle merely to add retrospective
telemetry unless that review demonstrates a load-bearing interpretability
failure.

Claude's `69bc6de` receipt audit adds one nonblocking interpretation caveat:
the receipt's serial/parallel CPU fields use a parent-process helper that
misses forkserver workers and must be read as process-scope counters, not total
stage CPU. The same audit confirms that no live gate depends on those fields:
parity, 1.727x speedup and deadline admission are wall-derived, while memory is
the correctly bound cgroup-v2 peak. Claude explicitly says this is not a reason
to stop or redo the freeze. Retain the caveat for terminal cost reporting and
repair the CPU measurement field in a future receipt schema; do not move this
exact R4 head or spend another capacity/freeze cycle.

Codex's independent exact-head safety audit found no load-bearing defect, and
13 anchored `-P -B` witnesses for durable-before-test publication, sealed
import/capacity/freeze bindings, worker completeness, byte parity, immediate
reconstruction, and recovery all pass. This is latency-hiding evidence for the
single consolidated review, not an execution marker or substitute for Claude's
final receipt/freeze authentication.

**No PT review is pending.** Claude's consolidated PASS for PR #160 exact head
`2394140bcdaebf72d81912a55ac18f5051848fe5` is canonical in
`HANDOFF_REVIEW.md` (2026-08-28 06:35 EDT). It authorizes only the single
non-retryable PT-Luna0 DEV run against the already-open PT-Sol0 population;
that run has not launched and its frozen public/private outputs remain absent.
The prior watcher waiting for this PASS is stale and may be closed. PT-Sol0's
result review is already complete and must not be repeated.

PT-Claude Opus r3 has sealed `INCOMPLETE` at 3/52 complete and 49/52
per-session timeouts, report SHA `a28dfbd…37e3b`. Preserve it as a budget
diagnostic; do not retry, pool its rows, or infer gameplay efficacy. R5 remains
paused until R4's verdict and curves are interpreted and is not reviewable now.

The exact import, clean repaired head, capacity receipt, and deterministic
freeze are now present together. The freeze uses
`source_review_commit == execution_git`, activating the existing
`consolidated-source-and-freeze` marker mode, so one external marker covers
the whole packet with no intermediate source review or user round trip.

Claude's `c578c36` prognosis is correct for the unchanged old Perf lane: it
would publish calibration and then hit the same old reopener failure. It is
already superseded by final replacement source
`56bd35f0c45080121d094f6906ab8d1053ca9e6b`: every
readiness/test/immediate-reconstruction/independent-reopen boundary forwards
the sealed legacy tensor-cache identity, the authenticated import is now
source-bound, and post-freeze gates avoid replaying an already deep-verified
receipt. The final two commits additionally use filename-backed tensor sharing
for the scoring-pool lifetime and a 16-party startup barrier, closing the real
Linux file-descriptor and partial-worker-start failures without changing score
semantics. Do not start a second diagnostic or alternate repair.

There is no current R4, R5, PT-Luna, or PT-Claude review request. The Luna0
PASS authorizes its one isolated DEV run but does not require launching it
while R4 is on the scientific critical path.

Do not create an intermediate R5 review. Do not treat a progress update as a
review request.

## Live fleet

| host | job | exact source | current state | authority |
|---|---|---|---|---|
| Mini | idle for reviewed PT-Luna0; PT-Claude Opus r3 sealed incomplete | Claude `a82adb9b7139b0490650ab7a55533e1fccaa3ab7`; Luna `2394140bcdaebf72d81912a55ac18f5051848fe5` | Opus r3 sealed `INCOMPLETE` 3/52; Luna source+launch PASS is canonical, but its public/private outputs remain absent and no Luna process is active | one isolated, non-retryable Luna0 DEV launch is authorized; do not pool Opus rows or infer efficacy from the incomplete report |
| Perf Cloud | R5 paused; prior R4 calibration sealed/inactive | preserved source `0ff18349c76b13e9f594e6d84fe9b34b04a91f04` | the disposable resumed diagnostic crossed the old FD ceiling and published calibration-selection artifacts, then was operator-stopped without a receipt on 2026-08-27 after the user requested a design pause. All prior rehearsal artifacts remain preserved; no R5 process is active. | no R5 design, source, rehearsal, freeze, review, or scientific action until R4 is complete and the design is discussed with the user |
| Strength Cloud | R4 sole scientific test + immediate reconstruction | calibration source `e10cb3d3426d758f2d757d41462aba6a06bc60c8`; repaired terminal `56bd35f0c45080121d094f6906ab8d1053ca9e6b` | readiness passed and was independently matched to 4 cohorts / 32 members; scientific invocation `f8069d7e…98d` started `12:23:19Z`, `Restart=no` | no duplicate/retry; only scientific success may launch the reviewed independent verifier |
| Air | none | — | idle | none |

No R5 process is running. Preserve its existing artifacts, but do not resume,
redesign, review, or launch R5 until R4 has a reproduced verdict and its curves
have been interpreted with the user.

The earlier PT-Claude r2 public report is
`/Users/jerryyu/Projects/shengji-ptcla0-a82adb9-r2.json`; its private evidence
root and monitor log remain beside it. All 37 incomplete records share the
same fail-closed reason. Inspection of the sealed process envelope—not hidden
gameplay outcomes—shows Claude returned `is_error: true` with the Fable 5
usage-limit message. This is an external quota stop, not a harness/game verdict.
The 15 completed rows are partial diagnostics only and must not be selected,
pooled, or promoted as a PT-Claude estimate.

The distinct Opus r3 attempt runs as PID `84270` with two workers and writes
only to `/Users/jerryyu/Projects/shengji-ptcla0-a82adb9-r3-opus*`. It is not a
retry or continuation of r2, and no r3 public result exists until all attempted
records are sealed. It had attempted 24/52 role records at 02:02 EDT; this is
operational telemetry, not completion or efficacy evidence.

## PT-Sol0 — complete and independently reviewed

- PR #155 received canonical PASS on remote main `69be1e2` for exact head
  `e73f970e` and frozen design SHA
  `31f0be8fa06ff65b73f90d633491b94816c1804364dd2a609e9fd99a4481a7e8`.
- The authorized 26-root / 52-role open-DEV execution completed all 52 role
  records with zero incomplete records in 16,684.81 seconds. The launch agent
  was unloaded after completion; its later respawns correctly refused the
  already-existing private root and did not alter the sealed report.
- Public output:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1.json`.
- Private evidence root:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1-private`.
- Monitor log:
  `/Users/jerryyu/Projects/shengji-ptsol0-e73f970-r1.log`.
- The exact Git/native/Python/Codex/design checks passed at launch. Two fresh
  ephemeral `gpt-5.6-sol` processes run at high reasoning in isolated temporary
  workspaces. The engine retains the real `Round`, legal ballot, rollout
  execution, budgets, and completion token.
- Public external SHA-256 is
  `adf01527e3577f12a71c95afefdc70fa414fa2b038e365b61992371d9dfac422`;
  internal report SHA-256 is
  `db4934cff3314e07848e2f6b8ab2831940588a9862e6af2aa6f544e4581bc965`.
- Parent files: C0
  `/Users/jerryyu/Projects/shengji-ptc0-2391bc4-r1.json` external
  `aada4737…8d60eda`, internal `b77e3fde…bdf8a3`; PT-Full
  `/Users/jerryyu/Projects/shengji-ptfull-c6e8d08-r1.json` external
  `1b404cf3…4468a3`, internal `93ad8e98…45449`.
- Codex's exact-source reopen passed canonical-byte, parent, record,
  work-accounting, and summary reconstruction. The unreviewed-but-reproduced
  mean signed-level contrasts are Sol minus A `+17/26` (+0.654), Sol minus B
  `+37/52` (+0.712), and Sol minus C0-S `+23/26` (+0.885). At the 26-root
  level those contrasts were positive/negative/zero on 21/1/4, 20/2/4, and
  20/3/3 roots respectively. Both banker-team and attacker-team means are
  positive in all three contrasts.
- This is strong mechanism evidence that a reasoning consumer can use perfect
  information better than the fixed production-search and C0-S consumers. It
  is still a small open-DEV diagnostic without a preregistered strength CI;
  it authorizes no deployment, gameplay integration, training, or strength
  claim. Never restart or substitute this attempt.

## R4 — optimized completion and one-shot cutover

### Current measurement

The serial Strength path finished and sealed all seven calibration-selection
artifacts at 11:23 EDT. At 11:56 EDT its wrapper failed during the mandatory
post-publication reconstruction because the legacy tensor-cache manifest
identity was not forwarded through a later reopen call. This was an
infrastructure wiring failure after calibration, not a calibration or model
failure. The serial test split was never opened.

The authenticated score-free import of `/opt/belief-r4-completion-v1-r3`
completed without opening test data and is now bound into exact source
`56bd35f0c45080121d094f6906ab8d1053ca9e6b`. Its imported-calibration
canonical bytes remain 1,226
bytes, SHA-256 `61d62ddb2229c8d6f6acd7eb4b630a96063b009248091be31def4790b29ac48e`;
the source copy is
`server/scripts/belief_v2_r4_terminal_parallel_import.v1.json`. The replacement
terminal uses 16 decision workers, pre-warms and identity-checks the complete
worker population before the durable test attempt, scores/reconstructs in
parallel with exact serial parity, and can recover a missing outer binding from
a sealed inner terminal without rescoring or changing the result. It also
reuses the deep import by strict byte binding instead of replaying all saved
epoch curves on every command; model populations are still independently
reopened for capacity, readiness, scoring, and reconstruction. The final
scoring-pool transport uses filename-backed tensors only during the pool
lifetime and requires all 16 workers to cross one startup barrier before work
begins. A real Linux two-cohort/16-member/16-worker bounded probe passed in
6.29 seconds with sharing restored afterward and no test opening or authority.
The exact-head full suite is green in pure mode (306 passed, 5 skipped) and
strict compiled mode (307 passed, 4 skipped).

The prior all-rank score-free capacity measurement ran on Strength under
`belief-r4-terminal-capacity-34ab86c-r1`, exact clean head `34ab86c`. The prior
exact `e099d14` attempt spent 2h41m deep-reopening the cohorts, then failed
before score timing or receipt publication when Python 3.14 could not pass all
model storage file descriptors into the 16-worker forkserver pool. The first
transport repair exposed a second fail-closed issue: the timing warm-up did not
prove all 16 workers had started. Both are repaired and witnessed at `34ab86c`;
the fresh service completed all 26 parity units at zero restarts. It measured
924 calibration decisions and exact serial/parallel result bytes: 3m55s with
16 workers versus 6m47s serial, a 1.728x speedup. The conservative maximum-test
wall projection fits the 48-hour cap with about 15.46 hours of headroom for the
scientific unit and 30.26 hours for the independent verifier. The subsequent
resource gate nevertheless refused because `_aggregate_peak_host_memory_bytes`
uses a parent-plus-per-worker RSS upper bound that exceeded 24 GiB; systemd's
actual whole-cgroup peak was 23,579,484,160 bytes. It published no capacity
receipt, so the zero-authority freeze watcher also stopped. No terminal/test
destination, attempt record, receipt, or freeze exists. Codex must repair and
remeasure this boundary before the single consolidated review request.

Exact repaired head `56bd35f` removes the invalid RSS multiplication, binds
`linux-cgroup-v2-memory.peak` in capacity schema v2, preserves the unchanged
24-GiB cap, and adds production-wiring over-cap refusal plus canonical forged
`test_split_opened`/selection-order witnesses. Both imported-test-state guards
were mutation-killed individually. Full belief validation is 511 passed / 6
skipped; strict changed surfaces are 53/53. The fresh service
`belief-r4-terminal-capacity-56bd35f-r1` and watcher
`belief-r4-terminal-freeze-watcher-56bd35f-r1` started at 22:13 EDT. The
capacity service exited successfully at zero restarts and atomically published
`/opt/belief-r4-terminal-capacity-56bd35f-r1.json` (5,444 canonical bytes,
mode `0400`, one link), SHA-256
`df51a8f9704298b3a7958d0daa8ee9b1cf220cb3cc140f682910072f07a6051e`.
The receipt records exact serial/parallel parity over all 13 ranks and 924
decisions, 16 workers, 6m37s serial versus 3m50s parallel (1.727x), and an
actual whole-cgroup peak of 21,056,126,976 bytes (19.61 GiB) under 24 GiB.
Its conservative projections are 11.86 hours per scoring pass, 31.68 hours for
the scientific unit, and 17.17 hours for the independent verifier; both plus
reserve fit the immutable 48-hour cap. Canonical-byte and projection arithmetic
were independently reproduced. Freeze, consolidated review, initialization,
and score-free readiness are complete. The sole scientific unit is active; no
new review is requested before its result.

The older Perf lane is inactive and preserved only as superseded diagnostic
evidence. It is not a fallback execution path and must not be resumed while
the repaired Strength scientific unit runs.

**Counter interpretation:** `score-r4-calibration-populations: 1/6` is a
heterogeneous milestone counter: synthetic REF0, synthetic REF1, human REF0,
human REF1, statistic derivation, and publication. It is not six equal
1,326-round populations. Do not project 6 × the first synthetic pass or quote
the resulting 88–101 hour estimate. The later human/finalization wall remains
unmeasured; preserve the live lane and use actual phase telemetry.

### Replacement operator sequence

1. **Complete:** exact repaired source, imported calibration, 13-rank capacity
   receipt, freeze, consolidated PASS, initialization, and score-free
   readiness.
2. **Active:** the one reviewed scientific unit opens the sole test population,
   scores it, seals the terminal, and immediately reconstructs it. Never launch
   a duplicate or retry.
3. **Pending only on scientific success:** run the separate reviewed verifier,
   compare exact terminal bytes/verdict, and then interpret the result in plain
   English. A scientific failure permits diagnosis only, not a second opening.

The prior PR #152 cutover sequence is superseded for execution by this fresh
packet; its test authority must not be reused. Do not open test early, retry a
one-shot step, or infer an R4 answer from calibration output.

## R5 — paused pending post-R4 design discussion

- Exact pushed repair source:
  `0ff18349c76b13e9f594e6d84fe9b34b04a91f04`.
- No PR/freeze/review/scientific run is active for this exact packet. The prior
  clean 104-round rehearsal at `4521bac` completed capture, cache, references,
  device qualification, and all four 30-epoch cohorts in 26m40s, then failed
  at calibration startup because Python's forkserver tried to transfer too many
  tensor file descriptors. No terminal/test authority or scientific evidence
  was consumed.
- `0ff1834` switches only the scoring-pool transport to filename-backed tensor
  sharing, restores the process-global sharing setting on exit, and requires
  an exact 16-party startup barrier. Focused tests are 13/13; exact-head pure is
  513 passed / 6 skipped and strict compiled is 515 passed / 4 skipped.
- A development-only resume diagnostic started all 16 scoring workers past the
  exact old failure and published calibration-selection artifacts. The user
  then paused R5; Codex stopped the diagnostic before terminal completion. It
  produced no receipt and remains ineligible for any freeze. All reusable DEV
  rehearsal artifacts are preserved.
- When the packet is complete, its single stacked PR targets the last
  independently PASSed R5 source/freeze, PR #147 head
  `2d4dfe84280d7c1cb433b000aa18670bf4abfdd1`. PR #148 head `232fc27` was
  explicitly HOLDed and is part of the new review surface. The consolidated
  delta is the complete stack from `2d4dfe8` through `4521bac`, not the
  entire historical R5 stack or current `main`.
- The underlying exact-head local validation remains green. The runtime delta
  adds bounded Python-3.12-compatible decision submission, parallel
  calibration/terminal statistics, fine-grained outcome-blind scoring
  progress, and a foreign-venv import-root refusal; it changes no model,
  population, gate, or authority.
  The final test-only commit adds a can-fail production-wiring witness for the
  exact cache-manifest identity omitted by serial R4: neutralizing that
  argument makes the named test fail, while the complete controller file is
  39/39 green in both modes. It requests no intermediate review.
- The final source-bound supervisor repair preserves one 72-hour absolute
  same-boot deadline across process resume. It verifies the freeze's live boot,
  records the original start/cap/hard deadline, checks before every task and
  before completion, kills active children on expiry, refuses an expired
  resume before its receipt, and cannot reset through a fresh wrapper. Three
  anchored mutations—resume-expiry, per-launch and completion-seal—each turn
  their named witness red.
- The exact source retains the full objective surface: all 13 trump ranks,
  frozen real-human H0 splits and a capped human-mixture arm, persisted
  per-epoch curves, exact cache/optimizer resume, graceful deadline
  truncation, durable calibration readiness, and a single test opening only
  after all saved curves and workers reopen. The remaining uncertainty is
  host execution evidence, not a missing source feature.
- The terminal answer is already closed: PASS requires at least 0.5% relative
  Brier improvement over REF-C, a positive paired-round 95% lower bound,
  positive means in at least 6/8 members, no log-loss sign reversal, no
  simultaneous material regression in any of 13 rank strata, and a clean
  permuted-label control. Anything else routes mechanically to a named null or
  refusal; human transfer remains separately reported rather than pooled.
- Host-independent inputs are sealed under
  `/private/tmp/shengji-r5-4521bac-freeze-inputs-local`: exact-head seed scan
  `abb35184…f9e094`, seed registry `666f0b79…94d09`, and byte-identical H0
  inventory/split, authenticated V1 resource-failure receipt, and named
  re-entry rationale. The refreshed registry has 5,573 candidates, zero V2
  collisions, and the unchanged population-table SHA `43ebd6ba…32004`.
  Do not regenerate these solely because host evidence is pending. Do not use
  the obsolete project-level `belief-v2-h0-inventory-v1`.
- Do not resume the diagnostic, run the fresh zero-resume rehearsal, change the
  design, create the R5 PR/freeze, or request review until R4 is complete and
  the user has discussed the remaining R5 design.
- The prior corrected cap rationale is only a template until those fresh
  receipts bind it: 64 GiB total training artifacts, 30 GiB aggregate host
  memory, zero swap, 48 hours training wall, and CPU execution on this
  accelerator-free Perf host. Capture core-hours remain mechanically derived
  from the fresh 416-round preflight and may not be moved to fit a projection.
- Request exactly one consolidated review binding source, rehearsal identity,
  runtime/device identity, freeze, caps, registry, and all-false authority map.
  Do not split this into intermediate approvals.

## Closed results that must not be repeated

- PT-Full and PT/C0 source/result evidence are complete and serve only as
  immutable parents for PT-Sol0.
- C0 terminal verdict: **SELECT NONE**. C0-S was least bad, but no C0 arm had a
  positive mean against both PT-Full A and B. Bare-point avoidance did not
  transport into positive whole-round value.
- PR #153 canonical reopen repair is PASSed and spent for interpretation; no
  rerun is authorized.
- No completed PT result authorizes BELIEF integration, production behavior,
  promotion, deployment, or a strength claim.

## Immediate operator priorities

1. Monitor the active R4 scientific unit and its explicit progress telemetry;
   do not launch a duplicate, retry, or alternate scorer.
2. On scientific success only, launch the already-reviewed independent
   verifier and compare exact terminal bytes and verdict.
3. Keep R5 paused. PT-Luna0 is reviewed and runnable on idle Mini, but it must
   remain isolated and must not distract from R4 terminal interpretation.
