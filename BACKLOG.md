# Backlog

Last re-derived: 2026-08-09 23:36 EDT.

This file owns the **active executable queue**. `AI_POLICIES.md` owns policy
verdicts, `RL_PLAN.md` owns research design, `JOBS.md` owns compute, and
`HANDOFF_ACTIVE.md` owns the next external review. Detailed T3 chronology is
now in `docs_archive/daily-log-2026-08-09.md`; it is intentionally not repeated
here.

## Two-minute state

- **Production:** compiled `mc-s0-report-lcb` in Fly release 17. Fresh RLCB-C1
  confirmed `+0.338 +/- 0.068` signed levels versus `mc-strong`; the matched
  null was flat.
- **T3 is complete:** it made the human-proposal, mixed-Teacher and small-
  endgame ideas executable and reviewable. It did **not** produce a stronger
  policy. S3a selected none, S4 remains the only live direct-strength test,
  H0 later refused without utility, and Stage C still has zero states or
  labels.
- **T4 objective:** create one genuinely new learned challenger: capture the
  frozen 2,048-state Stage-C curriculum, label it, train at least eight seeds,
  open untouched REPORT once, compose one passer inside report-LCB, and test it
  against the live champion plus a same-work null.
- **Immediate blocker:** the first Stage-C packet failed adversarial review.
  Repaired v2 on PR #9 is frozen at source `debec42` / packet
  `fe79b5bb…6b30f` and needs one exact external PASS before a receipt or state
  capture. The label implementation can advance in parallel, but no label
  packet can bind a dataset that does not yet exist.
- **Fleet:** Mini is occupied by the sealed 2,048-cluster S4 screen. Air is
  free for PR #9 review reproduction and bounded two-card packet work. Fly runs
  production only.

## T3 handoff — compact terminal digest

| T3 output | why we tried it, in plain English | terminal result | what T4 inherits |
|---|---|---|---|
| **S3a structured bury** | Give the point-shy banker deliberate point/void/trump kitty plans and ask whether they improve complete games. | **SELECT NONE.** The selected-state mechanism passed, but the fresh full-game result was `+0.0464`, LCB `-0.0041`. | Preserve disagreement states as diagnostics. Do not retry, tune, pool or promote this consumed recipe. |
| **S4 point banking** | Let rollouts bank a 5/10/K when already winning while retaining higher control. | Exact-state mechanism **PASS** in both roles (`+5.156` points, LCB `+3.029`); the natural full-game screen was reviewed and launched. | One sealed terminal whole-game verdict, still pending. This is a direct-policy side bet, not Teacher evidence. |
| **H0 human/V11 proposal machinery** | Evaluate human, V11 and random suggestions fairly instead of treating source reputation as truth. | Bounded design/controller **PASS** with zero pre-review outcomes. The later one-shot T4 execution completed 555/557 rows and correctly refused aggregate utility. | No human-derived proposal rule. Stage C keeps its separately reviewed V11/structured/random sources. |
| **Teacher Stage C** | Replace broad heuristic imitation with routine anchors plus deeper uncertainty, disagreement, point, bury and tiny-endgame examples. | Design and dependency rebind **PASS**; exact 1,024/512/512 split and finite work frozen; zero states or labels. | One eligible capture-controller implementation, now frozen in PR #9. |
| **S3c small endgames** | Start exact search at a tiny natural problem and grow one card at a time instead of repeating the infeasible four-card jump. | Controller **PASS**; later one-card capacity run completed 64/64 roots and 256/256 worlds with zero refusal/overflow. | Two-card action-selection packet review is open. No action-value or strength claim exists. |
| **Human/evaluation boundary** | Use human play to diversify ideas without contaminating model selection or the eventual human A/B test. | `human_v8` is provenance-verified: 2,830 plays, 45 buries, seven incomplete-round refusals and 25 off-ballot actions. HUMAN-C1 exclusion guards pass. | Human rows remain proposal/DEV evidence only; formal REPORT and future HUMAN-C1 traffic stay disjoint. |

The complete artifact trail and plain-English chronology are in the August 9
daily log. The canonical policy consequences are in `AI_POLICIES.md`; the
research lessons and Teacher lineage are in `RL_PLAN.md`.

## T4 — active output ledger ordered by dependency

T4 closes an end-to-end **attempt**, not another readiness packet. Its success
path ends with one frozen learned composition earning a fresh whole-game screen
PASS against production. Confirmation launch, promotion and deployment remain
separate future authority.

