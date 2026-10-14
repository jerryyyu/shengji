"""The SOFT oracle worlds of the pv-search play search (#707 S17 step 3).

DIAGNOSTIC ONLY, never served, OFF BY DEFAULT.  Two partial-information
variants of #975's perfect-information diagnostic (``oracle_worlds``, token
``orc``), built to measure how much a partially correct belief over the hidden
hands buys, so S17's belief model has an accuracy target:

* **k-mix** (``oracle_mix_k = k``, ``SHENGJI_PV_ORACLE_MIX_K``, token
  ``orcm<k>``): of the W worlds, ``k`` are the TRUE deal and ``W - k`` are
  drawn by production's sampler (the refusal-aware draw when the round has a
  refusal, else the plain draw).  The true copies sit at the evenly spaced
  positions ``floor(i * W / k)``.
* **q-pin** (``oracle_pin_q = q``, ``SHENGJI_PV_ORACLE_PIN_Q``, token
  ``orcq<round(100 q)>``): every one of the W worlds is a production draw in
  which a fraction ``q`` of the hidden card copies, chosen by a seeded draw per
  world, is pinned to its true holder.  The rest are filled by production's
  own count search and suit dealer (`MCBot._assign`, with the pinned cards in
  its ``pre`` hands, so voids, pair caps and run caps hold for the WHOLE hand)
  and the world is then checked against every constraint
  (`world_violations`: voids, pair caps, run caps, the declarer and refusal
  pins, and refusal consistency).  A fill that fails ``PIN_FILL_ATTEMPTS``
  times falls back to production's draw for that world and is counted.

"Hidden" copies are the unseen cards production's sampler actually places:
`Memory.unseen` less the banker's own kitty and less the public pins
(`Memory.known`: declared cards and the unplayed cards of a refused throw).
The pin draw is ``random.Random(sampler.rng.getrandbits(64))``, one per world,
so it is seeded by the bot's seed and restored with the sampler stream by the
serving fallback.

Nothing in this module reads a `Round`'s hidden hands: the true deal arrives
as an argument, from the bot's harness hook (`PVSearchBot._oracle_world`).
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass

#: name tokens (`pv_policy_name`): ``-orcm<k>`` / ``-orcq<100 q>``
MIX_TOKEN = "orcm"
PIN_TOKEN = "orcq"
#: the digest's statement of what the worlds are
MIX_INFORMATION = "true-deal-mix"
PIN_INFORMATION = "true-holder-pin"
PIN_FILL = "production-assign-v1"
#: fills tried per pinned world (each a fresh `_assign` draw; a refusal or
#: constraint rejection counts as one) before production's draw replaces it
PIN_FILL_ATTEMPTS = 8


class SoftOracleConfigError(ValueError):
    pass


def check_mix_k(k, worlds=None) -> int:
    if type(k) is not int or k < 0:
        raise SoftOracleConfigError("oracle_mix_k must be an int >= 0")
    if k and worlds is not None and not 1 <= k < worlds:
        raise SoftOracleConfigError(f"oracle_mix_k must be in [1, worlds - 1] = [1, {worlds - 1}], "
                                    f"not {k}")
    return k


def check_pin_q(q) -> float:
    if type(q) not in (int, float) or not math.isfinite(q) or not 0 <= q < 1:
        raise SoftOracleConfigError("oracle_pin_q must be a number in [0, 1)")
    if q and abs(q * 100 - round(q * 100)) > 1e-9:
        raise SoftOracleConfigError("oracle_pin_q must be a whole percentage (0.01 steps)")
    return float(q)


def mix_token(k: int) -> str:
    return f"{MIX_TOKEN}{int(k)}"


def pin_token(q: float) -> str:
    return f"{PIN_TOKEN}{int(round(q * 100))}"


def mix_positions(k: int, worlds: int) -> list[int]:
    """The evenly spaced indices of the ``k`` true copies among ``worlds``."""
    return sorted({(i * worlds) // k for i in range(k)})


@dataclass
class HiddenLayout:
    """What production's sampler places for ``seat``, and the truth of it.

    ``pre`` are the public pins per other seat (exactly `MCBot._sample_hands`'s),
    ``free`` the hidden copies it deals, ``truth`` each hidden copy with its true
    receiver (a seat or ``"kitty"``), in a canonical order."""
    seat: int
    others: tuple
    sizes: dict
    kitty_slots: int
    known_kitty: list
    pre: dict
    free: list
    truth: list
    true_hands: list
    true_buried: list

    @property
    def hidden(self) -> int:
        return len(self.free)


def hidden_layout(sampler, rnd, seat, mem, true_hands, true_buried) -> HiddenLayout:
    """`MCBot._sample_hands`'s pool, sizes and public pins, plus each hidden
    copy's true receiver.  Raises ``ValueError`` when the true deal does not
    complete that pool (a contract defect, never a sampling accident)."""
    pool = list(mem.unseen.elements())
    if seat == rnd.banker:
        if not getattr(mem, "own_kitty_known", False):
            pool = list((Counter(pool) - Counter(rnd.buried)).elements())
        known_kitty, kitty_slots = list(rnd.buried), 0
    else:
        known_kitty, kitty_slots = [], len(rnd.buried)
    others = tuple(s for s in range(4) if s != seat)
    sizes = {s: len(rnd.hands[s]) for s in others}
    if len(pool) != sum(sizes.values()) + kitty_slots:
        raise ValueError("unseen pool does not fill the other hands and the hidden kitty")
    pinned: Counter = Counter()
    pre: dict = {s: [] for s in others}
    if getattr(sampler, "DECLARER_PIN", True):
        for code, (dseat, ncopies) in mem.known.items():
            if dseat in pre:
                take = min(ncopies, sizes[dseat] - len(pre[dseat]))
                for _ in range(take):
                    pre[dseat].append(code)
                    pinned[code] += 1
    free = sorted((Counter(pool) - pinned).elements())
    truth = []
    for s in others:
        rest = Counter(true_hands[s]) - Counter(pre[s])
        if Counter(pre[s]) - Counter(true_hands[s]):
            raise ValueError(f"a public pin of seat {s} is not in its true hand")
        truth.extend((card, s) for card in sorted(rest.elements()))
    if kitty_slots:
        truth.extend((card, "kitty") for card in sorted(true_buried))
    if Counter(card for card, _ in truth) != Counter(free):
        raise ValueError("the true deal does not complete the sampler's hidden pool")
    return HiddenLayout(seat=seat, others=others, sizes=sizes, kitty_slots=kitty_slots,
                        known_kitty=known_kitty, pre=pre, free=free, truth=truth,
                        true_hands=[list(h) for h in true_hands],
                        true_buried=sorted(true_buried))


def pin_count(q: float, hidden: int) -> int:
    return int(math.floor(q * hidden + 0.5))


def pinned_fill(sampler, rnd, mem, layout: HiddenLayout, pins):
    """One `MCBot._assign` fill of the unpinned copies with ``pins`` (a list of
    ``(card, receiver)`` from ``layout.truth``) held in place: ``(hands dict,
    kitty)`` or None when the fill failed."""
    pre = {s: list(layout.pre[s]) for s in layout.others}
    kitty_pins = []
    for card, receiver in pins:
        (kitty_pins if receiver == "kitty" else pre[receiver]).append(card)
    free = sorted((Counter(layout.free) - Counter(card for card, _ in pins)).elements())
    caps = {s: layout.sizes[s] - len(pre[s]) for s in layout.others}
    slots = layout.kitty_slots - len(kitty_pins)
    if min(caps.values(), default=0) < 0 or slots < 0:
        raise ValueError("pins exceed a receiver's size")
    got = sampler._assign(free, caps, slots, rnd.ordering, mem, pre, respect_voids=True)
    if got is None:
        return None
    hands, kitty = got
    hands = {s: pre[s] + hands[s] for s in layout.others}
    kitty = list(layout.known_kitty) if not layout.kitty_slots else kitty_pins + list(kitty)
    return hands, kitty


def world_violations(rnd, seat, mem, layout: HiddenLayout, hands, buried, refusals=()) -> list:
    """Every constraint a world can break, as ``(kind, seat, detail)``; [] when
    valid.  ``hands`` are the four complete hands (`_complete_determinized_hands`)."""
    from ..ai.refusal import refusal_consistent
    from ..engine.combos import decompose
    o = rnd.ordering
    out = []
    for s in layout.others:
        hand = hands[s]
        if len(hand) != layout.sizes[s]:
            out.append(("size", s, len(hand)))
        if Counter(layout.pre[s]) - Counter(hand):
            out.append(("public_pin", s, None))
        by_suit: dict = {}
        for card in hand:
            by_suit.setdefault(o.eff_suit(card), []).append(card)
        for suit, cards in by_suit.items():
            if suit in mem.voids[s]:
                out.append(("void", s, suit))
            cap = mem.max_pairs(s, suit)
            if cap is not None and sum(v // 2 for v in Counter(cards).values()) > cap:
                out.append(("pair_cap", s, suit))
            run = mem.max_run(s, suit)
            if run is not None and decompose(list(cards), o).max_pair_run() > run:
                out.append(("run_cap", s, suit))
    if not layout.kitty_slots and sorted(buried) != sorted(layout.known_kitty):
        out.append(("known_kitty", seat, None))
    for refusal in refusals:
        if not refusal_consistent(rnd, hands, refusal):
            out.append(("refusal", refusal.seat, None))
    return out


def agreement(layout: HiddenLayout, hands, buried) -> tuple[int, bool]:
    """``(hidden copies with their true receiver, is the true deal)`` for one world."""
    matched = 0
    exact = True
    for s in layout.others:
        world, true = Counter(hands[s]), Counter(layout.true_hands[s])
        exact = exact and world == true
        matched += sum((world & true).values()) - len(layout.pre[s])
    if layout.kitty_slots:
        world, true = Counter(buried), Counter(layout.true_buried)
        exact = exact and world == true
        matched += sum((world & true).values())
    return matched, exact


def pin_rng(sampler) -> random.Random:
    """The per-world pin draw, seeded from the sampler's own stream."""
    return random.Random(sampler.rng.getrandbits(64))
