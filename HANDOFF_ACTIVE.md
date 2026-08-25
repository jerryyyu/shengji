# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 00:10 EDT.

## Immediate objective

Obtain a decision-grade answer on whether actor-visible public history improves
hidden-card ownership prediction. Finish and independently reproduce R4, then
run one efficient recoverable R5 using the same frozen scientific population.
R4 and R5 are not independent replications. Neither authorizes a sampler,
gameplay, strength, promotion, deployment or merge.

## Review queue — exact current asks

### 1. PT0 natural-endgame terminal result — review now

The single reviewed score-free Mini execution is complete. Do not launch or
resume it again.

| binding | exact value |
|---|---|
| source / PR | PR #142, `bd4833fed1aa6196bca94b1ef65752cc5c4b10c3` |
| source+freeze PASS | canonical `HANDOFF_REVIEW.md` line 3617 |
| design SHA-256 | `f4001fcd3db02bee1ae85963971d610795fa0703c43ff84bce1a99b9ad9237c6` |
| freeze SHA-256 | `6be498e8137d41533df912fe271c51813eb5cfdacf2ac8193a6a6b6b1b0d222d` |
| result root | `/private/tmp/shengji-pt0-natural-run-bd4833f-r1` |
| packet self-hash | `692179df282bea3358275cc140b9609deeefd9fdaebba2333c2b41fdc69388e9` |
| packet file SHA-256 | `23b5374218903ac19f6c82ec70ded0986ded2e2dafffeacbf49f49b95cbd6e5a` |
| manifest self-hash | `52097d6180afaed044a2e1a60c10f40b7a8cfc232fafc60252b663a089246e4c` |
| manifest file SHA-256 | `f039afdb2f7d88d4160cfef3d860f0ce0e57923310f113cea3b9b0454881440b` |
| launch | one run, exit 0, no restart, 104/104, no truncation |

Independently reopen the exact source, freeze, all 104 record files, packet and
manifest. Run the reviewed `--verify` path and rederive the summary plus
5,000-replicate fixed-seed capture-round-cluster bootstrap from record bytes.
Confirm the complete 13-rank
x 2-banker x 2-role x 2-horizon grid, 16 proposal plus 16 independent
evaluation draws per state, with-replacement semantics, actor-visible identity
binding, no hidden fields in published bytes, and the all-false authority map.
If doing a full deterministic replay for terminal reproduction, use controlled
read access to the committed capture secret, write only to reviewer-owned
scratch and compare canonical packet bytes; never alter the sealed result root
or treat the replay as another scientific attempt.

Reproduce and interpret these exact summaries:

| baseline | mean held-out signed-level delta | 95% clustered interval | state signs | action flips |
|---|---:|---:|---:|---:|
| heuristic | `5/208` = `+0.02404` | `[1/544, 91/1712]` = `[+0.00184,+0.05315]` | 7 positive / 95 zero / 2 negative | 220/416 = 55/104 |
| smart | `5/208` = `+0.02404` | `[1/428, 85/1584]` = `[+0.00234,+0.05366]` | 8 / 93 / 3 | 228/416 = 57/104 |
| `mc-s0-report-lcb` | `35/1664` = `+0.02103` | `[-1/560, 73/1488]` = `[-0.00179,+0.04906]` | 7 / 94 / 3 | 275/416 |

Return one formal conclusion: what local privileged-teacher headroom is proven,
what remains inconclusive against the production MC baseline, and whether the
evidence is sufficient only to draft/review the PT1 three-arm acquisition
screen. Do not issue PT1 execution, training, gameplay, strength, merge,
promotion or deployment authority.

### 2. R4 terminal result — wait for seal

No review yet. When the live supervisor seals, independently reopen raw score
populations, curves, chosen checkpoints, mechanics, caps and terminal
statistics once. Human test `n=51` remains descriptive. Distinguish patience
stop, full-epoch completion and deadline truncation. Do not interpret a partial
or inspect an outcome before the terminal exists.

### 3. R5 source + freeze — wait for one consolidated packet

Do not review PR #144 yet. Codex is finishing one exact Perf-host capacity and
freeze packet. The next request will bind the final source and immutable freeze
together once; no intermediate source-only review is wanted.

## Live R4

| field | exact binding |
|---|---|
| source | `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host / unit | `shengji-cloud`; `belief-v2-r4-d2d466f-r1.service` |
| evidence / ops | `/opt/belief-r4-evidence-d2d466f-r1`; `/opt/belief-r4-ops-d2d466f-r1` |

R4 is active and untouched in stage 8/10 calibration, 82/85 supervisor tasks,
with `NRestarts=0`, about 27.0 GB current / 31.09 GB peak memory, no failure,
no test opening and no terminal. All four training cohorts and checkpoints are
sealed. Remaining work is final calibration, the one test opening/terminal
derivation, and read-only terminal verification.

## R5 exact successor preparation

The spent `8d9390e` admission remains immutable and cannot retry. Its input
index and five completed train/calibration tensor-cache components are preserved
under `/opt/belief-r5-evidence-8d9390e-r2`; no model, test or terminal exists.

Draft PR #144 exact head
`9e44c0f41541c576ec3acedf1097aec26d9a7a12` is clean and CI-green. Its complete
delta from parent `50f2a88f8f6d95594bd8d92fa6546f0613915f15` is eight files,
`+1138/-79`. It imports the exact sealed train/calibration cache read-only,
releases cold parent pages, avoids imported executor startup, reports zero
realized cache-build workers, and permits only path relocation while retaining
exact source/native/package content identities. Final exact-head BELIEF suites
pass 469 with six skips pure and 471 with four skips strict compiled;
`git diff --check` and both CI jobs pass.

On Perf Cloud, exact-head 16-CPU capture capacity completed in 6m41.5s using
1h41m44s CPU and 2.4 GiB peak memory; its canonical receipt and two independent
seed scan/registry populations verify byte-exactly. The score-free deadline
probe is active under a 30-GiB/zero-swap/three-hour hard boundary after two
pre-measurement setup refusals (one generated build-tree shadow, then one
missing `PYTHONHASHSEED=0`). Neither refusal produced a receipt or scientific
namespace. Evidence root `/opt/belief-r5-evidence-cache-import-v1-r1` remains
absent. After the deadline receipt, Codex will derive caps, build the freeze
twice byte-identically, full-hash-reopen all five external cache components,
and publish one consolidated source+freeze review request.

## Fleet

| host | current use | invariant |
|---|---|---|
| Mini | PT0 complete; idle | Do not rerun PT0. |
| Strength Cloud | live R4 calibration | Monitor only; do not signal, mutate, merge into or compete with it. |
| Performance Cloud | R5 score-free preflight/freeze work | No scientific R5 namespace or test opening before exact consolidated PASS. |
| Production | untouched | No deploy or policy change from any research result. |

## Next operator sequence

1. Claude performs the single PT0 terminal review above and records the formal
   interpretation in `HANDOFF_REVIEW.md`.
2. Codex completes the R5 Perf receipts, immutable freeze and one consolidated
   source+freeze request.
3. Launch exactly one recoverable R5 only after that exact PASS; no
   same-admission retry.
4. When R4 seals, independently reproduce its terminal result before any
   belief-to-gameplay decision.
5. R5 later receives the same terminal treatment. Only then decide whether
   BELIEF advances to a B3 sampler/search design or closes/revises.
