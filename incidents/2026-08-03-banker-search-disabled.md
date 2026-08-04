# Banker MC search silently disabled by BANKER_KITTY (2026-08-03)

**Severity: P0 for measurement.** Found by Codex in the frontend/banker
review handoff, ~21:40. Live for roughly 40 minutes (~21:05–21:48).

## What broke

`BANKER_KITTY` taught `Memory` that the banker's own buried 8 cards are
known information, so they were removed from `unseen`. But `MCBot._sample_hands`
already subtracted that same burial from the pool for the banker seat:

```python
pool = list(mem.unseen.elements())
if seat == rnd.banker:
    pool = list((Counter(pool) - Counter(rnd.buried)).elements())   # second time
```

Counter subtraction clamps at zero, so the second subtraction did not remove
the banker's own cards (already gone) — it removed **opponents' genuine
copies** of those ranks. The pool ended up 8 cards short of the 75 slots it
had to fill, so every retry failed the size check, `_sample_hands` returned
`None` for all 30 determinizations, and:

```python
if n_worlds == 0:
    return candidates[0]
```

The banker returned candidate 0 — the heuristic baseline — with **no search
at all**. Measured directly: `sampled_ok = 0/20` on every seed tried.

## Why nothing caught it

1. There was no conservation invariant. The sampler treated "cannot build a
   world" as a routine miss (it is, occasionally, under void constraints) and
   had no way to distinguish that from "cannot EVER build a world."
2. The failure path was a silent fallback, not an error.
3. Every duel still produced a plausible number. `q_banker_kitty` read 50%,
   `q_kitty2` 46%, `q_kitty3` 54% — noisy-looking results that invited a
   "not decisive at n=300" reading rather than "arm A is not searching."

This is the fourth instance of the same class this week: **an artifact that
looks like a result but is produced by code that is not doing the work.**
The standing rule (verify the artifact, not the exit code) was applied to job
logs but not to the semantics of the number in the log.

## Blast radius

- **gen-v4 training data (1.96M decisions): CLEAN.** `META.json` records
  `teacher_git = 367a822` (13:23), which has zero occurrences of `own_kitty`;
  generation finished 16:46, well before the bug. The per-shard provenance
  manifest Codex asked for is what made this answerable in one command
  instead of a re-generation.
- **The three kitty duels: INVALID.** They compared "banker with kitty
  knowledge" against "banker without" — but the first arm had search
  disabled, so they measured *no-search vs search*, not the kitty question.
  The AI_POLICIES entry claiming a pooled 49.8% has been retracted.
- **v10res residual battery (21:32): number invalid, verdict safe.** The mc
  opponent's banker was weakened, so 45% vs mc OVERSTATES v10res; it is
  rejected on its own preregistered bar anyway (47% vs smart, and it must
  beat smart, being smart-plus-an-override).
- **Prod: unaffected** — none of this is deployed.
- **Golden histories:** `mc-13` legitimately changed (first divergence is at
  the banker seat, play 11); `heuristic-11` and `smart-12` are bit-identical.
  Regenerated in the fixing commit per the file's own rule.

## Fix

`Memory` now exposes `own_kitty_known`, and the sampler subtracts the burial
only when Memory has not already excluded it. Added a hard conservation
invariant that turns this class of bug loud instead of silent:

```python
assert len(pool) == sum(sizes.values()) + kitty_slots
```

Plus `MCBot.last_n_worlds` (0 means no search happened) and an opt-in
`SHENGJI_STRICT_SAMPLING` that raises instead of falling back.

`tests/test_banker_sampler.py` covers the three cases Codex specified:
kitty counted once with full multiset conservation, banker decisions
actually evaluating `N_DETERMINIZATIONS` worlds, and an ENC_VERSION contract
test asserting the RL observation did **not** silently gain the burial while
`ENC_VERSION` stayed 1.

## Lesson

Any invariant that is cheap to state ("the pool must exactly fill the seats")
should be asserted at the point of use, not inferred from downstream results.
A search that quietly returns its fallback is indistinguishable from a search
that ran — the numbers keep flowing, and they are all wrong.
