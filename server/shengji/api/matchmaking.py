"""Matchmaking queue: signed-in players queue alone or as a pair and are
seated together at a shared waiting table that becomes an ordinary rated room.

The queue lives in memory, one per server process. Every state change is a
synchronous method with no ``await`` between the check and the mutation, so
under the asyncio loop a tick and a burst of messages can never seat one
player twice: a table leaves ``tables`` and its entries leave the queue
before its room is built, and a second ``table_start`` for it then finds
nothing.

Seating (``seat_waiting``, on every join and every ``tick``):

1. waiting entries (not yet at a table) are ordered front-of-line first,
   then longest wait;
2. each takes a free place at an existing waiting table, else opens a new
   table with the next waiting entry; with fewer than ``WINDOW_FROM`` people
   queued anyone sits with anyone, from ``WINDOW_FROM`` on only within the
   entry's rating window (``window_for`` its wait). Tables never merge;
3. seats fill in arrival order, alternating teams (``SEAT_ORDER``: the
   second person on the other team, the third as the first one's partner,
   the fourth the last seat); a pair takes two seats of one team
   (``PAIR_SEATS``). Nobody is re-seated while waiting, and a leaver's seat
   is simply free again.

A table starts (``tick``, and at once after the event that makes it due):

* when it has four people;
* when every entry at it has tapped Start (``table_start``; a pair's leader
  taps for the pair), bots taking the empty seats;
* at the table's timer: the earliest ``bots_at`` among its entries. An entry
  whose switch is on ("Only tables with people", ``queue_wait_players``)
  has no ``bots_at`` and rides another entry's timer; with every switch on
  the table has no timer.

The first two wait while a member is reconnecting (``TABLE_AWAY_SECS``); the
timer does not, and starts without an entry whose socket is still gone.
There is no ready check: the table is the accept. An entry alone in the queue
starts with bots at its own ``bots_at``, or at once on ``queue_start_bots``.

Room creation is the server's job: ``start_room`` is injected, and receives
the table id (``None`` for a game started alone) and the four seats in seat
order (bots as ``Slot`` with ``user_id=None``).

Open tables (``open_tables`` and ``join_table`` are injected by the server):
a ranked game in play with a seat a newcomer may take. A single entry alone
in the queue (after ``seat_waiting``, so a waiting table always comes first)
is offered the open table with the most people, for ``OFFER_SECS``: it picks
a seat and joins, or waits. A table it waited on (or let lapse) is never
offered to it again by itself, but stays one tap away on the bar while it is
joinable, and the entry's bot timer is paused for as long as an offer is up
or such a table can still be joined. Leaving a table it joined, before its
first ranked round there, costs a ``JOIN_COOLDOWN_SECS`` queue cooldown and
that table is never offered to it again.
"""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Awaitable, Callable

from . import accounts, ratings

log = logging.getLogger(__name__)

# Loop granularity: timers, away drops and the count broadcast are checked
# this often; seating and table starts run every TICK_INTERVAL.
PUMP_INTERVAL = 0.5
TICK_INTERVAL = 2.0
# An entry's own wait after which it starts with bots.
BOT_FILL_SECS = 60.0
# (wait below, rating half-width): the window widens with the entry's wait
# and is unlimited once the wait passes the last step.
WINDOW_STEPS: tuple[tuple[float, float], ...] = ((20.0, 100.0), (40.0, 250.0))
# People queued (at tables or not) from which the rating window decides who
# shares a table; below it everyone queued sits at one table.
WINDOW_FROM = 5
# How long a closed socket keeps its entry: alone in the queue, and seated at
# a waiting table (where an app sent to the background must not lose its seat).
AWAY_SECS = 10.0
TABLE_AWAY_SECS = 60.0
# A seated entry that has not tapped Start and sent nothing for this long
# leaves the table and the queue, with no cooldown.
TABLE_IDLE_SECS = 120.0
# Seat order for arrivals (team 0 at seats 0+2, team 1 at 1+3), and the two
# seat pairs a pair can take.
SEAT_ORDER = (0, 1, 2, 3)
PAIR_SEATS = ((0, 2), (1, 3))
# How long an open-table offer stays up, and the queue cooldown after
# leaving a table one joined before its first ranked round there.
OFFER_SECS = 10.0
JOIN_COOLDOWN_SECS = 300.0
PARTY_TTL = 300.0
COUNT_DEBOUNCE = 1.0
JOIN_LIMIT = (10, 60.0)      # queue_join per account per window
PARTY_LIMIT = (20, 60.0)     # party_* per account per window
LOOKUP_LIMIT = (30, 60.0)    # code_lookup per account (a guest: per socket) per window
# Room and pair codes share one space: no live room and live pair ever hold
# the same code, so one join box takes either. No I, O, 0 or 1, which read
# alike.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 4

QUEUE_MESSAGES = frozenset({
    "queue_join", "queue_leave", "table_start", "match_accept", "match_decline",
    "queue_start_bots", "queue_wait_players", "queue_allow_bots", "party_create", "party_invite", "party_join",
    "party_leave", "open_table_join", "open_table_wait", "open_table_show",
})
# The only queue message a seated socket may send: leaving a pair.
IN_ROOM_MESSAGES = frozenset({"party_leave"})


_CODE_RNG = secrets.SystemRandom()


def new_code(taken: Callable[[str], bool], rng: Any = None) -> str:
    """A code from the shared space that ``taken`` says is free. ``taken``
    must cover both live rooms and live pairs."""
    rng = rng if rng is not None else _CODE_RNG
    while True:
        code = "".join(rng.choices(CODE_ALPHABET, k=CODE_LEN))
        if not taken(code):
            return code


def normalize_code(raw: Any) -> str:
    return str(raw if raw is not None else "").strip().upper()


def window_for(wait: float) -> float:
    for below, width in WINDOW_STEPS:
        if wait < below:
            return width
    return math.inf


# ------------------------------------------------------------------ model
@dataclass(frozen=True)
class Slot:
    """One seat of a room to start: a human (``user_id``) or a bot (``None``)."""
    user_id: int | None
    name: str
    rating: float
    group: str | None = None      # entry id; the two seats of a pair share it

    @property
    def is_bot(self) -> bool:
        return self.user_id is None


@dataclass
class Party:
    id: str
    code: str
    leader: int
    members: list[int]
    names: dict[int, str]
    idle_since: float             # the 5-minute expiry runs while not queued


