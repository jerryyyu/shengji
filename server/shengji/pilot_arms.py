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

ARMS = ("current", "v3", "random_fill", "quota", "mc_more", "full_universe")

#: `mc_more` keeps the DEPLOYED ballot and spends the extra proposal compute on
#: more worlds instead. It is the arm that decides whether any of this is worth
#: doing: if simply pricing the old ballot harder matches a wider ballot at the
#: same total work, the simpler bot wins and the pilot has its answer.
#:
#: There is deliberately NO world multiplier here. A flat 3x is not equal work,
#: because arms differ in ballot size — it would have given mc_more roughly
#: double quota's compute. The runner budgets from
#: `pilot_score.worlds_for_equal_work()`, and a stale constant alongside it
#: would be a second, contradictory contract (Codex).


def _legal(rnd, seat, cards) -> bool:
    """Is this a well-formed ATTEMPTED lead, from PUBLIC state plus this hand?

    It must not consult the other seats. The previous version passed the true
    hidden hands to `validate_lead` and required `not msg`, i.e. it required
    the throw to SUCCEED — so the universe became a function of hidden cards:
    `CA CJ CJ` was in it under the real deal and vanished under a different
    sampler-valid world (Codex). A proposer cannot see that, and a ballot that
    depends on it is not reproducible from the state.

    Whether a throw is beaten is an OUTCOME, priced later by the rollouts. At
    proposal time the only questions are: does the seat hold these cards, and
    is the play a single effective suit.
    """
    if not cards:
        return False
    hand = Counter(rnd.hands[seat])
    if any(n > hand.get(c, 0) for c, n in Counter(cards).items()):
        return False
    o = rnd.ordering
    return len({o.eff_suit(c) for c in cards}) == 1


