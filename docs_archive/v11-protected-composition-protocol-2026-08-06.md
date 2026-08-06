# V11 protected-composition protocol — blind amendment

Predeclared 2026-08-06 13:45 EDT. At declaration time the frozen direct-V11
block had produced one of eight final shard manifests, but no final manifest,
record, shard effect or aggregate had been opened by Codex. Only completion
counts were inspected. This document does not change or reinterpret the frozen
direct block's registered verdict.

## Why this is a separate question

The direct block asks whether the standalone `rl-override-v11pair` policy beats
today's search champion. The protected composition asks whether v11's proposal
is useful *after* the terminal S0 champion applies its complete search and
fixed safety rule. Standalone superiority is sufficient but not logically
necessary for complementarity: search can reject bad learned proposals while
retaining good ones. Therefore:

- the direct block must still be aggregated under its original rule and its
  stored `anchor_test_authorized` bit must never be rewritten;
- a protocol-valid direct block with a sane matched-null interval may admit
  this separately declared, non-promotable composition screen even when the
  standalone v11 superiority criteria fail; and
- any direct protocol/counter failure or a matched-null interval excluding
  zero holds the composition lane. It may not be repaired by extending or
  replacing seeds.

## Screen: mechanism evidence only

Run only after both parents are terminal: the frozen direct block has a valid
aggregate and S0 has named its terminal production champion. Freeze the exact
terminal S0 receipt/packet hashes, executable commit/runtime, v11 checkpoint
SHA-256 and champion policy contract in every shard.

- Name: `v11-protected-composition-screen-v1`.
- Population: exactly 2,048 fresh mirrored deal clusters, eight shards of 256,
  contiguous seeds 137,000,000–137,002,047.
- Opponent: the terminal S0 champion.
- Four common-seed labels: champion-matched v11 protected anchor,
  champion-matched same-trigger random anchor, the literal terminal champion,
  and a champion-matched distinct-RNG true null.
- Work: every label copies the terminal champion's complete search/ballot,
  rollout, allocation and exact-work contract. The protected arms may change
  only candidate-zero ordering on the frozen v11 trigger. No pruning, new
  candidates, v11 scalar leaf or changed continuation is allowed.
- Validity: exact seed/flip coverage; clean compiled+strict runtime; one ballot
  identity; digest-pinned checkpoint and parents; zero failed/rejected worlds,
  short searches, zero-world fallbacks or void fallbacks. Any violation holds
  the whole block.
- Statistics: paired signed level utility clustered by deal seed, two-sided
  normal 95% intervals using the registered evaluator's `1.96 * SE` rule.

The screen authorizes one independent confirmation only when all four checks
pass:

1. protected-anchor minus terminal champion lower bound is greater than zero;
2. protected-anchor minus same-trigger random-anchor lower bound is greater
   than zero;
3. protected-anchor minus champion-matched null lower bound is greater than
   zero; and
4. champion-matched-null minus champion interval contains zero.

The screen is explicitly non-promotable. Failure or an interval touching zero
is `HOLD`; there is no seed extension, alternate threshold or post-hoc subset.

## Confirmation: production-strength evidence

Only a passing screen may launch
`v11-protected-composition-confirmation-v1`: exactly 8,192 independent mirrored
clusters, eight shards of 1,024, contiguous seeds
138,000,000–138,008,191, with the same four labels, contracts, validity checks
and four statistical criteria. The screen and confirmation may not be pooled.

A clean confirmation PASS makes the exact protected-anchor policy eligible for
the normal production review against the terminal champion. It does not deploy
or restart Fly automatically. A failure leaves the terminal S0 champion in
production and closes this frozen composition attempt without extension.
