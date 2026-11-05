"""Saved games: link signed-in seats to the games they play.

The room log stays the source of truth and never carries an account id; the
accounts database holds only which account sat at which seat for which
rounds, plus a small summary (``accounts.SCHEMA`` version 3).

Link side. ``start`` runs when a table starts, ``seat_changed`` when a
seat's account changes mid-game, ``round_started``/``round_ended`` at the
round boundaries, and ``log_failed`` when a room record did not reach disk.
Each hook only updates the room's in-memory ``GameLink`` and queues a write
on one worker thread, so the writes of a game reach the database in the
order the game made them and nothing here waits on the disk. A hook never
raises into a game: any failure, in the hook or in the queued write,
increments ``ACTIVITY.account_link_failures`` and play goes on.

What is linked: only ordinary rooms whose log lives in the training log root
(rooms with an experimental policy or a human-evaluation context write
elsewhere and are not linked); only seats signed in to an account; and a
seat that signs in mid-game from the round it signs in on (the next round
when the current one is already over). A game no seat ever signed in to
never touches the database.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import accounts

log = logging.getLogger(__name__)

# One worker keeps each game's writes in order (create before close, round
# start before round end).
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saved-games")
# Expired games are swept at most this often, on the link worker.
PURGE_EVERY = 86400.0
_purge_lock = threading.Lock()
_last_purge = 0.0


@dataclass
class GameLink:
    """Server-only state of one linked-or-linkable game; it enters no state
    frame and no log record."""
    id: str
    room_code: str
    log_file: str
    log_offset: int | None
    started_at: int
    last_round: int = 1
    incomplete: bool = False
    # A games row has been queued (some seat linked).
    stored: bool = False
    incomplete_sent: bool = False
    # seat -> account whose link is open at that seat
    open: dict[int, int] = field(default_factory=dict)
    # the latest round_end summary, replayed into a row created after it
    last_result: tuple[int, list, list] | None = None

    def header(self) -> dict:
        return {"id": self.id, "room_code": self.room_code, "log_file": self.log_file,
                "log_offset": self.log_offset, "started_at": self.started_at,
                "last_round": self.last_round, "incomplete": self.incomplete}


def new_game_id() -> str:
    """A random 16-byte id, hex encoded."""
    return secrets.token_hex(16)


def _count_failure(exc: BaseException | None) -> None:
    from . import server            # the counter lives with the room counters
    server.ACTIVITY.account_link_failed()
    log.warning("saved-game link write failed (%s); gameplay continues",
                type(exc).__name__ if exc is not None else "cancelled")


def _done(fut: "asyncio.Future[Any]") -> None:
    if fut.cancelled():
        _count_failure(None)
    elif fut.exception() is not None:
        _count_failure(fut.exception())


def _submit(method: str, *args: Any) -> None:
    """Queue ``accounts.STORE.<method>(*args)`` on the link worker."""
    bound: Callable[..., Any] = getattr(accounts.STORE, method)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:                # called off the loop (scripts, unit tests)
        try:
            bound(*args)
        except Exception as exc:    # noqa: BLE001 - never raise into a game
            _count_failure(exc)
        return
    loop.run_in_executor(_EXECUTOR, bound, *args).add_done_callback(_done)


def flush(timeout: float = 10.0) -> None:
    """Block until every write queued so far has run (tests, shutdown)."""
    _EXECUTOR.submit(lambda: None).result(timeout=timeout)


def _guarded(fn: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:    # noqa: BLE001 - never raise into a game
            _count_failure(exc)
    return wrapper


def eligible(room: Any, training_root: Path) -> bool:
    """Ordinary rooms only: no experimental policy, no human-evaluation
    context, and a log in the training log root the read side reads."""
    if room.experimental_policy is not None or room.evaluation is not None:
        return False
    if room.log_dir is None:
        return False
    return Path(room.log_dir).resolve() == Path(training_root).resolve()


def _maybe_purge() -> None:
    global _last_purge
    now = time.time()
    with _purge_lock:
        if now - _last_purge < PURGE_EVERY:
            return
        _last_purge = now
    _submit("purge_games")


def _open(room: Any, link: GameLink, seat: int, user_id: int, from_round: int) -> None:
    first = not link.stored
    link.open[seat] = user_id
    link.stored = True
    _submit("link_seat", link.header(), user_id, seat, from_round)
    if first:
        if link.last_result is not None:
            _submit("record_round_end", link.id, *link.last_result)
        if link.incomplete:
            link.incomplete_sent = True
        _maybe_purge()


def _boundary(room: Any) -> tuple[int, int]:
    """(round a closing link ends at, round an opening link starts at)."""
    game = room.game
    current = game.round_no if game is not None else 1
    finished = room.round is not None and room.round.phase == "round_end"
    return current, current + 1 if finished else current


@_guarded
def start(room: Any, round_start_offset: int | None, training_root: Path) -> None:
    """At ``start_game``, after round 1's ``round_start`` was logged at
    ``round_start_offset`` (None when that write failed)."""
    room.saved_game = None
    if not eligible(room, training_root):
        return
    link = GameLink(id=new_game_id(), room_code=room.code, log_file=f"{room.code}.jsonl",
                    log_offset=round_start_offset, started_at=int(time.time()),
                    last_round=room.game.round_no if room.game is not None else 1,
                    incomplete=round_start_offset is None)
    room.saved_game = link
    for seat, occupant in enumerate(room.seats):
        if occupant.user_id is not None and not occupant.is_bot:
            _open(room, link, seat, occupant.user_id, link.last_round)


@_guarded
def seat_changed(room: Any, seat: int) -> None:
    """After a seat's account changed (reclaim, bot-seat claim, sign-in,
    sign-out): close the old account's link and open the new one's."""
    link: GameLink | None = getattr(room, "saved_game", None)
    if link is None:
        return
    occupant = room.seats[seat]
    new = occupant.user_id if not occupant.is_bot else None
    old = link.open.get(seat)
    if old == new:
        return
    closing_round, opening_round = _boundary(room)
    if old is not None:
        del link.open[seat]
        _submit("close_link", link.id, old, seat, closing_round)
    if new is not None:
        _open(room, link, seat, new, opening_round)


@_guarded
def round_started(room: Any) -> None:
    link: GameLink | None = getattr(room, "saved_game", None)
    if link is None or room.game is None:
        return
    link.last_round = max(link.last_round, room.game.round_no)
    if link.stored:
        _submit("record_round_start", link.id, link.last_round)


@_guarded
def round_ended(room: Any, result: Any) -> None:
    link: GameLink | None = getattr(room, "saved_game", None)
    if link is None or room.game is None:
        return
    link.last_result = (room.game.round_no, list(result.new_levels), list(result.games_won))
    if link.stored:
        _submit("record_round_end", link.id, *link.last_result)


@_guarded
def log_failed(room: Any) -> None:
    """A record of this game did not reach disk: its replay is incomplete."""
    link: GameLink | None = getattr(room, "saved_game", None)
    if link is None:
        return
    link.incomplete = True
    if link.stored and not link.incomplete_sent:
        link.incomplete_sent = True
        _submit("mark_incomplete", link.id)
