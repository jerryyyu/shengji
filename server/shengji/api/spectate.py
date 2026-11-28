"""Watching a table: every hand, one round behind.

A watcher reads a table's latest FINISHED round from the room log and plays
it back; by then every card has been played face up and the kitty turned
over, so nothing it shows can reach a player at the table. A watcher never
opens the room's socket, holds no seat and sends nothing to the table: it
reads over HTTP. The players are told how many watch and, in one toast per
``ANNOUNCE_GAP``, who started watching (``players_field``): a watcher's
account is read from its session as it starts watching a table and held
server-side by its token; the players get its name only when the
leaderboard lists it (``ratings.listed_ids``), and never an id.

Which tables. A table a stranger could already find: a ranked table, or a
casual table with Allow joiners on (the queue offers those to strangers),
with a person still connected, once one of its rounds has finished. With
none, a rerun: the newest whole round among the last few finished ranked
rounds, so the way in always leads somewhere.

Reruns survive a restart. Where those rounds sit in their logs is written
to an index beside the logs (``_index_path``; on the Fly volume,
``/data/spectate/replays.json``) at each ranked round's end, replaced
atomically, and read back on first use; an entry whose log no longer holds
the whole round is dropped then. The index holds log paths, byte offsets,
round numbers and account ids, never a name: names are read from the log
and masked by the leaderboard rule each time a rerun is served.

The guard. Only a round whose ``round_end`` record was written is served,
and it is checked twice: the round's records must run from its
``round_start`` to its ``round_end`` (``_read``), and the room itself must
be past that round (``_is_over``). A round in play, an abandoned one or one
replaced by a new deal has no ``round_end`` and is never served.

Whole rounds only. A round is served only when its records are the whole
round as the engine plays one (``complete_sequence``); one with a lost
record gives way to the table's previous finished round.

Limits. At most ``WATCH_CAP`` watchers per table (a watcher counts until
``WATCH_TTL`` passes without a poll), and ``LIMITER`` per address. The
presence line counts only tables with a free place, so its link never
promises a live table the feed cannot give. A finished round is read and
serialised once (``_doc``), not once per watcher.

Who may watch. Nobody unless ``SPECTATE_ENABLED=1`` (everyone) or the
signed-in account's id is in ``SPECTATE_ACCOUNTS`` (comma-separated account
ids, set as a deployment secret): the presence line carries the watch keys
only to such a socket, and the endpoints check the session's account before
reading anything. An account let in by the list alone may also watch any
live table's last finished round, not only those a stranger could find, so
a tester has a table to watch while the flag is off for everyone else.

Privacy. A rerun (always a ranked round) names a player only if the
leaderboard shows them (``ratings.listed_ids``); everyone else is "Player N"
and bots keep their names; a late joiner's claim is named only by its own
account (``_keeper``).
The events pass the saved games' allow-list (``PUBLIC_KEYS``: no
bot reasoning, timing, seeds or chat) and each seat carries only its seat,
display name, whether it is a bot and its companion look, masked as the
name is (``_with_looks``). No account id, address or room code
is in a feed; a casual table that seats joiners names its code, which the
open-table offer already gives a stranger, so Take a seat can join it.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request, Response

from ..engine.round import HAND_SIZE
from . import accounts, ratings, saved_games

log = logging.getLogger(__name__)

ENV = "SPECTATE_ENABLED"
WATCH_CAP = 50
WATCH_TTL = 90.0
# A watcher polls a table about every 15 s while a round is in play, and a
# tap on Next table reads one more; this leaves room for both.
LIMITER = accounts.RateLimiter(limit=30, window=60.0)
# A round's records fill well under 1 MB; the read stops here regardless.
READ_CAP = 4 * 1024 * 1024
RERUN_ID = "rerun"
KEEP_ROUNDS = 3
INDEX_SCHEMA = 1
# The index holds KEEP_ROUNDS small entries; a larger file is not ours.
INDEX_CAP = 256 * 1024
# Built round documents kept: a table's last few rounds, the reruns, and a
# rerun's masks while the leaderboard changes under it.
DOC_CACHE = 64
# The players hear "X is watching" at most once per this many seconds per
# table; watchers who arrive in between are told together.
ANNOUNCE_GAP = 30.0


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
    # the account at each seat when the round began (None: a guest or a
    # bot), so a replay can name the players the leaderboard shows.
    # Server-only: never in a feed.
    start_accounts: tuple = (None, None, None, None)
    # the look each seat showed when the round began (None: a bot, or a
    # seat its person left), served masked as the seat's name is
    start_looks: tuple = (None, None, None, None)
    # each ``seat_claimed`` record's account, by the record's byte offset in
    # the log (None: a guest or a bot), so a claim names its own claimer
    claims: dict = field(default_factory=dict)
    # whether the log holds the whole round, once read (None: not read yet).
    # A table is offered only for a round known whole (``servable``).
    whole: bool | None = field(default=None, compare=False)


@dataclass
class WatchState:
    """A room's watch bookkeeping. Server-only: it enters no frame and no
    log record."""
    id: str = field(default_factory=lambda: secrets.token_hex(8))
    # (round number, the log, its round_start offset) of the round in play
    started: tuple[int, Path, int] | None = None
    last: Finished | None = None
    # the latest finished rounds, newest last: a round whose log turns out
    # incomplete is skipped for the one before it
    recent: collections.deque = field(default_factory=lambda: collections.deque(maxlen=KEEP_ROUNDS))
    # the round in play's seat claims: log offset -> the claimer's account
    claims: dict = field(default_factory=dict)
    # watcher token -> when it last read this table
    watchers: dict[str, float] = field(default_factory=dict)
    # watcher token -> (its account id, its name, its look), read from the
    # session as it starts watching here; all None for a guest
    who: dict[str, tuple] = field(default_factory=dict)
    # watcher token -> its name as the players may read it, once told: the
    # name when the leaderboard listed the account then, else None
    shown: dict[str, str | None] = field(default_factory=dict)
    # tokens that started watching since the players were last told, oldest first
    arrivals: list[str] = field(default_factory=list)
    # the players' latest "is watching" toast: its number and who it names
    told: int = 0
    joined: list = field(default_factory=list)
    told_at: float = float("-inf")
    # the announcement waiting for its turn (``ANNOUNCE_GAP``), if any
    announcing: Any = None

    def drop(self, token: str) -> None:
        self.watchers.pop(token, None)
        self.who.pop(token, None)
        self.shown.pop(token, None)

    def live_watchers(self, now: float) -> int:
        for tok in [t for t, at in self.watchers.items() if now - at > WATCH_TTL]:
            self.drop(tok)
            lease = _leases.get(tok)
            if lease is not None and lease.table == self.id:
                del _leases[tok]
        return len(self.watchers)


@dataclass
class Lease:
    """Where one watcher token counts, server-side only. ``epoch`` is the
    highest Watch session (the client's count of the times it opened the
    watch screen) admitted for the token; ``table`` the table it counts at
    (None: at none); ``left`` whether that session has left."""
    table: str | None
    epoch: int
    at: float
    left: bool = False
    # the session's read that admitted it (its ``q``, counted up from 1 by
    # the client within a session): an earlier read of the session that
    # finishes later counts nowhere
    seq: int = 0


# watcher token -> its Lease: a token counts at one table at most, and a
# read or leave from an older Watch session than one admitted changes nothing.
# Each admission is its own Lease object: a handler that awaited after
# admitting acts on the token only while that object still holds it.
_leases: dict[str, Lease] = {}
_leases_swept = 0.0
# The leaves of tokens never admitted here (the leave outran its session's
# own first read): token -> (that session, when), oldest first, at most
# EARLY_LEAVES of them, so a leave needs no admission and costs bounded state.
EARLY_LEAVES = 1024
_early: collections.OrderedDict = collections.OrderedDict()


def _sweep(now: float) -> None:
    """Forget leases nothing has renewed for a lease's length (a table that
    closed never expires its own), and early leaves as old, at most once
    per lease length."""
    global _leases_swept
    if now - _leases_swept < WATCH_TTL:
        return
    _leases_swept = now
    for tok in [t for t, lease in _leases.items() if now - lease.at > WATCH_TTL]:
        del _leases[tok]
    for tok in [t for t, (_, at) in _early.items() if now - at > WATCH_TTL]:
        del _early[tok]


def _room_by_id(table: str | None) -> Any | None:
    if table is None:
        return None
    return next((r for r in _rooms() if getattr(r, "watch", None) is not None
                 and r.watch.id == table), None)


def admissible(token: str, epoch: int, table: str, follow: bool, seq: int = 0) -> bool:
    """Whether read ``seq`` of Watch session ``epoch`` may count ``token``
    at ``table``: never from a session older than one admitted, nor from a
    session that has left, nor a read of the session sent before the one
    that admitted it (a pick overtaken by a later Next); and a follow never
    moves the token, so one of a table the token has since moved from (Next,
    its answer still on its way) is answered without counting there."""
    early = _early.get(token)
    if early is not None and epoch <= early[0]:
        return False
    lease = _leases.get(token)
    if lease is None or epoch > lease.epoch:
        return True
    if epoch < lease.epoch or lease.left or seq < lease.seq:
        return False
    return not follow or lease.table in (None, table)


def admit(room: Any, token: str, epoch: int, now: float, seq: int = 0) -> Lease:
    """Count ``token`` at this table, and at no other; the admission's own
    Lease, for ``holds``."""
    for other in _rooms():
        st = getattr(other, "watch", None)
        if st is not None and other is not room:
            st.drop(token)
    room.watch.watchers[token] = now
    lease = _leases[token] = Lease(room.watch.id, epoch, now, seq=seq)
    _early.pop(token, None)
    _sweep(now)
    return lease


def holds(token: str, lease: Lease | None) -> bool:
    """Whether this admission still holds the token: no later read, leave or
    expiry has replaced it while its handler awaited."""
    return lease is not None and _leases.get(token) is lease


def unadmit(room: Any, token: str, lease: Lease | None) -> None:
    """The table turned out to have no round for this read: the token holds
    no place there, and its session may still be admitted elsewhere. Only
    while this admission still holds the token: a later one keeps its place."""
    if lease is None or not holds(token, lease):
        return
    room.watch.drop(token)
    lease.table = None


def release(token: str, epoch: int, now: float) -> bool:
    """Watch session ``epoch`` left: the token stops counting wherever it
    counts, unless a newer session has been admitted since, and a read of
    that session arriving after the leave (its answer was on its way) counts
    nowhere. False when a newer session holds the token."""
    lease = _leases.get(token)
    _sweep(now)
    if lease is None:
        # never admitted here (or forgotten): remembered, boundedly, so the
        # session's read arriving after this leave counts nowhere
        if epoch >= _early.get(token, (-1, 0.0))[0]:
            _early[token] = (epoch, now)
            _early.move_to_end(token)
            while len(_early) > EARLY_LEAVES:
                _early.popitem(last=False)
        return True
    if epoch < lease.epoch:
        return False
    room = _room_by_id(lease.table)
    if room is not None:
        room.watch.drop(token)
    _leases[token] = Lease(None, epoch, now, left=True)
    return True


# The latest finished ranked rounds (newest last), kept after their rooms
# close: a rerun plays the newest whose log holds the whole round, and one
# that does not is dropped, so an older whole round still plays.
_reruns: collections.deque = collections.deque(maxlen=KEEP_ROUNDS)
# Whether ``_reruns`` has been read back from the index since the process started.
_loaded = False


def _index_path() -> Path:
    """The rerun index, beside the logs it points into, so both live on the
    same volume (``/data/logs`` -> ``/data/spectate/replays.json``)."""
    from . import server
    return Path(server.LOG_DIR).parent / "spectate" / "replays.json"


def _entry(f: Finished) -> dict:
    return {"path": str(f.path), "start": f.start, "round": f.round, "ranked": f.ranked,
            "start_accounts": list(f.start_accounts), "start_looks": list(f.start_looks),
            "claims": sorted([at, uid] for at, uid in f.claims.items())}


def _account(v: Any) -> bool:
    return v is None or (isinstance(v, int) and not isinstance(v, bool))


def _from_entry(e: Any) -> Finished | None:
    """An index entry back as a ``Finished``, or None when any field is off."""
    if not isinstance(e, dict):
        return None
    path, start, n, accts, claims = (e.get("path"), e.get("start"), e.get("round"),
                                     e.get("start_accounts"), e.get("claims"))
    if not isinstance(path, str) or not path or e.get("ranked") is not True:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (start, n)):
        return None
    if not isinstance(accts, list) or len(accts) != 4 or not all(_account(v) for v in accts):
        return None
    if not isinstance(claims, list) or not all(
            isinstance(c, list) and len(c) == 2 and isinstance(c[0], int) and _account(c[1])
            for c in claims):
        return None
    looks = e.get("start_looks")
    if not (isinstance(looks, list) and len(looks) == 4
            and all(v is None or accounts.parse_look(v) is not None for v in looks)):
        looks = [None] * 4          # an entry from before looks were kept: no figures
    return Finished(path=Path(path), start=start, round=n, ranked=True,
                    start_accounts=tuple(accts), claims={at: uid for at, uid in claims},
                    start_looks=tuple(looks))


def _starts_here(f: Finished) -> bool:
    """Whether the log record at ``f.start`` is this round's ranked
    ``round_start``."""
    with open(f.path, "rb") as fh:
        fh.seek(f.start)
        rec = json.loads(fh.readline(READ_CAP))
    return (isinstance(rec, dict) and rec.get("e") == "round_start"
            and rec.get("round") == f.round and rec.get("ranked") is True)


def _restore(e: Any) -> Finished | None:
    """One index entry back as a rerun, or None when the entry, its offset
    or its log's round is not whole; a damaged entry never touches another."""
    try:
        f = _from_entry(e)
        if f is None or not _starts_here(f):
            return None
        records = _read(f)
        if records is None or not complete_sequence(records):
            return None
        f.whole = True
        return f
    except Exception:               # noqa: BLE001 - one bad replay drops only itself
        return None


