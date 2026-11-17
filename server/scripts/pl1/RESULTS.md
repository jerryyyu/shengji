# PL1 result (2026-11-17, this Mac, 4 single-thread workers at nice 10; read once): **FAIL, not killed**

Predeclaration `PREDECLARE.md` sha256 `4a8e407cc11c5549911eae85e8dab3d38ff322b08bbba6264c3a35e048ea68ed`, written
15:58:19Z, before any S136 likelihood was computed on the main sample. Every file in `SHA256SUMS.prerun` was verified
unchanged before the read. `scripts/analyze.py` ran once, rc 0. `results/pl1_results.json` sha256 `888e80ce...0ef2`.
Branch `claude/pl1` 21cd324e8e1466d8e7ce1074398b1a72e4ccf706 (code only; pushed, no PR).

## Headline (2,394 points / 200 deals, M = 512 B1a candidates, 64 resampled, cross-fit tau/alpha)

| method | q_eff | 95% CI | minus B1a [95%] |
|---|---|---|---|
| B1a (served R51 belief, S113 re-score, bit-identical) | 0.2256 | [0.2183, 0.2332] | |
| first 512 candidates, unweighted (control) | 0.2265 | | +0.0008 [-0.0004, +0.0020] |
| FT1 prior likelihood (S113's method, same 512 candidates, same tuning) | 0.2540 | [0.2461, 0.2618] | +0.0283 [+0.0255, +0.0313] |
| **S136 policy-head likelihood (PL1)** | **0.2657** | **[0.2567, 0.2749]** | **+0.0400 [+0.0363, +0.0436]** |

- **Bar:** q_eff >= 0.27: **no** (0.2657). Median Kish ESS >= 16: yes (26.5). Paired LB > 0: yes. The kill line is q_eff < 0.26,
  and 0.2657 is above it. So the verdict is **FAIL (not killed)**: no duel, no packet.
- Both folds independently chose **tau = 1.0, alpha = 0**, the top edge of the grid (fold q 0.269 / 0.263). Weighted q rises
  monotonically in tau while ESS falls: tau 0.5 → 0.260 at ESS 124, tau 0.75 → 0.266 at ESS 54, tau 1.0 → 0.269 at ESS 26.
  Mixing in uniform weight (alpha > 0) always lowered q.
- S136 vs FT1, paired (descriptive, weighted, tau 1): **+0.0121 [+0.0086, +0.0154]**. The acting-search model is a better
  likelihood than the prior: about 1.4 times FT1's gain over B1a.
- Concentration: the median ESS is 26.5 of 512 (FT1 79), 37% of points fall below 16 (FT1 7%), and the median distinct
  worlds among the 64 is 35 (FT1 48). That is sharper than FT1 but less concentrated than S135's 12.9 of 512 at tau 2.
- FT1 at M = 512 gives +0.0283, which matches S113's +0.0286 at M = 2,048. For FT1, M is not what limits the gain.

## Slices (q_eff; deal-clustered 1,000 resamples)

| slice | B1a | FT1 | S136 | S136 - B1a 95% |
|---|---|---|---|---|
| early tricks 0-7 | 0.148 | 0.167 | 0.166 | [+0.016, +0.022] |
| mid 8-16 | 0.312 | 0.353 | 0.374 | [+0.055, +0.069] |
| late 17+ (110 pts) | 0.442 | 0.461 | 0.566 | [+0.080, +0.166] |
| leads | 0.216 | 0.245 | 0.260 | [+0.037, +0.052] |
| follows | 0.229 | 0.257 | 0.268 | [+0.035, +0.043] |

S136's advantage over FT1 comes entirely from mid and late tricks. Early in the round the two are equal, and there the gain
is small for both (+0.018).

## Validity and deviations
- Candidates came from S113's own code at its commit. Base and B1a accuracy are bit-identical on all 2,394 points. The
  2,048-candidate mean differs on one point (93112133510, 8e-6), which is recorded. Zero candidates had -inf likelihood.
- On pilot points only: the hand-patched inputs equal `decision_inputs` exactly (2,240 checks), and the torch logits match
  `UnifiedNumpy.policy_logits` within 2.4e-5.
- **M = 512, not the row's 2,048.** This is compute-bound: 0.74 ms per (world, past play) on one thread.
- The S136 *policy head* (card log-odds over the full legal set, S113's likelihood form) was used, not the candidate head,
  which has no normalised likelihood over the legal set.
- Operational: after the FT1 control finished, one reverse-order helper worker (`score_s136_helper.py`, the same computation,
  added after the predeclaration) took over its thread. 208 points were computed twice, and the rows were identical (ESS,
  zero count and play count match on all 208). The overlapping workers were stopped once all 2,400 files existed, and every
  file was validated (shape 512, no NaN).
- The points are R51 self-play deals (S112), so the acting policy there is R51's search. S136 was trained on Y's search choices.
- Card-location accuracy is a proxy. No strength claim follows.

## Reading and next step
Swapping the prior for the acting-search model moved policy-likelihood inference from +0.028 to +0.040 q_eff, short of the
+0.044 that the 0.27 bar needs. The tuning sits on the grid's tau edge with ESS falling. The one cheap untested direction is
the row's own M = 2,048 (more candidates let a sharper tau keep ESS ≥ 16), which would be about 6 h on the Ultra with
`scripts/score_s136.py` unchanged. By the bceil local slope, the gain would still be about +0.03 levels/round at best, and
S135 showed that concentrated resampling can lose in play. Running it is a judgement call, and no pre-registered bar requires
it.
