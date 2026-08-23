# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-23 09:09 EDT.

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
5,992/118,800, 6,083/119,040, 6,098/118,800 and 5,665/62,340 total scheduled
batch units. All four cohorts have sealed an epoch-1 journal and reusable resume
state; the synthetic 50%-scale cohort has also sealed epoch 2. These journals
bind all eight member training/calibration receipts, common-epoch selection and
`exact_resume_count=0`, while keeping test, strength and deployment authority
false. Persisted file sizes and SHA-256 bindings reopen directly; the full typed
journal reopener is deferred until it will not compete with live training.
Overall task-weighted progress is 92.05%.
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

## Parallel R5 scientific run

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
passed / 4 skipped. A score-free eight-worker preflight is running on Perf
Cloud against the preserved failed index. It may retain only a receipt and must
reproduce the exact 311,250,588-byte index and SHA `e4958a13…` below 24 GiB;
it cannot initialize, train or open test bytes.

The successor will use a fresh evidence namespace and recapture the same
deterministic synthetic/human population after review. It will not transplant
artifacts whose manifests are bound to the spent R5 admission: avoiding that
new rebinding trust boundary is worth the roughly 3.5-hour recapture cost. The
entire failed root, logs, tombstone and exact predecessor-refusal receipt remain
preserved for audit. R5 shares R4's preregistered population and is not an
independent scientific replication.

## Review queue — no review yet; R5 repair is being prepared

Do not review or authorize anything until Codex posts one exact repaired
source+fresh-freeze packet. The intended next ask is one consolidated review,
not separate source, reuse and freeze rounds. Until then do not append another
execution marker, initialize another root, retry R5, alter R4 or open outcome
evidence.

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
2. Codex closes the R5 memory-cap defect with a measured bounded-worker repair,
   an exact prior-refusal receipt and one fresh immutable freeze packet.
3. Claude reviews that complete packet once. No execution precedes its PASS.
4. On each sealed terminal completion, Codex uses only the reviewed reopener;
   Claude performs one terminal/reproducibility review.
5. Only then inspect full curves and decide whether belief advances to a
   sampler/gameplay-search design or closes/revises. PR merge decisions remain
   separate from scientific execution.
