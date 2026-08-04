"""The five lead-ballot arms for the pilot.

Per BALLOT_PLAN Phase 3 and Codex's design, at the SAME lead-candidate budget
unless stated:

  * `current`       — the deployed `MCBot._candidates` lead ballot
  * `v3`            — current plus one single per (level, residual shape)
  * `random_fill`   — protected action plus RANDOM fill to the same budget
  * `quota`         — protected action plus archetype quotas and diversity
  * `full_universe` — every structured lead, NOT budget-matched (the
                      high-compute arm; Jerry optimises strength, not latency)

`random_fill` is the arm that decides whether the pilot means anything. A quota
arm that beats `current` has only shown that a wider or differently-shaped
ballot helps; beating `random_fill` at the same budget is what shows the
SELECTION is doing work. V3 already demonstrated the difference matters: it
widened the ballot in exactly the place the coverage audit pointed at, and its
random-fill control scored higher.

Every arm is a pure function of (state, budget, seed). No arm looks at a world,
a rollout, or a value — proposal happens before any scoring, and the folds keep
proposal worlds away from report worlds.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from collections import Counter

from .engine.cards import TRUMP, points
from .engine.combos import decompose, find_tractor_runs
from .engine.legal import suit_cards, validate_lead

ARMS = ("current", "v3", "random_fill", "quota", "full_universe")


def _legal(rnd, seat, cards) -> bool:
    others = [rnd.hands[s] for s in range(4) if s != seat]
    try:
        played, msg = validate_lead(list(cards), rnd.hands[seat], others,
                                    rnd.ordering)
    except Exception:
        return False
    return sorted(played) == sorted(cards) and not msg


def structured_universe(rnd, seat) -> list[list[str]]:
    """Every single, pair and true tractor the seat can legally lead.

    The denominator the coverage audit uses, and the `full_universe` arm's
    ballot. Deterministic and sorted, so it is a function of the hand rather
    than of hand order.
    """
    o = rnd.ordering
    hand = rnd.hands[seat]
    out: list[list[str]] = []
    for suit in {o.eff_suit(c) for c in hand}:
        cs = suit_cards(hand, suit, o) if suit != TRUMP else \
            [c for c in hand if o.eff_suit(c) == TRUMP]
        for code in sorted(set(cs)):
            out.append([code])
        for code, n in sorted(Counter(cs).items()):
            if n >= 2:
                out.append([code, code])
        for k in range(2, len(cs) // 2 + 1):
            for run in find_tractor_runs(cs, o, k):
                out.append(sorted(run))
    seen, uniq = set(), []
    for a in out:
        key = tuple(sorted(a))
        if key in seen or not _legal(rnd, seat, a):
            continue
        seen.add(key)
        uniq.append(sorted(a))
    uniq.sort()
    return uniq


def archetype(rnd, seat, action) -> tuple:
    """Structural bucket for one lead action, from PUBLIC features only.

    Deliberately coarse. Fine buckets with one member each are not strata,
    they are a shuffled list — and the quota arm's whole claim is that
    spending slots ACROSS kinds of action beats spending them on whichever
    the generator happened to emit first.
    """
    o = rnd.ordering
    hand = rnd.hands[seat]
    dec = decompose(list(action), o)
    shape = ("tractor" if dec.max_pair_run() >= 2 else
             "pair" if dec.n_pairs else "single")
    eff = o.eff_suit(action[0])
    is_trump = eff == TRUMP
    pts = sum(points(c) for c in action) > 0
    # where the action sits within what the seat holds in that suit
    same = [c for c in hand if o.eff_suit(c) == eff]
    levels = sorted({o.level(c) for c in same})
    lv = o.level(action[0])
    rank = ("high" if lv == levels[-1] else
            "low" if lv == levels[0] else "mid") if levels else "low"
    # does playing this empty the suit, and does it break residual structure?
    left = list(hand)
    for c in action:
        left.remove(c)
    creates_void = not any(o.eff_suit(c) == eff for c in left)
    before = decompose(same, o).n_pairs
    after = decompose([c for c in left if o.eff_suit(c) == eff], o).n_pairs
    breaks = after < before - dec.n_pairs
    return (shape, "trump" if is_trump else "side", rank,
            "pts" if pts else "nopts",
            "void" if creates_void else "keep",
            "breaks" if breaks else "intact")


def _rng(seed, state_key, arm) -> random.Random:
    h = hashlib.sha256(f"{seed}|{state_key}|{arm}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def protected(bot, rnd, seat) -> list[str]:
    """SmartBot's pick. Every arm keeps it, so no arm can lose by omission."""
    return sorted(bot._lead(rnd, seat))


def propose(arm: str, bot, rnd, seat, *, budget: int, seed: int,
            state_key: str) -> list[list[str]]:
    """One arm's lead ballot. Pure in (state, budget, seed, arm)."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")
    keep = protected(bot, rnd, seat)

    if arm == "current":
        return _dedupe([keep] + [sorted(a) for a in bot._candidates(rnd, seat)],
                       budget)
    if arm == "v3":
        was = bot.V3_LEAD_SINGLES
        bot.V3_LEAD_SINGLES = True
        try:
            cands = [sorted(a) for a in bot._candidates(rnd, seat)]
        finally:
            bot.V3_LEAD_SINGLES = was
        return _dedupe([keep] + cands, budget)

    universe = structured_universe(rnd, seat)
    if arm == "full_universe":
        return _dedupe([keep] + universe, None)      # NOT budget-matched
    if arm == "random_fill":
        pool = [a for a in universe if a != keep]
        _rng(seed, state_key, arm).shuffle(pool)
        return _dedupe([keep] + pool, budget)
    # quota: round-robin over archetypes, then farthest-point diversity inside
    by_arch: dict[tuple, list] = {}
    for a in universe:
        if a == keep:
            continue
        by_arch.setdefault(archetype(rnd, seat, a), []).append(a)
    rng = _rng(seed, state_key, arm)
    for v in by_arch.values():
        v.sort()
        rng.shuffle(v)
    picked = [keep]
    arches = sorted(by_arch)
    i = 0
    while len(picked) < budget and any(by_arch[k] for k in arches):
        k = arches[i % len(arches)]
        if by_arch[k]:
            picked.append(by_arch[k].pop())
        i += 1
    return _dedupe(picked, budget)


def _dedupe(actions, budget):
    seen, out = set(), []
    for a in actions:
        key = tuple(sorted(a))
        if key in seen:
            continue
        seen.add(key)
        out.append(sorted(a))
        if budget is not None and len(out) >= budget:
            break
    return out
