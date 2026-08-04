"""Disjoint belief-world folds for the lead-ballot pilot.

BALLOT_PLAN Phase 2 requires three folds that never share a world:

  1. **proposal** — only arms that SEARCH for proposals may look at it;
  2. **oracle-selection** — picks the reference action from the union of every
     arm's ballot plus a wider mutation set;
  3. **report** — estimates each arm's chosen action, and the frozen reference
     action, on worlds nothing has looked at.

The reason is the failure this project has hit repeatedly under a different
name. If an arm proposes on the same worlds that score it, the maximum it
selected is biased upward by exactly the noise it selected on, and a wider
ballot wins for having more draws rather than better actions. That is the
select-and-test-on-the-same-worlds defect that made the high-N corpus's `best`
and `gap` columns unusable, and a wider-ballot arm is precisely the shape that
would exploit it.

Disjointness here is STRUCTURAL, not incidental. Each fold draws from its own
named RNG stream, derived by hashing (salt, state key, fold name) so that:

  * drawing from one fold cannot advance another — the historical
    `Ordering._dcache`-style coupling where two consumers shared a generator
    and one silently shifted the other;
  * the same state always yields the same worlds, so a rerun reproduces;
  * two different states never collide, because the state key is in the hash.

Worlds are compared by a canonical key and asserted disjoint, rather than
assumed disjoint because the streams differ — different streams CAN produce
the same world, and for a constrained late state the legal space is small
enough that they sometimes will.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

FOLDS = ("proposal", "oracle", "report")


def stream_seed(salt: str, state_key: str, fold: str) -> int:
    """Deterministic, independent seed for one (state, fold) stream.

    Hash-derived rather than `base + offset`: an additive scheme collides as
    soon as two states are `offset` apart, and the collision is invisible.
    """
    if fold not in FOLDS:
        raise ValueError(f"unknown fold {fold!r}; expected one of {FOLDS}")
    h = hashlib.sha256(f"{salt}|{state_key}|{fold}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def world_key(hands, extra) -> tuple:
    """Canonical identity of a sampled world, seat-aware.

    Seat-keyed because seats are not interchangeable — they carry different
    voids and caps — and sorting the hands together would call two genuinely
    different worlds equal.
    """
    return (tuple(sorted((s, tuple(sorted(cards))) for s, cards in hands.items())),
            tuple(sorted(extra)))


@dataclass
class FoldedWorlds:
    """Worlds for one state, partitioned into folds that share nothing."""

    state_key: str
    worlds: dict = field(default_factory=dict)     # fold -> list[(hands, extra)]
    rejected: int = 0
    collisions: int = 0

    def keys(self, fold: str) -> set:
        return {world_key(h, e) for h, e in self.worlds[fold]}

    def assert_disjoint(self) -> None:
        seen: dict = {}
        for fold in FOLDS:
            for k in self.keys(fold):
                if k in seen:
                    raise AssertionError(
                        f"{self.state_key}: a world appears in both "
                        f"{seen[k]} and {fold}. Folds must share nothing — "
                        f"an arm that proposes and is scored on the same world "
                        f"is measuring its own selection noise.")
                seen[k] = fold


def draw_folds(bot, rnd, seat, mem, counts: dict, *, salt: str,
               state_key: str, max_attempts_factor: int = 40) -> FoldedWorlds:
    """Draw `counts[fold]` distinct worlds per fold, sharing none.

    Each fold gets its OWN bot RNG state, restored afterwards, so drawing the
    report fold cannot shift what the proposal fold would have produced. A
    world already claimed by an earlier fold is skipped rather than reused,
    and the skip is counted — silently reusing it is the whole defect.
    """
    out = FoldedWorlds(state_key=state_key)
    claimed: set = set()
    saved = bot.rng.getstate()
    try:
        for fold in FOLDS:
            want = counts[fold]
            bot.rng = random.Random(stream_seed(salt, state_key, fold))
            got: list = []
            seen_here: set = set()
            attempts = 0
            while len(got) < want and attempts < want * max_attempts_factor:
                attempts += 1
                sampled = bot._sample_hands(rnd, seat, mem)
                if sampled is None:
                    out.rejected += 1
                    continue
                hands, extra = sampled
                k = world_key(hands, extra)
                if k in claimed:
                    out.collisions += 1
                    continue
                if k in seen_here:
                    continue          # duplicate within a fold: not an error
                seen_here.add(k)
                claimed.add(k)
                got.append((hands, extra))
            out.worlds[fold] = got
    finally:
        bot.rng = random.Random()
        bot.rng.setstate(saved)
    out.assert_disjoint()
    return out


def short(counts: dict, drawn: FoldedWorlds) -> str:
    """One-line summary; a fold that came up short must be visible."""
    bits = []
    for fold in FOLDS:
        n = len(drawn.worlds[fold])
        bits.append(f"{fold}={n}" + ("" if n == counts[fold] else
                                     f"/{counts[fold]} SHORT"))
    return (f"{' '.join(bits)}  rejected={drawn.rejected} "
            f"collisions={drawn.collisions}")
