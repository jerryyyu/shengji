"""FastAPI WebSocket server: rooms, seats, humans + bots, per-seat state."""

from __future__ import annotations

import asyncio
import copy
import errno
import json
import logging
import random
import re
import time
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

import os
import secrets

from ..ai.heuristic import HeuristicBot
from ..ai.registry import make_bot
from ..engine.cards import RANKS
from ..engine.game import Game
from ..engine.legal import IllegalPlay
from ..engine import combos
from ..engine.round import Round, actual_play_after
from . import accounts, matchmaking, ratings, reports, saved_games, support
from .human_eval import HUMAN_SEATS, HumanEvaluationContext
from .model_serving import run_model_search
from .room_experiments import SHORTLIST_TEST_ROOMS, TestRoomUnavailable


#: the pv-search DIAGNOSTIC flags the game server refuses outright (#707 S16:
#: perfect-information worlds exist only inside the screen harness)
_PV_DIAGNOSTIC_FLAGS = ("SHENGJI_PV_ORACLE_WORLDS",
                        # its soft variants (#707 S17 step 3)
                        "SHENGJI_PV_ORACLE_MIX_K", "SHENGJI_PV_ORACLE_PIN_Q")


def _refuse_pv_diagnostics(environ=None) -> None:
    """The served process REFUSES a pv-search diagnostic flag at import, before
    any room can build a bot: ``SHENGJI_PV_ORACLE_WORLDS`` prices plays over
    the TRUE hidden hands and belongs to `train.cwv_shortlist_screen` only
    (`train.pv_search_policy`: the registry factory refuses it too, without
    the harness's hook).  Unset, empty and ``0`` are off; anything else raises."""
    env = os.environ if environ is None else environ
    for flag in _PV_DIAGNOSTIC_FLAGS:
        if env.get(flag) not in (None, "", "0"):
            raise RuntimeError(f"{flag}={env.get(flag)!r}: a screen-harness diagnostic, "
                               "never served; unset it before starting the game server")


_refuse_pv_diagnostics()


def _fast_active() -> bool:
    """True only if the compiled decompose is the one in use."""
    try:
        from ..engine import combos, fast
        return bool(fast.HAVE_FAST and combos.decompose is fast.decompose)
    except Exception:
        return False


def _pv_search_health() -> dict | None:
    """The served policy/value-search package (#585), by the SHA256 of the file on disk;
    ``None`` unless the pv-search mode is configured."""
    path = os.environ.get("SHENGJI_PV_CKPT")
    if not path:
        return None
    try:
        from ..ai.cwv_policy import file_sha256
        from ..train.pv_search_policy import DEFAULTS, latency_switches
        return {"sha256": file_sha256(path),
                "worlds": int(os.environ.get("SHENGJI_PV_WORLDS", DEFAULTS["worlds"])),
                "candidates": int(os.environ.get("SHENGJI_PV_CANDIDATES", DEFAULTS["candidates"])),
                "budget_seconds": os.environ.get("SHENGJI_PV_SERVING_BUDGET_SECONDS"),
                "bury_arm": os.environ.get("SHENGJI_PV_BURY_ARM") or "heuristic",
                "bury_budget_seconds": os.environ.get("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"),
                # read from the same process environment the bot factory reads them from;
                # they enter no name, so this is where a deploy shows them
                "latency_switches": latency_switches()}
    except Exception as exc:                # noqa: BLE001 - health must answer
        return {"error": f"{type(exc).__name__}: {exc}"}


def _prior_health() -> dict | None:
    """The served policy prior, by the SHA256 of the file actually on disk.

    ``None`` when no prior is bound. The hash is what a rollback is checked
    against (DEPLOY.md), so it is read from the file, not echoed from env.
    """
    path = os.environ.get("SHENGJI_CWV_PRIOR_CKPT")
    if not path:
        return None
    try:
        from ..ai.cwv_policy import file_sha256
        from ..train.cwv_shortlist import (SHORTLIST_PRIOR_THRESHOLD,
                                           SHORTLIST_PRIOR_TOP)
        return {"sha256": file_sha256(path),
                "threshold": int(os.environ.get("SHENGJI_CWV_PRIOR_THRESHOLD",
                                                SHORTLIST_PRIOR_THRESHOLD)),
                "top": int(os.environ.get("SHENGJI_CWV_PRIOR_TOP", SHORTLIST_PRIOR_TOP))}
    except Exception as exc:                # noqa: BLE001 - health must answer
        return {"error": f"{type(exc).__name__}: {exc}"}


BOT_DELAY = 0.7
CHAT_KEEP = 50        # scrollback kept per room (in memory, like game state)
CHAT_MAX_LEN = 300    # per-message cap
DEAL_DELAY = 0.15          # seconds between dealt cards (~15s full deal)
DECLARE_GRACE = 5.0        # window after the deal; extended on new declarations
DECLARE_EXTEND = 3.0
ROOM_TTL = 300.0           # grace before deleting a room with no humans connected
TAKEOVER_AFTER = 30.0      # bot plays for a disconnected human after this long
EMPTY_ROOM_BOT_DELAY = 10.0  # least seconds per bot move while no human is connected
EMPTY_ROOM_POLL = 0.25     # how often a long empty-room wait re-checks for a human
# Move timer (rooms with ``move_timer`` on, which today means ranked rooms):
# a connected human has MOVE_TIMER seconds for each bury, play and round-end
# Next; at zero the bot makes that one decision. AWAY_IN_A_ROW consecutive
# timeouts, or AWAY_PER_ROUND in one round, mark the seat away: the bot then
# plays every decision for it until the player is back.
MOVE_TIMER = 60.0
AWAY_IN_A_ROW = 2
AWAY_PER_ROUND = 3
MOVE_TIMER_POLL = 1.0      # watchdog period in a room with the move timer
# Game logs (full hands!). Prod sets SHENGJI_LOG_DIR=/data/logs and those
# files are fetched into logs/ as the HUMAN CORPUS, so a dev server must not
# write there: local multiplayer testing would otherwise be mined as real
# human play (Jerry's VKHW/DPMV test games, 2026-08-03).
LOG_DIR = Path(os.environ.get(
    "SHENGJI_LOG_DIR",
    Path(__file__).resolve().parents[3] / "logs" / "local"))
app = FastAPI(title="shengji")

rooms: dict[str, "Room"] = {}


