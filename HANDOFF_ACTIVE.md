# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical reviews
> belong in `HANDOFF_REVIEW.md` and Git history. A request not listed here is
> not active.

Last reconciled: 2026-08-23 23:23 EDT.

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
task-weighted progress 94.16%, four cohort workers active, `NRestarts=0`, no
failure task, no terminal and no test opening. Exact schedule progress is:

- synthetic primary 49,943/118,800 = 42.03%;
- hard-geometry label control 49,901/118,800 = 42.00%;
- human mixture 50,681/119,040 = 42.57%;
- synthetic 50%-scale 48,513/62,340 = 77.82%.

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
`00eb6ab56e9547094128fa03aede7086a6845f70` is clean, mergeable and CI-green.
It keeps the 24-GiB cap, derives topology `8 aggregate = 2 concurrent x 4
workers`, durably records cap refusal and forbids same-admission resume. The
primary worker now emits the deterministic hard-geometry control labels from
the same in-memory natural batch that writes the primary actor tensors. This
removes the later 9.4-GiB actor-cache reread without changing any output bytes,
model input, label, population, gate or authority. Complete BELIEF suites pass
453 with six skips pure and 455 with four skips strict-compiled; the final
combined parity/resume and production-controller wiring battery passes 12/12.
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

A fresh v6 score-free proof is live:

| field | current binding |
|---|---|
| source / checkout | `00eb6ab56e9547094128fa03aede7086a6845f70`; `/opt/belief-r5-00eb6ab` |
| host / unit | `shengji-perf`; `belief-r5-cache-capacity-00eb6ab-v6.service`, `Restart=no`, `RuntimeMaxSec=4h` |
| scratch / receipt | `/opt/belief-r5-cache-capacity-00eb6ab-v6`; `/opt/belief-r5-cache-capacity-00eb6ab-v6.json` |
| limits | exact 25,769,803,776-byte `MemoryMax`, no swap, topology 8 = 2 x 4 |
| authority | score-free train/calibration rebuild only; no retry, model, test, outcome, gameplay, merge, strength or deployment authority |

The checkout/native extension is exact and clean. The unit completed its
expected 16-minute one-core integrity reopen of the preserved 25-GB component
set, then began the timed rebuild. At 23:22 EDT both the primary actor cache and
its control overlay had published their first exact batch concurrently; the
human cache had independently published 33 batches. This proves on real data
that no later control actor reread remains. `NRestarts=0`, `OOMKills=0`, peak
memory 22,834,737,152 bytes under the hard cap and receipt absent while live.
PASS still requires all five byte-identical component reopens, a sealed
receipt, successful hard-capped unit and explicit false test/outcome/authority
fields. If it passes, Codex will generate fresh 416-round/all-13-rank capacity
and deadline receipts, then seal one fresh freeze at exact source `00eb6ab`.

## Separate proposal state — no compute authority

- PR #130 exact head `943bc5834494cb7ae698d063b25585b6c584d090`
  passed substantive code review: its flag remains off, the equal-trump
  lower-point-risk route works, a `+1` trump increment remains guarded and the
  killing mutation fails. It is not literally stacked on the PR #127/#129
  proposal chain; reconcile ancestry with current main and freeze round-level
  utility/dose telemetry before any experiment decision. No run or adoption is
  authorized.
- `codex/privileged-teacher-v1-proposal` is a docs-only proposal lane. It must
  distinguish an omniscient capability league from actor-legal targets averaged
  over compatible hidden worlds. It grants no implementation, compute or
  gameplay authority and does not compete with R4/R5.

## Review queue — one consolidated R5 ask, not ready yet

Do **not** review PR #131 yet. The only next source review will bind exact head
`00eb6ab`, the sealed v6 capacity receipt, fresh host receipts, immutable fresh
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
2. Finish and independently reopen the v6 score-free capacity proof.
3. Generate fresh capacity/deadline/seed receipts; seal one fresh freeze and
   one exact consolidated source+freeze review request.
4. Launch one bounded R5 only after that PASS. No same-admission retry.
5. Independently reopen each terminal, then decide whether belief advances to
   gameplay-search design or closes/revises. Merge remains a separate choice.
