# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical reviews
> belong in `HANDOFF_REVIEW.md` and Git history. A request not listed here is
> not active.

Last reconciled: 2026-08-24 15:55 EDT.

## Immediate objective

Carry live BELIEF R4 and one efficient, recoverable R5 successor to sealed,
independently reopened terminal results. Determine whether public-history
ownership learning improves held-out hidden-hand calibration over REF-C, then
decide separately whether belief should enter gameplay search. Neither lane
authorizes a sampler, gameplay or strength claim, promotion, deployment or
merge. R4 and R5 share one preregistered population and are not independent
scientific replications.

## Live scientific R4

| field | current binding |
|---|---|
| source | draft PR #123, exact head `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| execution review | PASS marker commit `10bd1dab39ee900a7c4650aba06de28ac62587ce` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host / unit | `shengji-cloud`; `belief-v2-r4-d2d466f-r1.service`, `Restart=no` |
| evidence / ops | `/opt/belief-r4-evidence-d2d466f-r1`; `/opt/belief-r4-ops-d2d466f-r1` |

R4 is active and untouched: stage 7/10 `training`, 79/85 supervisor tasks
reconciled, task-weighted progress 96.17%, the primary and human full-data
workers active, and the hard-geometry control plus 50%-scale workers complete,
`NRestarts=0`, no failure task, no terminal and no
test opening. Exact schedule progress is:

- synthetic primary 103,300/118,800 = 86.95%;
- hard-geometry label control reports protocol completion;
- human mixture 105,099/119,040 = 88.28%;
- synthetic 50%-scale 30/30 epochs = 100%.

All 832x16 synthetic captures, 30 human-capture tasks, 12,003 input-index
units, 12,649 cache units, device qualification and 29 reference tasks sealed
and independently reopened before training. Full-data cohorts have durable
epoch journals/resume states; progress remains outcome-blind. Frozen training
cap is 256 device-hours / 172,800 seconds. Graceful truncation may seal the
best common epoch at the deadline but must not be described as convergence.
Human test evidence is descriptive only at exact n=51.
At the 15:55 EDT progress sample, the hard-geometry control worker had emitted
its outcome-blind completion event; its curve and selection reason remain
sealed. Primary and human respectively reported 86.95% and 88.28%, projecting
roughly 4.9 and 4.4 hours remaining and leaving ample margin inside the frozen
48-hour training cap. No curve value or test/outcome field was opened to make
that operational estimate. Terminal review must classify each cohort as
patience-stopped, full-epoch-complete or deadline-truncated from sealed evidence
rather than treating worker completion as proof of convergence.

R4 itself is a transient systemd unit, so its host-level success/restart/OOM
and peak-memory fields would otherwise disappear immediately after completion.
The metadata-only unit `belief-r4-systemd-evidence-keeper-d2d466f-r1.service`
now holds a D-Bus reference using the same exact `638cae4a…5da8` script as the
independently tested v7 keeper. It neither signals nor changes R4 and opens no
artifact; its only purpose is to retain completed systemd properties for the
terminal review.

## Spent R5 admission

Source `8d9390e12535bbf0d235b76e81484f54f912cc86`, admission
`4e95d87b2c2ffdec99ac1c0fdb5111e176c2389d5f83384fb2af21f2d25bf756`
and root `/opt/belief-r5-evidence-8d9390e-r2` are preserved. Failed freeze SHA
is `dc7e3a96ad4624144a2d35fa4c6fcb0e4ff5e539efa45a7b87023ca0a7030a95`;
the sealed eight-worker input-index SHA is
`189334f9ecf14d71abfeae91d1fcda73f2f4e39658e9a93d6600ab2511757c83`.
The tensor-cache stage then completed every
non-test batch but measured 30,452,371,456 bytes against the frozen
25,769,803,776-byte cap and refused before publishing. The service failed once
with `NRestarts=0`; no model, reference, calibration, test or terminal artifact
exists, no test byte opened and this admission may never be retried. Its five
partial component caches and tombstone remain immutable evidence.

## R5 score-free lineage and next exact proof