| priority / output | strategy and problem, in plain English | progress so far and what is left | required artifact | exact exit gate |
|---|---|---|---|---|
| **P0 / S4 terminal verdict** | Resolve whether the point-banking rollout change occurs often enough and preserves enough future control to improve complete rounds. | Reviewed 2,048-cluster screen is running on Mini under exact `cad3992`, packet `17036e63…1385`, admission `1d99bb55…bdbf` and receipt `20a420d2…5cc`. Outcomes remain sealed. **Left:** count/status only until all shards stop, then invoke the exact verifier once. | One verifier-authenticated treatment-minus-champion and treatment-minus-null verdict | `AUTHORIZE_CONFIRM_PACKET_REVIEW` opens review of a fresh confirmation packet; `SELECT_NONE` closes v2. Neither result changes T4's Teacher critical path. |
| **CLOSED / T4.1 H0 outcome** | Find supported human/V11 proposals before admitting them into the new Teacher. | The one-shot run ended 555 complete + two validation refusals; aggregate `84ef4400…196c` published no utility. **Left:** none—no retry, row dropping or partial inference. | Receipt `37ab77a9…748c6` plus terminal refused aggregate | Closed fail-safe. No H0-derived conditional proposer enters Stage C. This is not evidence that human or V11 actions are bad. |
| **P0 / T4.2a capture-controller review** | Prove the program will collect exactly the reviewed state population and cannot hide a retagged state, forged priority, fabricated ledger or missing sampler work. | V1 was correctly held. Repaired PR #9 freezes source `debec42`, packet commit `c5d2e0f`, external packet `fe79b5bb…6b30f`; focused 31/31 and cross-lane 153/153 pass, and the real zero-work freeze/recompute matches. **Left:** exact independent adversarial review of v2. | One external `TEACHER_STAGE_C_CAPTURE_CONTROLLER_V2_REVIEW` marker | PASS authorizes one score-free capture receipt only. HOLD returns a named defect; it does not authorize a weakened run. |
| **P0 / T4.2b frozen 2,048-state asset** | Collect the actual hard examples where the live bot is uncertain or missing plausible ideas, while retaining broad ordinary coverage and an untouched exam. | No receipt or state exists. **Left:** after T4.2a PASS, run capture once, replay every selected state and publish quotas/rejections/provenance. | Exactly 1,024 DESIGN + 512 CALIB + 512 REPORT states; 1,920 play + 128 bury; one state/deal; complete manifest and hashes | Every quota, split, candidate cap, exclusion asset and 9,216,000 selection-work ceiling must reproduce. Underfill, drift or retry closes the receipt without a dataset. |
| **P0 / T4.3 frozen labels** | Turn those states into better supervision: cheap labels for ordinary anchors and deeper disjoint comparisons for the hard tail. | Design budget exists, but no label controller, packet or label exists. **Left:** freeze/review a separate label job, run once, verify every accepted world and publish per-surface uncertainty/regret. | Replayable candidate ballots plus paired outcomes under the passed finite-work contract, with selection and report streams disjoint | Labels must bind the exact captured asset, champion, continuation, sampler and work. REPORT remains unopened and cannot tune the Teacher. |
| **P0 / T4.4 eight-seed models** | Test whether the new signal is learnable and stable rather than celebrating one lucky checkpoint. | Not started because labels do not exist. **Left:** freeze one recipe; train at least eight seeds of play ranking and calibrated signed-outcome heads, with bury separate; publish state-count learning curves and seed variance. | Eight-or-more immutable checkpoints per intended head plus DESIGN/CALIB metrics and one CALIB-only selection rule | One frozen recipe/checkpoint rule selected on CALIB. If ranking passes but calibration fails, only ranking/proposal use may advance. |
| **P0 / T4.5 untouched REPORT** | Take one honest exam after all data, architecture and checkpoint choices are frozen. | REPORT is still sealed. **Left:** open its 512 rows exactly once and compare per-surface regret, coverage and calibration with the live Teacher baseline. | One terminal REPORT artifact for the frozen recipe | PASS freezes exactly one bounded learned capability. Failure is classified as data, target, capacity or composition; REPORT is never retuned. |
| **P0 / T4.6 composed whole-game screen** | Put the learned capability inside actual report-LCB search with an incumbent fallback and answer whether the complete bot improves. | No learned capability has passed REPORT. **Left:** bind one passer as proposal/ranking help, add a same-work random/null arm, preflight, review and run one fresh paired screen against live `mc-s0-report-lcb`. | One frozen three-arm complete-round aggregate and terminal verifier result | Positive clustered utility against champion **and** null opens confirmation-packet review. SELECT NONE closes this exact composition. Stop before confirmation launch, promotion or production change. |

## Parallel strength work that must not block T4

