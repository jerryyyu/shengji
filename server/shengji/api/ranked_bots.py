"""The bots' level at a ranked table, chosen by the rating of its people.

At a ranked table the two bots that oppose the people play Standard (the
casual table's relaxed bot, ``server.make_relaxed_bot``) when every person at
the table rates at most ``STANDARD_UP_TO``, and Advanced (the served bot)
otherwise. A guest counts as ``ratings.GUEST_RATING`` and a new account starts
at ``accounts.START_RATING``, so both meet Standard first. A bot that is a
person's partner always plays Advanced, so Standard is possible only when
every person sits on one team (one person, or two partners): with people on
both teams every bot partners someone.

When: the level is chosen for the table's game (``begin_game`` at
``_start_game``: the queue's table, a created ranked room, or Continue on a
ranked saved game) and again for each new game at that table (the round
after a point is scored, when the levels restart). It is read from the
round's own ordered rating snapshot (``RoomRatings.standing``: queued on the
ratings worker behind every earlier rating write, so a round just settled is
in it), awaited off the event loop once the round's cards are dealt and
before its declare window closes (``settle_game``), so before any card is
played; until then the bots are Advanced. A rating that changes
during the game never changes the level.

Inside a game the level only rises. A person who takes a Standard seat
makes that team a person's team, so both its bots play Advanced at once. A
new person or a different account at a seat of the people's team
(``seat_changed``: an open-table handover, a claim, a resume that brings
another account) has their rating read the same ordered way; while it is
read the Standard seats play Advanced, and if it is above ``STANDARD_UP_TO``
the table stays Advanced for the rest of the game. A reconnect by the same
account changes nothing. The rated anchors of a round in play are the ones
read when it started.

Invisible: ``room.bot_level`` stays "advanced" at a ranked table, so no frame
carries the choice. The seats that play Standard are server-only
(``Room.bot_levels``); the round log names them, and each rated round reads
them at its start to rate those seats as ``ratings.STANDARD_BOT_RATING``.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from . import accounts, ratings

log = logging.getLogger(__name__)

# The highest rating that still meets Standard opponents.
STANDARD_UP_TO = 1000.0


@dataclass
class SeatLevels:
    """The seats whose bots play Standard. One holder per room, shared by
    every copy of the room's bot, so a change reaches a search in flight."""
    standard: set[int] = field(default_factory=set)
    # the game's level waits for the round's ordered rating read
    pending_game: bool = False
    # seat checks in flight (``seat_changed``): Standard seats play Advanced
    checks: int = 0

    def plays_standard(self, seat: int) -> bool:
        return seat in self.standard and not self.checks and not self.pending_game


# Seat checks awaiting their rating read; the loop holds only weak references.
_TASKS: set = set()


def person_rating(seat: Any, rating_of: Callable[[int], float | None]) -> float | None:
    """A person's rating for the level: their account's, or a guest's fixed
    rating (also for an account deleted while seated)."""
    uid = seat.user_id
    if uid is None or accounts.is_deleted(uid):
        return ratings.GUEST_RATING
    return rating_of(uid)


def standard_seats(seats: list, rating_of: Callable[[int], float | None]) -> set[int]:
    """The bot seats that play Standard at a ranked table seated ``seats``:
    the two seats of the people's opposing team when every person sits on one
    team and rates at most ``STANDARD_UP_TO``; otherwise none."""
    people = [(s, seat) for s, seat in enumerate(seats) if seat is not None and not seat.is_bot]
    teams = {s % 2 for s, _ in people}
    if len(teams) != 1:
        return set()
    opposing = [s for s in range(len(seats)) if s % 2 != next(iter(teams))]
    if not all(seats[s] is not None and seats[s].is_bot for s in opposing):
        return set()
    for _, seat in people:
        r = person_rating(seat, rating_of)
        if r is None or r > STANDARD_UP_TO:
            return set()
    return set(opposing)