Draft PR #131 is the sole successor source lane, stacked on reviewed tip
`9a057dfa07d84dda1672d4895bb0db553182a6ad`. Exact current head
`8221eec405b3bfa58fc30918838e1780eea4e2b9` is pushed and clean; server and
frontend CI both pass. It keeps the 24-GiB cap, derives topology `8 aggregate = 1
cache build x 8 workers`, durably records cap refusal and forbids
same-admission resume. The
primary worker now emits the deterministic hard-geometry control labels from
the same in-memory natural batch that writes the primary actor tensors. This
removes the later 9.4-GiB actor-cache reread without changing any output bytes,
model input, label, population, gate or authority. The newest six-file delta
adds an explicit one-build barrier and primary-first order: the shared
primary+control pass finishes before human, scale or calibration readers open.
This directly repairs the measured cgroup file-cache contention; process
parallelism remains eight workers inside the active build. The in-pass control
overlay is unchanged.
Complete BELIEF suites pass 455 with six skips pure and 457 with four skips
strict-compiled at exact head `8221eec`; the focused changed wiring passes 4/4.
Tests pin topology 1x8, primary-first population, the production executor width
of one on fresh and resumed paths, and the preflight's identical order. An
isolated exact-head mutation sweep killed all three corresponding regressions:
restoring 2x4, restoring primary-last, and hard-wiring executor width two each
turned the named focused witnesses red; the clean exact head returned 4/4.
Claude's exact `BELIEF_R5_CACHE_SERIAL_SOURCE_V1_REVIEW` marker authorized one
v8 proof only. Unit `belief-r5-cache-capacity-8221eec-v8.service`, invocation
`15dae1729a65413b81ce174f796eda28`, ran naturally from 03:51:30 to 07:51:30
EDT and terminalized `failed/timeout`, `ExecMainStatus=15`, `NRestarts=0` at its
exact four-hour `RuntimeMax`. It consumed 5h01m54.835s CPU, reached the exact
25,769,803,776-byte memory ceiling, and recorded `OOMKills=0`,
`ManagedOOMKills=0`, zero swap and no restart. The receipt
`/opt/belief-r5-cache-capacity-8221eec-v8.json` is absent. Scratch contains
only two unsealed partial directories: 2,130 direct files (1,065 actor/label
pairs; 3,009,765,823 bytes) and 1,065 matching control-overlay files
(459,587,885 bytes). The last emitted progress was 1,005/9,128 direct = 11.01%
and 1,000/3,521 overlay = 28.40%. No sealed cache, later reader, manifest,
model, checkpoint, training, test, result or terminal path exists. This is a
clean score-free deadline failure, not a capacity pass or scientific result.
Metadata-only unit
`belief-r5-v8-systemd-evidence-keeper-b016780-r6.service`, invocation
`c4a128bddd8b4de5becccc83b84e2f86`, now holds a three-hour D-Bus reference to
the failed unit using the previously dummy-tested script SHA-256
`638cae4a53cff068b573fc46fa736cdd3e2041ccd9284b1122fd2105c7d05da8`.
It neither signals the target nor reads project/cache bytes and exists only to
keep the exact terminal properties live through the hourly review.

The terminal evidence is now closed independently of the transient unit at
`/opt/belief-r5-v8-terminal-evidence-8221eec-v8`. Its seven-file population is
root-owned, mode-closed and manifest-bound: manifest SHA-256
`43a4a95b52e7e12c8d409fbfdbaa60d525220fce7cfb9c72952396e04ce97d46`,
packet SHA-256
`8141c5854ad10efb37657e7ba4a0bbb6db3b36d30bb62d332dc8e97d9291c6ed`,
partial-inventory SHA-256
`962f8985cf817d54e138c3a7927b1867a00fcd7eca426ecffce9b9390caa1b55`
and source-checkout binding SHA-256
`e32cfc30d028b98e43bc8dbc6168b28d05e95386ab4a3347f8e3f55d2301ef8e`.
The inventory binds and independently rehashed all 3,195 partial files and
3,469,353,708 payload bytes. The packet verdict is
`REFUSE_CAPACITY_TIMEOUT_NO_RECEIPT`; every execution, reuse, retry, freeze,
test, merge, strength and deployment authority is false.

The terminal file timestamps make the new bottleneck precise without
attaching to or altering v8: 131 inter-batch pauses longer than 90 seconds
consumed 13,167.451 of the 13,303.838-second file-production span (98.97%);
median non-stall gap was 0.106 seconds and maximum pause was 103.225 seconds.
During sampled pauses all eight children were idle while the parent used one
CPU. This is strong evidence consistent with automatic cyclic-GC rescans of
the roughly 1.6-GiB immutable index/schedule graph, but only the next proof may
establish realized speed and memory safety.

