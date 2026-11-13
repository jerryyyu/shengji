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

Read side (``/api/me/games``). An account reads round ``n`` of a game only
through one of its own visible links whose interval holds ``n``, and sees
that round from the seat the link names. Everything else, including a round
outside every interval, answers 404, so ids and round numbers cannot be
probed. A round's events are the room log's records for that round, sliced
from the game's first ``round_start`` to the next game in the same file,
with a per-kind allow-list of keys (bot reasoning, timing, seeds and chat
never leave) and the hidden cards masked: the viewer's own hand once dealt;
the kitty and the bury to the seat that took the kitty; every other hand
only once that round's ``round_end`` exists. Before the round's ``trump``
record (the deal and declaring still running) no deck card is shown at all.
File reads run off the event loop and stop at ``READ_BYTE_CAP`` bytes per
request.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request, Response

from ..engine.cards import RANKS
from ..engine.round import HAND_SIZE, KITTY_SIZE
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
    if accounts.is_deleted(user_id):
        return
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
def abort(room: Any) -> None:
    """A start rolled back before the game began: no account keeps it. The
    delete queues behind this game's link writes on the same worker."""
    link: GameLink | None = getattr(room, "saved_game", None)
    room.saved_game = None
    if link is not None and link.stored:
        _submit("forget_game", link.id)


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


# ---------------------------------------------------------------- read side
READ_BYTE_CAP = 64 * 1024 * 1024
LIST_LIMIT_MAX = 50
# Per-IP budget for the history reads: a replay steps through rounds, so
# this is wider than the sign-in budget.
READ_LIMITER = accounts.RateLimiter(limit=120, window=60.0)
GAME_ID_RE = re.compile(r"[0-9a-f]{32}")
DEAL_CARDS = 4 * HAND_SIZE
DECK_CARDS = DEAL_CARDS + KITTY_SIZE
_COMMON_KEYS = ("t", "room", "round", "e")
# What each record kind may show. A kind not named here is never served
# (``model_search``, ``bot_timing``, ``declare_decision``, ``chat``, ...), and
# a key not named here is dropped (``decision``, ``bot_seed``, ...).
PUBLIC_KEYS: dict[str, tuple[str, ...]] = {
    "round_start": ("deck", "banker", "trump_rank", "levels", "players"),
    "declare": ("seat", "cards", "bot"),
    "trump": ("suit", "rank", "banker", "declared"),
    "bury": ("seat", "cards", "bot"),
    "play": ("seat", "cards", "bot", "attempted_cards", "engine_resolution"),
    "trick": ("winner", "points", "plays"),
    "round_end": ("attacker_points", "kitty", "kitty_points", "winner_team",
                  "level_change", "new_levels", "next_banker", "game_over",
                  "games_won", "point_scored"),
    "seat_claimed": ("seat", "name", "bot"),
}
# The fixed prefix ``Room.log_event`` writes, so a scan can find each
# record's round and kind without decoding the whole line.
_PREFIX = re.compile(rb'^\{"t": [^,]*, "room": "[^"]*", "round": (\d+), "e": "([a-z_]+)"')
_CACHE_MAX = 256
_segments: dict[tuple[str, int], tuple[int, "Segment"]] = {}
_names: dict[str, list[str]] = {}
_cache_lock = threading.Lock()


@dataclass
class Segment:
    """One game's slice of a room-code log: each round's byte span."""
    rounds: dict[int, tuple[int, int]]
    truncated: bool


def _log_root() -> Path:
    from . import server
    return Path(server.LOG_DIR)


def _log_path(game: dict) -> Path:
    return _log_root() / Path(game["log_file"]).name


def _head(line: bytes) -> tuple[int, str] | None:
    m = _PREFIX.match(line)
    if m:
        return int(m.group(1)), m.group(2).decode("ascii")
    try:
        rec = json.loads(line)
        return int(rec["round"]), str(rec["e"])
    except Exception:               # noqa: BLE001 - a torn line is skipped
        return None