def save() -> None:
    """Write ``_reruns`` to the index: a temporary file, fsynced, renamed
    over the old one, so a crash leaves the old index or the new, never part."""
    try:
        path = _index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"schema": INDEX_SCHEMA,
                           "rounds": [_entry(f) for f in _reruns]}).encode("utf-8")
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass                    # a directory that cannot be fsynced still has the rename
    except Exception:               # noqa: BLE001 - never raise into a game
        log.exception("spectate index write failed")


def load() -> None:
    """Read the index back into ``_reruns``, keeping only ranked rounds
    whose log still holds the whole round. A missing, unreadable, corrupt
    or other-schema index starts empty."""
    global _loaded
    rounds: list = []
    try:
        path = _index_path()
        if path.stat().st_size <= INDEX_CAP:
            data = json.loads(path.read_bytes())
            if isinstance(data, dict) and data.get("schema") == INDEX_SCHEMA \
                    and isinstance(data.get("rounds"), list):
                rounds = data["rounds"][-KEEP_ROUNDS:]
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.warning("spectate index unreadable; starting with no reruns")
    except Exception:               # noqa: BLE001 - a bad index never stops the feed
        log.exception("spectate index read failed")
    kept = [f for f in map(_restore, rounds) if f is not None]
    _reruns.clear()
    _reruns.extend(kept)
    _loaded = True
    if len(kept) != len(rounds):
        save()


