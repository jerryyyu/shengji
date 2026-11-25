"""The bots' level at a ranked table, chosen by the rating of its people.

At a ranked table the two bots that oppose the people play Beginner (the
relaxed bot with wider card-play noise, ``server.make_beginner_bot``) when
every person at the table rates at most ``BEGINNER_UP_TO``; Standard (the
casual table's relaxed bot, ``server.make_relaxed_bot``) when every person
rates at most ``STANDARD_UP_TO`` and not all of them at most
``BEGINNER_UP_TO``; and Advanced (the served bot) otherwise. A new account
starts at ``accounts.START_RATING`` and a guest counts as
``ratings.GUEST_RATING`` (800 both), so both meet Beginner first. A bot that is a person's
partner always plays Advanced, so Beginner or Standard is possible only when
every person sits on one team (one person, or two partners): with people on
both teams every bot partners someone. Beginner and Standard are the relaxed
levels (``RELAXED_LEVELS``); one table plays at most one of them.

When: the level is chosen for the table's game (``begin_game`` at
``_start_game``: the queue's table, a created ranked room, or Continue on a
ranked saved game) and again for each new game at that table (the round
after a point is scored, when the levels restart), from scratch, so a new
game can be easier than the last. It is read from the round's own ordered
rating snapshot (``RoomRatings.standing``: queued on the ratings worker
behind every earlier rating write, so a round just settled is in it),
awaited off the event loop once the round's cards are dealt and before its
declare window closes (``settle_game``), so before any card is played;
until then the bots are Advanced. An account seated after that read (a
guest who signs in during the deal) gets an ordered read of its own, and
the choice applies only to the seats' holders it was read for.

Inside a game the level only rises (Beginner, then Standard, then
Advanced). Every later round of a game whose opponents play a relaxed level
(``begin_round``) is re-checked at the same settle point, from that round's
ordered snapshot and by the same rule: a higher level than the table's
applies from that round's first card for the rest of the game, and a lower
one changes nothing. So a rating that crosses its line in a round takes
effect at the next round, never mid-round, and a rating that falls back
under it does not lower the level before the next game. While that re-check
is read the table keeps its level; a failed read plays Advanced. A person who takes a relaxed seat
makes that team a person's team, so both its bots play Advanced at once. A
new person or a different account at a seat of the people's team
(``seat_changed``: an open-table handover, a claim, a resume that brings
another account) has their rating read the same ordered way; while it is
read the relaxed seats play Advanced, and if it is above the line of the
table's level (``BEGINNER_UP_TO`` or ``STANDARD_UP_TO``) the table stays
Advanced for the rest of the game. A reconnect by the same
account changes nothing. A search plays the level its snapshot was taken
at (``pin``), and a decision whose level is not the seat's level at commit
is searched again. The rated anchors of a round are those of the level its
cards are played at: set when it starts and rewritten at its settle point
when the level is chosen or rises there; a change during its play leaves
them.

Invisible: ``room.bot_level`` stays "advanced" at a ranked table, so no frame
carries the choice. The seats that play a relaxed level, and which level, are
server-only (``Room.bot_levels``); the round log names them ("beginner" or
"standard"), a ``bot_levels`` record names the level a round settled at
when it is chosen or rises there (a rise also names ``rose_from``), and
each rated round rates those seats at that level's anchor
(``ratings.BOT_ANCHORS``).
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
# The highest rating that still meets Beginner opponents.
BEGINNER_UP_TO = 800.0
# The levels a ``RankedBots`` hands card play to, weakest first.
RELAXED_LEVELS = ("beginner", "standard")
# Every level, weakest first: inside a game the table only moves right.
LEVEL_ORDER = ("beginner", "standard", "advanced")


@dataclass
class SeatLevels:
    """The seats whose bots play a relaxed level, and that level. One holder
    per room, shared by every copy of the room's bot, so a change reaches a
    search in flight."""
    # the seats playing ``level`` (Beginner or Standard), the rest Advanced
    standard: set[int] = field(default_factory=set)
    level: str = "standard"
    # the game's level waits for the round's ordered rating read
    pending_game: bool = False
    # a later round's rise check waits for that round's ordered rating read
    pending_rise: bool = False
    # seat checks in flight (``seat_changed``): relaxed seats play Advanced
    checks: int = 0
    # seat changes recorded while the game's level is pending: a read made
    # before one is not applied (``settle_game``)
    changes: int = 0
    # the game these levels belong to, raised by ``begin_game``: a seat check
    # started in an earlier game changes nothing when it ends
    game: int = 0

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


def line_of(level: str) -> float:
    """The highest rating that still meets ``level`` (a relaxed level)."""
    return BEGINNER_UP_TO if level == "beginner" else STANDARD_UP_TO


def table_level(seats: list, rating_of: Callable[[int], float | None]) -> tuple[str, set[int]]:
    """The opposing bots' level at a ranked table seated ``seats``, and the
    seats that play it: the two seats of the people's opposing team when
    every person sits on one team, at "beginner" when every person rates at
    most ``BEGINNER_UP_TO`` and at "standard" when every person rates at
    most ``STANDARD_UP_TO``; otherwise ("advanced", no seats)."""
    people = [(s, seat) for s, seat in enumerate(seats) if seat is not None and not seat.is_bot]
    teams = {s % 2 for s, _ in people}
    if len(teams) != 1:
        return "advanced", set()
    opposing = [s for s in range(len(seats)) if s % 2 != next(iter(teams))]
    if not all(seats[s] is not None and seats[s].is_bot for s in opposing):
        return "advanced", set()
    level = "beginner"
    for _, seat in people:
        r = person_rating(seat, rating_of)
        if r is None or r > STANDARD_UP_TO:
            return "advanced", set()
        if r > BEGINNER_UP_TO:
            level = "standard"
    return level, set(opposing)


def standard_seats(seats: list, rating_of: Callable[[int], float | None]) -> set[int]:
    """The bot seats that play a relaxed level (Beginner or Standard) at a
    ranked table seated ``seats`` (``table_level``)."""
    return table_level(seats, rating_of)[1]


class RankedBots:
    """A ranked room's bot while some seats play a relaxed level: ``relaxed``
    (the relaxed wrap of the served bot at ``level``, Beginner or Standard)
    plays the cards of the seats in ``levels.standard``, the served bot every
    other decision. Declaring and burying are the served bot's at every seat,
    as in the relaxed bot."""

    def __init__(self, relaxed: Any, levels: SeatLevels, level: str = "standard"):
        self.relaxed = relaxed
        self.levels = levels
        self.level = level
        self._last_relaxed = False
        # (seat, plays the relaxed level) bound by ``pin`` on a search's copy: that
        # search plays the level its snapshot was taken at
        self._pinned: tuple[int, bool] | None = None

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
        if name in ("relaxed", "levels", "level", "_last_relaxed", "_pinned") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.served, name)

    def __deepcopy__(self, memo: dict) -> "RankedBots":
        new = RankedBots.__new__(RankedBots)
        memo[id(self)] = new
        new.relaxed = copy.deepcopy(self.relaxed, memo)
        new.levels = self.levels
        new.level = self.level
        new._last_relaxed = self._last_relaxed
        new._pinned = self._pinned
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
        if self._pinned is not None and self._pinned[0] == seat:
            self._last_relaxed = self._pinned[1]
        else:
            self._last_relaxed = self.levels.plays_standard(seat)
        if self._last_relaxed:
            return self.relaxed.decide_play(rnd, seat)
        return self.served.decide_play(rnd, seat)


def pin(bot: Any, seat: int, level: str) -> None:
    """Bind a search's bot copy to ``level`` for ``seat``: what it plays does
    not follow a level change during the search."""
    if isinstance(bot, RankedBots):
        bot._pinned = (seat, level in RELAXED_LEVELS)


def unpin(bot: Any) -> None:
    if isinstance(bot, RankedBots):
        bot._pinned = None


def played_level(bot: Any) -> str:
    """The level of the card play ``bot`` last decided: the relaxed bot's
    level ("beginner" or "standard") only when a ``RankedBots`` handed it to
    the relaxed bot."""
    return bot.level if isinstance(bot, RankedBots) and bot._last_relaxed else "advanced"


def served_bot(bot: Any) -> Any:
    return bot.served if isinstance(bot, RankedBots) else bot


def choose(room: Any, build_relaxed: Callable[[Any, int], Any],
           rating_of: Callable[[int], float | None],
           build_beginner: Callable[[Any, int], Any] | None = None) -> None:
    """Set a ranked room's bot level from its seats and ``rating_of`` (the
    caller holds the room's lock, before the round's first play). An
    unranked room is left alone. ``build_relaxed`` builds Standard and
    ``build_beginner`` Beginner (without it a Beginner table plays Standard);
    a builder that returns the served bot (its package missing) plays
    Advanced everywhere."""
    if not ratings.ranked(room):
        return
    if room.bot_levels is None:
        room.bot_levels = SeatLevels()
    served = served_bot(room.bot)
    level, seats = table_level(room.seats, rating_of)
    if level == "beginner" and build_beginner is None:
        level = "standard"
    if seats:
        if isinstance(room.bot, RankedBots) and room.bot.level == level:
            relaxed = room.bot.relaxed
        else:
            build = build_beginner if level == "beginner" else build_relaxed
            relaxed = build(served, room.bot_seed)
        if relaxed is served:
            seats = set()
        elif not (isinstance(room.bot, RankedBots) and room.bot.relaxed is relaxed):
            room.bot = RankedBots(relaxed, room.bot_levels, level)
    if not seats:
        room.bot = served
    room.bot_levels.standard = seats
    room.bot_levels.level = level if seats else "standard"


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
    room.bot_levels.pending_rise = False
    room.bot_levels.game += 1
    room.bot_levels.checks = 0      # an earlier game's checks no longer hold its seats


def begin_round(room: Any) -> None:
    """A later round of a ranked game starts (the caller holds the lock, with
    the round in place and before its deal): when its opponents play a
    relaxed level, ``settle_game`` re-reads the people's ratings for it and
    raises the level if they have crossed its line."""
    levels = getattr(room, "bot_levels", None)
    if levels is None or levels.pending_game or not ratings.ranked(room):
        return
    levels.pending_rise = bool(levels.standard)


def _identities(room: Any, levels: SeatLevels) -> tuple:
    """Who holds each seat, and how many seat changes were recorded."""
    return (tuple((sd.is_bot, sd.user_id) for sd in room.seats), levels.changes)


def _seated_accounts(room: Any) -> list[int]:
    return sorted({sd.user_id for sd in room.seats
                   if not sd.is_bot and sd.user_id is not None
                   and not accounts.is_deleted(sd.user_id)})


async def settle_game(room: Any, build_relaxed: Callable[[Any, int], Any],
                      build_beginner: Callable[[Any, int], Any] | None = None) -> None:
    """Choose a pending game's level, or check a later round for a rise
    (``begin_round``), awaited off the loop: from the round's ordered rating
    read (``RoomRatings.standing``), and for an account seated since that
    read (a guest who signed in during the deal) from an ordered read of its
    own. The result applies only if the round and every seat's holder are
    still those the reads were made for (one retry, then Advanced); the
    round's rated anchors follow it. Called by the round's deal before its
    declare window closes, so before any card is played; the caller does not
    hold the lock."""
    levels = getattr(room, "bot_levels", None)
    if levels is None or not (levels.pending_game or levels.pending_rise):
        return
    rnd, tracker = room.round, room.ratings
    apply = _apply_game if levels.pending_game else _apply_rise

    def current() -> bool:
        if room.round is not rnd or room.ratings is not tracker:
            return False
        return levels.pending_game if apply is _apply_game else (
            levels.pending_rise and not levels.pending_game)

    future = tracker.standing if tracker is not None else None
    standing: dict | None = {}
    if future is not None:
        try:
            standing = dict(await asyncio.wrap_future(future))
        except Exception:       # noqa: BLE001 - an unread rating plays Advanced
            log.warning("ordered rating read failed; the table plays Advanced")
            standing = None
    present = set(tracker.present.values()) if tracker is not None else set()
    for _ in range(2):
        async with room.lock:
            if not current():
                return
            seen = _identities(room, levels)
            missing = [uid for uid in _seated_accounts(room)
                       if standing is not None and (uid not in present or uid not in standing)]
        extra: dict = {}
        if missing:
            try:
                extra = dict(await _ordered_read(missing))
            except Exception:   # noqa: BLE001 - an unread rating plays Advanced
                log.warning("ordered rating read failed; the table plays Advanced")
                standing = None
        async with room.lock:
            if not current():
                return
            if _identities(room, levels) != seen:
                continue        # a seat changed hands during the read
            apply(room, levels, tracker, standing, present, extra, build_relaxed, build_beginner)
            return
    async with room.lock:
        if current():
            apply(room, levels, tracker, None, present, {}, build_relaxed, build_beginner)


def _rating_reader(standing: dict, present: set, extra: dict) -> Callable[[int], float | None]:
    def rating_of(uid: int) -> float | None:
        if uid in present and uid in standing:
            return standing[uid][0]
        return extra[uid][0] if uid in extra else None
    return rating_of


def _apply_game(room: Any, levels: SeatLevels, tracker: Any, standing: dict | None,
                present: set, extra: dict, build_relaxed: Callable[[Any, int], Any],
                build_beginner: Callable[[Any, int], Any] | None = None) -> None:
    levels.pending_game = False
    if standing is not None:
        choose(room, build_relaxed, _rating_reader(standing, present, extra), build_beginner)
    _record_level(room, levels, tracker)


def _apply_rise(room: Any, levels: SeatLevels, tracker: Any, standing: dict | None,
                present: set, extra: dict, build_relaxed: Callable[[Any, int], Any],
                build_beginner: Callable[[Any, int], Any] | None = None) -> None:
    """A later round's rise check: the level the rule gives now applies only
    when it is above the table's; an unread rating plays Advanced."""
    levels.pending_rise = False
    before = levels.level if levels.standard else "advanced"
    if standing is None:
        level = "advanced"
    else:
        rating_of = _rating_reader(standing, present, extra)
        level = table_level(room.seats, rating_of)[0]
        if level == "beginner" and build_beginner is None:
            level = "standard"
    if LEVEL_ORDER.index(level) <= LEVEL_ORDER.index(before):
        return
    if standing is None:
        room.bot = served_bot(room.bot)
        levels.standard = set()
        levels.level = "standard"
    else:
        choose(room, build_relaxed, rating_of, build_beginner)
    _record_level(room, levels, tracker, rose_from=before)


