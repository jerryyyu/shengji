"""The bots' level at a ranked table, chosen by the rating of its people.

At a ranked table the two bots that oppose the people play Standard (the
casual table's relaxed bot, ``server.make_relaxed_bot``) when every person at
the table rates at most ``STANDARD_UP_TO``, and Advanced (the served bot)
otherwise. A guest counts as ``ratings.GUEST_RATING`` and a new account starts
at ``accounts.START_RATING``, so both meet Standard first. A bot that is a
person's partner always plays Advanced, so Standard is possible only when
every person sits on one team (one person, or two partners): with people on
both teams every bot partners someone.

When: the level is chosen when the table's game starts (``_start_game``: the
queue's table, a created ranked room, or Continue on a ranked saved game) and
again at the first round of each new game at that table (the round after a
point is scored, when the levels restart), from the ratings stored at that
moment. A rating that changes during a game, or any later round of it, never
changes the level. The one change inside a game: a newcomer who takes a
Standard seat at an open table makes that team a person's team, so its bots
play Advanced from the handover on (a level only ever rises mid-game).

Invisible: ``room.bot_level`` stays "advanced" at a ranked table, so no frame
carries the choice. The seats that play Standard are server-only
(``Room.bot_levels``); the round log names them, and each rated round reads
them at its start to rate those seats as ``ratings.STANDARD_BOT_RATING``.
"""
from __future__ import annotations

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


def stored_rating(user_id: int) -> float | None:
    """An account's stored rating, or None when it cannot be read."""
    try:
        return ratings.current_rating(accounts.STORE, user_id)
    except Exception:           # noqa: BLE001 - a failed read plays Advanced
        log.warning("rating read for the bots' level failed; the table plays Advanced")
        return None


def person_rating(seat: Any, rating_of: Callable[[int], float | None]) -> float | None:
    """A person's rating for the level: their account's, or a guest's fixed
    rating (also for an account deleted while seated)."""
    uid = seat.user_id
    if uid is None or accounts.is_deleted(uid):
        return ratings.GUEST_RATING
    return rating_of(uid)


def standard_seats(seats: list, rating_of: Callable[[int], float | None] = stored_rating) -> set[int]:
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
        bot = self.relaxed if self.levels.standard else self.served
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
        self._last_relaxed = seat in self.levels.standard
        if self._last_relaxed:
            return self.relaxed.decide_play(rnd, seat)
        return self.served.decide_play(rnd, seat)


def served_bot(bot: Any) -> Any:
    return bot.served if isinstance(bot, RankedBots) else bot


def choose(room: Any, build_relaxed: Callable[[Any, int], Any],
           rating_of: Callable[[int], float | None] = stored_rating) -> None:
    """Set a ranked room's bot level from its seats and the stored ratings
    (the caller holds the room's lock, between rounds). An unranked room is
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


def seat_taken(room: Any, seat: int) -> None:
    """A person took ``seat`` mid-game: if it played Standard, its team is a
    person's team now and both its bots play Advanced from here."""
    levels = getattr(room, "bot_levels", None)
    if levels is not None and seat in levels.standard:
        levels.standard = set()


def standard(room: Any) -> frozenset[int]:
    """The seats playing Standard now (server-only)."""
    levels = getattr(room, "bot_levels", None)
    return frozenset(levels.standard) if levels is not None else frozenset()