def _iso_utc(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _errno_name(exc: OSError) -> str | None:
    """``ENOSPC``/``EROFS``/``EACCES`` for an errno the platform names, else None."""
    if exc.errno is None:
        return None
    return errno.errorcode.get(exc.errno)


@dataclass
class Activity:
    """Process-lifetime counters reported by ``/healthz``.

    From outside, a server whose room log silently stopped reaching disk looks
    exactly like a server nobody is playing on: both leave no new file.  These
    counters tell the two apart without opening a log.  ``games_started``
    moves on the game path when a table starts; ``rounds_recorded`` moves only
    when that round's ``round_start`` record reached disk; a gap between them
    is a write failure, and ``last_record_failure`` names its class and errno.

    Plain integers, mutated only on the event loop (every ``log_event`` call
    runs there).  They observe the room path and never gate it: a counter
    cannot raise into a game.  Nothing here carries a room code, a path or a
    record payload, so the unauthenticated health endpoint may show it.
    """
    rooms_created: int = 0
    games_started: int = 0
    rounds_recorded: int = 0
    records_written: int = 0
    record_write_failures: int = 0
    # saved-game link writes that failed; the game went on without them
    account_link_failures: int = 0
    last_record_write_t: float | None = None
    last_record_failure: dict | None = None

    def record_written(self, kind: str) -> None:
        self.records_written += 1
        self.last_record_write_t = time.time()
        if kind == "round_start":
            self.rounds_recorded += 1

    def record_failed(self, exc: OSError) -> None:
        self.record_write_failures += 1
        self.last_record_failure = {
            "at": _iso_utc(time.time()),
            "class": type(exc).__name__,
            "errno": exc.errno,
            "errno_name": _errno_name(exc),
        }

    def account_link_failed(self) -> None:
        self.account_link_failures += 1

    def health(self) -> dict:
        return {
            "rooms_created": self.rooms_created,
            "games_started": self.games_started,
            "rounds_recorded": self.rounds_recorded,
            "records_written": self.records_written,
            "record_write_failures": self.record_write_failures,
            "account_link_failures": self.account_link_failures,
            "last_record_write": (None if self.last_record_write_t is None
                                  else _iso_utc(self.last_record_write_t)),
            "last_record_failure": (None if self.last_record_failure is None
                                    else dict(self.last_record_failure)),
        }


ACTIVITY = Activity()


@dataclass
class Seat:
    name: str
    is_bot: bool = False
    bot_announced: bool = False
    # Monotonic stamp of the disconnect, independent of the event loop, so the
    # takeover countdown can be computed anywhere (loop.time() is only
    # meaningful inside a running loop).
    left_at: float | None = None  # bot-takeover announced for this absence
    ws: WebSocket | None = None
    connected: bool = False
    queue: asyncio.Queue | None = None   # outbound messages; writer task drains
    writer: asyncio.Task | None = None
    # Why this seat's writer stopped, if it stopped on an exception. A dead
    # writer is otherwise INVISIBLE: the seat stays connected, enqueue keeps
    # accepting, and the client simply never receives another frame (#628).
    writer_error: str | None = None
    # How the writer exited, if it exited at all: None means it is STILL
    # RUNNING, "cancelled" means a routine displacement or detach, "error"
    # means see writer_error. Without this, a None writer_error was ambiguous
    # between "never died" and "died by cancellation", so it ruled nothing out
    # (Codex, reviewing #640).
    writer_exit: str | None = None
    last_seen: float = 0.0               # loop time of last disconnect
    # Connection GENERATION. A dropped socket's `finally` can run long after a
    # newer socket has resumed the seat; without this the old cleanup detaches
    # the LIVE connection and strands the player (Codex ship gate P0-1).
    # Every attach bumps it; a detach only applies to the generation it owns.
    gen: int = 0
    # Opaque resume token: names are not identity. Two people called "jerry",
    # or one person on two devices, must not be able to seize each other's
    # seat, and a returning player must be able to resume even while their
    # stale socket is still open.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(12))
    # Assigned only by a future reviewed HUMAN-C1 ingress.  It is server-only;
    # ordinary rooms and client state never use or expose it.
    evaluation_participant_id: str | None = None
    # The signed-in account (accounts.users.id) whose cookie the socket that
    # took this seat carried; None for a guest. Server-only: it enters no
    # state frame, no log record and no game decision.
    user_id: int | None = None
    # Who holds this seat as the queue knows them: the account id, or a
    # guest's negative device id (``guest_queue_id``). Set in matched rooms
    # only, and never stored as ``user_id``. Server-only.
    queue_id: int | None = None
    # The socket's device key (``device_key``): one device holds one human
    # seat at a matched or ranked table. Server-only; never logged or sent.
    device: str | None = None
    # Set when the host removed this occupant before the game: the seat is no
    # longer in the room, and the socket that held it returns to the lobby.
    removed: bool = False
    # The connection generation whose socket this seat's account left from
    # another of its sockets: that socket returns to the lobby on its next
    # frame, as a removed one does.
    left_gen: int | None = None
    # Move timer state; untouched in a room without the move timer.
    # ``turn_started`` is the ``now()`` at which this seat began owing the
    # current decision (None when it owes none). A disconnect does not reset
    # it, so a reconnect cannot buy a fresh minute.
    turn_started: float | None = None
    timeouts_in_row: int = 0
    timeouts_in_round: int = 0
    # The bot plays every decision for this seat until the player is back.
    away: bool = False
    # The round in which this seat went away (None while it is not away): a
    # seat away for a whole round may be offered to newcomers.
    away_since: int | None = None
    # Open tables: the round a newcomer took this seat mid-way (unranked
    # for them; None once a round starts with them seated), and the bot
    # name the seat goes back to if they leave during it.
    joined_round: int | None = None
    bot_name: str | None = None


@dataclass
class Room:
    code: str
    # Index = seat position. Before the game starts a position may be None
    # (empty: a person left, was removed or moved away), never as the last
    # entry; start_game seats a bot in every empty position, so once a game
    # exists the list is four Seats and nothing past the lobby sees a None.
    seats: list[Seat | None] = field(default_factory=list)
    host: int = 0
    game: Game | None = None
    # Rank both teams start at. Chosen by the creator; applied when the game
    # starts, so it is visible in the lobby before anyone commits to a seat.
    start_level: str = RANKS[0]
    ready: set[int] = field(default_factory=set)  # seats confirming round end
    chat_seq: int = 0            # monotonic per-room chat id
    chat: list[dict] = field(default_factory=list)  # last CHAT_KEEP messages
    ids: list[dict[int, str]] = field(default_factory=lambda: [{} for _ in range(4)])
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # None builds the served policy (SHENGJI_BOT) in `__post_init__` with this
    # room's own seed, so rooms do not share one sampler stream
    bot: HeuristicBot | None = None
    # the seed that bot was built with (None for a bot passed in); every
    # round_start record carries it, so a room's decisions can be replayed
    bot_seed: int | None = None
    bot_task: asyncio.Task | None = None
    deal_task: asyncio.Task | None = None
    watchdog_task: asyncio.Task | None = None
    cleanup_task: asyncio.Task | None = None
    # How the room's deal/bot tasks ENDED, keyed by attribute name (#628).
    # ``run_deal`` and ``pump_bots`` are the only producers of state frames
    # between start_game and the first human turn; a task that died on an
    # exception was otherwise silent (no handler, no done callback; asyncio
    # reports an unretrieved exception only at garbage collection, which the
    # test fixture's cancel-on-teardown never reaches). Absent key: the task
    # was never spawned or is still running -- read the task for which.
    task_exits: dict[str, str] = field(default_factory=dict)
    # Ordinary rooms use LOG_DIR.  A reviewed human evaluation must provide a
    # different root plus an immutable server-only identity; no websocket path
    # can construct one yet.
    log_dir: Path | None = None
    # Bound warnings during a persistent disk failure without stopping retries.
    _log_error_reported: bool = field(default=False, init=False, repr=False)
    evaluation: HumanEvaluationContext | None = None
    # Any missing evaluation event destroys the assigned session's evidence
    # chain.  Keep the room terminally unusable rather than allowing a retry or
    # subsequent play to create an apparently complete but selectively logged
    # HUMAN-C1 block.
    evaluation_invalidated: bool = False
    # Fixed at creation, never set from join/action messages. Not HUMAN-C1.
    experimental_policy: str | None = None
    # The saved-game link of the running game (``saved_games.GameLink``), or
    # None. Server-only: it enters no state frame and no log record.
    saved_game: Any = field(default=None, init=False, repr=False)
    # The running game's rating state (``ratings.RoomRatings``), or None.
    # Server-only: a state frame carries only the receiving seat's own line.
    ratings: Any = field(default=None, init=False, repr=False)
    # Built by the matchmaking queue rather than by a player's create_room.
    matched: bool = False
    # A created room's Ranked switch (``set_ranked``): its rounds are rated
    # (``ratings.ranked``). Off at creation; the host may change it only
    # before the game starts. A matched room is always ranked and keeps this
    # off.
    ranked: bool = False
    # The waiting table this matched room was formed from (its id; None for
    # a game one entry started alone with bots) and how many people sat at
    # it. Server-only: what an open-table offer reads to find bot seats.
    waiting_table: str | None = field(default=None, repr=False)
    table_humans: int = field(default=0, repr=False)
    # Per-decision clock for connected humans (MOVE_TIMER). On for ranked
    # rooms; a casual room keeps it off.
    move_timer: bool = False
    # Which decision the seats' ``turn_started`` clocks belong to.
    timer_key: tuple | None = field(default=None, init=False, repr=False)
    # A matched room whose start failed and was unwound: no socket may act
    # in it, and a receive loop still holding it drops it.
    aborted: bool = field(default=False, init=False, repr=False)
    # Open tables (matched rooms): whether a newcomer may be offered a seat
    # (any human at the table can switch it off), the Joins waiting for their
    # handover by seat, and who was seated at this round's end (they play
    # from the next round). Server-only apart from the notices in a frame.
    allow_joiners: bool = True
    pending_joins: dict = field(default_factory=dict, repr=False)
    round_end_joins: dict = field(default_factory=dict, repr=False)
    # Every human is gone and a round in play still owes a rating: the bots
    # finish that round without pacing and the room closes at its end.
    closing: bool = field(default=False, init=False, repr=False)
    # The cheap bot that plays a closing room's round: nobody is watching, so
    # no model search runs for it. Built on first use.
    closing_bot: Any = field(default=None, init=False, repr=False)
    # The created room's own move-timer setting, kept while Ranked forces the
    # timer on so switching Ranked off restores it.
    casual_move_timer: bool | None = field(default=None, init=False, repr=False)
    # A table continuing a saved game: the ``saved_games.resume_point`` its
    # creator's account was given, applied once at ``start_game`` (both
    # teams' levels and the first banker). Server-only.
    resume: dict | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.bot is None:
            if self.bot_seed is None:
                self.bot_seed = secrets.randbits(31)
            self.bot = make_bot(os.environ.get("SHENGJI_BOT", "mc"), seed=self.bot_seed)
        if self.log_dir is None:
            self.log_dir = LOG_DIR
        else:
            self.log_dir = Path(self.log_dir)
        if self.experimental_policy is not None:
            if self.experimental_policy != "w32" or self.evaluation is not None:
                raise ValueError("invalid experimental room context")
            test_root, ordinary_root = self.log_dir.resolve(), LOG_DIR.resolve()
            if (test_root == ordinary_root or test_root.is_relative_to(ordinary_root)
                    or ordinary_root.is_relative_to(test_root)):
                raise ValueError("test rooms require a disjoint log root")
        if self.evaluation is not None:
            evaluation_root = self.log_dir.resolve()
            training_root = LOG_DIR.resolve()
            if (evaluation_root == training_root
                    or evaluation_root.is_relative_to(training_root)
                    or training_root.is_relative_to(evaluation_root)):
                raise ValueError(
                    "human evaluation rooms require a disjoint log root")
        if (self.evaluation is not None
                and getattr(self.bot, "policy_name", None)
                != self.evaluation.active_policy):
            raise ValueError(
                "human evaluation policy identity does not match room bot")

    @property
    def round(self) -> Round | None:
        return self.game.round if self.game else None

    def log_event(self, kind: str, **data) -> int | None:
        """Append one JSONL record; returns the byte offset it starts at, or
        None when it did not reach disk.

        Ordinary game logging remains best-effort.  Evaluation logging fails
        closed because continuing an unrecorded assigned session would create
        evidence that cannot be audited.
        """
        offset: int | None = None
        try:
            assert self.log_dir is not None
            self.log_dir.mkdir(parents=True, exist_ok=True)
            rec = {"t": round(time.time(), 3), "room": self.code,
                   "round": self.game.round_no if self.game else 0,
                   "e": kind, **data}
            if self.experimental_policy is not None:
                rec["experimental_policy"] = self.experimental_policy
                rec["policy"] = self.bot.policy_name
                rec["training_excluded"] = True
            if self.evaluation is not None:
                if kind == "chat":
                    rec = {
                        "t": rec["t"], "room": rec["room"],
                        "round": rec["round"], "e": kind,
                        "seat": data.get("seat"), "content_recorded": False,
                    }
                rec["experiment"] = self.evaluation.log_payload()
                rec["training_excluded"] = True
            # Binary append: the offset is an exact byte position, and the
            # bytes are the same as a text write (json.dumps emits ASCII).
            with open(self.log_dir / f"{self.code}.jsonl", "ab") as f:
                start = f.seek(0, os.SEEK_END)
                f.write((json.dumps(rec) + "\n").encode("utf-8"))
            offset = start
        except OSError as exc:
            ACTIVITY.record_failed(exc)
            if self.saved_game is not None:
                saved_games.log_failed(self)
            if self.evaluation is not None:
                self.evaluation_invalidated = True
                raise  # evidence rooms fail closed instead of silently playing
            if not self._log_error_reported:
                self._log_error_reported = True
                # Do not send event payloads, chat, or exception paths to
                # stderr.  The class alone cannot separate a full disk from a
                # read-only mount or an I/O error; the errno can.
                logging.warning("room %s event logging failed (%s errno=%s); "
                                "gameplay continues, records may be missing",
                                self.code, type(exc).__name__,
                                _errno_name(exc) or exc.errno)
        else:
            ACTIVITY.record_written(kind)
        return offset

    # ------------------------------------------------------------- id mapping
    def index_round(self) -> None:
        rnd = self.round
        assert rnd is not None
        self.ids = [{} for _ in range(4)]  # filled card-by-card as the deal runs
        self._kitty_ids = {100 + i: rnd.deck[100 + i] for i in range(8)}
        self._kitty_given = False

    def mint_card_id(self, seat: int, code: str) -> int:
        """Fresh id for a card the id map is missing (desync recovery)."""
        nid = max([*self.ids[seat], 199]) + 1
        self.ids[seat][nid] = code
        return nid

    def sync_kitty(self) -> None:
        rnd = self.round
        if rnd and rnd.phase in ("bury", "play", "round_end") and not self._kitty_given:
            assert rnd.banker is not None
            self.ids[rnd.banker].update(self._kitty_ids)
            self._kitty_given = True

    def codes_for(self, seat: int, card_ids: list[int]) -> list[str]:
        try:
            return [self.ids[seat][i] for i in card_ids]
        except KeyError:
            raise IllegalPlay("Unknown card id.")

    def remove_ids(self, seat: int, card_ids: list[int]) -> None:
        for i in card_ids:
            self.ids[seat].pop(i, None)

    def remove_codes(self, seat: int, codes: list[str]) -> None:
        pool = dict(self.ids[seat])
        for code in codes:
            cid = next(i for i, c in pool.items() if c == code)
            del pool[cid]
            del self.ids[seat][cid]

    def ids_for_codes(self, seat: int, codes: list[str]) -> list[int]:
        pool = dict(self.ids[seat])
        out = []
        for code in codes:
            cid = next(i for i, c in pool.items() if c == code)
            out.append(cid)
            del pool[cid]
        return out


# --------------------------------------------------------------------- state
def play_shape(cards: list[str], ordering) -> str:
    """What the play IS, decided by the engine — "single" | "pair" |
    "tractor" | "throw".

    The voice announcer used to infer this client-side ("4+ cards, all even
    counts => tractor"), which called a two-PAIR throw a 拖拉机 (Jerry,
    2026-08-04). A tractor needs CONSECUTIVE pairs in one effective suit, and
    consecutiveness depends on the trump ordering — trump-rank cards and
    jokers sit outside their printed ranks — which the client cannot see.
    """
    n = len(cards)
    if n == 0:
        return "throw"
    if n == 1:
        return "single"
    if ordering is None:
        return "throw"
    suits = {ordering.eff_suit(c) for c in cards}
    if len(suits) > 1:
        return "throw"          # multi-suit is always a throw
    dec = combos.decompose(list(cards), ordering)
    if len(dec.components) != 1:
        return "throw"          # e.g. 55 + 99: two components, not a run
    comp = dec.components[0]
    if comp.pair_len == 1 and comp.size == 2:
        return "pair"
    if comp.pair_len >= 2:
        return "tractor"
    return "throw"


def trick_json(t, ordering=None) -> dict | None:
    if t is None:
        return None
    d = {"leader": t.leader,
         "plays": [{"seat": p.seat, "cards": p.cards,
                    "shape": play_shape(p.cards, ordering)}
                   for p in t.plays]}
    if t.winner is not None:
        d["winner"] = t.winner
        d["points"] = t.points
    return d


def now() -> float:
    """The single clock for takeover timing.

    One seam, so tests can advance time instead of sleeping 30 seconds, and
    so the countdown the UI shows and the deadline the watchdog enforces can
    never disagree (they were on different clocks: loop.time() vs monotonic).
    """
    return time.monotonic()


def _reserved(room: Room, seat: int) -> bool:
    """Is this dropped seat still exclusively its owner's?

    HOUSE RULE (adopted explicitly, 2026-08-04): ONE window, TAKEOVER_AFTER
    long, serves both purposes — the bot does not act and nobody else may
    claim the seat until it expires. Codex offered the alternative of a prompt
    bot plus a separate reservation clock; a single deadline was chosen so the
    countdown a player sees is the same number the server enforces. Before
    this, a seat was claimable the instant its player blipped.
    """
    sd = room.seats[seat]
    if sd.is_bot or sd.connected or sd.left_at is None:
        return False
    return (now() - sd.left_at) < TAKEOVER_AFTER


def _controller(room: Room, seat: int) -> str:
    sd = room.seats[seat]
    if sd.is_bot:
        return "bot"
    return "human" if sd.connected else "bot_cover"


def _takeover_in(room: Room, seat: int) -> float | None:
    """Seconds before the bot plays for a disconnected human (None if N/A)."""
    sd = room.seats[seat]
    if sd.is_bot or sd.connected or sd.bot_announced:
        return None
    if sd.left_at is None:
        return None
    return round(max(0.0, TAKEOVER_AFTER - (now() - sd.left_at)), 1)


def _decision_key(room: Room) -> tuple | None:
    """Identity of the decision the table is waiting on: a new key restarts
    every owing seat's move clock."""
    game, rnd = room.game, room.round
    if game is None or rnd is None or game.game_over:
        return None
    if rnd.phase == "round_end":
        return (game.round_no, "round_end")
    if rnd.phase == "bury":
        return (game.round_no, "bury", rnd.turn)
    if rnd.phase == "play":
        return (game.round_no, "play", rnd.turn, len(rnd.history),
                len(rnd.trick.plays) if rnd.trick else 0)
    return None


def _owing_seats(room: Room) -> set[int]:
    """Human seats that owe the current decision, connected or not."""
    key = _decision_key(room)
    if key is None:
        return set()
    if key[1] == "round_end":
        return {i for i, sd in enumerate(room.seats)
                if not sd.is_bot and i not in room.ready}
    seat = room.round.turn
    if seat is None or room.seats[seat].is_bot:
        return set()
    return {seat}


def _sync_move_timer(room: Room) -> None:
    """Start the clock of every seat that newly owes a decision (caller holds
    the lock). A no-op in a room without the move timer."""
    if not room.move_timer:
        return
    key = _decision_key(room)
    owing = _owing_seats(room)
    fresh = key != room.timer_key
    room.timer_key = key
    for i, sd in enumerate(room.seats):
        if sd is None:
            continue
        if i not in owing:
            sd.turn_started = None
        elif fresh or sd.turn_started is None:
            sd.turn_started = now()


def _timed(room: Room, seat: int) -> bool:
    """Is this seat's move clock running? Connected humans only: a
    disconnected seat is on TAKEOVER_AFTER instead."""
    sd = room.seats[seat]
    return (room.move_timer and not sd.is_bot and sd.connected
            and sd.turn_started is not None)


def _turn_deadline(room: Room, seat: int) -> float | None:
    """Seconds this seat has left for the current decision (None if no clock
    runs for it, or the bot already plays for it)."""
    if not _timed(room, seat) or room.seats[seat].away:
        return None
    return round(max(0.0, MOVE_TIMER - (now() - room.seats[seat].turn_started)), 1)


def _timed_out(room: Room, seat: int) -> bool:
    _sync_move_timer(room)
    return (_timed(room, seat)
            and now() - room.seats[seat].turn_started >= MOVE_TIMER)


def _count_timeout(room: Room, seat: int) -> None:
    """The bot made a decision a present player let run out."""
    sd = room.seats[seat]
    if sd.away:
        return
    sd.timeouts_in_row += 1
    sd.timeouts_in_round += 1
    if (sd.timeouts_in_row >= AWAY_IN_A_ROW
            or sd.timeouts_in_round >= AWAY_PER_ROUND):
        sd.away = True
        sd.away_since = room.game.round_no if room.game is not None else 0


def _player_moved(room: Room, seat: int) -> None:
    """A real decision (or ``im_back``) from the seat's player: the seat is
    no longer away and its run of timeouts is broken."""
    sd = room.seats[seat]
    sd.away = False
    sd.away_since = None
    sd.timeouts_in_row = 0


def _round_timeouts_reset(room: Room) -> None:
    for sd in room.seats:
        if sd is not None:
            sd.timeouts_in_round = 0


def _auto_mode(room: Room, seat: int) -> str | None:
    """How the bot may act for this seat without waiting: ``"bot"`` for a bot
    seat, ``"timeout"`` for a present player who is away, ``"takeover"`` for
    an absent player the bot already covers. The first cover of an absence
    stays with the watchdog, after TAKEOVER_AFTER, which also announces it."""
    sd = room.seats[seat]
    if sd.is_bot:
        return "bot"
    if room.move_timer and sd.connected and sd.away:
        return "timeout"
    if room.closing and not sd.connected:
        return "close"
    if sd.bot_announced and _turn_eligible(room, seat, "takeover"):
        return "takeover"
    return None


def _move_timer_fields(room: Room, seat: int) -> dict[str, Any]:
    """Per-seat move-timer fields, sent only in a room with the move timer:
    a casual room's frames stay identical to the offline local server's,
    which has no move timer."""
    return {
        # Seconds this seat has left on the move timer; null when no clock
        # runs for it. Ticked down locally, like takeover_in.
        "turn_deadline": _turn_deadline(room, seat),
        # The bot is playing every decision for this present player.
        "away": room.seats[seat].away,
    }


def state_for(room: Room, seat: int) -> dict[str, Any]:
    game = room.game
    rnd = room.round
    assert game is not None and rnd is not None
    room.sync_kitty()
    phase = rnd.phase if not game.game_over else "game_over"
    banker = rnd.banker
    hand_codes = rnd.sorted_hand(seat)
    id_pool = dict(room.ids[seat])
    hand = []
    for code in hand_codes:
        # Total by construction: a bare next() here raises StopIteration
        # INSIDE a coroutine, which Python turns into RuntimeError and which
        # killed every subsequent broadcast to the room, not just this seat.
        # If the id map ever disagrees with the hand, mint a fresh handle and
        # carry on — ids are per-round client handles, and an unknown id sent
        # back is already rejected by codes_for().
        cid = next((i for i, c in id_pool.items() if c == code), None)
        if cid is None:
            cid = room.mint_card_id(seat, code)
        else:
            del id_pool[cid]
        hand.append({"id": cid, "code": code})

    trump = None
    if rnd.ordering is not None:
        trump = {"suit": "NT" if rnd.trump_is_nt else rnd.trump_suit,
                 "rank": rnd.trump_rank,
                 "declarer": rnd.declaration["seat"] if rnd.declaration else None}

    declare_options = [room.ids_for_codes(seat, opt)
                       for opt in rnd.declare_options(seat)]

    result = game.result
    me = room.seats[seat]
    # a person with no account at a rated table: plays, is never rated
    guest = ratings.ranked(room) and not me.is_bot and me.user_id is None
    return {
        "type": "state",
        **({"experimental_policy": room.experimental_policy}
           if room.experimental_policy else {}),
        "room": room.code,
        "you": seat,
        # The round-end tally lives here too: in-game broadcasts send ONLY
        # state_for, so without this the client's ready count was always
        # 0/N and "Next round" never disabled (2026-08-03).
        "ready": sorted(room.ready),
        "phase": phase,
        "players": [{
            "seat": s, "name": room.seats[s].name, "is_bot": room.seats[s].is_bot,
            "connected": room.seats[s].connected or room.seats[s].is_bot,
            "team": s % 2, "cards_left": len(rnd.hands[s]),
            "is_banker": banker == s,
            # Seconds until the bot covers this seat, so the table can show a
            # countdown instead of a bare "offline" (Jerry, 2026-08-03).
            # Clients tick it down locally: broadcasts are event-driven, not
            # per-second, and an absolute time would need clock agreement.
            "takeover_in": _takeover_in(room, s),
            # Explicit three-way state instead of inferring it from is_bot:
            #   "human"     — a connected person is playing
            #   "bot"       — a permanent bot seat
            #   "bot_cover" — a bot covering a human who dropped
            "controller": _controller(room, s),
            # Seconds the absent owner keeps the right to reclaim. After it
            # expires anyone may claim the seat.
            "reserved_for": (room.seats[s].name
                             if _controller(room, s) == "bot_cover" else None),
            # Seconds the seat stays exclusively its owner's — the SAME
            # deadline the takeover countdown shows, so they cannot disagree.
            "reserved_secs": (_takeover_in(room, s)
                              if _reserved(room, s) else None),
            **(_move_timer_fields(room, s) if room.move_timer else {}),
        } for s in range(4)],
        "hand": hand,
        "levels": list(game.levels),
        "games_won": list(game.games_won),
        "banker": banker,
        "trump": trump,
        "turn": rnd.turn,
        "declare_options": declare_options,
        "passed": sorted(rnd.passed),
        "current_declaration": (
            {"seat": rnd.declaration["seat"], "cards": rnd.declaration["cards"]}
            if rnd.declaration else None),
        "trick": trick_json(rnd.trick, rnd.ordering),
        "last_trick": trick_json(rnd.last_trick, rnd.ordering),
        "attacker_points": rnd.attacker_points,
        "kitty_count": 8,
        "round_result": ({
            "attacker_points": result.attacker_points,
            "kitty_points": result.kitty_points,
            "kitty_cards": result.kitty_cards,
            "winner_team": result.winner_team,
            "level_change": result.level_change,
            "next_banker": result.next_banker,
            "new_levels": list(result.new_levels),
            "game_over": result.game_over,
            "games_won": list(result.games_won),
            "point_scored": result.point_scored,
            **ratings.round_payload(room, seat),
            # took this seat mid-round from an open table: not ranked for it;
            # a guest is not ranked at all
            **({"unranked": "joined"} if me.joined_round == game.round_no
               else {"unranked": "guest"} if guest else {}),
        } if result else None),
        "message": rnd.message,
        "notice": rnd.notice,
        **({"matched": True, "allow_joiners": room.allow_joiners,
            "joining": _join_notices(room)} if room.matched else {}),
        **({"ranked": True} if room.ranked else {}),
        **({"guest": True} if guest else {}),
    }


def room_json(room: Room, seat: int) -> dict:
    return {
        "type": "room", "room": room.code, "you": seat, "host": room.host,
        "start_level": room.start_level,
        **({"experimental_policy": room.experimental_policy}
           if room.experimental_policy else {}),
        **({"matched": True} if room.matched else {}),
        **({"ranked": True} if room.ranked else {}),
        "ready": sorted(room.ready),
        "players": [{"seat": i, "name": s.name, "is_bot": s.is_bot,
                     "connected": s.connected or s.is_bot}
                    for i, s in enumerate(room.seats) if s is not None],
    }


async def send(ws: WebSocket, payload: dict) -> None:
    """Direct send; only for sockets not yet bound to a seat."""
    try:
        await ws.send_json(payload)
    except Exception:
        pass


def chat_post(room: Room, entry: dict) -> None:
    """Append with a room-scoped monotonic id and fan out.

    Ids let a client deduplicate: on attach it gets ONE chat_history snapshot
    for the room, then live events it can drop if already present. The old
    scheme replayed bare messages with no room and no id, so a reconnect
    doubled the log and a room switch leaked the previous room's lines
    (Codex ship gate P0-5).
    """
    room.chat_seq += 1
    entry = {**entry, "id": room.chat_seq, "room": room.code}
    room.chat.append(entry)
    del room.chat[:-CHAT_KEEP]
    for sd in room.seats:
        if sd is not None:
            enqueue(sd, {"type": "chat", **entry})


def chat_snapshot(room: Room) -> dict:
    return {"type": "chat_history", "room": room.code,
            "through_id": room.chat_seq, "messages": list(room.chat)}


def chat_system(room: Room, text: str) -> None:
    """Post a system line into the room chat (joins, leaves, seat claims).

    Uses seat -1 so clients can style it apart from player messages; kept
    in the same scrollback so late joiners see who arrived before them.
    """
    chat_post(room, {"seat": -1, "name": "", "text": text, "t": time.time()})


def enqueue(seat: Seat, payload: dict) -> None:
    """Non-blocking send via the seat's writer task. A slow client fills its
    own queue (old snapshots are dropped) without stalling the room."""
    if seat.queue is None:
        return
    try:
        seat.queue.put_nowait(payload)
    except asyncio.QueueFull:
        try:
            seat.queue.get_nowait()  # drop oldest, keep newest
            seat.queue.put_nowait(payload)
        except asyncio.QueueEmpty:
            pass


def _receive_is_legal(ws: WebSocket) -> bool:
    """Would starlette still allow a receive on this socket?

    It must be APPLICATION_STATE, not client_state. starlette's
    receive_text/bytes/json all gate on application_state and raise
    'WebSocket is not connected' from it, and a send that fails with OSError
    sets application_state = DISCONNECTED while leaving client_state at
    CONNECTED. Checking client_state therefore reports "still connected" for
    exactly the socket that is about to raise (Codex, P2 on #643, reproduced
    against real starlette).
    """
    return getattr(ws, "application_state", None) is WebSocketState.CONNECTED


def _record_writer_exit(seat: "Seat", task: asyncio.Task) -> None:
    """Terminal, AUTHORITATIVE record of how a writer task ended.

    The in-body handlers cannot cover every case: a task cancelled before its
    coroutine takes its first step never runs the body at all, so it ends
    done() and cancelled() while the handler has recorded nothing (Codex, P2
    on #641). This callback fires for every completed task regardless, and
    reads the outcome from the TASK ITSELF rather than from whether some
    except clause happened to execute.

    Ownership-guarded for the same reason `_still_owns` is: a displaced
    writer must not stamp the seat the new socket already claimed.
    """
    if seat.writer is not task:
        return
    if seat.writer_exit is not None:
        return                      # the body already recorded it, with detail
    if task.cancelled():
        seat.writer_exit = "cancelled"
        return
    error = task.exception()
    if error is not None:           # body re-raised, or failed before its try
        seat.writer_exit = "error"
        seat.writer_error = f"{type(error).__name__}: {error}"
        logging.warning("websocket writer failed for seat %r: %s",
                        seat.name, seat.writer_error)
    else:
        seat.writer_exit = "returned"


def _start_writer(seat: "Seat", ws: WebSocket) -> asyncio.Task:
    """Spawn a seat's writer and attach its terminal record in ONE place, so
    no spawn path can exist without the diagnostic."""
    task = asyncio.create_task(_writer(ws, seat.queue, seat))
    seat.writer = task
    task.add_done_callback(lambda finished, s=seat: _record_writer_exit(s, finished))
    return task


def _still_owns(seat: "Seat | None") -> bool:
    """Is the calling writer still this seat's CURRENT writer?

    _attach displaces an old socket by cancelling its writer and then resetting
    the seat's fields. The cancelled writer's handler runs afterwards, so
    without this check a displaced writer stamps "cancelled" onto the seat that
    the NEW socket has already claimed -- reporting a dead writer for a
    perfectly healthy connection.
    """
    if seat is None:
        return False
    try:
        return seat.writer is asyncio.current_task()
    except RuntimeError:          # no running loop
        return False


async def _writer(ws: WebSocket, queue: asyncio.Queue,
                  seat: "Seat | None" = None) -> None:
    """Drain one seat's outbound queue to its socket.

    The writer still EXITS on an exception -- that behaviour is unchanged, and
    restarting it is a separate question. What changes is that it no longer
    exits silently. A swallowed exception here mutes the seat permanently while
    every other signal still says healthy: `connected` stays True, `enqueue`
    keeps accepting, and the queue just grows. That left #628 unfalsifiable
    from a log, because the one failure mode that explains the symptom is also
    the one that leaves no trace.

    Cancellation is recorded but NOT logged and NOT treated as an error: a
    displacement or detach cancels the writer as a matter of course. It is
    recorded anyway so that `writer_exit is None` carries real information --
    it means the writer is still running. Before this, a writer that died by
    cancellation was indistinguishable from one that never died, so a quiet
    seat ruled nothing out (Codex, reviewing #640).
    """
    try:
        while True:
            await ws.send_json(await queue.get())
    except asyncio.CancelledError:
        # Record, then RE-RAISE. Swallowing this would break cancellation for
        # every caller that awaits the task.
        if _still_owns(seat):
            seat.writer_exit = "cancelled"
        raise
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        if _still_owns(seat):
            seat.writer_error = detail
            seat.writer_exit = "error"
        logging.warning(
            "websocket writer stopped for seat %r after %d queued frames: %s",
            getattr(seat, "name", None),
            queue.qsize(),
            detail,
        )


async def broadcast(room: Room) -> None:
    if room.pending_joins:
        _settle_joins(room)
    if room.game and room.round:
        _sync_move_timer(room)
    for i, seat in enumerate(room.seats):
        if seat is not None and seat.connected and not seat.is_bot:
            if room.game and room.round:
                enqueue(seat, state_for(room, i))
            else:
                enqueue(seat, room_json(room, i))
    if room.game and room.round:
        # a newcomer waiting for the handover watches the seat it takes
        for i, pj in list(room.pending_joins.items()):
            pj.conn.push({**state_for(room, i), "joining_you": True})


# ----------------------------------------------------------------- bot pump
def _unwatched(room: Room) -> bool:
    """A room with human seats and none of them connected: its bots play at
    EMPTY_ROOM_BOT_DELAY, unless it is closing."""
    if room.closing:
        return False
    humans = [s for s in room.seats if s is not None and not s.is_bot]
    return bool(humans) and not any(s.connected for s in humans)


def _close_room(room: Room) -> None:
    """Unregister the room and cancel its tasks (caller holds the lock).
    The task running this call is left to return on its own."""
    if rooms.get(room.code) is room:
        del rooms[room.code]
    room.closing = False
    for seat in sorted(room.pending_joins):
        if seat in room.pending_joins:
            _drop_join(room, seat, back_in_line=True, reason="table_closed",
                       message="That game ended. You are back in the queue.")
    current = asyncio.current_task()
    for task in (room.bot_task, room.deal_task, room.watchdog_task, room.cleanup_task):
        if task is not None and task is not current:
            task.cancel()


def _close_when_empty(room: Room) -> None:
    """No human is connected any more (caller holds the lock): close now,
    or, while a round in play still owes a rating, finish it first."""
    if ratings.pending(room):
        room.closing = True
        if room.cleanup_task is None or room.cleanup_task.done():
            room.cleanup_task = asyncio.create_task(cleanup_room(room))
        kick_bots(room)
    else:
        _close_room(room)


def current_actor(room: Room) -> int | None:
    rnd = room.round
    if rnd is None or rnd.turn is None or rnd.phase == "round_end":
        return None
    return rnd.turn


def _acting_bot(room: Room) -> Any:
    """The bot that decides for the room now: the served bot, or in a closing
    room the heuristic bot, so a round nobody is in runs no model search."""
    if not room.closing:
        return room.bot
    if room.closing_bot is None:
        room.closing_bot = make_bot("heuristic", seed=room.bot_seed)
    return room.closing_bot


def _keep_acting_bot(room: Room, used: Any, decided: Any) -> None:
    """Store ``decided`` (the copy that made a committed decision) in the slot
    of ``used``, the bot it was copied from."""
    if used is room.closing_bot and used is not None:
        room.closing_bot = decided
    else:
        room.bot = decided


def _log_play(room: Room, seat: int, cards: list[str], bot: bool,
              prev_last, decider: Any = None) -> None:
    # S0 item 3: attach the search's own account of the decision. A live game
    # previously recorded only the CARD, so a reported misplay could not be
    # replayed — the QHKR incident had to be diagnosed from replicas rather
    # than from the actual draw. Best-effort and bot-only; a policy that ran no
    # search simply has no record.
    extra = {}
    if bot:
        rec = getattr(room.bot if decider is None else decider,
                      "last_decision_record", None)
        if rec is not None:
            if sorted(rec.get("played", [])) != sorted(cards):
                # A lead throw is an attempted action: the engine may replace
                # it with the lowest beatable component.  Preserve the policy
                # record as the attempted choice and put the engine resolution
                # beside it in the play event.  Any other mismatch is still a
                # hard observability bug rather than something to paper over.
                rnd = room.round
                if not (rnd is not None and isinstance(rnd.message, str)
                        and rnd.message.startswith("Throw failed")):
                    raise RuntimeError(
                        "bot decision record/play mismatch: record says "
                        f"{rec.get('played')}, server received {cards}")
                extra["attempted_cards"] = list(rec.get("played", []))
                extra["engine_resolution"] = "failed_throw_forced"
            extra["decision"] = rec
    room.log_event("play", seat=seat, cards=cards, bot=bot, **extra)
    rnd = room.round
    if rnd and rnd.last_trick is not None and rnd.last_trick is not prev_last:
        lt = rnd.last_trick
        room.log_event("trick", winner=lt.winner, points=lt.points,
                       plays=[{"seat": p.seat, "cards": p.cards}
                              for p in lt.plays])



def _observe_committed_play(room: Room) -> None:
    """Let the COMMITTED room bot read the public failed-throw notice (#707 S8).

    Where this hook lives, and why.  A ``Round.notice`` is posted by the commit
    of a failed throw and replaced by the next one, so a ledger that reads it
    only inside the bot's own decisions misses notices (#745).  The decision
    runs on a deep-copied snapshot (`_snapshot_bot_turn`) against a deep-copied
    round, BEFORE the play commits -- it cannot see its own throw's notice, and
    the whole copy is discarded when the commit is stale.  So the read must
    happen (1) after ``rnd.play`` on the LIVE round, (2) under ``room.lock`` on
    the three commit paths (`bot_step`, `_commit_bot_turn`, the human play in
    `handle_action`), and (3) on ``room.bot`` AS IT IS AFTER THE COMMIT -- in
    `_commit_bot_turn` that is ``snapshot.bot_copy``, which has just become the
    room bot and persists to the next turn.  Reading on the snapshot inside
    `_compute_bot_turn` would be too early and, on a stale commit, lost.

    Best-effort and bounded: a bot without `observe_public` (every non-PV bot)
    is skipped, and nothing raised here reaches the game loop -- the play has
    already committed and is logged; a failed read must never desync a room.
    A flag-off PV bot's `observe_public` is itself a no-op.
    """
    observe = getattr(room.bot, "observe_public", None)
    if observe is None:
        return
    try:
        observe(room.round)
    except Exception as exc:  # never into the loop; the play is already committed
        logging.warning("room %s observe_public failed: %s: %s",
                        room.code, type(exc).__name__, exc)


def pending_ready(room: Room) -> set[int]:
    """Connected humans who have not yet confirmed the round end."""
    return {i for i, sd in enumerate(room.seats)
            if not sd.is_bot and sd.connected} - room.ready


async def advance_if_all_ready(room: Room) -> bool:
    """Start the next round once every CONNECTED human has confirmed.

    Called both when someone clicks and when someone drops: a player who
    leaves during the round-end screen must stop being counted, or the
    remaining players wait forever on a browser that is never coming back
    (Jerry, 2026-08-03).
    """
    if room.evaluation is not None and room.evaluation_invalidated:
        return False
    rnd, game = room.round, room.game
    if game is None or rnd is None or rnd.phase != "round_end" or game.game_over:
        return False
    if pending_ready(room) or not room.ready:
        return False
    room.ready.clear()
    game.start_round()
    room.index_round()
    _round_timeouts_reset(room)
    # everyone seated now starts this round, so it is ranked for them
    room.round_end_joins.clear()
    for sd in room.seats:
        if sd is not None:
            sd.joined_round = None
    _log_round_start(room)
    saved_games.round_started(room)
    ratings.round_started(room)
    _spawn_room_task(room, "deal_task", run_deal(room))
    return True


def _log_round_start(room: Room) -> int | None:
    rnd, game = room.round, room.game
    assert rnd is not None and game is not None
    if room.evaluation is None:
        players = [
            {"seat": i, "name": seat.name, "is_bot": seat.is_bot}
            for i, seat in enumerate(room.seats)
        ]
    else:
        players = [
            {
                "seat": i,
                "is_bot": seat.is_bot,
                **({"participant_id": seat.evaluation_participant_id}
                   if not seat.is_bot else {}),
            }
            for i, seat in enumerate(room.seats)
        ]
    # Room logs never carry account ids (test_no_log_record_carries_the_account);
    # seats map to accounts through the game_players links instead.
    return room.log_event("round_start", deck=rnd.deck, banker=rnd.banker,
                   trump_rank=rnd.trump_rank, levels=list(game.levels),
                   players=players, bot_seed=room.bot_seed,
                   ranked=ratings.ranked(room))


def _log_seat(room: Room, kind: str, seat: Seat, reason: str) -> None:
    """A seat's presence change (``seat_disconnected``, ``seat_reconnected``,
    ``seat_left``) in a started game; a lobby keeps no log of its own."""
    if room.game is not None and seat in room.seats:
        room.log_event(kind, seat=room.seats.index(seat), reason=reason)


def _log_play_refused(room: Room, seat: int, msg: dict, error: IllegalPlay) -> None:
    """A human play the server refused, with the cards it named (unknown ids
    are kept as ids). The record reveals a hand, so ``saved_games`` never
    serves it (it is not in ``PUBLIC_KEYS``)."""
    rnd = room.round
    if room.game is None or rnd is None:
        return
    ids = msg.get("card_ids")
    ids = ids[:64] if isinstance(ids, list) else []
    attempted = [room.ids[seat].get(i, i)
                 if isinstance(i, int) and not isinstance(i, bool) else None
                 for i in ids]
    room.log_event("play_refused", seat=seat, attempted_cards=attempted,
                   phase=rnd.phase, turn=rnd.turn,
                   code=getattr(error, "code", None) or type(error).__name__,
                   reason=str(error))


def _log_round_end(room: Room) -> None:
    r = room.game.result if room.game else None
    if r is None:
        return
    room.log_event("round_end", attacker_points=r.attacker_points,
                   kitty=r.kitty_cards, kitty_points=r.kitty_points,
                   winner_team=r.winner_team, level_change=r.level_change,
                   new_levels=list(r.new_levels), next_banker=r.next_banker,
                   game_over=r.game_over, games_won=list(r.games_won),
                   point_scored=r.point_scored)
    saved_games.round_ended(room, r)
    ratings.round_ended(room, r)
    _joined_round_ended(room)
    if room.closing:
        _close_room(room)


def bot_step(room: Room, seat: int) -> bool:
    """One bot decision for ``seat`` (caller holds the lock). True if acted."""
    if room.evaluation is not None and room.evaluation_invalidated:
        return False
    game, rnd = room.game, room.round
    if game is None or rnd is None or game.game_over:
        return False
    try:
        if rnd.phase == "bury":
            cards = room.bot.decide_bury(rnd, seat)
            room.sync_kitty()
            rnd.bury(seat, cards)
            room.remove_codes(seat, cards)
            room.log_event("bury", seat=seat, cards=cards, bot=True)
        elif rnd.phase == "play":
            prev_last = rnd.last_trick
            cards = room.bot.decide_play(rnd, seat)
            rnd.play(seat, cards)
            # a failed throw plays fewer cards than attempted — mirror what
            # the ENGINE recorded, not what the bot asked for
            played = actual_play_after(rnd, seat, prev_last)
            room.remove_codes(seat, played)
            _log_play(room, seat, played, True, prev_last)
            _observe_committed_play(room)
        else:
            return False
        if rnd.phase == "round_end" and game.result is None:
            game.finish_round()
            _log_round_end(room)
        return True
    except IllegalPlay as e:  # bot bug — shouldn't happen; skip safely
        rnd.message = f"Bot error at seat {seat}: {e}"
        return False


@dataclass(frozen=True)
class _BotTurnSnapshot:
    """Immutable ownership token plus isolated state used by one search."""

    game_token: Game
    round_token: Round
    round_copy: Round
    bot_copy: Any
    seat: int
    phase: str
    mode: str
    owner_left_at: float | None
    play_cursor: tuple[int, int] | None
    # copied from the closing room's heuristic bot, not the served bot
    closing_bot: bool = False


@dataclass(frozen=True)
class _BotTurnDecision:
    snapshot: _BotTurnSnapshot
    cards: list[str]


@dataclass(frozen=True)
class _PreparedBotTurn:
    decision: _BotTurnDecision
    compute_seconds: float
    pacing_seconds: float
    turn_seconds: float


def _turn_eligible(room: Room, seat: int, mode: str, *,
                   owner_left_at: float | None = None) -> bool:
    if room.evaluation is not None and room.evaluation_invalidated:
        return False
    if current_actor(room) != seat or not 0 <= seat < len(room.seats):
        return False
    owner = room.seats[seat]
    if mode == "bot":
        return owner.is_bot
    if mode == "close":
        return room.closing and not owner.is_bot and not owner.connected
    if mode == "takeover":
        return (
            not owner.is_bot
            and not owner.connected
            and owner.left_at is not None
            and (owner_left_at is None or owner.left_at == owner_left_at)
            and now() - owner.left_at >= TAKEOVER_AFTER
        )
    if mode == "timeout":
        return (room.move_timer and not owner.is_bot and owner.connected
                and (owner.away or _timed_out(room, seat)))
    raise ValueError(f"unknown bot-turn mode {mode!r}")


def _snapshot_bot_turn(room: Room, seat: int, mode: str
                       ) -> _BotTurnSnapshot | None:
    """Copy a currently eligible turn while the caller holds ``room.lock``.

    Search must not read the live round after the lock is released.  The bot is
    copied too: if a player claims the seat while search is running, discarding
    the result must also discard its RNG/counter advance.
    """
    game, rnd = room.game, room.round
    if (game is None or rnd is None or game.game_over
            or not _turn_eligible(room, seat, mode)):
        return None
    bot = _acting_bot(room)
    return _BotTurnSnapshot(
        game_token=game,
        round_token=rnd,
        round_copy=copy.deepcopy(rnd),
        bot_copy=copy.deepcopy(bot),
        seat=seat,
        phase=rnd.phase,
        mode=mode,
        owner_left_at=room.seats[seat].left_at,
        play_cursor=(len(rnd.history), len(rnd.trick.plays)) if rnd.phase == "play" else None,
        closing_bot=bot is not room.bot,
    )


def _compute_bot_turn(snapshot: _BotTurnSnapshot) -> _BotTurnDecision:
    rnd, bot, seat = snapshot.round_copy, snapshot.bot_copy, snapshot.seat
    if snapshot.phase == "bury":
        cards = bot.decide_bury(rnd, seat)
    elif snapshot.phase == "play":
        cards = bot.decide_play(rnd, seat)
    else:
        raise IllegalPlay(f"Bot cannot act during {snapshot.phase}.")
    return _BotTurnDecision(snapshot=snapshot, cards=list(cards))


async def _compute_bot_turn_off_loop(
        snapshot: _BotTurnSnapshot) -> _BotTurnDecision:
    """Run isolated CPU search without starving every WebSocket room.

    Cancellation is deferred until the worker exits so a cancelled room cannot
    accumulate orphaned report-LCB searches.  This no longer protects live
    mutation—the worker has none—but it keeps CPU ownership bounded.
    """
    worker = asyncio.create_task(
        asyncio.to_thread(_compute_bot_turn, snapshot),
        name=f"bot-search-{snapshot.seat}",
    )
    cancelled: asyncio.CancelledError | None = None
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as exc:
            cancelled = exc
    result = worker.result()
    if cancelled is not None:
        raise cancelled
    return result


async def _paced_bot_step(room: Room, seat: int, *,
                          turn_started: float | None = None,
                          mode: str = "bot",
                          minimum_turn_seconds: float | None = None,
                          ) -> _PreparedBotTurn | None:
    """Search an isolated snapshot while the live room remains claimable."""
    if turn_started is None:
        turn_started = time.perf_counter()
    # The served pace (no explicit minimum) is the one that slows an empty
    # room; a caller's explicit minimum, such as 0 in tests, stands as given.
    served_pace = minimum_turn_seconds is None
    if served_pace:
        minimum_turn_seconds = BOT_DELAY
    async with room.lock:
        snapshot = _snapshot_bot_turn(room, seat, mode)
    if snapshot is None:
        return None
    compute_started = time.perf_counter()
    model_serving = getattr(getattr(snapshot.bot_copy, "evaluator", None),
                            "backend", None) == "numpy"
    if model_serving:
        def emit(kind, **fields):
            # ``phase`` (bury / play) lets a log reader separate bury search
            # time from play search time; the room log otherwise records only
            # the queue/run/complete stages and their elapsed seconds.
            room.log_event("model_search", seat=seat, mode=mode,
                           policy=getattr(snapshot.bot_copy, "policy_name", "W32"),
                           phase=snapshot.phase, event=kind, **fields)
        try:
            decision = await run_model_search(
                lambda: _compute_bot_turn_off_loop(snapshot), emit)
        except Exception:
            # No silent policy downgrade or commit of a partially advanced
            # snapshot. Leave the live state/RNG intact and make the failure
            # visible; an operator can roll back or a human claim the seat.
            async with room.lock:
                if room.round is snapshot.round_token:
                    room.round.message = "Model search failed; claim this seat or contact the host."
                    await broadcast(room)
            raise
    else:
        decision = await _compute_bot_turn_off_loop(snapshot)
    compute_seconds = time.perf_counter() - compute_started
    pacing_seconds = max(
        0.0, minimum_turn_seconds - (time.perf_counter() - turn_started))
    if pacing_seconds:
        await asyncio.sleep(pacing_seconds)
    # An empty room plays slowly. The wait is re-read in slices, so a human
    # connecting cuts it short.
    while served_pace and _unwatched(room):
        remaining = EMPTY_ROOM_BOT_DELAY - (time.perf_counter() - turn_started)
        if remaining <= 0:
            break
        await asyncio.sleep(min(remaining, EMPTY_ROOM_POLL))
        pacing_seconds += min(remaining, EMPTY_ROOM_POLL)
    turn_seconds = time.perf_counter() - turn_started
    return _PreparedBotTurn(
        decision=decision,
        compute_seconds=compute_seconds,
        pacing_seconds=pacing_seconds,
        turn_seconds=turn_seconds,
    )


def _commit_bot_turn(room: Room, prepared: _PreparedBotTurn) -> bool:
    """Commit only if snapshot ownership and the live turn are unchanged.

    The caller holds ``room.lock``.  A claim, reconnect, human play, new round,
    or takeover-state change makes the speculative result stale.  In that case
    both the action and the cloned bot RNG/counters are discarded.
    """
    decision = prepared.decision
    snapshot = decision.snapshot
    if (room.game is not snapshot.game_token
            or room.round is not snapshot.round_token
            or room.round is None
            or room.round.phase != snapshot.phase
            # The fourth player can win and immediately lead. Seat and phase
            # then match an OLD snapshot, but the previous follow is not a
            # decision for the new lead. Store this outside round_copy because
            # speculative policy code may mutate its isolated copy.
            or (snapshot.phase == "play" and snapshot.play_cursor !=
                (len(room.round.history), len(room.round.trick.plays)))
            or not _turn_eligible(
                room, snapshot.seat, snapshot.mode,
                owner_left_at=snapshot.owner_left_at)):
        return False
    if snapshot.closing_bot:
        room.closing_bot = snapshot.bot_copy
    else:
        room.bot = snapshot.bot_copy
    rnd = room.round
    seat = snapshot.seat
    try:
        if snapshot.phase == "bury":
            room.sync_kitty()
            rnd.bury(seat, decision.cards)
            room.remove_codes(seat, decision.cards)
            room.log_event("bury", seat=seat, cards=decision.cards, bot=True)
        elif snapshot.phase == "play":
            prev_last = rnd.last_trick
            rnd.play(seat, decision.cards)
            played = actual_play_after(rnd, seat, prev_last)
            room.remove_codes(seat, played)
            _log_play(room, seat, played, True, prev_last,
                      decider=snapshot.bot_copy)
            # on the served bot: ``snapshot.bot_copy`` unless the room is closing
            _observe_committed_play(room)
        else:  # guarded by snapshot construction; fail closed on corruption
            return False
        if snapshot.mode == "close":
            # the bot played for an absent player: rated as a takeover
            room.seats[seat].bot_announced = True
        if snapshot.mode == "timeout":
            # Counted here, once per committed action and before the round
            # end below captures ratings: a final-card timeout that makes the
            # seat away must be rated as away.
            _count_timeout(room, seat)
        if rnd.phase == "round_end" and room.game.result is None:
            room.game.finish_round()
            _log_round_end(room)
    except IllegalPlay as exc:
        rnd.message = f"Bot error at seat {seat}: {exc}"
        return False
    return True


def _log_bot_timing(room: Room, prepared: _PreparedBotTurn, *,
                    acted: bool) -> None:
    snapshot = prepared.decision.snapshot
    bury_fields = {}
    if snapshot.phase == "bury":
        record = getattr(snapshot.bot_copy, "last_bury_record", None)
        if isinstance(record, dict) and record.get("schema") in (
                "cwv-bury-policy-v1", "cwv-bury-fallback-v1"):
            bury_fields = {
                "bury_search_status": ("fallback" if record["schema"] == "cwv-bury-fallback-v1"
                                       else "complete"),
                "bury_requested_arm": record["arm"],
                "bury_fallback_reason": record.get("reason"),
                "bury_error_class": record.get("error_class"),
            }
            if "bury_belief_fallbacks" in record:
                # only a bbw bury carries it: every other bury logs the fields above
                bury_fields["bury_belief_fallbacks"] = record["bury_belief_fallbacks"]
    prior_fields = {}
    # PLAY ONLY, and that is load-bearing.  `room.bot = snapshot.bot_copy` keeps the
    # bot between turns and `decide_bury` never touches `_prior_diagnostics`, so on a
    # bury turn the attribute still holds the PREVIOUS play turn's admission figures.
    # Logging those under phase="bury" would write a number that was never measured
    # for that decision.  The play side is kept honest at the other end, by
    # `CWVPriorAdmissionBot.decide_play` clearing the attribute on entry -- the
    # TRACTOR_LOCK early return never reaches `_candidates`, so clearing there alone
    # is not enough.
    diagnostic = (getattr(snapshot.bot_copy, "_prior_diagnostics", None)
                  if snapshot.phase == "play" else None)
    if isinstance(diagnostic, dict):
        # The admission prior already builds this per decision; until now nothing
        # carried it off the machine, so how much of the wide tail the threshold
        # actually prunes in real play was unmeasurable from the room logs (#419).
        # Logging only: read after the decision, never consulted by it.
        prior_fields = {
            "prior_triggered": bool(diagnostic.get("triggered")),
            "prior_legal_count": diagnostic.get("legal_count"),
            "prior_threshold": (diagnostic.get("threshold")
                                if not diagnostic.get("triggered")
                                else (diagnostic.get("recipe") or {}).get("threshold")),
        }
        if diagnostic.get("triggered"):
            prior_fields.update(
                prior_union_size=diagnostic.get("union_size"),
                prior_anchors_added=diagnostic.get("anchors_added"),
                prior_pool_actions=diagnostic.get("pool_action_count"),
                prior_pool_evaluations=diagnostic.get("pool_evaluations"),
                prior_seconds=round(float(diagnostic.get("prior_seconds") or 0.0), 6),
            )
    room.log_event(
        "bot_timing", seat=snapshot.seat, phase=snapshot.phase,
        policy=getattr(
            snapshot.bot_copy, "policy_name",
            type(snapshot.bot_copy).__name__),
        mode=snapshot.mode,
        compute_seconds=round(prepared.compute_seconds, 6),
        pacing_seconds=round(prepared.pacing_seconds, 6),
        turn_seconds=round(prepared.turn_seconds, 6),
        event_loop_offloaded=True,
        snapshot_isolated=True,
        acted=acted,
        stale_discarded=not acted,
        **prior_fields,
        **bury_fields,
    )


async def pump_bots(room: Room) -> None:
    while True:
        turn_started = time.perf_counter()
        async with room.lock:
            seat = current_actor(room)
            mode = None if seat is None else _auto_mode(room, seat)
            if mode is None:
                return
        prepared = await _paced_bot_step(
            room, seat, turn_started=turn_started, mode=mode,
            minimum_turn_seconds=0.0 if room.closing else None)
        if prepared is None:
            return
        async with room.lock:
            acted = _commit_bot_turn(room, prepared)
            _log_bot_timing(room, prepared, acted=acted)
            if not acted:
                return
            await broadcast(room)


async def watchdog_tick(room: Room) -> bool:
    """One takeover check. Returns True if a bot acted for an absent human.

    Split out of the loop so tests can drive it with an injected clock rather
    than sleeping through TAKEOVER_AFTER (Codex ship gate P0-3).
    """
    return await _watchdog_body(room)


async def _watchdog_body(room: Room) -> bool:
    """Cover one expired disconnected turn without blocking reconnection."""
    if rooms.get(room.code) is not room:
        return False
    async with room.lock:
        if rooms.get(room.code) is not room:
            return False
        seat = current_actor(room)
        if (seat is None
                or not _turn_eligible(room, seat, "takeover")):
            return False
        if room.seats[seat].bot_announced:
            # an announced cover moves at the served pace through pump_bots;
            # here it only restarts a pump that is not running
            kick_bots(room)
            return False
    prepared = await _paced_bot_step(
        room, seat, mode="takeover", minimum_turn_seconds=0.0)
    if prepared is None:
        return False
    async with room.lock:
        if rooms.get(room.code) is not room:
            return False
        acted = _commit_bot_turn(room, prepared)
        _log_bot_timing(room, prepared, acted=acted)
        if not acted:
            return False
        owner = room.seats[seat]
        if not owner.bot_announced:
            owner.bot_announced = True
            chat_system(room, f"bot is playing for {owner.name} "
                              f"(disconnected)")
        await broadcast(room)
        kick_bots(room)
        return True


async def move_timer_tick(room: Room) -> bool:
    """One move-timer check. Returns True if the bot decided for a present
    player (a play, a bury or a round-end Next). Tests drive it with an
    injected clock."""
    if rooms.get(room.code) is not room or not room.move_timer:
        return False
    async with room.lock:
        if rooms.get(room.code) is not room:
            return False
        _sync_move_timer(room)
        rnd, game = room.round, room.game
        if rnd is None or game is None or game.game_over:
            return False
        if rnd.phase == "round_end":
            readied = False
            for s in sorted(_owing_seats(room)):
                sd = room.seats[s]
                if not sd.connected:
                    continue
                if sd.away:
                    room.ready.add(s)
                    readied = True
                elif _timed_out(room, s):
                    room.ready.add(s)
                    _count_timeout(room, s)
                    readied = True
            if not readied:
                return False
            if not await advance_if_all_ready(room):
                await broadcast(room)
            return True
        seat = current_actor(room)
        if seat is None or not _turn_eligible(room, seat, "timeout"):
            return False
    prepared = await _paced_bot_step(
        room, seat, mode="timeout", minimum_turn_seconds=0.0)
    if prepared is None:
        return False
    async with room.lock:
        if rooms.get(room.code) is not room:
            return False
        acted = _commit_bot_turn(room, prepared)
        _log_bot_timing(room, prepared, acted=acted)
        if not acted:
            return False
        await broadcast(room)
        kick_bots(room)
        return True


async def watchdog(room: Room) -> None:
    """If the turn-holder is a disconnected human for TAKEOVER_AFTER seconds,
    the bot plays their turn so the game can't stall forever. In a room with
    the move timer it also enforces MOVE_TIMER for present players."""
    while True:
        await asyncio.sleep(MOVE_TIMER_POLL if room.move_timer else 5.0)
        if rooms.get(room.code) is not room:
            return
        await _watchdog_body(room)
        if room.move_timer:
            await move_timer_tick(room)


async def cleanup_room(room: Room) -> None:
    """Close the room only after ROOM_TTL with no humans connected, so a
    refresh or network blip can reclaim the seat and resume the game; the
    bots play slowly meanwhile. A closing room still open after ROOM_TTL
    closes without its round."""
    await asyncio.sleep(ROOM_TTL)
    async with room.lock:
        if any(s.connected for s in room.seats if s is not None and not s.is_bot):
            return
        if room.cleanup_task is asyncio.current_task():
            room.cleanup_task = None
        if room.closing:
            _close_room(room)       # the round it waited for never ended
        else:
            _close_when_empty(room)


def kick_bots(room: Room) -> None:
    seat = current_actor(room)
    if seat is not None and _auto_mode(room, seat) is not None:
        if room.bot_task is None or room.bot_task.done():
            _spawn_room_task(room, "bot_task", pump_bots(room))


# ---------------------------------------------------------------- room tasks
def _record_room_task_exit(room: "Room", attr: str, task: asyncio.Task) -> None:
    """Terminal record of how a room task ended, from the TASK ITSELF (the
    same design as ``_record_writer_exit``); ownership-guarded so a replaced
    task does not stamp its successor's slot."""
    if getattr(room, attr, None) is not task:
        return
    if task.cancelled():
        room.task_exits[attr] = "cancelled"
        return
    error = task.exception()
    if error is not None:
        room.task_exits[attr] = f"error: {type(error).__name__}: {error}"
        logging.warning("room %s %s failed: %s: %s", room.code, attr,
                        type(error).__name__, error)
    else:
        room.task_exits[attr] = "returned"


def _spawn_room_task(room: "Room", attr: str, coro) -> asyncio.Task:
    """Spawn ``coro`` as ``room.<attr>`` with its terminal record attached in
    ONE place, so no spawn path can exist without the diagnostic (#628)."""
    task = asyncio.create_task(coro)
    setattr(room, attr, task)
    room.task_exits.pop(attr, None)
    task.add_done_callback(lambda finished, r=room, a=attr: _record_room_task_exit(r, a, finished))
    return task


# ---------------------------------------------------------------- deal task
async def _bot_declares(room: Room, seats: list[int], final: bool = False) -> bool:
    """Declare without holding the room lock during optional model search.

    Callers must NOT hold the lock. Each decision sees the last committed
    declaration. A concurrent human declaration or seat claim invalidates the
    speculative bot state as well as its cards. The flag-off path stays inline.
    """
    original_round = room.round
    complete = True
    for s in seats:
        async with room.lock:
            rnd = room.round
            if (rnd is not original_round or rnd is None
                    or rnd.phase not in ("deal", "declare")
                    or (room.evaluation is not None and room.evaluation_invalidated)):
                return False
            if s >= len(room.seats) or not room.seats[s].is_bot:
                continue
            bot = _acting_bot(room)
            value_declare = getattr(bot, "value_declare", False)
            gate = getattr(bot, "declare_gate", None)
            # Most dealt cards cannot trigger value evaluation. Keep those
            # calls inline before copying or queueing behind another room's
            # model search. Unknown bot implementations stay on the safe
            # off-loop path; only the bot's own gate can certify a cheap call.
            gated = value_declare and (not callable(gate) or gate(rnd, s, final)[1])
            if not gated:
                cards = bot.decide_declare(rnd, s, final=final)
                if cards:
                    try:
                        rnd.declare(s, cards)
                        room.log_event("declare", seat=s, cards=cards, bot=True)
                    except IllegalPlay:
                        pass
                continue
            game, owner = room.game, room.seats[s]
            phase, declaration = rnd.phase, rnd.declaration
            hands = tuple(tuple(hand) for hand in rnd.hands)
            round_copy, bot_copy = copy.deepcopy(rnd), copy.deepcopy(bot)

        def emit(kind, **fields):
            room.log_event("model_search", seat=s, mode="bot", phase="declare",
                           policy=getattr(bot_copy, "policy_name", "W32"),
                           event=kind, **fields)

        # The shared admission wrapper retains its permit through cancellation
        # and drains the thread before returning: no orphan declaration workers.
        # PVSearchBot retains its own cooperative serving budget and heuristic
        # fallback; this wiring does not select a new deployment budget.
        cards = await run_model_search(
            lambda: asyncio.to_thread(bot_copy.decide_declare, round_copy, s,
                                      final=final), emit)
        async with room.lock:
            if (room.game is not game or room.round is not rnd
                    or _acting_bot(room) is not bot or rnd.phase != phase
                    or rnd.declaration is not declaration
                    or tuple(tuple(hand) for hand in rnd.hands) != hands
                    or s >= len(room.seats) or room.seats[s] is not owner
                    or not owner.is_bot
                    or (room.evaluation is not None and room.evaluation_invalidated)):
                complete = False
                continue
            if cards:
                try:
                    rnd.declare(s, cards)
                    room.log_event("declare", seat=s, cards=cards, bot=True)
                except IllegalPlay:
                    complete = False
                    continue
            _keep_acting_bot(room, bot, bot_copy)
            record = getattr(bot_copy, "last_declare_record", None)
            if record is not None:
                room.log_event("declare_decision", seat=s, record=record, bot=True)
    return complete


async def run_deal(room: Room) -> None:
    """Stream the deal card by card, then run the declare grace window."""
    rnd = room.round
    assert rnd is not None
    while True:
        async with room.lock:
            if room.round is not rnd:
                return
            if room.evaluation is not None and room.evaluation_invalidated:
                return
            if rnd.phase != "deal":
                break
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code
        await _bot_declares(room, [seat])
        async with room.lock:
            if room.round is not rnd:
                return
            await broadcast(room)
        await asyncio.sleep(0.0 if room.closing else DEAL_DELAY)

    loop = asyncio.get_event_loop()
    needs_response = not await _bot_declares(room, list(range(4)), final=True)
    async with room.lock:
        if (room.round is not rnd or rnd.phase != "declare"
                or (room.evaluation is not None and room.evaluation_invalidated)):
            return
        for s in range(4):
            if room.seats[s].is_bot and not needs_response:
                rnd.passed.add(s)
        await broadcast(room)
    deadline = loop.time() + DECLARE_GRACE
    last_declaration = rnd.declaration
    while True:
        await asyncio.sleep(0.0 if room.closing else 0.25)
        async with room.lock:
            if room.evaluation is not None and room.evaluation_invalidated:
                return
            if room.round is not rnd or rnd.phase != "declare":
                return
            if needs_response or rnd.declaration is not last_declaration:
                last_declaration = rnd.declaration
                deadline = max(deadline, loop.time() + DECLARE_EXTEND)
                respond = True
            else:
                respond = False
        if respond:
            needs_response = not await _bot_declares(room, list(range(4)), final=True)
        async with room.lock:
            if (room.round is not rnd or rnd.phase != "declare"
                    or (room.evaluation is not None and room.evaluation_invalidated)):
                return
            if needs_response:
                # A human changed the position during search. Do not mark a
                # stale response as a pass or finalize before the next attempt.
                continue
            if respond:
                if rnd.declaration is not last_declaration:
                    # Search may consume the old grace period. Give humans a
                    # full response window to a declaration committed afterward.
                    deadline = max(deadline, loop.time() + DECLARE_EXTEND)
                for s in range(4):
                    if room.seats[s].is_bot:
                        rnd.passed.add(s)
            humans = [i for i, s in enumerate(room.seats)
                      if not s.is_bot and s.connected]
            if all(i in rnd.passed for i in humans) or loop.time() >= deadline:
                rnd.finalize_declare()
                room.log_event("trump", suit=rnd.trump_suit or "NT",
                               rank=rnd.trump_rank, banker=rnd.banker,
                               declared=rnd.declaration is not None)
                await broadcast(room)
                kick_bots(room)
                return


# ------------------------------------------------------------------ actions
def new_code() -> str:
    # The module RNG, as before: choices() draws once per character whatever
    # the alphabet, so the stream that seeded fixtures read is unchanged.
    return matchmaking.new_code(
        lambda c: c in rooms or MATCHMAKER.has_party_code(c), random)


def _card_ids(msg: dict) -> list[int]:
    ids = msg.get("card_ids")
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
            or len(set(ids)) != len(ids)):
        raise IllegalPlay("Invalid card selection.")
    return ids


