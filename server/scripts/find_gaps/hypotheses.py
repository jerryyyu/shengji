"""Exploit hypotheses for exploit_duel.py: scripted overrides of release 45.

A hypothesis sees only what its seat may see (its own hand, public history,
its own team's bury) unless it is labelled CHEAT (a calibration bound, not an
exploit).  ``play`` returns cards to override release 45's play, or None to
let release 45 decide.
"""
from __future__ import annotations

from collections import Counter

from shengji.engine.cards import points

HYPOTHESES: dict = {}


def register(name):
    def deco(cls):
        HYPOTHESES[name] = cls
        cls.NAME = name
        return cls
    return deco


def make(name):
    return HYPOTHESES[name]()


class Base:
    """Release 45 unchanged (all hooks delegate)."""

    def bind(self, bots, ex_team, deal_seed):
        self.bots, self.ex_team, self.deal_seed = bots, ex_team, deal_seed
        self.notes = Counter()

    def declare(self, ex, rnd, seat, final, base):
        return base

    def bury(self, ex, rnd, seat, base):
        return base

    def play(self, ex, rnd, seat):
        """None lets release 45 decide; else ``(cards, overrode)``.  A hook that
        consults release 45 itself must return its cards (never call it twice)."""
        return None

    def record(self):
        return dict(self.notes)


@register("identity")
class Identity(Base):
    """Exploiter wrapper with no override: must read exactly 0 on every deal."""


# --------------------------------------------------------------------------
# CHEAT bounds (hidden information; calibration only, not exploits)

def _patch_sampler(bot, fn):
    """Replace one bot's play-world draw (``sampler._sample_hands``)."""
    sampler = bot.sampler
    orig = sampler._sample_hands

    def patched(rnd, seat, mem):
        return fn(orig, rnd, seat, mem)
    sampler._sample_hands = patched


@register("cheat-oracle")
class CheatOracle(Base):
    """CHEAT: exploiter seats' 64 play worlds are all the true deal (ORC W64)."""

    def bind(self, bots, ex_team, deal_seed):
        super().bind(bots, ex_team, deal_seed)
        for b in bots:
            if getattr(b, "hyp", None) is self:
                _patch_sampler(b.base, self._truth)

    def _truth(self, orig, rnd, seat, mem):
        self.notes["truth_worlds"] += 1
        hands = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
        return hands, (list(rnd.buried) if seat != rnd.banker else list(rnd.buried))


@register("cheat-partner")
class CheatPartner(Base):
    """CHEAT: exploiter seats see their PARTNER's hand (perfect-signalling bound)."""

    def bind(self, bots, ex_team, deal_seed):
        super().bind(bots, ex_team, deal_seed)
        for b in bots:
            if getattr(b, "hyp", None) is self:
                _patch_sampler(b.base, self._partner)

    def _partner(self, orig, rnd, seat, mem):
        import copy
        partner = (seat + 2) % 4
        relaxed = copy.copy(mem)
        known = dict(mem.known)
        for code, n in Counter(rnd.hands[partner]).items():
            if code in known and known[code][0] != partner:
                self.notes["pin_conflict"] += 1
                continue
            known[code] = (partner, n)
        relaxed.known = known
        got = orig(rnd, seat, relaxed)
        if got is not None:
            self.notes["partner_worlds"] += 1
        return got


# --------------------------------------------------------------------------
# Legal exploits

@register("bury-declared")
class BuryDeclared(Base):
    """Banker who declared buries its declared cards: release 45's sampler pins
    declared cards to the declarer's HAND (Memory.known), never hand+kitty, so
    the attackers' worlds can never contain the true deal afterwards."""

    def bury(self, ex, rnd, seat, base):
        decl = rnd.declaration
        if not decl or decl["seat"] != seat:
            return base
        o = rnd.ordering
        out = list(base)
        need = Counter(decl["cards"]) - Counter(out)
        for code, n in need.items():
            for _ in range(n):
                # return the bury card worth most to keep: points first, then rank
                cand = [c for c in out if c not in decl["cards"]]
                back = max(cand, key=lambda c: (points(c), o.level(c), c))
                out.remove(back)
                out.append(code)
        if sorted(out) != sorted(base):
            self.notes["declared_buried"] += 1
        return out


