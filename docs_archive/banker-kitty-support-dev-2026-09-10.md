# Banker declaration support: opt-in correction, not a production rollout

Follow-up to [issue326](https://github.com/jerryyyu/shengji/issues/326).
Base `2024bddf`; source lives in `train/banker_kitty_sampler.py`. No existing
Memory/encoder/sampler/registry source is modified. No deployment or change to
running generators, and no strength claim.

## Semantics

If the declarer is not the banker, its still-unplayed shown cards remain
pinned to its hand. If the actor is the banker, its actual hand and burial
remain private known information. Both paths retain the exact old RNG stream.

For a non-banker observing a banker declaration, the hard fact is a lower
bound across **banker hand plus hidden kitty**. Remove only the incorrect
hand-only pin from a local copy of Memory. Draw from the existing proposal
and accept only worlds satisfying that union bound. Subtract the banker's
public plays, not another player's copy of the same card. The helper never
reads the true opponent-private burial. Original Memory is not mutated.

The proposal is rejection-conditioned, not uniform or an exact posterior.
Rejections count as failed/rejected attempts, not accepted worlds. Existing
attempt/deadline limits remain in charge; underfill is not silently accepted.
The opt-in mixin precedes CWVShortlistBot/CWVBuryBot in the class hierarchy,
so cheap ranking and final MC use it. Bury helpers are unchanged: their actor
is the banker. This is not yet a registered data-generation recipe; a later
consumer must name the changed sampler semantics, not reuse an old policy ID.

## What was measured

- The natural seed4/rank2 legal counterexample confirms the old sampler
  forbids the true zero-S2 banker hand after S2 is buried. New tests admit
  banker-count0 and positive banker counts while enforcing the union bound,
  for both single and pair declarations.
- In the retained1,976-round hybrid-bury DEV corpus,513 rounds had a banker
  declarer. **Zero** buried any declared card. Thus the constructed defect is
  not a measured false hand pin in this corpus, and it does not explain a
  claimed failure of that bury experiment. No live-human prevalence is known.
- On the first52 corpus indices, both proposals supplied1,664/1,664 requested
  worlds. Baseline used1,664 attempts; correction2,908. Python sampler CPU was
  0.1750s versus0.3444s, wall0.1758s versus0.3508s on a contended Mini.
  This small one-pass probe suggests overhead; it is not a stable benchmark,
  end-to-end W32 slowdown estimate, or evidence of improved gameplay.

Preserved raw report:
`~/shengji-archive/2026-09-10/declare-belief-dev-20260910.gzyIgY/banker-support-panel52.json`.
Input corpus: `~/shengji-archive/2026-09-09/bury-allrank.QOpPMY/`.

## Validation and next steps

Ten focused tests exercise complete-world acceptance, card/hand conservation,
actor isolation under hidden twins, non-banker and actor-banker stream parity,
rejection/counter/cap wiring, W32 ranking plus MC sampling, and census arithmetic.
The W32 test uses synthetic scores to keep it cheap; it proves dispatch, not
model quality. An independent bounded review found no blocking defect in the
mixin and its9 sampler/consumer tests.

Next: retain this as an explicit sampler treatment in the saved-state W32
belief diagnostic; measure admissible-world support and decision effects
before any gameplay/production adoption. If rejection becomes material,
optimize conditional assignment separately without weakening the support rule.
New belief training must not silently reuse the old banker-hand-only mask.

```sh
PYTHONPATH=server python -m pytest -q server/tests/test_banker_kitty_sampler.py server/tests/test_banker_support_panel.py
PYTHONPATH=server SHENGJI_REQUIRE_VOIDS=1 python -m shengji.train.banker_support_panel /path/to/bury-corpus --sample-states 52 --worlds 32 --out /fresh/report.json
```