Draft stacked PR #138 is prepared at exact head
`b016780d3d84b9a33233ea63b9b09b009f75469d` over exact parent `8221eec`. Its
two-file delta suspends automatic cyclic GC only around the bounded
ProcessPool parent reduction and restores the caller state on success and
failure; reference counting, output bytes, topology, order, deadlines, caps
and authorities are unchanged. Focused tests pass 13/13, full BELIEF passes
456+6 skips pure and 458+4 skips strict-compiled, and neutralizing the
suspension turns the named production-wiring witness red. The already-disabled
caller branch is pinned; server/frontend CI are green; `git diff --check`
passes. Exact file hashes are `47f7b2fa…2836` for
`belief_v2_parallel_cache.py` and `74f7e965…c57f` for its test.

The reviewed v9 full-build proof at exact source
`b016780d3d84b9a33233ea63b9b09b009f75469d` terminalized at its exact
13:50:57 EDT four-hour cutoff. Unit
`belief-r5-cache-capacity-b016780-v9.service`, invocation
`f9f5785f90ed48ab881097589a55bf00`, reports `Result=timeout`, zero restarts,
zero OOM kills, zero swap, 18,247,347,324,000 CPU nanoseconds and a memory peak
exactly equal to its 24-GiB cap. No capacity receipt exists. The durable
partial population reached 1,114/9,128 direct actor/label batches and
1,114/3,521 control-overlay batches before cutoff.

The failure evidence is closed at
`/opt/belief-r5-v9-terminal-evidence-b016780-v9`: its manifest SHA-256 is
`968c321e07a2ec942c97dac26dc594c2235df9ceff116ab815aa296325a8eaec`
and packet SHA-256 is
`0f33b574f4c5878d2966e14dd0d6254e7663747cef8aedbb67336cfb8c39369d`.
An independent second pass reopened the canonical seven-file population,
rehashed all 3,342 partial files / 3,628,382,648 bytes, rebound the exact clean
source/native files and reproduced verdict
`REFUSE_CAPACITY_TIMEOUT_NO_RECEIPT`. Every partial-reuse, retry, capacity-pass,
scientific, test, merge, strength and deployment authority is false. The v9
partials are evidence only; do not reuse them. The binding stop rule forbids
v10 or another full-build attempt.

Three outcome-blind `pidstat` samples before cutoff consistently found the
outer build thread consuming one CPU while all eight spawned workers slept;
the last sample was about 86.8% user / 13.2% system with 0.2% wait. Combined
with the timeout and exact memory-cap contact, this localizes the next question
to serial parent work and peak-memory accounting but does not identify a Python
phase. The bounded phase profiler below is now the only permitted next R5
diagnostic.

Draft PR #143 is pushed and clean at exact head
`50f2a88f8f6d95594bd8d92fa6546f0613915f15` on branch
`codex/belief-r5-bounded-parent-profile`, stacked directly on reviewed v9 head
`b016780d3d84b9a33233ea63b9b09b009f75469d`. Its complete four-file delta adds an outcome-free phase observer
and a minutes-scale diagnostic that selects 64 evenly spaced batches from the
authenticated primary train schedule, builds the exact primary actor-cache
plus control-overlay path with the same eight-worker parent, and records
wall/caller-thread/whole-parent-process CPU
time for executor creation, submission, waiting, result transfer, canonical
emission, shutdown and seal. The parent-process clock covers the executor's
internal result-management thread, so the sample can distinguish its CPU from
both the waiting caller and the separate worker-process aggregate.
Every completed phase and the exact sampled-population identity are also
written immediately as canonical, outcome-free systemd-journal lines, so an
external cutoff preserves useful attribution evidence instead of turning the
diagnostic into another all-or-nothing run.
It independently reopens every sampled actor and control-overlay byte and
publishes explicit false authority,
`quantile_sample_is_not_full_capacity_evidence=true`, and zero calibration,
test or outcome access. Production cache bytes and calls are unchanged unless
the separate profiled entry point is invoked. Its exact wiring, byte-parity,
population and tamper battery now passes 22/22; the production-code head's full BELIEF
batteries pass 463 with six skips pure and 465 with four skips strict compiled,
both CI jobs are green and `git diff --check` passes. The CLI also
refuses `PYTHONPATH`, dirty source and importable bytecode/shadows before
loading Shengji code; a subprocess witness proves the actual CLI invokes that
gate before project imports, and aggregate CPU accounting has its own
failing-direction witness. A final same-altitude prelaunch probe found and
closed a real defect before packet seal: a fresh CLI had not configured Torch's
deterministic one-thread runtime before comparing it with the failed freeze and
would have refused immediately. Exact production head `b47ed10` configures first, and
removing that call turns the new CLI-level wiring witness red. Exact file
SHA-256 values are `34195d7d…ce63` for the profiler, `924f65b2…3859` for the
parallel cache, `22e7ccbd…3ee` for the profiler test and
`70d718a1…981f` for the parallel-cache test.