def _ensure_loaded() -> None:
    if not _loaded:
        load()


def _state(room: Any) -> WatchState:
    st = getattr(room, "watch", None)
    if st is None:
        st = WatchState()
        room.watch = st
    return st


def _log_path(room: Any) -> Path:
    from . import server
    return Path(room.log_dir or server.LOG_DIR) / f"{room.code}.jsonl"


def _looks(room: Any) -> tuple:
    """The look each seat shows now (``server.seat_look``), None for a bot."""
    from . import server
    out = []
    for i in range(4):
        sd = room.seats[i] if i < len(room.seats) else None
        out.append(server.seat_look(sd) if sd is not None else None)
    return tuple(out)


def _accounts(room: Any) -> tuple:
    """The signed-in account at each seat, None for a guest or a bot."""
    out = []
    for i in range(4):
        sd = room.seats[i] if i < len(room.seats) else None
        uid = getattr(sd, "user_id", None) if sd is not None and not sd.is_bot else None
        out.append(uid if isinstance(uid, int) else None)
    return tuple(out)


# ------------------------------------------------------------- room hooks
def round_started(room: Any, offset: int | None) -> None:
    """After a ``round_start`` record: where the round in play begins. A
    record that missed the disk leaves the round unservable."""
    try:
        st = _state(room)
        game = room.game
        st.started = (game.round_no, _log_path(room), offset, _accounts(room), _looks(room)) if (
            game is not None and offset is not None) else None
        st.claims = {}
    except Exception:               # noqa: BLE001 - never raise into a game
        log.exception("spectate round_started failed")