def validate_human_evaluation_start(room: Room) -> None:
    """Refuse a HUMAN-C1 start unless the clean 2-human/2-bot estimand holds."""
    context = room.evaluation
    if context is None:
        return
    if room.evaluation_invalidated:
        raise IllegalPlay("Evaluation session was invalidated by logging failure.")
    if len(room.seats) != 4:
        raise IllegalPlay("Evaluation requires exactly four assigned seats.")
    for seat in (0, 2):
        occupant = room.seats[seat]
        expected = context.participant_ids_by_human_seat[seat // 2]
        if occupant.is_bot or not occupant.connected:
            raise IllegalPlay(
                "Evaluation requires connected humans at seats 0 and 2.")
        if occupant.evaluation_participant_id != expected:
            raise IllegalPlay("Evaluation participant identity mismatch.")
    if any(not room.seats[seat].is_bot for seat in (1, 3)):
        raise IllegalPlay("Evaluation requires bots at seats 1 and 3.")


def _empty_position(room: Room) -> int | None:
    """The lowest empty seat position before the game, or None when full."""
    for i, sd in enumerate(room.seats):
        if sd is None:
            return i
    return len(room.seats) if len(room.seats) < 4 else None


def _seat_at(room: Room, position: int, occupant: Seat | None) -> None:
    """Put ``occupant`` (None: empty) at a lobby position, keeping the list
    free of trailing empties so a room nobody rearranged is a plain list."""
    while len(room.seats) <= position:
        room.seats.append(None)
    room.seats[position] = occupant
    while room.seats and room.seats[-1] is None:
        room.seats.pop()


def _occupant(room: Room, position: int) -> Seat | None:
    return room.seats[position] if position < len(room.seats) else None


class SeatChanged(IllegalPlay):
    """A lobby action named an occupant who is no longer in that seat."""


class SameDevice(IllegalPlay):
    """A ranked game with two human seats on one device."""


def _check_expected(room: Room, position: int, expected: Any) -> None:
    """Refuse when the client said whom it meant at ``position`` and that is
    no longer so. ``expected`` is the occupant as the room frame showed it,
    ``{"name": ..., "is_bot": ...}``, or None for an empty seat: the frame
    carries no other identity, and the offline server's frames must match."""
    sd = _occupant(room, position)
    seen = {"name": sd.name, "is_bot": sd.is_bot} if sd is not None else None
    if expected != seen:
        raise SeatChanged("That seat just changed. Try again.")


def _swap_seats(room: Room, seat: int, msg: dict) -> None:
    """Host-only lobby move: exchange what is in two seat positions, a
    person, a bot or nothing.

    Everything a connection owns (socket, queue, writer, generation, resume
    token, account) lives on the ``Seat`` object, and a socket finds its seat
    by identity on every action, so moving the objects moves the people. The
    only per-POSITION state before a game exists is the host seat, the ready
    set and the per-seat card-id maps, which follow the move here. A
    saved-game continuation binds its creator's team and banker to seat
    numbers, and an evaluation room fixes its seating, so neither can be
    rearranged.
    """
    if seat != room.host:
        raise IllegalPlay("Only the host can move seats.")
    if room.game:
        raise IllegalPlay("Seats are fixed once the game has started.")
    if room.resume is not None or room.evaluation is not None:
        raise IllegalPlay("Seats are fixed at this table.")
    a, b = msg.get("a"), msg.get("b")
    if (type(a) is not int or type(b) is not int or a == b
            or not (0 <= a < 4 and 0 <= b < 4)):
        raise IllegalPlay("Invalid seats.")
    if "expect" in msg:
        expect = msg["expect"]
        if not isinstance(expect, list) or len(expect) != 2:
            raise IllegalPlay("Invalid seats.")
        _check_expected(room, a, expect[0])
        _check_expected(room, b, expect[1])
    first, second = _occupant(room, a), _occupant(room, b)
    if first is None and second is None:
        raise IllegalPlay("Both seats are empty.")
    _seat_at(room, a, second)
    _seat_at(room, b, first)
    room.ids[a], room.ids[b] = room.ids[b], room.ids[a]
    if room.host in (a, b):
        room.host = b if room.host == a else a
    room.ready = {b if s == a else a if s == b else s for s in room.ready}


def _remove_player(room: Room, seat: int, msg: dict) -> None:
    """Host-only lobby removal: the occupant of ``msg["seat"]`` leaves.

    The position becomes empty and nobody else moves; the removed socket is
    told and returns to the lobby on its next frame, and its resume token is
    replaced so it can never reclaim a seat of this room.
    """
    if seat != room.host:
        raise IllegalPlay("Only the host can remove players.")
    if room.game:
        raise IllegalPlay("Players are fixed once the game has started.")
    if room.resume is not None or room.evaluation is not None:
        raise IllegalPlay("Seats are fixed at this table.")
    target = msg.get("seat")
    if (type(target) is not int or not 0 <= target < 4
            or _occupant(room, target) is None):
        raise IllegalPlay("Invalid seat.")
    if target == seat:
        raise IllegalPlay("Use Leave to leave the room.")
    if "expect" in msg:
        _check_expected(room, target, msg["expect"])
    gone = room.seats[target]
    assert gone is not None
    _seat_at(room, target, None)
    room.ready.discard(target)
    gone.removed = True
    gone.token = secrets.token_urlsafe(12)
    if not gone.is_bot:
        enqueue(gone, {"type": "left", "reason": "removed",
                       "message": "The host removed you from the room."})
        chat_system(room, f"{gone.name} was removed by the host")


async def handle_action(room: Room, seat: int, msg: dict) -> None:
    """Caller holds room.lock. Raises IllegalPlay on bad input."""
    if room.evaluation is not None and room.evaluation_invalidated:
        raise IllegalPlay("Evaluation session was invalidated by logging failure.")
    t = msg.get("type")
    game, rnd = room.game, room.round

    if t == "chat":
        text = str(msg.get("text", "")).strip()[:CHAT_MAX_LEN]
        if not text:
            return
        room.log_event("chat", seat=seat, text=text, bot=False)
        chat_post(room, {"seat": seat, "name": room.seats[seat].name,
                         "text": text, "t": time.time()})
        return

    if t == "add_bot":
        free = _empty_position(room) if room.game is None else None
        if seat != room.host or free is None:
            raise IllegalPlay("Cannot add a bot now.")
        _seat_at(room, free, Seat(name=f"Bot {free}", is_bot=True))
    elif t == "remove_bot":
        last = room.seats[-1] if room.seats else None
        if seat != room.host or last is None or not last.is_bot:
            raise IllegalPlay("No bot to remove.")
        if room.game:
            raise IllegalPlay("Game already started.")
        _seat_at(room, len(room.seats) - 1, None)
    elif t == "swap_seats":
        _swap_seats(room, seat, msg)
    elif t == "remove_player":
        _remove_player(room, seat, msg)
    elif t == "allow_joiners":
        # Any person at a ranked table may switch it either way; a Join
        # already waiting for its trick goes ahead.
        if not room.matched or room.seats[seat].is_bot:
            raise IllegalPlay("Only a ranked table takes joiners.")
        room.allow_joiners = msg.get("on") is True
    elif t == "set_start_level":
        # Jerry 09-26: the selector lives in the room screen, not the lobby.
        # Host-only, and only while no game exists -- Game() reads the level
        # exactly once at start_game, so a change after that would be a lie
        # the HUD tells for the rest of the session.
        if seat != room.host:
            raise IllegalPlay("Only the host can set the starting level.")
        if room.game:
            raise IllegalPlay("The starting level is fixed once the game has started.")
        level = msg.get("start_level")
        if level not in RANKS:
            raise IllegalPlay("Unknown starting level.")
        room.start_level = level
    elif t == "set_ranked":
        # A created room's Ranked switch: host-only, lobby-only (start_game
        # fixes the mode for the game), and never on a queue room (always
        # ranked) or a test or evaluation room (never rated).
        if seat != room.host:
            raise IllegalPlay("Only the host can change Ranked.")
        if room.game:
            raise IllegalPlay("Ranked is fixed once the game has started.")
        if room.matched or not ratings.eligible(room):
            raise IllegalPlay("This room's mode can't be changed.")
        on = msg.get("on") is True
        if on and _same_device_humans(room):
            raise SameDevice("Two players here share one device; a ranked game "
                             "needs one device per player.")
        # A ranked room has the move timer, as a matched room does; Ranked
        # off gives the room back its own setting.
        if on and not room.ranked:
            room.casual_move_timer = room.move_timer
            room.move_timer = True
        elif not on and room.ranked:
            room.move_timer = bool(room.casual_move_timer)
            room.casual_move_timer = None
        room.ranked = on
    elif t == "start_game":
        if seat != room.host:
            raise IllegalPlay("Only the host can start.")
        if room.game:
            raise IllegalPlay("Game already started.")
        if (room.matched or room.ranked) and _same_device_humans(room):
            raise SameDevice("Two players here share one device; a ranked game "
                             "needs one device per player.")
        # A bot plays every seat nobody took, in that seat.
        room.seats = [sd if sd is not None else Seat(name=f"Bot {i}", is_bot=True)
                      for i, sd in enumerate([*room.seats, *[None] * (4 - len(room.seats))])]
        validate_human_evaluation_start(room)
        # games_to_win=None: a table keeps playing. Holding A scores a
        # point and the levels restart, rather than ending the session.
        room.game = Game(start_level=room.start_level, games_to_win=None)
        if room.resume is not None:
            # The engine reads a game's levels and banker only through these
            # two fields, so setting them before the first round starts the
            # table exactly where the saved game left off.
            room.game.level_idx = [RANKS.index(level) for level in room.resume["levels"]]
            room.game.banker = room.resume["banker"]
        ACTIVITY.games_started += 1
        room.game.start_round()
        room.index_round()
        _round_timeouts_reset(room)
        saved_games.start(room, _log_round_start(room), LOG_DIR)
        ratings.start(room)
        _spawn_room_task(room, "deal_task", run_deal(room))
        if room.watchdog_task is None or room.watchdog_task.done():
            room.watchdog_task = asyncio.create_task(watchdog(room))
    elif game is None or rnd is None:
        raise IllegalPlay("Game not started.")
    elif t == "im_back":
        # The player is back: the bot stops playing for the seat, and a
        # decision it owes now gets a fresh clock.
        sd = room.seats[seat]
        was_away = sd.away
        _player_moved(room, seat)
        if was_away and sd.turn_started is not None:
            sd.turn_started = now()
    elif t == "declare":
        codes = room.codes_for(seat, _card_ids(msg))
        rnd.declare(seat, codes)
        room.log_event("declare", seat=seat, cards=codes, bot=False)
        _player_moved(room, seat)
    elif t == "pass_declare":
        rnd.pass_declare(seat)
        _player_moved(room, seat)
    elif t == "bury":
        room.sync_kitty()
        ids = _card_ids(msg)
        codes = room.codes_for(seat, ids)
        rnd.bury(seat, codes)
        room.remove_ids(seat, ids)
        room.log_event("bury", seat=seat, cards=codes, bot=False)
        _player_moved(room, seat)
    elif t == "play":
        ids = _card_ids(msg)
        codes = room.codes_for(seat, ids)
        prev_last = rnd.last_trick
        rnd.play(seat, codes)
        # a failed throw may have played different (fewer) cards than sent;
        # the play landed either in the open trick or the just-closed one
        if rnd.trick and rnd.trick.plays:
            played = rnd.trick.plays[-1].cards
        else:
            assert rnd.last_trick is not None
            played = next(p.cards for p in rnd.last_trick.plays if p.seat == seat)
        if sorted(played) == sorted(codes):
            room.remove_ids(seat, ids)
        else:
            room.remove_codes(seat, played)
        _log_play(room, seat, played, False, prev_last)
        # a human's play is a committed play too: the room bot's ledger must see
        # the notice it posts (or replaces) before the bot's next turn
        _observe_committed_play(room)
        _player_moved(room, seat)
    elif t == "next_round":
        if rnd.phase != "round_end":
            raise IllegalPlay("Round not finished.")
        if game.game_over:
            raise IllegalPlay("Game is over.")
        # Wait for EVERY connected human to confirm, so nobody's review of
        # the round gets cut short by a faster clicker (Jerry, 2026-08-03).
        room.ready.add(seat)
        _player_moved(room, seat)
        if not await advance_if_all_ready(room):
            await broadcast(room)
    else:
        raise IllegalPlay(f"Unknown action: {t}")

    rnd = room.round
    if rnd and rnd.phase == "round_end" and room.game and room.game.result is None:
        room.game.finish_round()
        _log_round_end(room)


async def _resume_point(user_id: int | None, game_id: Any, options: dict) -> dict | None:
    """The ``create_room`` ``resume_from`` option: a saved game of the
    signed-in caller's own account, in an ordinary room. None refuses it
    (a guest, another account's game, an unknown id, no level data)."""
    if user_id is None or options or not isinstance(game_id, str):
        return None
    return await accounts.STORE.run(saved_games.resume_point, user_id, game_id)


# A guest's device key, ``?device=`` on the socket URL: a random 128-bit
# url-safe token the client keeps (22 base64url characters, or up to 64).
# It stays in memory; it is never logged, stored or sent to anyone.
DEVICE_KEY_RE = re.compile(r"[A-Za-z0-9_-]{22,64}")
# device key -> that guest's queue id: -1, -2, ... in order of first use, so
# a reconnect from the same device keeps its place, pair and cooldown.
GUEST_IDS: dict[str, int] = {}


def device_key(raw: Any) -> str | None:
    """The socket's device key, or None when absent or malformed."""
    return raw if isinstance(raw, str) and DEVICE_KEY_RE.fullmatch(raw) else None


def guest_queue_id(device: str) -> int:
    """The negative queue id of the guest on ``device``."""
    qid = GUEST_IDS.get(device)
    if qid is None:
        qid = GUEST_IDS[device] = -(len(GUEST_IDS) + 1)
    return qid


# --------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    if ws.query_params.get("heartbeat") == "1":
        await send(ws, {"type": "heartbeat_ready"})
    room: Room | None = None
    me: Seat | None = None  # seat OBJECT — indexes shift when lobby seats leave
    my_gen = 0              # connection generation this socket owns
    # Optional sign-in, read once from the handshake cookie (a guest has none).
    # It changes two things: the seat remembers the account, and a signed-in
    # player is always called by the account's current name (the display
    # name they chose, else their first name), whatever name the client sends.
    user = await accounts.websocket_user(ws)
    user_id = user["id"] if user else None
    default_name = accounts.effective_name(user) if user else ""

    def account_id() -> int | None:
        # A socket whose account was deleted while it stayed open reads as
        # signed out from then on.
        return None if user_id is None or accounts.is_deleted(user_id) else user_id

    def player_name(raw: Any) -> str:
        # ``conn.name`` is the account's current name: ``rename_user`` keeps
        # it up to date. A client-sent name is a guest's only.
        if account_id() is not None:
            return conn.name or "Player"
        return str(raw or "Player")

    device = device_key(ws.query_params.get("device"))
    guest_id = guest_queue_id(device) if user_id is None and device is not None else None

    def queue_id() -> int | None:
        # The queue's identity for this socket: the account, else the
        # device's guest id; None for a deleted account or a guest whose
        # client sent no device key, which the queue refuses.
        return account_id() if user_id is not None else guest_id

    conn = matchmaking.Conn(ws, user_id, default_name,
                            queue_id=user_id if user_id is not None else guest_id,
                            device=device)
    LIVE_CONNS.add(conn)
    # The same device's guest id, when this socket is signed in: the guest
    # signed in here. Its queue, waiting-table seat, pair and pending Join
    # end now (a matched seat moves over on rejoin by its resume token).
    signed_in_guest = (GUEST_IDS.get(device)
                       if user_id is not None and device is not None else None)
    if signed_in_guest is not None:
        old_conn = MATCHMAKER.conns.get(signed_in_guest)
        if old_conn is not None and old_conn.joining is not None:
            await end_pending_join(old_conn, penalty=False)
        MATCHMAKER.signed_in(signed_in_guest, user_id)
    MATCHMAKER.connect(conn)

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except RuntimeError:
                # starlette raises RuntimeError, not WebSocketDisconnect, when
                # the peer is already gone (#639). Scoped to the RECEIVE so a
                # RuntimeError from anything else in this loop still escapes,
                # and gated on whether a receive was legal at all -- not on the
                # message text, which would break silently on a reword.
                if _receive_is_legal(ws):
                    raise
                break
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if conn.adopted is not None:       # the queue seated this socket
                room, me, my_gen = conn.adopted
                conn.adopted = None
            if room is not None and room.aborted:
                room, me = None, None
            if me is not None and me.removed:
                # the host removed this seat: back to the lobby, no room
                _detach(me)
                room, me = None, None
                MATCHMAKER.return_to_lobby(conn)
            if me is not None and me.left_gen == my_gen:
                # the account left this seat from another of its sockets
                await send(ws, {"type": "left"})
                room, me = None, None
                MATCHMAKER.return_to_lobby(conn)
            if t == "ping":
                nonce = msg.get("nonce")
                if type(nonce) is int and 0 <= nonce <= 9007199254740991:
                    await send(ws, {"type": "pong", "nonce": nonce})
                continue
            if t == "code_lookup":
                await send(ws, MATCHMAKER.code_lookup(conn, msg, account_id()))
                continue
            if room is None or me is None:
                if t == "leave_room" and conn.joining is not None:
                    # Leave before the handover: the Join ends, with the
                    # join-then-leave cooldown, and the seat stays the bot's.
                    await end_pending_join(conn, penalty=True)
                    await send(ws, {"type": "left"})
                    continue
                if t in matchmaking.QUEUE_MESSAGES:
                    if account_id() is None and msg.get("name"):
                        # a guest is called in the queue what it typed
                        conn.name = str(msg["name"]).strip()[:accounts.DISPLAY_NAME_MAX]
                    await MATCHMAKER.handle(conn, msg, queue_id())
                    continue
                if t in ("create_room", "join_room"):
                    MATCHMAKER.enter_room(conn)
                try:
                    if t == "create_room":
                        try:
                            options = SHORTLIST_TEST_ROOMS.room_options(msg, rooms, LOG_DIR)
                        except TestRoomUnavailable as error:
                            await send(ws, {"type": "error", "code": "test_room_unavailable",
                                            "message": str(error)})
                            continue
                        # Absent means "the standard game"; PRESENT AND WRONG is
                        # refused rather than coerced, so a client sending a level
                        # this server does not know cannot silently get a game at
                        # rank 2 while its own UI claims otherwise.
                        start_level = msg.get("start_level")
                        if start_level is None:
                            start_level = RANKS[0]
                        elif start_level not in RANKS:
                            await send(ws, {"type": "error", "code": "bad_start_level",
                                            "message": "Unknown starting level."})
                            continue
                        resume = None
                        if "resume_from" in msg:
                            resume = await _resume_point(account_id(), msg.get("resume_from"), options)
                            if resume is None:
                                await send(ws, {"type": "error", "code": "resume_unavailable",
                                                "message": "That game can't be continued."})
                                continue
                        room = Room(code=new_code(), start_level=start_level, resume=resume, **options)
                        rooms[room.code] = room
                        ACTIVITY.rooms_created += 1
                        # Through _attach like every other path: hand-rolling the
                        # queue/writer here skipped the generation bump AND the
                        # resume token, so a creator had no identity and an
                        # overlapping refresh appended them as a SECOND seat.
                        me = Seat(name=player_name(msg.get("name")), user_id=account_id(),
                                  device=device)
                        if resume is None:
                            room.seats.append(me)
                        else:
                            # the creator back in their saved seat, a bot in each other
                            bots = iter(range(1, 4))
                            room.seats = [me if i == resume["seat"]
                                          else Seat(name=f"Bot {next(bots)}", is_bot=True)
                                          for i in range(4)]
                            room.host = resume["seat"]
                        my_gen = _attach(room, me, ws)
                        await broadcast(room)
                    elif t == "peek_room":
                        # Who is sitting where, WITHOUT joining — the lobby uses
                        # this to offer a seat picker for a game in progress.
                        target = rooms.get(str(msg.get("room", "")).upper())
                        if target is None:
                            await send(ws, {"type": "error", "code": "room_not_found",
                                            "message": "Room not found."})
                            continue
                        # A ranked table's invite: its open seats only, and
                        # whether there is none.
                        ranked_open = (_open_seats(target, invite=True)
                                       if target.matched else None)
                        await send(ws, {
                            "type": "room_seats",
                            "room": target.code,
                            "in_game": target.game is not None,
                            **({"ranked": True, "full": not ranked_open}
                               if target.matched else {}),
                            "seats": [{"seat": i, "name": sd.name,
                                       "is_bot": sd.is_bot,
                                       "connected": sd.connected,
                                       "team": i % 2,
                                       # What the lobby actually needs to know:
                                       # a dropped human's seat can be taken too.
                                       "claimable": (i in ranked_open
                                                     if ranked_open is not None
                                                     else sd.is_bot or (
                                           not sd.connected
                                           and not _reserved(target, i))),
                                       "reserved_secs": (_takeover_in(target, i)
                                                         if _reserved(target, i)
                                                         else None),
                                       "controller": ("bot" if sd.is_bot else
                                                      "human" if sd.connected
                                                      else "bot_cover")}
                                      for i, sd in enumerate(target.seats)
                                      if sd is not None],
                        })
                    elif t == "join_room":
                        # Per-JOIN, not per-socket: these were read back via
                        # locals(), so a player who claimed a bot seat in one room
                        # kept claimed_from_bot/took_from set and the NEXT room
                        # announced a stale bot's name.
                        claimed_from_bot = False
                        took_from = ""
                        took_over_human = False
                        code = str(msg.get("room", "")).upper()
                        target = rooms.get(code)
                        if target is None:
                            await send(ws, {"type": "error", "code": "room_not_found",
                                            "message": "Room not found."})
                            continue
                        tok = msg.get("token")
                        qid = queue_id()
                        # A guest comes back to a matched seat by its token
                        # alone; a guest who signed in on this device moves
                        # its seat over to the account the same way.
                        migrate = (_guest_seat_of(target, tok, signed_in_guest)
                                   if target.matched and account_id() is not None
                                   and signed_in_guest is not None else None)
                        if (target.matched and qid is not None
                                and not _holds_seat(target, qid)
                                and migrate is None
                                and not (account_id() is None
                                         and _token_seat(target, tok) is not None)):
                            # An invite link to a ranked table: the open-table
                            # path for that table (pending until the handover).
                            refused = await join_by_invite(
                                target, msg.get("seat"), qid,
                                player_name(msg.get("name")), conn)
                            if refused is not None:
                                await send(ws, {
                                    "type": "error", "code": refused,
                                    "message": INVITE_REFUSALS[refused],
                                    **({"cooldown_until": MATCHMAKER.cooldowns[qid]}
                                       if refused == "cooldown" else {})})
                            continue
                        async with target.lock:
                            name = player_name(msg.get("name"))
                            # At a ranked table a person only comes back to
                            # the seat they already hold: an account to its
                            # own seat (or to the guest seat it held on this
                            # device before signing in), a guest by its guest
                            # seat's token; never a guest to an account's
                            # seat (anyone else takes the invite path above).
                            held = None
                            if target.matched:
                                if account_id() is None:
                                    held = _guest_seat_of(target, tok)
                                else:
                                    held = next(
                                        (s for s in target.seats
                                         if s is not None and not s.is_bot
                                         and s.user_id == account_id()), None)
                                    if held is None:
                                        held = migrate
                                if held is None:
                                    await send(ws, {
                                        "type": "error", "code": "ranked_queue_only",
                                        "message": "Ranked games are joined through "
                                                   "the queue."})
                                    continue
                            # Match on a normalised name: an exact-only match
                            # locked people out of their own seat whenever they
                            # came back on another device or retyped their name
                            # with different capitalisation.
                            # Identity order: TOKEN first (the only real identity;
                            # it also lets a player resume while their stale socket
                            # is still open — the newest connection wins), then a
                            # normalised name among DISCONNECTED seats.
                            reclaim = _token_seat(target, tok)
                            if held is not None:
                                reclaim = held
                            by_name = False
                            if reclaim is None:
                                key = name.strip().casefold()
                                reclaim = next(
                                    (s for s in target.seats
                                     if s is not None and not s.is_bot
                                     and not s.connected
                                     and s.name.strip().casefold() == key),
                                    None)
                                by_name = reclaim is not None
                            if ((target.matched or target.ranked) and device is not None
                                    and _device_seated(target, device, reclaim)):
                                await send(ws, {"type": "error", "code": "same_device",
                                                "message": SAME_DEVICE_MESSAGE})
                                continue
                            if reclaim is not None:
                                me = reclaim
                                me.device = device
                                if target.matched:
                                    me.queue_id = qid
                                # The seat's account follows the socket that now
                                # owns it: a sign-in reconnect brings one, a
                                # sign-out reconnect (or a guest's by-name
                                # re-entry) brings none and clears it.
                                me.user_id = account_id()
                                if me.user_id is not None and me.name != name:
                                    _rename_seat(target, me, name)
                                saved_games.seat_changed(target, target.seats.index(me))
                            elif (target.game is None
                                  and (free := _empty_position(target)) is not None):
                                me = Seat(name=name, user_id=account_id(), device=device)
                                _seat_at(target, free, me)
                            else:
                                # Take over a BOT's seat, mid-game if need be —
                                # the hand already exists, so a late arrival can
                                # sit down without restarting.
                                # Safe under the room lock: pump_bots re-checks
                                # is_bot after every BOT_DELAY and exits cleanly
                                # when a seat stops being a bot.
                                want = msg.get("seat")
                                # Claimable = bot seats, plus seats whose human has
                                # dropped (a bot is covering those anyway). Without
                                # the second group a 4-human game with one player
                                # offline reported "room full" and NOBODY could
                                # take the seat — not even that player under a
                                # different name.
                                botseats = [i for i, sd in enumerate(target.seats)
                                            if sd.is_bot]
                                # A dropped seat is RESERVED for its owner during
                                # the grace window, so nobody can claim it the
                                # instant a player blips. After the window
                                # the bot is covering and the seat is open to all.
                                dropped = [i for i, sd in enumerate(target.seats)
                                           if not sd.is_bot and not sd.connected
                                           and not _reserved(target, i)]
                                claimable = botseats + dropped
                                if isinstance(want, bool) or not (
                                        want is None or isinstance(want, int)):
                                    want = None          # malformed: treat as "any"
                                if want is not None and want not in claimable:
                                    # Two people can pick the same seat between the
                                    # peek and the join. Silently seating the loser
                                    # somewhere else puts them on a team they did
                                    # not choose — refuse and let them re-pick.
                                    await send(ws, {
                                        "type": "error", "code": "seat_unavailable",
                                        "message": "That seat was just taken — "
                                                   "pick another."})
                                    continue
                                pick = want if want is not None else (
                                    botseats[0] if botseats else None)
                                if pick is None:
                                    reserved = [i for i, sd in enumerate(target.seats)
                                                if _reserved(target, i)]
                                    if reserved and not dropped:
                                        secs = max((_takeover_in(target, i) or 0)
                                                   for i in reserved)
                                        await send(ws, {
                                            "type": "error", "code": "seat_reserved",
                                            "message": f"A player just dropped — "
                                                       f"their seat is held for "
                                                       f"{secs:.0f}s in case they "
                                                       f"come back."})
                                    elif dropped:
                                        # Seats exist, but each belongs to someone
                                        # who may be reconnecting: make the caller
                                        # choose one deliberately.
                                        await send(ws, {
                                            "type": "error", "code": "choose_seat",
                                            "message": "Every seat is taken, but "
                                                       "a player is offline — pick "
                                                       "their seat to take over."})
                                    else:
                                        await send(ws, {
                                            "type": "error", "code": "room_full",
                                            "message": "Room is full — every seat "
                                                       "is taken by a human."})
                                    continue
                                me = target.seats[pick]
                                # Name whoever they replaced: "took Bot 1's seat"
                                # says WHICH seat far better than "a bot's seat".
                                took_from = me.name
                                took_over_human = not me.is_bot
                                me.bot_announced = False
                                _player_moved(target, pick)
                                me.timeouts_in_round = 0
                                # New owner => new identity. Keeping the old token
                                # would let the previous owner present it later and
                                # displace the person who took the seat.
                                me.token = secrets.token_urlsafe(12)
                                me.is_bot = False
                                me.name = name
                                me.user_id = account_id()
                                me.device = device
                                saved_games.seat_changed(target, pick)
                                target.log_event("seat_claimed", seat=pick,
                                                 name=name, bot=False)
                                claimed_from_bot = True
                            room = target
                            if by_name:
                                # HOUSE TRUST MODEL, stated plainly: a dropped
                                # seat can be re-entered by anyone who types that
                                # player's name. It is the same permission the
                                # seat picker already grants deliberately, so the
                                # name path grants no MORE access — but it must
                                # not hand over the original owner's token, or an
                                # impersonator could later displace the real owner.
                                me.token = secrets.token_urlsafe(12)
                            my_gen = _attach(room, me, ws)
                            if reclaim is not None:
                                _log_seat(room, "seat_reconnected", me,
                                          "name" if by_name
                                          else "account" if held is not None
                                          else "token")
                                chat_system(
                                    room,
                                    f"{name} reconnected"
                                    + (" — taking over from the bot"
                                       if me.bot_announced else ""))
                                me.bot_announced = False
                            elif claimed_from_bot:
                                chat_system(
                                    room,
                                    f"{name} took over for {took_from} (offline)"
                                    if took_over_human
                                    else f"{name} took {took_from}'s seat")
                            else:
                                chat_system(room, f"{name} joined")
                            kick_bots(room)      # remaining bot seats keep playing
                            await broadcast(room)
                    else:
                        await send(ws, {"type": "error", "message": "Join a room first."})
                finally:
                    # A failed create or join returns the socket to the lobby;
                    # a seat taken elsewhere ends its queue entry.
                    if t in ("create_room", "join_room"):
                        if conn.joining is not None:
                            pass       # an invite Join waits for its handover
                        elif room is None or me is None:
                            MATCHMAKER.return_to_lobby(conn)
                        else:
                            MATCHMAKER.leave_for_room(conn)
                continue

            # A socket that has been displaced by a newer connection owns
            # nothing: its leave_room previously detached the LIVE connection
            # and deleted the room, and it could still submit plays.
            # The one exception is the seat's own account pressing Leave on
            # a socket that another of its tabs or devices displaced by
            # resuming: that is still the person leaving, so the seat is
            # left, and the socket now holding it is sent back to the lobby.
            if (my_gen != me.gen and t == "leave_room" and account_id() is not None
                    and me.user_id == account_id() and me.connected):
                my_gen = me.left_gen = me.gen
            if my_gen != me.gen:
                await send(ws, {"type": "error", "code": "stale_connection",
                                "message": "This connection was replaced by a "
                                           "newer one."})
                break

            if t == "leave_room":
                async with room.lock:
                    chat_system(room, f"{me.name} left")
                    _log_seat(room, "seat_left", me, "leave")
                    if me in room.seats:
                        ratings.seat_left(room, room.seats.index(me))
                    # a newcomer leaving the round it joined mid-way: the
                    # seat is a bot's again, and the leave costs (rule in
                    # _joined_leave_penalty). At the round end that round is
                    # over, so leaving then is an ordinary between-rounds leave.
                    joined_leave = (room.game is not None and not room.game.game_over
                                    and me in room.seats and not me.is_bot
                                    and me.joined_round == room.game.round_no
                                    and room.round is not None
                                    and room.round.phase != "round_end")
                    leaver = (me.user_id, me.queue_id)
                    _detach(me, room, my_gen)
                    if joined_leave:
                        _revert_to_bot(room, room.seats.index(me))
                        _joined_leave_penalty(room, *leaver)
                        kick_bots(room)
                    if room.game is None:
                        # lobby: the seat empties and nobody else moves
                        if me in room.seats:
                            gone = room.seats.index(me)
                            _seat_at(room, gone, None)
                            room.ready.discard(gone)
                        humans = [i for i, x in enumerate(room.seats)
                                  if x is not None and not x.is_bot]
                        if not humans:
                            rooms.pop(room.code, None)
                        else:
                            if _occupant(room, room.host) is None:
                                room.host = humans[0]
                            await broadcast(room)
                    else:
                        # mid-game: seat stays (reclaimable); bots cover it.
                        # The last human leaving closes the room.
                        if not any(x.connected for x in room.seats
                                   if not x.is_bot):
                            _close_when_empty(room)
                        # Explicit leave must re-check the round-end quorum
                        # exactly like an abrupt disconnect: the last unready
                        # player LEAVING used to deadlock everyone else while
                        # the same player DROPPING advanced the round
                        # (Codex ship gate P0-4).
                        elif not await advance_if_all_ready(room):
                            await broadcast(room)
                await send(ws, {"type": "left"})
                room, me = None, None
                MATCHMAKER.return_to_lobby(conn)
                continue
            if t in matchmaking.QUEUE_MESSAGES:
                await MATCHMAKER.handle(conn, msg, queue_id())
                continue
            if t == "report_player":
                await _report_player(room, me, account_id(), msg)
                continue
            async with room.lock:
                try:
                    seat_idx = room.seats.index(me)
                except ValueError:  # seat vanished — shouldn't happen mid-game
                    room, me = None, None
                    MATCHMAKER.return_to_lobby(conn)
                    await send(ws, {"type": "error", "code": "room_not_found",
                                    "message": "Seat no longer exists."})
                    continue
                try:
                    await handle_action(room, seat_idx, msg)
                    await broadcast(room)
                    kick_bots(room)
                except SeatChanged as e:
                    enqueue(me, {"type": "error", "code": "seat_changed", "message": str(e)})
                except SameDevice as e:
                    enqueue(me, {"type": "error", "code": "same_device", "message": str(e)})
                except IllegalPlay as e:
                    if t == "play":
                        _log_play_refused(room, seat_idx, msg, e)
                    enqueue(me, {"type": "error", "message": str(e)})
                except Exception:  # malformed input must not kill the socket
                    enqueue(me, {"type": "error", "message": "Invalid request."})
    except WebSocketDisconnect:
        pass
    finally:
        if conn.adopted is not None:
            room, me, my_gen = conn.adopted
            conn.adopted = None
        if conn.joining is not None:
            # the newcomer's socket went before the handover: the Join ends
            await end_pending_join(conn, penalty=False)
        MATCHMAKER.disconnect(conn)
        if me is not None and me.removed:
            _detach(me)
        elif me is not None and me.left_gen == my_gen:
            pass                       # the account already left this seat
        elif room is not None and me is not None:
            async with room.lock:
                if not me.is_bot and me.connected:
                    chat_system(room, f"{me.name} disconnected")
                    if my_gen == me.gen:
                        _log_seat(room, "seat_disconnected", me, "socket_closed")
                _detach(me, room, my_gen)
                if not any(x.connected for x in room.seats
                           if x is not None and not x.is_bot):
                    if room.cleanup_task is None or room.cleanup_task.done():
                        room.cleanup_task = asyncio.create_task(cleanup_room(room))
                else:
                    if not await advance_if_all_ready(room):
                        await broadcast(room)



async def _report_player(room: Room, me: Seat, account: int | None, msg: dict) -> None:
    """Store a report on another seat and confirm it to the reporter only.
    The record is built under the room lock and written off the event loop;
    nothing about the report reaches the other seats or the room state."""
    async with room.lock:
        if me not in room.seats:
            return
        try:
            record = reports.build(room, room.seats.index(me), account, msg)
        except reports.ReportRefused as refused:
            enqueue(me, {"type": "error", "code": refused.code, "message": str(refused)})
            return
    try:
        await asyncio.get_running_loop().run_in_executor(None, reports.store, record)
    except OSError:
        enqueue(me, {"type": "error", "code": "report_not_stored",
                     "message": "The report could not be sent. Try again later."})
        return
    enqueue(me, {"type": "report_received", "seat": record["reported"]["seat"],
                 "message": f"Thanks. {record['reported']['name']} was reported for review."})


async def start_matched_room(match_id: str | None, slots: list,
                             conns: dict) -> str:
    """Build, seat and start the room for a waiting table (``match_id`` is
    the table's id) or an entry that starts alone with bots (``None``).
    Slots arrive in seat order; every
    human's socket is bound to its seat here, before anything awaits, so the
    socket's receive loop adopts the room on its next message.

    The start is all or nothing: if anything fails once the room is
    registered, the room is unregistered and aborted, every attached seat is
    detached and every socket is back in the lobby with no adoption pending,
    before the error reaches the matchmaker that requeues these players."""
    room = Room(code=new_code(), matched=True, move_timer=True, waiting_table=match_id,
                table_humans=sum(1 for slot in slots if slot.user_id is not None))
    rooms[room.code] = room
    attached: list[tuple[Seat, Any, int]] = []
    try:
        humans = []
        for i, slot in enumerate(slots):
            # ``slot.user_id`` is the queue id: negative for a guest
            if slot.user_id is None:
                room.seats.append(Seat(name=f"Bot {i}", is_bot=True))
            else:
                conn = conns[slot.user_id]
                seat = Seat(name=slot.name or "Player", user_id=_account_of(slot.user_id),
                            queue_id=slot.user_id, device=conn.device)
                room.seats.append(seat)
                humans.append((seat, conn))
        room.host = room.seats.index(humans[0][0])
        async with room.lock:
            for seat, conn in humans:
                gen = _attach(room, seat, conn.ws)
                attached.append((seat, conn, gen))
                conn.adopted = (room, seat, gen)
                MATCHMAKER.enter_room(conn)
                enqueue(seat, {"type": "match_started", "match_id": match_id,
                               "room": room.code, "rated": ratings.eligible(room),
                               **({"guest": True} if seat.user_id is None else {})})
            await broadcast(room)
            await handle_action(room, room.host, {"type": "start_game"})
            await broadcast(room)
            kick_bots(room)
    except BaseException:
        _unwind_matched_room(room, attached, conns.values())
        raise
    ACTIVITY.rooms_created += 1
    return room.code


def _unwind_matched_room(room: Room, attached: list, conns) -> None:
    room.aborted = True
    if room.game is not None:       # start_game ran: undo its durable effects
        ACTIVITY.games_started -= 1
        saved_games.abort(room)
        room.ratings = None
    if rooms.get(room.code) is room:
        del rooms[room.code]
    for task in (room.bot_task, room.deal_task, room.watchdog_task, room.cleanup_task):
        if task is not None:
            task.cancel()
    for seat, _conn, gen in attached:
        _detach(seat, room, gen)
    for conn in conns:
        if conn.adopted is not None and conn.adopted[0] is room:
            conn.adopted = None
        MATCHMAKER.return_to_lobby(conn)


# ---------------------------------------------------------- open tables
@dataclass
class PendingJoin:
    """A newcomer's Join of an open-table seat, waiting for its handover:
    the bot (or the away owner's bot) plays the seat until then. ``uid``
    is the newcomer's queue id (negative for a guest)."""
    uid: int
    name: str
    conn: Any                     # the newcomer's ``matchmaking.Conn``
    away: bool = False            # the seat is an away player's, not a bot's
    # A queued pair's two Joins share a group: they are seated together and
    # end together. ``confirmer`` is the account whose Join it was; only it
    # pays the join-then-leave cost for leaving before the handover.
    group: str | None = None
    confirmer: int | None = None


def _joinable(room: Room, invite: bool = False) -> bool:
    """A ranked game in play that takes joiners and still has a person
    connected at it. An invite link is the table's own consent, so it does
    not need Allow joiners."""
    game = room.game
    return (room.matched and not room.aborted and rooms.get(room.code) is room
            and (room.allow_joiners or invite) and room.evaluation is None
            and game is not None and room.round is not None and not game.game_over
            and any(sd is not None and not sd.is_bot and sd.connected for sd in room.seats))


def _away_offerable(room: Room, seat: int) -> bool:
    """A present player's seat that the bot has played for the whole
    previous round: offered from the round boundary on (at a round end the
    round just played is the previous one)."""
    sd, game = room.seats[seat], room.game
    if sd.is_bot or not sd.away or sd.away_since is None or game is None:
        return False
    boundary = game.round_no if room.round.phase == "round_end" else game.round_no - 1
    return sd.away_since <= boundary - 1


def _open_seats(room: Room, invite: bool = False) -> list[int]:
    """The seats a newcomer may take: bot seats, and away seats from the
    round boundary, none already claimed by a waiting Join."""
    if not _joinable(room, invite):
        return []
    return [i for i, sd in enumerate(room.seats)
            if i not in room.pending_joins and (sd.is_bot or _away_offerable(room, i))]


def open_tables() -> list[dict]:
    """Every open table as the matchmaker sees it: its code, whether it is
    at a round end (a newcomer then plays, ranked, from the next round), and
    the four seats with who holds them and which a newcomer may take."""
    out = []
    for room in list(rooms.values()):
        seats = _open_seats(room)
        if not seats:
            continue
        view = []
        for i, sd in enumerate(room.seats):
            pj = room.pending_joins.get(i)
            view.append({"name": pj.name if pj else sd.name,
                         "bot": sd.is_bot and pj is None,
                         "away": i in seats and not sd.is_bot,
                         "open": i in seats, "team": i % 2,
                         "queue_id": pj.uid if pj else sd.queue_id,
                         "device": pj.conn.device if pj else sd.device})
        out.append({"code": room.code, "seats": view,
                    "round_end": room.round.phase == "round_end"})
    return out


async def join_open_table(code: str, seat: int, uid: int, name: str, conn: Any) -> str | None:
    """A newcomer confirmed a seat: it is theirs, pending the handover at
    the next trick boundary (at once when the seat owes nothing). The first
    confirm wins; a later one for the same seat is ``seat_taken``."""
    room = rooms.get(code)
    if room is None:
        return "closed"
    async with room.lock:
        seats = _open_seats(room)
        if seat not in seats:
            return "seat_taken" if seats else "closed"
        if _holds_seat(room, uid):
            return "closed"
        if conn.device is not None and _device_seated(room, conn.device):
            return "same_device"
        await _claim_open_seat(room, seat, uid, name, conn)
    return None


def _holds_seat(room: Room, qid: int) -> bool:
    """Whether queue id ``qid`` holds a seat at the matched room, or a Join
    waiting for one."""
    return any(sd is not None and not sd.is_bot and sd.queue_id == qid
               for sd in room.seats) or any(
        pj.uid == qid for pj in room.pending_joins.values())


def _device_seated(room: Room, device: str, besides: Seat | None = None) -> bool:
    """Whether ``device`` already holds a human seat (other than
    ``besides``) at the room, or a Join waiting for one."""
    return any(sd is not None and sd is not besides and not sd.is_bot
               and sd.device == device for sd in room.seats) or any(
        pj.conn.device == device for pj in room.pending_joins.values())


def _token_seat(room: Room, tok: Any) -> Seat | None:
    """The human seat whose resume token is ``tok``."""
    if not isinstance(tok, str) or not tok:
        return None
    return next((s for s in room.seats if s is not None and not s.is_bot
                 and secrets.compare_digest(s.token, tok)), None)


def _guest_seat_of(room: Room, tok: Any, guest: int | None = None) -> Seat | None:
    """The guest-held seat whose resume token is ``tok`` (and, given
    ``guest``, that guest's queue id holds it); never an account's seat."""
    seat = _token_seat(room, tok)
    if (seat is None or seat.user_id is not None or seat.queue_id is None
            or seat.queue_id >= 0 or (guest is not None and seat.queue_id != guest)):
        return None
    return seat


def _same_device_humans(room: Room) -> bool:
    """Whether two human seats at the room share a device key."""
    devices = [sd.device for sd in room.seats
               if sd is not None and not sd.is_bot and sd.device is not None]
    return len(set(devices)) < len(devices)


def _account_of(qid: int | None) -> int | None:
    """The account id a queue id names; None for a guest's (negative) id."""
    return qid if qid is not None and qid > 0 else None


SAME_DEVICE_MESSAGE = "Someone on this device is already at that table."


async def _claim_open_seat(room: Room, seat: int, uid: int, name: str, conn: Any, *,
                           group: str | None = None, confirmer: int | None = None,
                           announce: bool = True) -> None:
    """The seat is the newcomer's, pending the handover (caller holds the
    lock and has checked the seat is open)."""
    room.pending_joins[seat] = PendingJoin(uid=uid, name=name or "Player", conn=conn,
                                           away=not room.seats[seat].is_bot, group=group,
                                           confirmer=uid if confirmer is None else confirmer)
    conn.joining = (room, seat)
    MATCHMAKER.enter_room(conn)
    conn.push({"type": "match_started", "match_id": None, "room": room.code,
               "rated": ratings.eligible(room), "joining": True, "seat": seat,
               **({"guest": True} if uid < 0 else {})})
    if announce:
        await broadcast(room)
        kick_bots(room)


async def join_pair_open_table(code: str, seats: list[int], uids: list[int], names: list[str],
                               conns: list[Any], confirmer: int) -> str | None:
    """A queued pair confirmed: both partner seats are theirs at once,
    pending one shared handover, or neither is."""
    room = rooms.get(code)
    if room is None:
        return "closed"
    async with room.lock:
        open_ = _open_seats(room)
        if (len(seats) != 2 or (seats[0] + 2) % 4 != seats[1]
                or not all(s in open_ for s in seats)):
            return "seat_taken" if open_ else "closed"
        if any(_holds_seat(room, u) for u in uids):
            return "closed"
        devices = [c.device for c in conns if c.device is not None]
        if len(set(devices)) < len(devices) or any(_device_seated(room, d) for d in devices):
            return "same_device"
        group = secrets.token_hex(6)
        for seat, uid, name, conn in zip(seats, uids, names, conns):
            await _claim_open_seat(room, seat, uid, name, conn, group=group,
                                   confirmer=confirmer, announce=False)
        await broadcast(room)
        kick_bots(room)
    return None


def _default_seat(room: Room, seats: list[int]) -> int:
    """The lone player's partner seat when it is open, else the first."""
    humans = [i for i, sd in enumerate(room.seats)
              if not sd.is_bot and i not in seats] + list(room.pending_joins)
    if len(humans) == 1 and (humans[0] + 2) % 4 in seats:
        return (humans[0] + 2) % 4
    return seats[0]


async def join_by_invite(room: Room, seat: Any, uid: int, name: str, conn: Any) -> str | None:
    """A friend (``uid`` is their queue id) opened a ranked table's invite
    link: the open-table path for that table (any open seat, the handover
    after the trick, the first round unranked), even with Allow joiners off.
    Returns a refusal code: ``cooldown``, ``table_left`` (they left this
    table after joining it), ``table_full``, ``seat_unavailable`` or
    ``same_device`` (this device already holds a seat there)."""
    if MATCHMAKER.cooldowns.get(uid, 0.0) > MATCHMAKER.clock():
        return "cooldown"
    if room.code in MATCHMAKER.barred.get(uid, ()):
        return "table_left"
    async with room.lock:
        seats = _open_seats(room, invite=True)
        if not seats or _holds_seat(room, uid):
            return "table_full"
        if isinstance(seat, bool) or not (seat is None or isinstance(seat, int)):
            seat = None
        if seat is None:
            seat = _default_seat(room, seats)
        if seat not in seats:
            return "seat_unavailable"
        if conn.device is not None and _device_seated(room, conn.device):
            return "same_device"
        MATCHMAKER.leave_for_room(conn)
        MATCHMAKER.invite_joining(uid, room.code)
        await _claim_open_seat(room, seat, uid, name, conn)
    return None


INVITE_REFUSALS = {
    "cooldown": "You left a table you joined. You can join again in 5 minutes.",
    "table_left": "You left this table, so you can't join it again.",
    "table_full": "Table is full.",
    "seat_unavailable": "That seat was just taken — pick another.",
    "same_device": SAME_DEVICE_MESSAGE,
}


def _join_due(room: Room, seat: int) -> bool:
    """Can the seat change hands now: at a round end, or a trick boundary,
    or whenever it owes nothing (dealing, declaring, someone else's bury,
    or it already played to this trick). Never mid-bury."""
    game, rnd = room.game, room.round
    if game is None or rnd is None or game.game_over:
        return False
    if rnd.phase == "bury":
        return rnd.turn != seat
    if rnd.phase == "play":
        trick = rnd.trick
        return trick is None or not trick.plays or any(p.seat == seat for p in trick.plays)
    return True


def _join_notices(room: Room) -> list[dict]:
    """The table's corner line: who takes a seat after this trick, and who
    was seated at this round end and plays from the next round."""
    out = [{"seat": i, "name": pj.name, "when": "trick"}
           for i, pj in sorted(room.pending_joins.items())]
    if room.round is not None and room.round.phase == "round_end":
        out += [{"seat": i, "name": n, "when": "round"}
                for i, n in sorted(room.round_end_joins.items())]
    return out


def _drop_join(room: Room, seat: int, *, back_in_line: bool, penalty: bool = False,
               reason: str | None = None, message: str | None = None) -> None:
    """End a Join before its handover (caller holds the lock). The newcomer
    is told when it did not ask, and is back in the lobby (and, with
    ``back_in_line``, at the front of the queue)."""
    pj = room.pending_joins.pop(seat)
    pj.conn.joining = None
    if reason is not None:
        pj.conn.push({"type": "left", "reason": reason, "message": message})
    MATCHMAKER.return_to_lobby(pj.conn)
    MATCHMAKER.join_ended(pj.uid, back_in_line=back_in_line, penalty=penalty)


async def end_pending_join(conn: Any, *, penalty: bool) -> None:
    """The newcomer on ``conn`` left (``penalty``) or lost its socket before
    the handover: its Join ends and the seat stays as it was. A pair's Join
    ends for both, and the leave costs only the member who confirmed."""
    if conn.joining is None:
        return
    jroom, jseat = conn.joining
    async with jroom.lock:
        pj = jroom.pending_joins.get(jseat)
        if pj is not None and pj.conn is conn:
            for seat in _join_group(jroom, jseat):
                if seat == jseat:
                    _drop_join(jroom, seat, back_in_line=False,
                               penalty=penalty and pj.confirmer == pj.uid)
                else:
                    _drop_join(jroom, seat, back_in_line=False, reason="partner_left",
                               message=f"{pj.name} left, so your join was cancelled.")
            await broadcast(jroom)
    conn.joining = None


def _join_group(room: Room, seat: int) -> list[int]:
    """The seats whose Joins stand or fall with this one's."""
    group = room.pending_joins[seat].group
    if group is None:
        return [seat]
    return sorted(s for s, pj in room.pending_joins.items() if pj.group == group)


def _settle_joins(room: Room) -> None:
    """Hand every waiting Join its seat when the seat can change hands, or
    drop it: the away owner came back first, the game ended, or the
    newcomer's socket went (caller holds the lock; ``broadcast`` runs it
    before every frame)."""
    for seat in sorted(room.pending_joins):
        if seat not in room.pending_joins:
            continue                   # settled with its pair
        group = _join_group(room, seat)
        gone = [s for s in group if room.pending_joins[s].conn.closed]
        reclaimed = [s for s in group if room.pending_joins[s].away
                     and (room.seats[s].is_bot or not room.seats[s].away)]
        if gone:
            who = room.pending_joins[gone[0]].name
            for s in group:
                if s in gone:
                    _drop_join(room, s, back_in_line=False)
                else:
                    _drop_join(room, s, back_in_line=False, reason="partner_left",
                               message=f"{who} left, so your join was cancelled.")
        elif reclaimed:
            owner = room.seats[reclaimed[0]].name
            for s in group:
                _drop_join(room, s, back_in_line=True, reason="reclaimed",
                           message=f"{owner} came back to the seat. You are back in the queue.")
        elif room.game is None or room.game.game_over or room.aborted:
            for s in group:
                _drop_join(room, s, back_in_line=True, reason="table_closed",
                           message="That game ended. You are back in the queue.")
        elif all(_join_due(room, s) for s in group):
            # a pair takes its two seats at the same boundary
            for s in group:
                _seat_newcomer(room, s, room.pending_joins[s])


def _seat_newcomer(room: Room, seat: int, pj: PendingJoin) -> None:
    """The handover: the newcomer holds the seat from here. A bot seat
    changes hands in place, as a mid-game claim does; an away player's seat
    gets a new Seat and its owner's socket is sent back to the lobby."""
    old = room.seats[seat]
    at_round_end = room.round.phase == "round_end"
    took = old.name
    if old.is_bot:
        me = old
        me.bot_name = old.name
    else:
        displaced_ws, owner = old.ws, old.queue_id
        _detach(old, room, old.gen)
        old.removed = True
        me = Seat(name=pj.name, bot_name=f"Bot {seat}")
        room.seats[seat] = me
        holder = MATCHMAKER._live(owner) if owner is not None else None
        if holder is not None and displaced_ws is not None and holder.ws is displaced_ws:
            holder.push({"type": "left", "reason": "seat_given",
                         "message": "You were away for a whole round, so a new player "
                                    "took your seat."})
    me.is_bot = False
    me.name = pj.name
    me.user_id = _account_of(pj.uid)
    me.queue_id = pj.uid
    me.device = pj.conn.device
    me.token = secrets.token_urlsafe(12)
    me.bot_announced = False
    me.away, me.away_since = False, None
    me.timeouts_in_row = me.timeouts_in_round = 0
    me.turn_started = None
    me.joined_round = None if at_round_end else room.game.round_no
    if at_round_end:
        room.round_end_joins[seat] = pj.name
    del room.pending_joins[seat]
    pj.conn.joining = None
    saved_games.seat_changed(room, seat)
    room.log_event("seat_claimed", seat=seat, name=pj.name, bot=False)
    gen = _attach(room, me, pj.conn.ws)
    pj.conn.adopted = (room, me, gen)
    MATCHMAKER.join_seated(pj.uid)
    chat_system(room, f"{pj.name} took {took}'s seat")


def _revert_to_bot(room: Room, seat: int) -> None:
    """A newcomer left during the round they joined: the seat is a bot's
    again (caller holds the lock and has detached the socket)."""
    sd = room.seats[seat]
    sd.is_bot = True
    sd.name = sd.bot_name or f"Bot {seat}"
    sd.user_id = None
    sd.queue_id = sd.device = None
    sd.token = secrets.token_urlsafe(12)
    sd.joined_round = None
    sd.away, sd.away_since = False, None
    sd.bot_announced = False
    sd.timeouts_in_row = sd.timeouts_in_round = 0
    sd.turn_started = None
    sd.left_at = None
    saved_games.seat_changed(room, seat)
    room.log_event("seat_claimed", seat=seat, name=sd.name, bot=True)


def _joined_leave_penalty(room: Room, uid: int | None, qid: int | None) -> None:
    """Leaving (or abandoning) the round one joined mid-way: the leaver cap
    moves to the account's (``uid``) next rated round, and for the account
    or guest (queue id ``qid``) a queue cooldown starts and this table is
    never offered again."""
    if uid is not None:
        ratings.carry_leaver_cap(uid)
    if qid is not None:
        MATCHMAKER.left_open_table(qid, room.code)


def _joined_round_ended(room: Room) -> None:
    """At the end of a round someone joined mid-way: a newcomer who went
    away or whose socket the bot took over abandoned it, as a leave would."""
    game = room.game
    if game is None:
        return
    for sd in room.seats:
        if (sd is not None and not sd.is_bot and sd.joined_round == game.round_no
                and (sd.away or (not sd.connected and sd.bot_announced))):
            _joined_leave_penalty(room, sd.user_id, sd.queue_id)


MATCHMAKER = matchmaking.Matchmaker(start_room=start_matched_room,
                                    room_live=lambda code: code in rooms,
                                    open_tables=open_tables,
                                    join_table=join_open_table,
                                    join_pair=join_pair_open_table)


def _attach(room: Room, seat: Seat, ws: WebSocket) -> int:
    """Bind a socket to a seat as ONE transition (caller holds the room lock).

    Membership used to be updated inline at each call site — connected flag,
    queue, writer, cleanup task, scrollback — and the paths drifted apart.
    That is how a dropped player's seat became unreachable while still looking
    occupied (Jerry, 2026-08-03) and why Codex asked for a single owner of the
    transition.
    """
    if room.cleanup_task is not None:
        room.cleanup_task.cancel()
        room.cleanup_task = None
    room.closing = False             # a human is back: the game goes on
    if seat.writer is not None:      # displace any older live socket
        seat.writer.cancel()
    seat.gen += 1
    seat.ws, seat.connected = ws, True
    seat.left_at = None
    seat.queue = asyncio.Queue(maxsize=128)
    seat.writer_error = None      # fresh socket, fresh writer
    seat.writer_exit = None
    _start_writer(seat, ws)
    enqueue(seat, {"type": "resume", "token": seat.token, "gen": seat.gen})
    enqueue(seat, chat_snapshot(room))   # one snapshot, before the first state
    return seat.gen


def _detach(seat: Seat, room: Room | None = None,
            gen: int | None = None) -> None:
    """Unbind a websocket from a seat (caller holds the room lock).

    Also drops the seat from the round-end quorum: a player who leaves must
    stop being waited on, or everyone else sits on a browser that is never
    coming back.
    """
    if gen is not None and gen != seat.gen:
        return                       # a newer socket owns this seat now
    if (room is not None and room.evaluation is not None
            and room.game is not None and not room.game.game_over
            and seat in room.seats
            and room.seats.index(seat) in HUMAN_SEATS
            and not room.evaluation_invalidated):
        # HUMAN-C1 cannot let selective dropout turn into bot-cover play or a
        # shorter favorable session.  The assignment is terminal as soon as a
        # bound participant leaves after the game starts.  Log only the seat
        # and a fixed reason; the immutable experiment context already carries
        # pseudonymous identity and raw names never enter this root.
        room.evaluation_invalidated = True
        try:
            room.log_event(
                "evaluation_invalidated", seat=room.seats.index(seat),
                reason="participant_disconnect", terminal=True,
            )
        except OSError:
            # log_event also marks the room invalid.  Socket cleanup must still
            # finish so neither takeover nor a stale connection can act.
            pass
    if room is not None and seat in room.seats:
        room.ready.discard(room.seats.index(seat))
    seat.ws, seat.connected = None, False
    seat.left_at = now()
    if seat.writer is not None:
        seat.writer.cancel()
    seat.writer, seat.queue = None, None
    try:                     # watchdog clock; unavailable off-loop (tests)
        seat.last_seen = asyncio.get_event_loop().time()
    except RuntimeError:
        pass


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "rooms": len(rooms),
            "bot": os.environ.get("SHENGJI_BOT", "mc"),
            # Whether the compiled hot-path engine actually ACTIVATED, not
            # merely whether the .so shipped. `fast.py` falls back silently, so
            # without this a mismatched or missing extension is invisible and
            # the server just runs ~3x slower for months (it did).
            "fast": _fast_active(),
            # The served policy prior (#435), or null: a deploy that binds a
            # prior must show its SHA256 here, and a rollback must show null.
            "prior": _prior_health(),
            "pv_search": _pv_search_health(),
            # Whether optional Google sign-in is configured (GOOGLE_CLIENT_ID).
            "accounts": accounts.health(),
            # Since this process started: rooms, games, records on disk and
            # record write failures, so a quiet week and a silent log failure
            # read differently without opening the volume.
            "activity": ACTIVITY.health()}