Claude's first review at `b47ed10` returned HOLD only because the final direct
and overlay reopen comparisons had no same-altitude witness. Repaired head
`50f2a88` changes exactly that one test file by +42/-0; production source is
byte-identical. A parametrized `run()` witness now injects a mismatched direct
receipt and a mismatched overlay receipt and requires the exact refusal from
each comparison. Neutralizing either comparison makes only its corresponding
case red; clean focused result is 22/22 and both CI jobs pass. The narrow
re-review must adjudicate this named blocker only, not repeat the source audit.

The repaired immutable bounded launch packet is sealed on Perf Cloud at
`/opt/belief-r5-parent-profile-freeze-50f2a88-v2`: source manifest
`a5187c40fd944ff988556425ef38f67bdb4a77f91df938e9fbe6db965557e264`
(157 files), live runtime
`812b11b394b19fba7ef8207500fd959e99cf6efbd611e7b619879b00878cbc21`,
launch `ee021c3cb89fbb713d1a5fcee60aadffa00d678c9710eee93d3b28dd595674ed`,
packet `f983d4c063365c76193e1e14577f0297898a6c36f97e24ee0fc6eba0eacbf426`
and manifest
`4531473320f7f833850fa3009b8c775fb730038186ecf19f27bbd2c21fc49540`.
The exact root-owned checkout is `/opt/belief-r5-50f2a88`; runtime equals the
failed freeze byte-for-byte, including boot/native/Python/packages. The packet
binds 64 batches, eight workers, 30 minutes, 24 GiB, zero swap and `Restart=no`.
An independent reopen verified all five packet files and 157 source rows.
The unit is not loaded, scratch/receipt are absent and every authority is false.
The prior `b47ed10-v1` packet remains immutable but is superseded and must not run.
V9 produced no receipt, so this is the single bounded diagnostic required by
the stop rule: review source+launch once, then run it instead of v10.

Superseded v5--v7 diagnostics and the failed detached prep queue are preserved
on Perf Cloud and recorded in `HANDOFF_REVIEW.md`. Collectively they established
actor-cache eviction under concurrent readers, eliminated label transformation
as the primary cost, and motivated the reviewed 1x8 serialization. None sealed
a capacity receipt or created a scientific namespace, and none has retry,
freeze, model, test, outcome, gameplay, merge, strength or deployment
authority. Do not reuse their partial scratch or prep queue.

## Separate proposal state — no compute authority

- PR #130 exact head `943bc5834494cb7ae698d063b25585b6c584d090`
  passed substantive code review: its flag remains off, the equal-trump
  lower-point-risk route works, a `+1` trump increment remains guarded and the
  killing mutation fails. It is not literally stacked on the PR #127/#129
  proposal chain; reconcile ancestry with current main and freeze round-level
  utility/dose telemetry before any experiment decision. No run or adoption is
  authorized.
- Draft PR #135 exact pushed head
  `62b157dd25a8fe6644962de231fd78f501ba7fae` is the isolated PT0
  perfect-teacher foundation. The prior resume and two-world blockers remain
  repaired. The newest exact two-file delta closes the final compatible-world
  provenance HOLD: every exact `Round` now derives a canonical actor-visible
  fingerprint covering actor hand, public history, turn, banker, trump,
  points and actor-visible burial while excluding true other hands and a
  non-banker actor's burial. Exact value rows and checkpoints carry that hash,
  and both the miniature runner and information-set reducer refuse mismatches.
  Same-altitude witnesses prove hidden twins pass while public points drift
  refuses, and a value row with a different public-state hash refuses before
  aggregation. The newest test-only +48/−0 delta pins the privacy partition
  per component: opponent-hand, non-banker burial and deck-order changes leave
  the hash identical; own-hand, public-points and banker-visible-burial changes
  alter it. Claude's exact always-expose-burial mutation now turns the named
  test red. Codex reproduced 65/65 over PT0/native-round/fast-parity/game in
  pure mode and 65/65 with strict compiled/native flags; `git diff --check`
  passes. Claude's repaired-head review is now **PASS** at ledger `7cfef47`;
  the prior HOLD is closed and this foundation must not be re-reviewed. It
  still has no training, gameplay, fleet, scientific run, merge, strength or
  deployment authority and does not compete with R4/R5.