@register("always-ruff")
class AlwaysRuff(Base):
    """Void in a plain led suit with an opponent winning: ruff with the cheapest
    winning trump.  Release 45's leaf finishes the trick with HeuristicBot, which
    ruffs a non-last trick only when it holds >= 10 points, so release 45 plays
    as if low-point tricks are never ruffed."""

    def play(self, ex, rnd, seat):
        from shengji.ai.heuristic import HeuristicBot
        from shengji.engine.cards import TRUMP
        from shengji.engine.legal import uniform_suit
        trick = rnd.trick
        if not trick.plays:
            return None
        o = rnd.ordering
        lead = trick.plays[0].cards
        lead_suit = uniform_suit(lead, o)
        if lead_suit is None or lead_suit == TRUMP:
            return None
        hand = rnd.hands[seat]
        if any(o.eff_suit(c) == lead_suit for c in hand):
            return None
        hb = HeuristicBot()
        win_seat, inc_suit, inc_top = hb._current_winner(rnd)
        if win_seat % 2 == seat % 2:
            return None
        win = hb._cheapest_winning(hand, lead, inc_suit, inc_top, o)
        if win is None or o.eff_suit(win[0]) != TRUMP:
            return None
        base = ex.base.decide_play(rnd, seat)       # keep release 45's streams moving
        if sorted(base) == sorted(win) or o.eff_suit(base[0]) == TRUMP:
            return base, False
        self.notes["ruff_override"] += 1
        return win, True


@register("declare-asap")
class DeclareAsap(Base):
    """Declare (or overcall) at the first chance with the strongest option,
    breaking ties by trump count.  Tests whether release 45's gated value
    declaration (it only evaluates where the heuristic would declare, or in the
    grace window) concedes first-round banks to an aggressive declarer."""

    def declare(self, ex, rnd, seat, final, base):
        opts = rnd.declare_options(seat)
        if not opts:
            return base
        from shengji.engine.cards import card_rank, is_joker
        hand = rnd.hands[seat]

        def key(opt):
            strength = rnd._declaration_strength(opt)
            if is_joker(opt[0]):
                n = sum(1 for c in hand if card_rank(c) == rnd.trump_rank or is_joker(c))
            else:
                n = sum(1 for c in hand if is_joker(c) or card_rank(c) == rnd.trump_rank
                        or c[0] == opt[0][0])
            return (strength, n)
        best = max(opts, key=key)
        if (base or None) != best:
            self.notes["declare_changed"] += 1
        return best


@register("bury-voids")
class BuryVoids(Base):
    """Banker buries whole short plain suits (no aces, at most 10 points per
    suit) to create voids.  Release 45's attackers sample the hidden kitty from
    the unseen pool uniformly, so they keep believing the banker holds those
    suits until it shows out."""

    def bury(self, ex, rnd, seat, base):
        from shengji.engine.cards import TRUMP
        o = rnd.ordering
        hand = list(rnd.hands[seat])
        top = len(o.plain_ranks) - 1
        suits = {}
        for c in hand:
            s = o.eff_suit(c)
            if s != TRUMP:
                suits.setdefault(s, []).append(c)
        chosen = []
        for s, cards in sorted(suits.items(), key=lambda kv: len(kv[1])):
            if any(o.level(c) == top for c in cards):
                continue
            if sum(points(c) for c in cards) > 10:
                continue
            if len(chosen) + len(cards) <= 8:
                chosen += cards
        if not chosen:
            return base
        rest = Counter(hand) - Counter(chosen)
        fill = [c for c in base if rest[c] > 0 and not (rest.__setitem__(c, rest[c] - 1))]
        out = chosen + fill
        if len(out) < 8:
            # base order exhausted (it overlapped the voided suits): add the
            # lowest remaining non-trump, non-point cards, then anything
            left = list((Counter(hand) - Counter(out)).elements())
            left.sort(key=lambda c: (o.eff_suit(c) == TRUMP, points(c), o.level(c)))
            out += left[:8 - len(out)]
        out = out[:8]
        if sorted(out) != sorted(base):
            self.notes["voids_bury"] += 1
        return out


@register("policy-finisher")
class PolicyFinisher(Base):
    """Exploiter's play leaf finishes the current trick with release 45's own
    POLICY HEAD at every seat (argmax per seat, heuristic fallback) instead of
    HeuristicBot: a cheap model of how release 45 actually responds inside the
    trick.  Same worlds, same candidates, same value head."""

    def bind(self, bots, ex_team, deal_seed):
        super().bind(bots, ex_team, deal_seed)
        from shengji.ai.cwv_policy import afterstate
        from shengji.ai.heuristic import HeuristicBot
        from shengji.train.leaf_first_trick import PolicyFirstTrick
        for b in bots:
            if getattr(b, "hyp", None) is self:
                bot = b.base
                pft = PolicyFirstTrick(bot.predict, bot.version, HeuristicBot())
                self._pft = pft

                def leaf(rnd, seat, hands, buried, action, world_index, _p=pft):
                    return afterstate(rnd, seat, hands, buried, action,
                                      finish_trick=True, policy=_p)
                bot._leaf = leaf

    def record(self):
        out = dict(self.notes)
        p = getattr(self, "_pft", None)
        if p is not None:
            out.update(policy_plays=p.policy_plays, fallbacks=p.fallbacks)
        return out


