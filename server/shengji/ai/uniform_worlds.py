"""Uniform public-constraint world proposal and the bury-rule kitty (board rows
S30 and S31).

THE TARGET.  A world deals the unseen cards to the other three seats (and, for a
seat that is not the banker, to the hidden kitty).  The deal was a uniformly
random permutation of the deck, so given what is public every PHYSICAL deal that
honours the public constraints is equally likely: the hand sizes, the declarer's
shown cards (pinned, as `MCBot._sample_hands` pins them), the public voids, the
pair and run caps `Memory` proves, and the pair obligation's draw constraints
(`history_legality.draw_constraints`: a seat may not hold the twin of a card it
played at or after a follow that showed fewer pairs than were led).  The suit
counts each seat receives are then distributed in proportion to the number of
deals that realise them.  `MCBot._splits` instead draws each receiver's count
uniformly from its feasible range, in random receiver order, which spreads trump
lengths several times too wide; this module is the alternative, used only
through the ``propose=`` seam of `history_legality.sample_worlds_history_legal`
and the served bury's model worlds when its flag is on.

THE CONSTRUCTION (exact for every constraint that is a property of single cards).
Each unseen physical card has a set of receivers it may go to: the kitty always,
a seat unless the card's effective suit is void there or its code is one of that
seat's draw constraints.  Cards with the same allowed set form a TYPE; the type
allowed everywhere is the free block.  The number of deals with type-count
matrix ``x`` is ``prod_t n_t! / prod_r x[t, r]!``, and the largest type (the free
block) admits ``m! / prod_r c_r!`` deals into the capacities ``c`` it is left on
its own receivers (a closed form).
`UniformProposal` builds, once per draw call, the suffix count arrays
``Z_t(c)`` (the number of deals of types ``t..`` and the free block into
capacities ``c``) by repeated multiplication with ``sum_{r in A_t} z_r``; a
world then draws each constrained type's split in proportion to
``multinomial(n_t; x) * Z_{t+1}(c - x)``, deals each type's physical cards in a
uniformly shuffled order, and gives the free block what is left.  That is an
exact uniform draw over deals honouring the voids and draw constraints.  The
pair and run caps constrain pairs of cards, not single cards, so a world that
breaks one is rejected and redrawn whole (rejection of a uniform draw stays
uniform).  The history test (`history_legality.first_violation`, the tractor
obligation) still runs on every world the seam accepts.

BOUNDED COST.  A decision gets at most ``TRY_FACTOR`` tries per requested world
in all.  A call whose tries fail, every call after the budget is spent, and every
call in a state with no feasible type split returns the fallback draw (the
sampler's own, or the history rule's constrained draw) and counts it in
``uniform_fallback_worlds``: the search never stalls or runs short because of
this proposal.

THE BURY-RULE KITTY (``kitty_rule=True``; a seat that is not the banker).  The
real kitty is the banker's discard, not eight random cards.  The proposal then
deals the banker's current hand and the kitty as ONE receiver, ``U``, allowed
every card (the banker's voids bind its hand, not its discard; ``U`` is split by
card into the cards the banker's hand may not hold, at most the kitty's size
since all of them must be buried, and the rest, and the count array is read at
every split, so ``U`` stays uniform under that necessary condition), rebuilds the
banker's 33-card bury hand as ``U`` plus every card the banker has played, and
chooses the kitty with the served bury's incumbent rule (`HeuristicBot.
decide_bury`, `heuristic_bury_kitty`), restricted to ``U`` since a played card
was not buried.  The banker's hand is ``U`` minus that kitty and must honour the
banker's voids, draw constraints and caps, else the world is redrawn; so is a
world whose kitty would need a trump (the rule keeps every trump while the
33-card hand holds eight other cards, so such a kitty means the rule's own
choice held a card the banker has played since).  Requiring the rule's whole
choice to be unplayed instead rejects nearly every world once the banker has
played one low card, and the real banker is not exactly this rule.  The
declarer's shown cards, when the declarer is the banker, are pinned to ``U``:
they were in the 33-card hand at the bury.  The served bury chooser itself (the
value head over 64 candidates and 32 worlds) costs about 0.2 s a bury, too much
inside every play world; its incumbent is the rule it starts from.  A world
the rule cannot produce within its budget (a banker void in a long suit early,
where the consistent ``U`` is rare) comes from the plain uniform proposal, and
is counted in ``kitty_rule_fallback_worlds``.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from ..engine.cards import TRUMP, points
from ..engine.combos import decompose
from .heuristic import HeuristicBot
from .history_legality import draw_constraints

#: tries per requested world, over the whole draw call, before every further
#: world comes from the fallback draw
TRY_FACTOR = 16
#: tries one call may spend before it returns the fallback draw
TRIES_PER_CALL = 64
#: the largest count array (the product of receiver capacities + 1) built
MAX_CELLS = 2_000_000
#: the receivers' keys besides the seats: the hidden kitty, and with the
#: bury-rule kitty the banker's hand-plus-kitty split by card into the cards its
#: hand may not hold (OUT) and the rest (IN)
KITTY = "kitty"
UNION_OUT = "union-out"
UNION_IN = "union-in"
#: record fields, in order (the bury-rule kitty adds ``KITTY_FIELDS``)
FIELDS = ("uniform_tries", "uniform_cap_rejections", "uniform_fallback_worlds",
          "uniform_constrained_types", "uniform_constrained_cards", "uniform_infeasible",
          "uniform_draw_constraints", "uniform_draw_forbidden")
KITTY_FIELDS = ("kitty_rule_worlds", "kitty_rule_rejections", "kitty_rule_fallback_worlds")

_INCUMBENT = HeuristicBot()


def heuristic_bury_kitty(hand33, available, ordering, slots):
    """The served bury's incumbent rule (`HeuristicBot.decide_bury`) on the
    rebuilt bury hand ``hand33``, choosing ``slots`` cards from ``available``
    only (a multiset inside ``hand33``).  Its keep value is the incumbent's,
    computed on the whole 33-card hand; ties go to the lower code, which is the
    incumbent's stable order on a hand sorted by code
    (`tests/test_uniform_worlds.py` pins the two equal when nothing is
    excluded)."""
    o = ordering
    cnt = Counter(hand33)
    suit_len = Counter(o.eff_suit(c) for c in hand33)
    mult = _INCUMBENT._bury_points_mult(suit_len[TRUMP], cnt["BJ"] > 0)
    top = len(o.plain_ranks) - 1
    keep = {}
    for code in cnt:
        suit = o.eff_suit(code)
        if suit == TRUMP:
            keep[code] = 100 + o.level(code)
            continue
        v = float(o.level(code))
        if o.level(code) >= top:
            v += 40
        if cnt[code] >= 2:
            v += 25
        v += points(code) * mult
        v -= _INCUMBENT._bury_short_bonus(suit_len[suit])
        keep[code] = v
    return sorted(available, key=lambda c: (keep[c], c))[:slots]


def _compositions(n, allowed, caps):
    """Every split of ``n`` cards over the receivers ``allowed`` (indices), each
    at most its cap, as rows of a ``len(caps)``-wide int array."""
    rows = []
    width = len(caps)

    def rec(i, left, acc):
        if i == len(allowed):
            if left == 0:
                row = [0] * width
                for r, k in zip(allowed, acc):
                    row[r] = k
                rows.append(row)
            return
        r = allowed[i]
        rest = sum(caps[q] for q in allowed[i + 1:])
        for k in range(max(0, left - rest), min(left, caps[r]) + 1):
            rec(i + 1, left - k, acc + [k])
    rec(0, n, [])
    return np.array(rows, dtype=np.int64).reshape(-1, width)


def _log_factorials(n):
    return np.array([math.lgamma(k + 1) for k in range(n + 1)])


class UniformProposal:
    """``propose(rnd, seat, mem) -> (hands, buried)``, the seam's contract: the
    three other seats' hands at their current sizes and the kitty (the banker's
    own when ``seat`` is the banker), drawn only from ``mem.unseen``; ``mem`` is
    read, never written.  Built per draw call: the first call reads the state
    (after the refusal rule's pins are written) and every call reuses it.

    ``sampler`` is the bot whose ``rng`` draws (so a restored sampler state
    restores this stream too) and whose ``_sample_hands`` is the default
    fallback; ``fallback`` overrides it (the history rule's constrained draw).
    ``constraints`` is `draw_constraints` for this state when the caller has it
    (else derived on the first call).  ``record()`` returns the record fields.

    With ``kitty_rule`` a world the rule cannot produce within the budget comes
    from a plain uniform proposal (no rule; its own budget), and only a world
    that one cannot produce from ``fallback``; ``kitty_rule_fallback_worlds``
    counts the first kind, ``uniform_fallback_worlds`` the second."""

    def __init__(self, sampler, *, n, kitty_rule=False, fallback=None, constraints=None):
        self.sampler = sampler
        self.rng = sampler.rng
        self.kitty_rule = bool(kitty_rule)
        self.fallback = sampler._sample_hands if fallback is None else fallback
        self.constraints = constraints
        self.budget = int(n) * TRY_FACTOR
        self.state = None
        self.stats = {key: 0 for key in FIELDS}
        self.plain = None
        if self.kitty_rule:
            self.stats.update({key: 0 for key in KITTY_FIELDS})
            self.plain = UniformProposal(sampler, n=n, fallback=fallback, constraints=constraints)
            self.fallback = self.plain

    def record(self):
        """The record fields: this proposal's counts, with the plain proposal's
        tries and rejections added under the bury-rule kitty."""
        out = dict(self.stats)
        if self.plain is not None:
            plain = self.plain.stats
            out["kitty_rule_fallback_worlds"] = self.stats["uniform_fallback_worlds"]
            out["uniform_fallback_worlds"] = plain["uniform_fallback_worlds"]
            out["uniform_tries"] += plain["uniform_tries"]
            out["uniform_cap_rejections"] += plain["uniform_cap_rejections"]
        return out

    # ------------------------------------------------------------ the state
    def _prepare(self, rnd, seat, mem):
        o = rnd.ordering
        banker = rnd.banker
        pool = Counter(mem.unseen)
        if seat == banker:
            if not getattr(mem, "own_kitty_known", False):
                pool = pool - Counter(rnd.buried)
            buried, kitty_slots = list(rnd.buried), 0
        else:
            buried, kitty_slots = None, len(rnd.buried)
        others = [s for s in range(4) if s != seat]
        sizes = {s: len(rnd.hands[s]) for s in others}
        if sum(pool.values()) != sum(sizes.values()) + kitty_slots:
            raise AssertionError(f"unseen pool {sum(pool.values())} != hands "
                                 f"{sum(sizes.values())} + kitty {kitty_slots}")
        union = (banker if self.kitty_rule and seat != banker and kitty_slots
                 and banker in sizes else None)
        room = {s: sizes[s] + (kitty_slots if s == union else 0) for s in others}
        pre = {s: [] for s in others}
        pinned = Counter()
        if getattr(self.sampler, "DECLARER_PIN", True):
            for code, (dseat, copies) in mem.known.items():
                if dseat in pre:
                    take = min(copies, room[dseat] - len(pre[dseat]))
                    pre[dseat].extend([code] * take)
                    pinned[code] += take
        free = sorted((pool - pinned).elements())
        forbidden = {s: set() for s in range(4)}
        constraints = (draw_constraints(rnd, seat) if self.constraints is None
                       else self.constraints)
        for (s, _suit), codes in constraints.items():
            forbidden[s].update(codes)
        # the history rule's ``history_draw_*`` count only its own draw's use
        # of these; a proposal records the ones it honours here
        self.stats["uniform_draw_constraints"] = len(constraints)
        self.stats["uniform_draw_forbidden"] = sum(sum(c.values()) for c in constraints.values())

        def barred(s, code):
            return o.eff_suit(code) in mem.voids[s] or code in forbidden[s]
        receivers = [s for s in others if s != union]
        caps = [room[s] - len(pre[s]) for s in receivers]
        targets = None
        if union is None:
            if kitty_slots:
                receivers.append(KITTY)
                caps.append(kitty_slots)
        else:
            # the banker's hand and the kitty as two receivers by card, not by
            # slot: OUT takes the cards its hand may not hold (all of them must
            # end in the kitty, so at most ``kitty_slots``), IN the rest; the
            # count array is read at every split of U between them
            total = room[union] - len(pre[union])
            out_cap = min(kitty_slots, total, sum(barred(union, c) for c in free))
            if out_cap:
                receivers.append(UNION_OUT)
                caps.append(out_cap)
            receivers.append(UNION_IN)
            caps.append(total)
            targets = [caps[:-2] + [v, total - v] if out_cap else caps[:-1] + [total]
                       for v in range(out_cap + 1)]

        def allowed(code):
            return tuple(r == KITTY
                         or (r == UNION_OUT and barred(union, code))
                         or (r == UNION_IN and not barred(union, code))
                         or (isinstance(r, int) and not barred(r, code))
                         for r in receivers)
        groups: dict[tuple, list[str]] = {}
        for code in free:
            groups.setdefault(allowed(code), []).append(code)
        types = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        free_mask, free_block = types.pop(0) if types else (tuple(True for _ in receivers), [])
        state = dict(o=o, banker=banker, buried=buried, kitty_slots=kitty_slots,
                     others=others, union=union, pre=pre, receivers=receivers,
                     forbidden=forbidden, free_block=free_block, types=types,
                     feasible=True, played_banker=None)
        everywhere = all(free_mask)
        self.stats["uniform_constrained_types"] = len(types) + (not everywhere)
        self.stats["uniform_constrained_cards"] = (sum(len(cards) for _, cards in types)
                                                   + (0 if everywhere else len(free_block)))
        if union is not None:
            state["played_banker"] = sorted(mem.played_by[banker].elements())
        state.update(self._count_arrays(types, free_mask, len(free_block), caps,
                                        targets or [caps]))
        self.state = state

    def _count_arrays(self, types, free_mask, n_free, caps, targets):
        """The suffix count arrays, each type's splits and the targets' weights
        (module docstring).  The largest type is the closed-form block: it
        admits ``n! / prod_r c_r!`` deals into capacities ``c`` on its own
        receivers."""
        dims = tuple(c + 1 for c in caps)
        if (any(not any(mask) for mask, _ in types) or (n_free and not any(free_mask))
                or math.prod(dims) > MAX_CELLS):
            return {"feasible": False}
        lf = _log_factorials(max([max(dims), n_free] + [len(c) for _, c in types]) + 1)
        if not types and all(free_mask):
            # no constrained card: the targets' weights in closed form, no array
            weights = np.array([math.exp(lf[n_free] - sum(lf[k] for k in t))
                                if sum(t) == n_free else 0.0 for t in targets])
            if not weights.sum() > 0:
                return {"feasible": False}
            return {"suffix": [], "splits": [], "targets": np.array(targets, dtype=np.int64),
                    "target_cum": np.cumsum(weights)}
        grid = np.indices(dims)
        log_free = lf[n_free] - sum(lf[grid[r]] for r in range(len(dims)))
        support = grid.sum(axis=0) == n_free
        for r, ok in enumerate(free_mask):
            if not ok:
                support &= grid[r] == 0
        z = np.where(support, np.exp(log_free), 0.0)
        suffix = [None] * len(types)
        splits = [None] * len(types)
        for t in range(len(types) - 1, -1, -1):
            mask, cards = types[t]
            axes = [r for r, ok in enumerate(mask) if ok]
            suffix[t] = z
            rows = _compositions(len(cards), axes, caps)
            coef = np.exp(lf[len(cards)] - lf[rows].sum(axis=1)) if len(rows) else np.zeros(0)
            splits[t] = (rows, coef)
            for _ in range(len(cards)):
                nz = np.zeros_like(z)
                for r in axes:
                    dst = [slice(None)] * len(dims)
                    src = [slice(None)] * len(dims)
                    dst[r] = slice(1, None)
                    src[r] = slice(None, -1)
                    nz[tuple(dst)] += z[tuple(src)]
                z = nz
        weights = np.array([z[tuple(t)] for t in targets])
        if not weights.sum() > 0:
            return {"feasible": False}
        return {"suffix": suffix, "splits": splits, "targets": np.array(targets, dtype=np.int64),
                "target_cum": np.cumsum(weights)}

    # ------------------------------------------------------------- one draw
    def _deal(self):
        st = self.state
        rng = self.rng
        receivers = st["receivers"]
        dealt = {r: [] for r in receivers}
        cum = st["target_cum"]
        pick = int(np.searchsorted(cum, rng.random() * cum[-1], side="right"))
        c = st["targets"][min(pick, len(cum) - 1)].copy()
        for t, (_mask, cards) in enumerate(st["types"]):
            rows, coef = st["splits"][t]
            ok = (rows <= c).all(axis=1)
            cand = rows[ok]
            rest = c - cand
            w = coef[ok] * st["suffix"][t][tuple(rest.T)]
            cum = np.cumsum(w)
            pick = int(np.searchsorted(cum, rng.random() * cum[-1], side="right"))
            x = cand[min(pick, len(cand) - 1)]
            shuffled = list(cards)
            rng.shuffle(shuffled)
            i = 0
            for r, k in zip(receivers, x):
                dealt[r].extend(shuffled[i:i + k])
                i += k
            c = c - x
        shuffled = list(st["free_block"])
        rng.shuffle(shuffled)
        i = 0
        for r, k in zip(receivers, c):
            dealt[r].extend(shuffled[i:i + int(k)])
            i += int(k)
        return dealt

    def _caps_hold(self, seat_, hand, mem, o):
        caps = mem.pair_cap[seat_]
        runs = mem.run_cap[seat_]
        if not caps and not runs:
            return True
        for suit in set(caps) | set(runs):
            cards = [c for c in hand if o.eff_suit(c) == suit]
            if len(cards) < 2:
                continue
            cap = caps.get(suit)
            if cap is not None and sum(v // 2 for v in Counter(cards).values()) > cap:
                return False
            run = runs.get(suit)
            if run is not None and decompose(cards, o).max_pair_run() > run:
                return False
        return True

    def _try(self, mem):
        st = self.state
        o = st["o"]
        dealt = self._deal()
        union = st["union"]
        hands = {s: st["pre"][s] + dealt[s] for s in st["others"] if s != union}
        for s in hands:
            if not self._caps_hold(s, hands[s], mem, o):
                self.stats["uniform_cap_rejections"] += 1
                return None
        if union is None:
            kitty = st["buried"] if st["buried"] is not None else dealt.get(KITTY, [])
            return hands, list(kitty)
        available = st["pre"][union] + dealt.get(UNION_OUT, []) + dealt[UNION_IN]
        kitty = heuristic_bury_kitty(available + st["played_banker"], available, o,
                                     st["kitty_slots"])
        hand = list((Counter(available) - Counter(kitty)).elements())
        voids = mem.voids[union]
        forbidden = st["forbidden"][union]
        # the rule buries a trump only from a hand short of eight other cards; a
        # kitty that needs one here means the rule's own choice included a card
        # the banker has played since, so the world contradicts the rule
        if (any(o.eff_suit(c) == TRUMP for c in kitty)
                or any(o.eff_suit(c) in voids or c in forbidden for c in hand)
                or not self._caps_hold(union, hand, mem, o)):
            self.stats["kitty_rule_rejections"] += 1
            return None
        hands[union] = hand
        self.stats["kitty_rule_worlds"] += 1
        return hands, list(kitty)

    def __call__(self, rnd, seat, mem):
        if self.state is None:
            self._prepare(rnd, seat, mem)
            if not self.state["feasible"]:
                self.stats["uniform_infeasible"] = 1
        if self.state["feasible"]:
            for _ in range(TRIES_PER_CALL):
                if self.stats["uniform_tries"] >= self.budget:
                    break
                self.stats["uniform_tries"] += 1
                got = self._try(mem)
                if got is not None:
                    return got
        self.stats["uniform_fallback_worlds"] += 1
        return self.fallback(rnd, seat, mem)


def sample_worlds_uniform(bot, rnd, seat, n, *, mem=None, check_budget=None, kitty_rule=False):
    """``n`` canonicalised complete worlds from `UniformProposal` (the served
    bury's model worlds: no follow exists yet, so no history test), with
    production's attempt cap.  Returns ``(worlds, attempts, stats)``."""
    from .memory import Memory
    if mem is None:
        mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    propose = UniformProposal(bot, n=n, kitty_rule=kitty_rule)
    worlds = []
    attempts = 0
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    while len(worlds) < n and attempts < cap:
        if check_budget is not None:
            check_budget()
        attempts += 1
        sampled = propose(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        worlds.append((bot._complete_determinized_hands(rnd, seat, hands, buried=buried),
                       sorted(buried)))
    if check_budget is not None:
        check_budget()
    return worlds, attempts, propose.record()


__all__ = ["TRY_FACTOR", "TRIES_PER_CALL", "FIELDS", "KITTY_FIELDS", "UniformProposal",
           "heuristic_bury_kitty", "sample_worlds_uniform"]