Draft stacked PR #142 is pushed and clean at exact head
`3f27ddbc38350ccffba53df15a66e410aa6a6765` over PR #135. Its exact newest
five-file repair changes proposal and evaluation to independently seeded
posterior draws **with replacement**. Every draw has a unique,
cohort-separated draw identity; repeated underlying worlds and cross-cohort
underlying overlap are valid and publish only as counts. This preserves
posterior frequency on small-support information sets instead of distorting it
through deduplication. The focused battery passes 29/29, the broader PT/endgame
battery passes 89 with two skips pure and 91/91 strict compiled,
`git diff --check` passes and both PR CI jobs are green. Claude's consolidated
review at ledger `b435e03` returned HOLD on exactly two missing same-altitude
witnesses: cohort public-fingerprint mismatch and proposal/evaluation draw-ID
overlap. A local uncommitted test-only repair now adds those two witnesses.
Neutralizing the public-fingerprint comparison makes only its named test red;
restoring it and neutralizing the draw-ID overlap comparison makes only that
named test red. The clean PT0 battery is 53/53 and `git diff --check` passes.
The broader PT0/endgame/native-parity/game battery is 109/109 in both pure
and strict compiled modes.
No production source changed. This repair still needs an authorized exact
commit/push, fresh CI, and regenerated clean-head capacity/freeze artifacts
before one narrow re-review; do not review the local bytes or old freeze.

The prior clean-head bounded Mini capacity sample completed all four records at
16 proposal plus 16 evaluation draws/state in 7.04 seconds wall, with zero
swaps, 110,608,384-byte maximum RSS and an independent byte-equal reopen. The
formerly binding state validly reported 11/16 and 10/16 unique underlying
worlds with six cross-cohort overlaps. The closed capacity root is
`/private/tmp/shengji-pt0-natural-capacity-3f27ddb-c1`; receipt SHA-256 is
`190c48b42f87fb1122dd5435cb9d2523a848c6938cf65e2b1ad3d3e9f2f158bd`
and manifest SHA-256 is
`b251ff98611a41e65851c0e1d7edc5f2669468512f9fd3cdcf363aaa7b23fa4e`.
It is capacity-only, uses a distinct secret and has all authority false. It is
preserved as evidence but will be superseded when the test-only repair gets an
exact committed source head; do not use it to launch.

The prior immutable 104-state freeze is sealed at
`/private/tmp/shengji-pt0-natural-freeze-3f27ddb-r1`. Its design SHA-256 is
`2ff49b3a47463079fb7e5733bb3dbc633949f5d6538e68bad0207668c148ccc7`,
source-manifest SHA-256 is
`53ee55df9cdef82fd87ef0f86bda1b02e30b0bf056ec6d68f312572f9a5d3775`,
freeze SHA-256 is
`46c1191a4d8c5c502e236cdc8296ff31a7f1e829a09bea2782f6b863c91372bd`
and freeze-manifest SHA-256 is
`0d21d24c4cde7a109195b8ac3f7cbb623179ba5c7cd9a6a88fc101152ad59216`.
The freeze independently binds 144 source/native files, exact Python/native/
boot/Mini identity, the 13-rank x 2-banker x 2-role x 2-horizon grid, 16+16
with-replacement draws, four baseline seeds, a 30-minute graceful deadline,
4-GiB launchd RSS cap, no automatic restart, no manual resume and every
execution/merge/gameplay/strength/deployment authority false. The launchd job
is not loaded, the ops directory is empty and scientific run/output namespaces
do not exist. It remains unopened and immutable but must be regenerated at the
repaired exact source head; it has no execution authority.

## Review queue — one active review, one locally repaired HOLD

### PT0 natural-state source + freeze — not yet reviewable

PR #135's repaired foundation remains PASS at ledger `7cfef47`; never repeat
that review. PR #142 head `3f27ddb` received HOLD at ledger `b435e03`; never
issue a PASS against its old capacity/freeze packet. The two requested
failing-direction witnesses are locally implemented and proven, but no review
is requested until the exact test-only repair is committed/pushed, CI passes,
and a new clean-head Mini capacity receipt plus 104-state freeze are sealed.
At that point request exactly one narrow HOLD re-review covering the two tests,
new source manifest and replacement capacity/freeze hashes. All execution,
merge, training, gameplay, strength and deployment authority remains false.