from .debug import register_debug  # noqa: E402

register_debug(app, rooms)
def detach_deleted_user(user_id: int) -> None:
    """``DELETE /api/me`` hook: every live seat held by the deleted account
    becomes a guest seat, and its open saved-game link is closed, so no later
    round or game links that id."""
    for room in list(rooms.values()):
        for index, seat in enumerate(room.seats):
            if seat is not None and seat.user_id == user_id:
                seat.user_id = None
                saved_games.seat_changed(room, index)


accounts.USER_DELETED_HOOKS.append(detach_deleted_user)

# Every open socket's queue view, so a rename reaches the sockets it was
# read into at the handshake.
LIVE_CONNS: "weakref.WeakSet[matchmaking.Conn]" = weakref.WeakSet()


def _rename_seat(room: Room, seat: Seat, name: str) -> None:
    seat.name = name
    if room.game is not None and room.evaluation is None and seat in room.seats:
        room.log_event("seat_renamed", seat=room.seats.index(seat), name=name)


async def _broadcast_locked(room: Room) -> None:
    async with room.lock:
        if rooms.get(room.code) is room and not room.aborted:
            await broadcast(room)


def rename_user(user_id: int, name: str) -> None:
    """``PATCH /api/me`` hook: the account's new effective name replaces the
    old one on its open sockets, in its pair and queue, and on every seat it
    holds or is about to take; each room it sits in is sent a fresh frame."""
    for conn in list(LIVE_CONNS):
        if conn.user_id == user_id:
            conn.name = name
    MATCHMAKER.renamed(user_id, name)
    for room in list(rooms.values()):
        changed = False
        for seat in room.seats:
            if (seat is not None and not seat.is_bot and seat.user_id == user_id
                    and seat.name != name):
                _rename_seat(room, seat, name)
                changed = True
        for pj in room.pending_joins.values():
            if pj.uid == user_id and pj.name != name:
                pj.name = name
                changed = True
        for index in list(room.round_end_joins):
            if room.seats[index].user_id == user_id:
                room.round_end_joins[index] = name
        if changed:
            task = asyncio.get_running_loop().create_task(_broadcast_locked(room))
            _RENAME_TASKS.add(task)
            task.add_done_callback(_RENAME_TASKS.discard)


_RENAME_TASKS: set[asyncio.Task] = set()
accounts.USER_RENAMED_HOOKS.append(rename_user)
# /api/auth/*, /api/me, /api/me/games: registered before the static mount so the catch-all
# page handler never shadows them.
accounts.register_accounts(app)
saved_games.register_saved_games(app)
ratings.register_ratings(app)

# ------------------------------------------------------------------ static
class WebFiles(StaticFiles):
    """The built page. Vite names every file under assets/ by its content
    hash, so those may be cached forever; everything else (index.html, the
    icons, the og/ preview) keeps its name across deploys, so a browser
    re-checks it each load and picks up a new deploy at once instead of
    holding the old page, which points at the old assets."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


dist = Path(__file__).resolve().parents[3] / "web" / "dist"
support.register_support(app, dist)
if dist.is_dir():
    app.mount("/", WebFiles(directory=dist, html=True), name="web")


def main() -> None:
    import uvicorn
    uvicorn.run("shengji.api.server:app", host="0.0.0.0", port=8000)
