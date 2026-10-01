# Backlog

Last reconciled: **2026-10-01 (release 37; the model is release 36's: the gen-5 SMV3 outcome head in the release-30 search)**. This file is the prioritized
decision queue, not a run log. Live processes and exact operator authority are
in `HANDOFF_ACTIVE.md`; immutable reviews and hashes are in
`HANDOFF_REVIEW.md`; research architecture is in `RL_PLAN.md`; callable policy
status is in `AI_POLICIES.md`.

Historical queues remain in `docs_archive/backlog-through-2026-08-11.md` and
Git history. Do not append dated progress blocks here.

## Program objective

Beat the live policy on fresh mirrored whole games with a single learned model
that keeps improving from its own search data, and keep production's latency
tail bounded. The reference points are `mc-s0-report-lcb` (the screen
baseline), the release 24 recipe (`fd6bb411` + hybrid bury, the capped control
of every 2026-09 screen), release 27 (M1 + prior v2), release 28 (JS-M1 as
one package) and, since 2026-09-30, release 36 (the SMV3 outcome head in the release-30 search,
live under release 37; every screen compares against it). Screens are 520-cluster mirrored windows; five windows
triage (extend only when the point exceeds +0.015; MDE80 about 0.033), ten
shared-control windows are nominal, and only fresh held-out deals confirm.

## Now — ordered by decision value

| priority | lane | current state | next decision-bearing output | gate |
|---:|---|---|---|---|
| **LIVE** | **Release 37 (2026-10-01) on release 36's model: pv-search W64/K8 + hybrid bury, SMV3 outcome head 491ee4bf — Claude** | Release 36 deployed 2026-09-30 11:53 ET (#666, plan #663) on v36a +0.0361 [+0.0015, +0.0707] and the predeclared confirmation v36a2 +0.0393 [+0.0033, +0.0752] vs release 30 as served; release 37 (#671, 01:1x ET 10-01) is a phone-HUD CSS fix, same package and name. Releases 29–35 served the soft head 8ecd4fea. | The post-gen-5 plan on #663 and the data-use audit #667; every screen compares against release 36. | Rollback = the release-30 lines in `fly.toml` or the release-35 image (`DEPLOY.md`). |
| **DONE** | **Lane v34r5 — run 4's head served vs release 30 as served — Perf** | Sealed 2026-09-22 13:58 ET at ten windows: +0.0228 [−0.0020, +0.0477], crosses zero; no resolved difference in served form (Atlas v2 `v34r5`). | — | — |
| **DONE** | **Depth screen — Codex, cloud** | Sealed 2026-09-22 12:1x ET: neither depth primary resolves a gain (heuristic continuation −0.0692 [−0.1500, +0.0115] at 97.5%; policy continuation also crosses zero; Atlas v2 `depth-screen`). | — | — |
| **DONE** | **Gen-4 run 3 — Mini** | Sealed; served lane v34r3 vs release 30 at five windows +0.0037 [−0.0302, +0.0375], below the triage line (Atlas v2 `v34r3`). Run 2 (depth 6) likewise crossed zero (v34r2). | — | — |
| **P1** | **Data generation on the search (#592) — cloud** | runPV1/runPV2 stopped on #606 (unresumable after #607; kept as evidence). Fresh regenerations runPV1r/runPV2r on a 4e006561 tree, same seeds, recorded seed-window overlap, scripts ready. | Two 32,000-round stores as the gen-5 corpus. | Behind the depth screen on cloud; Perf needs the storage move before another store. |
| **DONE** | **Atlas v2 (#604) — Claude** | Built 09-22; `docs/atlas_v2/registry.json` + `build_v2.py` live in the repo and are the single ground truth for every screen since release 29. | — | — |
| **P2** | **Perf storage (#592)** | 28 GB free; 356 GB of August belief evidence in Codex's `/opt` and `cloud-archive` namespaces is the lever; corpora stay. | Jerry/Codex decide the move to the SSD with verification. | Never delete evidence. |
| **P2** | **Jev (TypeSafe) — Claude** | Harness merged (#593); live screen vs SmartBot 31/100, −0.47 [−0.65, −0.27]. | Advice mode (policies + search values as context) if Jerry wants it. | Call ceiling on every live run. |
| **CLOSED** | **BELIEF R4/R5, PT-Sol/Luna, D64, Direct-Q, V11, encoder v5, the shortlist-package generations** | Retained as lessons and datasets; v5 closed 09-20 (v32 null), warm generations inside the shortlist null (v33). | — | — |

## Immediate sequence

1. ~~Read lane v34r5~~ done (ten windows, crosses zero; see the table).
2. ~~Read Codex's depth screen~~ done (no resolved gain; see the table).
3. ~~Arm runPV1r then runPV2r on cloud~~ done; the gen-5 corpus and its successors are on Atlas v2 (data rows).
4. ~~Seal gen-4 run 3~~ done (v34r3 crosses zero; see the table).
5. ~~Land the atlas v2 generator in the repo (#604) and close the docs pass for release 30 (#608)~~ both merged.
6. Decide the next run under #663 after #667's audit actions (#668–#673, all merged); every screen vs release 36.

## Entry criteria for new scientific lanes

A proposed lane enters the review queue only when it names:

1. the exact decision or prediction it changes;
2. natural dose and the smallest effect worth detecting;
3. candidate, literal parent, and behavior/work-matched null;
4. one frozen population/split and one terminal rule;
5. source/runtime/artifact identities plus recoverability behavior;
6. one consolidated review surface; and
7. for any projected multi-hour run, one pre-launch DAG audit proving there is
   no duplicate full-data integrity work, naming worker/core utilization for
   every expensive stage, demonstrating checkpoint/recovery behavior, and
   identifying the cheapest learning-bearing result before fleet scale.

Run a cheap score-free census or rehearsal first when dose, runtime, or
candidate geometry is unknown. Rehearsals prove mechanics, not efficacy, and
must never be used to choose scientific seeds or thresholds.

## Operating constraints

- No test opening before a durable pre-test readiness artifact proves that
  training, calibration, curves, and exact identities independently reopen.
- Expiry yields a sealed, explicitly truncated result at the best complete
  common epoch when the design permits it; it must not erase healthy learning
  or masquerade as convergence.
- Preserve reusable capture, reference, index, cache, checkpoint, and
  calibration artifacts when their contracts permit exact reuse.
- Progress must expose completed/total units, percent, elapsed time, ETA, stage,
  worker identity, and deadline headroom without exposing outcomes.
- Use diverse trump ranks and player/deal-disjoint human data. Human moves are
  behavior/proposal evidence, not strength labels.
- Keep facts, actor-private observations, probabilistic beliefs, and privileged
  labels typed and separate. Actor-visible runtime bytes must be invariant to
  hidden-world twins.
- Negative and refused results remain evidence. Never delete them, retry a
  spent namespace, or convert a mechanism PASS into deployment authority.
- Exact raw markers and chronology belong only in `HANDOFF_REVIEW.md`; current
  review asks belong only in `HANDOFF_ACTIVE.md`.

## Durable conclusions shaping the queue

| result | conclusion |
|---|---|
| **RLCB confirmed and deployed** | Two-stage Monte Carlo remains the only confirmed production strength gain and the named parent for challengers. |
| **A+B+C W32 + exact engineering replay** | Positive model-guided whole-round DEV screen at substantially reduced cost. The model selects the small set that expensive MC evaluates; it is not proven as a standalone final evaluator. Extra worlds/final rollouts have not shown an incremental gain. Full numbers: [AI policy ledger](AI_POLICIES.md#experimental-w32-shortlist). |
| **S4, S6, T4 learned proposals, pair-aware, global learned rankers** | Rigorous mechanism work did not establish another whole-game winner. Reopen only with a materially different axis, not a larger retry. |
| **T4 widening control** | Positive but compute-confounded; still needs a separate work-controlled confirmation before claiming widening itself won. The new W32 screen does not settle that old experiment. |
| **BELIEF V1/R3 resource failures** | They provide no learning verdict. They motivated reusable artifacts, measured scheduling, graceful truncation, progress telemetry, and the R4/R5 recovery path. |
| **PT0** | Small privileged endgame edge over heuristic/smart; inconclusive versus production MC. |
| **PT1** | Negative for the frozen scope: exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. The recovered result carries a preregistration-governance caveat and is not a clean general closure of late-game teacher search. |
| **PT-Full** | Repeated true-world search recovered a bad single-world collapse but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | All fixed perfect-information consumer arms were negative versus both required parents; local bare-point improvements did not transport. |

Exact numbers, packet identities, incidents, and reviewer findings remain in
`HANDOFF_REVIEW.md`, `incidents/`, and the dated archives.