def _provably_safe_throw(rnd, seat, cards):
    """True when no card this seat cannot see could beat any component: the
    unseen pool (Memory.unseen, own bury known to the banker) is checked as if
    one opponent held all of it.  Public information only."""
    from shengji.ai.memory import Memory
    from shengji.engine.legal import validate_lead
    mem = Memory(rnd, seat)
    pool = list(mem.unseen.elements())
    _, msg = validate_lead(list(cards), list(rnd.hands[seat]), [pool, [], []], rnd.ordering)
    return msg is None


@register("safe-throws-only")
class SafeThrowsOnly(Base):
    """Never attempt a throw that public information cannot prove safe: replace
    it with release 45's best-valued admitted single-component lead.  Release 45
    attempts throws that fail ~0.9 times per round in self-play."""

    def play(self, ex, rnd, seat):
        from shengji.engine.combos import decompose
        if rnd.trick.plays:
            return None
        base = ex.base.decide_play(rnd, seat)
        o = rnd.ordering
        if len(base) < 2 or len(decompose(list(base), o).components) < 2:
            return base, False
        if _provably_safe_throw(rnd, seat, base):
            self.notes["safe_throw_kept"] += 1
            return base, False
        rec = ex.base.last_decision_record or {}
        admitted, means = rec.get("admitted"), rec.get("value_means")
        if not admitted or not means:
            self.notes["no_record"] += 1
            return base, False
        best = None
        for cards, m in zip(admitted, means):
            if len(decompose(list(cards), o).components) == 1 or \
                    _provably_safe_throw(rnd, seat, cards):
                if best is None or m > best[1]:
                    best = (list(cards), m)
        if best is None:
            self.notes["no_alternative"] += 1
            return base, False
        self.notes["throw_replaced"] += 1
        return best[0], True


@register("no-zero-ruff")
class NoZeroRuff(Base):
    """Opposite of always-ruff: never ruff a zero-point plain trick when not the
    last to play; take release 45's best-valued admitted non-trump follow.
    Release 45 ruffs ~60% of those spots in self-play."""

    def play(self, ex, rnd, seat):
        from shengji.engine.cards import TRUMP
        from shengji.engine.legal import uniform_suit
        trick = rnd.trick
        if not trick.plays or len(trick.plays) == 3:
            return None
        o = rnd.ordering
        lead_suit = uniform_suit(trick.plays[0].cards, o)
        if lead_suit is None or lead_suit == TRUMP:
            return None
        if any(o.eff_suit(c) == lead_suit for c in rnd.hands[seat]):
            return None
        if sum(points(c) for tp in trick.plays for c in tp.cards):
            return None
        base = ex.base.decide_play(rnd, seat)
        if not any(o.eff_suit(c) == TRUMP for c in base):
            return base, False
        rec = ex.base.last_decision_record or {}
        admitted, means = rec.get("admitted"), rec.get("value_means")
        if not admitted or not means:
            return base, False
        alt = [(m, list(a)) for a, m in zip(admitted, means)
               if not any(o.eff_suit(c) == TRUMP for c in a)]
        if not alt:
            self.notes["no_alternative"] += 1
            return base, False
        self.notes["ruff_withheld"] += 1
        return max(alt)[1], True


@register("declare-scaled")
class DeclareScaled(Base):
    """Declare as soon as the heuristic's trump score clears its full-hand bar
    (9 of 25) SCALED to the cards dealt so far (at least 2): an early but
    suit-aware bank grab, to separate the race from the early-suit cost."""

    def declare(self, ex, rnd, seat, final, base):
        if base:
            return base
        opts = rnd.declare_options(seat)
        if not opts:
            return base
        from shengji.engine.cards import card_rank, is_joker
        hand = rnd.hands[seat]
        best, best_score = None, -1
        for opt in opts:
            if is_joker(opt[0]):
                n_rank = sum(1 for c in hand if card_rank(c) == rnd.trump_rank)
                score = 14 + n_rank if n_rank >= 3 else 0
            else:
                score = sum(1 for c in hand if is_joker(c) or card_rank(c) == rnd.trump_rank
                            or c[0] == opt[0][0]) + (2 if len(opt) == 2 else 0)
            if score > best_score:
                best, best_score = opt, score
        bar = max(2.0, 9 * len(hand) / 25)
        if best_score >= bar:
            self.notes["declare_early"] += 1
            return best
        return base
