# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-23 10:00 EDT.

## Immediate objective

Carry live BELIEF R4 and R5 to sealed, independently reopened terminal results.
Determine whether public-history ownership learning improves held-out
hidden-hand calibration over REF-C, then decide separately whether belief
should enter gameplay search. Neither run authorizes a sampler, gameplay or
strength claim, promotion, deployment or merge.

## Live scientific run

| field | current binding |
|---|---|
| source | draft PR #123, exact head `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| execution review | PASS marker commit `10bd1dab39ee900a7c4650aba06de28ac62587ce` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host | `shengji-cloud` / `ubuntu-32gb-hel1-1`, 16 logical CPUs |
| service | transient `belief-v2-r4-d2d466f-r1.service`, started 2026-08-22 08:59:17 EDT, `Restart=no` |
| evidence | `/opt/belief-r4-evidence-d2d466f-r1` |
| ops | `/opt/belief-r4-ops-d2d466f-r1` |

The exact packet-bound supervisor plan is live. Synthetic capture sealed all
16 lanes at 832/832 rounds and all 30 human-capture tasks sealed. Capture used
53.4/65 core-hours, 13.55/16 GiB and 3.36/5.00 wall-hours, with zero retries or
drops. The run has crossed both stage boundaries that previously exposed the
canonical-tip defect and remains healthy.

The input index sealed all 12,003 units in 3 h 10 m. The 26 GiB training cache
then completed all 12,649 units and passed its exact reopen/hash verification.
Device qualification sealed cleanly. All 29 synthetic/human reference tasks
then passed their post-publish typed byte reconstruction. The run entered stage
7/10, `training`, at 2026-08-23 06:40 EDT with 78/85 tasks complete and four
cohorts active: synthetic primary, hard-geometry label-permutation, human
mixture and synthetic 50%-scale. Each worker independently authenticated the
cache population for about 31 minutes before the first honest epoch-1 batch
progress appeared at 07:10 EDT. At reconciliation the four workers had consumed
8,809/118,800, 8,673/118,800, 8,770/119,040 and 8,388/62,340 total scheduled
batch units. All four cohorts have sealed an epoch-1 journal and reusable resume
state; the synthetic 50%-scale cohort has also sealed epoch 2. These journals
bind all eight member training/calibration receipts, common-epoch selection and
`exact_resume_count=0`, while keeping test, strength and deployment authority
false. Persisted file sizes and SHA-256 bindings reopen directly; the full typed
journal reopener is deferred until it will not compete with live training.
Overall task-weighted progress is 92.18%.
All progress is outcome-blind. The service is active, `NRestarts=0`, with no
recorded failure task and no test opening.

Frozen bounds remain: capture 65 core-hours / 18,000 seconds; reference 40
core-hours / 14,400 seconds; training 256 device-hours / 172,800 seconds.
The training next-epoch estimate is 5.346 hours. Graceful truncation may seal a
valid best-common-epoch curve at the deadline; it must not be described as
convergence. Human test evidence is descriptive only at exact n=51.

Prior spent roots are not reused. In particular, `b78f802-r3` contains prior
capture artifacts from the canonical-tip failure; the reviewed packet records
`reuse_authorized: false` and the live root was initialized fresh.

## Prior R5 refusal and fresh successor

| field | current binding |
|---|---|
| source | draft PR #128, exact head `dd8fe3141e9142b1cbd60d998cbde34441b5ecb3` |
| freeze | `3f56662cb7ba2a7d24a870b648949ef9529afecda860c4874806459265047cfb` |
| execution review | consolidated PASS marker commit `b0693e132aae6346c7888598ce96e6ac2f061fd8` |
| admission | `66d42c7e137929534658650686a905ede8c261f706c46e5eee4e8ca801deffbf` |
| host | `shengji-perf` / `ubuntu-32gb-hel1-2`, 16 logical CPUs |
| service | transient `belief-v2-r5-dd8fe31-r1.service`, started 2026-08-23 04:42:03 EDT, `Restart=no` |
| evidence | `/opt/belief-r5-evidence-dd8fe31-r1` |
| ops | `/opt/belief-r5-evidence-dd8fe31-r1.ops` |

The production reopener authenticated the exact append-only marker (marker SHA
`f3bce678…`) and initialized this namespace once. The root then reopened with
the frozen admission/inventory/group split and all prohibited authorities
false. Synthetic capture sealed all 16 lanes only after their independent
post-publish typed reconstructions passed. The manifests reconcile to 13,312
rounds, 54.21/65 core-hours, 13.55/16 GiB, a 3.46/5.00-hour parallel wall span,
zero retries/drops, one exact freeze/admission and all prohibited authorities
false. All 30 human-capture tasks then sealed. The optimized input-index build
completed all 12,003 units in 851.03 seconds, about 13.4x faster than R4's 3 h
10 m serial stage, and wrote a 311,250,588-byte candidate index. Before any
manifest/seal or downstream stage, the source measured the 16-worker process
tree above the frozen 24 GiB host-memory cap and refused with exact error
`V2 training input index resource cap drift`. The service failed once at
2026-08-23 08:42:45 EDT with `NRestarts=0`; the index remains only in
`result.partial`, no test byte was opened, and retry is false. Preserve the
entire root, ops logs and tombstone. Do not restart this admission or describe
the 100% progress row as a sealed index.