### R5 bounded parent profiler HOLD repair + launch

**This is a narrow re-review of one named witness blocker, not a v9 or broad
source re-review.** PR #138 source and
the v8 lineage are already PASS at ledger commit `780413e0`; V9 is closed
`REFUSE_CAPACITY_TIMEOUT_NO_RECEIPT`. Do not inspect or interpret its partial
cache contents and do not authorize v10. Claude's first PR #143 review at exact
head `b47ed10e…e1a0` verified the complete four-file source/launch surface and
returned HOLD only because the direct and overlay reopen comparisons lacked a
witness. Review exact repaired head
`50f2a88f8f6d95594bd8d92fa6546f0613915f15`, whose only delta from that HOLD
head is `server/tests/test_belief_v2_cache_parent_profile.py` +42/-0, together
with immutable Perf packet `/opt/belief-r5-parent-profile-freeze-50f2a88-v2`.

Verify the new parametrized witness drives the real `run()` path with a
mismatched direct-cache receipt and mismatched overlay receipt, and that each
case fails under exactly its corresponding comparison neutralization. Reopen
all five repaired packet files and 157 source rows; confirm production profiler
and parallel-cache hashes remain `34195d7d…ce63` and `924f65b2…3859`, runtime
remains `812b11b3…bc21`, the unit is absent, scratch/receipt are absent, and
every packet authority remains false.

If clean, append one
`BELIEF_R5_BOUNDED_PARENT_PROFILE_SOURCE_LAUNCH_V1_REVIEW` PASS marker bound to
source `50f2a88f…1f15`, source manifest `a5187c40…e264`, runtime
`812b11b3…bc21`, launch `ee021c3c…74ed`, packet `f983d4c0…f426` and manifest
`45314733…9540`. That marker may authorize exactly one minutes-scale,
score-free profiler execution only. It grants no full-capacity claim,
scientific/retry/partial-reuse/test/training/gameplay/merge/strength/deployment
authority. Do not request another source review unless reviewed bytes change.
R4 terminal review remains separate and starts only after its terminal seals.

A narrow R4-only terminal audit repair is prepared locally at exact commit
`51cf7c3` on branch `codex/belief-r4-terminal-rescore-audit`, based directly on
the live R4 source `d2d466f`. It changes only the terminal reopener and its
test: independent reopening regenerates both synthetic and human test score
populations from the frozen sources/checkpoints and requires byte-equal
agreement with the persisted populations. A coordinated persisted-score plus
manifest rewrite fails the repaired reopener; neutralizing the comparison
makes that exact witness red. Focused terminal tests pass 13/13 and the exact
clean branch now passes the complete strict-compiled BELIEF battery 437 with
one skip; `git diff --check` passes. This branch is intentionally unpushed and
requests no review yet; fold it into the one R4 terminal/reproducibility review
after the live terminal seals.

After each scientific run seals, one terminal/reproducibility review must
independently replay raw score populations and statistics, distinguish
truncation from convergence, preserve human n=51 as descriptive only and
remember R4/R5 are not independent replications.

## Monitoring contract

- Read each scientific run from its exact ops `status.json` and systemd unit.
- Report task-weighted percent, stage, completed/total tasks, active workers,
  elapsed time and deadline headroom. Progress is outcome-blind, not evidence.
- On failure, preserve artifacts/logs and do not retry.
- On completion, do not interpret or promote before the reviewed terminal
  reopener and independent review pass.

## Next operator sequence

1. Monitor R4 without changing it; preserve the spent R5 root.
2. Commit/push the local two-test PT0 HOLD repair only with explicit authority,
   then regenerate its clean-head Mini capacity receipt and 104-state freeze.
3. Obtain one narrow PT0 repaired-head+replacement-freeze PASS, then launch
   that score-free 104-state packet exactly once; do not merge first.
4. Obtain the narrow PR #143 HOLD re-review at exact head `50f2a88`, then
   run the frozen 64-batch profiler exactly once instead of v10.
5. Use the profiler result to design the next R5 cache-capacity proof; no
   scientific R5 launch until a fresh capacity receipt and consolidated freeze
   PASS exist.
6. Independently reopen each scientific terminal, then decide whether belief advances to
   gameplay-search design or closes/revises. Merge remains a separate choice.