def _record_level(room: Any, levels: SeatLevels, tracker: Any, **fields: Any) -> None:
    """The round's level is settled before its first card: its rated anchors
    follow it, and the room log records it."""
    chosen = set(levels.standard)
    if tracker is not None:
        # only the seats that were bots when the round started (``round_started``)
        # take the chosen level's anchor; a person's opening anchor stands,
        # whoever holds the seat now
        opening = list(tracker.anchors) or [ratings.seat_anchor(seat) for seat in room.seats]
        kinds = list(tracker.kinds) or [ratings.BOT if seat.is_bot else None for seat in room.seats]
        tracker.anchors = [ratings.BOT_ANCHORS[levels.level if s in chosen else "advanced"]
                           if kinds[s] == ratings.BOT else opening[s] for s in range(len(room.seats))]
    room.log_event("bot_levels", level=levels.level if chosen else "advanced",
                   standard_seats=sorted(chosen), **fields)


def level_of(room: Any, seat: int) -> str:
    """The level the bot at ``seat`` plays now: "beginner", "standard" or
    "advanced"."""
    levels = getattr(room, "bot_levels", None)
    return levels.level if levels is not None and levels.plays_standard(seat) else "advanced"


def log_level(room: Any) -> str | None:
    """The relaxed level chosen for the table's opposing seats (server-only),
    or None when none is."""
    levels = getattr(room, "bot_levels", None)
    return levels.level if levels is not None and levels.standard else None


