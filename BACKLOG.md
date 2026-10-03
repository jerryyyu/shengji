# Backlog

Last reconciled: **2026-10-03 (release 37 live on release 36's model; release 38 = the same package + four search rules, approved and pending deploy)**. This file is the prioritized
decision queue, not a run log. Open investigations are tracked on the board issue #679 and its
topic issues (#663 model, #676 search screens, #436 PUCT/allocation, #355 Sol benchmark, #681
mistake audit). Live processes are
`server/scripts/fleet_status.sh` plus the owning GitHub issue (`HANDOFF_ACTIVE.md` was
deleted, #674); immutable authority markers are in `HANDOFF_REVIEW.md` (frozen to its
markers, #674; prose lives on GitHub issues); research architecture is in `RL_PLAN.md`; callable policy
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
live under release 37; every screen compares against it until release 38 deploys, then against release 38). Screens are 520-cluster mirrored windows; five windows
triage (extend only when the point exceeds +0.015; MDE80 about 0.033), ten
shared-control windows are nominal, and only fresh held-out deals confirm.

## Now — ordered by decision value

| priority | lane | current state | next decision-bearing output | gate |
|---:|---|---|---|---|
| **LIVE** | **Release 37 (2026-10-01) on release 36's model: pv-search W64/K8 + hybrid bury, SMV3 outcome head 491ee4bf — Claude** | Release 36 deployed 2026-09-30 11:53 ET (#666, plan #663) on v36a +0.0361 [+0.0015, +0.0707] and the predeclared confirmation v36a2 +0.0393 [+0.0033, +0.0752] vs release 30 as served; release 37 (#671, 01:1x ET 10-01) is a phone-HUD CSS fix, same package and name. Releases 29–35 served the soft head 8ecd4fea. | The post-gen-5 plan on #663 and the data-use audit #667; every screen compares against release 36. | Rollback = the release-30 lines in `fly.toml` or the release-35 image (`DEPLOY.md`). |
| **PENDING** | **Release 38: release 36's package + search rules div + rc + tb + la — release PR in preparation** | Jerry approved promotion 2026-10-03. Evidence (#676, indirect vs a common MC-LCB control): div + rc + tb vs release 36 +0.0461 [+0.0242, +0.0681] on ten fresh windows, CONFIRMED; + la over the combination +0.0106 [+0.0006, +0.0205], ten windows, POSITIVE incremental (lower bound near zero; not a second confirmation). Served name `pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457`. | Deploy (Jerry's call), then every screen compares against release 38. | Rollback = release 37's selection, recorded in `DEPLOY.md` by the release PR. |
| **P1** | **Model: C11 retrain — #663** | SMV3 recipe + runPVR1..8 (624k deals); early-stopped at epoch 9, best epoch 6. Finding (#663 issuecomment-5967276911): on a row whose admitted candidates all contain the same card multiplicity, the listwise term has zero direct gradient for that shared card; the card-presence BCE still pushes toward the recorded play, and other rows and shared parameters can still train it. C15 baseline (issuecomment-5967436179): 702 of 41,551 soft-target rows (1.69%) have a pair common to every candidate in the FIRST availability-selected 50,000-row chunk of the PVR5–8 extraction — a descriptive count on that chunk, not a prevalence estimate across PVR. Hypothesis, unmeasured: search-rule diversity raises the contrast in new data. | C11's served screen vs the production search. | Every screen vs the current production release. |
| **P1** | **Data: runPVC1/runPVC2 — teacher = the combo + la search** | runPVC1 done 10-03 (16,000 deals, seeds 44260910..); runPVC2 running. | A corpus whose ballots carry the release-38 admission's contrast. | Corpus seed ranges excluded from screens of models trained on them. |
| **P2** | **Sol benchmark — #355** | SMV3 row vs Sol +0.55 [+0.10, +1.00] (15/20), vs PT-Sol +0.10 [−0.20, +0.40]; ten deals each, descriptive. Remaining rows running. | The full nine-policy panel. | Descriptive only; no strength claim. |
| **CLOSED** | **PUCT P1 and root allocation A6 — #436** | PUCT on the SMV3 package vs release 36: package prior −0.417, uniform −0.894 (issuecomment-5962752743); A6 closed (issuecomment-5962069171). Adaptive K16 −0.0061 [−0.0303, +0.0181], inconclusive (#676). | — | — |
| **DONE** | **Lane v34r5 — run 4's head served vs release 30 as served — Perf** | Sealed 2026-09-22 13:58 ET at ten windows: +0.0228 [−0.0020, +0.0477], crosses zero; no resolved difference in served form (Atlas v2 `v34r5`). | — | — |
| **DONE** | **Depth screen — Codex, cloud** | Sealed 2026-09-22 12:1x ET: neither depth primary resolves a gain (heuristic continuation −0.0692 [−0.1500, +0.0115] at 97.5%; policy continuation also crosses zero; Atlas v2 `depth-screen`). | — | — |
| **DONE** | **Gen-4 run 3 — Mini** | Sealed; served lane v34r3 vs release 30 at five windows +0.0037 [−0.0302, +0.0375], below the triage line (Atlas v2 `v34r3`). Run 2 (depth 6) likewise crossed zero (v34r2). | — | — |
| **DONE** | **Data generation on the search (#592) — cloud** | Superseded: runPV1r/runPV2r and their successors became the gen-5 corpus; the release-36 teacher stores runPVR1..8 followed (Atlas v2 data rows). | — | — |
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
6. ~~Decide the next run under #663 after #667's audit actions~~ done: C11 trained (screen pending) and the #676 search rules screened.
7. Deploy release 38 (Jerry's call); move every screen's comparator to release 38.
8. Screen C11; train on runPVC1/runPVC2 once sealed; finish the #355 panel.

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
- Exact raw markers belong only in `HANDOFF_REVIEW.md` (frozen to its authority
  markers, #674); chronology and current review asks belong on GitHub issues and
  PR review comments.

## Durable conclusions shaping the queue

| result | conclusion |
|---|---|
| **RLCB confirmed and deployed** | Two-stage Monte Carlo remains the only confirmed production strength gain and the named parent for challengers. |
| **A+B+C W32 + exact engineering replay** | Positive model-guided whole-round DEV screen at substantially reduced cost. The model selects the small set that expensive MC evaluates; it is not proven as a standalone final evaluator. Extra worlds/final rollouts have not shown an incremental gain. Full numbers: [AI policy ledger](AI_POLICIES.md#the-shortlist-era-condensed-releases-2228). |
| **S4, S6, T4 learned proposals, pair-aware, global learned rankers** | Rigorous mechanism work did not establish another whole-game winner. Reopen only with a materially different axis, not a larger retry. |
| **T4 widening control** | Positive but compute-confounded; still needs a separate work-controlled confirmation before claiming widening itself won. The new W32 screen does not settle that old experiment. |
| **BELIEF V1/R3 resource failures** | They provide no learning verdict. They motivated reusable artifacts, measured scheduling, graceful truncation, progress telemetry, and the R4/R5 recovery path. |
| **PT0** | Small privileged endgame edge over heuristic/smart; inconclusive versus production MC. |
| **PT1** | Negative for the frozen scope: exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. The recovered result carries a preregistration-governance caveat and is not a clean general closure of late-game teacher search. |
| **PT-Full** | Repeated true-world search recovered a bad single-world collapse but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | All fixed perfect-information consumer arms were negative versus both required parents; local bare-point improvements did not transport. |

Exact numbers, packet identities, incidents, and reviewer findings remain in
the `HANDOFF_REVIEW.md` authority markers and its archived prose
(`docs_archive/handoff-review-*.md`; the ledger is frozen to its markers, #674, and
new prose lives on GitHub issues), `incidents/`, and the dated archives.
