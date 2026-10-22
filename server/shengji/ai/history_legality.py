"""History-legal world sampling: every earlier follow must be legal in the world.

A sampled world gives each hidden seat a hand NOW.  The seat's hand at any
earlier play of the round is that hand plus every card the seat has played
from that play on (cards leave a hand only by being played).  The world is
HISTORY-LEGAL when, for every earlier FOLLOW by a seat other than the acting
one, the engine's own `validate_follow` accepts the cards that seat played,
from the hand the world gives it at that moment, against the trick's lead.

The true deal passes by construction (the engine accepted every one of those
plays from the true hands), so rejecting a world that fails never discards the
truth.  The test is exactly as strong as the engine's follow rule and no
stronger: it restates nothing.

Why the sampler alone lets such worlds through: `Memory` turns a follow that
showed fewer pairs than were led into ``pair_cap = 0`` (and a short tractor
answer into ``run_cap``) on the seat's CURRENT hand.  The obligation applied to
the hand at the time of the follow, which also held every card the seat
played later.  A world that gives the seat one copy of a card whose twin the
seat played afterwards satisfies the cap today and still means the seat held
a pair it was obliged to play.  Follow-suit itself is already sound through
the public voids (a seat that showed out holds none of the suit now and,
truthfully, never plays it later), so in practice only the pair and tractor
obligations reject; the test still runs the whole rule.

Leads are not tested here: a lead is legal for any hand that holds its cards,
which every world does, and a refused throw is the refusal rule's subject
(`ai.refusal`).  An accepted multi-component throw does constrain the other
hands, but that is a lead-side inference this module does not draw.

`sample_worlds_history_legal` is production's draw (`cwv_policy.sample_worlds`
through ``bot._sample_hands`` and ``_complete_determinized_hands``) with this
test between the draw and the world, combined with the refusal test when the
round has refusals on record.  The history test runs for at most
``n * HISTORY_ATTEMPT_FACTOR`` attempts; after that the remaining worlds are
drawn exactly as today (refusal test only, then the plain fill), so the search
never stalls or runs short because of this rule, and the shortfall is
recorded.  The engine, `Memory` and the encoder closure are untouched.

THE DRAW-TIME FORM (``constrain=True``).  For the pair obligation the test has
a closed form.  Let seat ``t`` follow a lead carrying ``n`` pairs in effective
suit ``S`` and show ``shown < n`` pairs in ``S`` (exactly `Memory`'s
``pair_cap = 0`` condition).  The rule then says ``t`` held no more than
``shown`` pairs in ``S`` at that moment, and the ``shown`` pairs are among the
cards it played from then on, so its hand now may add NO pair in ``S`` to
those cards.  The current hand alone holding a pair is `Memory`'s cap; the
remaining way is a card whose single twin ``t`` played at or after the
earliest such follow.  `draw_constraints` lists those twins per ``(t, S)``,
and the constrained draw seeds them into the sampler's own per-seat pair
count (``MCBot._deal_suit``'s ``already``), so the existing ``pair_cap = 0``
check never deals the second copy.  The constraint is exact for the pair
obligation, so no rejection is needed for it; the tractor obligation (no
``k``-run held then) has no such closed form and stays with the oracle, which
still tests every drawn world.  The constrained draw is a different proposal
from rejection: the sampler chooses suit counts without seeing the twins, so
its distribution differs from the rejection-accepted set in how counts are
weighted (measured, not assumed equal).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..engine import legal as _legal
from ..engine.legal import IllegalPlay
from .refusal import pin_unplayed_attempt, refusal_consistent

#: attempts per requested world during which the history test applies; the
#: remaining attempts (up to the sampler's own ``SAMPLE_ATTEMPT_FACTOR``) draw
#: without it, so a state the sampler can rarely satisfy costs a bounded amount
HISTORY_ATTEMPT_FACTOR = 8


@dataclass(frozen=True)
class FollowEvent:
    """One earlier follow by another seat, with what it needs for the test."""
    seat: int
    cards: tuple[str, ...]
    lead: tuple[str, ...]
    #: every card this seat played from this play on, this play included
    later: tuple[str, ...]
    #: index of the trick (``len(rnd.history)`` for the current one)
    trick: int


def follow_events(rnd, seat: int) -> list[FollowEvent]:
    """Every follow of this round by a seat other than ``seat``, in table order."""
    tricks = list(rnd.history)
    if rnd.trick is not None and rnd.trick.plays:
        tricks.append(rnd.trick)
    flat = [(index, position, play) for index, trick in enumerate(tricks)
            for position, play in enumerate(trick.plays)]
    later: dict[int, tuple[str, ...]] = {s: () for s in range(4)}
    events: list[FollowEvent] = []
    for index, position, play in reversed(flat):
        later[play.seat] = tuple(play.cards) + later[play.seat]
        if position > 0 and play.seat != seat:
            events.append(FollowEvent(play.seat, tuple(play.cards),
                                      tuple(tricks[index].plays[0].cards),
                                      later[play.seat], index))
    events.reverse()
    return events


def first_violation(events, hands, ordering) -> int | None:
    """The index into ``events`` of the first follow the world's hands make
    illegal, else None.  ``hands`` are the world's four current hands."""
    for i, ev in enumerate(events):
        held = list(hands[ev.seat])
        held.extend(ev.later)
        try:
            _legal.validate_follow(list(ev.cards), held, list(ev.lead), ordering)
        except IllegalPlay:
            return i
    return None


