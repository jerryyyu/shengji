# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 01:32 EDT.

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

## Review queue — no active ask until repaired R5 freeze

The former PR #144 review at `9e44c0f` is withdrawn. Do not append its marker:
R4 exposed a deterministic production-path projection defect shared by that
head, so the `r11` freeze would fail in calibration. Codex is preparing one
repaired PR #144 head and fresh immutable freeze. The next request will again
be one consolidated source+freeze review, not separate review rounds.

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

## R5 exact successor — current freeze superseded, repair in progress

PR #144 `9e44c0f` is clean and CI-green, but it contains R4's exact projection
failure path. Its `r11` freeze and any review marker are superseded and must not
launch. The repair routes the failed one-PPB residual matching case through the
already-existing exact hard-bound transport fallback and adds a direct
mutation-sensitive witness. A fresh exact head, validation, host freeze and
single consolidated review request will replace `r11`.

The reusable cache import was full-byte reopened twice under exact source and
freeze. Both passes returned the same five child manifests, counts and logical
bytes. Neither produced a scientific namespace or opened test. The first
passed in 47.0s wall and the independent warm-cache reopen in 27.2s.

R5 is now scientifically useful as the recoverable successor to an R4
pre-test infrastructure failure; it is not a pseudo-independent replication.
Launch remains prohibited until the repaired source and fresh freeze receive
one consolidated PASS.

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
| Performance Cloud | idle; current R5 `r11` packet superseded | Validate repaired source, build fresh freeze, then await one consolidated PASS. |
| Production | untouched | No deploy or policy change from research evidence. |

## Next operator sequence

1. Codex lands and validates the narrow projection repair on PR #144 without
   altering R4, then builds one fresh exact Perf Cloud freeze.
2. Claude performs one consolidated repaired-head source+freeze review.
3. Codex launches one fresh recoverable R5 and independently reproduces its
   terminal; R4 remains a documented pre-test infrastructure failure.
4. Codex finishes PT1-only source, runs a score-free Mini capacity proof and
   requests one consolidated PT1 source+freeze review.
5. R5 and PT1 each receive independent terminal reproduction before any
   belief-to-gameplay or privileged-teacher-to-public-policy decision.