def claimed(room: Any, offset: int | None, user_id: Any) -> None:
    """After a ``seat_claimed`` record: whose account made that claim (None
    for a guest or a bot), held server-side by the record's offset."""
    try:
        if offset is not None:
            _state(room).claims[offset] = user_id if isinstance(user_id, int) else None
    except Exception:               # noqa: BLE001 - never raise into a game
        log.exception("spectate claimed failed")


def round_ended(room: Any, written: bool = True) -> None:
    """After a ``round_end`` record: the round in play is the one to watch."""
    try:
        st = _state(room)
        game = room.game
        if not written or game is None or st.started is None or st.started[0] != game.round_no:
            return
        n, path, offset, began, looks = st.started
        st.last = Finished(path=path, start=offset, round=n, ranked=ratings.ranked(room),
                           start_accounts=began, claims=dict(st.claims), start_looks=looks)
        st.recent.append(st.last)
        if st.last.ranked or enabled() or allowlist():
            # read once now, so the lobby count and the feed agree from the start
            _remember(_doc_key(st.last, None), _build(st.last, None))
        if st.last.ranked and st.last.whole is True:
            # only a whole round is kept to replay, so a broken one never
            # advertises a rerun nor pushes a good one out
            _ensure_loaded()
            _reruns.append(st.last)
            save()
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
            at = f.start
            for line in fh:
                here, at = at, at + len(line)
                read += len(line)
                if read > READ_CAP:
                    return None
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("round") != f.round:
                    if out:
                        return None     # the round ran out without its end
                    continue
                if not out and rec.get("e") != "round_start":
                    return None
                rec["_at"] = here           # read-side only: no event carries it
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