def history_legal(rnd, seat: int, hands) -> bool:
    """Is every earlier follow by another seat legal in this world?"""
    return first_violation(follow_events(rnd, seat), hands, rnd.ordering) is None


def draw_constraints(rnd, seat: int, events=None) -> dict[tuple[int, str], Counter]:
    """``{(other seat, effective suit): Counter of codes}``: the cards whose
    single twin that seat played at or after its earliest follow that showed
    fewer pairs than were led in that suit (the draw-time form above).  Codes
    the seat played twice are absent (both copies are seen)."""
    if events is None:
        events = follow_events(rnd, seat)
    ordering = rnd.ordering
    out: dict[tuple[int, str], Counter] = {}
    for ev in events:
        if len(ev.lead) < 2:
            continue
        led = _legal.pair_count(list(ev.lead))
        if not led:
            continue
        suit = ordering.eff_suit(ev.lead[0])
        key = (ev.seat, suit)
        if key in out:
            continue
        shown = _legal.pair_count([c for c in ev.cards if ordering.eff_suit(c) == suit])
        if shown >= led:
            continue
        later = Counter(c for c in ev.later if ordering.eff_suit(c) == suit)
        out[key] = Counter({c: 1 for c, k in later.items() if k == 1})
    return {k: v for k, v in out.items() if v}


def constrained_draw(bot, constraints):
    """``propose(rnd, seat, mem)``: ``bot._sample_hands`` with each
    constrained seat's twins counted as already held in that suit, so its
    ``pair_cap = 0`` check never deals the second copy.  The bot's own rng and
    counters are used; the override lives only for the duration of one draw."""
    base = type(bot)._deal_suit

    def deal_suit(remaining, n, r, suit, mem, already=None):
        extra = constraints.get((r, suit)) if isinstance(r, int) else None
        if extra:
            if mem.max_pairs(r, suit) != 0:
                raise AssertionError(f"draw constraint on seat {r} suit {suit} without pair_cap 0")
            already = Counter(already or ()) + extra
        return base(bot, remaining, n, r, suit, mem, already)

    def propose(rnd, seat, mem):
        if not constraints:
            return bot._sample_hands(rnd, seat, mem)
        bot._deal_suit = deal_suit
        try:
            return bot._sample_hands(rnd, seat, mem)
        finally:
            del bot._deal_suit
    return propose


