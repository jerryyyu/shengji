# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 02:52 EDT.

## Immediate objective

Obtain a decision-grade answer on whether actor-visible public history improves
hidden-card ownership prediction. Finish and independently reproduce R4, then
run one efficient recoverable R5 chosen in light of R4's result. R4 and R5 use
the same scientific population and are not independent replications. Neither
authorizes gameplay, strength, promotion, deployment or merge.

In parallel, PT0's sealed natural endgame result now supports designing PT1: a
fresh three-arm privileged-teacher acquisition screen whose primary bar is an
improved exact/full-information teacher beating production MC given the same
true world. PT1 is isolated to Mini and cannot touch R4/R5.

## Review queue — empty

Claude's one consolidated PR #144 source + exact `r12` freeze review PASS is
canonical at main commit `19b63f8`. The authenticated marker SHA-256 is
`418fa4c36a419d985c03d5c160d55731e24d191f6de28bf2d4167a419891335a`.
No R5 source, freeze or launch review remains open. Do not review or launch the
superseded `9e44c0f` / `r11` freeze.

## PT0 result — closed and interpreted

Claude's authenticated terminal review is canonical at main commit `b8419bf`.
Exact source `bd4833f`, 104/104 records and the clustered bootstrap reproduced.

- Exact teacher minus heuristic and smart: mean `5/208 = +0.02404`; both 95%
  clustered intervals exclude zero. Local headroom is proven.
- Exact teacher minus production `mc-s0-report-lcb`: mean `35/1664 = +0.02103`,
  interval `[-0.00179,+0.04906]`. This is inconclusive.
- The result supports drafting PT1 only. No PT1 run, public policy, gameplay or
  strength authority followed from PT0.

## R4 — stopped before calibration selection or test opening

| field | exact binding |
|---|---|
| source | `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host / unit | `shengji-cloud`; `belief-v2-r4-d2d466f-r1.service` |
| evidence / ops | `/opt/belief-r4-evidence-d2d466f-r1`; `/opt/belief-r4-ops-d2d466f-r1` |

R4 stopped at 2026-08-25 00:59 EDT with service result `exit-code`, status 1,
82/85 tasks and task-weighted progress 96.47%. All four 30-epoch cohorts,
checkpoints and reusable non-test artifacts remain sealed and untouched.
There is no `calibration/`, `terminal.partial/` or `terminal/` artifact and the
test-scoring controller never opened the frozen test population.

The failure was pre-test synthetic calibration projection:
`BeliefProjectionError: integral projection flow is infeasible`. Independent
read-only replay localized it exactly to seed `4807564651809522458`, rank `2`,
decision index 68 / key `666ee457…e135`, `synthetic-primary` member 6 / model
`ab68d94f…eec7`, after 4,742 successful member projections. The existing
general exact-transport fallback repairs this real prediction with maximum
cell movement 2.38 ppb and then passes full ownership validation. This is an
operational/model-path defect, not a positive or negative belief result.

## R5 exact successor — consolidated PASS; running on Performance Cloud

PR #144 exact head `5d3b129` routes the reproduced R4 one-PPB residual
dead-end through the already-existing exact hard-bound transport fallback. A
direct minimal rerouting witness and the actual R4 calibration replay both
validate the repair; the real row moves by at most 2.38 ppb and then passes the
full ownership validator. The superseded `9e44c0f` / `r11` freeze must never
launch.

The fresh `r12` capacity receipt covers 416 rounds across all 13 trump ranks
and all 16 lanes. It derives the 65 capture-core-hour cap from measured bytes
using the fixed 1.25x rule. The uncontended deadline receipt measures a 6.35h
p95 training epoch and a 19.1-minute reserve against the unchanged 48h wall;
graceful truncation seals the best common epoch if patience has not converged.
The 64 GiB artifact and 30 GiB host-memory caps are unchanged.

The reusable cache import was full-byte reopened twice under exact repaired
source and freeze. Both passes returned the same five child manifests, counts
and 27,822,677,063 logical bytes. Neither produced a scientific namespace,
opened test or mutated the source cache. The independently reproduced
supervisor DAG has 85 tasks and keeps the sole test opening serialized.

The exact `r12` freeze and repaired source received the single consolidated
PASS at main `19b63f8`. Codex independently re-authenticated the append-only
Claude commit and marker, fetched canonical main on Performance Cloud, and
reran the independent freeze verifier: `verified=true`, source `5d3b129`, 11
inputs, 48 support artifacts, five cache children / 27,822,677,063 logical
bytes, scientific namespace absent and test unopened.

R5 initialized at 2026-08-25 02:50 EDT under
`belief-v2-r5-5d3b129-r12.service`, invocation
`bd1b850aa3bf4770a0fc4d132ef5a311`, with admission SHA-256
`70b15175edd62798c3cbd2d6b323bce1b206ae122d8629755e11bc3f616cedc8`.
All 16 capture lanes were active at the first post-launch check, each using
approximately one CPU core; service memory was 5.9 GiB of the frozen 30 GiB
limit and restart count was zero.

The first systemd spawn at 02:49 EDT failed before executing a single launcher
instruction because the byte-reviewed launcher is mode `0400`, not executable.
Both scientific namespaces remained absent. Codex then invoked the exact same
SHA-256-bound launcher bytes through `/bin/bash`; initialization succeeded.
This was an OS exec-mode correction before admission, not a scientific retry.
The consumed marker now prevents another initialization. R5 remains one
scientific run and is not an independent replication of R4.

## PT1 preparation

New isolated worktree `/private/tmp/shengji-privileged-teacher-pt1` branches
from exact PT0 head `bd4833f`. The proposed PT1 search design has three arms:
public production MC, true-world production MC, and exact true-world teacher.
Primary `C-B` measures policy improvement after both receive perfect
information; `B-A` measures value of information. The teacher must beat
production MC with a positive held-out lower bound, not merely beat heuristic.

Implementation is being prepared in new PT1-only files. Do not review or run
it until Codex publishes one exact source+Mini-capacity+freeze request. The
first intended population is fresh and cluster-powered; PT0 records are not
reused as training/evaluation data.

## Fleet

| host | current use | invariant |
|---|---|---|
| Mini | idle; reserved for isolated PT1 capacity/run after review | Never rerun PT0; do not touch R4/R5. |
| Strength Cloud | R4 stopped; immutable evidence preserved | Read-only failure diagnosis only; never restart or alter R4. |
| Performance Cloud | R5 active: 16-way capture under `belief-v2-r5-5d3b129-r12.service` | Monitor only; no retry, source mutation or test opening outside the sealed controller. |
| Production | untouched | No deploy or policy change from research evidence. |

## Next operator sequence

1. Monitor the active R5 DAG and publish percent/stage/resource progress. Do
   not intervene in the sealed run.
2. At terminal, Codex independently reopens every bound artifact and reproduces
   the positive or negative verdict before deciding whether belief advances
   into gameplay search.
3. Codex finishes PT1-only source, runs a score-free Mini capacity proof and
   requests one consolidated PT1 source+freeze review.
4. R5 and PT1 each receive independent terminal reproduction before any
   belief-to-gameplay or privileged-teacher-to-public-policy decision.
