# Active Claude/Codex handoff

Last compacted: 2026-08-09 19:15 EDT. This is the short executable mailbox.
Terminal evidence lives in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, live jobs in `JOBS.md`, and queue order in `BACKLOG.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` signed levels versus `mc-strong`. |
| S3a structured bury | **TERMINAL SELECT NONE** | Preserve `+0.0464`, LCB `-0.0041`; no retry, tuning, pooling or confirmation. |
| S4 point banking | **SEALED MINI SCREEN RUNNING** | Exact `cad3992`, packet `17036e63…1385`, receipt `20a420d2…5cc`; 484/2,048 count-only lines at 19:15 with eight live workers. Inspect no partial outcomes. |
| Human H0 | **CONTROLLER V2 REVIEW PASS / ZERO OUTCOMES** | Marker landed at `cc1c293`. One diagnostic execution is eligible, but Mini is occupied; no label/training/strength authority. |
| Teacher Stage C | **V3 FROZEN / REVIEW OPEN / ZERO STATES** | Review exact source `20bdb95`, asset `1a29418`, packet `f213314a…3b4`. No capture or labeling. |
| S3c small endgames | **ONE-CARD CONTROLLER REVIEW PASS / ZERO SOLVER WORK** | One mechanics/capacity receipt is eligible. Two-card work remains closed. |
| S5 point protection | **CODE REVIEW OPEN / NO CENSUS YET** | Draft PR #4, source `c7bba40`; review the score-free census before a real freeze. No treatment exists. |
| HUMAN-C1 | **PARKED / NO TRAFFIC** | Resume only after a challenger beats report-LCB in confirmation. |

## Active milestone — T3 human-witness challenger readiness

Plain English: finish a trustworthy recipe for generating better training
examples while S4 tests one direct policy improvement. A design review is a
routing boundary, not a strength result.

| output | why it can improve strength | progress and what remains |
|---|---|---|
| **T3.1 S3a** | Test deliberate point/void/trump kitty plans. | **Closed SELECT NONE.** Keep its candidates only as Teacher diagnostics. |
| **T3.2 S4** | Make rollouts price point-card winners rather than always using the cheapest winner. | Full-game screen is running sealed; one terminal verifier owns the result. |
| **T3.3–3.4 H0** | Find human/V11 proposals that survive fair common-world evaluation instead of blindly copying people. | Design and controller both passed. The one-shot diagnostic itself is T4 work and has not run. |
| **T3.5 Stage C v3** | Spend bounded work on uncertainty, proposal disagreement, bury, point play and small endgames while retaining ordinary coverage. | Exact design is frozen below; external PASS/HOLD remains. Zero states or labels exist. |
| **T3.6 S3c** | Grow exact endgame search from one card rather than retrying the failed four-card jump. | Controller passed; one mechanics run is eligible, with no strength claim. |
| **S5 support** | Prove whether apparent point feeding is avoidable and still reproduced before inventing another heuristic. | Code-only review is open on PR #4. |

## Review priority 1 — Teacher Stage-C v3 design

### Plain-English question

Does this packet define a finite, implementable way to build a better Teacher,
without quietly turning human actions into labels or creating an infeasible
recursive-MC job? It must bind the passed H0 controller, exact live champion,
fixed 2,048-state split, candidate caps, folds, refusal rules and a hard maximum
of 10,494,720 candidate-world rollouts. It is score-free and may authorize only
implementation of a future capture/controller.

### Exact assets

- producer source `20bdb95e50169d0877f096e1418c2f135bb2b9f3`;
- asset commit `1a29418155fd2b6e34ad1ad7a64aec740272480c`;
- packet `server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/design_packet.json`;
- external/internal SHA-256 `f213314ace8ead497fcaccde150d0694851069b970948a10d0823cf74ceb93b4` / `649849768d09a14f114569d76fe1753c9044ce05e48de7005f1f008488d84677`;
- script SHA-256 `8c56f6e48b6157e6fad3eecd6950bd40706718bd963427a446dc50dc843ab3ed`;
- H0 controller `3f68dc6e…7fcf`, exact H0 PASS marker, candidate geometry `876ed56b…ff2b`;
- 1,024 DESIGN / 512 CALIB / 512 untouched REPORT; 1,920 play / 128 bury;
- play/bury caps 20/33; ordinary folds 256+256, hard-tail 64 selection plus a fixed 300-world report, deeper audit 128+600;
- hard cap 10,494,720 candidate-world rollouts; recursive MC continuation count is exactly zero;
- real freeze and exact recomputation both passed with zero states, worlds, outcomes or labels.