def _with_looks(players: list[dict], f: Finished, listed: set[int] | None) -> list[dict]:
    """Each seat's look as the round began, masked as its name is: a bot has
    none (nor a seat its person had left), and in a rerun a person the
    leaderboard does not list shows the default look, so a look never tells
    who a "Player N" is."""
    for p in players:
        seat = p["seat"]
        look = None if p["is_bot"] else f.start_looks[seat]
        if look is not None and listed is not None and f.start_accounts[seat] not in listed:
            look = accounts.DEFAULT_LOOK
        p["look"] = look
    return players


def _seat_name(seat: Any) -> str | None:
    return f"Player {seat + 1}" if isinstance(seat, int) and 0 <= seat < 4 else None


def _keeper(ev: dict, rec: dict, f: Finished, listed: set[int]) -> Callable[[dict], bool]:
    """Whether a named entry of this event keeps its name: a bot's always; a
    person's only when that entry's own account is on the leaderboard, read
    from the seat at the round's start for ``round_start`` and from the
    claim's own account for ``seat_claimed``. Any other name is masked."""
    def bot(entry: dict) -> bool:
        return entry.get("is_bot") is True or entry.get("bot") is True

    if ev.get("e") == "round_start":
        def keep(entry: dict) -> bool:
            seat = entry.get("seat")
            uid = f.start_accounts[seat] if isinstance(seat, int) and 0 <= seat < 4 else None
            return bot(entry) or (uid is not None and uid in listed)
        return keep
    if ev.get("e") == "seat_claimed":
        uid = f.claims.get(rec.get("_at"))
        return lambda entry: bot(entry) or (uid is not None and uid in listed)
    return bot


def _redact(value: Any, keep: Callable[[dict], bool]) -> Any:
    """Every ``name`` in ``value``, at any depth: kept where ``keep`` says,
    else the entry's seat as "Player N" (dropped with no seat)."""
    if isinstance(value, list):
        return [_redact(v, keep) for v in value]
    if not isinstance(value, dict):
        return value
    out = {k: _redact(v, keep) for k, v in value.items() if k != "name"}
    if "name" in value:
        if keep(value):
            out["name"] = value["name"]
        elif (named := _seat_name(value.get("seat"))) is not None:
            out["name"] = named
    return out


def _listed() -> set[int]:
    """The accounts the leaderboard shows; none when the store cannot be read."""
    try:
        return ratings.listed_ids(accounts.STORE)
    except Exception:               # noqa: BLE001 - unreadable: name nobody
        log.exception("spectate leaderboard read failed")
        return set()


def _cards(v: Any) -> list[str] | None:
    return list(v) if isinstance(v, list) and all(isinstance(c, str) for c in v) else None


def complete_sequence(records: list[dict]) -> bool:
    """Whether the records are a whole round as the engine plays one: one
    deal, the banker's bury of eight, then tricks of four plays in turn
    order, each led by the previous trick's winner (the banker first), each
    play as many cards as the lead and from that seat's own cards, every
    trick closed by its ``trick`` record, until each seat has played its
    ``HAND_SIZE`` cards, then ``round_end``. A lost record anywhere fails it."""
    if not records or records[0].get("e") != "round_start" or records[-1].get("e") != "round_end":
        return False
    deck = _cards(records[0].get("deck"))
    if deck is None or len(deck) < 4 * HAND_SIZE + 8:
        return False
    trump = [r for r in records if r.get("e") == "trump"]
    buries = [r for r in records if r.get("e") == "bury"]
    if len(trump) != 1 or len(buries) != 1:
        return False
    banker = trump[0].get("banker")
    buried = _cards(buries[0].get("cards"))
    if not isinstance(banker, int) or not 0 <= banker < 4 or buries[0].get("seat") != banker \
            or buried is None or len(buried) != 8:
        return False
    held = [collections.Counter(deck[s:4 * HAND_SIZE:4]) for s in range(4)]
    held[banker].update(deck[4 * HAND_SIZE:4 * HAND_SIZE + 8])
    held[banker].subtract(buried)
    if any(v < 0 for v in held[banker].values()):
        return False
    leader, plays = banker, []
    played = [0, 0, 0, 0]
    for rec in records[1:-1]:
        kind = rec.get("e")
        if kind == "play":
            cards = _cards(rec.get("cards"))
            seat = rec.get("seat")
            if (len(plays) == 4 or seat != (leader + len(plays)) % 4 or not cards
                    or (plays and len(cards) != len(plays[0]))):
                return False
            held[seat].subtract(cards)
            if any(v < 0 for v in held[seat].values()):
                return False
            played[seat] += len(cards)
            plays.append(cards)
        elif kind == "trick":
            winner = rec.get("winner")
            if len(plays) != 4 or not isinstance(winner, int) or not 0 <= winner < 4:
                return False
            leader, plays = winner, []
        elif kind in ("round_start", "round_end"):
            return False
    return not plays and played == [HAND_SIZE] * 4


