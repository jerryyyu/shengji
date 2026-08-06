"""Determinized Monte Carlo bot.

For every play decision:
 1. Enumerate a small, diverse set of legal candidate plays.
 2. Sample N "determinizations": full deals of the unseen cards to the other
    players (and hidden kitty), consistent with public information — hand
    sizes, observed voids, and the card count. The banker's own knowledge of
    the buried kitty is used when this bot IS the banker (that's private but
    legitimately its own information).
 3. Roll each (candidate, determinization) to the end of the round with the
    fast heuristic policy for all four seats, scoring attacker points
    (sign-flipped for the banker team).
 4. Play the candidate with the best average score.

Declaration and burying are inherited from SmartBot.
"""

from __future__ import annotations

import os
import time

#: Sample count matrices in proportion to the number of card-assignments they
#: admit, rather than uniformly. Off by default until Codex adopts it.
WEIGHTED_SPLITS = bool(os.environ.get("SHENGJI_WEIGHTED_SPLITS"))
#: Draw uniformly among cap-respecting cards instead of taking the first legal
#: one — the second named posterior bias. Also off by default.
UNIFORM_DEAL = bool(os.environ.get("SHENGJI_UNIFORM_DEAL"))
PHYSICAL_FILLS = bool(os.environ.get("SHENGJI_PHYSICAL_FILLS"))
from math import factorial as _fact

import copy
import random
from collections import Counter

from ..engine.cards import TRUMP
from ..engine.combos import decompose
from ..engine.legal import IllegalPlay, suit_cards, uniform_suit, validate_follow
from ..engine.round import Round, Trick, TrickPlay
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory
from .smart import SmartBot


class _BuryLoose(SmartBot):
    """Bury variant: points in the kitty are nearly free."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 1.0


class _BuryStrict(SmartBot):
    """Bury variant: never bury points."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 8.0


class _BuryNoVoid(SmartBot):
    """Bury variant: ignore void-creation, keep balanced suits."""
    BURY_VOID = False