@dataclass
class Offer:
    """An open table offered to one entry: the table's seats as the server
    described them (``open`` marks a seat the newcomer may take), the seat
    picked for it, and when the offer lapses."""
    code: str
    seats: list[dict]
    pick: int
    expires_at: float
    round_end: bool = False
    # A pair's offer: the two partner seats, the leader's first. Neither
    # member picks; one confirm takes both.
    pair: tuple[int, int] | None = None

    def open_seats(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s.get("open")]


@dataclass
class Entry:
    id: str
    seq: int
    members: list[int]            # leader first
    leader: int
    member_ratings: dict[int, float]
    since: float
    front: bool = False
    party_id: str | None = None
    # When this entry starts with bots; None while its switch ("Only tables
    # with people") is on.
    bots_at: float | None = None
    # The waiting table it sits at, and when a member last sent anything
    # there (or it sat down): the idle clock.
    table_id: str | None = None
    active_at: float = 0.0
    # The open table on offer, the remaining bot wait while the timer is
    # paused for open tables, and the open tables this entry waited on that
    # can still be joined (the bar's chip).
    offer: Offer | None = None
    paused: float | None = None
    open_codes: list[str] = field(default_factory=list)
    # A Join is in flight: the entry is neither seated nor started meanwhile.
    claiming: bool = False

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def rating(self) -> float:
        return sum(self.member_ratings.values()) / len(self.member_ratings)


@dataclass
class Table:
    """A waiting table: up to four people in fixed seats, before the game."""
    id: str
    seq: int
    seats: list[int | None] = field(default_factory=lambda: [None] * 4)
    entries: list[Entry] = field(default_factory=list)   # arrival order
    ready: set[str] = field(default_factory=set)          # entry ids that tapped Start
    seated_at: dict[int, float] = field(default_factory=dict)

    @property
    def humans(self) -> int:
        return sum(e.size for e in self.entries)

    @property
    def rating(self) -> float:
        rs = [r for e in self.entries for r in e.member_ratings.values()]
        return sum(rs) / len(rs)

    def places_for(self, e: Entry) -> tuple[int, ...] | None:
        """The seats ``e`` would take: the first free seat in arrival order,
        or for a pair the first free seat pair of one team."""
        if e.size == 1:
            for s in SEAT_ORDER:
                if self.seats[s] is None:
                    return (s,)
            return None
        for pair in PAIR_SEATS:
            if all(self.seats[s] is None for s in pair):
                return pair
        return None

    def timer(self) -> tuple[float, Entry] | None:
        """The table's bot timer and its owner: the earliest ``bots_at`` of
        an entry whose switch is off; None when every switch is on."""
        timed = [e for e in self.entries if e.bots_at is not None]
        if not timed:
            return None
        owner = min(timed, key=lambda e: (e.bots_at, e.seq))
        return owner.bots_at, owner


# ------------------------------------------------------------ connections
class Conn:
    """One websocket as the queue sees it, with its own outbound writer so
    the matcher can message lobby sockets without awaiting them.

    ``adopted`` is set by the server when it seats this socket in a matched
    room: ``(room, seat, gen)``, picked up by the socket's receive loop.
    """

    def __init__(self, ws: Any, user_id: int | None, name: str = "") -> None:
        self.ws = ws
        self.user_id = user_id
        self.name = name
        self.closed = False
        self.closed_at: float | None = None
        self.in_room = False
        self.adopted: tuple | None = None
        # ``(room, seat)`` while this socket's Join of an open table waits for
        # its handover; set and cleared by the server.
        self.joining: tuple | None = None
        self._queue: asyncio.Queue | None = None
        self._writer: asyncio.Task | None = None

    def push(self, payload: dict) -> None:
        if self.closed:
            return
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=64)
            self._writer = asyncio.get_running_loop().create_task(self._drain())
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(payload)
            except asyncio.QueueEmpty:
                pass

    async def _drain(self) -> None:
        assert self._queue is not None
        try:
            while True:
                await self.ws.send_json(await self._queue.get())
        except asyncio.CancelledError:
            raise
        except Exception as error:   # noqa: BLE001 - a dead socket ends its writer
            log.debug("queue writer stopped: %s", error)

    def close(self, at: float) -> None:
        self.closed, self.closed_at = True, at
        if self._writer is not None:
            self._writer.cancel()
        self._writer, self._queue = None, None