This is a source/freeze design defect in R5's new concurrency, not a transient
host failure: wall time and artifact bytes were far inside their caps, while
systemd measured a 26.7 GiB service peak against the 24 GiB bound. The narrow
repair is pushed on PR #128 at exact head
`8d9390e12535bbf0d235b76e81484f54f912cc86`: input indexing is now capped at
eight workers by the unchanged frozen memory allowance, the stage has a
can-fail over-memory witness, CI is green, and the exact compiled suite is 248
passed / 4 skipped. A score-free eight-worker full-corpus preflight completed
and independently reopened against the preserved failed index. It reproduced
the exact 311,250,588-byte index and SHA `e4958a13…` with a conservative
9.28 GiB process-tree peak under the unchanged 24 GiB cap, 34.27 minutes wall,
no test target or outcome opening and no retained index. Receipt SHA is
`ea772763dcf21016fbca9881f5f36b13b5cbf934a1a39db8f678d024ccde0f69`.

The fresh exact-head receipts and immutable successor freeze are now complete:

| field | successor binding |
|---|---|
| source | draft PR #128, exact head `8d9390e12535bbf0d235b76e81484f54f912cc86` |
| checkout / venv | `/opt/belief-r5-8d9390e` / `/opt/belief-r5-8d9390e-venv` |
| freeze | `/opt/belief-r5-freeze-8d9390e-r2.json`, SHA `dc7e3a96ad4624144a2d35fa4c6fcb0e4ff5e539efa45a7b87023ca0a7030a95` |
| packet | `/opt/belief-r5-8d9390e-freeze-inputs-r2/freeze-review-packet.json`, SHA `f57056fd4da1dbf81603642b7608b1f9600303357d4013ccbd1d2bff7db6537a` |
| claim / marker | claim SHA `6ef3f4d870293e9e59cccd89066419ba9598f81d44af0ed4757052f0bab09792`; marker SHA `ba889610c84d7f3a49c809ebc74e0674676d2f2fa8ba16f53ebaa2890caf9ffa` |
| fresh evidence / ops | `/opt/belief-r5-evidence-8d9390e-r2` and `/opt/belief-r5-ops-8d9390e-r2`, both absent |

Fresh capacity is 416/416 score-free rounds over 16 lanes and all 13 trump
ranks: 377.40 seconds parallel wall, derived capture cap 65 core-hours. Fresh
deadline estimates are 18.013-second capture p95, 34.010-second REF-C p95,
6.089-hour conservative epoch wall and 18.27-minute reserve; exactly seven
complete epochs fit before the fixed 48-hour deadline reserve, after which
graceful truncation remains load-bearing. The supervisor plan independently
reopens to 85 exact tasks with 16/16/1/1/1/16/4/1/1/1 concurrency.

The successor will recapture the same deterministic synthetic/human population
after review. It will not transplant any artifact whose manifest is bound to
the spent R5 admission. The entire failed root, logs, tombstone and predecessor
refusal receipt SHA `58712f72714de6645f94a7ca78cf1dac461c1e74bec83f147a565b615ee5ec6b`
remain preserved. R5 shares R4's preregistered population and is not an
independent scientific replication.

## Review queue — one consolidated R5 source + freeze review now

Review PR #128 exact head `8d9390e12535bbf0d235b76e81484f54f912cc86`
and the exact fresh freeze packet above **once**. Do not split this into source,
memory, reuse and freeze reviews. The reviewed predecessor is `dd8fe314`; the
repair delta is exactly 6 files, +250/-3, while the full R4-to-R5 delta is 19
files, +2207/-221. CI is green, `git diff --check` passes and the exact strict
compiled suite is 248 passed / 4 skipped.

Reproduce and audit these load-bearing boundaries:

1. Eight-worker input indexing stays below the unchanged 24 GiB host cap,
   preserves exact lane/split/coordinate order, cannot read test targets, and
   cannot advance or seal after deadline/resource refusal. Reopen the exact
   memory receipt and predecessor-refusal receipt from the packet.
2. Reopen every freeze/input/claim/plan byte and bind exact Git, complete source
   closure, Python/native/numerical runtime, live boot, H0 split, all-rank seed
   registry, fixed cap derivation, deadline receipt and fresh absent namespace.
3. Confirm the prior R5 admission is spent with no test/model/terminal result,
   this freeze requires fresh capture, and no prior corpus/index is reused.
4. Preserve recoverable caches/checkpoints, progress curves, graceful
   truncation, independent source replay at terminal, one test opening and all
   false sampler/gameplay/strength/promotion/deployment/merge authority.

If and only if all of that passes, append exactly one
`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW ` marker plus the exact canonical
bytes in `expected-review-claim.json` to `HANDOFF_REVIEW.md` in one
Claude-authored append-only canonical-main commit. That one marker may authorize
only initialization and this bounded offline run. Do not request a second
review. Until PASS, do not initialize, retry R5, alter R4 or open outcomes.

R4 remains live. After it seals, its one terminal/reproducibility review becomes
actionable for that exact admission and artifact population.

## Monitoring contract

- Read operational state from each run's exact ops `status.json` and systemd
  unit only.
- Report `task_weighted_percent_basis_points`, current stage, completed/total
  tasks, active worker count, elapsed time and deadline headroom.
- Progress rows are outcome-blind and are not scientific evidence.
- If the service fails, preserve all artifacts and logs; do not retry.
- If it completes, do not interpret or promote the result before the terminal
  reopener and independent review pass.

## Next operator sequence

1. Codex monitors R4 without changing it and preserves the failed R5 root.
2. Claude reviews the complete R5 repair + freeze packet once. No execution
   precedes its PASS.
3. After PASS, Codex initializes only the exact fresh namespace and launches
   the reviewed supervisor once with `Restart=no`.
4. On each sealed terminal completion, Codex uses only the reviewed reopener;
   Claude performs one terminal/reproducibility review.
5. Only then inspect full curves and decide whether belief advances to a
   sampler/gameplay-search design or closes/revises. PR merge decisions remain
   separate from scientific execution.
