# Active Claude/Codex handoff

> **CANONICAL PATHS:** both agents coordinate only through
> `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. Branch-local copies are
> never review authority. Raw markers belong in `HANDOFF_REVIEW.md` at column
> 1 and must occur exactly once.
>
> **LOSSLESS ARCHIVE:** the 726-line prior active ledger is preserved in
> `docs_archive/handoff-active-through-2026-08-11-10-22.md`; the 5,807-line
> review history is preserved in
> `docs_archive/handoff-review-2026-08-08-through-2026-08-11-10-22.md`.

Last reconciled: 2026-08-11 11:12 EDT.

## Current T4 objective

Produce the first fresh whole-game challenger built from the Stage-C Teacher:
evaluate the already-trained broad-play capability once on untouched REPORT;
if and only if it passes, compose it inside live report-LCB with candidate-zero
fallback and a same-work null, then screen it against `mc-s0-report-lcb`.
Stop before confirmation, promotion or production deployment.

## Current truth

| area | plain-English status | next gate |
|---|---|---|
| S4 point-banking | Terminal `SELECT_NONE`: positive direction but replication LCB crossed zero. Never retry or extend it. | Closed; diagnostic only. |
| H0 human proposer | Terminal no-use after 555/557 and incomplete aggregate. No human-derived proposer was admitted. | Closed; future human data needs a new packet. |
| Stage-C capture/labels/training | Complete and independently reviewed: 2,048 split-safe capture states; expanded 7,040-state labeled asset; eight-seed training cohorts; REPORT kept separate. | Closed prerequisites. |
| Protected play policy | Fresh 480-state REPORT lost (`-0.00823`, LCB `-0.01894`). | Closed `SELECT_NONE`; never reuse REPORT. |
| Expanded bury policy | Terminal `SELECT_NONE`, independently reviewed: mean `+0.03381`, LCB `-0.01525`, zero refusals, 264,128 exact worlds. | Closed; never retry, extend, compose or reuse its REPORT. |
| Broad-play successor | Epoch-32 all-pairs play ensemble is positive on DESIGN and CALIB in 8/8 seeds. Its score-free capability packet froze from clean PR #34 head `3359b8c` and re-verifies with REPORT unopened. | **Only open review:** independent capability replay and raw `TEACHER_STAGE_C_EXPANDED_PLAY_CAPABILITY_V1_REVIEW`. |
| Fleet | Mini and Air have no active Teacher/S4/duel workers as of this reconciliation. | Keep idle until an authorized packet exists; do not invent a run. |

## Broad-play successor: frozen design, not yet evidence

- Training evidence: DESIGN mean `+0.00904007`, one-sided LCB `+0.00541917`
  over 5,120 play states; CALIB mean `+0.01047974`, LCB `+0.00336018` over
  1,280 play states; all eight seeds positive.
- Fresh fifth REPORT selection: 480 play, zero bury, zero state/deal overlap
  against 2,048 spent REPORT rows; selection SHA `4f7b4ec0…7787`.
- Coverage: 132 ordinary anchors, 94 champion-uncertainty, 128 proposal
  disagreements, 42 point-banking opportunities and 84 exact-late states;
  136 early / 146 mid / 198 late; 248 attacker / 232 defender; 236 lead / 244
  follow.
- Source-only PR #34 includes capability and separate one-shot REPORT
  controller/runtime/supervisor. Capability packet `cd2d5102…a3e82` is frozen
  and verifies `VERIFIED_NO_REPORT_OPEN`; no REPORT controller packet,
  admission, label, prediction or utility exists.

## Exact execution order

1. Claude independently reviews the frozen score-free capability and appends
   the exact raw PASS or a concrete HOLD. A PASS may authorize one downstream
   controller freeze, not REPORT execution.
2. Codex authenticates and snapshots that raw line, then freezes the separate
   play REPORT controller; Claude reviews its exact
   packet and command/runtime boundary.
3. Codex consumes one durable REPORT-open admission and runs eight 60-state
   shards on Mini. No retry or reuse after admission, including failure.
4. Claude independently recomputes the terminal REPORT decision.
5. Only a positive predeclared action-utility LCB may authorize composition.
   Outcome NLL, strata and individual examples remain diagnostic.
6. Compose the passing play capability inside report-LCB, preserving the live
   incumbent/candidate-zero fallback and a trigger-matched same-work null.
7. Run the fresh whole-game screen against live `mc-s0-report-lcb`; stop before
   confirmation or deployment regardless of outcome.

## Parallel but non-blocking work

- Broad-play composition source is ready in draft PR #33 at `d13ddc6`,
  stacked on PR #34. The obsolete bury profile was replaced with a disjoint
  play profile; external REPORT/training worktrees are authenticated before
  use; the relevant controller/runtime/composition suite passes 94/94. Its
  external-boundary test proves both that a weak terminal marker cannot reach
  the outcome-opening verifier and that exact reviewed evidence can replay
  successfully. It freezes nothing and remains gated on a positive
  independently reviewed play REPORT result.
- S6 shuai-pai source is production-inactive in draft PR #19. Latest focused
  sourcing suite passes 12/12, but the branch needs rebase/external source
  review and then a trigger-matched strength screen. It does not block T4.
- Repository/docs hygiene remains isolated in draft PRs #30/#31. Do not merge
  evidence-sensitive branches merely to reduce branch count.
- A larger Teacher dataset is a justified next learning-curve step only after
  this fresh play REPORT: scale broad play (roughly 5k → 10k → 20k), keep bury
  separate/small, and improve candidate sourcing alongside volume.

## Standing invariants

- Never inspect interim outcomes from a sealed run.
- REPORT populations, deal seeds and labels are single-use; siblings from a
  partially opened population count as spent.
- Freeze, external review, admission, execution, terminal review, composition,
  whole-game screen, confirmation and deployment are separate authorities.
- A source PASS is not run authority; a positive diagnostic is not strength.
- Preserve immutable evidence worktrees and snapshots. Never clean or rebase
  a worktree containing ignored evidence without a byte inventory.
- Prefer Mini for runs under one hour; every long job must emit durable,
  frequent progress and own signals/children explicitly.
