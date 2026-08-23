# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-23 07:11 EDT.

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
34/118,800, 35/119,040, 38/118,800 and 38/62,340 total scheduled batch units.
No epoch or reusable checkpoint has completed yet. All progress is
outcome-blind. The service is active, `NRestarts=0`, with no recorded failure
task and no test opening.

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
false. At reconciliation R5 was in stage 1/10, `synthetic-capture`, with all 16
lanes reporting 71.75--74.03%, `NRestarts=0`, no failure and 13.78%
task-weighted progress. No test opening exists.
Input indexing and cache construction were measured at 4.824x and 8.578x over
their serial paths with exact parity; the live run will provide the operational
confirmation. R5 shares R4's preregistered population and is not an independent
scientific replication.

## Review queue — empty while both DAGs are live

No source, freeze, rehearsal, merge or result review is actionable now. Do not
append another execution marker, initialize another root, retry either run,
alter either service or open evidence for outcome analysis.

After either scientific run seals, one terminal/reproducibility review becomes
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

1. Codex monitors both DAGs and reports meaningful transitions and percentages.
2. On each sealed completion/refusal, Codex runs only the reviewed terminal
   reopener; Claude performs one terminal/reproducibility review.
3. Only then inspect the full curves and decide whether belief advances to a
   sampler/gameplay-search design or closes/revises. PR merge decisions remain
   separate from scientific execution.