def _ordered_read(user_ids: list[int]) -> "asyncio.Future":
    """The accounts' ``(rating, rated_rounds)``, read on the ratings worker
    behind every rating write queued before it."""
    store = accounts.STORE
    return asyncio.wrap_future(ratings._EXECUTOR.submit(ratings.read_standing, store, list(user_ids)))


async def _check(room: Any, levels: SeatLevels, user_id: int, on_change: Callable[[], None],
                 game: int | None = None) -> None:
    game = levels.game if game is None else game
    rating: float | None = None
    try:
        standing = await _ordered_read([user_id])
        if user_id in standing:
            rating = standing[user_id][0]
    except Exception:           # noqa: BLE001 - an unread rating plays Advanced
        log.warning("ordered rating read failed; the table plays Advanced")
    async with room.lock:
        if levels.game != game:
            return              # a new game began during the read: its level stands
        levels.checks -= 1
        if rating is None or rating > line_of(levels.level):
            levels.standard = set()
        on_change()


def seat_changed(room: Any, seat: int, before: Any = None,
                 on_change: Callable[[], None] = lambda: None) -> None:
    """A new person, or a different account, holds ``seat`` mid-game (the
    caller holds the lock). ``before`` is the account that held it (None
    for a bot or a guest); the same account again changes nothing. The
    level only rises: a relaxed seat taken makes its team Advanced; a
    newcomer on the people's team is checked against the line of the
    table's level (``line_of``) by an ordered read, while the relaxed seats
    play Advanced; above it the table is Advanced for the rest of the game.
    ``on_change`` runs (under the lock) when a check ends."""
    levels = getattr(room, "bot_levels", None)
    if levels is None:
        return
    if levels.pending_game:
        levels.changes += 1     # ``settle_game`` reads the seat as it is now
        return
    if not levels.standard:
        return
    sd = room.seats[seat]
    uid = None if sd.user_id is None or accounts.is_deleted(sd.user_id) else sd.user_id
    if seat in levels.standard:
        levels.standard = set()
        return
    if uid is None:
        # a guest counts ``ratings.GUEST_RATING``
        if ratings.GUEST_RATING > line_of(levels.level):
            levels.standard = set()
        return
    if uid == before:
        return                  # the same account is frozen
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        levels.standard = set()  # off the loop no read can be awaited: Advanced
        return
    levels.checks += 1
    task = loop.create_task(_check(room, levels, uid, on_change, levels.game))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def seat_taken(room: Any, seat: int) -> None:
    """A person took ``seat`` mid-game: if it played a relaxed level, its team is a
    person's team now and both its bots play Advanced from here."""
    levels = getattr(room, "bot_levels", None)
    if levels is not None and seat in levels.standard:
        levels.standard = set()


def standard(room: Any) -> frozenset[int]:
    """The seats chosen for a relaxed level (server-only), whether or not a seat
    check holds them at Advanced for now."""
    levels = getattr(room, "bot_levels", None)
    return frozenset(levels.standard) if levels is not None else frozenset()