### Load-bearing checks

1. Recompute the packet from clean source `20bdb95`; verify exact adapter,
   H0 packet/PASS marker, portable live parent, split totals and self-hash.
2. Confirm raw H0 actions never enter the fresh 2,048-state population.
   Human-derived proposals require supported H0 DESIGN evidence and a later
   frozen rule/model; H0 AUDIT cannot tune it.
3. Confirm hard-tail labels use `HeuristicBot` continuation with disjoint
   selection/report folds. The 300-world report evaluates only the fixed
   selection winner versus candidate zero and never reselects.
4. Recompute the 10,494,720 ceiling, including the deeper audit and optional
   S4/S5 continuations. Candidate-cap, underfill or partial-fold drift must
   refuse rather than extend/retry.
5. Confirm S4, S3c and S5 are conditional: S4 needs this running screen's
   terminal PASS; S3c needs each sequential mechanics gate; S5 needs a
   replay-positive census plus separate treatment review.
6. Mutation-test parent mismatch, H0 authority/self-hash drift, split/work
   arithmetic and authority widening. PASS may authorize controller
   implementation only—not capture, labels, training, strength or production.

Focused command:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONPATH=server /Users/jerryyu/Projects/shengji/server/.venv/bin/python -m pytest -q server/tests/test_teacher_stage_c_design.py server/tests/test_h0_human_counterfactual_controller.py server/tests/test_h0_human_counterfactual_packet.py server/tests/test_teacher_stage_b_readiness.py server/tests/test_teacher_terminal_adapter.py
```

Requested marker:

`TEACHER_STAGE_C_V3_REVIEW {"adapter_sha256":"56ccefbd62d9ea2aef30a4c6e54e11a0d2231e464f129e754b84b3488f1c2442","audit_report_worlds":600,"audit_selection_worlds":128,"bury_candidate_cap":33,"calib_states":512,"capture_controller_implementation_authorized":true,"design_states":1024,"git":"20bdb95e50169d0877f096e1418c2f135bb2b9f3","h0_controller_review_schema":"human-h0-counterfactual-controller-review-v2","h0_controller_sha256":"3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf","hard_tail_report_worlds":300,"hard_tail_selection_worlds":64,"independent_review":true,"labels_authorized":false,"live_parent_policy":"mc-s0-report-lcb","live_parent_schema":"live-champion-parent-v1","max_candidate_worlds":10494720,"ordinary_worlds":[256,256],"outcomes_computed_before_review":false,"packet_sha256":"f213314ace8ead497fcaccde150d0694851069b970948a10d0823cf74ceb93b4","play_candidate_cap":20,"production_deployment":false,"production_promotion":false,"recursive_mc_continuation_rollouts":0,"report_states":512,"schema":"teacher-stage-c-hard-tail-design-review-v3","score_free":true,"script_sha256":"8c56f6e48b6157e6fad3eecd6950bd40706718bd963427a446dc50dc843ab3ed","state_capture_authorized":false,"states":2048,"strength_claim":false,"training_authorized":false,"verdict":"PASS","worlds_sampled_before_review":0}`

Append measured PASS/HOLD only to `HANDOFF_REVIEW.md`.

## Review priority 2 — S5 score-free replay census code

Review draft PR #4 / source `c7bba40`. Confirm exhaustive legal-follow
enumeration, exact source-manifest replay, current ballot and preserved
`mc-decision-v2` authentication, no MC sampling/rollouts, no raw cards or
identifiers, and correct separation of historical-only versus currently
reproduced defects. A code PASS permits one deterministic census freeze only;
it does not permit an S5 treatment or strength run.

## Fleet and safety

- Mini: S4 only until terminal; count/status checks only.
- Air: free for review reproduction or a separately reviewed bounded job.
- Fly: release 17, passive monitoring only.
- Prefer Mini for long H0/Teacher work after S4 releases it; do not trade an
  exact one-shot run for idle-machine utilization.
- Never retry, resume, extend, tune from or pool a consumed one-shot stream.
- Fresh paired confirmation owns policy strength; the blinded human ladder
  owns eventual product value.
