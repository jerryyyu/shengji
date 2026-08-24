# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical reviews
> belong in `HANDOFF_REVIEW.md` and Git history. A request not listed here is
> not active.

Last reconciled: 2026-08-23 20:43 EDT.

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
task-weighted progress 93.78%, four cohort workers active, `NRestarts=0`, no
failure task, no terminal and no test opening. Exact schedule progress is:

- synthetic primary 42,052/118,800 = 35.39%;
- hard-geometry label control 42,047/118,800 = 35.39%;
- human mixture 42,624/119,040 = 35.80%;
- synthetic 50%-scale 40,810/62,340 = 65.46%.

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
`5e3bb6bb36cef7a184a821cda25e85a15d5a6fc1` is clean, mergeable and CI-green.
It keeps the 24-GiB cap, derives topology `8 aggregate = 2 concurrent x 4
workers`, durably records cap refusal, forbids same-admission resume and orders
direct builds human, scale, calibration, primary so the primary pages are hot
when the control-label overlay begins. Output/manifest order is unchanged.
Focused tests pass 54/54; complete V2 suites pass 453 with six skips pure and
455 with four skips strict-compiled. Reverting the new ordering helper makes
all three schedule/wiring witnesses fail.

The previous non-scientific v4 proof rebuilt all 9,128 direct batches under
the hard 24-GiB cgroup with no OOM or restart, but primary finished about 48
minutes before overlay. Under file-cache pressure the overlay advanced only
53/3,521 batches and projected about 12.5 hours. The operator stopped it before
its three-hour timeout. It emitted no receipt and is not a pass. An external
one-batch diagnostic after stop reopened the same bytes in 0.648 seconds and
transformed them in 0.046 seconds, isolating cold-cache schedule rather than
data or algorithm parity.

A fresh v5 score-free proof is live:

| field | current binding |
|---|---|
| source / checkout | `5e3bb6bb36cef7a184a821cda25e85a15d5a6fc1`; `/opt/belief-r5-5e3bb6b` |
| host / unit | `shengji-perf`; `belief-r5-cache-capacity-5e3bb6b-v5.service`, `Restart=no`, `RuntimeMaxSec=3h` |
| scratch / receipt | `/opt/belief-r5-cache-capacity-5e3bb6b-v5`; `/opt/belief-r5-cache-capacity-5e3bb6b-v5.json` |
| limits | exact 25,769,803,776-byte `MemoryMax`, no swap, topology 8 = 2 x 4 |
| authority | score-free train/calibration rebuild only; no retry, model, test, outcome, gameplay, merge, strength or deployment authority |

The checkout/native extension is exact and clean. At launch the unit was
active with `NRestarts=0`, receipt absent and no fresh scientific namespace
initialized. PASS requires five byte-identical component reopens, a sealed
receipt, successful hard-capped unit and explicit false test/outcome/authority
fields. If it passes, Codex will generate fresh 416-round/all-13-rank capacity
and deadline receipts, then seal one R3 freeze at exact source `5e3bb6b`.

## Review queue — one consolidated R5 ask, not ready yet

Do **not** review PR #131 yet. The only next source review will bind exact head
`5e3bb6b`, the sealed v5 capacity receipt, fresh host receipts, immutable R3
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
2. Finish and independently reopen the v5 score-free capacity proof.
3. Generate fresh capacity/deadline/seed receipts; seal R3 freeze and one exact
   consolidated source+freeze review request.
4. Launch one bounded R5 only after that PASS. No same-admission retry.
5. Independently reopen each terminal, then decide whether belief advances to
   gameplay-search design or closes/revises. Merge remains a separate choice.
