"""Cross-fitted belief-world folds for the lead-ballot pilot.

BALLOT_PLAN Phase 2 requires three INDEPENDENTLY DRAWN folds:

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

**Independence comes from the STREAMS, not from disjoint realised support.**
The first version of this module rejected a sampled world whose key had already
appeared, in the same or another fold. That is wrong, and wrong in the
direction that matters: it conditions later draws on earlier outcomes and
changes their distribution. Codex's example is decisive — with a toy posterior
P(A)=0.8, P(B)=0.2, rejecting the proposal fold's outcome from a two-world
report fold makes report A occur only when proposal drew B, i.e. 0.2 instead of
0.8. Rejecting duplicates WITHIN a fold overweights rare worlds the same way.
Two independent draws are allowed to coincide; forbidding it is the bias.

So every successful draw is accepted, equal keys are counted as a DIAGNOSTIC
only, and cross-fitting rests on the streams being independent. Each fold
draws from its own named RNG stream, derived by hashing (salt, state key, fold
name) so that:

  * drawing from one fold cannot advance another — the historical
    `Ordering._dcache`-style coupling where two consumers shared a generator
    and one silently shifted the other;
  * the same state always yields the same worlds, so a rerun reproduces;
  * two different states never collide, because the state key is in the hash.

Worlds carry a canonical seat-aware key, used to REPORT coincidence between
folds. It is a diagnostic: a high rate says the legal space is small, not that
anything is wrong.
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
    """Worlds for one state, drawn independently per fold."""

    state_key: str
    worlds: dict = field(default_factory=dict)     # fold -> list[(hands, extra)]
    requested: dict = field(default_factory=dict)
    attempts: dict = field(default_factory=dict)
    rejected_by_fold: dict = field(default_factory=dict)
    rejected: int = 0
    collisions: int = 0

    def keys(self, fold: str) -> set:
        return {world_key(h, e) for h, e in self.worlds[fold]}

    def ordered_keys(self, fold: str) -> tuple:
        """World identity in scoring order (duplicates deliberately retained)."""
        return tuple(world_key(h, e) for h, e in self.worlds[fold])

    def shared_keys(self) -> int:
        """How many worlds coincide across folds. DIAGNOSTIC, never an error.

        Independent draws may legitimately land on the same world, and in a
        constrained late state they often will. Rejecting the coincidence is
        what breaks independence, so this is reported and not acted on.
        """
        seen: set = set()
        shared = 0
        for fold in FOLDS:
            ks = self.keys(fold)
            shared += len(ks & seen)
            seen |= ks
        return shared

    def stats(self) -> dict:
        """Auditable requested/accepted/rejected/short/collision counts."""
        result = {}
        key_sets = {fold: self.keys(fold) for fold in FOLDS}
        for fold in FOLDS:
            ordered = self.ordered_keys(fold)
            other = set().union(*(key_sets[f] for f in FOLDS if f != fold))
            result[fold] = {
                "requested": self.requested[fold],
                "accepted": len(self.worlds[fold]),
                "attempts": self.attempts[fold],
                "rejected": self.rejected_by_fold[fold],
                "short": self.requested[fold] - len(self.worlds[fold]),
                "collision_within": len(ordered) - len(set(ordered)),
                "collision_cross": len(set(ordered) & other),
            }
        return result


def draw_folds(bot, rnd, seat, mem, counts: dict, *, salt: str,
               state_key: str, max_attempts_factor: int = 40) -> FoldedWorlds:
    """Draw `counts[fold]` worlds per fold from independent streams.

    Each fold draws from its own named stream. EVERY successful draw is kept,
    including one that coincides with a world another fold drew: forbidding
    the coincidence would condition this fold on that one and bias it.
    Coincidences are counted for reporting only.
    """
    out = FoldedWorlds(state_key=state_key)
    out.requested = {fold: int(counts[fold]) for fold in FOLDS}
    original_rng = bot.rng          # restore the OBJECT, not a copy of state
    try:
        for fold in FOLDS:
            want = counts[fold]
            bot.rng = random.Random(stream_seed(salt, state_key, fold))
            got: list = []
            attempts = 0
            while len(got) < want and attempts < want * max_attempts_factor:
                attempts += 1
                sampled = bot._sample_hands(rnd, seat, mem)
                if sampled is None:
                    out.rejected += 1
                    continue
                got.append(sampled)
            out.worlds[fold] = got
            out.attempts[fold] = attempts
            out.rejected_by_fold[fold] = attempts - len(got)
    finally:
        bot.rng = original_rng
    out.collisions = out.shared_keys()
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