class RankedBots:
    """A ranked room's bot while some seats play Standard: ``relaxed`` (the
    relaxed wrap of the served bot) plays the cards of the seats in
    ``levels.standard``, the served bot every other decision. Declaring and
    burying are the served bot's at every seat, as in the relaxed bot."""

    def __init__(self, relaxed: Any, levels: SeatLevels):
        self.relaxed = relaxed
        self.levels = levels
        self._last_relaxed = False

    @property
    def served(self) -> Any:
        return self.relaxed.served

    @property
    def policy_name(self) -> str:
        bot = self.relaxed if any(map(self.levels.plays_standard, range(4))) else self.served
        return getattr(bot, "policy_name", type(bot).__name__)

    @property
    def last_decision_record(self) -> Any:
        bot = self.relaxed if self._last_relaxed else self.served
        return getattr(bot, "last_decision_record", None)

    def __getattr__(self, name: str) -> Any:
        if name in ("relaxed", "levels", "_last_relaxed") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.served, name)

    def __deepcopy__(self, memo: dict) -> "RankedBots":
        new = RankedBots.__new__(RankedBots)
        memo[id(self)] = new
        new.relaxed = copy.deepcopy(self.relaxed, memo)
        new.levels = self.levels
        new._last_relaxed = self._last_relaxed
        return new

    def observe_public(self, rnd: Any) -> None:
        self.relaxed.observe_public(rnd)

    def decide_declare(self, rnd: Any, seat: int, final: bool = False) -> Any:
        self._last_relaxed = False
        return self.served.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd: Any, seat: int) -> Any:
        self._last_relaxed = False
        return self.served.decide_bury(rnd, seat)

    def decide_play(self, rnd: Any, seat: int) -> Any:
        self._last_relaxed = self.levels.plays_standard(seat)
        if self._last_relaxed:
            return self.relaxed.decide_play(rnd, seat)
        return self.served.decide_play(rnd, seat)


def served_bot(bot: Any) -> Any:
    return bot.served if isinstance(bot, RankedBots) else bot


def choose(room: Any, build_relaxed: Callable[[Any, int], Any],
           rating_of: Callable[[int], float | None]) -> None:
    """Set a ranked room's bot level from its seats and ``rating_of`` (the
    caller holds the room's lock, before the round's first play). An unranked room is
    left alone. A missing Standard package plays Advanced everywhere."""
    if not ratings.ranked(room):
        return
    if room.bot_levels is None:
        room.bot_levels = SeatLevels()
    served = served_bot(room.bot)
    seats = standard_seats(room.seats, rating_of)
    if seats:
        relaxed = (room.bot.relaxed if isinstance(room.bot, RankedBots)
                   else build_relaxed(served, room.bot_seed))
        if relaxed is served:
            seats = set()
        else:
            room.bot = room.bot if isinstance(room.bot, RankedBots) else RankedBots(relaxed, room.bot_levels)
    if not seats:
        room.bot = served
    room.bot_levels.standard = seats


def begin_game(room: Any) -> None:
    """A ranked game starts (``_start_game``) or a new one starts at the table
    (the caller holds the lock, after ``ratings.round_started``): its bots are
    Advanced until ``settle_game`` reads the round's ordered ratings."""
    if not ratings.ranked(room):
        return
    if room.bot_levels is None:
        room.bot_levels = SeatLevels()
    room.bot = served_bot(room.bot)
    room.bot_levels.standard = set()
    room.bot_levels.pending_game = True


