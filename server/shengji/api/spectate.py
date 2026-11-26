"""Watching a table: every hand, one round behind.

A watcher reads a table's latest FINISHED round from the room log and plays
it back; by then every card has been played face up and the kitty turned
over, so nothing it shows can reach a player at the table. A watcher never
opens the room's socket, holds no seat and sends nothing to the table: it
reads over HTTP, and the players are not told.

Which tables. A table a stranger could already find: a ranked table, or a
casual table with Allow joiners on (the queue offers those to strangers),
with a person still connected, once one of its rounds has finished. With
none, the latest finished ranked round seen since the process started is a
rerun, so the way in always leads somewhere.

The guard. Only a round whose ``round_end`` record was written is served,
and it is checked twice: the round's records must run from its
``round_start`` to its ``round_end`` (``_read``), and the room itself must
be past that round (``_is_over``). A round in play, an abandoned one or one
replaced by a new deal has no ``round_end`` and is never served.

Limits. At most ``WATCH_CAP`` watchers per table (a watcher counts until
``WATCH_TTL`` passes without a poll), and ``LIMITER`` per address.

Who may watch. Nobody unless ``SPECTATE_ENABLED=1`` (everyone) or the
signed-in account's id is in ``SPECTATE_ACCOUNTS`` (comma-separated account
ids, set as a deployment secret): the presence line carries the watch keys
only to such a socket, and the endpoints check the session's account before
reading anything. An account let in by the list alone may also watch any
live table's last finished round, not only those a stranger could find, so
a tester has a table to watch while the flag is off for everyone else.

Privacy. The events pass the saved games' allow-list (``PUBLIC_KEYS``: no
bot reasoning, timing, seeds or chat) and each seat carries only its seat,
display name and whether it is a bot. No account id, address or room code
is in a feed; a casual table that seats joiners names its code, which the
open-table offer already gives a stranger, so Take a seat can join it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from . import accounts, ratings, saved_games

log = logging.getLogger(__name__)

ENV = "SPECTATE_ENABLED"
WATCH_CAP = 8
WATCH_TTL = 90.0
# A watcher polls a table about every 15 s while a round is in play, and a
# tap on Next table reads one more; this leaves room for both.
LIMITER = accounts.RateLimiter(limit=30, window=60.0)
# A round's records fill well under 1 MB; the read stops here regardless.
READ_CAP = 4 * 1024 * 1024
RERUN_ID = "rerun"


ACCOUNTS_ENV = "SPECTATE_ACCOUNTS"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


def allowlist() -> frozenset[int]:
    out = set()
    for part in os.environ.get(ACCOUNTS_ENV, "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def access(user_id: int | None) -> str | None:
    """How ``user_id`` may watch: "all" with the feed on for everyone,
    "listed" for an allowlisted account (any live table), else None."""
    if enabled():
        return "all"
    if user_id is not None and user_id in allowlist():
        return "listed"
    return None


@dataclass
class Finished:
    """Where one finished round is logged."""
    path: Path
    start: int
    round: int
    ranked: bool


@dataclass
class WatchState:
    """A room's watch bookkeeping. Server-only: it enters no frame and no
    log record."""
    id: str = field(default_factory=lambda: secrets.token_hex(8))
    # (round number, the log, its round_start offset) of the round in play
    started: tuple[int, Path, int] | None = None
    last: Finished | None = None
    # watcher token -> when it last read this table
    watchers: dict[str, float] = field(default_factory=dict)

    def live_watchers(self, now: float) -> int:
        for tok in [t for t, at in self.watchers.items() if now - at > WATCH_TTL]:
            del self.watchers[tok]
        return len(self.watchers)


# The latest finished ranked round, kept after its room closes.
_rerun: Finished | None = None


def _state(room: Any) -> WatchState:
    st = getattr(room, "watch", None)
    if st is None:
        st = WatchState()
        room.watch = st
    return st


def _log_path(room: Any) -> Path:
    from . import server
    return Path(room.log_dir or server.LOG_DIR) / f"{room.code}.jsonl"


# ------------------------------------------------------------- room hooks
def round_started(room: Any, offset: int | None) -> None:
    """After a ``round_start`` record: where the round in play begins. A
    record that missed the disk leaves the round unservable."""
    try:
        st = _state(room)
        game = room.game
        st.started = (game.round_no, _log_path(room), offset) if (
            game is not None and offset is not None) else None
    except Exception:               # noqa: BLE001 - never raise into a game
        log.exception("spectate round_started failed")


def round_ended(room: Any, written: bool = True) -> None:
    """After a ``round_end`` record: the round in play is the one to watch."""
    global _rerun
    try:
        st = _state(room)
        game = room.game
        if not written or game is None or st.started is None or st.started[0] != game.round_no:
            return
        n, path, offset = st.started
        st.last = Finished(path=path, start=offset, round=n, ranked=ratings.ranked(room))
        if st.last.ranked:
            _rerun = st.last
    except Exception:               # noqa: BLE001 - never raise into a game
        log.exception("spectate round_ended failed")


# ------------------------------------------------------------- the guard
def _is_over(room: Any, n: int) -> bool:
    """Whether the room has finished its round ``n``: a later round has
    started, or ``n`` is the round in play and it stands at its end."""
    game = room.game
    if game is None or room.round is None:
        return False
    if game.round_no > n:
        return True
    return (game.round_no == n and room.round.phase == "round_end"
            and game.result is not None)


def _read(f: Finished) -> list[dict] | None:
    """Round ``f.round``'s records from its ``round_start`` through its
    ``round_end``, or None unless the log holds both."""
    out: list[dict] = []
    read = 0
    try:
        with open(f.path, "rb") as fh:
            fh.seek(f.start)
            for line in fh:
                read += len(line)
                if read > READ_CAP:
                    return None
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("round") != f.round:
                    if out:
                        return None     # the round ran out without its end
                    continue
                if not out and rec.get("e") != "round_start":
                    return None
                out.append(rec)
                if rec.get("e") == "round_end":
                    return out
    except OSError:
        return None
    return None


def _players(rec: dict) -> list[dict]:
    out = []
    for p in rec.get("players") or []:
        seat = p.get("seat")
        if isinstance(seat, int) and 0 <= seat < 4:
            out.append({"seat": seat, "name": str(p.get("name") or ""),
                        "is_bot": bool(p.get("is_bot"))})
    return out


def round_doc(f: Finished) -> dict | None:
    """The finished round as a watcher sees it: every event of the
    allow-list with every card shown, or None when it is not finished."""
    records = _read(f)
    if records is None or records[-1].get("e") != "round_end":
        return None
    events = []
    for rec in records:
        if rec.get("e") not in saved_games.PUBLIC_KEYS:
            continue
        ev = saved_games.public_event(rec, 0, True, None)
        if ev["e"] == "round_start":
            ev["players"] = _players(rec)
        ev.pop("room", None)
        events.append(ev)
    start = events[0]
    names = ["", "", "", ""]
    for p in start.get("players", []):
        names[p["seat"]] = p["name"]
    banker = next((e.get("banker") for e in events if e["e"] == "trump"), start.get("banker"))
    seat = banker if isinstance(banker, int) and 0 <= banker < 4 else 0
    return {"round": f.round, "seat": seat, "players": names, "finished": True,
            "events": events}


# ------------------------------------------------------------- picking
def _rooms() -> list[Any]:
    from . import server
    return [r for r in list(server.rooms.values()) if server.rooms.get(r.code) is r]


def watchable(room: Any, wide: bool = False) -> bool:
    """A table a stranger could find (``wide``: any live table), with a
    person at it, past its first finished round."""
    st = getattr(room, "watch", None)
    game = room.game
    if st is None or st.last is None or game is None or room.round is None:
        return False
    if getattr(room, "aborted", False) or getattr(room, "closing", False):
        return False
    if not (wide or ratings.ranked(room) or room.allow_joiners):
        return False
    return any(sd is not None and not sd.is_bot and sd.connected for sd in room.seats)


def _mode(room: Any) -> str:
    return "ranked" if ratings.ranked(room) else "casual"


def _counts() -> tuple[int, int, bool]:
    """(tables anyone may watch, live tables with a finished round, rerun)."""
    rooms = _rooms()
    return (sum(1 for r in rooms if watchable(r)), sum(1 for r in rooms if watchable(r, True)),
            _rerun is not None)


def presence_key() -> tuple:
    """What every socket's watch keys are read from; empty with nobody
    able to watch, so the presence line is then exactly as without the feed."""
    if not enabled() and not allowlist():
        return ()
    try:
        return _counts()
    except Exception:               # noqa: BLE001 - the line is cosmetic
        log.exception("spectate presence failed")
        return (0, 0, False)


def presence(user_id: int | None = None) -> dict | None:
    """The presence line's watch keys for this account, or None when it may
    not watch."""
    how = access(user_id)
    if how is None:
        return None
    key = presence_key() or (0, 0, False)
    return {"watch": key[0] if how == "all" else key[1], "rerun": key[2]}


def pick(mode: str | None, skip: str | None, token: str, now: float,
         wide: bool = False) -> Any | None:
    """The table to watch: the asked mode first, then the one furthest
    into its game; never ``skip``, never one at its cap (unless this
    watcher already counts there)."""
    best = None
    for room in _rooms():
        if not watchable(room, wide) or room.watch.id == skip:
            continue
        st = room.watch
        if token not in st.watchers and st.live_watchers(now) >= WATCH_CAP:
            continue
        key = (_mode(room) == mode, room.game.round_no, st.last.round)
        if best is None or key > best[0]:
            best = (key, room)
    return best[1] if best else None


def _join_code(room: Any) -> str | None:
    """A casual table that seats joiners now: its code, for Take a seat."""
    from . import server
    if ratings.ranked(room) or not server._open_seats(room):
        return None
    return room.code


async def _serve(room: Any, token: str, after: int | None) -> dict:
    """One table's answer: its latest finished round (when newer than
    ``after``), or that its round is still in play."""
    st = room.watch
    f = st.last
    head = {"table": st.id, "watcher": token, "mode": _mode(room),
            "live_round": room.game.round_no, "code": _join_code(room), "rerun": False}
    if f is None or (after is not None and f.round <= after) or not _is_over(room, f.round):
        return {**head, "waiting": True}
    doc = await asyncio.to_thread(round_doc, f)
    # checked again after the read: the room must still be past that round
    if doc is None or not _is_over(room, f.round):
        return {**head, "waiting": True}
    return {**head, **doc, "waiting": False}


# ------------------------------------------------------------- endpoints
router = APIRouter(prefix="/api")


async def _admit(request: Request) -> bool:
    """Refuse a reader who may not watch, before anything is read; True for
    an allowlisted account (it may watch any live table)."""
    how = "all" if enabled() else None
    if how is None and allowlist():
        try:
            user = await accounts.STORE.run(accounts.STORE.session_user,
                                            request.cookies.get(accounts.COOKIE))
        except Exception:           # noqa: BLE001 - no account store reads as signed out
            user = None
        how = access(user["id"] if user else None)
    if how is None:
        raise HTTPException(status_code=404, detail="Not found.")
    if not LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests; try again in a minute.")
    return how == "listed"


def _token(w: str | None) -> str:
    if w is not None and 16 <= len(w) <= 64 and w.isalnum():
        return w
    return secrets.token_hex(16)


@router.get("/watch")
async def watch(request: Request, mode: str | None = None, skip: str | None = None,
                w: str | None = None) -> dict:
    """Pick a table and send its latest finished round; with no table, the
    rerun; with neither, 404."""
    wide = await _admit(request)
    token, now = _token(w), time.time()
    room = pick(mode if mode in ("ranked", "casual") else None, skip, token, now, wide)
    if room is not None:
        for other in _rooms():
            st = getattr(other, "watch", None)
            if st is not None and other is not room:
                st.watchers.pop(token, None)
        room.watch.watchers[token] = now
        out = await _serve(room, token, None)
        if not out["waiting"]:
            return out
    rerun = _rerun
    if rerun is not None:
        doc = await asyncio.to_thread(round_doc, rerun)
        if doc is not None:
            return {"table": RERUN_ID, "watcher": token, "mode": "ranked", "live_round": None,
                    "code": None, "rerun": True, "waiting": False, **doc}
    raise HTTPException(status_code=404, detail="Nothing to watch.")


@router.get("/watch/{table}")
async def follow(table: str, request: Request, after: int | None = None,
                 w: str | None = None) -> dict:
    """The table a watcher is at: its newer finished round, or ``waiting``
    while the round after ``after`` is in play. 404 once it cannot be
    watched (closed, emptied, Allow joiners off) or is at its cap."""
    wide = await _admit(request)
    token, now = _token(w), time.time()
    room = next((r for r in _rooms() if getattr(r, "watch", None) is not None
                 and r.watch.id == table), None)
    if room is None or not watchable(room, wide):
        raise HTTPException(status_code=404, detail="Not found.")
    st = room.watch
    if token not in st.watchers and st.live_watchers(now) >= WATCH_CAP:
        raise HTTPException(status_code=404, detail="Not found.")
    st.watchers[token] = now
    return await _serve(room, token, after)


def register_spectate(app) -> None:
    app.include_router(router)
