"""Matchmaking queue: signed-in players queue alone or as a pair and are
matched into an ordinary rated room.

The queue lives in memory, one per server process. Every state change is a
synchronous method with no ``await`` between the check and the mutation, so
under the asyncio loop a tick and a burst of messages can never seat one
player twice: a match leaves ``matches`` before its room is built, and a
second accept or a ``queue_start_bots`` for it then finds nothing.

The matcher (``tick``, every ``TICK_INTERVAL`` seconds):

1. waiting entries are ordered front-of-line first, then longest wait;
2. the anchor is the first of them; the other entries whose rating lies in
   the anchor's window (``window_for`` its wait) are taken closest first
   until four players are found; a pair prefers another pair, else solos;
3. at the anchor's ``bots_at`` (``BOT_FILL_SECS`` after joining) its match
   is completed with bots. An entry that chose to wait for real players
   (``queue_wait_players``) has no ``bots_at``: it is never bot-filled nor
   taken into another anchor's bot fill, and when it anchors without four
   humans the next entry anchors instead, so it never holds up the line;
4. teams are the valid pairing with the smallest gap in team-average rating
   (``choose_teams``): a pair always sits together, and with bots the humans
   are spread across both teams where possible;
5. each human gets a ``READY_SECS`` ready check. All accept: the room is
   created and started. A decline or a timeout removes the entry that missed
   with a ``COOLDOWN_SECS`` cooldown; the others requeue with their original
   wait, at the front only if every member of that entry had accepted. An
   accept or decline must name the current ``match_id`` and arrive before
   the deadline.

Room creation is the server's job: ``start_room`` is injected, and receives
the four seats in seat order (bots as ``Slot`` with ``user_id=None``).
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

# Loop granularity: deadlines, away drops and the count broadcast are checked
# this often; matching runs every TICK_INTERVAL.
PUMP_INTERVAL = 0.5
TICK_INTERVAL = 2.0
READY_SECS = 10.0
COOLDOWN_SECS = 30.0
# The anchor's wait after which its match is completed with bots.
BOT_FILL_SECS = 60.0
# (wait below, rating half-width): the window widens with the anchor's wait
# and is unlimited once the wait passes the last step.
WINDOW_STEPS: tuple[tuple[float, float], ...] = ((20.0, 100.0), (40.0, 250.0))
AWAY_SECS = 10.0
PARTY_TTL = 300.0
COUNT_DEBOUNCE = 1.0
JOIN_LIMIT = (10, 60.0)      # queue_join per account per window
PARTY_LIMIT = (20, 60.0)     # party_* per account per window
PARTY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PARTY_CODE_LEN = 4

QUEUE_MESSAGES = frozenset({
    "queue_join", "queue_leave", "match_accept", "match_decline",
    "queue_start_bots", "queue_wait_players", "queue_allow_bots", "party_create", "party_invite", "party_join",
    "party_leave",
})
# The only queue message a seated socket may send: leaving a pair.
IN_ROOM_MESSAGES = frozenset({"party_leave"})

# The three ways to split four seats into two teams of two.
PAIRINGS = (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))


def window_for(wait: float) -> float:
    for below, width in WINDOW_STEPS:
        if wait < below:
            return width
    return math.inf


# ------------------------------------------------------------------ model
@dataclass(frozen=True)
class Slot:
    """One seat of a match: a human (``user_id``) or a bot (``None``)."""
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
class Entry:
    id: str
    seq: int
    members: list[int]            # leader first
    leader: int
    member_ratings: dict[int, float]
    since: float
    front: bool = False
    party_id: str | None = None
    match_id: str | None = None
    # When the matcher may complete this entry's match with bots; None while
    # the entry waits for real players only.
    bots_at: float | None = None

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def rating(self) -> float:
        return sum(self.member_ratings.values()) / len(self.member_ratings)


@dataclass
class Match:
    id: str
    entries: list[Entry]
    slots: list[Slot]             # seat order 0..3
    deadline: float
    accepted: set[int] = field(default_factory=set)

    @property
    def humans(self) -> list[int]:
        return [s.user_id for s in self.slots if s.user_id is not None]

    @property
    def bots(self) -> int:
        return sum(1 for s in self.slots if s.is_bot)


def choose_teams(slots: list[Slot]) -> list[Slot]:
    """The four slots in seat order (team 0 at seats 0+2, team 1 at 1+3).

    Of the three pairings, the ones that keep each pair together are valid;
    with bots and at least two humans, the pairings that give each team a
    human are preferred where any exists. The smallest gap in team-average
    rating wins, ties going to the first pairing. The team holding the first
    slot (the anchor) takes seats 0 and 2, humans before bots.
    """
    assert len(slots) == 4

    def together(p) -> bool:
        groups: dict[str, set[int]] = {}
        for t, team in enumerate(p):
            for i in team:
                if slots[i].group is not None:
                    groups.setdefault(slots[i].group, set()).add(t)
        return all(len(ts) == 1 for ts in groups.values())

    def gap(p) -> float:
        means = [sum(slots[i].rating for i in team) / 2 for team in p]
        return abs(means[0] - means[1])

    valid = [p for p in PAIRINGS if together(p)]
    humans = sum(1 for s in slots if not s.is_bot)
    if humans >= 2 and humans < 4:
        spread = [p for p in valid
                  if all(any(not slots[i].is_bot for i in team) for team in p)]
        if spread:
            valid = spread
    best = min(valid, key=gap)
    teams = [sorted(team, key=lambda i: (slots[i].is_bot, i)) for team in best]
    a, b = teams
    return [slots[a[0]], slots[b[0]], slots[a[1]], slots[b[1]]]


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


class Matchmaker:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 rating_of: Callable[[int], Awaitable[float | None]] | None = None,
                 start_room: StartRoom | None = None,
                 user_active: Callable[[int], bool] | None = None,
                 autorun: bool = True) -> None:
        self.clock = clock
        self.rating_of = rating_of or _store_rating
        self.start_room = start_room
        self.user_active = user_active or (lambda uid: not accounts.is_deleted(uid))
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
        self.matches: dict[str, Match] = {}
        self.cooldown: dict[int, float] = {}
        self.parties: dict[str, Party] = {}
        self.party_of: dict[int, str] = {}
        self.party_codes: dict[str, str] = {}
        self.join_limiter = accounts.RateLimiter(*JOIN_LIMIT)
        self.party_limiter = accounts.RateLimiter(*PARTY_LIMIT)
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
            if (not self.entries and not self.matches and not self.parties
                    and self._count_sent == 0):
                return

    def _live(self, uid: int) -> Conn | None:
        c = self.conns.get(uid)
        return c if c is not None and not c.closed else None

    def _available(self, uid: int) -> bool:
        c = self._live(uid)
        return c is not None and not c.in_room

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

    def queue_state(self, uid: int) -> dict:
        e = self._entry(uid)
        if e is None:
            return {"type": "queue_state", "queued": False, "count": self.count()}
        return {"type": "queue_state", "queued": True, "since": e.since,
                "count": self.count(), "front": e.front,
                "party_id": e.party_id, "leader": e.leader == uid,
                "bots_at": e.bots_at, "wait_players": e.bots_at is None}

    def _send_state(self, e: Entry) -> None:
        for u in e.members:
            self._send(u, self.queue_state(u))

    def _remove(self, e: Entry) -> None:
        self.entries.pop(e.id, None)
        for u in e.members:
            if self.entry_of.get(u) == e.id:
                del self.entry_of[u]
        if e.party_id in self.parties:
            self.parties[e.party_id].idle_since = self.clock()

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

    def enter_room(self, conn: Conn) -> None:
        """The socket is joining or holds a seat: no longer a lobby socket,
        and never seated by the matcher while it is in a room."""
        conn.in_room = True
        self.lobby.pop(conn, None)

    def leave_for_room(self, conn: Conn) -> None:
        """The socket took a seat in some other room: its queue entry goes
        (a pending ready check counts as a decline)."""
        uid = conn.user_id
        if uid is None or self.conns.get(uid) is not conn:
            return
        e = self._entry(uid)
        if e is None:
            return
        if e.match_id is not None:
            self._fail_match(self.matches[e.match_id], {uid}, "declined")
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
        self._send(uid, self.queue_state(uid))
        if e.match_id is not None:
            m = self.matches[e.match_id]
            self._send(uid, self._match_payload(m, e))
            self._send(uid, {"type": "match_ready", "match_id": m.id,
                             "accepted": len(m.accepted), "of": len(m.humans)})

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
                elif t == "match_accept":
                    await self._accept(user_id, msg)
                elif t == "match_decline":
                    self._decline(user_id, msg)
                elif t == "queue_start_bots":
                    await self._start_bots(user_id)
                elif t in ("queue_wait_players", "queue_allow_bots"):
                    self._set_bot_fill(user_id, t == "queue_allow_bots")
        except QueueError as err:
            self._error(conn, err)
        self.ensure_running()

    async def _join(self, conn: Conn, uid: int, msg: dict) -> None:
        if uid in self.entry_of:              # already queued: this socket holds it now
            self._resync(uid)
            return
        now = self.clock()
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
        until = max((self.cooldown.get(m, 0.0) for m in members), default=0.0)
        if until > now:
            raise QueueError("cooldown", "You can queue again shortly.",
                             cooldown_until=until, cooldown_secs=until - now)
        for m in members:
            if m != uid and not self._available(m):
                raise QueueError("partner_unavailable", "Your partner is not in the lobby.")
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
        self._send_state(e)
        self._flush_count()

    def _leave(self, uid: int) -> None:
        e = self._entry(uid)
        if e is None:
            self._send(uid, self.queue_state(uid))
            return
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can cancel.")
        if e.match_id is not None:
            self._fail_match(self.matches[e.match_id], {uid}, "declined")
            return
        self._remove(e)
        self._send_state(e)
        self._flush_count()

    def _set_bot_fill(self, uid: int, allow: bool) -> None:
        """Turn the entry's bot fill off (wait for real players) or back on,
        due ``BOT_FILL_SECS`` from now. Only the matcher reads ``bots_at``, so
        the entry keeps its wait, its window and its place in line."""
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can change this.")
        if allow:
            if e.bots_at is None:
                e.bots_at = self.clock() + BOT_FILL_SECS
        else:
            e.bots_at = None
        self._send_state(e)

    def _current_match(self, uid: int, msg: dict) -> Match:
        """The ready check an accept or decline answers. The deadline is
        checked here, not left to the pump, so a late answer cannot act on an
        expired check; and the answer must name the exact current match, so a
        delayed answer to an earlier check cannot land on its replacement."""
        e = self._entry(uid)
        m = self.matches.get(e.match_id) if e is not None and e.match_id else None
        if m is None:
            raise QueueError("no_match", "There is no ready check for you.")
        if self.clock() >= m.deadline:
            self._expire(m)
            raise QueueError("stale_match", "That ready check is over.")
        if msg.get("match_id") != m.id:
            raise QueueError("stale_match", "That ready check is over.")
        return m

    async def _accept(self, uid: int, msg: dict) -> None:
        m = self._current_match(uid, msg)
        m.accepted.add(uid)
        humans = m.humans
        if len(m.accepted) < len(humans):
            for u in humans:
                self._send(u, {"type": "match_ready", "match_id": m.id,
                               "accepted": len(m.accepted), "of": len(humans)})
            return
        await self._launch(m)

    def _decline(self, uid: int, msg: dict) -> None:
        m = self._current_match(uid, msg)
        keep = bool(msg.get("keep_waiting")) and m.bots > 0
        self._fail_match(m, {uid}, "declined", keep_waiting=keep)

    def _fail_match(self, m: Match, missers: set[int], reason: str, *,
                    keep_waiting: bool = False, away: frozenset[int] | set[int] = frozenset()) -> None:
        """End a ready check that not everyone accepted. An entry with a
        misser leaves the queue: with a cooldown for every member, or with
        none when each misser's socket was gone (``away``) or the misser
        chose to keep waiting for people (that entry restarts its wait). The
        other entries requeue with their original wait; only an entry whose
        every member accepted goes to the front, so a player who had not
        answered yet is neither rewarded nor penalised."""
        self.matches.pop(m.id, None)
        now = self.clock()
        for e in m.entries:
            e.match_id = None
            missed = [u for u in e.members if u in missers]
            if not missed:
                e.front = all(u in m.accepted for u in e.members)
                for u in e.members:
                    self._send(u, {"type": "match_cancelled", "match_id": m.id,
                                   "reason": "player_missed"})
                self._send_state(e)
                continue
            if keep_waiting:
                e.front, e.since = False, now
                e.bots_at = now + BOT_FILL_SECS
                for u in e.members:
                    self._send(u, {"type": "match_cancelled", "match_id": m.id,
                                   "reason": "keep_waiting"})
                self._send_state(e)
                continue
            self._remove(e)
            no_penalty = all(u in away for u in missed)
            until = None if no_penalty else now + COOLDOWN_SECS
            for u in e.members:
                if until is not None:
                    self.cooldown[u] = until
                payload = {"type": "queue_removed",
                           "reason": "away" if no_penalty else reason,
                           "cooldown_until": until, "match_id": m.id}
                if e.size == 2:
                    payload["by"] = self._name(missed[0])
                self._send(u, payload)
        self._flush_count()

    def _match_payload(self, m: Match, e: Entry) -> dict:
        return {"type": "match", "match_id": m.id, "deadline": m.deadline,
                "deadline_in": max(0.0, m.deadline - self.clock()),
                "size": len(m.humans), "bots": m.bots, "party_id": e.party_id}

    async def _launch(self, m: Match) -> None:
        """Everyone accepted: build the room. Synchronous up to the
        ``start_room`` call, so the match is gone before anything yields."""
        self.matches.pop(m.id, None)
        gone = {u for u in m.humans if not self._available(u)}
        if gone:
            self._fail_match(m, gone, "missed", away=gone)
            return
        names = [s.name for s in m.slots if not s.is_bot]
        for e in m.entries:
            self._remove(e)
        for u in m.humans:
            self._send(u, {"type": "match_ready", "match_id": m.id,
                           "accepted": len(names), "of": len(names), "names": names})
        self._flush_count()
        conns = {u: self.conns[u] for u in m.humans}
        try:
            await self._start(m.id, m.slots, conns)
        except Exception:          # noqa: BLE001 - players go back, never stranded
            log.exception("matched room failed to start")
            for e in m.entries:
                e.match_id, e.front = None, True
                self.entries[e.id] = e
                for u in e.members:
                    self.entry_of[u] = e.id
                    self._send(u, {"type": "match_cancelled", "match_id": m.id,
                                   "reason": "server_error"})
                self._send_state(e)
            self._flush_count()

    async def _start(self, match_id: str | None, slots: list[Slot],
                     conns: dict[int, Conn]) -> Any:
        if self.start_room is None:
            raise RuntimeError("no room factory")
        return await self.start_room(match_id, slots, conns)

    async def _start_bots(self, uid: int) -> None:
        e = self._entry(uid)
        if e is None:
            raise QueueError("not_queued", "Queue first.")
        if e.match_id is not None:
            raise QueueError("match_pending", "A match was found; answer the ready check.")
        if e.leader != uid:
            raise QueueError("not_leader", "Only the party leader can start with bots.")
        for m in e.members:
            if not self._available(m):
                raise QueueError("partner_unavailable", "Your partner is not in the lobby.")
        self._remove(e)
        self._flush_count()
        bot = Slot(None, "", ratings.BOT_RATING)
        people = [Slot(u, self._name(u), e.member_ratings[u], e.id) for u in e.members]
        slots = ([people[0], bot, bot, bot] if len(people) == 1
                 else [people[0], bot, people[1], bot])
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

    # ------------------------------------------------------------- parties
    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(PARTY_CODE_ALPHABET) for _ in range(PARTY_CODE_LEN))
            if code not in self.party_codes:
                return code

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
        code = str(msg.get("code", "")).strip().upper()
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
            if e.match_id is not None:
                self._fail_match(self.matches[e.match_id], {uid}, "declined")
            else:
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
        for m in list(self.matches.values()):
            if now >= m.deadline:
                self._expire(m)
        self._drop_away(now)
        for p in list(self.parties.values()):
            queued = any(u in self.entry_of for u in p.members)
            if not queued and now - p.idle_since > PARTY_TTL:
                self._close_party(p, None, reason="expired")
        if now - self._last_tick >= TICK_INTERVAL:
            self._last_tick = now
            self.tick()
        self._flush_count()

    def _expire(self, m: Match) -> None:
        """The ready check's deadline passed: everyone who has not accepted
        missed it."""
        missers = {u for u in m.humans if u not in m.accepted}
        away = {u for u in missers if not self._available(u)}
        self._fail_match(m, missers, "missed", away=away)

    def _drop_inactive(self) -> None:
        for e in list(self.entries.values()):
            if e.match_id is None and not all(self.user_active(u) for u in e.members):
                self._remove(e)
                for u in e.members:
                    self._send(u, self.queue_state(u))

    def _drop_away(self, now: float) -> None:
        """A member whose socket has been gone over AWAY_SECS takes the entry
        out of the queue, with no cooldown. A ready check in progress is left
        to its own deadline."""
        for e in list(self.entries.values()):
            if e.match_id is not None:
                continue
            gone = []
            for u in e.members:
                c = self.conns.get(u)
                if c is None or (c.closed and now - (c.closed_at or now) > AWAY_SECS):
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

    def tick(self) -> list[Match]:
        """Form every match the anchor rule allows now."""
        now = self.clock()
        pool = [e for e in self.entries.values()
                if e.match_id is None and all(self._available(u) for u in e.members)]
        pool.sort(key=lambda e: (not e.front, e.since, e.seq))
        formed: list[Match] = []
        # Entries waiting for real players that could not anchor a match this
        # tick: still candidates for later anchors' human matches.
        passed: list[Entry] = []
        while len(passed) < len(pool):
            anchor = pool[len(passed)]
            wait = now - anchor.since
            width = window_for(wait)
            others = sorted(
                (e for e in pool if e is not anchor
                 and abs(e.rating - anchor.rating) <= width),
                key=lambda e: (abs(e.rating - anchor.rating), not e.front, e.since, e.seq))
            picked = self._pick(anchor, others, fill=False)
            if picked is None and anchor.bots_at is not None and now >= anchor.bots_at:
                picked = self._pick(anchor, [e for e in others if e.bots_at is not None],
                                    fill=True)
            if picked is None:
                if anchor.bots_at is not None:
                    break
                passed.append(anchor)
                continue
            formed.append(self._open_match(picked, now))
            pool = [e for e in pool if e not in picked]
            passed = [e for e in passed if e not in picked]
        return formed

    @staticmethod
    def _pick(anchor: Entry, others: list[Entry], fill: bool) -> list[Entry] | None:
        if anchor.size == 2:
            pairs = [o for o in others if o.size == 2]
            if pairs:
                return [anchor, pairs[0]]
        chosen, total = [anchor], anchor.size
        for o in others:
            if total + o.size <= 4:
                chosen.append(o)
                total += o.size
            if total == 4:
                return chosen
        return chosen if fill else None

    def _open_match(self, picked: list[Entry], now: float) -> Match:
        slots = [Slot(u, self._name(u), e.member_ratings[u], e.id if e.size == 2 else None)
                 for e in picked for u in e.members]
        while len(slots) < 4:
            slots.append(Slot(None, "", ratings.BOT_RATING))
        m = Match(id=secrets.token_hex(6), entries=picked, slots=choose_teams(slots),
                  deadline=now + READY_SECS)
        self.matches[m.id] = m
        for e in picked:
            e.match_id = m.id
            for u in e.members:
                self._send(u, self._match_payload(m, e))
        return m