def _scan(path: Path, offset: int, cap: int | None = None) -> Segment:
    """Each round's byte span from ``offset`` (the game's first
    ``round_start``) up to the next game's first record: a lobby record
    (round 0) or another round 1 ``round_start``."""
    cap = READ_BYTE_CAP if cap is None else cap
    rounds: dict[int, tuple[int, int]] = {}
    read = 0
    with open(path, "rb") as f:
        f.seek(offset)
        pos = offset
        for line in f:
            start, pos = pos, pos + len(line)
            read += len(line)
            if read > cap:
                return Segment(rounds, True)
            head = _head(line)
            if head is None:
                continue
            rnd, kind = head
            if start == offset:
                if (rnd, kind) != (1, "round_start"):
                    return Segment({}, False)
            elif rnd == 0 or (rnd == 1 and kind == "round_start"):
                break
            first = rounds.get(rnd, (start, pos))[0]
            rounds[rnd] = (first, pos)
    return Segment(rounds, False)


def _segment(game: dict) -> Segment:
    if game["log_offset"] is None:
        return Segment({}, False)
    path = _log_path(game)
    try:
        size = path.stat().st_size
    except OSError:
        return Segment({}, False)
    key = (str(path), int(game["log_offset"]))
    with _cache_lock:
        hit = _segments.get(key)
    if hit is not None and hit[0] == size:
        return hit[1]
    seg = _scan(path, key[1])
    with _cache_lock:
        if len(_segments) >= _CACHE_MAX:
            _segments.pop(next(iter(_segments)))
        _segments[key] = (size, seg)
    return seg


def _round_records(game: dict, seg: Segment, n: int) -> list[dict]:
    span = seg.rounds.get(n)
    if span is None:
        return []
    with open(_log_path(game), "rb") as f:
        f.seek(span[0])
        blob = f.read(min(span[1] - span[0], READ_BYTE_CAP))
    out = []
    for line in blob.splitlines():
        head = _head(line)
        if head is None or head[0] != n or head[1] not in PUBLIC_KEYS:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _player_names(rec: dict | None) -> list[str]:
    names = ["", "", "", ""]
    for p in (rec or {}).get("players") or []:
        seat = p.get("seat")
        if isinstance(seat, int) and 0 <= seat < 4:
            names[seat] = str(p.get("name") or "")
    return names


def _first_names(game: dict) -> list[str]:
    """Names by seat from the game's first ``round_start`` (one line read)."""
    with _cache_lock:
        cached = _names.get(game["id"])
    if cached is not None:
        return cached
    if game["log_offset"] is None:
        return ["", "", "", ""]
    try:
        with open(_log_path(game), "rb") as f:
            f.seek(int(game["log_offset"]))
            rec = json.loads(f.readline(READ_BYTE_CAP))
        if rec.get("e") != "round_start":
            return ["", "", "", ""]
    except Exception:               # noqa: BLE001 - a missing log reads as no names
        return ["", "", "", ""]
    names = _player_names(rec)
    with _cache_lock:
        if len(_names) >= _CACHE_MAX:
            _names.pop(next(iter(_names)))
        _names[game["id"]] = names
    return names


def readable_rounds(game: dict) -> dict[int, int]:
    """Round -> the seat this account reads it from, for every round inside
    one of its links' intervals (open links run to ``last_round``). Two
    seats held in one round read from the lower one."""
    last = int(game["last_round"])
    seats: dict[int, int] = {}
    for link in game["links"]:
        end = link["to_round"] if link["to_round"] is not None else last
        for n in range(max(1, link["from_round"]), min(end, last) + 1):
            seats[n] = min(seats.get(n, link["seat"]), link["seat"])
    return dict(sorted(seats.items()))


def _add_rating(summary: dict, rated: dict | None) -> None:
    """The viewer's own rating change in this game; an unrated game (unranked
    room, or no rated round for this account) carries no rating keys."""
    if not rated:
        return
    summary["rating_change"] = int(round(rated["rating_change"]))
    summary["rating_after"] = int(round(rated["rating_after"]))
    summary["rated_rounds"] = int(rated["rated_rounds"])


def _current(names: list[str], current: dict[int, str] | None) -> list[str]:
    """The logged names by seat, each seat an account held shown by that
    account's current name instead."""
    return [(current or {}).get(seat) or name for seat, name in enumerate(names)]


def _summary(game: dict, rounds: dict[int, int],
             current: dict[int, str] | None = None) -> dict:
    return {"id": game["id"], "room_code": game["room_code"],
            "started_at": game["started_at"], "ended_at": game["ended_at"],
            "seat": rounds[max(rounds)], "players": _current(_first_names(game), current),
            "rounds": list(rounds), "final_levels": game["final_levels"],
            "games_won": game["games_won"], "incomplete": bool(game["incomplete"])}


