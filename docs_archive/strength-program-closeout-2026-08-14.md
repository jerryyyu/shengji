# Strength program closeout — 2026-08-14

## Bottom line

This program did **not** establish a stronger Shengji bot. It established that
the measurements were trustworthy, closed three plausible policy recipes with
honest negative results, and made the engine materially faster. Those are useful
outputs, but none is a substitute for a whole-game strength win.

The live `mc-s0-report-lcb` champion remains the only policy with a confirmed
promotion result. No T4, S4, or S6 candidate advances. Pair-aware continuation
is still running on Air and remains unresolved until its sealed terminal gate
completes or times out.

## What completed

| lane | terminal result | conclusion |
|---|---|---|
| **T4 learned mid/late proposal** | `SELECT_NONE`; treatment-vs-champion mean `+0.01611`, LCB `-0.00759`; treatment-vs-matched-null mean `-0.00977`, LCB `-0.03313` | The selected-state signal did not transfer to whole games. The same-work uninformed proposal beat champion on this population, so generic ballot widening—not the learned source—explained the useful signal. |
| **S4 point banking** | `SELECT_NONE` after a clean 16,384-cluster, two-look confirmation | The mechanism was real but too sparse and/or too small to clear the final efficacy boundary. Its observed decision incidence was about `0.7%`, which sharply limited its whole-game ceiling. |
| **S6 shuai-pai sourcing** | `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN` after reconstructing all 64 scored DEV records | The bury-source arm passed every registered diagnostic, but the lead-source arm failed three. This preserves a bury-side hypothesis; it does not justify the combined selector, a fresh screen, or a strength claim. |
| **Pair-aware continuation** | still running, sealed | No conclusion yet. Selected-root promise is not whole-game evidence. The admitted Air run must finish or fail closed without intervention; a separately reviewed checkpoint successor remains operational contingency, not a strength result. |
| **Performance** | production extraction measured `29.3203%` lower wall on its exact stack; PR #103 measured a further `3.4074%` on x86 | The engine is faster with exact normalized behavior. Faster evidence generation is an enabler, not evidence that the bot chooses stronger moves. |

## Strategic failure pattern

The repeated failure was not primarily experimental sloppiness. It was a
transfer problem between attractive local mechanisms and complete-game value:

1. **Selected states overstated transport.** T4 and earlier S6 screens found
   conditional signal, but natural whole rounds diluted or changed it.
2. **Causal controls mattered.** T4 could not beat a literal same-work,
   uninformed proposal. The model's apparent benefit was not attributable to
   learned targeting.
3. **Natural dose was too small.** S4 affected roughly `0.7%` of decisions.
   Even a useful conditional action had little room to change the game-level
   estimator.
4. **Continuation assumptions were fragile.** S6's bury-side evidence survived
   while lead-side alternative-continuation checks did not. A signal under one
   proxy policy is not yet a robust policy improvement.
5. **Too many candidates stayed inside the same search scaffold.** We tested
   several tactical patches to proposal generation and rollout behavior. That
   produced valuable diagnosis, but not a sufficiently different decision
   system to move whole-game strength reliably.

The review and one-shot gates were expensive, but they were not wasted. They
caught stale caches, unsafe native boundaries, authority bugs, malformed
receipts, calibration mistakes, and several false-positive interpretations.
The process should now become smaller and more consolidated—not weaker.

## Entry criteria for the next strength goal

Do not begin another large whole-game campaign until a candidate satisfies all
of these on fresh DESIGN/CALIB evidence:

1. **Natural-dose economics:** measured trigger dose multiplied by a
   conservative conditional effect exceeds the intended whole-game minimum
   detectable effect with margin.
2. **Causal source attribution:** treatment beats both the literal champion and
   a same-work matched null; merely widening the action set is not enough.
3. **Robust continuation:** the conditional sign survives at least two named
   continuation models or the role/phase strata that matter naturally.
4. **Transport story:** the design states why the mechanism should change full
   rounds, which decisions carry the effect, and what could cancel it.
5. **One consolidated review chain:** review source plus a concrete frozen
   design together when possible; use one execution admission and one terminal
   review. Add a second layer only when it protects a materially different
   boundary.
6. **A genuinely different axis:** prefer belief/world modeling, value inside
   search, or decision-type compute allocation over another small isolated
   heuristic in the same rollout scaffold.

## Immediate disposition

- Close the exact T4, S4, and combined S6 recipes. Do not retry, pool, or tune
  their spent evidence.
- Let the existing Air Pair screen reach its frozen terminal condition. Do not
  resize or extend it.
- Preserve S6 bury-source states and T4 matched-null behavior only as labelled
  hypothesis inputs.
- Land reviewed behavior-identical performance work separately from strength
  policy changes.
- Pause new scored strength launches after Pair terminalizes. Choose the next
  milestone explicitly from the entry criteria above rather than filling idle
  machines with another underpowered mechanism.

This closeout ends the current campaign without declaring the research area
dead. It changes the standard for what earns the next expensive run.
