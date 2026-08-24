# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical reviews
> belong in `HANDOFF_REVIEW.md` and Git history. A request not listed here is
> not active.

Last reconciled: 2026-08-24 01:09 EDT.

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

R4 is active and untouched: stage 7/10 `training`, 78/85 tasks complete,
task-weighted progress 94.35%, four cohort workers active, `NRestarts=0`, no
failure task, no terminal and no test opening. Exact schedule progress is:

- synthetic primary 53,779/118,800 = 45.27%;
- hard-geometry label control 53,682/118,800 = 45.19%;
- human mixture 54,548/119,040 = 45.82%;
- synthetic 50%-scale 52,196/62,340 = 83.73%.

All 832x16 synthetic captures, 30 human-capture tasks, 12,003 input-index
units, 12,649 cache units, device qualification and 29 reference tasks sealed
and independently reopened before training. Full-data cohorts have durable
epoch journals/resume states; progress remains outcome-blind. Frozen training
cap is 256 device-hours / 172,800 seconds. Graceful truncation may seal the
best common epoch at the deadline but must not be described as convergence.
Human test evidence is descriptive only at exact n=51.

## Spent R5 admission

Source `8d9390e12535bbf0d235b76e81484f54f912cc86`, admission
`4e95d87b2c2ffdec99ac1c0fdb5111e176c2389d5f83384fb2af21f2d25bf756`
and root `/opt/belief-r5-evidence-8d9390e-r2` are preserved. Its eight-worker
input index sealed exactly. The tensor-cache stage then completed every
non-test batch but measured 30,452,371,456 bytes against the frozen
25,769,803,776-byte cap and refused before publishing. The service failed once
with `NRestarts=0`; no model, reference, calibration, test or terminal artifact
exists, no test byte opened and this admission may never be retried. Its five
partial component caches and tombstone remain immutable evidence.

## PR #131 repair and live score-free proof

Draft PR #131 is the sole successor source lane, stacked on reviewed tip
`9a057dfa07d84dda1672d4895bb0db553182a6ad`. Exact current head
`69502263c7a2a648ba29d3cc55c883d4131fef23` is clean and mergeable; both CI
checks pass on the new head.
It keeps the 24-GiB cap, derives topology `8 aggregate = 2 concurrent x 4
workers`, durably records cap refusal and forbids same-admission resume. The
primary worker now emits the deterministic hard-geometry control labels from
the same in-memory natural batch that writes the primary actor tensors. This
removes the later 9.4-GiB actor-cache reread without changing any output bytes,
model input, label, population, gate or authority. The newest delta restores
the already-measured primary-last launch order: the two large peer readers run
first, then the small calibration reader and primary+control build. This avoids
large-reader file-cache thrash while retaining the in-pass control overlay.
Complete BELIEF suites pass 455 with six skips pure and 457 with four skips
strict-compiled; the focused cache/controller/identity/rehearsal battery passes
64 with four intentional skips.
The exact serial and combined direct+overlay directories are byte-identical,
wrong control dose refuses, both partials resume together and the controller
witness proves the cold fallback is not called on a fresh parallel build.

The superseded non-scientific v5 proof rebuilt all 9,128 direct batches under
the hard 24-GiB cgroup in 1h53m with no OOM or restart, then advanced only
22/3,521 overlay batches in about four minutes and projected the old roughly
12-hour cold-cache behavior. This disproved the reviewed "primary last stays
resident" premise: Linux evicted much of the 9.4-GiB primary cache under
cgroup pressure. The operator stopped only that score-free proof. It emitted
no receipt, initialized no scientific namespace and is not a pass.

The superseded v6 proof was stopped score-free at 3,834/9,128 direct batches
and 250/3,521 overlay batches with no receipt. Its early primary throughput was
misdiagnosed as label-transformation cost. A read-only benchmark over 32 real
cached primary batches measured the transformation at about 45.6 ms/batch;
v5 file timestamps independently showed primary alone at about 74 batches/min.
The actual regression was starting primary beside another large reader under
the fixed cgroup, which reduced it to about 4.9 batches/min. v6 scratch and
journal remain preserved; no scientific namespace or test byte was touched.