def round_doc(f: Finished, listed: set[int] | None = None) -> dict | None:
    """The finished round as a watcher sees it: every event of the
    allow-list with every card shown, or None unless the log holds the
    whole round (``complete_sequence``). ``listed`` (a rerun) names only
    the players the leaderboard shows (``_redact``)."""
    records = _read(f)
    if records is None or not complete_sequence(records):
        return None
    events = []
    for rec in records:
        if rec.get("e") not in saved_games.PUBLIC_KEYS:
            continue
        ev = saved_games.public_event(rec, 0, True, None)
        if ev["e"] == "round_start":
            ev["players"] = _with_looks(_players(rec), f, listed)
        ev.pop("room", None)
        if listed is not None:
            ev = _redact(ev, _keeper(ev, rec, f, listed))
        events.append(ev)
    start = events[0]
    names = ["", "", "", ""]
    for p in start.get("players", []):
        names[p["seat"]] = p["name"]
    banker = next((e.get("banker") for e in events if e["e"] == "trump"), start.get("banker"))
    seat = banker if isinstance(banker, int) and 0 <= banker < 4 else 0
    return {"round": f.round, "seat": seat, "players": names, "finished": True,
            "events": events}


@dataclass(frozen=True)
class Built:
    """A round document and its JSON body without the outer braces, so an
    answer is its header and these bytes."""
    doc: dict
    body: bytes


_DOCS: collections.OrderedDict = collections.OrderedDict()
_PENDING: dict = {}


def _doc_key(f: Finished, listed: set[int] | None) -> tuple:
    """What a round's document depends on: the round, and for a rerun
    which of its own accounts the leaderboard shows now."""
    if listed is None:
        return (str(f.path), f.start, f.round, None)
    own = {u for u in (*f.start_accounts, *f.claims.values()) if isinstance(u, int)}
    return (str(f.path), f.start, f.round, frozenset(own & listed))


def _build(f: Finished, listed: set[int] | None) -> Built | None:
    doc = round_doc(f, listed)
    f.whole = doc is not None
    if doc is None:
        return None
    return Built(doc, _dumps(doc)[1:-1])


def _remember(key: tuple, built: Built | None) -> Built | None:
    _DOCS[key] = built
    _DOCS.move_to_end(key)
    while len(_DOCS) > DOC_CACHE:
        _DOCS.popitem(last=False)
    return built


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def _doc(f: Finished, listed: set[int] | None = None) -> Built | None:
    """``round_doc`` read and serialised once per round (and per rerun
    mask): a finished round's log never changes, so later watchers get the
    same bytes from memory. Readers arriving together share one read."""
    key = _doc_key(f, listed)
    if key in _DOCS:
        _DOCS.move_to_end(key)
        return _DOCS[key]
    task = _PENDING.get(key)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.ensure_future(asyncio.to_thread(_build, f, listed))
        _PENDING[key] = task
    try:
        built = await asyncio.shield(task)
    finally:
        if task.done() and _PENDING.get(key) is task:
            del _PENDING[key]
    return _remember(key, built)


def _answer(head: dict, built: Built) -> Response:
    return Response(content=_dumps(head)[:-1] + b"," + built.body + b"}",
                    media_type="application/json")


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


def servable(room: Any, now: float, wide: bool = False, token: str | None = None) -> bool:
    """Whether a watcher (``token``: one already counted here keeps its
    place) gets a live round here now; safe on any room, a lobby or an
    undealt one included: the table is watchable, holds a
    finished round its log holds whole, and has a place. The lobby count and
    the pick both ask this, so the link offers exactly the tables the feed
    serves."""
    return (watchable(room, wide) and (token in room.watch.watchers or _free(room, now))
            and any(f.whole is True and _is_over(room, f.round) for f in room.watch.recent))


def _mode(room: Any) -> str:
    return "ranked" if ratings.ranked(room) else "casual"


def _free(room: Any, now: float) -> bool:
    """Whether one more watcher has a place at this table."""
    return room.watch.live_watchers(now) < WATCH_CAP


