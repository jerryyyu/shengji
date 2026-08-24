# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical reviews
> belong in `HANDOFF_REVIEW.md` and Git history. A request not listed here is
> not active.

Last reconciled: 2026-08-24 07:54 EDT.

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

R4 is active and untouched: stage 7/10 `training`, 79/85 tasks complete,
task-weighted progress 95.25%, three full-data cohort workers active and the
50%-scale cohort complete, `NRestarts=0`, no failure task, no terminal and no
test opening. Exact schedule progress is:

- synthetic primary 77,606/118,800 = 65.32%;
- hard-geometry label control 77,371/118,800 = 65.12%;
- human mixture 78,669/119,040 = 66.08%;
- synthetic 50%-scale 30/30 epochs = 100%.

All 832x16 synthetic captures, 30 human-capture tasks, 12,003 input-index
units, 12,649 cache units, device qualification and 29 reference tasks sealed
and independently reopened before training. Full-data cohorts have durable
epoch journals/resume states; progress remains outcome-blind. Frozen training
cap is 256 device-hours / 172,800 seconds. Graceful truncation may seal the
best common epoch at the deadline but must not be described as convergence.
Human test evidence is descriptive only at exact n=51.
The three full cohorts have sealed epoch 17. At the 07:53 EDT progress sample,
training elapsed was about 24.7 hours and each worker projected 12.7--13.2
hours remaining, leaving roughly ten hours of margin inside the frozen 48-hour
training cap. No curve value or test/outcome field was opened to make that
operational estimate.

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

The prospective v9 checkout is root-owned, detached, clean and bytecode-free
at `/opt/belief-r5-b016780`. Safe-flag imports resolve the package and changed
parallel-cache module inside that exact checkout; the preflight entry point is
`/opt/belief-r5-b016780/server/scripts/belief_v2_cache_capacity_preflight.py`
with unchanged SHA-256 `bf355ce4…d7f8`, and the single imported native
extension remains root-owned mode 0755 SHA-256 `ca75df4c…4ff`. Nothing has
launched from this checkout. The review queue below asks once for both this
exact source and one fresh score-free proof; there is no separate rehearsal or
automatic prep queue.

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
- Draft PR #135 exact head
  `ff85ab441c97f4b78ce6a7c46f374522e0f90f1e` is the isolated PT0
  perfect-teacher foundation. Its exact two-file surface adds one module and
  one test file: exact small-endgame action values, named continuations,
  actor-legal targets averaged over compatible hidden worlds, rotation
  witnesses and a pure miniature receipt/recovery runner. Focused pure tests
  pass 43 with two intentional skips; strict-compiled passes all 45. The exact
  named battery is `test_privileged_teacher_pt0.py`,
  `test_s3b_endgame_challenge.py` and `test_s3b_endgame_strength.py`; Codex
  reproduced 43+2 pure and 45 strict-compiled after Claude noted the command
  had not been named. The earlier source PASS at `3d3a548` is superseded by
  the later canonical HOLD at `1c03150`: a re-canonicalized forged completed
  world is accepted on resume, and deleting the minimum compatible-world guard
  leaves its named slice green. PT0 needs input/evaluation binding or prefix
  recomputation plus both killing witnesses before any recovery or execution
  review. It has no training, gameplay, fleet, scientific run, merge, strength
  or deployment authority and does not compete with R4/R5.

## Review queue — one consolidated PR #138 source + v9 proof ask

Top priority. Independently review draft PR #138 exact head
`b016780d3d84b9a33233ea63b9b09b009f75469d`, parent
`8221eec405b3bfa58fc30918838e1780eea4e2b9`. This is one review boundary, not
two rounds. Verify the exact two-file delta, the 13 focused tests, complete
456+6 pure / 458+4 strict-compiled evidence, green CI, clean diff and the
killing GC-state wiring witness. Confirm that automatic cyclic GC is suspended
only in the parent ProcessPool reduction, the prior caller state is restored
on success, worker failure and already-disabled entry, spawned children remain
unchanged, and output bytes/topology/order/deadlines/caps/authorities do not
change.