class MCBot(SmartBot):
    N_DETERMINIZATIONS = 10
    MAX_CANDIDATES = 8
    WIDE_LEAD_BALLOT = True  # leads: roll out every pair/tractor/near-boss
    #                          throw in every suit incl. trump (JVRA gap:
    #                          sourcing, not judgment). ADOPTED: 62% vs
    #                          narrow-ballot mc (75-45, n=120), +7% latency.
    LEAD_MAX_CANDIDATES = 14
    # Ballot V3 lead layer: offer one single per distinct effective level
    # instead of only the top and lowest-non-point card per suit.
    V3_LEAD_SINGLES = False
    V3_LEAD_RANDOM = False      # control: same slots, arbitrary singles
    WIDE_FOLLOW_BALLOT = True  # ADOPTED 60% (72-48, n=120). Follows: bounded exhaustive distinct-code
    #                             multisets on top of the constructed set
    #                             (audit: 21% of human follow singles were
    #                             off-ballot — discard selection). Cap below.
    FOLLOW_MAX_CANDIDATES = 12
    SAMPLE_RETRIES = 15
    DECLARER_PIN = True   # sampled worlds place the declarer's SHOWN cards
    #                       in the declarer's hand (public info; RTLT: a
    #                       declared rank pair was sampled split, making a
    #                       beatable K-pair lead look boss)
    CONFIDENCE_OVERRIDE = False   # S0: require a paired LCB, not a point gap
    CONFIDENCE_Z = 1.64           # one-sided 95%
    MARGIN = 5.0  # points/round a candidate must beat SmartBot's pick by;
    #               keeps the heuristic prior unless the search is confident.
    #               0 = pure argmax.
    LEVEL_OBJECTIVE = False  # score rollouts by level-change brackets (the
    #                          real payoff: 79 vs 80 points is a cliff), not
    #                          raw points. Scaled so MARGIN keeps meaning.
    MC_BURY = False          # search the banker's bury over sampled worlds
    N_BURY_WORLDS = 8
    RISKY_THROWS = False     # put near-boss throws (A+QQ) on the ballot and
    #                          let determinization price them (user idea)
    TRUMP_BALLOT = False     # trump pair / top-trump lead candidates (钓主):
    #                          hand-rules for draining measured -4% three
    #                          times, but the ballot lets worlds price it
    #                          per-position (user idea)
    TRACTOR_LOCK = True      # heuristic tractor leads are final (measured
    #                          56% vs override-allowed, and fixes perceived
    #                          "why didn't it lead the tractor" moments)
    POINT_SHY_EPS = 2.0      # among candidates within this of the best,
    #                          risk the fewest points (10-10 pair leads lose
    #                          20 immediately when beaten; expectation-equal
    #                          but worse downside)
    LEAD_MARGIN = None       # optional higher margin for LEADS only: rollout
    #                          opponents are too passive to punish slow play,
    #                          biasing lead values toward low cards (None =
    #                          use MARGIN)

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.rollout_policy = HeuristicBot()
        # CUMULATIVE work counters (not per-decision): comparing gates at equal
        # call RATE is not comparing compute, because search cost scales with
        # candidates and worlds and a candidate-count gate deliberately selects
        # expensive states (Codex, 2026-08-04).
        self.search_calls = 0
        self.rollouts = 0
        self.search_secs = 0.0
        # Worlds buildable only by ignoring observed voids. Counted, never
        # refused: refusing them killed the search outright in constrained
        # late-round states where no void-respecting world exists.
        self.impossible_worlds = 0
        self.rejected_worlds = 0
        self.last_override_stats = None
        self.reject_cause = Counter()
        # Decisions that fell back to candidate 0 with NO world sampled.
        self.zero_world_decisions = 0     # kept at 0; readers still reference it

    # ------------------------------------------------------------------- play
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        self.last_eval = None  # (candidates, per-candidate values) for distillation
        self.last_n_worlds = 0  # worlds that actually sampled — 0 means NO search
        if self.TRACTOR_LOCK and not rnd.trick.plays:
            pick = self.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return pick
        candidates = self._candidates(rnd, seat)
        if len(candidates) <= 1:
            return candidates[0]
        self.search_calls += 1
        _t0 = time.perf_counter()
        mem = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
        i_attack = rnd.is_attacker(seat)
        totals = [0.0] * len(candidates)
        # Paired running moments of (candidate_i - candidate_0) on the SAME
        # world. The fixed-margin override compares point estimates only, so a
        # noisy draw can clear it: in the QHKR incident `DJ` beat candidate 0 by
        # 5.8-6.3 against a 5.0 margin in 2 of 500 N=30 replicas, while the
        # correct card won the other 479. Pairing on shared worlds removes the
        # world-to-world variance that dominates the raw spread.
        d_sum = [0.0] * len(candidates)
        d_sq = [0.0] * len(candidates)
        n_worlds = 0
        for _ in range(self.N_DETERMINIZATIONS):
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            n_worlds += 1
            hands, buried = sampled
            world_vals = []
            for i, cand in enumerate(candidates):
                val = self._score(self._rollout(rnd, seat, hands, buried, cand))
                val = val if i_attack else -val
                totals[i] += val
                world_vals.append(val)
            base = world_vals[0]
            for i, v in enumerate(world_vals):
                d = v - base
                d_sum[i] += d
                d_sq[i] += d * d
        self.last_n_worlds = n_worlds
        # Batched, not incremented inside the candidate/world loop: an
        # attribute write in MC's hottest path taxes every production search
        # for the sake of instrumentation (Codex).
        self.rollouts += n_worlds * len(candidates)
        self.search_secs += time.perf_counter() - _t0
        if n_worlds == 0:
            # Sampling produced nothing. This once meant banker search was
            # silently disabled for a day, so it must never pass unnoticed —
            # but killing a 42-cluster shard over one rare decision throws away
            # hours of compute for no information. COUNT it; the evaluator
            # treats a nonzero count as a protocol failure, which is loud
            # without being destructive (2026-08-04).
            self.zero_world_decisions += 1
            return candidates[0]
        # acting-team perspective values, exposed for search distillation
        self.last_eval = (candidates, [t / n_worlds for t in totals])
        best = max(range(len(candidates)), key=lambda i: totals[i])
        # Among near-tied candidates, risk the fewest points.
        from ..engine.cards import points as _pts
        close = [i for i in range(len(candidates))
                 if (totals[best] - totals[i]) / n_worlds <= self.POINT_SHY_EPS]
        best = min(close, key=lambda i: (sum(_pts(c) for c in candidates[i]),
                                         -totals[i]))
        # candidates[0] is SmartBot's own choice: prefer it unless the search
        # clears the confidence margin (rollouts are noisiest early on).
        margin = self.MARGIN
        if self.LEAD_MARGIN is not None and not rnd.trick.plays:
            margin = self.LEAD_MARGIN
        if best != 0:
            gap = (totals[best] - totals[0]) / n_worlds
            if self.CONFIDENCE_OVERRIDE:
                # Require the paired LOWER CONFIDENCE BOUND to clear the
                # margin, not the point estimate. This is what the fixed
                # margin could not do: distinguish "genuinely better" from
                # "ahead on a lucky draw".
                se = self._paired_se(d_sum[best], d_sq[best], n_worlds)
                self.last_override_stats = {
                    "gap": gap, "se": se, "n_worlds": n_worlds,
                    "lcb": gap - self.CONFIDENCE_Z * se, "margin": margin,
                    "candidate": list(candidates[best]),
                    "candidate0": list(candidates[0]),
                }
                if gap - self.CONFIDENCE_Z * se < margin:
                    return candidates[0]
            elif gap < margin:
                return candidates[0]
        return candidates[best]

    @staticmethod
    def _paired_se(d_sum: float, d_sq: float, n: int) -> float:
        """SE of the paired mean difference. Zero variance -> zero SE."""
        if n < 2:
            return float("inf")
        mean = d_sum / n
        var = max(0.0, d_sq / n - mean * mean) * n / (n - 1)
        return (var / n) ** 0.5

    def _score(self, attacker_pts: float) -> float:
        """Rollout value from the attackers' perspective.

        With LEVEL_OBJECTIVE, points map to the scoring brackets that decide
        the round (0 / <40 / <80 / 80+ / 120+ / ...) plus a half-bracket for
        seizing or keeping the deal, scaled x40 so MARGIN stays comparable;
        a small points term breaks ties within a bracket."""
        p = attacker_pts
        if not self.LEVEL_OBJECTIVE:
            return float(p)
        if p >= 80:
            bracket, deal = min(3, int(p - 80) // 40), 0.5
        elif p == 0:
            bracket, deal = -3, -0.5
        else:
            bracket, deal = -(1 + int(79 - p) // 40), -0.5
        return 40.0 * (bracket + deal) + 0.2 * p

    # ------------------------------------------------------------------- bury
    def decide_bury(self, rnd: Round, seat: int) -> list[str]:
        base = super().decide_bury(rnd, seat)
        if not self.MC_BURY:
            return base
        cands: list[list[str]] = [base]
        for variant in (_BuryLoose(), _BuryStrict(), _BuryNoVoid()):
            c = variant.decide_bury(rnd, seat)
            if not any(sorted(c) == sorted(x) for x in cands):
                cands.append(c)
        if len(cands) == 1:
            return base
        mem = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
        totals = [0.0] * len(cands)
        n_worlds = 0
        for _ in range(self.N_BURY_WORLDS):
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            n_worlds += 1
            hands, _ = sampled
            for i, cand in enumerate(cands):
                # banker's perspective: minimize the attackers' value
                totals[i] -= self._score(
                    self._rollout_from_bury(rnd, seat, hands, cand))
        if n_worlds == 0:
            return base
        best = max(range(len(cands)), key=lambda i: totals[i])
        if best != 0 and (totals[best] - totals[0]) / n_worlds < self.MARGIN:
            return base
        return cands[best]

    def _rollout_from_bury(self, rnd: Round, seat: int,
                           sampled: dict[int, list[str]],
                           bury_cards: list[str]) -> float:
        clone: Round = copy.copy(rnd)
        # A determinization is a CARD MULTISET per seat.  The sampler's list
        # order is incidental, but HeuristicBot walks hands in list order.  A
        # rollout therefore used to assign different values to the same world
        # after nothing more than a hand permutation, and one changed value
        # was enough to flip MC's argmax.  Canonicalise at the rollout-policy
        # boundary so every continuation sees one representation of a world.
        clone.hands = [sorted(sampled.get(s, rnd.hands[s])) for s in range(4)]
        clone.hands[seat] = sorted(rnd.hands[seat])
        clone.buried = []
        clone.trick = None
        clone.last_trick = None
        clone.history = []
        clone.message = None
        clone.bury(seat, list(bury_cards))
        policy = self.rollout_policy
        while clone.phase == "play":
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)

    # ------------------------------------------------------------- candidates
    def canonical_lead(self, rnd: Round, seat: int) -> list[str]:
        """SmartBot's lead pick, through the canonical hand order.

        THE shared boundary. `_lead` walks the hand, so its pick depended on
        list order; the TRACTOR_LOCK path in `decide_play` called it raw and
        therefore returned different leads for the same state. That is a
        PRODUCTION actor-distribution defect, not just a pilot one — a capture
        self-played through it inherits the wrong distribution (Codex).
        """
        saved = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved)
        try:
            return sorted(self._lead(rnd, seat))
        finally:
            rnd.hands[seat] = saved

    def _candidates(self, rnd: Round, seat: int) -> list[list[str]]:
        """The ballot. CANONICALISED in the seat's hand order.

        Generation walks the hand and the caps truncate whatever was produced
        first, so the emitted ACTION SET depended on incidental list order —
        `D2` was offered under one ordering and `H2` under another, in roughly
        one lead state in six (found while building the pilot, 2026-08-05).
        Same class as the `decompose` order-dependence, one level up, and it
        put ballot noise into every measurement that used this ballot.

        The hand is sorted for the duration of generation and restored after,
        so every helper below — `_lead`, `_follow`, the throw builders — sees
        one canonical order without each needing to sort defensively.
        """
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        _saved_hand = rnd.hands[seat]
        rnd.hands[seat] = sorted(_saved_hand)
        try:
            return self._candidates_canonical(rnd, seat, o)
        finally:
            rnd.hands[seat] = _saved_hand

    def _candidates_canonical(self, rnd: Round, seat: int, o) -> list[list[str]]:
        hand = rnd.hands[seat]
        cands: list[list[str]] = []

        def add(play: list[str] | None) -> None:
            if not play:
                return
            key = tuple(sorted(play))
            if key in {tuple(sorted(c)) for c in cands}:
                return
            if rnd.trick.plays:
                try:
                    validate_follow(play, hand, rnd.trick.plays[0].cards, o)
                except IllegalPlay:
                    return
            cands.append(play)

        if not rnd.trick.plays:
            add(self._lead(rnd, seat))  # SmartBot's pick (throws included)
            if self.RISKY_THROWS or self.WIDE_LEAD_BALLOT:
                mem_ = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
                for t in self.near_boss_throws(rnd, seat, mem_):
                    add(t)  # sampled worlds price the beat risk + penalty
            if self.WIDE_LEAD_BALLOT:
                # JVRA 2026-08-02: ballot lacked trump pairs (♣A♣A/♣8♣8) —
                # sourcing gap, not judgment. Show rollouts EVERY pair,
                # tractor, and near-boss throw in every suit incl. trump;
                # the margin rule still shields the heuristic from noise.
                from ..engine.combos import find_tractor_runs
                for s in list(PLAIN_SUITS) + [TRUMP]:
                    cards = suit_cards(hand, s, o)
                    for length in range(6, 1, -1):
                        for run in find_tractor_runs(cards, o, length):
                            add(run)
                    for code, k in sorted(Counter(cards).items(),
                                          key=lambda e: -o.level(e[0])):
                        if k >= 2:
                            add([code, code])
                    if cards:
                        add([max(cards, key=o.level)])
            for s in PLAIN_SUITS:
                cards = suit_cards(hand, s, o)
                if not cards:
                    continue
                comps = decompose(cards, o).components
                paired = [c for c in comps if c.pair_len]
                if paired:
                    # list(): .cards aliases the decompose cache
                    add(list(max(paired, key=lambda c: (c.pair_len, c.top)).cards))
                # top single (the ace lead) must always be on the ballot
                add([max(cards, key=o.level)])
                add([self._lowest(cards, o, avoid_points=True)])
            trumps = suit_cards(hand, TRUMP, o)
            if trumps:
                add([self._lowest(trumps, o, avoid_points=True)])
                if self.TRUMP_BALLOT:
                    comps = decompose(trumps, o).components
                    paired = [c for c in comps if c.pair_len]
                    if paired:
                        add(list(max(paired, key=lambda c: (c.pair_len, c.top)).cards))
                    add([max(trumps, key=o.level)])  # boss/top trump drain
        else:
            add(self._follow(rnd, seat))  # SmartBot's pick
            lead = rnd.trick.plays[0].cards
            add(self._forced_follow(hand, lead, o, prefer_points=False))
            add(self._forced_follow(hand, lead, o, prefer_points=True))
            win_seat, inc_suit, inc_top = self._current_winner(rnd)
            add(self._cheapest_winning(hand, lead, inc_suit, inc_top, o))
            if self.WIDE_FOLLOW_BALLOT:
                # Every distinct-code follow (in-suit part maximal, as the
                # rules force), validated by add(); constructed seeds above
                # keep the known-good shapes ahead of the cap.
                from itertools import combinations
                suit = uniform_suit(lead, o)
                h_suit = suit_cards(hand, suit, o)
                n_suit = min(len(lead), len(h_suit))
                if n_suit == len(lead):
                    pool = {tuple(sorted(c))
                            for c in combinations(sorted(h_suit), n_suit)}
                else:
                    off = list(hand)
                    for c in h_suit:
                        off.remove(c)
                    base = tuple(sorted(h_suit))
                    pool = {base + tuple(sorted(c))
                            for c in combinations(sorted(off),
                                                  len(lead) - n_suit)}
                for cand in sorted(pool):
                    if len(cands) >= self.FOLLOW_MAX_CANDIDATES:
                        break
                    add(list(cand))
        if self.V3_LEAD_SINGLES and not rnd.trick.plays:
            # BALLOT V3, lead layer (Codex audit 2026-08-04). The deployed
            # ballot misses 15.5% of human LEADS — 55 of them middle-rank
            # singles — because per suit it only ever offers the top card and
            # the lowest non-point card. Everything in between is unreachable,
            # so no amount of search or learning can find it: race4 only
            # REMOVES from this list, and highn_build values only what is on
            # it.
            #
            # Offer one representative per DISTINCT effective level, which is
            # what "strategically distinct" means here — two cards of the same
            # level are interchangeable for the trick. The cap is unchanged, so
            # rollout cost is comparable; what changes is WHAT fills it.
            for suit in list(PLAIN_SUITS) + [TRUMP]:
                cards = suit_cards(hand, suit, o)
                # Equivalence must include what the play LEAVES BEHIND, not
                # just its immediate strength. Under trump rank 7, S7 and C7
                # tie in level, but from S7-S7-C7 leading S7 breaks the pair
                # while leading C7 keeps it — so "one representative per
                # effective level" silently dropped a materially different
                # action (Codex P0, reproduced 2026-08-04).
                seen_keys = set()
                order = sorted(cards, key=lambda x: -o.level(x))
                if self.V3_LEAD_RANDOM:
                    # CONTROL: fill the same slots with arbitrary legal
                    # singles, so "better sourcing helps" can be told apart
                    # from "a fuller ballot helps". Its RNG is SEPARATE from
                    # self.rng: sharing the stream would couple which actions
                    # are proposed to how worlds are sampled (Codex).
                    if not hasattr(self, "_proposal_rng"):
                        import random as _r
                        self._proposal_rng = _r.Random(
                            (self.rng.random() * 1e9).__int__() ^ 0xC0FFEE)
                    order = list(cards)
                    self._proposal_rng.shuffle(order)
                for c in order:
                    rest = list(cards)
                    rest.remove(c)
                    key = (o.level(c), decompose(rest, o).shape() if rest else ())
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    if len(cands) >= self.LEAD_MAX_CANDIDATES:
                        break
                    add([c])
        if (self.WIDE_LEAD_BALLOT or self.V3_LEAD_SINGLES) and not rnd.trick.plays:
            return cands[:self.LEAD_MAX_CANDIDATES]
        if self.WIDE_FOLLOW_BALLOT and rnd.trick.plays:
            return cands[:self.FOLLOW_MAX_CANDIDATES]
        return cands[:self.MAX_CANDIDATES]

    # ------------------------------------------------------------- sampling
    def _sample_hands(self, rnd: Round, seat: int, mem: Memory):
        """Deal unseen cards to the other three seats (+ hidden kitty when we
        aren't the banker), respecting hand sizes and observed voids.
        Returns (hands, buried) or None if sampling failed."""
        o = rnd.ordering
        assert o is not None
        pool = list(mem.unseen.elements())
        if seat == rnd.banker:
            # Subtract our own burial only if Memory did not already exclude
            # it (own_kitty). Subtracting twice removes cards opponents
            # genuinely hold and no world can then be built.
            if not getattr(mem, "own_kitty_known", False):
                pool = list((Counter(pool) - Counter(rnd.buried)).elements())
            buried = list(rnd.buried)
            kitty_slots = 0
        else:
            buried = []
            kitty_slots = len(rnd.buried)

        others = [s for s in range(4) if s != seat]
        sizes = {s: len(rnd.hands[s]) for s in others}
        # Conservation invariant: the unseen pool must fill exactly the other
        # hands plus the hidden kitty. A silent mismatch here means every
        # world fails and search degrades to candidate 0 without a word.
        assert len(pool) == sum(sizes.values()) + kitty_slots, (
            f"unseen pool {len(pool)} != hands {sum(sizes.values())} + "
            f"kitty {kitty_slots} (seat {seat}, banker {rnd.banker})")
        # Pin the declarer's PUBLIC shown cards before anything else, so the
        # assignment below only has to place genuinely unknown cards (RTLT
        # incident: scattering a declared trump-rank pair across hands made
        # KK-pair leads look boss in most worlds).
        pinned: Counter[str] = Counter()
        pre: dict[int, list[str]] = {s: [] for s in others}
        if self.DECLARER_PIN:
            for code, (dseat, ncopies) in mem.known.items():
                if dseat in pre:
                    take = min(ncopies, sizes[dseat] - len(pre[dseat]))
                    for _ in range(take):
                        pre[dseat].append(code)
                        pinned[code] += 1
        free = list((Counter(pool) - pinned).elements())
        caps = {s: sizes[s] - len(pre[s]) for s in others}

        for attempt in range(self.SAMPLE_RETRIES):
            respect_voids = attempt < self.SAMPLE_RETRIES - 1
            got = self._assign(free, caps, kitty_slots, o, mem, pre,
                               respect_voids=respect_voids)
            if got is None:
                continue
            hands, kitty = got
            for s in others:
                hands[s] = pre[s] + hands[s]
            if not respect_voids:
                # This world was only buildable by IGNORING observed voids,
                # i.e. it is impossible given the play history.
                #
                # SHENGJI_REQUIRE_VOIDS makes this a hard constraint. A
                # constraint-correct world ALWAYS exists (the real deal is
                # one), so a failure under this flag is a defect in the
                # construction — not proof of impossibility, which is what I
                # wrongly concluded on 2026-08-04 (Codex).
                if os.environ.get("SHENGJI_REQUIRE_VOIDS"):
                    self.rejected_worlds += 1
                    return None
                self.impossible_worlds += 1
            return hands, (buried or kitty)
        return None

    def _assign(self, cards, caps, kitty_slots, o, mem, pre, respect_voids=True):
        """Deal `cards` to seats + kitty without ever dead-ending.

        The previous version walked a shuffled pool and gave each card to a
        random seat that still had room. That is a greedy first-fit, and it
        FAILS on states where a feasible world plainly exists: place two
        off-suit cards early and the only seat that can legally take the next
        suit is already full. Those failures were not theoretical — 14 of them
        landed in the determinization confirmation blocks, each one forcing
        `PROTOCOL FAILURES` and invalidating the run they appeared in.

        The fix is to decide COUNTS before cards. There are at most five
        effective suits and four receivers, so the count matrix is tiny and can
        be searched exactly with randomized backtracking and forward checking:
        if any legal assignment exists, this finds one. Cards are only then
        distributed inside each suit, where pair caps apply.
        """
        by_suit: dict[str, list[str]] = {}
        for c in cards:
            by_suit.setdefault(o.eff_suit(c), []).append(c)

        seats = list(caps)
        recv = seats + ["kitty"]
        cap = dict(caps)
        cap["kitty"] = kitty_slots
        allowed = {
            u: [r for r in recv
                if r == "kitty" or not (respect_voids and u in mem.voids[r])]
            for u in by_suit
        }
        # Most-constrained suit first: fewest receivers, then most cards.
        order = sorted(by_suit,
                       key=lambda u: (len(allowed[u]), -len(by_suit[u]), u))
        counts: dict[str, dict] = {}
        rem = dict(cap)

        def place(i: int) -> bool:
            if i == len(order):
                return True
            u = order[i]
            need = len(by_suit[u])
            opts = [r for r in allowed[u] if rem[r] > 0]
            # Forward check: everything still unplaced must still fit.
            def feasible() -> bool:
                for j in range(i + 1, len(order)):
                    v = order[j]
                    if sum(rem[r] for r in allowed[v]) < len(by_suit[v]):
                        return False
                return True

            # PAIR-CAP FORWARD CHECK. The search previously forward-checked
            # VOIDS only, so it proposed count matrices no fill could satisfy
            # and the failure surfaced later as an exhausted card deal. A
            # receiver given `n` cards drawn from `d` distinct codes is FORCED
            # to hold at least `n - d` pairs, so `n - d > cap` is impossible
            # however the cards are shuffled. Example that produced a rejected
            # world at original:81002046:4 — 6 clubs over 4 codes (C10 and CQ
            # doubled), seat 2 void, kitty full, and pair_cap 0 everywhere: any
            # split handing one seat 5 clubs is dead on arrival, but `place`
            # could not see it and `_deal_suit` burned its retries discovering
            # it. This is a necessary condition and costs O(receivers).
            ncodes = len(set(by_suit[u]))
            caps_u = {r: (mem.max_pairs(r, u) if isinstance(r, int) else None)
                      for r in allowed[u]}

            def pair_feasible(split) -> bool:
                for r, n in split.items():
                    cap_r = caps_u.get(r)
                    if cap_r is not None and n - ncodes > cap_r:
                        return False
                return True

            for split in self._splits(need, opts, rem,
                                      cards=by_suit[u] if WEIGHTED_SPLITS else None):
                if not pair_feasible(split):
                    continue
                for r, n in split.items():
                    rem[r] -= n
                if feasible() and place(i + 1):
                    counts[u] = split
                    return True
                for r, n in split.items():
                    rem[r] += n
            return False

        if not place(0):
            self.reject_cause["no_void_assignment"] += 1
            return None

        # Counts are feasible for VOIDS; whether they are feasible for PAIR
        # CAPS depends on which specific cards land where, so a failure here is
        # a reason to redraw the cards, not to abandon the world.
        for _ in range(8):
            hands: dict[int, list[str]] = {s: [] for s in seats}
            kitty: list[str] = []
            ok = True
            for u, split in counts.items():
                # Work from an explicit REMAINING list and remove what is
                # taken. The previous version indexed into a shared list while
                # also writing slices back into it, and a swap left the taken
                # region stale — which dealt a third copy of a two-copy card.
                remaining = list(by_suit[u])
                self.rng.shuffle(remaining)
                for r, n in split.items():
                    # Seed the pair count with cards ALREADY pinned to this
                    # seat in this suit. The declarer pin runs before dealing,
                    # so a seat holding one declared copy could be handed the
                    # second and form a pair the history proves it cannot have
                    # — the two fixes never met. Found by certification against
                    # a rules-derived validator, not by the self-consistent
                    # tests, which is the whole reason Codex asked for it.
                    already = Counter(
                        c for c in pre.get(r, ()) if o.eff_suit(c) == u) \
                        if isinstance(r, int) else Counter()
                    chunk = self._deal_suit(remaining, n, r, u, mem, already)
                    if chunk is None:
                        ok = False
                        break
                    if r == "kitty":
                        kitty += chunk
                    else:
                        hands[r] += chunk
                if not ok:
                    break
            if ok:
                return hands, kitty
        self.reject_cause["pair_cap"] += 1
        return None

    @staticmethod
    def _fills(cards, split) -> int:
        """How many distinct card-assignments realise this count matrix.

        Two splits of six cards into 2/2/2 versus 6/0/0 are NOT equally likely
        worlds: the first admits far more completions. Sampling count matrices
        uniformly therefore under-weights balanced hands, which is the larger
        of the two named posterior biases. This counts the completions exactly
        by DP over CODES, so equal codes are not treated as distinguishable.
        """
        recv = [r for r in split]
        caps = tuple(split[r] for r in recv)
        codes = sorted(Counter(cards).items())
        from functools import lru_cache

        @lru_cache(maxsize=None)
        def rec(i, rem_caps):
            if i == len(codes):
                return 1 if not any(rem_caps) else 0
            _, m = codes[i]
            total = 0
            # distribute m identical copies over the receivers
            def dist(j, left, acc):
                nonlocal total
                if j == len(rem_caps):
                    if left == 0:
                        # PHYSICAL_FILLS: a multiset assignment giving receiver
                        # j exactly acc[j] copies of this code is realised by
                        # m!/prod(acc[j]!) distinct PHYSICAL deals, because the
                        # deck holds separate copies. Counting each multiset
                        # once targets a flat-over-multisets prior; the stated
                        # target is flat over DEALS. `AABB` split 2/2 is 3
                        # multisets but 6 deals (1/4/1), so the uncorrected
                        # count under-weights balanced hands even here, in the
                        # very function written to stop under-weighting them.
                        coef = 1
                        if PHYSICAL_FILLS:
                            coef = _fact(m)
                            for k in acc:
                                coef //= _fact(k)
                        total += coef * rec(i + 1, tuple(a - b for a, b in
                                                         zip(rem_caps, acc)))
                    return
                for k in range(min(left, rem_caps[j]) + 1):
                    dist(j + 1, left - k, acc + (k,))
            dist(0, m, ())
            return total

        return rec(0, caps)

    def _splits(self, need, opts, rem, cards=None):
        """EVERY distribution of `need` cards over `opts`, in random order.

        Drawing a bounded number of random splits made this a search that could
        fail while a legal assignment existed — 5 rejected worlds in 18k
        searches, small but the same class of defect as the greedy it replaced.
        Enumerating lazily costs nothing in the common case, because the first
        split that survives forward checking is almost always accepted; the
        completeness only does work in the constrained states where the old
        code gave up.
        """
        if not opts:
            if need == 0:
                yield {}
            return
        order = list(opts)
        self.rng.shuffle(order)

        def rec(i, left, acc):
            if i == len(order):
                if left == 0:
                    yield dict(acc)
                return
            r = order[i]
            room = min(rem[r], left)
            # Remaining capacity after this receiver, so impossible tails are
            # never explored.
            tail = sum(rem[x] for x in order[i + 1:])
            lo = max(0, left - tail)
            choices = list(range(lo, room + 1))
            self.rng.shuffle(choices)
            for n in choices:
                acc[r] = n
                yield from rec(i + 1, left - n, acc)
            acc.pop(r, None)

        if cards is None:
            yield from rec(0, need, {})
            return
        # WEIGHTED: enumerate every feasible split, weight each by the number
        # of card-assignments it admits, and sample proportionally. Yields in
        # weighted-random order so the caller's first accepted split is drawn
        # from the right distribution.
        all_splits = list(rec(0, need, {}))
        if not all_splits:
            return
        weights = [max(self._fills(cards, sp), 0) for sp in all_splits]
        if sum(weights) <= 0:
            yield from all_splits
            return
        pool = list(zip(all_splits, weights))
        while pool:
            tot = sum(w for _, w in pool)
            if tot <= 0:
                for sp, _ in pool:
                    yield sp
                return
            pick = self.rng.random() * tot
            acc = 0.0
            for idx, (sp, w) in enumerate(pool):
                acc += w
                if acc >= pick:
                    yield sp
                    pool.pop(idx)
                    break
            else:
                yield pool.pop()[0]

    def _deal_suit(self, remaining, n, r, suit, mem, already=None):
        """Remove and return `n` cards of one suit for one receiver.

        Honours `pair_cap`: the provable ceiling on how many pairs a seat can
        still hold in a suit — zero after failing to follow a PAIR lead, one
        after failing a tractor. Dealing them a pair anyway builds a world the
        play history has already ruled out. Nothing consumed this before;
        Codex raised it four times.

        Cards are REMOVED from `remaining`, so conservation is structural
        rather than something the index arithmetic has to get right.

        NOT named `_take`: HeuristicBot already defines one, and shadowing it
        from a subclass broke follow generation everywhere.
        """
        if n <= 0:
            return []
        is_seat = isinstance(r, int) and r != "kitty"
        cap = mem.max_pairs(r, suit) if is_seat else None
        run_cap = mem.max_run(r, suit) if is_seat else None
        if cap is None and run_cap is None:
            out = remaining[:n]
            del remaining[:n]
            return out
        # `held` starts from what is already pinned to this seat, so the cap
        # applies to the FULL hand rather than only to this deal.
        # Prefer distinct codes, so a capped seat is not handed a pair when an
        # alternative exists. Ties keep the shuffled order, so this stays a
        # random draw among the choices that respect the bound.
        out: list[str] = []
        held: Counter[str] = Counter(already or {})
        from ..engine.combos import decompose as _dec
        o = getattr(mem, "o", None)
        for _ in range(n):
            pick = None
            # UNIFORM among cap-respecting cards, rather than first-legal.
            # First-legal prefers distinct codes beyond what the caps require —
            # the second named posterior bias. Flagged so its contribution is
            # measurable separately from the split weighting.
            if UNIFORM_DEAL:
                elig = []
                for i, c in enumerate(remaining):
                    t = held + Counter([c])
                    if cap is not None and sum(v // 2 for v in t.values()) > cap:
                        continue
                    if run_cap is not None and o is not None and \
                            _dec(list(t.elements()), o).max_pair_run() > run_cap:
                        continue
                    elig.append(i)
                if not elig:
                    return None
                c = remaining.pop(self.rng.choice(elig))
                out.append(c)
                held[c] += 1
                continue
            for i, c in enumerate(remaining):
                trial = held + Counter([c])
                if cap is not None:
                    if sum(v // 2 for v in trial.values()) > cap:
                        continue
                if run_cap is not None and o is not None:
                    # A pair CAP is not a run cap: two non-consecutive pairs
                    # form no tractor, and a seat that failed a k-tractor
                    # obligation may still legally hold k-1 runs.
                    if _dec(list(trial.elements()), o).max_pair_run() > run_cap:
                        continue
                pick = i
                break
            if pick is None:
                return None
            c = remaining.pop(pick)
            out.append(c)
            held[c] += 1
        return out

    # -------------------------------------------------------------- rollout
    def _rollout(self, rnd: Round, seat: int, sampled: dict[int, list[str]],
                 buried: list[str], candidate: list[str]) -> float:
        clone: Round = copy.copy(rnd)
        # Sampled hands represent multisets, not sequences.  HeuristicBot's
        # continuation policy is intentionally simple and walks a list, so it
        # must receive a canonical representation or `_rollout` is a function
        # of sampler insertion order rather than of the game state.
        clone.hands = [sorted(sampled.get(s, rnd.hands[s])) for s in range(4)]
        clone.hands[seat] = sorted(rnd.hands[seat])
        clone.buried = sorted(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone._trusted_rollout = True  # skip follow re-validation (audit)
        clone.play(seat, list(candidate))
        policy = self.rollout_policy
        while clone.phase == "play":
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)


class MCSmartRoll(MCBot):
    """MCBot with SmartBot (memory-aware) rollouts — ~5x slower/decision."""

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self.rollout_policy = SmartBot()