def public_event(rec: dict, seat: int, finished: bool, kitty_holder: int | None,
                 dealt: bool = True) -> dict:
    """One record as the viewer at ``seat`` may see it. ``dealt`` says the
    log shows the deal complete; until then no deck card is shown, since the
    log does not record how far the deal had gone."""
    kind = rec["e"]
    ev = {k: rec[k] for k in (*_COMMON_KEYS, *PUBLIC_KEYS[kind]) if k in rec}
    if kind == "round_start" and isinstance(ev.get("deck"), list):
        sees_kitty = finished or kitty_holder == seat
        ev["deck"] = [card if finished
                      or (dealt and i < DEAL_CARDS and i % 4 == seat)
                      or (dealt and i >= DEAL_CARDS and sees_kitty) else None
                      for i, card in enumerate(ev["deck"])]
    elif kind == "bury" and not finished and rec.get("seat") != seat:
        ev["cards"] = None
    return ev


def filter_round(records: list[dict], seat: int) -> tuple[bool, list[dict]]:
    """(finished, the round's events as the viewer at ``seat`` may see them)."""
    finished = any(r.get("e") == "round_end" for r in records)
    trump = next((r for r in records if r.get("e") == "trump"), None)
    bury = next((r for r in records if r.get("e") == "bury"), None)
    # The seat that picked up the kitty: the banker once trump is settled.
    holder = bury.get("seat") if bury else (trump.get("banker") if trump else None)
    # ``trump`` is logged when declaring closes, after the last card is dealt.
    dealt = finished or trump is not None
    return finished, [public_event(r, seat, finished, holder, dealt) for r in records
                      if r.get("e") in PUBLIC_KEYS]


def _result(rec: dict) -> dict:
    return {k: rec[k] for k in PUBLIC_KEYS["round_end"] if k in rec}


def _level_and_banker(records: list[dict]) -> dict:
    """The rank the round was played at and its banker seat. A first round
    names its banker only when trump is fixed, so the trump record wins."""
    out: dict = {}
    for kind in ("round_start", "trump"):
        rec = next((r for r in records if r["e"] == kind), None)
        if rec is None:
            continue
        rank = rec.get("trump_rank", rec.get("rank"))
        if isinstance(rank, str):
            out["level"] = rank
        if isinstance(rec.get("banker"), int):
            out["banker"] = rec["banker"]
    return out


# The blocking bodies of the endpoints; each runs on a worker thread.
def _list(user_id: int, before: tuple[int, str] | None, limit: int) -> dict:
    games = accounts.STORE.list_games(user_id, before=before, limit=limit + 1)
    more = len(games) > limit
    current = accounts.STORE.current_seat_names([g["id"] for g in games[:limit]], 1)
    out = []
    for game in games[:limit]:
        rounds = readable_rounds(game)
        if rounds:
            out.append(_summary(game, rounds, current.get(game["id"])))
    rated = accounts.STORE.game_ratings(user_id, [g["id"] for g in out])
    for summary in out:
        _add_rating(summary, rated.get(summary["id"]))
    return {"games": out,
            "next_before": accounts.Store.game_cursor(games[limit - 1]) if more else None}


def _visible(user_id: int, game_id: str) -> tuple[dict, dict[int, int]] | None:
    if not GAME_ID_RE.fullmatch(game_id):
        return None
    game = accounts.STORE.user_game(user_id, game_id)
    if game is None:
        return None
    rounds = readable_rounds(game)
    return (game, rounds) if rounds else None


def _detail(user_id: int, game_id: str) -> dict | None:
    found = _visible(user_id, game_id)
    if found is None:
        return None
    game, rounds = found
    seg = _segment(game)
    out = _summary(game, rounds,
                   accounts.STORE.current_seat_names([game["id"]], 1).get(game["id"]))
    _add_rating(out, accounts.STORE.game_ratings(user_id, [game["id"]]).get(game["id"]))
    deltas = accounts.STORE.game_round_ratings(user_id, game["id"])
    results = []
    for n, seat in rounds.items():
        if n not in seg.rounds:
            out["incomplete"] = True
            continue
        records = _round_records(game, seg, n)
        end = next((r for r in records if r["e"] == "round_end"), None)
        if end is not None:
            row = {"round": n, "seat": seat, "result": _result(end)}
            row.update(_level_and_banker(records))
            if n in deltas:
                row["rating_delta"] = int(round(deltas[n]))
            results.append(row)
    if seg.truncated:
        out["incomplete"] = True
    out["round_results"] = results
    return out