A fresh v7 score-free proof is live:

| field | current binding |
|---|---|
| source / checkout | `69502263c7a2a648ba29d3cc55c883d4131fef23`; `/opt/belief-r5-6950226` |
| host / unit | `shengji-perf`; `belief-r5-cache-capacity-6950226-v7.service`, `Restart=no`, `RuntimeMaxSec=4h` |
| scratch / receipt | `/opt/belief-r5-cache-capacity-6950226-v7`; `/opt/belief-r5-cache-capacity-6950226-v7.json` |
| limits | exact 25,769,803,776-byte `MemoryMax`, no swap, topology 8 = 2 x 4 |
| authority | score-free train/calibration rebuild only; no retry, model, test, outcome, gameplay, merge, strength or deployment authority |

The root-owned checkout and imported native extension are exact and clean. The
unit started at 00:36 EDT, completed the expected integrity reopen and entered
the real eight-worker build. At 01:07 it had sealed 1,552/9,128 direct batches
(17.0%) under the hard cgroup ceiling with `NRestarts=0`, `OOMKills=0`; the
receipt remains absent while live. Exact source/failed
freeze/admission/index/topology arguments are visible in the systemd
invocation.
PASS still requires all five byte-identical component reopens, a sealed
receipt, successful hard-capped unit and explicit false test/outcome/authority
fields. If it passes, Codex will generate fresh 416-round/all-13-rank capacity
and deadline receipts, then seal one fresh freeze at exact source `6950226`.

Before any fresh receipt, Codex found that the preserved virtual environment's
editable pointer still named the spent old checkout for scripts without an
explicit source bootstrap. v7 is unaffected because its script inserts the
new source root before project imports. The successor launch view
`/opt/belief-r5-6950226-venv` now hard-links every dependency byte to the
preserved environment and changes only a root-owned mode-0444 editable pointer
(SHA-256 `b46247d2…df1c`) to `/opt/belief-r5-6950226/server`. New-source seed
scan/registry reproduction is byte-identical, and preflight, deadline,
supervisor and native imports all resolve to the exact new checkout. The
freeze/launch scripts recheck this binding and will publish a closed identity
receipt; no scientific namespace exists.

A detached fail-closed score-free preparation queue is active as
`belief-r5-freeze-prep-6950226-r5.service`, exact script SHA-256
`835315f4…75c2`, `Restart=no`, 256-MiB/no-swap/10-hour limits. It can only wait
for v7 success, finalize and reopen that receipt, run/finalize the fresh
capacity and deadline preflights, derive caps, and freeze. Any failed guard
terminates the queue. It cannot initialize R5, authenticate a review, open a
test byte or start scientific execution; the final status must be
`freeze-complete-review-required`.

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
  pass 43 with two intentional skips; strict-compiled passes all 45. It grants
  no training, gameplay, fleet, scientific-run, merge, strength or deployment
  authority and does not compete with R4/R5.

## Review queue — one ready source ask; consolidated R5 ask not ready

1. **PT0 source PR #135:** review exact head
   `ff85ab441c97f4b78ce6a7c46f374522e0f90f1e` as one bounded packet. Verify
   the target contract (`P`, `pi_cont`, actor perspective, signed-level return,
   legal-action population and exact horizon), compatible-world averaging,
   seat/trump-rank rotations, exact-prefix recovery, and that all execution,
   training, gameplay, fleet, merge, strength and deployment authorities are
   false. A PASS is source-foundation approval only; it authorizes no run.

Do **not** review PR #131 yet. The only next source review will bind exact head
`6950226`, the sealed v7 capacity receipt, fresh host receipts, immutable fresh
freeze and final launch script in one consolidated pass. Until that precise
ask replaces this paragraph: do not restart a spent R5 admission, initialize a
successor, alter R4 or open outcomes.

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
2. Finish and independently reopen the v7 score-free capacity proof.
3. Generate fresh capacity/deadline/seed receipts; seal one fresh freeze and
   one exact consolidated source+freeze review request.
4. Launch one bounded R5 only after that PASS. No same-admission retry.
5. Independently reopen each terminal, then decide whether belief advances to
   gameplay-search design or closes/revises. Merge remains a separate choice.