class QueueError(Exception):
    def __init__(self, code: str, message: str, **fields: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.fields = code, message, fields


async def _store_rating(user_id: int) -> float | None:
    store = accounts.STORE
    return await store.run(ratings.current_rating, store, user_id)


# ------------------------------------------------------------- the queue
StartRoom = Callable[[str | None, list[Slot], dict[int, Conn]], Awaitable[Any]]
# (room code, seat, account, name, socket) -> None when the seat is the
# newcomer's (pending until the handover), else a refusal code.
JoinTable = Callable[[str, int, int, str, Conn], Awaitable[str | None]]
# (room code, the two partner seats, the two accounts, their names, their
# sockets, the account that confirmed) -> as JoinTable, for both at once.
JoinPair = Callable[[str, list[int], list[int], list[str], list[Conn], int],
                    Awaitable[str | None]]


class Matchmaker:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 rating_of: Callable[[int], Awaitable[float | None]] | None = None,
                 start_room: StartRoom | None = None,
                 user_active: Callable[[int], bool] | None = None,
                 room_live: Callable[[str], bool] | None = None,
                 open_tables: Callable[[], list[dict]] | None = None,
                 join_table: JoinTable | None = None,
                 join_pair: JoinPair | None = None,
                 autorun: bool = True) -> None:
        self.clock = clock
        self.rating_of = rating_of or _store_rating
        self.start_room = start_room
        self.user_active = user_active or (lambda uid: not accounts.is_deleted(uid))
        # Whether a code names a live room: pair codes avoid them, and
        # code_lookup answers with them.
        self.room_live = room_live or (lambda code: False)
        # The open tables as the server sees them (``{"code", "seats",
        # "round_end"}``; a seat is ``{"name", "bot", "open", "user_id",
        # "team"}``), and the server's join of one seat for one account.
        self.open_tables = open_tables or (lambda: [])
        self.join_table = join_table
        self.join_pair = join_pair
        self.autorun = autorun
        self._task: asyncio.Task | None = None
        self.reset()

    def reset(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self.lobby: dict[Conn, None] = {}         # ordered set of lobby sockets
        self.conns: dict[int, Conn] = {}          # account -> its queue socket
        self.entries: dict[str, Entry] = {}
        self.entry_of: dict[int, str] = {}
        self.tables: dict[str, Table] = {}
        self.parties: dict[str, Party] = {}
        self.party_of: dict[int, str] = {}
        self.party_codes: dict[str, str] = {}
        # Open tables: per account, the tables it waited on (never offered
        # again by themselves), the tables it may never be offered (it joined
        # and left), its queue cooldown, and a Join waiting for its handover
        # (the entry kept to put back in line if the seat is reclaimed).
        self.declined: dict[int, set[str]] = {}
        self.barred: dict[int, set[str]] = {}
        self.cooldowns: dict[int, float] = {}
        self.joining: dict[int, tuple[str, Entry | None]] = {}
        self.join_limiter = accounts.RateLimiter(*JOIN_LIMIT)
        self.party_limiter = accounts.RateLimiter(*PARTY_LIMIT)
        self.lookup_limiter = accounts.RateLimiter(*LOOKUP_LIMIT)
        self._seq = count(1)
        self._count_sent = 0
        self._count_sent_at = -math.inf
        self._last_tick = -math.inf

    # ---------------------------------------------------------- plumbing
    def ensure_running(self) -> None:
        if not self.autorun or (self._task is not None and not self._task.done()):
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(PUMP_INTERVAL)
            try:
                await self.pump()
            except Exception:      # noqa: BLE001 - the queue outlives one bad tick
                log.exception("matchmaking pump failed")
            if (not self.entries and not self.tables and not self.parties
                    and not self.joining and self._count_sent == 0):
                return

    def _live(self, uid: int) -> Conn | None:
        c = self.conns.get(uid)
        return c if c is not None and not c.closed else None

    def _available(self, uid: int) -> bool:
        c = self._live(uid)
        return c is not None and not c.in_room

    def _entry_available(self, e: Entry) -> bool:
        return all(self._available(u) for u in e.members)

    def _send(self, uid: int, payload: dict) -> None:
        c = self._live(uid)
        if c is not None:
            c.push(payload)

    def _error(self, conn: Conn, err: QueueError) -> None:
        conn.push({"type": "error", "code": err.code, "message": err.message,
                   **err.fields})

    def _name(self, uid: int) -> str:
        c = self.conns.get(uid)
        return (c.name if c is not None else "") or "Player"

    def count(self) -> int:
        return sum(e.size for e in self.entries.values())

    def _flush_count(self) -> None:
        now = self.clock()
        n = self.count()
        if n == self._count_sent or now - self._count_sent_at < COUNT_DEBOUNCE:
            return
        self._count_sent, self._count_sent_at = n, now
        for c in list(self.lobby):
            c.push({"type": "queue_count", "count": n})

    def _entry(self, uid: int) -> Entry | None:
        eid = self.entry_of.get(uid)
        return self.entries.get(eid) if eid is not None else None

    def _party(self, uid: int) -> Party | None:
        pid = self.party_of.get(uid)
        return self.parties.get(pid) if pid is not None else None

    def _table(self, e: Entry | None) -> Table | None:
        return self.tables.get(e.table_id) if e is not None and e.table_id else None

    def table_payload(self, t: Table, uid: int) -> dict:
        """The waiting table as ``uid`` sees it: the four seats in seat order
        (``null`` for an empty one), whose Start is in, the timer's owner,
        and who is still to tap Start."""
        mine = self._entry(uid)
        by_user = {u: e for e in t.entries for u in e.members}
        seats: list[dict | None] = []
        for u in t.seats:
            if u is None:
                seats.append(None)
                continue
            e = by_user[u]
            seats.append({"name": self._name(u), "you": u == uid,
                          "ready": e.id in t.ready, "reconnecting": self._live(u) is None,
                          "since": t.seated_at.get(u), "pair": e.size == 2,
                          "leader": e.leader == u})
        timer = t.timer()
        return {
            "id": t.id, "seats": seats,
            "you": t.seats.index(uid) if uid in t.seats else None,
            "timer": (None if timer is None else
                      {"at": timer[0], "name": self._name(timer[1].leader),
                       "you": uid in timer[1].members}),
            "ready": sum(e.size for e in t.entries if e.id in t.ready),
            "of": t.humans,
            "you_ready": mine is not None and mine.id in t.ready,
            "waiting_for": [self._name(e.leader) for e in t.entries
                            if e.id not in t.ready and uid not in e.members],
        }

    def queue_state(self, uid: int) -> dict:
        e = self._entry(uid)
        if e is None:
            return {"type": "queue_state", "queued": False, "count": self.count()}
        t = self._table(e)
        return {"type": "queue_state", "queued": True, "since": e.since,
                "count": self.count(), "front": e.front,
                "party_id": e.party_id, "leader": e.leader == uid,
                "bots_at": e.bots_at,
                "wait_players": e.bots_at is None and e.paused is None,
                "bots_paused": e.paused is not None,
                "table": self.table_payload(t, uid) if t is not None else None,
                "offer": self._offer_payload(e.offer, uid, e) if e.offer is not None else None,
                "open_tables": len(e.open_codes)}

    def _offer_payload(self, o: Offer, uid: int | None = None, e: Entry | None = None) -> dict:
        """The offer as ``uid`` sees it: for a pair, ``pick`` is its own seat
        and ``partner`` the other member's."""
        out = {"room": o.code, "pick": o.pick, "expires_at": o.expires_at,
               "round_end": o.round_end, "partner": None,
               "seats": [{"name": s.get("name") or "Player", "bot": bool(s.get("bot")),
                          "open": bool(s.get("open"))} for s in o.seats]}
        if o.pair is not None and e is not None and uid in e.members:
            mine = o.pair[e.members.index(uid)]
            other = next(u for u in e.members if u != uid)
            out["pick"] = mine
            out["partner"] = {"seat": o.pair[1 - e.members.index(uid)], "name": self._name(other)}
        return out

    def _send_state(self, e: Entry) -> None:
        for u in e.members:
            self._send(u, self.queue_state(u))

    def _send_table(self, t: Table) -> None:
        for e in t.entries:
            self._send_state(e)

    def _remove(self, e: Entry) -> None:
        """Take ``e`` out of the queue, freeing its seats at a waiting table
        (nobody moves). The table's others are told; ``e``'s own members are
        the caller's to tell."""
        self._unseat(e)
        self.entries.pop(e.id, None)
        for u in e.members:
            if self.entry_of.get(u) == e.id:
                del self.entry_of[u]
        if e.party_id in self.parties:
            self.parties[e.party_id].idle_since = self.clock()

    def _unseat(self, e: Entry) -> None:
        t = self._table(e)
        e.table_id = None
        if t is None:
            return
        t.entries = [o for o in t.entries if o is not e]
        t.ready.discard(e.id)
        for s, u in enumerate(t.seats):
            if u in e.members:
                t.seats[s] = None
                t.seated_at.pop(u, None)
        left = list(t.entries)
        if len(left) <= 1:
            # One entry left is alone again: back to its own bar and timer.
            self.tables.pop(t.id, None)
            for o in left:
                o.table_id = None
            t.entries, t.ready = [], set()
        for o in left:
            self._send_state(o)

    # ------------------------------------------------------- connections
    def connect(self, conn: Conn) -> None:
        """A new socket: it is a lobby socket, and when its account's queue
        socket is gone it becomes the queue socket and gets the state back."""
        self.lobby[conn] = None
        n = self.count()
        if n:
            conn.push({"type": "queue_count", "count": n})
        uid = conn.user_id
        if uid is not None and self._live(uid) is None:
            self.conns[uid] = conn
            self._resync(uid)

    def disconnect(self, conn: Conn) -> None:
        conn.close(self.clock())
        self.lobby.pop(conn, None)
        uid = conn.user_id
        if uid is not None and self.conns.get(uid) is conn:
            t = self._table(self._entry(uid))
            if t is not None:          # the others see the seat reconnecting
                self._send_table(t)

    def enter_room(self, conn: Conn) -> None:
        """The socket is joining or holds a seat: no longer a lobby socket,
        and never seated by the matcher while it is in a room."""
        conn.in_room = True
        self.lobby.pop(conn, None)

    def leave_for_room(self, conn: Conn) -> None:
        """The socket took a seat in some other room: its queue entry goes,
        and its seat at a waiting table is free."""
        uid = conn.user_id
        if uid is None or self.conns.get(uid) is not conn:
            return
        e = self._entry(uid)
        if e is None:
            return
        self._remove(e)
        for u in e.members:
            payload = {"type": "queue_removed", "reason": "in_room",
                       "cooldown_until": None}
            if e.size == 2:
                payload["by"] = self._name(uid)
            self._send(u, payload)
        self._flush_count()

    def return_to_lobby(self, conn: Conn) -> None:
        if conn.closed or not conn.in_room:
            return
        conn.in_room = False
        self.lobby[conn] = None
        n = self.count()
        if n:
            conn.push({"type": "queue_count", "count": n})
        uid = conn.user_id
        if uid is not None and self._live(uid) is None:
            self.conns[uid] = conn
            self._resync(uid)

    def _bind(self, conn: Conn, uid: int) -> None:
        """The socket that last spoke for an account is its queue socket; a
        replaced live socket is told it no longer holds the entry."""
        old = self.conns.get(uid)
        if old is conn:
            return
        self.conns[uid] = conn
        if old is not None and not old.closed and uid in self.entry_of:
            old.push({"type": "queue_state", "queued": False,
                      "count": self.count(), "replaced": True})

    def _resync(self, uid: int) -> None:
        p = self._party(uid)
        if p is not None:
            self._send(uid, self._party_payload(p, uid))
        e = self._entry(uid)
        if e is None:
            return
        t = self._table(e)
        if t is not None:              # back from reconnecting: everyone sees it
            self._send_table(t)
        else:
            self._send(uid, self.queue_state(uid))

    # ---------------------------------------------------------- messages
    async def handle(self, conn: Conn, msg: dict, user_id: int | None) -> None:
        t = msg.get("type")
        try:
            if user_id is None:
                raise QueueError("signed_in_only",
                                 "Sign in to play people; the queue is rated.")
            if conn.in_room and t not in IN_ROOM_MESSAGES:
                raise QueueError("in_room", "Leave the room before queueing.")
            now = self.clock()
            e = self._entry(user_id)
            if e is not None and e.table_id is not None:
                e.active_at = now          # any message from the table is a tap
            if t == "queue_join":
                if not self.join_limiter.allow(str(user_id), now):
                    raise QueueError("rate_limited", "Too many requests; wait a minute.")
                self._bind(conn, user_id)
                await self._join(conn, user_id, msg)
            elif t.startswith("party_"):
                if not self.party_limiter.allow(str(user_id), now):
                    raise QueueError("rate_limited", "Too many requests; wait a minute.")
                self._bind(conn, user_id)
                if t in ("party_create", "party_invite"):
                    self._party_create(user_id)
                elif t == "party_join":
                    self._party_join(user_id, msg)
                else:
                    self._party_leave(user_id)
            else:
                self._bind(conn, user_id)
                if t == "queue_leave":
                    self._leave(user_id)
                elif t in ("match_accept", "match_decline"):
                    # The ready check is gone: the waiting table is the accept.
                    raise QueueError("no_match", "There is no ready check for you.")
                elif t == "table_start" or (t == "queue_start_bots" and self._table(e) is not None):
                    # An older client's Play bots at a table is its Start.
                    await self._table_start(user_id)
                elif t == "queue_start_bots":
                    await self._start_bots(user_id)
                elif t in ("queue_wait_players", "queue_allow_bots"):
                    self._set_bot_fill(user_id, t == "queue_allow_bots")
                elif t == "open_table_join":
                    await self._open_join(conn, user_id, msg)
                elif t == "open_table_wait":
                    self._open_wait(user_id)
                elif t == "open_table_show":
                    self._open_show(user_id, msg)
        except QueueError as err:
            self._error(conn, err)
        self.ensure_running()

    async def _join(self, conn: Conn, uid: int, msg: dict) -> None:
        if uid in self.entry_of:              # already queued: this socket holds it now
            self._resync(uid)
            return
        want = msg.get("party_id")
        party = self._party(uid)
        members, pid = [uid], None
        if party is not None and len(party.members) == 2:
            if want is not None and want != party.id:
                raise QueueError("bad_party", "That is not your party.")
            if party.leader != uid:
                raise QueueError("not_leader", "Only the party leader can queue.")
            members, pid = list(party.members), party.id
        elif want is not None:
            raise QueueError("party_incomplete" if party is not None and party.id == want
                             else "bad_party", "Your friend has not joined yet.")
        for m in members:
            if m != uid and not self._available(m):
                raise QueueError("partner_unavailable", "Your partner is not in the lobby.")
        until = max((self.cooldowns.get(m, 0.0) for m in members), default=0.0)
        if until > self.clock():
            raise QueueError("cooldown", "You left a table you joined. You can queue "
                             "again in 5 minutes.", cooldown_until=until)
        member_ratings = {}
        for m in members:
            r = await self.rating_of(m)
            member_ratings[m] = float(r) if r is not None else accounts.START_RATING
        # Re-check everything the awaits could have changed.
        if any(m in self.entry_of for m in members):
            self._resync(uid)
            return
        if conn.closed or conn.in_room:
            return
        if pid is not None and (self.party_of.get(uid) != pid
                                or self.parties[pid].members != members):
            raise QueueError("party_changed", "Your party changed; try again.")
        since = self.clock()
        e = Entry(id=secrets.token_hex(6), seq=next(self._seq), members=members,
                  leader=uid, member_ratings=member_ratings, since=since,
                  party_id=pid, bots_at=since + BOT_FILL_SECS)
        self.entries[e.id] = e
        for m in members:
            self.entry_of[m] = e.id
        self.seat_waiting()
        self._offer_open_tables(self.clock(), quiet={e.id})
        if e.table_id is None:
            self._send_state(e)
        self._flush_count()
        await self._start_due()

    def _leave(self, uid: int) -> None:
        e = self._entry(uid)
        if e is None:
            self._send(uid, self.queue_state(uid))
            return
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can cancel.")
        self._remove(e)
        self._send_state(e)
        self._flush_count()

    def _set_bot_fill(self, uid: int, allow: bool) -> None:
        """Turn the entry's bot timer off ("Only tables with people") or back
        on, due ``BOT_FILL_SECS`` from now. The entry keeps its wait, its
        window, its place in line and its seat; at a table the table's timer
        may change owner, so everyone there is told."""
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can change this.")
        if allow:
            if e.bots_at is None and e.paused is None:
                e.bots_at = self.clock() + BOT_FILL_SECS
        else:
            e.bots_at, e.paused = None, None
        t = self._table(e)
        if t is not None:
            self._send_table(t)
        else:
            self._send_state(e)

    async def _table_start(self, uid: int) -> None:
        """Start at the waiting table: this entry is ready. Readiness is never
        taken back, and a newcomer does not clear it."""
        e = self._entry(uid)
        t = self._table(e)
        if e is None or t is None:
            raise QueueError("not_seated", "You are not at a waiting table.")
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can start.")
        if e.id not in t.ready:
            t.ready.add(e.id)
            self._send_table(t)
        await self._start_due()

    # ----------------------------------------------------------- seating
    def seat_waiting(self) -> None:
        """Seat every waiting entry that can sit: first at an existing waiting
        table with its places free (a newcomer joins the table before anyone
        opens another), then at a new table with the next waiting entry. From
        ``WINDOW_FROM`` people queued, only within the entry's rating window."""
        now = self.clock()
        windowed = self.count() >= WINDOW_FROM

        def near(e: Entry, rating: float) -> bool:
            return not windowed or abs(rating - e.rating) <= window_for(now - e.since)

        def gap(e: Entry, rating: float) -> float:
            return abs(rating - e.rating) if windowed else 0.0

        while True:
            pool = sorted((e for e in self.entries.values()
                           if e.table_id is None and not e.claiming
                           and self._entry_available(e)),
                          key=lambda e: (not e.front, e.since, e.seq))
            seated = False
            for e in pool:
                fits = [t for t in self.tables.values()
                        if t.places_for(e) is not None and near(e, t.rating)]
                if fits:
                    t = min(fits, key=lambda t: (gap(e, t.rating), t.seq))
                    self._sit(t, e, now)
                    self._send_table(t)
                    seated = True
            if seated:
                continue
            for e in pool:
                others = [o for o in pool if o is not e and near(e, o.rating)]
                if not others:
                    continue
                o = min(others, key=lambda o: (gap(e, o.rating), not o.front, o.since, o.seq))
                t = Table(id=secrets.token_hex(6), seq=next(self._seq))
                self.tables[t.id] = t
                self._sit(t, e, now)
                self._sit(t, o, now)
                self._send_table(t)
                seated = True
                break
            if not seated:
                return

    def _sit(self, t: Table, e: Entry, now: float) -> None:
        places = t.places_for(e)
        assert places is not None
        for s, u in zip(places, e.members):
            t.seats[s] = u
            t.seated_at[u] = now
        t.entries.append(e)
        e.table_id, e.active_at = t.id, now
        # A waiting table outranks an open table: the offer goes, and a
        # paused bot wait runs again as the table's timer.
        e.offer, e.open_codes = None, []
        if e.paused is not None:
            e.bots_at, e.paused = now + e.paused, None

    # ------------------------------------------------------------- starts
    def _due(self, t: Table, now: float) -> bool:
        timer = t.timer()
        if timer is not None and now >= timer[0]:
            return True
        if not all(self._entry_available(e) for e in t.entries):
            return False               # four people or every Start: wait for a reconnect
        return t.humans == 4 or all(e.id in t.ready for e in t.entries)

    async def _start_due(self) -> None:
        """Start every table that is due and every lone entry whose bot timer
        ran out. One at a time: each leaves the queue before its room awaits.
        An entry whose start failed is not tried again in the same pass."""
        tried: set[str] = set()
        while True:
            now = self.clock()
            t = next((t for t in sorted(self.tables.values(), key=lambda t: t.seq)
                      if self._due(t, now) and not any(e.id in tried for e in t.entries)), None)
            if t is not None:
                tried.update(e.id for e in t.entries)
                await self._launch_table(t)
                continue
            e = next((e for e in sorted(self.entries.values(), key=lambda e: e.seq)
                      if e.table_id is None and e.bots_at is not None and e.id not in tried
                      and not e.claiming
                      and now >= e.bots_at and self._entry_available(e)), None)
            if e is None:
                return
            tried.add(e.id)
            await self._launch_alone(e)

    async def _launch_table(self, t: Table) -> None:
        """Build the room for a due table. Synchronous up to the ``start_room``
        call, so the table and its entries are gone before anything yields.
        An entry whose socket is gone at the start leaves with no cooldown."""
        self.tables.pop(t.id, None)
        entries = list(t.entries)
        for e in entries:
            e.table_id = None
        gone = [e for e in entries if not self._entry_available(e)]
        for e in gone:
            self._remove(e)
            for u in e.members:
                self._send(u, {"type": "queue_removed", "reason": "away",
                               "cooldown_until": None})
        entries = [e for e in entries if e not in gone]
        if not entries:
            self._flush_count()
            return
        by_user = {u: e for e in entries for u in e.members}
        slots = []
        for u in t.seats:
            e = by_user.get(u) if u is not None else None
            if e is None:
                slots.append(Slot(None, "", ratings.BOT_RATING))
            else:
                slots.append(Slot(u, self._name(u), e.member_ratings[u],
                                  e.id if e.size == 2 else None))
        for e in entries:
            self._remove(e)
        self._flush_count()
        await self._start_room_for(t.id, slots, entries)

    async def _launch_alone(self, e: Entry) -> None:
        """An entry alone in the queue whose own timer ran out: it plays the
        bots now, as with ``queue_start_bots``."""
        self._remove(e)
        self._flush_count()
        await self._start_room_for(None, self._bot_slots(e), [e])

    def _bot_slots(self, e: Entry) -> list[Slot]:
        bot = Slot(None, "", ratings.BOT_RATING)
        people = [Slot(u, self._name(u), e.member_ratings[u], e.id) for u in e.members]
        return ([people[0], bot, bot, bot] if len(people) == 1
                else [people[0], bot, people[1], bot])

    async def _start_room_for(self, table_id: str | None, slots: list[Slot],
                              entries: list[Entry]) -> bool:
        """Start the room; on failure every entry goes back in the queue at
        the front, unseated, and is told. Never strands a player."""
        conns = {s.user_id: self.conns[s.user_id] for s in slots if s.user_id is not None}
        try:
            await self._start(table_id, slots, conns)
            return True
        except Exception:          # noqa: BLE001 - players go back, never stranded
            log.exception("queued room failed to start")
            for e in entries:
                e.front, e.table_id = True, None
                self.entries[e.id] = e
                for u in e.members:
                    self.entry_of[u] = e.id
                    self._send(u, {"type": "match_cancelled", "match_id": table_id,
                                   "reason": "server_error"})
                self._send_state(e)
            self._flush_count()
            return False

    async def _start(self, table_id: str | None, slots: list[Slot],
                     conns: dict[int, Conn]) -> Any:
        if self.start_room is None:
            raise RuntimeError("no room factory")
        return await self.start_room(table_id, slots, conns)

    async def _start_bots(self, uid: int) -> None:
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can start with bots.")
        for m in e.members:
            if not self._available(m):
                raise QueueError("partner_unavailable", "Your partner is not in the lobby.")
        self._remove(e)
        self._flush_count()
        slots = self._bot_slots(e)
        conns = {u: self.conns[u] for u in e.members}
        try:
            await self._start(None, slots, conns)
        except Exception:          # noqa: BLE001
            log.exception("bot game failed to start")
            err = QueueError("start_failed", "Could not start the game.")
            for m in e.members:
                if m != uid and (c := self._live(m)) is not None:
                    self._error(c, err)
            raise err

    # --------------------------------------------------------- open tables
    def _usable(self, t: dict, uid: int) -> bool:
        """Can ``uid`` be offered this open table: a seat is open, it holds no
        seat there already, and it never left this table after joining."""
        if t["code"] in self.barred.get(uid, ()):
            return False
        seats = t["seats"]
        return (any(s.get("open") for s in seats)
                and not any(s.get("user_id") == uid for s in seats))

    @staticmethod
    def _default_pick(seats: list[dict]) -> int:
        """The lone human's partner seat when it is open, else the first
        open seat."""
        humans = [i for i, s in enumerate(seats) if not s.get("bot") and not s.get("open")]
        if len(humans) == 1 and seats[(humans[0] + 2) % 4].get("open"):
            return (humans[0] + 2) % 4
        return next(i for i, s in enumerate(seats) if s.get("open"))

    @staticmethod
    def _pair_seats(seats: list[dict]) -> tuple[int, int] | None:
        """Two open partner seats (opposite each other), or None."""
        for s in (0, 1):
            if seats[s].get("open") and seats[s + 2].get("open"):
                return (s, s + 2)
        return None

    def _fits(self, t: dict, e: Entry) -> bool:
        """A single fits any open seat; a pair only two open partner seats."""
        if not all(self._usable(t, u) for u in e.members):
            return False
        return e.size == 1 or self._pair_seats(t["seats"]) is not None

    def _declined_by(self, e: Entry, code: str) -> bool:
        return any(code in self.declined.get(u, ()) for u in e.members)

    def _make_offer(self, t: dict, now: float, e: Entry | None = None) -> Offer:
        pair = self._pair_seats(t["seats"]) if e is not None and e.size == 2 else None
        return Offer(code=t["code"], seats=list(t["seats"]),
                     pick=pair[0] if pair else self._default_pick(t["seats"]),
                     expires_at=now + OFFER_SECS, round_end=bool(t.get("round_end")), pair=pair)

    def _offer_open_tables(self, now: float, quiet: set[str] = frozenset()) -> None:
        """Bring every lone single's open-table state up to date: re-render or
        withdraw a standing offer, offer the best table it has not waited on,
        list the waited-on tables still joinable, and pause or resume its bot
        wait. An entry not at a waiting table is offered one: a single any
        open seat, a pair only two open partner seats; entries in ``quiet``
        are told by the caller."""
        tables = [t for t in self.open_tables() if t.get("seats")]
        by_code = {t["code"]: t for t in tables}
        for e in sorted(self.entries.values(), key=lambda e: e.seq):
            if e.table_id is not None or e.claiming:
                continue
            uid = e.leader
            usable = [t for t in tables if self._fits(t, e)]
            before = (self._offer_payload(e.offer) if e.offer else None,
                      list(e.open_codes), e.paused is not None)
            if e.offer is not None:
                t = by_code.get(e.offer.code)
                if t is None or t not in usable:
                    e.offer = None
                elif t["seats"] != e.offer.seats:
                    # another newcomer took a seat: re-render, keeping the pick if open
                    e.offer.seats = list(t["seats"])
                    e.offer.round_end = bool(t.get("round_end"))
                    if e.offer.pair is not None:
                        e.offer.pair = self._pair_seats(t["seats"])
                        e.offer.pick = e.offer.pair[0]
                    elif e.offer.pick not in e.offer.open_seats():
                        e.offer.pick = self._default_pick(t["seats"])
            if e.offer is None and self._entry_available(e):
                fresh = [t for t in usable if not self._declined_by(e, t["code"])]
                if fresh:
                    best = max(fresh, key=lambda t: sum(1 for s in t["seats"] if not s.get("bot")))
                    e.offer = self._make_offer(best, now, e)
            e.open_codes = [t["code"] for t in usable
                            if self._declined_by(e, t["code"])
                            and (e.offer is None or t["code"] != e.offer.code)]
            self._sync_pause(e, now)
            after = (self._offer_payload(e.offer) if e.offer else None,
                     list(e.open_codes), e.paused is not None)
            if after != before and e.id not in quiet:
                self._send_state(e)

    @staticmethod
    def _sync_pause(e: Entry, now: float) -> None:
        """The bot wait stands still while an offer is up or a waited-on open
        table can still be joined, and runs on from where it stopped after."""
        hold = e.offer is not None or bool(e.open_codes)
        if hold and e.bots_at is not None:
            e.paused, e.bots_at = max(0.0, e.bots_at - now), None
        elif not hold and e.paused is not None:
            e.bots_at, e.paused = now + e.paused, None

    def _decline(self, e: Entry) -> None:
        """Wait (either member of a pair): the table is waited on for both."""
        if e.offer is not None:
            for u in e.members:
                self.declined.setdefault(u, set()).add(e.offer.code)
            e.offer = None

    def _lapse_offers(self, now: float) -> None:
        """An offer nobody answered in ``OFFER_SECS`` counts as Wait."""
        for e in list(self.entries.values()):
            if e.offer is not None and not e.claiming and now >= e.offer.expires_at:
                self._decline(e)
                self._offer_open_tables(now, quiet={e.id})
                self._send_state(e)

    def _open_wait(self, uid: int) -> None:
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        self._decline(e)
        self._offer_open_tables(self.clock(), quiet={e.id})
        self._send_state(e)

    def _open_show(self, uid: int, msg: dict) -> None:
        """The bar's open-table chip: the offer again, with a fresh clock."""
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        now = self.clock()
        self._offer_open_tables(now, quiet={e.id})
        want = normalize_code(msg.get("room")) or None
        code = want if want in e.open_codes else (e.open_codes[0] if e.open_codes else None)
        t = next((t for t in self.open_tables() if t["code"] == code), None)
        if e.offer is None and t is not None and self._fits(t, e):
            e.offer = self._make_offer(t, now, e)
            e.open_codes = [c for c in e.open_codes if c != code]
        elif e.offer is None:
            self._send_state(e)
            raise QueueError("table_closed", "That table is no longer open.")
        self._sync_pause(e, now)
        self._send_state(e)

    async def _open_join(self, conn: Conn, uid: int, msg: dict) -> None:
        """Join on the offer: the server makes the seat this account's,
        pending until the handover, and the entry leaves the queue. A seat
        another newcomer confirmed first is refused and the offer re-renders
        without it."""
        e = self._entry(uid)
        if e is None or e.offer is None or e.claiming:
            raise QueueError("no_offer", "That table is no longer offered to you.")
        code = normalize_code(msg.get("room")) or e.offer.code
        seat = msg.get("seat", e.offer.pick)
        if code != e.offer.code:
            raise QueueError("no_offer", "That table is no longer offered to you.")
        if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
            raise QueueError("bad_seat", "Pick one of the open seats.")
        if e.offer.pair is not None:
            await self._open_join_pair(e, uid, code)
            return
        if self.join_table is None:
            raise QueueError("table_closed", "That table is no longer open.")
        e.claiming = True
        # recorded before the await: a seat that owes nothing changes hands
        # inside the server's join, which clears it (``join_seated``)
        self.joining[uid] = (code, e)
        try:
            refused = await self.join_table(code, seat, uid, self._name(uid), conn)
        finally:
            e.claiming = False
        now = self.clock()
        if refused is None:
            if self.entries.get(e.id) is e:
                self._remove(e)
            e.offer, e.open_codes, e.front = None, [], True
            if e.paused is not None:
                e.bots_at, e.paused = now + e.paused, None
            self._flush_count()
            return
        self.joining.pop(uid, None)
        self._offer_open_tables(now, quiet={e.id})
        self._send_state(e)
        if refused == "seat_taken":
            raise QueueError("seat_taken", "That seat was just taken. Pick another.")
        raise QueueError("table_closed", "That table is no longer open.")

    async def _open_join_pair(self, e: Entry, uid: int, code: str) -> None:
        """Either member's Join takes both partner seats at once; ``uid`` is
        the one that confirmed (a leave before the handover costs only it)."""
        assert e.offer is not None and e.offer.pair is not None
        if not self._entry_available(e):
            raise QueueError("partner_unavailable", "Your partner is not in the lobby.")
        if self.join_pair is None:
            raise QueueError("table_closed", "That table is no longer open.")
        e.claiming = True
        for u in e.members:
            self.joining[u] = (code, e)
        try:
            refused = await self.join_pair(
                code, list(e.offer.pair), list(e.members), [self._name(u) for u in e.members],
                [self.conns[u] for u in e.members], uid)
        finally:
            e.claiming = False
        now = self.clock()
        if refused is None:
            if self.entries.get(e.id) is e:
                self._remove(e)
            e.offer, e.open_codes, e.front = None, [], True
            if e.paused is not None:
                e.bots_at, e.paused = now + e.paused, None
            self._flush_count()
            return
        for u in e.members:
            self.joining.pop(u, None)
        self._offer_open_tables(now, quiet={e.id})
        self._send_state(e)
        raise QueueError("table_closed" if refused != "seat_taken" else "seat_taken",
                         "Those seats were just taken." if refused == "seat_taken"
                         else "That table is no longer open.")

    def invite_joining(self, uid: int, code: str) -> None:
        """A Join through a ranked table's invite link: no queue entry to put
        back, but the join-then-leave rules apply as to any newcomer."""
        self.joining[uid] = (code, None)

    def join_seated(self, uid: int) -> None:
        """The server seated a newcomer at its open table."""
        self.joining.pop(uid, None)

    def join_ended(self, uid: int, *, back_in_line: bool, penalty: bool = False) -> None:
        """A Join that never reached its seat: the owner reclaimed it or the
        table closed (``back_in_line``: the entry returns to the front of the
        queue), the newcomer left (``penalty``), or its socket went."""
        code, e = self.joining.pop(uid, (None, None))
        if code is None:
            return
        if penalty:
            self._bar(uid, code)
        else:
            self.declined.setdefault(uid, set()).add(code)
        if (e is None or not back_in_line or uid in self.entry_of
                or not self._entry_available(e)):
            return
        e.front, e.table_id, e.offer, e.open_codes = True, None, None, []
        if e.bots_at is not None:
            e.bots_at = self.clock() + BOT_FILL_SECS
        self.entries[e.id] = e
        for u in e.members:
            self.entry_of[u] = e.id
        self.seat_waiting()
        if e.table_id is None:
            self._offer_open_tables(self.clock(), quiet={e.id})
            self._send_state(e)
        self._flush_count()
        self.ensure_running()

    def _bar(self, uid: int, code: str) -> None:
        self.barred.setdefault(uid, set()).add(code)
        self.cooldowns[uid] = self.clock() + JOIN_COOLDOWN_SECS

    def left_open_table(self, uid: int, code: str) -> None:
        """A newcomer left the table it joined before its first ranked round
        there: a queue cooldown, and that table is never offered to it
        again."""
        self.joining.pop(uid, None)
        self._bar(uid, code)

    # ------------------------------------------------------------- parties
    def has_party_code(self, code: str) -> bool:
        return code in self.party_codes

    def _new_code(self) -> str:
        return new_code(lambda c: c in self.party_codes or self.room_live(c))

    def code_lookup(self, conn: Conn, msg: dict, user_id: int | None) -> dict:
        """What a typed or linked code names: ``room``, ``party`` or
        ``none``. Read-only and open to guests, so any join box can ask
        before choosing the room or the pair flow. A room wins a code both
        hold, which only codes issued before the shared space can do."""
        key = str(user_id) if user_id is not None else f"socket:{id(conn)}"
        code = normalize_code(msg.get("code"))
        if not self.lookup_limiter.allow(key, self.clock()):
            # ``lookup`` marks this refusal as the lookup's one reply; the
            # queue and pair messages refuse with the same code untagged.
            return {"type": "error", "code": "rate_limited", "lookup": code[:CODE_LEN * 2],
                    "message": "Too many requests; wait a minute."}
        kind = "none"
        if len(code) == CODE_LEN and code.isascii() and code.isalnum():
            if self.room_live(code):
                kind = "room"
            elif code in self.party_codes:
                kind = "party"
        return {"type": "code_kind", "code": code[:CODE_LEN * 2], "kind": kind}

    def _party_payload(self, p: Party, uid: int) -> dict:
        return {"type": "party", "party_id": p.id, "code": p.code,
                "you_lead": p.leader == uid,
                "members": [{"name": p.names[m], "leader": m == p.leader, "you": m == uid}
                            for m in p.members],
                "expires_at": p.idle_since + PARTY_TTL}

    def _send_party(self, p: Party) -> None:
        for m in p.members:
            self._send(m, self._party_payload(p, m))

    def _party_create(self, uid: int) -> None:
        p = self._party(uid)
        if p is None:
            p = Party(id=secrets.token_hex(6), code=self._new_code(), leader=uid,
                      members=[uid], names={uid: self._name(uid)},
                      idle_since=self.clock())
            self.parties[p.id] = p
            self.party_of[uid] = p.id
            self.party_codes[p.code] = p.id
        self._send(uid, self._party_payload(p, uid))

    def _party_join(self, uid: int, msg: dict) -> None:
        code = normalize_code(msg.get("code", ""))
        p = self.parties.get(self.party_codes.get(code, ""))
        if p is None:
            raise QueueError("party_not_found", "No party has that code.")
        if uid in p.members:
            self._send(uid, self._party_payload(p, uid))
            return
        if len(p.members) >= 2:
            raise QueueError("party_full", "That party is full.")
        if uid in self.entry_of:
            raise QueueError("in_queue", "Cancel your search before joining a party.")
        if p.leader in self.entry_of:
            raise QueueError("party_busy", "Your friend is already searching.")
        own = self._party(uid)
        if own is not None:
            if len(own.members) == 2:
                raise QueueError("in_party", "Leave your party first.")
            self._close_party(own, None)
        p.members.append(uid)
        p.names[uid] = self._name(uid)
        p.idle_since = self.clock()
        self.party_of[uid] = p.id
        self._send_party(p)

    def _party_leave(self, uid: int) -> None:
        p = self._party(uid)
        if p is None:
            raise QueueError("not_in_party", "You are not in a party.")
        e = self._entry(uid)
        if e is not None and e.party_id == p.id:
            self._remove(e)
            self._send_state(e)
            self._flush_count()
        self._close_party(p, uid)

    def _close_party(self, p: Party, by: int | None, reason: str = "left") -> None:
        self.parties.pop(p.id, None)
        self.party_codes.pop(p.code, None)
        for m in p.members:
            self.party_of.pop(m, None)
        for m in p.members:
            payload = {"type": "party_closed", "party_id": p.id, "reason": reason}
            if by is not None:
                payload["by"] = p.names.get(by, "Player")
                payload["you"] = m == by
            self._send(m, payload)

    # ---------------------------------------------------------------- time
    async def pump(self) -> None:
        """One pass of everything clock-driven; the background loop calls it
        every PUMP_INTERVAL and tests call it directly."""
        now = self.clock()
        self._drop_inactive()
        self._drop_away(now)
        self._drop_idle(now)
        self._lapse_offers(now)
        for p in list(self.parties.values()):
            queued = any(u in self.entry_of for u in p.members)
            if not queued and now - p.idle_since > PARTY_TTL:
                self._close_party(p, None, reason="expired")
        if now - self._last_tick >= TICK_INTERVAL:
            self._last_tick = now
            await self.tick()
        self._flush_count()

    async def tick(self) -> None:
        """Seat everyone who can sit, offer open tables to who is still
        alone, then start what is due."""
        self.seat_waiting()
        self._offer_open_tables(self.clock())
        await self._start_due()

    def _drop_inactive(self) -> None:
        for e in list(self.entries.values()):
            if not all(self.user_active(u) for u in e.members):
                self._remove(e)
                for u in e.members:
                    self._send(u, self.queue_state(u))

    def _drop_away(self, now: float) -> None:
        """A member whose socket has been gone over its grace takes the entry
        out of the queue, with no cooldown: ``AWAY_SECS`` alone,
        ``TABLE_AWAY_SECS`` at a waiting table."""
        for e in list(self.entries.values()):
            grace = TABLE_AWAY_SECS if e.table_id is not None else AWAY_SECS
            gone = []
            for u in e.members:
                c = self.conns.get(u)
                if c is None or (c.closed and now - (c.closed_at or now) > grace):
                    gone.append(u)
            if not gone:
                continue
            self._remove(e)
            for u in e.members:
                payload = {"type": "queue_removed", "reason": "away",
                           "cooldown_until": None}
                if e.size == 2:
                    payload["by"] = self._name(gone[0])
                self._send(u, payload)
            self._flush_count()

    def _drop_idle(self, now: float) -> None:
        """A seated entry that has not tapped Start and sent nothing for
        ``TABLE_IDLE_SECS`` leaves, with no cooldown. A reconnecting one is
        left to ``_drop_away``."""
        for e in list(self.entries.values()):
            t = self._table(e)
            if (t is None or e.id in t.ready or now - e.active_at < TABLE_IDLE_SECS
                    or not self._entry_available(e)):
                continue
            self._remove(e)
            for u in e.members:
                self._send(u, {"type": "queue_removed", "reason": "idle",
                               "cooldown_until": None})
            self._flush_count()
