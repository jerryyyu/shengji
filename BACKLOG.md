# Backlog

Last reconciled: **2026-09-16 (release 28: JS-M1 joint model as one package)**. This file is the prioritized
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
| **LIVE** | **Release 28: JS-M1 one package — Claude** | Deployed 2026-09-16 00:5x ET after the identity gate (2,207/2,208 + 1 near-tie), the server-path smoke and a live bot round. Rollback release 27 / 24. | Ten-window extension and five fresh windows vs release 27; production room logs (bury/play phase timings now logged). | Any regression → rollback to release 27; no recipe change without a new go. |
| **RUNNING** | **runJS1 corpus — Perf** | 32,000 rounds with JS-M1 as teacher (own head as prior at 1,000, hybrid bury), 16 workers, started 09-15 23:10 ET, about 20 clusters/min. | A generation-1 training run on the new corpus vs JS-M1 (same recipe, new data): the search→data→model loop's first measured link. | Offline gates (val CE, policy-head non-inferiority) then the in-play screen. |
| **RUNNING** | **JS-G1 — Mini** | G1's grid trunk from scratch with the policy head on all 20.3M root rows; the value curve tracks plain G1 (0.5495 at seal) so far. | Both #425 gates, then in play as one net vs JS-M1 at matched wall (G1 alone was 5.9× MC-LCB wall). | Same gates as JS-M1. |
| **P1** | **Search with the heads — Codex, #436** | Bounded PUCT lost (−0.62 levels/round at 2× wall); root reuse, compact expansions, root warmup, truncated-value and prior-guided continuations are merged or under review as opt-in research arms against a frozen release-27 control. | A matched-control read showing any of them beats the shortlist at equal wall. | Paired DEV screens first; five capped windows before any claim. |
| **P2** | **Bury latency — Claude** | Locally bury is 0.10–0.15 s and the banker's opening lead 0.4–0.65 s; production decisions queue behind one search worker. Phase telemetry on `model_search` events landed (#450). | The production split of bury vs play wall from the new events; then a bury screen at 16 candidates / 16 worlds if bury is the visible wait. | Bury screen vs the hybrid recipe; no default change without it. |
| **P2** | **Docs cleanup** | This pass updates README, AI_POLICIES, RL_PLAN, BACKLOG, W32_FLY_SERVING, PERF. Removal of HANDOFF_ACTIVE.md, the two Luna teacher docs, TEACHER_TOKEN_EFFICIENCY.md and RESEARCH_PRINCIPLES.md is proposed to Codex. | Codex's answer on the deletion list. | Nothing deleted without it. |
| **CLOSED** | **BELIEF R4/R5, PT-Sol/Luna, D64, Direct-Q, V11** | Retained as lessons and datasets. | — | — |

## Immediate sequence

1. Read runJS1 when it seals (about 09-16 midday); train generation 1 on it
   with JS-M1's recipe; compare offline against JS-M1, then in play.
2. Read JS-G1 at seal (about 09-16 07:00 ET): both gates, then the one-net screen.
3. Extend JS-M1 in play to ten windows and five fresh seeds; record on #425/#435.
4. Read the first production days of release 28 from the room logs (phase
   timings, fallbacks, timeouts); if bury is the visible wait, screen a lighter
   bury recipe.
5. Finish the docs cleanup once Codex answers on the deletion list.

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