def _counts() -> tuple[int, int, bool]:
    """(tables anyone may watch, live tables with a finished round, rerun),
    counting only tables with a free place."""
    _ensure_loaded()
    rooms, now = _rooms(), time.time()
    return (sum(1 for r in rooms if servable(r, now)),
            sum(1 for r in rooms if servable(r, now, True)),
            len(_reruns) > 0)


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
    """The table to watch, never one at its cap (unless this watcher
    already counts there). With no ``skip``: the asked mode first, then the
    one furthest into its game. With ``skip`` (Next table, or the table
    that went away): the next table after it in one fixed order, the asked
    mode first and then by table id, wrapping round, so each Next reaches
    another table and every table comes in turn however far each has
    played; ``skip`` itself only when no other table can be watched, and
    then never the rerun in its place."""
    rooms = _rooms()
    open_ = [r for r in rooms if servable(r, now, wide, token)]
    others = [r for r in open_ if r.watch.id != skip]
    if skip is not None:
        here = next((r for r in rooms if getattr(r, "watch", None) is not None
                     and r.watch.id == skip), None)
        if here is not None:
            def order(room: Any) -> tuple:
                return (_mode(room) != mode, room.watch.id)
            if not others:
                return here if servable(here, now, wide, token) else None
            after = [r for r in others if order(r) > order(here)]
            return min(after or others, key=order)
    best = None
    for room in others:
        st = room.watch
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


def _still(room: Any, wide: bool) -> bool:
    """The room is still the one under its code, and still watchable."""
    from . import server
    return server.rooms.get(room.code) is room and watchable(room, wide)


async def _serve(room: Any, token: str, after: int | None,
                 wide: bool) -> tuple[dict, Built | None] | None:
    """One table's answer: its header and its latest whole finished round
    (when newer than ``after``; a round whose log is incomplete gives way to
    the one before it), or the header alone (``waiting``) while its round is
    in play. None when, after the read, the room is gone or no longer
    watchable; the header is read then."""
    st = room.watch
    built = None
    for f in reversed(list(st.recent)):
        if after is not None and f.round <= after:
            break
        if not _is_over(room, f.round):
            continue
        built = await _doc(f)
        if built is not None or not _still(room, wide):
            break
    # checked again after the reads: the same room, still watchable, past the round
    if not _still(room, wide):
        return None
    head = {"table": st.id, "watcher": token, "mode": _mode(room),
            "live_round": room.game.round_no, "code": _join_code(room), "rerun": False,
            "watchers": st.live_watchers(time.time())}
    if built is None or not _is_over(room, built.doc["round"]):
        return {**head, "waiting": True}, None
    return {**head, "waiting": False}, built


# ------------------------------------------------------------- the players are told
def players_field(room: Any) -> dict:
    """The state frame's ``watchers``: how many watch the table now, the
    latest "is watching" toast (``told`` bumps once per toast; ``joined`` is
    who it tells of, a listed watcher by name and look, anyone else as null) and
    the names of the listed watchers now (at most two). A name is sent only
    for an account the leaderboard listed when it was told; never an id."""
    st = getattr(room, "watch", None)
    if st is None:
        return {"count": 0, "told": 0, "joined": [], "named": []}
    n = st.live_watchers(time.time())
    named = [v for tok in st.watchers if (v := st.shown.get(tok))][:2]
    return {"count": n, "told": st.told, "joined": list(st.joined), "named": named}


def announcement(st: WatchState, listed: set[int], now: float) -> bool:
    """Tell the players of the watchers who arrived since they were last
    told and still watch: each is named when the leaderboard lists its
    account, else null. False when nobody is left to tell of."""
    st.live_watchers(now)
    fresh = [tok for tok in dict.fromkeys(st.arrivals) if tok in st.watchers]
    st.arrivals = []
    if not fresh:
        return False
    looks = {}
    for tok in fresh:
        uid, name, look = st.who.get(tok, (None, None, None))
        st.shown[tok] = name if uid is not None and uid in listed and name else None
        looks[tok] = look
    st.told += 1
    st.joined = [{"name": st.shown[tok], "look": looks[tok] or accounts.DEFAULT_LOOK}
                 if st.shown[tok] else None for tok in fresh]
    st.told_at = now
    return True


def _schedule(room: Any) -> None:
    """One announcement, as soon as ``ANNOUNCE_GAP`` has passed since the
    last; arrivals in between wait for it."""
    st = room.watch
    task = st.announcing
    if task is not None and not task.done() and task.get_loop() is asyncio.get_running_loop():
        return
    st.announcing = asyncio.ensure_future(
        _announce(room, max(0.0, st.told_at + ANNOUNCE_GAP - time.time())))


async def _announce(room: Any, delay: float) -> None:
    from . import server
    st = room.watch
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        listed = await asyncio.to_thread(_listed)
        if announcement(st, listed, time.time()):
            await server._broadcast_locked(room)
    except Exception:               # noqa: BLE001 - a toast never breaks a table
        log.exception("spectate announcement failed")
    st.announcing = None
    if st.arrivals:
        _schedule(room)


def _arrived(room: Any, token: str, user: dict | None) -> None:
    """A watcher new at this table: its account (``user``, read before the
    table was last checked; server-side only) and the players' toast."""
    uid = user.get("id") if user else None
    st = room.watch
    st.who[token] = ((uid, accounts.effective_name(user) or None, accounts.account_look(uid))
                     if isinstance(uid, int) and not isinstance(uid, bool) else (None, None, None))
    st.arrivals.append(token)
    _schedule(room)