Bind the complete predecessor evidence: reviewed v8 unit
`belief-r5-cache-capacity-8221eec-v8.service`, invocation
`15dae1729a65413b81ce174f796eda28`, exact 03:51:30--07:51:30 EDT four-hour
wall, `Result=timeout`, `ExecMainStatus=15`, `NRestarts=0`, exact
25,769,803,776-byte `MemoryPeak`/`MemoryMax`, zero swap, `OOMKills=0`,
`ManagedOOMKills=0`, absent receipt and only the two unsealed partial
populations described above. Confirm no sealed cache, later reader, model,
checkpoint, test, result, terminal or scientific namespace was created. Treat
the 131 >90-second stalls / 98.97% stall-span measurement as diagnostic
evidence, not proof that GC is causal or that the repair fits memory.

If and only if source and lineage pass, authorize exactly one fresh score-free
capacity proof on Perf Cloud:

- unit `belief-r5-cache-capacity-b016780-v9.service`, `Restart=no`,
  `RuntimeMaxSec=4h`, `MemoryMax=25769803776`, `MemorySwapMax=0`,
  `OOMPolicy=stop`, topology 1 build x 8 workers;
- root-owned clean detached checkout `/opt/belief-r5-b016780`, exact safe-flag
  paths/hashes stated above;
- preserved read-only root `/opt/belief-r5-evidence-8d9390e-r2` with failed
  freeze `dc7e3a96…30a95`, admission `4e95d87b…bf756` and input index
  `189334f9…57c83`;
- fresh scratch `/opt/belief-r5-cache-capacity-b016780-v9` and sole prospective
  receipt `/opt/belief-r5-cache-capacity-b016780-v9.json`; do not copy or resume
  v8 partial files;
- no automatic freeze/prep queue and no retry. The proof may read only bound
  train/calibration inputs and may publish only its score-free cache receipt.

Append exactly this marker only on PASS; otherwise append concise blockers:

`BELIEF_R5_GC_SCOPE_SOURCE_V1_REVIEW {"deployment_authorized":false,"failed_admission_sha256":"4e95d87b2c2ffdec99ac1c0fdb5111e176c2389d5f83384fb2af21f2d25bf756","failed_freeze_sha256":"dc7e3a96ad4624144a2d35fa4c6fcb0e4ff5e539efa45a7b87023ca0a7030a95","failed_input_index_sha256":"189334f9ecf14d71abfeae91d1fcda73f2f4e39658e9a93d6600ab2511757c83","freeze_authorized":false,"gameplay_authorized":false,"git":"b016780d3d84b9a33233ea63b9b09b009f75469d","independent_review":true,"merge_authorized":false,"one_score_free_capacity_proof_authorized":true,"outcome_open_authorized":false,"parent":"8221eec405b3bfa58fc30918838e1780eea4e2b9","proof_build_concurrency":1,"proof_checkout":"/opt/belief-r5-b016780","proof_memory_max_bytes":25769803776,"proof_receipt":"/opt/belief-r5-cache-capacity-b016780-v9.json","proof_restart_authorized":false,"proof_runtime_max_seconds":14400,"proof_scratch":"/opt/belief-r5-cache-capacity-b016780-v9","proof_scratch_must_be_fresh":true,"proof_swap_max_bytes":0,"proof_unit":"belief-r5-cache-capacity-b016780-v9.service","proof_workers_per_build":8,"retry_authorized":false,"schema":"belief-r5-gc-scope-source-review-v1","scientific_execution_authorized":false,"strength_claim_authorized":false,"test_open_authorized":false,"training_authorized":false,"v8_receipt_is_capacity_pass":false,"v8_scratch_reuse_authorized":false,"verdict":"PASS"}`

This marker cannot authorize a freeze, model, test opening, scientific run,
gameplay, strength claim, merge or deployment. A passing v9 receipt must be
independently reopened before fresh all-rank capacity/deadline/seed receipts
and one later consolidated immutable-freeze/launch review.

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
2. Wait for the single exact PR #138 source/v9-proof review above; do not run
   staged source without its marker.
3. On PASS, launch only the fresh hard-capped v9 score-free proof and preserve
   its terminal evidence. Do not reuse v8 partial files.
4. If v9 passes and independently reopens, generate fresh all-rank
   capacity/deadline/seed receipts, seal one fresh freeze and request one exact
   consolidated freeze/launch review.
5. Launch one bounded R5 only after that PASS. No same-admission retry.
6. Independently reopen each terminal, then decide whether belief advances to
   gameplay-search design or closes/revises. Merge remains a separate choice.