def structured_universe(rnd, seat, bot=None) -> list[list[str]]:
    """The broad lead universe: structured actions AND throws.

    Singles, pairs and true tractors, PLUS the deployed ballot's own actions —
    which include safe/near-boss throws and bounded component throws that no
    amount of singles/pairs/tractors reproduces.

    Including the deployed actions is not a convenience. Without them the
    "high-compute" arm was not even a SUPERSET of the arm it is supposed to
    dominate: a 100-lead probe found deployed actions missing from it in 7
    states — throws like `DA DA DK`, `HA HK`, `H10 H8 H9` (Codex). An arm that
    cannot propose what the baseline proposes cannot be read as an upper bound
    on what sourcing can achieve.

    Deterministic and sorted, so it is a function of the hand rather than of
    hand order.
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
    if bot is not None:
        out += [sorted(a) for a in bot._candidates(rnd, seat)]
    out += _component_mutations(rnd, seat, out)
    seen, uniq = set(), []
    for a in out:
        key = tuple(sorted(a))
        if key in seen or not _legal(rnd, seat, a):
            continue
        seen.add(key)
        uniq.append(sorted(a))
    uniq.sort()
    return uniq


def _component_mutations(rnd, seat, base) -> list[list[str]]:
    """Bounded add / remove / replace of ONE component of a same-suit action.

    **The bound, stated precisely** — for each base action A of effective suit
    E, and writing S for the cards of suit E in hand that A does not use:

      ADD      A + [c]                for EVERY c in S
      REMOVE   A minus one component  (only when A has >1 component)
      REPLACE  (A minus component i) + one spare component of the same SIZE,
               for every component i and every same-size disjoint spare run

    Adding only the lexicographically first spare was not this bound: from a
    hand holding `SJ SK SQ` it produced `SJ SK` and `SJ SQ` but never the
    equally held `SK SQ`, so a one-component add was still unreachable (Codex).
    `full_universe` is exactly the closure of this rule over the structured
    base, and `test_mutation_bound_matches_brute_force` checks that on small
    hands by enumerating the rule independently.
    """
    o = rnd.ordering
    out: list[list[str]] = []
    by_suit: dict[str, list[str]] = {}
    for c in rnd.hands[seat]:
        by_suit.setdefault(o.eff_suit(c), []).append(c)
    for action in base:
        # Singletons included: adding one card to `SJ` is the one-component add
        # that reaches the held uniform throw `SJ SK`, and skipping len<2 made
        # that unreachable however wide the ballot got (Codex).
        eff = o.eff_suit(action[0])
        dec = decompose(list(action), o)
        comps = [list(c.cards) for c in dec.components]
        pool = list(by_suit.get(eff, []))
        for c in action:
            if c in pool:
                pool.remove(c)
        for i in range(len(comps) if len(comps) > 1 else 0):
            # REMOVE one component
            rest = [c for j, comp in enumerate(comps) if j != i for c in comp]
            if rest:
                out.append(sorted(rest))
            # REPLACE it with EVERY same-size spare run, not one prefix
            need = len(comps[i])
            for combo in itertools.combinations(sorted(set(pool)), need):
                if all(pool.count(c) >= list(combo).count(c) for c in combo):
                    out.append(sorted(rest + list(combo)))
        # ADD: every spare card in the suit, not just the first
        for c in sorted(set(pool)):
            out.append(sorted(list(action) + [c]))
    return out


def _farthest_point(candidates, chosen, feat):
    """Pick the candidate whose feature vector is furthest from those chosen.

    Round-robin over archetypes spreads across KINDS of action; this spreads
    WITHIN a kind, which is what BALLOT_PLAN asks for and what a plain shuffle
    does not do.
    """
    if not chosen:
        return candidates[0]
    def dist(a):
        fa = feat(a)
        return min(sum((x - y) ** 2 for x, y in zip(fa, feat(b))) for b in chosen)
    return max(candidates, key=dist)


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
    # The action's rank is its DECOMPOSITION top, not the level of whatever
    # card happens to sit first. For a throw or tractor those differ, and the
    # feature silently described the wrong action (Codex).
    lv = dec.top_level()
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
    # Throw class, so the safe / near-boss / speculative quotas BALLOT_PLAN
    # promises can actually operate — without it every multi-component action
    # fell into one undifferentiated bucket (Codex).
    if len(dec.components) > 1:
        from .ai.memory import Memory
        mem = Memory(rnd, seat)
        # SHAPE-AWARE: a pair is beaten by a higher PAIR and a tractor by a
        # higher same-length tractor, not by any higher singleton. Counting
        # singletons made `safe` and `near_boss` misleading labels (Codex).
        def _beatable(comp) -> int:
            if comp.pair_len == 0:
                return mem.higher_unseen(eff, comp.top)
            # how many unseen codes above this component could form a run of
            # the same pair length
            higher = sorted(o.level(c) for c, n in mem.unseen.items()
                            if o.eff_suit(c) == eff and n >= 2
                            and o.level(c) > comp.top)
            runs = 0
            for idx in range(len(higher)):
                if all(higher[idx + d] == higher[idx] + d
                       for d in range(comp.pair_len)
                       if idx + d < len(higher)) and \
                   idx + comp.pair_len <= len(higher):
                    runs += 1
            return runs

        risks = [_beatable(c) for c in dec.components]
        if all(r == 0 for r in risks):
            throw = "safe"
        elif max(risks) <= 2:
            throw = "near_boss"
        else:
            throw = "speculative"
    else:
        throw = "single_component"
    return (shape, "trump" if is_trump else "side", rank,
            "pts" if pts else "nopts",
            "void" if creates_void else "keep",
            "breaks" if breaks else "intact", throw)


def _rng(seed, state_key, arm) -> random.Random:
    h = hashlib.sha256(f"{seed}|{state_key}|{arm}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def protected(bot, rnd, seat) -> list[str]:
    """SmartBot's pick. Every arm keeps it, so no arm can lose by omission.

    Canonicalised in hand order for the same reason `_candidates` is: `_lead`
    walks the hand, so its pick depended on list order. Exhausting all 720
    permutations of one late state gave THREE different protected leads — H2,
    S2 and D2 — in both engines (Codex). The `_candidates` fix did not cover
    this because `_lead` is called from outside it.
    """
    saved = rnd.hands[seat]
    rnd.hands[seat] = sorted(saved)
    try:
        return sorted(bot._lead(rnd, seat))
    finally:
        rnd.hands[seat] = saved


def propose(arm: str, bot, rnd, seat, *, budget: int, seed: int,
            state_key: str) -> list[list[str]]:
    """One arm's lead ballot. Pure in (state, budget, seed, arm)."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")
    keep = protected(bot, rnd, seat)

    if arm in ("current", "mc_more"):
        # Same ballot. `mc_more` differs only in how many worlds price it —
        # the runner gives it MC_MORE_WORLD_MULTIPLIER x the proposal fold, so
        # the comparison is equal-work rather than equal-ballot.
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

    universe = structured_universe(rnd, seat, bot)
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
    def feat(a):
        d = decompose(list(a), o)
        return (len(a), d.n_pairs, d.max_pair_run(), d.top_level(),
                sum(points(c) for c in a))

    o = rnd.ordering
    picked = [keep]
    arches = sorted(by_arch)
    i = 0
    while len(picked) < budget and any(by_arch[k] for k in arches):
        k = arches[i % len(arches)]
        i += 1
        if not by_arch[k]:
            continue
        # WITHIN an archetype, take the action furthest from what is already
        # on the ballot rather than an arbitrary shuffled one.
        pick = _farthest_point(by_arch[k], picked, feat)
        by_arch[k].remove(pick)
        picked.append(pick)
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