def sample_worlds_history_legal(bot, rnd, seat: int, n: int, refusals=(), *, mem,
                                check_budget=None, propose=None, constrain=False, stop=None):
    """``n`` worlds by production's draw, each history-legal while the history
    test's attempt budget lasts and consistent with every refusal in
    ``refusals`` (`ai.refusal`, the same test and pinning as
    `refusal.sample_worlds_refusal_aware`).

    Returns ``(worlds, attempts, stats)``.  ``stats`` carries the record
    fields: the follow events tested, the history rejections (also by how many
    tricks back the first violated follow lies), the worlds accepted after the
    history budget ran out (``history_fallback_worlds``: drawn as today) and,
    with refusals, the refusal rule's own fields.

    ``propose(rnd, seat, mem) -> (hands, buried) | None`` replaces
    ``bot._sample_hands`` as the source of drawn hands (a belief proposal plugs
    in here; served play passes None).  Its hands go through the same
    completion, refusal test and history test; the plain fill after the
    attempt cap stays production's draw.

    ``constrain=True`` (and no ``propose``) draws through `constrained_draw`
    with `draw_constraints`; the history test still runs on every world.  A
    proposal passed as ``propose`` is responsible for its own constraints
    (`draw_constraints` is the list to honour).

    ``stop() -> bool``, when given, is asked before every attempt until it
    returns True; from then on the history test's budget is spent: the worlds
    accepted so far are kept and later draws are accepted untested, as after
    ``history_cap`` (still refusal-tested, the plain fill still after the
    attempt cap).  ``stats`` then also carries ``draw_stopped``,
    ``drawn_worlds`` (the worlds accepted from ``draw``) and
    ``stopped_untested`` (those accepted untested after the stop).  Without it
    the draw is unchanged. This is a soft history-validation cutoff, not a
    wall-time bound: refusal rejections can consume the remaining
    ``n * SAMPLE_ATTEMPT_FACTOR`` proposal attempts and then production fill.
    Proposal batch sizes belong to the proposal, not this loop."""
    from .cwv_policy import sample_worlds
    events = follow_events(rnd, seat)
    ordering = rnd.ordering
    current = len(rnd.history)
    pinned = sum(pin_unplayed_attempt(mem, rnd, r, seat) for r in refusals)
    worlds = []
    attempts = 0
    refusal_rejected = 0
    rejected = 0
    unchecked = 0
    by_age: Counter[int] = Counter()
    constraints = draw_constraints(rnd, seat, events) if constrain and propose is None else {}
    if propose is not None:
        draw = propose
    elif constraints:
        draw = constrained_draw(bot, constraints)
    else:
        draw = bot._sample_hands
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    history_cap = n * HISTORY_ATTEMPT_FACTOR if events else 0
    stopped = False
    kept = 0
    while len(worlds) < n and attempts < cap:
        if check_budget is not None:
            check_budget()
        if stop is not None and not stopped and stop():
            stopped = True
            kept = len(worlds)
            history_cap = min(history_cap, attempts)
        attempts += 1
        sampled = draw(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        world = bot._complete_determinized_hands(rnd, seat, hands, buried=buried)
        if refusals and not all(refusal_consistent(rnd, world, r) for r in refusals):
            refusal_rejected += 1
            continue
        if attempts <= history_cap:
            bad = first_violation(events, world, ordering)
            if bad is not None:
                rejected += 1
                by_age[current - events[bad].trick] += 1
                continue
        elif events:
            unchecked += 1
        worlds.append((world, sorted(buried)))
    drawn = len(worlds)
    fill = 0
    if len(worlds) < n:
        extra, more = sample_worlds(bot, rnd, seat, n - len(worlds), mem=mem,
                                    check_budget=check_budget)
        attempts += more
        fill = len(extra)
        worlds.extend(extra)
    elif check_budget is not None:
        check_budget()
    stats = {"history_follow_events": len(events), "history_rejections": rejected,
             "history_fallback_worlds": unchecked + fill,
             "history_rejections_by_age": {str(k): v for k, v in sorted(by_age.items())}}
    if constrain:
        stats["history_draw_constraints"] = len(constraints)
        stats["history_draw_forbidden"] = sum(sum(c.values()) for c in constraints.values())
    if refusals:
        stats.update(refusal_observations=len(refusals), refusal_rejections=refusal_rejected,
                     refusal_fallback_worlds=fill, refusal_pinned_codes=pinned)
    if stop is not None:
        stats.update(draw_stopped=stopped, drawn_worlds=drawn,
                     stopped_untested=drawn - kept if stopped else 0)
    return worlds, attempts, stats
