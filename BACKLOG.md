# Backlog

Last reconciled: **2026-09-22 09:2x ET (release 30: the policy/value search with the soft head, plus the hybrid-bury fix)**. This file is the prioritized
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
of every 2026-09 screen), release 27 (M1 + prior v2) and release 28 (JS-M1 as
one package, live). Screens are 520-cluster mirrored windows; five windows
triage (extend only when the point exceeds +0.015; MDE80 about 0.033), ten
shared-control windows are nominal, and only fresh held-out deals confirm.

## Now — ordered by decision value

| priority | lane | current state | next decision-bearing output | gate |
|---:|---|---|---|---|
| **LIVE** | **Release 30: pv-search W64/K8 + hybrid bury, soft head 8ecd4fea — Claude** | Release 29 deployed 2026-09-22 00:29 ET on the served confirmation (+0.049 [+0.003, +0.095], five clean windows); release 30 at 09:13 ET = the same name/package with the #607 bury fix (the duplicated-incumbent refusal that silently fell back to the heuristic on ~6% of banker burys, diagnostic-set rate). | First live rooms on release 30: bury fallback records should be budget-only; play p50/p95. | Rollback = the release-29 image, then release 28's one-line name. |
| **RUNNING** | **Lane v34r5 — run 4's head served vs RELEASE 30 as served — Perf** | Relaunched 09:17 ET on tree 4e006561 after Jerry's rule "all screens compare vs v30"; seeds 23960910..24360910, five windows then triage. | The head-to-head that v34r4 (run 4 vs release 28, +0.042 [+0.015, +0.068] at ten windows) could not give. | Extend to ten only if the point exceeds +0.015. |
| **RUNNING** | **Depth screen — Codex, cloud** | 260 mirrored deals × 3 arms (current trick; one extra trick with heuristic continuation; with policy continuation) vs the release-30 card-play control; Jerry approved; launched ~09:05 ET, ~3.5 h, 6 h ceiling. | Two depth-vs-production primaries at Bonferroni 97.5%. | Reader `policy_depth_readout`; #599/#601 PASSed. |
| **RUNNING** | **Gen-4 run 3 — Mini** | Grid trunk d3 c44 warm from JS-G1, soft targets, all 20 stores; 78 min/epoch; epoch 5/20 val_ce 0.5658. | Seal ~03:30 ET 09-23, then its served lane vs release 30 and Codex's W64 card-play arm. | Run 2 (depth 6, soft) armed behind it. |
| **P1** | **Data generation on the search (#592) — cloud** | runPV1/runPV2 stopped on #606 (unresumable after #607; kept as evidence). Fresh regenerations runPV1r/runPV2r on a 4e006561 tree, same seeds, recorded seed-window overlap, scripts ready. | Two 32,000-round stores as the gen-5 corpus. | Behind the depth screen on cloud; Perf needs the storage move before another store. |
| **P1** | **Atlas v2 (#604) — Claude** | Built 09-22: one registry feeds the page; every screen read against the current release; old page/atlas frozen. | Move `registry.json` + `build_v2.py` under `docs/atlas_v2/` with `--check` and tests (PR). | Codex review like the page PRs. |
| **P2** | **Perf storage (#592)** | 28 GB free; 356 GB of August belief evidence in Codex's `/opt` and `cloud-archive` namespaces is the lever; corpora stay. | Jerry/Codex decide the move to the SSD with verification. | Never delete evidence. |
| **P2** | **Jev (TypeSafe) — Claude** | Harness merged (#593); live screen vs SmartBot 31/100, −0.47 [−0.65, −0.27]. | Advice mode (policies + search values as context) if Jerry wants it. | Call ceiling on every live run. |
| **CLOSED** | **BELIEF R4/R5, PT-Sol/Luna, D64, Direct-Q, V11, encoder v5, the shortlist-package generations** | Retained as lessons and datasets; v5 closed 09-20 (v32 null), warm generations inside the shortlist null (v33). | — | — |

## Immediate sequence

1. Read lane v34r5 at five windows (~11:45 ET): run 4 vs release 30, served form; extend only on the triage rule.
2. Read Codex's depth screen when its three arms seal (~12:45 ET); record on the atlas v2.
3. Arm runPV1r then runPV2r on cloud after the depth screen ends; read the first store's manifest.
4. Seal gen-4 run 3 (~03:30 ET 09-23): receipt, atlas v2 row, its served lane vs release 30.
5. Land the atlas v2 generator in the repo (#604) and close the docs pass for release 30 (#608).

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
