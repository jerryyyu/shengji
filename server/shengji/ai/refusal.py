"""Refusal-aware world sampling (#676 strategy B, the SAMPLER side only).

A multi-component lead (a throw) is checked by the engine against the other
three hands (`engine.legal.validate_lead`): a component is BEATABLE when some
one other hand holds, in the led effective suit, a higher card (a single), a
higher pair (a pair) or a higher pair-run of the same length (a tractor).  If
any component is beatable the throw is refused and the leader is forced down
to the LOWEST beatable component -- lowest by ``(pair_len, top)`` -- and the
engine posts ``Round.notice = {"kind": "failed_throw", "seat", "attempted",
"forced"}`` for everyone at the table (``api.server.state_json`` sends it to
all four seats; the bots never read it, #676 category 1).

THE INFERENCE.  Let the throw ``A`` by seat ``s`` at the start of trick ``T``
be forced to component ``F``.  Then at that moment, with the true hands:

  (i)  some seat ``t != s`` held, in ``A``'s suit, something that beats ``F``
       (a higher single / a higher pair / a higher run of ``F``'s length, in
       ONE hand -- the scan is per hand, never pooled across seats); and
  (ii) no seat ``t != s`` could beat any component of ``A`` that is lower
       than ``F`` in the ``(pair_len, top)`` order (else THAT one would have
       been forced).

Rather than restate (i) and (ii) by hand, a sampled world is tested against
the engine's own rule: rebuild every seat's hand AS IT WAS when the throw was
made (its sampled hand now plus everything it has played in trick ``T`` and
later -- cards leave a hand only by being played) and run the real
`validate_lead` on ``A``.  The world is CONSISTENT iff the engine refuses the
throw and forces exactly ``F``.  The true deal passes by construction (it is
the very call the engine made), so rejecting inconsistent worlds never
discards the truth: the rule is sound, and it is exactly as strong as the
engine's rule, never more.

A second, cheaper consequence of the same notice: ``s`` held every card of
``A`` when it threw, so it still holds each attempted card it has not played
since.  Those are pinned to ``s`` through the sampler's declared-card channel
(`Memory.known`) before drawing, which keeps the rejection rate low when the
thrower is an opponent of the acting seat.  A code the declarer already pinned
keeps the declarer; the rejection test still covers it.

Nothing here touches the encoder or its hashed source closure
(`cwv_policy.AFTERSTATE_SOURCE_PATHS`, which includes ``ai/memory.py`` and
``engine/round.py``); the notice is read here, outside that closure, and only
sampled worlds change -- a model-input change is a different project.

The notice lives at most ``Round.NOTICE_PLAYS`` (8) accepted plays, so the
trick it refers to is the current one or one of the previous two. A later
failed throw can replace it before a particular seat acts again; observing
once per trick does NOT guarantee seeing every refusal, including one's own
failed throw. `RefusalLedger` retains only the notices that its bot instance
observes. Screen bots are per-seat; the server shares a room bot across its
bot-controlled seats and deep-copies that bot with each turn snapshot.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..engine.legal import IllegalPlay, validate_lead
from ..engine.round import Round

#: how far back a posted notice's throw can lie (``NOTICE_PLAYS`` = 8 plays:
#: the rest of trick T, all of T+1 and the first play of T+2)
_LOOKBACK_TRICKS = 3


@dataclass(frozen=True)
class Refusal:
    """One failed throw, as public information."""
    seat: int
    attempted: tuple[str, ...]
    forced: tuple[str, ...]
    #: index into ``Round.history`` of the trick the throw led; equal to
    #: ``len(history)`` while that trick is still the current one
    trick_index: int


def _lead_matches(trick, seat: int, forced) -> bool:
    if trick is None or not trick.plays:
        return False
    lead = trick.plays[0]
    return lead.seat == seat and Counter(lead.cards) == Counter(forced)


def throw_trick_index(rnd: Round, seat: int, forced) -> int | None:
    """The most recent trick led by ``seat`` with exactly ``forced``: the
    current trick, else the last `_LOOKBACK_TRICKS` resolved ones."""
    if _lead_matches(rnd.trick, seat, forced):
        return len(rnd.history)
    for index in range(len(rnd.history) - 1,
                       max(-1, len(rnd.history) - 1 - _LOOKBACK_TRICKS), -1):
        if _lead_matches(rnd.history[index], seat, forced):
            return index
    return None


def observe_refusal(rnd: Round) -> Refusal | None:
    """The posted failed-throw notice, located in the public record."""
    notice = getattr(rnd, "notice", None)
    if not isinstance(notice, dict) or notice.get("kind") != "failed_throw":
        return None
    seat = int(notice["seat"])
    attempted = tuple(notice["attempted"])
    forced = tuple(notice["forced"])
    index = throw_trick_index(rnd, seat, forced)
    if index is None:
        return None
    return Refusal(seat, attempted, forced, index)


def on_record(rnd: Round, refusal: Refusal) -> bool:
    """Is the throw trick still where the refusal says it is?"""
    if refusal.trick_index < len(rnd.history):
        trick = rnd.history[refusal.trick_index]
    elif refusal.trick_index == len(rnd.history):
        trick = rnd.trick
    else:
        return False
    return _lead_matches(trick, refusal.seat, refusal.forced)


def plays_since(rnd: Round, trick_index: int) -> dict[int, Counter[str]]:
    """Per seat, every card played in trick ``trick_index`` or later (the
    throw was validated against the hands BEFORE any play of that trick)."""
    since: dict[int, Counter[str]] = {s: Counter() for s in range(4)}
    tricks = list(rnd.history[trick_index:])
    if rnd.trick is not None and rnd.trick.plays:
        tricks.append(rnd.trick)
    for trick in tricks:
        for play in trick.plays:
            since[play.seat].update(play.cards)
    return since


def throw_time_hands(rnd: Round, hands, trick_index: int) -> list[list[str]]:
    """The four hands as they were when trick ``trick_index`` was led, from
    the four hands of one complete world now."""
    since = plays_since(rnd, trick_index)
    return [list(hands[s]) + list(since[s].elements()) for s in range(4)]


def refusal_consistent(rnd: Round, hands, refusal: Refusal) -> bool:
    """Would the engine, given this world's hands at throw time, have refused
    ``refusal.attempted`` and forced exactly ``refusal.forced``?  The real
    `validate_lead`, nothing restated."""
    assert rnd.ordering is not None
    full = throw_time_hands(rnd, hands, refusal.trick_index)
    others = [full[s] for s in range(4) if s != refusal.seat]
    try:
        accepted, message = validate_lead(list(refusal.attempted), full[refusal.seat],
                                          others, rnd.ordering)
    except IllegalPlay:
        return False       # this world does not even give the thrower the throw
    return message is not None and Counter(accepted) == Counter(refusal.forced)


def pin_unplayed_attempt(mem, rnd: Round, refusal: Refusal, seat: int) -> int:
    """Pin to the thrower every attempted card it has not played since (public:
    it held all of them when it threw).  Returns the number of codes pinned.
    Nothing to pin when the acting seat is the thrower (its own hand)."""
    if refusal.seat == seat:
        return 0
    since = plays_since(rnd, refusal.trick_index)[refusal.seat]
    pinned = 0
    for code, held in Counter(refusal.attempted).items():
        left = min(held - since[code], mem.unseen.get(code, 0))
        if left > 0 and code not in mem.known:
            mem.known[code] = (refusal.seat, left)
            pinned += 1
    return pinned


class RefusalLedger:
    """The refusals seen so far in the current round, kept by the bot."""

    def __init__(self):
        self.key = None
        self.refusals: list[Refusal] = []

    def observe(self, rnd: Round) -> list[Refusal]:
        """Read the posted notice (if any) and return the round's refusals;
        a new round (a different deck) starts an empty ledger, and an entry
        the record no longer supports is dropped."""
        key = tuple(rnd.deck)
        if key != self.key:
            self.key = key
            self.refusals = []
        seen = observe_refusal(rnd)
        if seen is not None and seen not in self.refusals:
            self.refusals.append(seen)
        self.refusals = [r for r in self.refusals if on_record(rnd, r)]
        return list(self.refusals)


def sample_worlds_refusal_aware(bot, rnd: Round, seat: int, n: int, refusals, *, mem,
                                check_budget=None):
    """``n`` worlds through production's sampler, each consistent with every
    refusal in ``refusals`` -- `cwv_policy.sample_worlds` with one rejection
    test added between the draw and the world.

    Attempts (sampler failures and refusal rejections alike) are capped at
    ``n * bot.SAMPLE_ATTEMPT_FACTOR``, the sampler's own contract; a shortfall
    at the cap is filled by plain `sample_worlds` draws (its own cap again), so
    the search never stalls and never runs short because of this rule.
    Returns ``(worlds, attempts, stats)``; ``stats`` carries the record fields.
    """
    from .cwv_policy import sample_worlds
    pinned = sum(pin_unplayed_attempt(mem, rnd, r, seat) for r in refusals)
    worlds = []
    attempts = 0
    rejected = 0
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    while len(worlds) < n and attempts < cap:
        if check_budget is not None:
            check_budget()
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        world = bot._complete_determinized_hands(rnd, seat, hands, buried=buried)
        if not all(refusal_consistent(rnd, world, r) for r in refusals):
            rejected += 1
            continue
        worlds.append((world, sorted(buried)))
    fallback = 0
    if len(worlds) < n:
        extra, more = sample_worlds(bot, rnd, seat, n - len(worlds), mem=mem,
                                    check_budget=check_budget)
        attempts += more
        fallback = len(extra)
        worlds.extend(extra)
    elif check_budget is not None:
        check_budget()
    stats = {"refusal_observations": len(refusals), "refusal_rejections": rejected,
             "refusal_fallback_worlds": fallback, "refusal_pinned_codes": pinned}
    return worlds, attempts, stats