def resume_point(user_id: int, game_id: str) -> dict | None:
    """Where a new table continuing one of this account's saved games
    starts: the account's seat (as the game list shows it), and both teams'
    levels and the next banker from the game's latest logged ``round_end``.
    None when the game is not this account's to read, when the summary has
    no levels (a game no round of which finished), when the log no longer
    holds a finished round, or when the latest state cannot be verified: a
    game whose log missed a record (``incomplete``) may lack its latest
    ``round_end``, and an older one would silently roll the game back, so
    the latest logged round end must also agree with the stored summary."""
    found = _visible(user_id, game_id)
    if found is None:
        return None
    game, rounds = found
    stored = teams_levels(game["final_levels"])
    if stored is None or game.get("incomplete"):
        return None
    seg = _segment(game)
    for n in sorted(seg.rounds, reverse=True):
        end = next((r for r in _round_records(game, seg, n) if r["e"] == "round_end"), None)
        if end is None:
            continue
        levels = teams_levels(end.get("new_levels"))
        banker = end.get("next_banker")
        if levels is None or not isinstance(banker, int) or not 0 <= banker < 4:
            return None
        if levels != stored or end.get("games_won") != game.get("games_won"):
            return None
        return {"seat": rounds[max(rounds)], "levels": levels, "banker": banker}
    return None


def teams_levels(value: Any) -> list[str] | None:
    """``[team 0, team 1]`` ranks, or None unless both are known ranks."""
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, str) and v in RANKS for v in value)):
        return list(value)
    return None


def _round(user_id: int, game_id: str, n: int) -> dict | None:
    found = _visible(user_id, game_id)
    if found is None:
        return None
    game, rounds = found
    if n not in rounds:
        return None
    records = _round_records(game, _segment(game), n)
    if not records:
        return None
    seat = rounds[n]
    start = next((r for r in records if r["e"] == "round_start"), None)
    finished, events = filter_round(records, seat)
    current = accounts.STORE.current_seat_names([game["id"]], n if start else 1)
    return {"game_id": game["id"], "round": n, "seat": seat,
            "players": _current(_player_names(start) if start else _first_names(game),
                                current.get(game["id"])),
            "finished": finished, "events": events}


router = APIRouter(prefix="/api")


async def _signed_in(request: Request) -> dict:
    if not READ_LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests; try again in a minute.")
    user = await accounts.STORE.run(accounts.STORE.session_user,
                                    request.cookies.get(accounts.COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found.")


@router.get("/me/games")
async def list_games(request: Request, before: str | None = None,
                     limit: int = LIST_LIMIT_MAX) -> dict:
    """``before`` is the previous page's ``next_before``: an opaque cursor."""
    user = await _signed_in(request)
    limit = max(1, min(LIST_LIMIT_MAX, limit))
    try:
        cursor = None if before is None else accounts.Store.parse_game_cursor(before)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad cursor.") from None
    return await accounts.STORE.run(_list, user["id"], cursor, limit)


@router.get("/me/games/{game_id}")
async def game_detail(game_id: str, request: Request) -> dict:
    user = await _signed_in(request)
    out = await accounts.STORE.run(_detail, user["id"], game_id)
    if out is None:
        raise _not_found()
    return out


@router.get("/me/games/{game_id}/rounds/{n}")
async def game_round(game_id: str, n: str, request: Request) -> dict:
    user = await _signed_in(request)
    if not n.isdigit() or len(n) > 6:
        raise _not_found()
    out = await accounts.STORE.run(_round, user["id"], game_id, int(n))
    if out is None:
        raise _not_found()
    return out


@router.delete("/me/games/{game_id}", status_code=204)
async def hide_game(game_id: str, request: Request) -> Response:
    """Hide a game from this account; other players' links are unchanged."""
    user = await _signed_in(request)
    if not GAME_ID_RE.fullmatch(game_id):
        raise _not_found()
    if not await accounts.STORE.run(accounts.STORE.hide_game, user["id"], game_id):
        raise _not_found()
    return Response(status_code=204)


def register_saved_games(app) -> None:
    app.include_router(router)
