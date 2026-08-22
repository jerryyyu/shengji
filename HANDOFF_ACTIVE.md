# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-22 16:50 EDT.

## Immediate objective

Carry the live BELIEF V2/R4 offline scientific DAG to one sealed,
independently reopened terminal result: does the learned ownership model
measurably improve held-out calibration over REF-C? This run cannot authorize
a sampler, gameplay/strength claim, promotion or deployment.

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

The input index sealed all 12,003 units in 3 h 10 m. At reconciliation the run
was in stage 4/10, `training-tensor-cache`, at 774/12,649 batches (6.11%) and
55.36% task-weighted total progress. This is a single-task stage, so low
host-wide CPU utilization is expected rather than a worker failure. All
progress is outcome-blind. The service is active, `NRestarts=0`, with no
recorded failure task.

Frozen bounds remain: capture 65 core-hours / 18,000 seconds; reference 40
core-hours / 14,400 seconds; training 256 device-hours / 172,800 seconds.
The training next-epoch estimate is 5.346 hours. Graceful truncation may seal a
valid best-common-epoch curve at the deadline; it must not be described as
convergence. Human test evidence is descriptive only at exact n=51.

Prior spent roots are not reused. In particular, `b78f802-r3` contains prior
capture artifacts from the canonical-tip failure; the reviewed packet records
`reuse_authorized: false` and the live root was initialized fresh.

## Review queue — empty while the DAG is live

No source, freeze, rehearsal, merge or result review is actionable now. Do not
append another execution marker, initialize another root, retry, alter the
service, open evidence for outcome analysis, merge PR #122/#123, or start a
competing BELIEF run.

The next review becomes actionable only after the supervisor publishes a
sealed terminal result or a fail-closed refusal. It is one consolidated
terminal/reproducibility review against the exact admission and artifact
population.

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

1. Codex monitors the live ten-stage DAG and reports meaningful transitions.
2. On sealed completion/refusal, Codex runs only the reviewed terminal reopener.
3. Claude performs one consolidated terminal/reproducibility review.
4. Only then do we interpret the BELIEF result, inspect the full training and
   calibration curves, and separately decide whether to merge PR #122 followed
   by PR #123.
5. A BELIEF pass may open a sampler-mechanics design; a null or truncation
   instead informs the next data/model experiment. No gameplay experiment is
   selected before that diagnosis.