# ------------------------------------------------------------- endpoints
router = APIRouter(prefix="/api")


async def _viewer(request: Request) -> dict | None:
    """The signed-in account reading, once per request; None for a guest."""
    if not hasattr(request.state, "watch_user"):
        try:
            user = await accounts.STORE.run(accounts.STORE.session_user,
                                            request.cookies.get(accounts.COOKIE))
        except Exception:           # noqa: BLE001 - no account store reads as signed out
            user = None
        request.state.watch_user = user
    return request.state.watch_user


async def _admit(request: Request) -> bool:
    """Refuse a reader who may not watch, before anything is read; True for
    an allowlisted account (it may watch any live table)."""
    how = "all" if enabled() else None
    if how is None and allowlist():
        user = await _viewer(request)
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
                w: str | None = None, e: int = 0, q: int = 0) -> Response:
    """Pick a table and send its latest finished round; with no table, the
    rerun; with neither, 404. ``e`` is the reader's Watch session
    and ``q`` its read within that session (``admissible``): a read from an
    older session, or overtaken by a later read of its own, is answered and
    never counted."""
    wide = await _admit(request)
    # read before the table is picked and checked: no await comes between
    # that check and the answer
    user = await _viewer(request)
    token, now = _token(w), time.time()
    room = pick(mode if mode in ("ranked", "casual") else None, skip, token, now, wide)
    if room is not None:
        lease = (admit(room, token, e, now, q)
                 if admissible(token, e, room.watch.id, False, q) else None)
        out = await _serve(room, token, None, wide)
        if out is not None and out[1] is not None:
            # the players are told once per arrival, by the admission that
            # still holds the token when its answer is ready
            if holds(token, lease) and token not in room.watch.who:
                _arrived(room, token, user)
            return _answer(*out)
        # no live round for this watcher after all: it holds no place there
        unadmit(room, token, lease)
    _ensure_loaded()
    listed = await asyncio.to_thread(_listed) if _reruns else set()
    for rerun in reversed(list(_reruns)):
        built = await _doc(rerun, listed)
        if built is not None:
            return _answer({"table": RERUN_ID, "watcher": token, "mode": "ranked",
                            "live_round": None, "code": None, "rerun": True,
                            "waiting": False}, built)
        try:
            _reruns.remove(rerun)
        except ValueError:
            pass                    # another request dropped it first
        else:
            save()
    raise HTTPException(status_code=404, detail="Nothing to watch.")


@router.get("/watch/{table}")
async def follow(table: str, request: Request, after: int | None = None,
                 w: str | None = None, e: int = 0, q: int = 0) -> Response:
    """The table a watcher is at: its newer finished round, or ``waiting``
    while the round after ``after`` is in play. 404 once it cannot be
    watched (closed, emptied, Allow joiners off) or is at its cap."""
    wide = await _admit(request)
    token = _token(w)

    def find() -> Any | None:
        return next((r for r in _rooms() if getattr(r, "watch", None) is not None
                     and r.watch.id == table), None)

    # a reader new to the table: its account, read before the table is checked
    first = find()
    if first is not None:
        first.watch.live_watchers(time.time())         # an expired lease is new again
    user = (await _viewer(request)
            if first is None or token not in first.watch.who else None)
    room, now = find(), time.time()
    if room is None or not watchable(room, wide):
        raise HTTPException(status_code=404, detail="Not found.")
    st = room.watch
    # the feed is for the table's watchers and for one more while it has a
    # place, whether or not this read may renew a lease
    new = token not in st.watchers
    if new and not _free(room, now):
        raise HTTPException(status_code=404, detail="Not found.")
    lease = admit(room, token, e, now, q) if admissible(token, e, st.id, True, q) else None
    out = await _serve(room, token, after, wide)
    if out is None:
        unadmit(room, token, lease)
        raise HTTPException(status_code=404, detail="Not found.")
    if holds(token, lease) and token not in st.who:
        _arrived(room, token, user)
    head, built = out
    if built is None:
        return Response(content=_dumps(head), media_type="application/json")
    return _answer(head, built)


@router.post("/watch/leave", status_code=204)
async def leave(w: str | None = None, e: int = 0) -> Response:
    """Watch session ``e`` of the watcher ``w`` left (its screen closed or
    its page went away): it stops counting wherever it counts now, not when
    its lease runs out, unless a newer session has been admitted since
    (``release``). An unknown token changes nothing; the answer is the same."""
    if w is not None and 16 <= len(w) <= 64 and w.isalnum():
        release(w, e, time.time())
    return Response(status_code=204)


def register_spectate(app) -> None:
    app.include_router(router)