| lane | why it matters | progress and what is left | next bounded output |
|---|---|---|---|
| **S3c two-card exact search** | Two-card endings are the first small-domain states with real action choices; exact hidden-world diagnostics could improve late play and future Teacher targets. | One-card mechanics/capacity passed cleanly. **Left:** freeze and externally review a finite two-card action-selection packet; do not launch it yet. | One score-free packet binding multi-action roots, sampled worlds, solver reuse, node/refusal caps, current champion/null and terminal authority |
| **S5 defensive point protection** | Human-loss mining suggests a bot may sometimes donate a point card to an already-lost trick, but the per-seat global headline disappeared after normalization. | Replay code/fixtures passed at PR #4 head `2351b36`; no corpus census exists. **Left:** one deterministic score-free replay census when Air is not needed for T4 review. | Trigger/refusal counts, legal strictly-lower-point alternatives, ballot membership and current champion/rollout reproduction; only a real reproduced trigger may open treatment design |
| **ExperimentSpec extraction** | Recent failures repeatedly came from code/data/authority mismatch. A reusable immutable boundary can make future launches faster without weakening evidence. | Strong one-off controllers exist. **Left:** extract only their common identity/receipt/reopen semantics after the Stage-C capture path proves them end to end. | Tested immutable spec for code, data, policy, ballot, sampler, continuation, actor, seeds, work, metric, null and stop rule |

## Strength-plan guardrails

- **Lane A — direct search:** finish S4; grow S3c one card at a time; run S5
  replay before inventing a new heuristic. S3a and S3b-v2 remain closed.
- **Lane B — stronger Teacher:** this is T4's critical path. Capture new
  hard-tail states, label them under explicit continuation contracts, prove
  multi-seed learning, then test one bounded composition in whole games.
- **Lane C — beyond MC imitation:** Direct-Q and O0/O0-v2 are closed exact
  recipes, not a rejection of RL. A successor must change target/credit,
  decision specialization, curriculum or bounded adaptation and reuse the CRN,
  semantic-replay and eight-seed chassis. It follows the first Stage-C loop
  unless it can run without delaying T4.
- **People-facing destination:** bot-vs-bot evidence is the controlled filter.
  Only a confirmed challenger may enter blinded HUMAN-C1 candidate-versus-
  champion evaluation and the later experienced-human benchmark.

## Active support queue — outside the T4 critical path

| priority | work, progress and what is left |
|---|---|
| **P1 performance** | Release 17 moved speculative search off the room event loop. **Left:** concurrent-room p50/p95/p99 measurement and pure/compiled parity before each next hot-path port (`_lead`, `_current_winner`, `_cheapest_winning`). |
| **P2 sampler correctness** | Bounded hard-validity/support certification passed. **Left:** global constructive dealer completeness/runtime and exact-toy posterior calibration; posterior-changing flags remain off. |
| **P2 data hygiene** | `gen_v4_all` remains the clean v11 source; contaminated banker-private-kitty caches stay quarantined. **Left:** regenerate only from retained raw states and bind replayable state/split/ballot/sampler/continuation/actor hashes for every future dataset. |
| **P2 training throughput** | Current `bc_train` loop is MPS-dispatch-bound. **Left:** vectorize only after the Stage-C recipe is frozen enough to measure semantic parity and end-to-end savings. |
| **P3 product correctness** | Reconnect/takeover and HUMAN-C1 no-traffic boundaries have focused tests. **Left:** spectator privacy, trick history/replay, remaining reconnect/takeover edges, frontend CI and portrait/zh-CN polish as separate product lanes. |
| **P3 documentation** | Handoff ledgers, jobs and top-level strategy docs were compacted; T3 detail moved to the daily log. **Left:** keep completed run bodies archived and top-level files limited to current operational truth. |

## Parked or closed — do not silently re-queue

- **HUMAN-C1 traffic is parked** until a challenger beats report-LCB in fresh
  bot confirmation and a separate launch packet receives explicit authority.
- Formal S0c is unread and nonretryable; independent RLCB-C1 supports
  production. N=30 beat N=10 twice; N=60 did not establish an increment.
- DEV-512 generic widening, V11 direct/protected-anchor, Direct-Q 144M,
  O0/O0-v2/O1, S3a and S3b-v2 are closed exact recipes. New work must name a
  changed mechanism, not rerun an inspected stream.
- Value-leaf, pairwise-as-scalar-leaf, generic widening and learned root-prior
  racing have no current promotion path.
- Correctness, faster simulation, larger corpora and green pipelines enable
  strength work; they are not themselves AI wins.

Standing rule: a screen may reject or select one frozen design. Only a fresh,
paired, clustered confirmation against the exact deployed champion can
establish strength, and only a separately reviewed production packet can ship
it.