async def settle_game(room: Any, build_relaxed: Callable[[Any, int], Any]) -> None:
    """Choose a pending game's level from the round's ordered rating read
    (``RoomRatings.standing``), awaited off the loop; the round's rated
    anchors follow it. Called by the round's deal before its declare window
    closes, so before any card is played; the caller does not hold the lock."""
    levels = getattr(room, "bot_levels", None)
    if levels is None or not levels.pending_game:
        return
    rnd, tracker = room.round, room.ratings
    future = tracker.standing if tracker is not None else None
    standing: dict | None = {}
    if future is not None:
        try:
            standing = dict(await asyncio.wrap_future(future))
        except Exception:       # noqa: BLE001 - an unread rating plays Advanced
            log.warning("ordered rating read failed; the table plays Advanced")
            standing = None
    async with room.lock:
        if room.round is not rnd or room.ratings is not tracker or not levels.pending_game:
            return
        levels.pending_game = False
        if standing is None:
            return
        present = tracker.present if tracker is not None else {}

        def rating_of(uid: int) -> float | None:
            # only the accounts at the table when the round started are read
            if uid not in present.values() or uid not in standing:
                return None
            return standing[uid][0]
        choose(room, build_relaxed, rating_of)
        chosen = set(levels.standard)
        if tracker is not None:
            tracker.anchors = [ratings.STANDARD_BOT_RATING if s in chosen and seat.is_bot
                               else ratings.GUEST_RATING for s, seat in enumerate(room.seats)]
        room.log_event("bot_levels", level="standard" if chosen else "advanced",
                       standard_seats=sorted(chosen))


def level_of(room: Any, seat: int) -> str:
    """The level the bot at ``seat`` plays now: "standard" or "advanced"."""
    levels = getattr(room, "bot_levels", None)
    return "standard" if levels is not None and levels.plays_standard(seat) else "advanced"


def _ordered_rating(user_id: int) -> "asyncio.Future":
    store = accounts.STORE
    return asyncio.wrap_future(ratings._EXECUTOR.submit(ratings.read_standing, store, [user_id]))


async def _check(room: Any, levels: SeatLevels, user_id: int, on_change: Callable[[], None]) -> None:
    rating: float | None = None
    try:
        standing = await _ordered_rating(user_id)
        if user_id in standing:
            rating = standing[user_id][0]
    except Exception:           # noqa: BLE001 - an unread rating plays Advanced
        log.warning("ordered rating read failed; the table plays Advanced")
    async with room.lock:
        levels.checks -= 1
        if rating is None or rating > STANDARD_UP_TO:
            levels.standard = set()
        on_change()


def seat_changed(room: Any, seat: int, before: Any = None,
                 on_change: Callable[[], None] = lambda: None) -> None:
    """A new person, or a different account, holds ``seat`` mid-game (the
    caller holds the lock). ``before`` is the account that held it (None
    for a bot or a guest); the same account again changes nothing. The
    level only rises: a Standard seat taken makes its team Advanced; a
    newcomer on the people's team is checked against ``STANDARD_UP_TO`` by
    an ordered read, while the Standard seats play Advanced. ``on_change``
    runs (under the lock) when a check ends."""
    levels = getattr(room, "bot_levels", None)
    if levels is None or not levels.standard:
        return
    sd = room.seats[seat]
    uid = None if sd.user_id is None or accounts.is_deleted(sd.user_id) else sd.user_id
    if seat in levels.standard:
        levels.standard = set()
        return
    if uid is None or uid == before:
        return                  # a guest counts 1000; the same account is frozen
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        levels.standard = set()  # off the loop no read can be awaited: Advanced
        return
    levels.checks += 1
    task = loop.create_task(_check(room, levels, uid, on_change))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def seat_taken(room: Any, seat: int) -> None:
    """A person took ``seat`` mid-game: if it played Standard, its team is a
    person's team now and both its bots play Advanced from here."""
    levels = getattr(room, "bot_levels", None)
    if levels is not None and seat in levels.standard:
        levels.standard = set()


def standard(room: Any) -> frozenset[int]:
    """The seats chosen for Standard (server-only), whether or not a seat
    check holds them at Advanced for now."""
    levels = getattr(room, "bot_levels", None)
    return frozenset(levels.standard) if levels is not None else frozenset()
