# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-23 04:05 EDT.

## Immediate objective

Carry live BELIEF R4 to a sealed, independently reopened terminal result while
starting one exact reviewed R5 performance successor on the idle Performance
Cloud. Determine whether public-history ownership learning improves held-out
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
At reconciliation the run was in stage 5/10, `device-qualification`, with
48/85 tasks complete and 56.47% task-weighted total progress. All progress is
outcome-blind. The service is active, `NRestarts=0`, with no recorded failure
task.

Frozen bounds remain: capture 65 core-hours / 18,000 seconds; reference 40
core-hours / 14,400 seconds; training 256 device-hours / 172,800 seconds.
The training next-epoch estimate is 5.346 hours. Graceful truncation may seal a
valid best-common-epoch curve at the deadline; it must not be described as
convergence. Human test evidence is descriptive only at exact n=51.

Prior spent roots are not reused. In particular, `b78f802-r3` contains prior
capture artifacts from the canonical-tip failure; the reviewed packet records
`reuse_authorized: false` and the live root was initialized fresh.

## Review queue — one precise launch ask

1. **R5 consolidated source + immutable-freeze review (launch-blocking):**
   review draft PR #128 at exact head
   `dd8fe3141e9142b1cbd60d998cbde34441b5ecb3` together with freeze
   `/opt/belief-r5-freeze-dd8fe31-r1.json`, SHA-256
   `3f56662cb7ba2a7d24a870b648949ef9529afecda860c4874806459265047cfb`,
   on `shengji-perf`. The complete request and plan-only addendum are PR
   comments `5384770069` and `5384782753`. Perform **one** review, not separate
   source/freeze rounds. If PASS, append exactly one canonical marker from
   `expected-review-claim.json` in an append-only Claude-authored main commit.
   PASS authorizes only initialization and the bounded offline R5 run; retry,
   test leakage, gameplay, strength, promotion, deployment and merge remain
   false. If HOLD, report all source/freeze blockers together.

R5 is otherwise ready and inert: exact-head compiled suite 246 passed / 4
skipped; input indexing is 4.824x faster and cache construction 8.578x faster
with exact parity; the 85-task plan reopens; live source/runtime/native/package
and boot bindings pass; all scientific root, partial, tombstone and ops paths
are absent. R5 uses the same preregistered population as R4 and is not an
independent scientific replication. Do not initialize before the marker and
do not request another rehearsal.

After either scientific run seals, one terminal/reproducibility review becomes
actionable for that exact admission and artifact population.

## Monitoring contract

- Read operational state from
  `/opt/belief-r4-ops-d2d466f-r1/status.json` and systemd only.
- Report `task_weighted_percent_basis_points`, current stage, completed/total
  tasks, active worker count, elapsed time and deadline headroom.
- Progress rows are outcome-blind and are not scientific evidence.
- If the service fails, preserve all artifacts and logs; do not retry.
- If it completes, do not interpret or promote the result before the terminal
  reopener and independent review pass.

## Next operator sequence

1. Claude performs the one R5 source+freeze review above.
2. After an exact marker, Codex authenticates it, initializes once and starts
   R5 under the prepared root-owned transient systemd unit on `shengji-perf`.
3. Codex monitors both DAGs and reports meaningful transitions and percentages.
4. On each sealed completion/refusal, Codex runs only the reviewed terminal
   reopener; Claude performs one terminal/reproducibility review.
5. Only then inspect the full curves and decide whether belief advances to a
   sampler/gameplay-search design or closes/revises. PR merge decisions remain
   separate from scientific execution.
