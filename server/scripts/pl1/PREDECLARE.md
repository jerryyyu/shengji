# PL1 predeclaration (written 2026-11-17 before any main-sample S136 likelihood was computed)

Row PL1 (levers scan, `levers1/ROWS.md` section 4; Jerry 2026-11-17 approved the lever lanes): reweight belief-sampled
worlds by the *acting search's* likelihood, modelled by the S136 net, instead of the R51 prior FT1 (S112/S113/S135).
Tier-i DEV, offline, no duel. Card-location accuracy is a proxy; no strength claim follows from any outcome.

## What is measured
- **Points:** S112's `points.jsonl` (sha256 `d7236fc3...f45ca27fe523a3d068326921b291bdf73845f38`), 2,400 points / 200 R51
  self-play deals; the 2,394 with a hidden copy are scored (S112/S113 convention).
- **Candidates:** S113's B1a proposals, reproduced in a detached worktree at S113's commit `7fc61e95` (compiled engine built in
  place) by S113's own code (`s113lib.py` with only the worktree path changed; `draw.py` = S113's `score.py` minus the
  likelihood). Witness: base and B1a 64-world accuracy are **bit-identical to S113's `main_rows.jsonl` on all 2,394 points**;
  the unweighted 2,048-candidate accuracy matches on 2,393 and differs by 8e-6 on one point (93112133510; its candidate draw
  is not reproduced exactly, recorded as is). Per candidate, the agreement with the true deal (`pv_soft_oracle.agreement`) is
  stored, so accuracy of any weighting is exact.
- **Likelihood (the one change from S113):** per candidate world, the sum over every past card play t by a seat other than the
  observer of log softmax over the seat's legal plays under the hypothesized hand at t, of the play's sum of card log-odds, the
  played (submitted) action forced in, -inf if illegal. This is S113's `teacher_loglik` form exactly (closed-form leads, full
  follow listing). The card log-odds come from the **S136 net's policy head** (trunk + `p_head` of `sf-s136-516617b8.npz`,
  sha256 `516617b8...a8d184`, the S136 duel package, trained on Y's search choices) on the seat's information set at t
  (`belief_numpy.decision_inputs` with the hypothesized hand), instead of FT1. The S136 *candidate* head is not used: it scores a
  short admitted list, not every legal play, so it gives no normalised likelihood over the legal set; scoring every legal lead
  with it is not affordable here.
- **Implementation checks (pilot points only, `scripts/test_pl1.py`, rc 0):** the batched hand-patched inputs equal
  `decision_inputs` on a root clone exactly (2,240 checks: X max |diff| 0.0, mask and row-card planes equal), and the batched
  torch policy logits equal `UnifiedNumpy.policy_logits` within 2.4e-5.
- **M = 512** (the first 512 of S113's 2,048 candidates per point), not 2,048: measured 0.74 ms per (world, past play) on one
  thread; 2,048 would need ~6.3 h on the 4 allowed threads. S135 served M = 512.
- **Weights:** w = (1 - alpha) * softmax(tau * ll) + alpha * uniform over history-legal candidates.
  Grid tau in {0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0}, alpha in {0, 0.05, 0.1, 0.25, 0.5}.
- **Cross-fit tuning (disjoint split):** deals split by sha256("pl1|fold|<deal>") mod 2. On each fold choose the cell with the
  highest pooled weighted q_eff subject to median Kish ESS >= 16; apply it to the OTHER fold. The headline pools both folds.
- **Headline accuracy:** 64 worlds resampled (multinomial, rng seeded by sha256("pl1|resample|<model>|<point>")), q_eff =
  (acc - acc_base)/(1 - acc_base) on pooled means, base = bceil arm C fill; deal-clustered percentile bootstrap, 2,000
  resamples, seed 112; paired (S136 - B1a) on the same resamples. B1a = S113's re-scored 64 worlds (q_eff 0.2256).
- **Control (descriptive, no bar):** FT1 likelihood (S113's `teacher_loglik`, unchanged, R51 tree) on the same 512 candidates,
  same grid and cross-fit. Also descriptive: tau = 1, alpha = 0 weighted accuracy for both, phase/lead-follow slices.

## Bar (from the row; applied mechanically by `scripts/analyze.py`, run once)
- **PASS** iff S136 q_eff >= **0.27** AND median Kish ESS of the applied weights >= **16** (the row's "ESS >= 16 of 64
  worlds"; Kish ESS over the 512 weighted candidates) AND the paired (S136 - B1a) 95% LB > 0.
- **KILL** iff S136 q_eff < **0.26**: park policy-likelihood inference for good.
- Otherwise FAIL (no duel; not killed).
- If PASS: write the DEV duel packet (1,000 paired deals vs R52, bar mean >= +0.02 and LB80 > 0, fresh seeds); do not run it.

## Files fixed by this predeclaration (sha256 in `SHA256SUMS.prerun`)
`scripts/pl1lib.py`, `scripts/score_s136.py`, `scripts/score_ft1.py`, `scripts/analyze.py`, `scripts/draw.py`,
`scripts/s113lib.py`, `scripts/test_pl1.py`, `models/sf-s136-516617b8.npz`.
