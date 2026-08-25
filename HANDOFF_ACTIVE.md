# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 00:32 EDT.

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

## Review queue — one exact consolidated ask

### 1. PR #144 R5 source + immutable freeze — review now

Review exact source head
`9e44c0f41541c576ec3acedf1097aec26d9a7a12` in clean checkout
`/opt/belief-r5-3dda4f1` on `shengji-perf`, together with the exact host freeze.
Do not initialize, launch, open test, merge, deploy or modify R4.

| binding | exact value |
|---|---|
| PR / source | PR #144; exact head `9e44c0f41541c576ec3acedf1097aec26d9a7a12` |
| reviewed base | `50f2a88f8f6d95594bd8d92fa6546f0613915f15` |
| source delta | 8 files, `+1138/-79`; `git diff --check` PASS |
| CI / suites | server+frontend SUCCESS; 469+6 skip pure; 471+4 skip strict compiled |
| freeze | `/opt/belief-r5-freeze-9e44c0f-r11.json` |
| freeze SHA-256 | `110f7d1592aabc1905961a1d9992b47de54ee3cd1e3ec15a6da05443ef10d777` |
| review packet | `/opt/belief-r5-9e44c0f-freeze-inputs-r11/freeze-review-packet.json` |
| packet SHA-256 | `67dc847e7e5532482a2b02e505efcc65e4b069463ed6e0142dcf7a64fd011749` |
| expected marker SHA-256 | `45a925cf2799152980bd468d49a00e8a0e19b55b81adef5fe30c6300818a6da8` |
| independent verifier | `/opt/belief-r5-9e44c0f-review-verification-r11/verify-review-packet.py` |
| verifier result | `verified=true`, 11 inputs, 46 support artifacts, 5 cache children |
| fresh evidence / ops | `/opt/belief-r5-evidence-cache-import-v1-r1` and `/opt/belief-r5-ops-cache-import-v1-r1`, both absent |

Audit the eight-file source fail-closed. In particular verify that the fresh
R5 run may import only the five named immutable non-test train/calibration
cache components from the spent `8d9390e` namespace; the old admission cannot
resume, retry, relabel or authorize training; source freeze/admission/review/
tombstone/runtime/index/stage/manifest/ownership/population bytes all bind; the
cache is never mutated; and portable relocation removes only host path/boot
locations while preserving exact Python/native/torch/numpy/source content.

Independently rerun the packet verifier and reopen the capacity, deadline,
seed scan/registry, caps, supervisor plan, freeze and cache receipts. The full
cache proof hashed all five components twice with identical stable receipts:
27,822,677,063 logical bytes, below the frozen 64-GiB training-artifact cap.
Confirm the expected review claim derives exactly from the freeze and the
launcher binds source/freeze/marker while requiring a real review commit.

Return one `PASS` or `HOLD` with findings ordered by severity and exact
file:line. On PASS, append only the exact derived
`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW` marker to `HANDOFF_REVIEW.md` in one
authenticated Claude review commit. That marker may authorize this single
offline capture/reference/training/test run only. It grants no retry, sampler,
gameplay, strength, promotion, deployment or merge. Codex will keep the run
unlaunched until R4's terminal result is independently interpreted.

### 2. R4 terminal result — wait for seal

No review yet. When the live supervisor seals, independently reopen raw score
populations, curves, chosen checkpoints, mechanics, caps and terminal
statistics once. Human test `n=51` remains descriptive. Distinguish patience
stop, full-epoch completion and deadline truncation. Do not inspect an outcome
before the terminal exists.

## PT0 result — closed and interpreted

Claude's authenticated terminal review is canonical at main commit `b8419bf`.
Exact source `bd4833f`, 104/104 records and the clustered bootstrap reproduced.

- Exact teacher minus heuristic and smart: mean `5/208 = +0.02404`; both 95%
  clustered intervals exclude zero. Local headroom is proven.
- Exact teacher minus production `mc-s0-report-lcb`: mean `35/1664 = +0.02103`,
  interval `[-0.00179,+0.04906]`. This is inconclusive.
- The result supports drafting PT1 only. No PT1 run, public policy, gameplay or
  strength authority followed from PT0.

## Live R4

| field | exact binding |
|---|---|
| source | `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host / unit | `shengji-cloud`; `belief-v2-r4-d2d466f-r1.service` |
| evidence / ops | `/opt/belief-r4-evidence-d2d466f-r1`; `/opt/belief-r4-ops-d2d466f-r1` |

R4 is active and untouched in calibration, 82/85 tasks, task-weighted progress
96.47%, `NRestarts=0`, about 27.3 GB current / 31.09 GB peak memory, no failure,
no test opening and no terminal. All four 30-epoch training cohorts and their
checkpoints are sealed. Remaining work is final calibration, the one test
opening/terminal derivation, and read-only terminal verification.

## R5 exact successor — launch-ready after review, held for R4

PR #144 exact head is clean, mergeable and CI-green. The score-free 416-round
capacity receipt completed under all 16 CPUs; deadline and resource caps are
frozen. The immutable all-rank/human R5 freeze uses 13,312 fresh synthetic
rounds, fresh references, four eight-member cohorts, transparent curves,
graceful deadline truncation and one test opening.

The reusable cache import was full-byte reopened twice under exact source and
freeze. Both passes returned the same five child manifests, counts and logical
bytes. Neither produced a scientific namespace or opened test. The first
passed in 47.0s wall and the independent warm-cache reopen in 27.2s.

The packet is ready for the single consolidated review above. Even after PASS,
hold scientific launch until R4 terminal interpretation: a same-population R5
rerun is useful after infrastructure failure or a deliberately revised
estimand, but not as a pseudo-independent confirmation of an R4 answer.

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
| Strength Cloud | live R4 calibration | Monitor only; never signal, mutate or compete with it. |
| Performance Cloud | R5 packet complete; no scientific run | Await one consolidated PASS, then R4 interpretation. |
| Production | untouched | No deploy or policy change from research evidence. |

## Next operator sequence

1. Claude performs the single PR #144 source+freeze review above.
2. Codex monitors R4 read-only and independently reproduces its sealed terminal.
3. Decide from R4 whether unchanged R5 remains informative; launch the one
   reviewed R5 only when it answers a distinct unresolved question.
4. Codex finishes PT1-only source, runs a score-free Mini capacity proof and
   requests one consolidated PT1 source+freeze review.
5. R5 and PT1 each receive independent terminal reproduction before any
   belief-to-gameplay or privileged-teacher-to-public-policy decision.
